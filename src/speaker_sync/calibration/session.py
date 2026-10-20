"""Driving a calibration session end to end.

One acoustic pass looks like this: put every speaker in one group, start the
microphone, start the track, and walk the mute state forward one round at a
time so exactly one speaker is audible during each stretch of chirps. Then
detect, analyse, solve, write the corrections back, and measure again to prove
the result rather than assert it.

The verification pass is not decoration. It is what catches a wrong sign
convention, a player that ignored the write, and a room that moved between
passes — all failures that would otherwise leave the user with a confident
report and worse sound than before.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

import numpy as np

from speaker_sync.calibration.measure import (
    SILENT,
    TOGETHER,
    MeasurementAnalysis,
    RoundPlan,
    analyze,
    plan_rounds,
    total_chirps,
)
from speaker_sync.calibration.solver import (
    CalibrationSolution,
    PlayerMeasurement,
    solve,
)
from speaker_sync.calibration.together import TogetherCheck, check_together
from speaker_sync.dsp.detect import analytic_correlation, detect_arrivals
from speaker_sync.dsp.signals import (
    DEFAULT_CHIRP_SECONDS,
    DEFAULT_F_END,
    DEFAULT_F_START,
    DEFAULT_PERIOD_SECONDS,
    DEFAULT_SAMPLE_RATE,
    TestSignal,
    build_test_signal,
)
from speaker_sync.i18n import say
from speaker_sync.ma.backend import PlayerInfo, SpeakerBackend

logger = logging.getLogger("speaker_sync.session")

Sleeper = Callable[[float], Awaitable[None]]

ProgressCallback = Callable[[dict], None]
"""Notified as the session advances, so the UI can show which speaker is
playing rather than a spinner for half a minute."""

SignalUrl = "str | Callable[[TestSignal], str]"
"""Where the media server should fetch the test track.

Accepts a callable because the track's length depends on how many speakers are
being calibrated: the URL can then carry the parameters and stay stateless,
rather than the web layer having to stash the current signal somewhere the
audio route can find it."""


def _resolve_url(signal_url, signal: TestSignal) -> str:
    return signal_url(signal) if callable(signal_url) else signal_url


def _clock_for(sleep: Sleeper) -> Callable[[], float]:
    """The clock that ``sleep`` advances: a simulator's own, or real time.

    The round schedule subtracts the time its commands took. That time has to
    be read off the clock the waiting happens on — the simulator's virtual
    clock moves only when something waits on it.
    """
    owner = getattr(sleep, "__self__", None)
    if owner is not None and hasattr(owner, "now"):
        return lambda: float(owner.now)
    return time.monotonic


def _report(progress: ProgressCallback | None, **event) -> None:
    if progress is not None:
        progress(event)


class Recorder(Protocol):
    """Whatever is holding the microphone — a browser, or the simulator."""

    async def start(self, signal: TestSignal) -> None: ...

    async def stop(self) -> tuple[np.ndarray, int]:
        """Return the recording and its sample rate."""


@dataclass(frozen=True)
class SessionConfig:
    chirps_per_round: int = 5
    """Chirps each speaker gets, before the guard is deducted.

    This is the session's main trade-off. The default leaves three readings
    per speaker: enough for the median to shrug off a single bad one, and a
    ~26 s pass for three speakers. Raising it buys margin in two places at
    once — the median gets harder to move, and the outlier check in
    :mod:`speaker_sync.calibration.measure` gets more evidence to notice a glitch
    with — at a directly proportional cost in session length, doubled because
    the run is measured and then verified.
    """

    guard_chirps: int = 2
    """Chirps discarded at the start of each round.

    They absorb the delay between issuing a mute and it taking effect, which
    is the only place network latency touches the measurement. At the default
    settings this leaves about 2.25 seconds of slack.
    """
    period_seconds: float = DEFAULT_PERIOD_SECONDS
    chirp_seconds: float = DEFAULT_CHIRP_SECONDS
    f_start: float = DEFAULT_F_START
    f_end: float = DEFAULT_F_END
    track_sample_rate: int = DEFAULT_SAMPLE_RATE
    settle_seconds: float = 0.35
    """Pause after a mute change before the round's chirps start counting."""

    align_to_first_chirp: bool = True
    """Time the rounds from the first chirp the microphone hears.

    The stream starts well after the play command — set-up, then every
    client fills its buffer — and a schedule counted from the command
    switched speakers early enough to cut the last chirp of a round, which
    then measured a few milliseconds off. Anchored on what is heard, every
    switch lands in the middle of the pause between two chirps.
    """

    first_chirp_timeout: float = 10.0
    """How long to wait for the first chirp before calling it unheard."""

    measure_passes: int = 2
    """Measurements taken before anything is corrected, combined by median.

    One pass trusts one moment. Two show whether the speakers arrive the same
    way twice, which is the difference between a speaker with a latency and a
    speaker whose latency wanders — and the second kind cannot be corrected
    with a fixed number at all. It costs one pass of time.
    """

    max_measure_passes: int = 3

    silence_round: bool = True
    """End every pass with a round in which every speaker is muted.

    A speaker that reports itself muted and plays on is heard in every other
    speaker's round; the measurement takes the first arrival it hears, so
    the others then "measure" like that speaker and the result looks
    plausible. The silent round is the one place such a leak cannot hide.
    """
    """Ceiling when the passes disagree or a speaker went unheard in one."""

    refine: bool = True
    """Correct again when the verification lands short of aligned.

    Only when every speaker moved as asked and arrived steadily: a speaker
    that ignores its writes gets nowhere with a second one, and one whose
    delay wanders would only be chased around by it.
    """

    max_refinements: int = 2
    """Corrections after the first, at most. A client that applies a share of
    each write closes the gap by that share every time — 90 % leaves 10 %,
    then 1 % — so two are enough for anything that counts as taking it."""

    def build_signal(self, chirp_count: int) -> TestSignal:
        return build_test_signal(
            chirp_count=chirp_count,
            period_seconds=self.period_seconds,
            chirp_seconds=self.chirp_seconds,
            f_start=self.f_start,
            f_end=self.f_end,
            sample_rate=self.track_sample_rate,
        )


@dataclass(frozen=True)
class MeasurementPass:
    analysis: MeasurementAnalysis
    rounds: tuple[RoundPlan, ...]
    signal: TestSignal
    sample_rate: int
    together: TogetherCheck | None = None
    """How the speakers lined up with all of them playing, when the pass
    ended with such a round."""

    @property
    def latencies_ms(self) -> dict[str, float]:
        return {pid: r.latency_ms for pid, r in self.analysis.readings.items()}

    def relative_spread_ms(self) -> float:
        values = list(self.latencies_ms.values())
        return max(values) - min(values) if len(values) >= 2 else 0.0


@dataclass(frozen=True)
class CalibrationReport:
    before: MeasurementPass
    solution: CalibrationSolution
    after: MeasurementPass | None = None
    applied: tuple[tuple[str, int], ...] = ()
    sign: int = 1
    """The convention the corrections were finally written under."""

    observed_sign: int | None = None
    """What the verification pass showed a positive ``sync_adjust`` doing.

    ``None`` when the run produced no evidence either way. When it is set, it
    is worth more than any assumption and worth remembering: establishing it
    otherwise costs two dedicated measurement passes.
    """

    problems: tuple[str, ...] = field(default=())

    suspect: bool = False
    """The measurement itself is in doubt — a muted speaker played on, or the
    listener heard something else than a round claimed. Nothing was written,
    and the result must not be saved as a position either: applying it later
    would write what the run itself refused to."""

    verifications: dict[str, "PlayerVerification"] = field(default_factory=dict)
    """Per speaker, how far it moved against how far it was asked to.

    Empty when there was no verification pass. The anchor the movements are
    measured against has no entry of its own."""

    @property
    def improved(self) -> bool:
        if self.after is None:
            return False
        return self.after.relative_spread_ms() < self.before.relative_spread_ms()

    @property
    def spread_before_ms(self) -> float:
        return self.before.relative_spread_ms()

    @property
    def spread_after_ms(self) -> float | None:
        return self.after.relative_spread_ms() if self.after else None

    @property
    def together(self) -> TogetherCheck | None:
        return self.after.together if self.after else None


def session_players(players: Iterable[PlayerInfo]) -> list[PlayerInfo]:
    """The players a session measures, adjustable ones first.

    References — players without a delay setting — take part, but never lead:
    the leader carries the stream for everyone, and the typical reference is
    a phone app that leaves, and takes its group with it, when the app is
    closed.
    """
    measurable = [p for p in players if p.is_measurable]
    return [p for p in measurable if not p.is_reference] + [
        p for p in measurable if p.is_reference
    ]


def _need_two(players: Sequence[PlayerInfo]) -> None:
    if len(players) < 2:
        raise ValueError(
            say(
                en="need at least two speakers that make a sound and can be muted",
                ru="нужно хотя бы две колонки, которые звучат и умеют заглушаться",
            )
        )


LEAK_MATCH_MS = 3.0
"""How close a leak's arrival must be to a speaker's reading to name it."""


def leak_problems(
    passes: Sequence[MeasurementPass], players: Sequence[PlayerInfo], *, wrote: bool
) -> list[str]:
    """Say so when the muted round was not silent, and who it sounded like."""
    leaked = [pass_ for pass_ in passes if pass_.analysis.silence_heard_ms]
    if not leaked:
        return []
    names = {p.player_id: p.name for p in players}
    candidates: list[str] = []
    for pass_ in leaked:
        heard = float(np.median(pass_.analysis.silence_heard_ms))
        for pid, latency in pass_.latencies_ms.items():
            if abs(latency - heard) <= LEAK_MATCH_MS and pid not in candidates:
                candidates.append(pid)
    who = ", ".join(f"«{names.get(pid, pid)}»" for pid in candidates)
    if who:
        like_en, like_ru = f", arriving like {who}", f", и он приходил как {who}"
    else:
        like_en = like_ru = ""
    return [
        say(
            en="in the round in which every speaker was muted, the microphone still heard the "
            f"test sound{like_en}. A speaker does not fall silent when muted — Music Assistant "
            "reports it muted, but it plays on — so it was heard in the other speakers' rounds "
            "too, and their readings are partly its own. "
            + ("" if wrote else "Nothing was written. ")
            + "Run “Speaker test” to find out by ear which one it is, then check its mute in "
            "Music Assistant or in its app, or switch it off here.",
            ru="в круге, где все колонки были заглушены, микрофон всё равно слышал тестовый "
            f"звук{like_ru}. Какая-то колонка не замолкает при заглушении — Music Assistant "
            "считает её заглушённой, а она играет дальше, — поэтому её было слышно и в кругах "
            "других колонок, и их отсчёты отчасти её. "
            + ("" if wrote else "Ничего не записано. ")
            + "Запустите «Проверку колонок», чтобы на слух найти, какая это, затем проверьте "
            "её заглушение в Music Assistant или в её приложении, или выключите её здесь.",
        )
    ]


def flagged_by_listener(recorder: Recorder) -> list[str]:
    """Rounds the person holding the phone said did not sound right, by player.

    The page offers "that's right" / "I hear something else" while each round
    plays. A human ear is the one check that knows which speaker is actually
    sounding, so a "something else" outweighs any number the analysis found.
    """
    feedback = getattr(recorder, "human_feedback", None) or []
    return list(dict.fromkeys(f["player_id"] for f in feedback if not f.get("ok")))


def listener_problems(flagged: Sequence[str], names: dict[str, str], *, wrote: bool) -> list[str]:
    problems = []
    for player_id in flagged:
        name = (
            say(en="every speaker together", ru="все колонки вместе")
            if player_id == TOGETHER
            else f"«{names.get(player_id, player_id)}»"
        )
        problems.append(
            say(
                en=f"you reported that the round of {name} did not sound as it should. "
                + (
                    ""
                    if wrote
                    else "Nothing was written, because a round that was not what it claimed "
                    "makes every reading suspect. "
                )
                + "Usually a speaker did not fall silent when muted, or never played — check "
                "the mute control of the speakers in Music Assistant, then measure again.",
                ru=f"вы отметили, что круг {name} звучал не так, как должен. "
                + (
                    ""
                    if wrote
                    else "Ничего не записано: если круг был не тем, за что себя выдавал, "
                    "под подозрением все отсчёты. "
                )
                + "Обычно колонка не замолкала при заглушении или вовсе не играла — проверьте "
                "в Music Assistant управление заглушением колонок и измерьте снова.",
            )
        )
    return problems


def solution_problems(solution: CalibrationSolution) -> list[str]:
    """What the solver could not do, in words — about references, mostly."""
    problems: list[str] = []
    references = solution.references
    if solution.reference_late_ms is not None and references:
        names = ", ".join(f"«{c.name}»" for c in references)
        late = solution.reference_late_ms
        problems.append(
            say(
                en=f"{names} arrives {late:.0f} ms after the latest point the other speakers "
                "can be moved to. Their delay setting can only make a speaker play earlier, "
                "never later, so this cannot be corrected from the server — nothing was "
                "written. Likely causes: the app's own latency compensation does not cover "
                "the whole path (a Bluetooth speaker on the phone adds 100–250 ms the app may "
                "not know about), or extra buffering over Wi-Fi. Remedies: set an output "
                "latency offset in the app if it has one, use the phone's own speaker or a "
                "cable instead of Bluetooth, or switch it off here to align the others among "
                "themselves.",
                ru=f"{names} приходит на {late:.0f} мс позже самой поздней точки, куда можно "
                "сдвинуть остальные колонки. Их настройка задержки умеет только ускорять "
                "колонку, но не задерживать, поэтому с сервера это не исправить — ничего не "
                "записано. Вероятные причины: собственная компенсация задержки приложения "
                "учитывает не весь путь (Bluetooth-колонка у телефона добавляет 100–250 мс, о "
                "которых приложение может не знать) или лишняя буферизация по Wi-Fi. Что "
                "делать: задать в приложении поправку задержки выхода, если она есть, играть "
                "через динамик телефона или по кабелю вместо Bluetooth, или выключить её "
                "здесь, чтобы выровнять остальные между собой.",
            )
        )
    if len(references) > 1 and solution.reference_disagreement_ms > AUDIBLE_SPREAD_MS:
        names = ", ".join(f"«{c.name}»" for c in references)
        apart = solution.reference_disagreement_ms
        problems.append(
            say(
                en=f"the references {names} arrive {apart:.1f} ms apart and cannot all be "
                "met; the other speakers were aimed halfway between them. To align exactly "
                "to one of them, switch the others off here.",
                ru=f"опорные колонки {names} расходятся на {apart:.1f} мс, и попасть во все "
                "сразу нельзя; остальные колонки нацелены посередине. Чтобы выровнять точно "
                "по одной из них, выключите здесь остальные.",
            )
        )
    for correction in solution.clamped_players:
        problems.append(
            say(
                en=f"«{correction.name}» cannot be moved far enough: its setting ends at "
                f"{correction.target_adjust_ms} ms, so it stays "
                f"{abs(correction.residual_error_ms):.1f} ms off.",
                ru=f"«{correction.name}» нельзя сдвинуть достаточно: её настройка "
                f"заканчивается на {correction.target_adjust_ms} мс, и она остаётся в "
                f"{abs(correction.residual_error_ms):.1f} мс от цели.",
            )
        )
    return problems


async def measure_once(
    backend: SpeakerBackend,
    recorder: Recorder,
    players: Sequence[PlayerInfo],
    *,
    reference_id: str | None = None,
    config: SessionConfig | None = None,
    signal_url="",
    sleep: Sleeper = asyncio.sleep,
    progress: ProgressCallback | None = None,
    together: bool = False,
) -> MeasurementPass:
    """Run one acoustic pass and return a latency per speaker.

    ``together`` ends the pass with every speaker audible at once and checks
    that round against the solo ones.
    """
    cfg = config or SessionConfig()
    if len(players) < 2:
        raise ValueError("need at least two players to calibrate")

    player_ids = [p.player_id for p in players]
    reference = reference_id or player_ids[0]
    rounds = plan_rounds(
        reference,
        player_ids,
        chirps_per_round=cfg.chirps_per_round,
        together=together,
        silent=cfg.silence_round,
    )
    signal = cfg.build_signal(total_chirps(rounds))

    leader = player_ids[0]
    await release_from_other_groups(backend, player_ids, leader)
    await backend.set_group(leader, player_ids)
    await confirm_group(backend, leader, player_ids, sleep=sleep)

    # Open the first round's speaker *before* the track starts, not after.
    #
    # Unmuting it afterwards races the stream, and losing that race is not
    # worth a reading — it is worth the whole measurement. The analysis has no
    # other way to find the track's origin than to treat the first chirp it
    # hears as chirp zero, so opening chirps lost to a late unmute slide every
    # round onto the wrong speaker. The result still looks like a result:
    # speakers "measure" each other's arrival times and come out suspiciously
    # aligned.
    # Both directions are checked, and both matter: a speaker that cannot be
    # muted plays through every other speaker's round, and one that cannot be
    # unmuted never sounds at all.
    for player_id in player_ids:
        await backend.set_muted(player_id, True)
    await confirm_mute(backend, dict.fromkeys(player_ids, True), sleep=sleep)

    opening = rounds[0].player_id
    await backend.set_muted(opening, False)
    await confirm_mute(backend, {opening: False}, sleep=sleep)

    await recorder.start(signal)
    audible: str | None = opening
    # The rounds follow the track's own timetable. Sleeping a round's length
    # after each round's mute commands would add every command's latency to
    # every later round boundary, and with enough speakers on a slow server
    # the boundaries slide past the guard chirps onto the wrong speaker.
    clock = _clock_for(sleep)
    spent = 0.0
    due = cfg.settle_seconds
    # Set once the first chirp has been heard: when it reached the microphone.
    origin: float | None = None

    try:
        await backend.play_url(leader, _resolve_url(signal_url, signal))
        first_chirp = getattr(recorder, "first_chirp", None)
        if cfg.align_to_first_chirp and first_chirp is not None:
            started = clock()
            try:
                ago = await first_chirp(cfg.first_chirp_timeout)
            except TimeoutError:
                raise RuntimeError(_unheard_message(players, rounds[0].player_id)) from None
            if ago is not None:
                origin = clock() - ago
            else:
                spent += clock() - started
        gap = max(0.0, cfg.period_seconds - cfg.chirp_seconds)
        for index, plan in enumerate(rounds):
            if origin is not None and index > 0:
                # Halfway through the pause before this round's first chirp:
                # the last chirp of the round before has ended, this one's
                # first has not begun.
                switch = origin + plan.first_chirp * cfg.period_seconds - gap / 2
                await sleep(max(0.0, switch - clock()))
            began = clock()
            if plan.is_silent:
                for player_id in player_ids if audible is None else [audible]:
                    await backend.set_muted(player_id, True)
                audible = SILENT
            elif plan.is_together:
                for player_id in player_ids:
                    if player_id != audible:
                        await backend.set_muted(player_id, False)
                audible = None
            elif plan.player_id != audible:
                if audible is not None:
                    await backend.set_muted(audible, True)
                await backend.set_muted(plan.player_id, False)
                audible = plan.player_id

            _report(
                progress,
                stage="round",
                round=index + 1,
                rounds=len(rounds),
                player_id=plan.player_id,
            )

            if origin is not None:
                continue
            # Without anything heard to time against: the first round also
            # absorbs the stream's start-up delay, as far as settle covers it.
            spent += clock() - began
            due += cfg.chirps_per_round * cfg.period_seconds
            wait = max(0.0, due - spent)
            await sleep(wait)
            spent += wait
        if origin is not None:
            # Until the last chirp has rung out.
            end = origin + total_chirps(rounds) * cfg.period_seconds
            await sleep(max(0.0, end - clock()))
    finally:
        # Each step on its own: a recorder that is gone — the browser was
        # closed — must not leave every speaker stopped mid-track and muted.
        # The recorder's own failure still ends the pass, after the rest.
        recorder_error: BaseException | None = None
        with contextlib.suppress(Exception):
            await backend.stop(leader)
        try:
            recording, sample_rate = await recorder.stop()
        except Exception as error:  # noqa: BLE001 - re-raised below
            recorder_error = error
        for player_id in player_ids:
            with contextlib.suppress(Exception):
                await backend.set_muted(player_id, False)
        if recorder_error is not None:
            raise recorder_error

    _report(progress, stage="analyzing")

    arrivals = detect_arrivals(
        recording,
        signal.reference(sample_rate),
        period_samples=cfg.period_seconds * sample_rate,
        sample_rate=sample_rate,
        f_start=cfg.f_start,
        f_end=cfg.f_end,
    )
    analysis = analyze(arrivals, rounds, sample_rate=sample_rate, guard_chirps=cfg.guard_chirps)
    _log_pass(analysis, players, aligned=origin is not None)

    check = None
    if together:
        check = check_together(
            analytic_correlation(
                recording,
                signal.reference(sample_rate),
                sample_rate=sample_rate,
                f_start=cfg.f_start,
                f_end=cfg.f_end,
            ),
            arrivals,
            rounds,
            analysis,
            period_samples=cfg.period_seconds * sample_rate,
            sample_rate=sample_rate,
            guard_chirps=cfg.guard_chirps,
        )

    return MeasurementPass(
        analysis=analysis,
        rounds=tuple(rounds),
        signal=signal,
        sample_rate=sample_rate,
        together=check,
    )


def _unheard_message(players: Sequence[PlayerInfo], opening: str) -> str:
    name = next((p.name for p in players if p.player_id == opening), opening)
    return say(
        en=f"the microphone heard no test sound after «{name}» started — so the rounds "
        "could not be timed, and nothing was measured. Check that «{name}» plays, that the "
        "page may use the microphone, and the level with “Test”.".replace("{name}", name),
        ru=f"после запуска «{name}» микрофон не услышал тестового звука — круги не удалось "
        "привязать ко времени, ничего не измерено. Проверьте, что «{name}» играет, что "
        "странице разрешён микрофон, и уровень кнопкой «Проверить».".replace("{name}", name),
    )


def _log_pass(analysis, players: Sequence[PlayerInfo], *, aligned: bool) -> None:
    """One line per pass in the add-on log: what was measured, and how sure.

    The page shows the result; the log keeps the evidence behind it, so a
    puzzling run can be looked into afterwards.
    """
    names = {p.player_id: p.name for p in players}
    readings = ", ".join(
        f"{names.get(pid, pid)} {r.latency_ms:.1f} ms ±{r.spread_ms:.2f} ({r.arrivals_used})"
        for pid, r in analysis.readings.items()
    )
    silence = (
        ", ".join(f"{v:.1f}" for v in analysis.silence_heard_ms)
        if analysis.silence_heard_ms
        else "nothing"
    )
    logger.info(
        "pass (%s): %s; drift %.2f ms; silent round heard %s; %d problem(s)",
        "timed by first chirp" if aligned else "timed by command",
        readings or "no readings",
        analysis.drift_ms,
        silence,
        len(analysis.problems),
    )
    for problem in analysis.problems:
        logger.info("  %s", problem)


STABILITY_TOLERANCE_MS = 1.5
"""How far one speaker's arrival may differ between passes and still count as
the same arrival. Readings within one pass agree to a tenth of a millisecond,
so anything near this is the speaker moving, not the measurement."""


@dataclass(frozen=True)
class CombinedPasses:
    """Several measurement passes folded into one, and how well they agreed."""

    pass_: MeasurementPass
    """The first pass, carrying the per-speaker median in its own time base."""

    variation_ms: dict[str, float]
    """Per speaker, how far its arrival moved between passes."""

    missing: tuple[str, ...]
    """Speakers that went unheard in at least one pass."""

    passes: tuple[MeasurementPass, ...] = ()
    """Every pass that went into it."""

    def unstable(self, tolerance: float = STABILITY_TOLERANCE_MS) -> dict[str, float]:
        return {pid: v for pid, v in self.variation_ms.items() if v > tolerance}


def combine_passes(passes: Sequence[MeasurementPass], order: Sequence[str]) -> CombinedPasses:
    """Fold repeated passes into one reading per speaker.

    Each pass has its own arbitrary origin, so speakers are compared against
    an anchor speaker present in every pass. The anchor is chosen as the one
    that makes the others vary least: should the anchor itself be the speaker
    that wanders, every other speaker would appear to wander instead, and the
    report would name the wrong ones.
    """
    first = passes[0]
    missing = tuple(
        pid for pid in order if any(pid not in p.latencies_ms for p in passes)
    )
    candidates = [pid for pid in order if all(pid in p.latencies_ms for p in passes)]
    if len(passes) == 1 or not candidates:
        return CombinedPasses(first, {}, missing, tuple(passes))

    def relative(anchor: str) -> dict[str, list[float]]:
        values: dict[str, list[float]] = {}
        for pass_ in passes:
            base = pass_.latencies_ms[anchor]
            for pid, latency in pass_.latencies_ms.items():
                values.setdefault(pid, []).append(latency - base)
        return values

    def total_variation(anchor: str) -> float:
        return sum(max(v) - min(v) for v in relative(anchor).values())

    anchor = min(candidates, key=total_variation)
    values = relative(anchor)
    origin = first.latencies_ms[anchor]

    readings = {}
    for pid in order:
        if pid not in values:
            continue
        template = next(p.analysis.readings[pid] for p in passes if pid in p.analysis.readings)
        readings[pid] = replace(
            template,
            latency_ms=origin + float(np.median(values[pid])),
            spread_ms=max(
                p.analysis.readings[pid].spread_ms for p in passes if pid in p.analysis.readings
            ),
            arrivals_used=sum(
                p.analysis.readings[pid].arrivals_used
                for p in passes
                if pid in p.analysis.readings
            ),
        )
    problems = tuple(dict.fromkeys(pr for p in passes for pr in p.analysis.problems))
    combined = replace(first, analysis=replace(first.analysis, readings=readings, problems=problems))
    variation = {pid: max(v) - min(v) for pid, v in values.items() if len(v) > 1}
    # The anchor varies by definition not at all against itself; it is as
    # stable as the least stable of the rest allows it to look.
    return CombinedPasses(combined, variation, missing, tuple(passes))


def stability_problems(
    combined: CombinedPasses,
    names: dict[str, str],
    *,
    tolerance: float = STABILITY_TOLERANCE_MS,
) -> list[str]:
    unstable = combined.unstable(tolerance)
    if not unstable:
        return []
    if len(unstable) == len(combined.variation_ms) - 1 and len(combined.variation_ms) == 2:
        # Two speakers: the offset between them moved, and nothing says which.
        a, b = combined.variation_ms
        value = max(unstable.values())
        return [
            say(
                en=f"«{names.get(a, a)}» and «{names.get(b, b)}» were {value:.1f} ms further "
                "apart in one measurement than in another. One of them does not play at a "
                "steady delay, so no fixed correction can hold; the median was used. With a "
                "third speaker the measurement can tell which one it is.",
                ru=f"«{names.get(a, a)}» и «{names.get(b, b)}» в одном замере разошлись на "
                f"{value:.1f} мс больше, чем в другом. Одна из них играет с плавающей "
                "задержкой, и никакая постоянная поправка не удержится; взята медиана. С "
                "третьей колонкой замер сможет сказать, какая именно.",
            )
        ]
    return [
        say(
            en=f"«{names.get(pid, pid)}» arrived {value:.1f} ms differently from one "
            "measurement to the next. Its delay is not steady, so no fixed correction can hold "
            "for it; the median was used. Typical causes: a playback client with unreliable "
            "timing (an old client version, an audio driver with variable buffering) or "
            "Wi-Fi dropouts. “Check without changes” a few times in a row shows whether it "
            "keeps moving.",
            ru=f"«{names.get(pid, pid)}» от замера к замеру приходила по-разному, на "
            f"{value:.1f} мс. Её задержка непостоянна, и постоянная поправка не удержится; "
            "взята медиана. Обычные причины: клиент воспроизведения с ненадёжным таймингом "
            "(старая версия, аудиодрайвер с плавающей буферизацией) или провалы Wi-Fi. "
            "Несколько «Проверок без изменений» подряд покажут, продолжает ли она гулять.",
        )
        for pid, value in unstable.items()
    ]


async def measure_repeatedly(
    backend: SpeakerBackend,
    recorder: Recorder,
    players: Sequence[PlayerInfo],
    *,
    config: SessionConfig,
    reference_id: str | None = None,
    signal_url="",
    sleep: Sleeper = asyncio.sleep,
    progress: ProgressCallback | None = None,
) -> CombinedPasses:
    """Measure until two passes agree, up to the configured ceiling.

    A speaker unheard in a pass, or passes that disagree, earn one more pass;
    the result is the per-speaker median of all of them.
    """
    order = [p.player_id for p in players]
    passes: list[MeasurementPass] = []
    wanted = max(1, config.measure_passes)
    ceiling = max(wanted, config.max_measure_passes)
    combined = None
    while len(passes) < ceiling:
        _report(
            progress,
            stage="pass",
            which="before",
            attempt=len(passes) + 1,
            planned=wanted,
            players=len(players),
        )
        passes.append(
            await measure_once(
                backend,
                recorder,
                players,
                reference_id=reference_id,
                config=config,
                signal_url=signal_url,
                sleep=sleep,
                progress=progress,
            )
        )
        if len(passes) < wanted:
            continue
        combined = combine_passes(passes, order)
        if not combined.missing and not combined.unstable():
            break
        wanted = len(passes) + 1
    assert combined is not None
    return combined


GROUP_CONFIRM_TIMEOUT_SECONDS = 4.0
GROUP_POLL_SECONDS = 0.5
MUTE_CONFIRM_TIMEOUT_SECONDS = 4.0


async def confirm_mute(
    backend: SpeakerBackend,
    wanted: dict[str, bool],
    *,
    sleep: Sleeper = asyncio.sleep,
    timeout: float = MUTE_CONFIRM_TIMEOUT_SECONDS,
) -> None:
    """Check the speakers really went quiet before playing anything.

    Muting is what makes a round a solo, and Music Assistant has a per-player
    setting for how — or whether — it can mute at all. A speaker that ignores
    the command plays straight through everyone else's rounds, and the damage
    is not a missing reading: every round then measures the speaker that would
    not shut up, so the speakers come out looking perfectly aligned.

    As with grouping, silence about the state is not a failure. A provider that
    never reports its mute state cannot be checked, and refusing to measure on
    that basis would ground a working setup.
    """
    deadline = timeout
    while True:
        players = {p.player_id: p for p in await backend.list_players()}
        stuck = [
            player_id
            for player_id, muted in wanted.items()
            if player_id in players
            and players[player_id].muted is not None
            and players[player_id].muted != muted
        ]
        if not stuck:
            return
        if deadline <= 0:
            names = ", ".join(f"«{players[pid].name}»" for pid in stuck)
            raise RuntimeError(
                say(
                    en=f"these speakers did not respond to the mute command: {names}. "
                    "The measurement needs exactly one speaker playing in each round, "
                    "otherwise every round measures the same one. Check the mute_control "
                    "setting of these speakers in Music Assistant.",
                    ru=f"эти колонки не отреагировали на команду заглушить: {names}. "
                    "Замер требует, чтобы в каждом круге звучала ровно одна колонка, "
                    "иначе все круги измерят одну и ту же. Проверьте в Music Assistant "
                    "настройку mute_control у этих колонок.",
                )
            )

        await sleep(GROUP_POLL_SECONDS)
        deadline -= GROUP_POLL_SECONDS


async def release_from_other_groups(
    backend: SpeakerBackend, player_ids: Sequence[str], leader: str
) -> None:
    """Take the session's players out of any group that is not the session's.

    Grouping a player that follows another leader is not refused, it is
    *redirected*: Music Assistant adds the new members to the group the
    player is already in. A speaker still in a sync group from the last song
    therefore took the session's group with it, and the track then played on
    that speaker alone. What is released here comes back afterwards with the
    rest of the players' state.
    """
    ids = set(player_ids)
    players = {p.player_id: p for p in await backend.list_players()}
    for player_id in player_ids:
        player = players.get(player_id)
        if player is None:
            continue
        follows_another = player.synced_to is not None and player.synced_to != leader
        if player_id == leader:
            follows_another = player.synced_to is not None
        leads_others = any(m not in ids for m in player.group_members if m != player_id)
        if follows_another or leads_others or player.active_group:
            await backend.ungroup(player_id)


async def confirm_group(
    backend: SpeakerBackend,
    leader: str,
    player_ids: Sequence[str],
    *,
    sleep: Sleeper = asyncio.sleep,
    timeout: float = GROUP_CONFIRM_TIMEOUT_SECONDS,
) -> None:
    """Check the speakers really joined the group before playing anything.

    The whole method rests on one stream reaching every speaker at once: that
    common stream is what gives the rounds a shared time base. A speaker that
    silently failed to join is not a degraded measurement, it is no measurement
    — it renders as silence, and the only symptom is "no usable chirps", which
    reads like a microphone problem and sends the user hunting in the room.

    Missing information is not treated as failure. A provider that never
    populates ``group_members`` would otherwise ground a setup that works, so
    the check needs positive evidence of exclusion before it refuses.
    """
    deadline = timeout
    while True:
        players = {p.player_id: p for p in await backend.list_players()}
        grouped = set(players[leader].group_members) if leader in players else set()
        # A member naming another leader, or the leader itself following
        # someone, is positive evidence even when the leader lists nobody.
        elsewhere = [
            pid
            for pid in player_ids
            if pid in players
            and players[pid].synced_to is not None
            and (pid == leader or players[pid].synced_to != leader)
        ]
        if not grouped and not elsewhere:
            return  # nothing reported: no evidence either way

        missing = [
            pid
            for pid in player_ids
            if pid in elsewhere or (grouped and pid != leader and pid not in grouped)
        ]
        if not missing:
            return
        if deadline <= 0:
            raise RuntimeError(_group_failure_message(players, leader, missing))

        # Grouping is a command, not a transaction; the state follows it.
        await sleep(GROUP_POLL_SECONDS)
        deadline -= GROUP_POLL_SECONDS


def _group_failure_message(players: dict, leader: str, missing: Sequence[str]) -> str:
    def describe(player_id: str) -> str:
        player = players.get(player_id)
        return player.name if player else player_id

    names = ", ".join(describe(pid) for pid in missing)
    lines = [
        say(
            en=f"these speakers did not join a group with «{describe(leader)}», "
            f"so they will not hear the test track: {names}.",
            ru=f"эти колонки не встали в одну группу с «{describe(leader)}», "
            f"поэтому они не услышат тестовый трек: {names}.",
        ),
        say(
            en="The measurement compares arrival times of one and the same stream, so "
            "a speaker outside the group cannot be measured.",
            ru="Замер сравнивает время прихода одного и того же потока, так что "
            "колонка вне группы измерена быть не может.",
        ),
    ]

    leader_player = players.get(leader)
    for player_id in missing:
        player = players.get(player_id)
        if player is None or leader_player is None:
            continue
        if not player.can_group_with_player(leader_player):
            lines.append(
                say(
                    en=f"Music Assistant does not group «{player.name}» with "
                    f"«{leader_player.name}» — their providers are incompatible; "
                    "switch one of them off.",
                    ru=f"Music Assistant не объединяет «{player.name}» с «{leader_player.name}» — "
                    "их провайдеры несовместимы; выключите одну из них.",
                )
            )
    return " ".join(lines)


def build_measurements(
    pass_: MeasurementPass, players: Sequence[PlayerInfo]
) -> list[PlayerMeasurement]:
    """Join acoustic readings with the corrections that were in force."""
    by_id = {p.player_id: p for p in players}
    return [
        PlayerMeasurement(
            player_id=player_id,
            name=by_id[player_id].name if player_id in by_id else player_id,
            measured_ms=reading.latency_ms,
            current_adjust_ms=by_id[player_id].sync_adjust_ms if player_id in by_id else 0,
            spread_ms=reading.spread_ms,
            delay_range_ms=by_id[player_id].delay_range_ms if player_id in by_id else None,
            sign=by_id[player_id].delay_sign if player_id in by_id else None,
            fixed=by_id[player_id].is_reference if player_id in by_id else False,
        )
        for player_id, reading in pass_.analysis.readings.items()
    ]


async def apply_solution(
    backend: SpeakerBackend,
    solution: CalibrationSolution,
    *,
    only_changed: bool = True,
) -> tuple[tuple[str, int], ...]:
    """Write the corrections in one batch.

    Music Assistant marks ``sync_adjust`` as requiring a reload, so each write
    interrupts the player. Batching them at the end of the session keeps that
    to a single disruption instead of one per measurement.

    ``only_changed`` skips the speakers already sitting at their target, which
    is the right thing on a first pass. It has to be off when re-applying after
    a sign correction: a speaker whose new target happens to equal what it
    started at looks unchanged, while the device is actually holding the
    previous attempt's value.
    """
    corrections = solution.changed() if only_changed else solution.writable()
    applied: list[tuple[str, int]] = []
    written = []
    try:
        for correction in corrections:
            await backend.set_sync_adjust(correction.player_id, correction.target_adjust_ms)
            applied.append((correction.player_id, correction.target_adjust_ms))
            written.append(correction)
    except BaseException:
        # All or nothing: a room half corrected is worse than one not touched,
        # and nobody would get a report saying which half. Put back what went
        # in, as far as the server lets us, and let the failure through.
        for correction in reversed(written):
            with contextlib.suppress(Exception):
                await backend.set_sync_adjust(correction.player_id, correction.current_adjust_ms)
        raise
    return tuple(applied)


MIN_SIGN_EVIDENCE_MS = 20.0
"""Smallest difference in written correction worth reading a direction from."""

SIGN_TOLERANCE = 0.35
"""How far the observed movement may be from the movement asked for."""


def observed_convention(
    before: MeasurementPass,
    after: MeasurementPass,
    solution: CalibrationSolution,
) -> int | None:
    """What a positive ``sync_adjust`` actually did, read off the two passes.

    The verification pass is already a sign probe: corrections of known size
    went in, and the arrival times moved. Comparing two speakers rather than
    looking at one in isolation is what makes it readable — each pass has its
    own arbitrary origin, and the difference between two speakers cancels it,
    exactly as the dedicated probe in :mod:`speaker_sync.calibration.validate`
    does.

    Returns ``1`` when a positive correction delays a player, ``-1`` when it
    advances one, and ``None`` when the evidence is too weak to say — a run
    that wrote nearly equal corrections everywhere, or a player that ignored
    the write.

    Only players whose direction is not already specified count: the question
    is what the session-wide sign should be, and it governs only them.
    """
    points = [
        (
            correction.target_adjust_ms - correction.current_adjust_ms,
            after.latencies_ms[correction.player_id] - before.latencies_ms[correction.player_id],
        )
        for correction in solution.corrections
        if correction.sign is None
        and correction.player_id in before.latencies_ms
        and correction.player_id in after.latencies_ms
    ]
    if len(points) < 2:
        return None

    least, most = min(points), max(points)
    span = most[0] - least[0]
    if span < MIN_SIGN_EVIDENCE_MS:
        return None

    moved = (most[1] - least[1]) / span
    if abs(abs(moved) - 1.0) > SIGN_TOLERANCE:
        return None  # nothing like what was asked for: not a sign question

    return 1 if moved > 0 else -1


MOVE_TOLERANCE_MS = 1.0
"""How far a speaker may land from where its written correction should put it."""

MOVE_TOLERANCE_SHARE = 0.25
"""The same, as a share of the movement asked for — for large corrections."""


@dataclass(frozen=True)
class PlayerVerification:
    """What the verification pass showed one written correction doing."""

    player_id: str
    expected_ms: float
    """How far the speaker should have moved relative to the anchor."""

    observed_ms: float
    """How far it did move, relative to the same anchor."""

    @property
    def error_ms(self) -> float:
        return self.observed_ms - self.expected_ms

    @property
    def held(self) -> bool:
        tolerance = max(MOVE_TOLERANCE_MS, abs(self.expected_ms) * MOVE_TOLERANCE_SHARE)
        return abs(self.error_ms) <= tolerance


def verify_movements(
    before: MeasurementPass,
    after: MeasurementPass,
    solution: CalibrationSolution,
    sign: int,
) -> dict[str, PlayerVerification]:
    """Compare each speaker's movement with what its correction asked for.

    Getting better overall is not proof. A speaker whose client ignored the
    write — or only applies a new delay after reconnecting — stays where it
    was, and if it happened to be near the target already the spread still
    shrinks. Each speaker is therefore held to its own expected movement.

    Each pass has its own arbitrary origin, so movements are compared against
    an anchor: the speaker asked to move least, ideally not at all.
    """
    expected = {
        c.player_id: (c.sign or sign) * c.delta_ms
        for c in solution.corrections
        if c.player_id in before.latencies_ms and c.player_id in after.latencies_ms
    }
    if len(expected) < 2:
        return {}
    observed = {
        pid: after.latencies_ms[pid] - before.latencies_ms[pid] for pid in expected
    }
    anchor = min(expected, key=lambda pid: abs(expected[pid]))
    return {
        pid: PlayerVerification(
            player_id=pid,
            expected_ms=expected[pid] - expected[anchor],
            observed_ms=observed[pid] - observed[anchor],
        )
        for pid in expected
        if pid != anchor
    }


def _check_the_movements(
    verifications: dict[str, PlayerVerification], names: dict[str, str]
) -> list[str]:
    problems = []
    for pid, check in verifications.items():
        if check.held:
            continue
        name = names.get(pid, pid)
        problems.append(
            say(
                en=f"«{name}» should have moved {check.expected_ms:+.1f} ms but moved "
                f"{check.observed_ms:+.1f} ms. Its new delay is not (fully) in force: the "
                "client may ignore it, or apply it only after reconnecting or restarting "
                "the stream. The values written are therefore not what you hear — run "
                "“Check” after restarting that speaker's client.",
                ru=f"«{name}» должна была сдвинуться на {check.expected_ms:+.1f} мс, а "
                f"сдвинулась на {check.observed_ms:+.1f} мс. Новая задержка действует не "
                "(полностью): клиент её игнорирует или применяет только после "
                "переподключения или перезапуска потока. Записанные значения не "
                "совпадают с тем, что слышно — запустите «Проверку» после перезапуска "
                "клиента этой колонки.",
            )
        )
    return problems


INDISTINGUISHABLE_MS = 0.2
"""Closer than two independent speakers plausibly land without help."""


def _check_the_rounds_isolated(
    pass_: MeasurementPass, players: Sequence[PlayerInfo]
) -> list[str]:
    """Notice a measurement in which every round heard the same speaker.

    This is the failure that costs the most to diagnose, because it does not
    look like a failure: if one speaker is audible throughout, every round
    measures that speaker, every reading agrees, and the report announces a
    system already in perfect alignment. It has been caused by an announcement
    overriding mute, by a speaker that never joined the group, and by the
    opening chirps being lost — three different faults with one signature.

    Uncorrected speakers landing within a fraction of a millisecond of each
    other is what gives it away. The corrections in force are what separates
    this from a system that is genuinely aligned: there, the readings agree
    *because* the delays differ, and here nothing is compensating anything.
    """
    latencies = pass_.latencies_ms
    if len(latencies) < 2 or max(latencies.values()) - min(latencies.values()) > (
        INDISTINGUISHABLE_MS
    ):
        return []

    corrections = {p.sync_adjust_ms for p in players if p.player_id in latencies}
    if len(corrections) > 1:
        return []  # they agree because their delays differ — that is alignment

    return [
        say(
            en=f"every speaker measured the same to within {INDISTINGUISHABLE_MS} ms, "
            "although all of them have the same delay set — so the rounds singled no one "
            "out: almost certainly one speaker played throughout and the others stayed "
            "silent. Check that each speaker really plays in its turn.",
            ru=f"все колонки измерились одинаково с точностью до {INDISTINGUISHABLE_MS} мс, "
            "хотя задержка у всех одна и та же — значит, круги никого не выделили: почти "
            "наверняка одна колонка звучала всё время, а остальные молчали. Проверьте, что "
            "каждая колонка действительно звучит в свою очередь.",
        )
    ]


# ------------------------------------------------------------ player state


@dataclass(frozen=True)
class PlayerState:
    """What a session may change about a player, as it stood beforehand."""

    synced_to: str | None
    group_members: tuple[str, ...]
    muted: bool | None
    volume_level: int | None


@dataclass(frozen=True)
class PlayerStateSnapshot:
    """The players' grouping, mute and volume from before a session.

    A measurement has to put every speaker into one group to give the rounds
    a common stream, and Music Assistant keeps that group after the track has
    stopped. Left behind, it is not harmless: a speaker still synced to the
    session's leader cannot join anything else, and playing a sync group that
    contains it then fails outright ("can not be grouped with"). So the state
    is taken before anything is touched and put back afterwards — on success,
    on failure, and when the run is cancelled because the browser went away.
    """

    states: dict[str, PlayerState]
    involved: frozenset[str]
    """The players the session works with. Restoring is limited to them and to
    whatever they were or are grouped with, so a change made elsewhere in the
    meantime is left alone."""

    @classmethod
    async def take(
        cls, backend: SpeakerBackend, involved: Iterable[str] | None = None
    ) -> "PlayerStateSnapshot":
        players = await backend.list_players()
        states = {
            p.player_id: PlayerState(
                synced_to=p.synced_to,
                group_members=tuple(p.group_members),
                muted=p.muted,
                volume_level=p.volume_level,
            )
            for p in players
        }
        return cls(states, frozenset(states if involved is None else involved))

    def _scope(self, now: dict[str, PlayerInfo]) -> set[str]:
        """The involved players plus anything linked to them, then or now."""
        scope = set(self.involved)
        for player_id in {*now, *self.states}:
            linked: set[str] = set()
            for state in (self.states.get(player_id), now.get(player_id)):
                if state is not None:
                    linked.update(state.group_members)
                    if state.synced_to:
                        linked.add(state.synced_to)
            if linked & self.involved:
                scope.add(player_id)
        return scope

    async def restore(self, backend: SpeakerBackend) -> list[str]:
        """Put grouping, mute and volume back; return what could not be.

        Every step is attempted regardless of the others, because the worst
        outcome is the one this exists to prevent: a speaker left stuck in the
        session's group. A failed step is reported, never raised.
        """
        problems: list[str] = []

        async def attempt(what: str, step: Awaitable[None]) -> None:
            try:
                await step
            except Exception as error:  # noqa: BLE001 - reported, not raised
                logger.warning("could not restore %s: %s", what, error)
                problems.append(
                    say(
                        en=f"could not put back {what}: {error}",
                        ru=f"не удалось вернуть {what}: {error}",
                    )
                )

        try:
            now = {p.player_id: p for p in await backend.list_players()}
        except Exception as error:  # noqa: BLE001
            logger.warning("could not read the players to restore them: %s", error)
            return [
                say(
                    en=f"could not read the speakers to restore their grouping: {error}",
                    ru=f"не удалось прочитать колонки, чтобы вернуть группировку: {error}",
                )
            ]
        scope = self._scope(now)

        # 1. Release every player that is grouped now in a way it was not
        #    before: a member following a new leader, or a leader holding
        #    members it did not have.
        release: list[str] = []
        for player_id in sorted(scope):
            current, before = now.get(player_id), self.states.get(player_id)
            if current is None:
                continue
            was_synced_to = before.synced_to if before else None
            if current.synced_to and current.synced_to != was_synced_to:
                release.append(player_id)
            had = set(before.group_members) if before else set()
            release.extend(
                m for m in current.group_members if m != player_id and m not in had
            )
        for player_id in dict.fromkeys(release):
            name = now[player_id].name if player_id in now else player_id
            await attempt(
                say(en=f"«{name}» to its own group", ru=f"«{name}» в свою группу"),
                backend.ungroup(player_id),
            )

        # 2. Rebuild a group that the session took players out of.
        if release:
            with contextlib.suppress(Exception):
                now = {p.player_id: p for p in await backend.list_players()}
        for player_id in sorted(scope):
            before, current = self.states.get(player_id), now.get(player_id)
            if before is None or current is None or before.synced_to:
                continue
            members = [m for m in before.group_members if m != player_id]
            missing = [
                m
                for m in members
                if m not in current.group_members and m in now and now[m].available
            ]
            if missing:
                await attempt(
                    say(
                        en=f"the group of «{current.name}»",
                        ru=f"группу «{current.name}»",
                    ),
                    backend.set_group(player_id, [player_id, *members]),
                )

        # 3. Mute and volume, for the players the session itself handled.
        for player_id in sorted(self.involved):
            before, current = self.states.get(player_id), now.get(player_id)
            if before is None or current is None:
                continue
            if before.muted is not None and current.muted is not None and (
                current.muted != before.muted
            ):
                await attempt(
                    say(en=f"the mute of «{current.name}»", ru=f"заглушение «{current.name}»"),
                    backend.set_muted(player_id, before.muted),
                )
            if before.volume_level is not None and current.volume_level != before.volume_level:
                await attempt(
                    say(en=f"the volume of «{current.name}»", ru=f"громкость «{current.name}»"),
                    backend.set_volume(player_id, before.volume_level),
                )

        return problems


@contextlib.asynccontextmanager
async def preserved_player_state(backend: SpeakerBackend, involved: Iterable[str]):
    """Run a block of session work and restore the players afterwards, always.

    Yields a list that receives whatever could not be restored, so the caller
    can report it alongside the session's own findings.
    """
    snapshot = await PlayerStateSnapshot.take(backend, involved)
    problems: list[str] = []
    try:
        yield problems
    finally:
        # Shielded: a cancellation arriving while the players are being put
        # back must not stop half way and leave a group behind.
        problems.extend(await asyncio.shield(snapshot.restore(backend)))


async def calibrate(
    backend: SpeakerBackend,
    recorder: Recorder,
    *,
    reference_id: str | None = None,
    config: SessionConfig | None = None,
    signal_url="",
    sign: int = 1,
    verify: bool = True,
    sleep: Sleeper = asyncio.sleep,
    progress: ProgressCallback | None = None,
) -> CalibrationReport:
    """Measure, correct, and then prove the correction worked.

    However it ends, the speakers are left grouped, muted and at the volume
    they were found in — see :class:`PlayerStateSnapshot`.
    """
    involved = [p.player_id for p in session_players(await backend.list_players())]
    async with preserved_player_state(backend, involved) as restore_problems:
        report = await _calibrate(
            backend,
            recorder,
            reference_id=reference_id,
            config=config,
            signal_url=signal_url,
            sign=sign,
            verify=verify,
            sleep=sleep,
            progress=progress,
        )
    if restore_problems:
        report = replace(report, problems=(*report.problems, *restore_problems))
    return report


async def _calibrate(
    backend: SpeakerBackend,
    recorder: Recorder,
    *,
    reference_id: str | None,
    config: SessionConfig | None,
    signal_url,
    sign: int,
    verify: bool,
    sleep: Sleeper,
    progress: ProgressCallback | None,
) -> CalibrationReport:
    cfg = config or SessionConfig()
    players = session_players(await backend.list_players())
    _need_two(players)
    if all(p.is_reference for p in players):
        raise ValueError(
            say(
                en="none of these speakers has a delay setting, so there is nothing to adjust",
                ru="ни у одной из этих колонок нет настройки задержки — настраивать нечего",
            )
        )

    names = {p.player_id: p.name for p in players}
    combined = await measure_repeatedly(
        backend,
        recorder,
        players,
        config=cfg,
        reference_id=reference_id,
        signal_url=signal_url,
        sleep=sleep,
        progress=progress,
    )
    before = combined.pass_
    problems = list(before.analysis.problems)
    problems.extend(stability_problems(combined, names))
    problems.extend(_check_the_rounds_isolated(before, players))

    measurements = build_measurements(before, players)
    after: MeasurementPass | None = None
    observed: int | None = None
    corrected_sign = False
    verifications: dict[str, PlayerVerification] = {}

    flagged = flagged_by_listener(recorder)
    leaks = leak_problems(combined.passes, players, wrote=False)
    while True:
        solution = solve(measurements, sign=sign)
        if not corrected_sign:
            problems.extend(solution_problems(solution))
        if flagged or leaks:
            # The listener heard something other than what the round claimed,
            # or a muted speaker played on. Corrections computed from that
            # could only make things worse, so the run reports and stops.
            problems.extend(leaks)
            problems.extend(listener_problems(flagged, names, wrote=False))
            applied = ()
            break

        writes = solution.corrections if corrected_sign else solution.changed()
        _report(progress, stage="applying", writes=len(writes))
        applied = await apply_solution(backend, solution, only_changed=not corrected_sign)

        if not (verify and applied):
            break

        _report(progress, stage="pass", which="after", players=len(players))
        refreshed = session_players(await backend.list_players())
        after = await measure_once(
            backend,
            recorder,
            refreshed,
            reference_id=reference_id,
            config=cfg,
            signal_url=signal_url,
            sleep=sleep,
            progress=progress,
            together=True,
        )
        problems.extend(after.analysis.problems)
        problems.extend(leak_problems([after], players, wrote=True))
        problems.extend(
            listener_problems(
                [f for f in flagged_by_listener(recorder) if f not in flagged], names, wrote=True
            )
        )

        # The verification pass is itself a sign probe: known corrections went
        # in and the arrivals moved. Reading it costs nothing and settles the
        # one question that turns a calibration into its own opposite.
        observed = observed_convention(before, after, solution)
        if observed is not None and observed != sign and not corrected_sign:
            sign = observed
            corrected_sign = True
            problems.append(
                say(
                    en="on this server a positive sync_adjust advances a speaker rather "
                    "than delaying it, so the first attempt doubled the spread instead of "
                    "removing it. The corrections have been written again, the other way "
                    "round.",
                    ru="на этом сервере положительный sync_adjust не задерживает колонку, "
                    "а торопит, поэтому первая попытка удвоила расхождение вместо того чтобы "
                    "его убрать. Поправки записаны заново, в обратную сторону.",
                )
            )
            continue

        if after.together is not None:
            problems.extend(after.together.problems)

        verifications = verify_movements(before, after, solution, sign)
        problems.extend(_check_the_movements(verifications, names))

        refinements = 0
        while (
            cfg.refine
            and refinements < cfg.max_refinements
            and not combined.unstable()
            and verifications
            and all(check.held for check in verifications.values())
            and solution.reference_late_ms is None
            and after.relative_spread_ms() > REFINE_SPREAD_MS
        ):
            refinements += 1
            refined = await _refine(
                backend,
                recorder,
                after,
                solution,
                sign=sign,
                config=cfg,
                reference_id=reference_id,
                signal_url=signal_url,
                sleep=sleep,
                progress=progress,
            )
            if refined is None:
                break
            solution, after, more = refined
            applied = tuple({**dict(applied), **dict(more)}.items())
            problems.extend(after.analysis.problems)
            if after.together is not None:
                problems.extend(after.together.problems)
            verifications = verify_movements(before, after, solution, sign)
            problems.extend(_check_the_movements(verifications, names))

        if after.relative_spread_ms() > before.relative_spread_ms():
            problems.append(
                say(
                    en="it got worse after applying — either a speaker ignored the write, "
                    "or sync_adjust on this server runs the other way from what the "
                    "measurement showed",
                    ru="после применения стало хуже — либо колонка проигнорировала запись, "
                    "либо знак sync_adjust на этом сервере не такой, как показал замер",
                )
            )
        break

    return CalibrationReport(
        before=before,
        solution=solution,
        after=after,
        applied=applied,
        sign=sign,
        observed_sign=observed,
        verifications=verifications,
        suspect=bool(flagged or leaks),
        # A fault present in both passes reports itself twice; the reader
        # learns nothing from the repetition. dict preserves first-seen order.
        problems=tuple(dict.fromkeys(problems)),
    )


REFINE_SPREAD_MS = 1.5
"""Left further apart than this after verifying, one more correction is made."""


async def _refine(
    backend: SpeakerBackend,
    recorder: Recorder,
    after: MeasurementPass,
    solution: CalibrationSolution,
    *,
    sign: int,
    config: SessionConfig,
    reference_id: str | None,
    signal_url,
    sleep: Sleeper,
    progress: ProgressCallback | None,
):
    """Correct what the verification still found, and verify again.

    The verification pass is a measurement of the room as it now stands, with
    the new delays in force, so it is the best starting point there is for a
    second, smaller correction: whatever moved slightly differently than asked
    — rounding, a delay applied a buffer late — is in it.

    Returns the solution expressed against the speakers' delays from before
    the whole run, the final pass and what was written, or ``None`` when there
    was nothing left to write.
    """
    players = session_players(await backend.list_players())
    second = solve(build_measurements(after, players), sign=sign)
    if not second.changed():
        return None

    _report(progress, stage="applying", writes=len(second.changed()), refine=True)
    applied = await apply_solution(backend, second)
    _report(progress, stage="pass", which="refine", players=len(players))
    final = await measure_once(
        backend,
        recorder,
        session_players(await backend.list_players()),
        reference_id=reference_id,
        config=config,
        signal_url=signal_url,
        sleep=sleep,
        progress=progress,
        together=True,
    )
    # Expressed from the run's starting point, so "before" and "after" in the
    # report and the movements checked against them span the whole run.
    original = {c.player_id: c.current_adjust_ms for c in solution.corrections}
    combined = replace(
        second,
        corrections=tuple(
            replace(c, current_adjust_ms=original.get(c.player_id, c.current_adjust_ms))
            for c in second.corrections
        ),
        spread_before_ms=solution.spread_before_ms,
    )
    return combined, final, applied


# ------------------------------------------------------------------ diagnosis

AUDIBLE_SPREAD_MS = 2.0
"""A spread past this is worth calibrating away."""

ECHO_SPREAD_MS = 20.0
"""Past this the second speaker is heard as a separate echo, not as colour."""

FORMAT_SHIFT_TOLERANCE_MS = 1.0
"""A latency that differs by more than this between track formats means a
correction can only suit one of them."""

CHECK_RATES = (44100, 48000)

FORMAT_JUMP_MS = 20.0
"""Past this, a difference between the two formats' passes is a speaker
jumping, not resampling latency."""


@dataclass(frozen=True)
class AlignmentCheck:
    """How the speakers line up right now, measured without changing anything."""

    passes: dict[int, MeasurementPass]
    """One pass per track sample rate, the first being the one music uses."""

    names: dict[str, str]
    problems: tuple[str, ...] = field(default=())

    @property
    def main(self) -> MeasurementPass:
        return next(iter(self.passes.values()))

    @property
    def spread_ms(self) -> float:
        return self.main.relative_spread_ms()

    @property
    def together(self) -> TogetherCheck | None:
        return self.main.together

    def offsets_ms(self, rate: int) -> dict[str, float]:
        """Each speaker's arrival after the earliest one, at ``rate``."""
        latencies = self.passes[rate].latencies_ms
        if not latencies:
            return {}
        earliest = min(latencies.values())
        return {pid: value - earliest for pid, value in latencies.items()}

    @property
    def format_shift_ms(self) -> dict[str, float]:
        """How much later each speaker lands at the other rates than at the main one.

        Measured against the first speaker, as a difference of differences:
        every pass has its own arbitrary origin, and only comparing speakers
        within a pass cancels it.
        """
        rates = list(self.passes)
        main = self.passes[rates[0]].latencies_ms
        shifts: dict[str, float] = {}
        for rate in rates[1:]:
            other = self.passes[rate].latencies_ms
            common = [pid for pid in main if pid in other]
            if len(common) < 2:
                continue
            base = common[0]
            for pid in common[1:]:
                shift = (other[pid] - other[base]) - (main[pid] - main[base])
                if abs(shift) > abs(shifts.get(pid, 0.0)):
                    shifts[pid] = shift
        return shifts

    @property
    def in_sync(self) -> bool:
        return not self.problems and self.spread_ms <= AUDIBLE_SPREAD_MS


async def check_alignment(
    backend: SpeakerBackend,
    recorder: Recorder,
    *,
    config: SessionConfig | None = None,
    signal_url="",
    sample_rates: Sequence[int] = CHECK_RATES,
    sleep: Sleeper = asyncio.sleep,
    progress: ProgressCallback | None = None,
) -> AlignmentCheck:
    """Measure the group as it stands, in each track format, and write nothing.

    This is what answers "I still hear an echo": whether the corrections in
    force hold, whether they hold with everyone playing, and whether a
    speaker's latency depends on the format of what it plays — the one thing
    a calibration in a single format cannot see.
    """
    cfg = config or SessionConfig()
    players = session_players(await backend.list_players())
    _need_two(players)

    passes: dict[int, MeasurementPass] = {}
    problems: list[str] = []
    async with preserved_player_state(backend, [p.player_id for p in players]) as restore_problems:
        for rate in sample_rates:
            _report(progress, stage="pass", which="check", rate=rate, players=len(players))
            pass_ = await measure_once(
                backend,
                recorder,
                players,
                config=replace(cfg, track_sample_rate=rate),
                signal_url=signal_url,
                sleep=sleep,
                progress=progress,
                together=True,
            )
            passes[rate] = pass_
            # Named by format: the same finding from two passes otherwise
            # reads as the report contradicting itself.
            label = f"{rate / 1000:g} kHz: " if len(sample_rates) > 1 else ""
            problems.extend(label + p for p in pass_.analysis.problems)
            if pass_.together is not None:
                problems.extend(label + p for p in pass_.together.problems)
    problems.extend(restore_problems)

    names = {p.player_id: p.name for p in players}
    problems.extend(leak_problems(list(passes.values()), players, wrote=True))
    problems.extend(listener_problems(flagged_by_listener(recorder), names, wrote=True))
    check = AlignmentCheck(passes=passes, names=names)

    spread = check.spread_ms
    if spread > ECHO_SPREAD_MS:
        problems.append(
            say(
                en=f"the speakers are {spread:.0f} ms apart right now — that is heard as an "
                "echo. Run a calibration.",
                ru=f"колонки сейчас расходятся на {spread:.0f} мс — это слышно как эхо. "
                "Запустите калибровку.",
            )
        )
    elif spread > AUDIBLE_SPREAD_MS:
        problems.append(
            say(
                en=f"the speakers are {spread:.1f} ms apart right now — run a calibration.",
                ru=f"колонки сейчас расходятся на {spread:.1f} мс — запустите калибровку.",
            )
        )

    main_rate, *other_rates = list(passes)
    # A difference this large between the two passes is not a format effect —
    # resampling costs a few milliseconds at most — but a speaker whose delay
    # jumped between them. Reported as what it is, rather than as a format
    # dependence nobody could act on.
    jumps = combine_passes(list(passes.values()), [p.player_id for p in players])
    jumped = set(jumps.unstable(FORMAT_JUMP_MS))
    problems.extend(stability_problems(jumps, names, tolerance=FORMAT_JUMP_MS))
    for pid, shift in check.format_shift_ms.items():
        if abs(shift) <= FORMAT_SHIFT_TOLERANCE_MS or pid in jumped or jumped:
            continue
        other = ", ".join(f"{r / 1000:g}" for r in other_rates)
        direction_en = "later" if shift > 0 else "earlier"
        direction_ru = "позже" if shift > 0 else "раньше"
        problems.append(
            say(
                en=f"«{names.get(pid, pid)}» plays {abs(shift):.1f} ms {direction_en} at "
                f"{other} kHz than at {main_rate / 1000:g} kHz — its latency depends on the "
                "format, so one correction cannot suit both. Calibration uses "
                f"{main_rate / 1000:g} kHz, the format most music is in.",
                ru=f"«{names.get(pid, pid)}» на {other} кГц звучит на {abs(shift):.1f} мс "
                f"{direction_ru}, чем на {main_rate / 1000:g} кГц — её задержка зависит от "
                "формата, и одна поправка не подойдёт обоим. Калибровка идёт на "
                f"{main_rate / 1000:g} кГц — в этом формате большая часть музыки.",
            )
        )

    return replace(check, problems=tuple(dict.fromkeys(problems)))


SPEAKER_TEST_STEP_SECONDS = 45.0
"""How long the speaker test waits for an answer before moving on."""

Ask = Callable[[dict], Awaitable["bool | None"]]
"""Puts one question to the listener and returns the answer, ``None`` for none."""


@dataclass(frozen=True)
class SpeakerTestResult:
    """What the listener heard, speaker by speaker, and in the silence."""

    names: dict[str, str]
    alone: dict[str, bool | None]
    """Per speaker: heard on its own (``True``), not (``False``), no answer."""

    silent: bool | None
    """With every speaker muted: silence (``True``), still sound (``False``)."""

    @property
    def passed(self) -> bool:
        return self.silent is True and all(v is True for v in self.alone.values())

    @property
    def problems(self) -> list[str]:
        problems = []
        for pid, ok in self.alone.items():
            name = self.names.get(pid, pid)
            if ok is False:
                problems.append(
                    say(
                        en=f"in the turn of «{name}» you heard something else than «{name}» "
                        f"alone. Either «{name}» did not play, or another speaker did not fall "
                        "silent when muted.",
                        ru=f"в очереди «{name}» вы слышали не только «{name}». Либо «{name}» "
                        "не играла, либо другая колонка не замолчала при заглушении.",
                    )
                )
            elif ok is None:
                problems.append(
                    say(
                        en=f"no answer for «{name}».",
                        ru=f"нет ответа для «{name}».",
                    )
                )
        if self.silent is False:
            problems.append(
                say(
                    en="with every speaker muted you still heard the test sound: a speaker "
                    "does not fall silent when muted. Walk up to each one while it is quiet "
                    "for everyone else to find it, then check its mute in Music Assistant or "
                    "in its app, or switch it off here — until then every measurement hears "
                    "it in the other speakers' rounds.",
                    ru="при заглушении всех колонок тестовый звук всё равно был слышен: какая-то "
                    "колонка не замолкает. Подойдите к каждой, чтобы найти её, затем проверьте "
                    "её заглушение в Music Assistant или в её приложении, или выключите её здесь "
                    "— иначе каждый замер слышит её в кругах других колонок.",
                )
            )
        elif self.silent is None:
            problems.append(
                say(en="no answer for the silence.", ru="нет ответа про тишину.")
            )
        return problems


async def speaker_test(
    backend: SpeakerBackend,
    signal_url,
    ask: Ask,
    *,
    config: SessionConfig | None = None,
    step_seconds: float = SPEAKER_TEST_STEP_SECONDS,
    sleep: Sleeper = asyncio.sleep,
) -> SpeakerTestResult:
    """Play each speaker on its own, then none, and ask the listener each time.

    The measurement takes the first arrival it hears in each round, so a
    speaker that keeps playing while muted does not spoil a round — it
    *replaces* it, and the numbers still look plausible. An ear standing in
    the room is the one instrument that knows which speaker is sounding, and
    it is given the time to answer here, unlike during a measurement whose
    rounds move on every few seconds.
    """
    cfg = config or SessionConfig()
    players = session_players(await backend.list_players())
    if not players:
        raise ValueError(
            say(en="no speaker to test", ru="нет колонок для проверки")
        )
    names = {p.player_id: p.name for p in players}
    player_ids = [p.player_id for p in players]
    leader = player_ids[0]
    # Long enough for every step to wait its full time; the track is
    # stopped as soon as the last answer is in.
    # One step's worth of margin: each step also spends time on its mute.
    steps = len(players) + 2
    chirps = min(512, int(steps * step_seconds / cfg.period_seconds) + 4)
    signal = cfg.build_signal(chirps)

    alone: dict[str, bool | None] = {}
    silent: bool | None = None
    async with preserved_player_state(backend, player_ids):
        await release_from_other_groups(backend, player_ids, leader)
        await backend.set_group(leader, player_ids)
        await confirm_group(backend, leader, player_ids, sleep=sleep)
        for player_id in player_ids:
            await backend.set_muted(player_id, True)
        await confirm_mute(backend, dict.fromkeys(player_ids, True), sleep=sleep)
        await backend.play_url(leader, _resolve_url(signal_url, signal))
        try:
            for index, player_id in enumerate(player_ids):
                await backend.set_muted(player_id, False)
                await confirm_mute(backend, {player_id: False}, sleep=sleep)
                alone[player_id] = await ask(
                    {
                        "step": "alone",
                        "player_id": player_id,
                        "name": names[player_id],
                        "index": index + 1,
                        "count": len(player_ids),
                    }
                )
                await backend.set_muted(player_id, True)
            await confirm_mute(backend, dict.fromkeys(player_ids, True), sleep=sleep)
            silent = await ask({"step": "silence"})
        finally:
            with contextlib.suppress(Exception):
                await backend.stop(leader)
    return SpeakerTestResult(names=names, alone=alone, silent=silent)


async def play_listening_test(
    backend: SpeakerBackend,
    url: str,
    *,
    hold_seconds: float,
    sleep: Sleeper = asyncio.sleep,
    on_playing: Callable[[list[PlayerInfo]], None] | None = None,
) -> list[str]:
    """Play the click track on every speaker at once, for judging by ear.

    Nothing is recorded: the listener is the instrument. The speakers are
    grouped and unmuted exactly as for a measurement, so what is heard is what
    the calibration aligned.

    The group is held for ``hold_seconds`` — the length of the track — and
    then taken apart again, so the test does not leave its group behind any
    more than a measurement does. ``on_playing`` is told once it is audible.
    Returns whatever could not be restored.
    """
    players = session_players(await backend.list_players())
    if len(players) < 2:
        raise ValueError(
            say(
                en="need at least two speakers to compare",
                ru="для сравнения нужно хотя бы две колонки",
            )
        )
    async with preserved_player_state(backend, [p.player_id for p in players]) as problems:
        await _start_listening_test(backend, url, players, sleep=sleep)
        if on_playing is not None:
            on_playing(players)
        try:
            await sleep(hold_seconds)
        finally:
            with contextlib.suppress(Exception):
                await backend.stop(players[0].player_id)
    return problems


async def _start_listening_test(
    backend: SpeakerBackend,
    url: str,
    players: list[PlayerInfo],
    *,
    sleep: Sleeper,
) -> None:
    player_ids = [p.player_id for p in players]
    leader = player_ids[0]
    await release_from_other_groups(backend, player_ids, leader)
    await backend.set_group(leader, player_ids)
    await confirm_group(backend, leader, player_ids, sleep=sleep)
    for player_id in player_ids:
        await backend.set_muted(player_id, False)
    await backend.play_url(leader, url)
