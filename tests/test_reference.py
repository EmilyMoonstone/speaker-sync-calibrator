"""A speaker without a delay setting, measured as a fixed point.

MassDroid compensates its own output latency and so offers the server no delay
to adjust. It still plays the stream, mutes and joins a group — so instead of
sitting the session out, it is measured, and the speakers that can be adjusted
are aligned to it. Its own configuration is never written.

Sendspin can only make a speaker play earlier, which splits the cases: a
reference that arrives *first* can be met by bringing the others forward; one
that arrives *last* cannot be met from the server at all, and then nothing is
written and the report says why.
"""

from __future__ import annotations

import pytest

from sim.fake_ma import FakeMusicAssistant, SimulatedRecorder, VirtualClock
from sim.virtual_room import RoomConfig, VirtualSpeaker
from speaker_sync.calibration.profiles import Profile, apply_profile
from speaker_sync.calibration.session import calibrate, check_alignment, measure_once
from speaker_sync.ma.backend import SelectedSpeakers


def flat(pixel_ms: float, *, pc_ms: float = 60.0, hifi_ms: float = 45.0) -> FakeMusicAssistant:
    """Two Sendspin speakers and a phone app as the reference."""
    speakers = [
        VirtualSpeaker("pc", "Emily-PC", hardware_latency_ms=pc_ms, distance_m=3.0, sign=-1),
        VirtualSpeaker("hifi", "Anlage", hardware_latency_ms=hifi_ms, distance_m=4.0, sign=-1),
        VirtualSpeaker("pixel", "Pixel9", hardware_latency_ms=pixel_ms, distance_m=1.0),
    ]
    server = FakeMusicAssistant(
        speakers=speakers,
        clock=VirtualClock(),
        config=RoomConfig(snr_db=30.0),
        delay_range_ms=(0, 5000),
        delay_key="sendspin_static_delay",
        no_delay={"pixel"},
    )
    return server


async def test_the_reference_is_measured_and_the_others_meet_it():
    server = flat(pixel_ms=20.0)
    recorder = SimulatedRecorder(server)

    report = await calibrate(server, recorder, sleep=server.clock.sleep)

    assert "pixel" in report.before.latencies_ms
    assert report.solution.strategy == "align_to_reference"
    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0
    assert "pixel" not in dict(server.writes)
    assert {pid for pid, _ in server.writes} == {"pc", "hifi"}
    assert not report.problems


async def test_the_reference_is_never_the_leader():
    """The leader carries the stream for the group; a phone app that is
    closed takes its group with it."""
    server = flat(pixel_ms=20.0)
    server.speakers = [server.speakers[2], *server.speakers[:2]]  # listed first

    await calibrate(server, SimulatedRecorder(server), sleep=server.clock.sleep)

    leaders = {entry[1] for entry in server.log if entry[0] == "group"}
    assert "pixel" not in leaders


async def test_a_reference_arriving_last_is_reported_and_nothing_is_written():
    server = flat(pixel_ms=250.0)  # e.g. a Bluetooth box the app does not know about

    report = await calibrate(server, SimulatedRecorder(server), sleep=server.clock.sleep)

    assert server.writes == []
    assert report.applied == ()
    assert report.solution.strategy == "reference_too_late"
    # 250 + 1 m against the latest the others can all be moved to, which is
    # the Anlage left as it is (45 + 4 m): Sendspin cannot hold anyone back.
    assert report.solution.reference_late_ms == pytest.approx(196.3, abs=1.5)
    message = next(p for p in report.problems if "Pixel9" in p)
    assert "cannot be corrected from the server" in message
    assert "nothing was written" in message


async def test_a_reference_switched_off_by_hand_sits_out():
    """The manual switch still works, for when the phone is not around."""
    server = flat(pixel_ms=250.0)
    speakers = SelectedSpeakers(server, frozenset({"pixel"}))

    report = await calibrate(speakers, SimulatedRecorder(server), sleep=server.clock.sleep)

    assert "pixel" not in report.before.latencies_ms
    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0


async def test_the_check_includes_the_reference():
    server = flat(pixel_ms=20.0)

    check = await check_alignment(server, SimulatedRecorder(server), sleep=server.clock.sleep)

    assert "pixel" in check.names


async def test_a_saved_position_aligns_to_the_reference_again():
    server = flat(pixel_ms=20.0)
    recorder = SimulatedRecorder(server)
    report = await calibrate(server, recorder, sleep=server.clock.sleep)
    profile = Profile.from_report("Flur", report)
    calibrated = dict(server.writes)
    for pid in ("pc", "hifi"):
        await server.set_sync_adjust(pid, 0)

    outcome = await apply_profile(server, profile)

    assert dict(outcome.applied) == calibrated
    verified = await measure_once(
        server, recorder, await server.list_players(), sleep=server.clock.sleep
    )
    assert verified.relative_spread_ms() < 2.0


async def test_a_reference_that_cannot_be_muted_sits_out():
    server = flat(pixel_ms=20.0)
    server.ignores_mute = {"pixel"}

    report = await calibrate(server, SimulatedRecorder(server), sleep=server.clock.sleep)

    assert "pixel" not in report.before.latencies_ms


async def test_the_report_follows_each_speaker_through_the_run():
    """Measured arrival, old and new delay, which way it moves the speaker and
    whether the verification saw it move that far — per speaker."""
    from speaker_sync.web.app import describe

    server = flat(pixel_ms=20.0)
    report = await calibrate(server, SimulatedRecorder(server), sleep=server.clock.sleep)

    rows = {row["player_id"]: row for row in describe(report)["players"]}

    assert rows["pixel"]["reference"] is True
    assert rows["pixel"]["arrival_ms"] == 0.0  # the earliest
    assert rows["pixel"]["moves_ms"] == 0
    # pc: 60 ms + 3 m against pixel's 20 ms + 1 m, so ~46 ms later; Sendspin
    # brings it forward, so its arrival moves earlier by what was written.
    assert rows["pc"]["arrival_ms"] == pytest.approx(45.8, abs=0.5)
    assert rows["pc"]["target_adjust_ms"] == pytest.approx(46, abs=1)
    assert rows["pc"]["moves_ms"] == -rows["pc"]["target_adjust_ms"]
    assert rows["pc"]["verification"]["held"] is True
    assert describe(report)["written"] == 2
