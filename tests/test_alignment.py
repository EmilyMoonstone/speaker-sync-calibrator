"""Rounds timed by the first chirp heard, not by the play command.

The audio starts well after "play" — the stream is set up, then every client
fills its buffer. Counted from the command, the round boundaries came early
enough to mute a speaker in the middle of its last chirp: heard live as the
last chirp of a speaker cut off, and measured as one reading a few
milliseconds off. Anchored on what the microphone hears, every switch lands
halfway through the pause between two chirps.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from sim.virtual_room import Round, RoomConfig, VirtualSpeaker, render_recording
from speaker_sync.calibration.live import LiveMonitor
from speaker_sync.calibration.session import SessionConfig, calibrate, measure_once
from speaker_sync.dsp.signals import build_test_signal
from tests.test_end_to_end import make_server

STREAM_START = 1.6
"""A realistic start: server set-up plus a client's one-second buffer."""


def glitches(problems):
    return [p for p in problems if "one reading is" in p or "no chirp was heard" in p]


async def test_a_late_starting_stream_no_longer_cuts_the_last_chirp():
    server, recorder, clock = make_server(snr_db=30.0)
    server.stream_start_seconds = STREAM_START

    report = await calibrate(server, recorder, sleep=clock.sleep)

    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0
    assert glitches(report.problems) == []


async def switches_during_chirps(config: SessionConfig) -> list[float]:
    """Run one pass on a late-starting stream; return mute changes made mid-chirp."""
    server, recorder, clock = make_server(snr_db=30.0)
    server.stream_start_seconds = STREAM_START
    switched_at = []
    real = server.set_muted

    async def noting(player_id, muted):
        switched_at.append(clock.now)
        await real(player_id, muted)

    server.set_muted = noting
    pass_ = await measure_once(server, recorder, await server.list_players(), config=config, sleep=clock.sleep)
    assert pass_.analysis.readings
    heard = server.first_chirp_heard_at()
    return [t for t in switched_at if t > heard and ((t - heard) % 1.3) < 0.5]


async def test_timed_by_the_command_switches_fall_into_chirps():
    """The control: the old schedule on the same late start mutes speakers
    in the middle of a chirp — the cut-off last chirp heard in the room."""
    assert await switches_during_chirps(SessionConfig(align_to_first_chirp=False))


async def test_switches_land_between_chirps():
    """Every mute change falls in a pause, never during a chirp."""
    assert await switches_during_chirps(SessionConfig()) == []


async def test_nothing_heard_at_the_start_stops_the_pass_with_a_reason():
    server, recorder, clock = make_server(snr_db=30.0)
    server.dropouts = {"esp32": {1}}  # the opening speaker stays silent

    with pytest.raises(RuntimeError, match="heard no test sound"):
        await measure_once(server, recorder, await server.list_players(), sleep=clock.sleep)
    # ...and nobody is left muted.
    assert not any(p.muted for p in await server.list_players())


def first_chirp_room(latency_ms: float):
    config = RoomConfig(chirp_count=4, snr_db=30.0)
    speaker = VirtualSpeaker("a", "A", hardware_latency_ms=latency_ms, distance_m=0.0)
    recording = render_recording([speaker], [Round(0.0, 4 * config.period_seconds, frozenset({"a"}))], config)
    signal = build_test_signal(chirp_count=4)
    return recording, signal, config


def test_the_live_view_finds_where_the_first_chirp_begins():
    recording, signal, config = first_chirp_room(latency_ms=120.0)
    monitor = LiveMonitor(signal, config.mic_sample_rate)

    for start in range(0, len(recording), 4096):
        monitor.feed(recording[start : start + 4096])

    expected = (config.lead_in_seconds + 0.120) * config.mic_sample_rate
    assert monitor.first_onset is not None
    assert abs(monitor.first_onset - expected) < 0.002 * config.mic_sample_rate


async def test_the_browser_recorder_says_how_long_ago_the_first_chirp_was():
    from speaker_sync.web.app import UPLOAD_LAG_SECONDS, BrowserRecorder

    class Socket:
        async def send_json(self, message):
            pass

    recording, signal, config = first_chirp_room(latency_ms=0.0)
    recorder = BrowserRecorder(Socket())
    await recorder.start(signal)
    recorder.set_format(config.mic_sample_rate)
    samples = recording.astype(np.float32)
    fed = 3 * config.mic_sample_rate  # three seconds in
    for start in range(0, fed, 4096):
        recorder.feed(samples[start : min(start + 4096, fed)].tobytes())

    ago = await recorder.first_chirp(timeout=1.0)

    expected = 3.0 - config.lead_in_seconds + UPLOAD_LAG_SECONDS
    assert ago == pytest.approx(expected, abs=0.01)


async def test_a_page_that_never_names_its_rate_falls_back_to_the_old_timing():
    from speaker_sync.web import app as web_app
    from speaker_sync.web.app import BrowserRecorder

    class Socket:
        async def send_json(self, message):
            pass

    recorder = BrowserRecorder(Socket())
    await recorder.start(build_test_signal(chirp_count=4))
    original = web_app.MONITOR_GRACE_SECONDS
    web_app.MONITOR_GRACE_SECONDS = 0.01
    try:
        assert await recorder.first_chirp(timeout=1.0) is None
    finally:
        web_app.MONITOR_GRACE_SECONDS = original
