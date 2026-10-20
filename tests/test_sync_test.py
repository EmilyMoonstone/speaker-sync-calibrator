"""The sync test: press Test, hear one short round, learn whether it is in sync.

It answers nothing but "do all speakers play together, as everything is set
right now" — delays in Music Assistant, a client's own, a mixer's output
delay alike — and changes nothing.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sim.fake_ma import SimulatedRecorder
from speaker_sync.calibration.session import calibrate, sync_test
from speaker_sync.web.app import create_app, describe_check
from tests.test_end_to_end import make_server
from tests.test_reference import flat
from tests.test_web import client_for, state  # noqa: F401  (the fixture)


def track_url(signal):
    return f"http://calibrator/signal.wav?chirps={signal.chirp_count}&rate={signal.sample_rate}"


async def test_a_calibrated_room_passes_in_one_short_pass_without_writes():
    server, recorder, clock = make_server(snr_db=30.0)
    await calibrate(server, recorder, signal_url=track_url, sleep=clock.sleep)
    writes, plays = list(server.writes), server.plays

    check = await sync_test(server, recorder, signal_url=track_url, sleep=clock.sleep)

    assert check.in_sync
    assert list(check.passes) == [44100]
    assert server.plays == plays + 1
    assert server.writes == writes
    assert check.together is not None and check.together.confirmed
    described = describe_check(check)
    assert described["quick"] is True and described["in_sync"] is True


async def test_an_uncalibrated_room_names_who_is_late():
    server, recorder, clock = make_server(snr_db=30.0)

    described = describe_check(
        await sync_test(server, recorder, signal_url=track_url, sleep=clock.sleep)
    )

    assert not described["in_sync"]
    assert described["spread_ms"] > 150.0
    assert described["latest"] == "Спальня (Bluetooth)"
    assert described["earliest"] == "Кухня (ESP32)"
    assert server.writes == []


async def test_a_delay_changed_outside_the_add_on_is_heard():
    """Calibrated, then a mixer's output delay moves one speaker 30 ms: the
    settings in Music Assistant are unchanged, and the test still hears it."""
    server, recorder, clock = make_server(snr_db=30.0)
    await calibrate(server, recorder, signal_url=track_url, sleep=clock.sleep)
    server.speakers = [
        replace(s, hardware_latency_ms=s.hardware_latency_ms + 30.0) if s.player_id == "avr" else s
        for s in server.speakers
    ]

    check = await sync_test(server, recorder, signal_url=track_url, sleep=clock.sleep)

    assert not check.in_sync
    assert check.spread_ms == pytest.approx(30.0, abs=1.0)
    assert check.latest == "avr"


async def test_a_player_without_a_delay_setting_is_part_of_the_test():
    server = flat(pixel_ms=20.0)
    recorder = SimulatedRecorder(server)
    await calibrate(server, recorder, sleep=server.clock.sleep)

    check = await sync_test(server, recorder, sleep=server.clock.sleep)

    assert "pixel" in check.main.latencies_ms
    assert check.in_sync


async def test_the_test_leaves_the_speakers_as_they_were():
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes.update({"esp32": 30, "avr": 40, "bt": 50})

    await sync_test(server, recorder, sleep=clock.sleep, test_volumes={"bt": 90})

    assert server.volumes == {"esp32": 30, "avr": 40, "bt": 50}
    assert not any(server.is_grouped(s.player_id) for s in server.speakers)
    assert not any(p.muted for p in await server.list_players())


async def test_the_sync_test_starts_over_the_socket(state):
    client = await client_for(create_app(state))
    try:
        socket = await client.ws_connect("/ws")
        await socket.send_json({"type": "sync_test"})
        message = await socket.receive_json(timeout=5)
        await socket.close()
    finally:
        await client.close()

    assert message["type"] != "error"
