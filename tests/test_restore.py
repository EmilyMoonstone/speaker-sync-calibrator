"""A session leaves the speakers the way it found them.

The measurement groups every speaker under one leader, and Music Assistant
keeps that group after the track stops. Left behind, a speaker stays synced to
the session's leader and cannot join anything else — playing a sync group that
contains it then fails with "can not be grouped with". These tests pin down
that the grouping, mute and volume come back however the session ends: done,
failed, or cancelled because the browser holding the microphone went away.
"""

from __future__ import annotations

import asyncio

import pytest

from sim.fake_ma import SimulatedRecorder
from speaker_sync.calibration.session import (
    PlayerStateSnapshot,
    calibrate,
    check_alignment,
)
from speaker_sync.calibration.validate import determine_sign
from tests.test_end_to_end import make_server


def grouped(server) -> set[str]:
    return {s.player_id for s in server.speakers if server.is_grouped(s.player_id)}


async def test_a_calibration_leaves_no_group_behind():
    server, recorder, clock = make_server(snr_db=30.0)

    report = await calibrate(server, recorder, sleep=clock.sleep)

    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0
    assert grouped(server) == set()
    assert all(p.synced_to is None for p in await server.list_players())
    # The session did group them, and then took the group apart again.
    assert any(entry[0] == "group" for entry in server.log)
    assert any(entry[0] == "ungroup" for entry in server.log)


async def test_a_check_and_a_sign_probe_leave_no_group_behind():
    server, recorder, clock = make_server(snr_db=30.0)

    await check_alignment(server, recorder, sleep=clock.sleep)
    assert grouped(server) == set()

    await determine_sign(server, recorder, sleep=clock.sleep)
    assert grouped(server) == set()


class FailingRecorder(SimulatedRecorder):
    """The browser stops answering when the recording should be handed over."""

    async def stop(self):
        raise RuntimeError("the browser did not finish uploading the recording")


async def test_a_failed_calibration_still_takes_the_group_apart():
    server, _, clock = make_server(snr_db=30.0)

    with pytest.raises(RuntimeError, match="browser"):
        await calibrate(server, FailingRecorder(server), sleep=clock.sleep)

    assert grouped(server) == set()
    # Nobody is left muted mid-track either.
    assert not any(p.muted for p in await server.list_players())


async def test_a_cancelled_calibration_still_takes_the_group_apart():
    """Closing the browser cancels the running job; the finally has to hold."""
    server, recorder, _ = make_server(snr_db=30.0)
    started = asyncio.Event()

    async def slow_sleep(seconds: float) -> None:
        # Real time stands still until the test cancels: the session is
        # parked in the middle of its first round.
        started.set()
        await asyncio.Event().wait()

    job = asyncio.create_task(calibrate(server, recorder, sleep=slow_sleep))
    await started.wait()
    assert grouped(server)  # mid-run, the measurement group exists

    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job

    assert grouped(server) == set()
    assert not any(p.muted for p in await server.list_players())


async def test_a_group_that_existed_before_is_put_back():
    """Two speakers that were playing together before stay together after."""
    server, recorder, clock = make_server(snr_db=30.0)
    await server.set_group("avr", ["avr", "bt"])

    await calibrate(server, recorder, sleep=clock.sleep)

    assert server.groups == {"avr": ["avr", "bt"]}
    assert server.synced_to("bt") == "avr"
    assert server.synced_to("esp32") is None


async def test_mute_and_volume_come_back_as_they_were():
    server, recorder, clock = make_server(snr_db=30.0)
    await server.set_muted("bt", True)
    server.volumes["esp32"] = 23

    await calibrate(server, recorder, sleep=clock.sleep)
    # Something along the way moved a volume, as a group volume change would.
    server.volumes["avr"] = 80
    await check_alignment(server, recorder, sleep=clock.sleep)

    players = {p.player_id: p for p in await server.list_players()}
    assert players["bt"].muted is True
    assert players["esp32"].muted is False
    assert players["esp32"].volume_level == 23
    # Restored to what it was when *that* session began.
    assert players["avr"].volume_level == 80


async def test_restoring_carries_on_past_a_command_that_fails():
    """One refused ungroup must not leave the rest of the speakers grouped."""
    server, recorder, clock = make_server(snr_db=30.0)
    snapshot = await PlayerStateSnapshot.take(server, ["esp32", "avr", "bt"])
    await server.set_group("esp32", ["esp32", "avr", "bt"])

    real_ungroup = server.ungroup

    async def refusing_ungroup(player_id: str) -> None:
        if player_id == "avr":
            raise RuntimeError("player is busy")
        await real_ungroup(player_id)

    server.ungroup = refusing_ungroup

    problems = await snapshot.restore(server)

    assert server.synced_to("bt") is None
    assert server.synced_to("avr") == "esp32"
    assert len(problems) == 1 and "busy" in problems[0]


async def test_players_outside_the_session_are_left_alone():
    """A group the user formed elsewhere in the meantime is none of our business."""
    server, recorder, clock = make_server(snr_db=30.0)
    snapshot = await PlayerStateSnapshot.take(server, ["esp32"])
    await server.set_group("avr", ["avr", "bt"])

    await snapshot.restore(server)

    assert server.groups == {"avr": ["avr", "bt"]}


async def test_a_leader_still_in_another_group_is_released_first():
    """The live listening test: the session's leader was still in the sync
    group from the last song, Music Assistant redirected the grouping there,
    and the clicks played on that one speaker alone — unnoticed, because the
    leader reported no members of its own."""
    server, recorder, clock = make_server(snr_db=30.0)
    await server.set_group("bt", ["bt", "esp32"])

    report = await calibrate(server, recorder, sleep=clock.sleep)

    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0
    # ...and the group it was taken out of is back as it was.
    assert server.groups == {"bt": ["bt", "esp32"]}


async def test_a_group_redirected_elsewhere_is_not_mistaken_for_success():
    from speaker_sync.calibration.session import confirm_group

    server, recorder, clock = make_server(snr_db=30.0)
    await server.set_group("bt", ["bt", "esp32"])
    await server.set_group("esp32", ["esp32", "avr", "bt"])  # redirected to bt

    with pytest.raises(RuntimeError, match="did not join"):
        await confirm_group(server, "esp32", ["esp32", "avr", "bt"], sleep=clock.sleep)


async def test_a_volume_that_fell_to_zero_comes_back():
    """A client that mutes by turning itself down, and is slow to turn back
    up: left alone, the speaker would stay at 0 after the run."""
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes["bt"] = 72
    server.zeroes_volume_on_mute = {"bt"}
    server.slow_volume_return = True

    await calibrate(server, recorder, sleep=clock.sleep)

    assert server.volumes["bt"] == 72


async def test_a_zero_read_before_the_run_is_never_written_back():
    """The live failure: the "before" was read while the phone app was still
    turned down from the previous run, and restoring wrote 0 for good."""
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes["bt"] = 0  # still down from last time
    snapshot = await PlayerStateSnapshot.take(server, ["esp32", "avr", "bt"])
    server.volumes["bt"] = 72  # the app turned itself back up meanwhile

    await snapshot.restore(server)

    assert server.volumes["bt"] == 72
    assert not any(entry[0] == "volume" for entry in server.log)


async def test_a_volume_the_listener_changed_during_the_run_is_left_alone():
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes["esp32"] = 40
    snapshot = await PlayerStateSnapshot.take(server, ["esp32", "avr", "bt"])
    server.volumes["esp32"] = 65  # turned up by hand while measuring

    await snapshot.restore(server)

    assert server.volumes["esp32"] == 65


async def test_an_unreported_volume_is_not_taken_for_silence():
    from tests.test_ma_client import FakeClient, FakePlayer, delay_entry
    from speaker_sync.ma.client import MusicAssistantBackend

    client = FakeClient([FakePlayer("pixel", "Pixel9", volume_level=None)], entries={"pixel": [delay_entry()]})

    (player,) = await MusicAssistantBackend(client).list_players()

    assert player.volume_level is None
