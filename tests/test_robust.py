"""A calibration that holds up when the room, the speakers or the person do not.

Each test is a way a real run has gone, or could go, wrong: a speaker whose
delay wanders from one stream start to the next, a speaker that drops out of
one pass, a client that applies only part of its correction, and a listener
who hears something other than the round claims. The run has to notice each,
recover where it can, and say so where it cannot.
"""

from __future__ import annotations

import pytest

from sim.fake_ma import SimulatedRecorder, mixed_speakers
from speaker_sync.calibration.session import (
    SessionConfig,
    calibrate,
    combine_passes,
)
from tests.test_end_to_end import make_server


def sendspin_server(**changes):
    speakers = [s.__class__(**{**s.__dict__, "sign": -1, **changes.get(s.player_id, {})}) for s in mixed_speakers()]
    server, recorder, clock = make_server(speakers, snr_db=30.0)
    server.delay_range_ms = (0, 5000)
    server.delay_key = "sendspin_static_delay"
    return server, recorder, clock


async def test_a_normal_run_measures_twice_before_correcting():
    server, recorder, clock = sendspin_server()

    report = await calibrate(server, recorder, sleep=clock.sleep)

    # Two passes before, one verifying after.
    assert server.plays == 3
    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0
    assert not report.problems


async def test_a_speaker_whose_delay_wanders_is_named_and_the_others_are_not():
    """The live Anlage: ~3, 247 and 152 ms against the others in three runs."""
    server, recorder, clock = sendspin_server()
    server.wander_ms = {"avr": (0.0, 40.0, 15.0)}

    report = await calibrate(server, recorder, sleep=clock.sleep)

    assert server.plays == 4  # passes disagreed, so a third was taken
    wandering = [p for p in report.problems if "differently from one measurement" in p]
    assert len(wandering) == 1
    assert "Гостиная (ресивер)" in wandering[0]


async def test_a_speaker_unheard_in_one_pass_earns_another():
    server, recorder, clock = sendspin_server()
    server.dropouts = {"bt": {1}}

    report = await calibrate(server, recorder, sleep=clock.sleep)

    assert server.plays == 4
    assert "bt" in report.before.latencies_ms
    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0


async def test_a_correction_applied_short_is_finished_by_a_second_one():
    """The client moved 90 % of the way: close enough to count as taking the
    write, 20 ms short on a 200 ms correction. One refinement closes it."""
    server, recorder, clock = sendspin_server(bt={"adjust_scale": 0.9})

    report = await calibrate(server, recorder, sleep=clock.sleep)

    # Two before, one verifying, then two refinements: 90 % of each step
    # leaves 20 ms, then 2 ms, then 0.2 ms.
    assert server.plays == 5
    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0
    # The report spans the whole run: from where bt started to where it ended.
    bt = next(c for c in report.solution.corrections if c.player_id == "bt")
    assert bt.current_adjust_ms == 0
    assert bt.target_adjust_ms == pytest.approx(203 / 0.9, abs=1)


async def test_refining_can_be_switched_off():
    server, recorder, clock = sendspin_server(bt={"adjust_scale": 0.9})

    report = await calibrate(
        server, recorder, config=SessionConfig(refine=False), sleep=clock.sleep
    )

    assert server.plays == 3
    assert report.spread_after_ms > 10.0


async def test_a_round_the_listener_flagged_writes_nothing():
    server, _, clock = sendspin_server()

    class Listening(SimulatedRecorder):
        human_feedback = [{"player_id": "avr", "ok": False}]

    report = await calibrate(server, Listening(server), sleep=clock.sleep)

    assert server.writes == []
    assert report.applied == ()
    assert any("Гостиная (ресивер)" in p and "Nothing was written" in p for p in report.problems)


async def test_a_single_pass_is_still_possible():
    server, recorder, clock = sendspin_server()

    report = await calibrate(
        server, recorder, config=SessionConfig(measure_passes=1), sleep=clock.sleep
    )

    assert server.plays == 2
    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0


def test_combining_names_the_wandering_speaker_even_when_it_is_listed_first():
    """Were the first speaker the anchor and the one that wanders, every
    other speaker would look unstable instead. The anchor is chosen so they
    do not."""
    from dataclasses import replace

    from speaker_sync.calibration.measure import MeasurementAnalysis, SpeakerReading
    from speaker_sync.calibration.session import MeasurementPass

    def pass_with(**latencies):
        readings = {
            pid: SpeakerReading(pid, value, 0.05, 3, 0) for pid, value in latencies.items()
        }
        return MeasurementPass(
            analysis=MeasurementAnalysis(readings=readings, drift_ms=0.0),
            rounds=(),
            signal=None,
            sample_rate=48000,
        )

    first = pass_with(wobbly=10.0, a=50.0, b=80.0)
    second = pass_with(wobbly=130.0, a=150.0, b=180.0)  # same, apart from wobbly
    second = replace(second, analysis=replace(second.analysis))
    third = pass_with(wobbly=0.0, a=30.0, b=60.0)

    combined = combine_passes([first, second, third], ["wobbly", "a", "b"])

    # Against a: -40, -20 and -30 ms — 20 ms of wandering.
    assert set(combined.unstable()) == {"wobbly"}
    assert combined.unstable()["wobbly"] == pytest.approx(20.0)
