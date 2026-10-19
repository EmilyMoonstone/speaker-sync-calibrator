"""Failure paths found in a review of the whole run, each pinned down.

None of these show on a good day. Each is what happens on a bad one — a slow
server, a write refused half way through, a socket that drops, a reply that
never comes — and what the run does then.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from sim.fake_ma import mixed_speakers
from speaker_sync.calibration.session import apply_solution, calibrate
from speaker_sync.calibration.solver import PlayerMeasurement, solve
from tests.test_end_to_end import make_server


async def test_slow_mute_commands_do_not_slide_the_rounds_onto_the_wrong_speaker():
    """Every mute command took 0.6 s. Sleeping a round's length after the
    commands added that to every later boundary — 6 s by the last round, far
    past the 2.6 s the guard chirps absorb. Rounds now keep the track's time."""
    server, recorder, clock = make_server(snr_db=30.0)
    server.command_seconds = 0.6

    report = await calibrate(server, recorder, sleep=clock.sleep)

    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0
    assert not any("every speaker was muted" in p for p in report.problems)


async def test_a_write_refused_half_way_puts_the_earlier_ones_back():
    server, recorder, clock = make_server(snr_db=30.0)
    solution = solve(
        [
            PlayerMeasurement("esp32", "ESP32", 10.0, current_adjust_ms=0),
            PlayerMeasurement("avr", "AVR", 60.0, current_adjust_ms=0),
            PlayerMeasurement("bt", "BT", 200.0, current_adjust_ms=0),
        ]
    )
    real = server.set_sync_adjust

    async def refusing(player_id, milliseconds):
        if player_id == "avr" and milliseconds != 0:
            raise RuntimeError("the server refused it")
        await real(player_id, milliseconds)

    server.set_sync_adjust = refusing

    with pytest.raises(RuntimeError, match="refused"):
        await apply_solution(server, solution)

    assert {s.player_id: s.sync_adjust_ms for s in server.speakers} == {
        "esp32": 0,
        "avr": 0,
        "bt": 0,
    }
    assert ("esp32", 190) in server.writes and server.writes[-1] == ("esp32", 0)


async def test_a_command_music_assistant_never_answers_ends_with_a_message():
    from speaker_sync.ma import client as client_module
    from speaker_sync.ma.client import MusicAssistantBackend
    from tests.test_ma_client import FakeClient, FakePlayer, delay_entry

    client = FakeClient([FakePlayer("pc", "PC")], entries={"pc": [delay_entry()]})

    async def never(player_id, muted):
        await asyncio.Event().wait()

    client.players.volume_mute = never
    original = client_module.COMMAND_TIMEOUT_SECONDS
    client_module.COMMAND_TIMEOUT_SECONDS = 0.05
    try:
        with pytest.raises(RuntimeError, match="did not answer"):
            await MusicAssistantBackend(client).set_muted("pc", True)
    finally:
        client_module.COMMAND_TIMEOUT_SECONDS = original


def test_a_frame_cut_mid_sample_is_trimmed_not_fatal():
    from speaker_sync.web.app import BrowserRecorder

    recorder = BrowserRecorder(socket=None)
    recorder.feed(np.ones(3, dtype=np.float32).tobytes() + b"\x00")
    recorder.feed(b"\x01\x02")

    assert len(recorder._chunks) == 1 and len(recorder._chunks[0]) == 3


def test_a_failing_live_view_is_switched_off_not_fatal():
    from speaker_sync.web.app import BrowserRecorder

    class Broken:
        def feed(self, samples):
            raise ValueError("boom")

    recorder = BrowserRecorder(socket=None, live=lambda message: None)
    recorder._monitor = Broken()
    recorder.feed(np.ones(8, dtype=np.float32).tobytes())

    assert recorder._monitor is None
    assert len(recorder._chunks) == 1


def test_a_together_finding_says_how_much_is_unexplained_in_words():
    from speaker_sync.calibration.together import _share

    assert _share(0.0) == "100 %"
    assert _share(-3.0) == "50 %"
    assert _share(3.0) == "100 %"
