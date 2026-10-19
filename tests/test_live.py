"""Live feedback: what the page can say while the recording is still coming in.

The verdicts are about whether the measurement can work — is a chirp heard,
is the level usable — so they are checked against rooms where the answer is
known: a clear speaker, a faint one, none at all, and an overdriven mic.
"""

from __future__ import annotations

import numpy as np

from sim.virtual_room import Round, RoomConfig, VirtualSpeaker, render_recording
from speaker_sync.calibration.live import LiveMonitor
from speaker_sync.dsp.signals import build_test_signal

CHIRPS = 8


def room(*, audible: bool = True, gain: float = 1.0, snr_db: float = 30.0, amplitude: float = 0.4):
    config = RoomConfig(chirp_count=CHIRPS, snr_db=snr_db, amplitude=amplitude)
    speaker = VirtualSpeaker("a", "A", hardware_latency_ms=40.0, gain=gain)
    end = CHIRPS * config.period_seconds
    rounds = [Round(0.0, end, frozenset({"a"}) if audible else frozenset())]
    recording = render_recording([speaker], rounds, config)
    signal = build_test_signal(
        chirp_count=CHIRPS,
        period_seconds=config.period_seconds,
        chirp_seconds=config.chirp_seconds,
        f_start=config.f_start,
        f_end=config.f_end,
    )
    return recording, signal, config.mic_sample_rate


def stream(recording: np.ndarray, monitor: LiveMonitor, block: int = 4096):
    """Feed the recording in browser-sized blocks, as the socket delivers it."""
    readings = []
    for start in range(0, len(recording), block):
        readings.extend(monitor.feed(recording[start : start + block]))
    return readings


def test_a_clear_speaker_is_heard_in_every_window():
    recording, signal, rate = room()

    readings = stream(recording, LiveMonitor(signal, rate))

    assert len(readings) >= CHIRPS - 2
    assert all(r.heard for r in readings)
    assert all(r.verdict == "ok" for r in readings)
    assert readings[1].at_seconds > readings[0].at_seconds


def test_silence_is_not_mistaken_for_a_chirp():
    """The noise maximum of a long window sits ~12 dB above its median; a
    fixed ratio would call that a chirp. The threshold accounts for it."""
    recording, signal, rate = room(audible=False)

    readings = stream(recording, LiveMonitor(signal, rate))

    assert readings
    assert not any(r.heard for r in readings)
    assert all(r.verdict == "silent" for r in readings)


def test_a_faint_speaker_is_called_quiet_before_it_is_lost():
    # About -20 dB SNR is where the margin drops below 10 dB: still measured,
    # but one bad moment away from being missed.
    recording, signal, rate = room(snr_db=-22.0, amplitude=0.02)

    verdicts = {r.verdict for r in stream(recording, LiveMonitor(signal, rate))}

    assert "quiet" in verdicts
    assert "clipping" not in verdicts


def test_an_overdriven_microphone_is_called_out():
    recording, signal, rate = room()
    recording = np.clip(recording * 10.0, -1.0, 1.0)

    readings = stream(recording, LiveMonitor(signal, rate))

    assert any(r.verdict == "clipping" for r in readings)


def test_block_size_does_not_change_the_verdicts():
    recording, signal, rate = room()

    small = [r.verdict for r in stream(recording, LiveMonitor(signal, rate), block=128)]
    large = [r.verdict for r in stream(recording, LiveMonitor(signal, rate), block=48000)]

    assert small == large


def test_a_reading_describes_itself_for_the_page():
    recording, signal, rate = room()

    reading = stream(recording, LiveMonitor(signal, rate))[0].to_dict()

    assert set(reading) == {"at_seconds", "level_db", "peak_db", "margin_db", "heard", "verdict"}
    assert reading["heard"] is True


class _Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, message):
        self.sent.append(message)


async def test_the_browser_recorder_reports_each_window_as_it_streams_in():
    """The path the page sees: the browser names its rate when recording
    starts, then every block it uploads is judged as soon as a window fills."""
    from speaker_sync.web.app import BrowserRecorder

    recording, signal, rate = room()
    events = []
    recorder = BrowserRecorder(_Socket(), live=events.append)

    await recorder.start(signal)
    recorder.set_format(rate)
    samples = recording.astype(np.float32)
    for start in range(0, len(samples), 4096):
        recorder.feed(samples[start : start + 4096].tobytes())

    assert events and all(e["type"] == "live" for e in events)
    assert all(e["verdict"] == "ok" for e in events)


async def test_without_the_rate_nothing_is_judged_live_but_everything_is_kept():
    """An older page never names its rate: the measurement still works."""
    from speaker_sync.web.app import BrowserRecorder

    recording, signal, rate = room()
    events = []
    recorder = BrowserRecorder(_Socket(), live=events.append)

    await recorder.start(signal)
    recorder.feed(recording.astype(np.float32).tobytes())
    recorder.complete(rate)
    kept, kept_rate = await recorder.stop()

    assert events == []
    assert len(kept) == len(recording) and kept_rate == rate


def test_the_listeners_answers_are_kept_for_the_session():
    from speaker_sync.web.app import BrowserRecorder

    recorder = BrowserRecorder(_Socket())
    recorder.note_feedback("avr", False)

    assert recorder.human_feedback == [{"player_id": "avr", "ok": False}]
