"""A stand-in Music Assistant wired to the virtual room.

The fake answers the same calls as the real adapter, but instead of streaming
to hardware it records *when* each mute landed and later renders exactly what a
microphone in the room would have picked up. That makes the end-to-end test
drive the real orchestration code — the round schedule, the guard chirps, the
apply-and-verify pass — against audio it has to genuinely measure.

Sessions run on a virtual clock, so a 30-second calibration completes in
milliseconds without any of the timing logic being stubbed out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from urllib.parse import parse_qs, urlparse

import numpy as np

from sim.virtual_room import Round, RoomConfig, VirtualSpeaker, render_recording
from speaker_sync.dsp.signals import exponential_sweep
from speaker_sync.ma.backend import SENDSPIN_PROVIDER, PlayerInfo


class VirtualClock:
    """A clock that only moves when someone waits on it."""

    def __init__(self) -> None:
        self.now = 0.0

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class _MuteEvent:
    at: float
    player_id: str
    muted: bool


@dataclass
class FakeMusicAssistant:
    """Implements :class:`speaker_sync.ma.backend.SpeakerBackend` over the room."""

    speakers: list[VirtualSpeaker]
    clock: VirtualClock = field(default_factory=VirtualClock)
    config: RoomConfig = field(default_factory=RoomConfig)
    provider: str = SENDSPIN_PROVIDER
    reload_seconds: float = 0.0
    """How long a ``sync_adjust`` write takes to come back, as the real one
    reloads the player."""

    extra_players: list[PlayerInfo] = field(default_factory=list)
    """Players Music Assistant reports but that make no sound of their own —
    sync groups, protocol anchors. They are listed and never rendered, which
    is exactly how a real server presents them."""

    _mutes: list[_MuteEvent] = field(default_factory=list, init=False)
    _muted_now: dict[str, bool] = field(default_factory=dict, init=False)
    played_urls: list[str] = field(default_factory=list, init=False)
    _commanded_mute: dict[str, bool] = field(default_factory=dict, init=False)
    _playback_started: float | None = field(default=None, init=False)
    _playing: bool = field(default=False, init=False)
    _stream_to: set[str] = field(default_factory=set, init=False)
    ungroupable: set[str] = field(default_factory=set)
    """Speakers Music Assistant will not put in a group, by player id.

    Real hardware does this — a speaker bridged through its own provider can
    refuse to sync with the rest — and the symptom is silence in that speaker's
    round rather than an error, so it is worth being able to reproduce.
    """

    ignores_mute: set[str] = field(default_factory=set)
    """Speakers where the mute command changes nothing at all — not the
    reported state, not the audio. Music Assistant has a per-player setting for
    how it may mute, and it can be switched off entirely."""

    mute_is_cosmetic: set[str] = field(default_factory=set)
    """Speakers that report themselves muted and keep playing anyway.

    The nastier of the two, and the real one: playing the track as an
    announcement made Music Assistant override mute to be sure the
    announcement was heard, so the state read back correctly while the speaker
    sounded through every round.
    """

    delay_range_ms: tuple[int, int] | None = None
    """What the delay setting accepts, and what it refuses.

    ``None`` is Music Assistant's own symmetric ``sync_adjust``. A Sendspin
    player instead carries ``static_delay_ms`` at ``(0, 5000)``: advance-only,
    and the server rejects anything outside it rather than clamping.
    """

    wander_ms: dict[str, tuple[float, ...]] = field(default_factory=dict)
    """Extra latency per playback, cycling: a speaker whose delay is not the
    same from one stream start to the next, as a client with unreliable
    timing behaves. ``{"bt": (0, 40)}`` adds nothing the first time, 40 ms the
    second, nothing the third."""

    dropouts: dict[str, set[int]] = field(default_factory=dict)
    """Playbacks (counted from 1) in which a speaker makes no sound at all."""

    plays: int = field(default=0, init=False)
    """How many times playback has started."""

    no_delay: set[str] = field(default_factory=set)
    """Speakers that offer no delay setting at all — a phone app that
    compensates its own output latency, say. They still play, mute and group;
    a write to one is refused, as the real server refuses a key it lacks."""

    ignores_delay: set[str] = field(default_factory=set)
    """Speakers whose client takes a new delay, reports it back, and plays on
    with the old one — as a client would that only applies it on reconnect.
    Every number then looks right and the sound is unchanged."""

    _reported_adjust: dict[str, int] = field(default_factory=dict, init=False)

    delay_key: str = "sync_adjust"
    """The config key the delay goes by, which decides whether its direction
    is specified (``sendspin_static_delay``) or has to be probed."""

    report_mute_state: bool = True
    report_group_state: bool = True
    """Whether this server tells anyone who is in the group.

    Not every provider does, and the session has to cope with being told
    nothing rather than treating silence as a refusal.
    """

    groups: dict[str, list[str]] = field(default_factory=dict)
    """Who leads which group: leader id to its members, the leader first.

    Public so a test can start from a system that was already grouped before
    the session, which is what the session has to put back afterwards.
    """

    volumes: dict[str, int] = field(default_factory=dict)
    """Each speaker's volume, 50 unless set."""

    writes: list[tuple[str, int]] = field(default_factory=list, init=False)
    """Every ``sync_adjust`` write, in order — asserted on by tests."""

    log: list[tuple] = field(default_factory=list, init=False)
    """Every command in the order it arrived.

    Timestamps cannot show ordering here: the virtual clock only advances when
    someone sleeps, so two calls either side of a race read as simultaneous.
    Sequence is the only way to pin down what has to happen before what.
    """

    def __post_init__(self) -> None:
        for speaker in self.speakers:
            self._muted_now[speaker.player_id] = False

    # ------------------------------------------------------------------ port

    async def list_players(self) -> list[PlayerInfo]:
        return [
            PlayerInfo(
                player_id=s.player_id,
                name=s.name,
                provider=self.provider,
                available=True,
                muted=self._reported_mute(s.player_id) if self.report_mute_state else None,
                volume_level=self.volumes.get(s.player_id, 50),
                sync_adjust_ms=(
                    0
                    if s.player_id in self.no_delay
                    else self._reported_adjust.get(s.player_id, s.sync_adjust_ms)
                ),
                sync_adjust_key=None if s.player_id in self.no_delay else self.delay_key,
                delay_range_ms=None if s.player_id in self.no_delay else self.delay_range_ms,
                can_mute=s.player_id not in self.ignores_mute,
                # The leader carries the membership and each member names its
                # leader, which is how Music Assistant reports a sync group.
                group_members=(
                    tuple(self.groups.get(s.player_id, ())) if self.report_group_state else ()
                ),
                synced_to=self.synced_to(s.player_id) if self.report_group_state else None,
            )
            for s in self.speakers
        ] + list(self.extra_players)

    def synced_to(self, player_id: str) -> str | None:
        """The leader this speaker follows, or ``None``."""
        return next(
            (
                leader
                for leader, members in self.groups.items()
                if player_id in members and player_id != leader
            ),
            None,
        )

    def is_grouped(self, player_id: str) -> bool:
        """Whether the speaker is part of any group, as leader or member."""
        return any(player_id in members for members in self.groups.values())

    async def set_sync_adjust(self, player_id: str, milliseconds: int) -> None:
        if player_id in self.no_delay:
            raise RuntimeError(f"player {player_id} has no delay setting to write")
        if self.delay_range_ms is not None:
            low, high = self.delay_range_ms
            if not low <= milliseconds <= high:
                # Refused, not clamped — which is how the real one behaves.
                raise ValueError(
                    f"static_delay_ms must be in range {low}-{high}, got {milliseconds}"
                )
        self.writes.append((player_id, milliseconds))
        if player_id in self.ignores_delay:
            self._reported_adjust[player_id] = milliseconds
            return
        self.speakers = [
            s.with_adjust(milliseconds) if s.player_id == player_id else s for s in self.speakers
        ]
        if self.reload_seconds:
            await self.clock.sleep(self.reload_seconds)

    async def set_muted(self, player_id: str, muted: bool) -> None:
        self.log.append(("mute", player_id, muted))
        # Accepted and ignored, which is what makes this failure so quiet.
        if player_id in self.ignores_mute:
            return

        self._commanded_mute[player_id] = muted
        if player_id in self.mute_is_cosmetic:
            return  # the state moves, the sound does not
        if self._muted_now.get(player_id) == muted:
            return
        self._muted_now[player_id] = muted
        self._mutes.append(_MuteEvent(self.clock.now, player_id, muted))

    def _reported_mute(self, player_id: str) -> bool:
        """What the server *says*, which is not always what the room hears."""
        if player_id in self.mute_is_cosmetic:
            return self._commanded_mute.get(player_id, False)
        return self._muted_now.get(player_id, False)

    async def set_group(self, leader_id: str, member_ids: list[str]) -> None:
        self.log.append(("group", leader_id, tuple(member_ids)))
        # Music Assistant redirects grouping on a player that follows another
        # to that player's leader ("Redirecting set_members from X to its group
        # player"): the new members join the old group, not this one.
        followed = self.synced_to(leader_id)
        if followed is not None:
            leader_id = followed
        # A refusal is silent, exactly as it is on real hardware: the command
        # succeeds and the speaker simply is not in the group afterwards.
        joining = [m for m in member_ids if m != leader_id and m not in self.ungroupable]
        # A speaker belongs to one group at a time; joining this one takes it
        # out of whichever it was in.
        for member in [leader_id, *joining]:
            self._leave(member, keep_leading=member == leader_id)
        current = self.groups.get(leader_id, [leader_id])
        self.groups[leader_id] = [*current, *[m for m in joining if m not in current]]

    async def ungroup(self, player_id: str) -> None:
        self.log.append(("ungroup", player_id))
        self._leave(player_id)

    async def set_volume(self, player_id: str, volume_level: int) -> None:
        self.log.append(("volume", player_id, volume_level))
        self.volumes[player_id] = volume_level

    def _leave(self, player_id: str, *, keep_leading: bool = False) -> None:
        """Take a speaker out of its group; a leader leaving dissolves it."""
        if player_id in self.groups and not keep_leading:
            del self.groups[player_id]
        for leader, members in list(self.groups.items()):
            if leader != player_id and player_id in members:
                members.remove(player_id)
            if len(self.groups.get(leader, ())) <= 1:
                self.groups.pop(leader, None)

    async def play_url(self, player_id: str, url: str) -> None:
        self.log.append(("play", player_id))
        self.played_urls.append(url)
        rate = parse_qs(urlparse(url).query).get("rate")
        self.config = RoomConfig(
            **{**self.config.__dict__, "track_rate": int(rate[0]) if rate else None}
        )
        self._playback_started = self.clock.now
        self.plays += 1
        # The stream goes to the group the player leads, and to nobody else.
        self._stream_to = set(self.groups.get(player_id, [player_id]))
        self._playing = True

    async def stop(self, player_id: str) -> None:
        # The start time is deliberately kept: the recording is rendered after
        # playback stops, and it is what the mute timeline is rebased against.
        self._playing = False

    # ------------------------------------------------------------ microphone

    def start_recording(self) -> None:
        self._mutes = [
            _MuteEvent(self.clock.now, player_id, muted)
            for player_id, muted in self._muted_now.items()
        ]

    def render_recording(self, chirp_count: int) -> tuple[np.ndarray, int]:
        """Render what the microphone heard, from the mute timeline."""
        if self._playback_started is None:
            raise RuntimeError("render_recording called before play_url")

        config = RoomConfig(**{**self.config.__dict__, "chirp_count": chirp_count})
        rounds = self._rounds(config, chirp_count)
        # A speaker outside the group never receives the stream, so it is
        # silent no matter what its mute state says.
        audible = [
            self._as_this_time(s)
            for s in self.speakers
            if s.player_id not in self.ungroupable
            and (not self._stream_to or s.player_id in self._stream_to)
            and self.plays not in self.dropouts.get(s.player_id, set())
        ]
        recording = render_recording(audible, rounds, config)
        return recording, config.mic_sample_rate

    def _as_this_time(self, speaker: VirtualSpeaker) -> VirtualSpeaker:
        """The speaker with this playback's share of its wandering applied."""
        wander = self.wander_ms.get(speaker.player_id)
        if not wander:
            return speaker
        extra = wander[(self.plays - 1) % len(wander)]
        return replace(speaker, hardware_latency_ms=speaker.hardware_latency_ms + extra)

    def reference_chirp(self, sample_rate: int | None = None) -> np.ndarray:
        cfg = self.config
        return exponential_sweep(
            f_start=cfg.f_start,
            f_end=cfg.f_end,
            duration=cfg.chirp_seconds,
            sample_rate=sample_rate or cfg.mic_sample_rate,
        )

    def _rounds(self, config: RoomConfig, chirp_count: int) -> list[Round]:
        """Collapse the mute timeline into intervals of constant audibility.

        Times are rebased onto the stream's own timeline, since that is what
        the room schedules chirps against.
        """
        start = self._playback_started or 0.0
        end = chirp_count * config.period_seconds

        moments = sorted({0.0, *(max(e.at - start, 0.0) for e in self._mutes)})
        rounds: list[Round] = []
        for index, moment in enumerate(moments):
            stop = moments[index + 1] if index + 1 < len(moments) else end
            if stop <= moment:
                continue
            rounds.append(Round(moment, stop, self._audible_at(moment + start)))
        return rounds

    def _audible_at(self, absolute_time: float) -> frozenset[str]:
        state = {s.player_id: False for s in self.speakers}
        for event in self._mutes:
            if event.at <= absolute_time:
                state[event.player_id] = event.muted
        return frozenset(pid for pid, muted in state.items() if not muted)


class SimulatedRecorder:
    """Stands in for the browser holding the microphone.

    The real recorder streams PCM from a phone; this one renders the same
    thing from the room once the session has finished walking the mute
    schedule, so the orchestration under test is identical either way.
    """

    def __init__(self, server: FakeMusicAssistant) -> None:
        self._server = server
        self._chirp_count = 0

    async def start(self, signal) -> None:
        self._chirp_count = signal.chirp_count
        self._server.start_recording()

    async def stop(self) -> tuple[np.ndarray, int]:
        return self._server.render_recording(self._chirp_count)


def mixed_speakers() -> list[VirtualSpeaker]:
    """The setup the project exists to fix: three very different speakers."""
    return [
        VirtualSpeaker("esp32", "Кухня (ESP32)", hardware_latency_ms=20.0, distance_m=2.0),
        VirtualSpeaker("avr", "Гостиная (ресивер)", hardware_latency_ms=80.0, distance_m=4.0),
        VirtualSpeaker("bt", "Спальня (Bluetooth)", hardware_latency_ms=220.0, distance_m=3.0),
    ]
