"""Turning measured latencies into ``sync_adjust`` values.

The arithmetic is small but every term earns its place: an already-applied
correction has to be backed out or the solver chases its own tail, the ±500 ms
limit has to be respected, and when the spread exceeds what one-sided delays
can cover the solver has to switch strategy rather than silently clamp.
"""

from __future__ import annotations

import pytest

from speaker_sync.calibration.solver import (
    SYNC_ADJUST_LIMIT_MS,
    PlayerMeasurement,
    solve,
)


def measurement(player_id, measured_ms, current=0, delay_range_ms=None):
    return PlayerMeasurement(
        player_id=player_id,
        name=player_id,
        measured_ms=measured_ms,
        current_adjust_ms=current,
        delay_range_ms=delay_range_ms,
    )


# What a Sendspin player reports: a latency compensation, so a positive value
# makes the player run *early*, and it cannot go below zero.
STATIC_DELAY = (0, 5000)


def landings(solution, sign=1):
    return [c.intrinsic_ms + sign * c.target_adjust_ms for c in solution.corrections]


def test_aligns_everyone_to_the_slowest_speaker():
    solution = solve(
        [
            measurement("esp32", 25.8),
            measurement("avr", 91.7),
            measurement("bluetooth", 228.7),
        ]
    )

    assert solution.strategy == "align_to_slowest"
    assert solution.fits
    # Nothing can be made faster, so every correction is a delay.
    assert all(c.target_adjust_ms >= 0 for c in solution.corrections)
    # The slowest speaker sets the target and needs no correction of its own.
    assert solution.corrections[2].target_adjust_ms == 0
    assert solution.spread_after_ms < 1.0


def test_an_advance_only_setting_pulls_everyone_forward_to_the_fastest():
    """The Sendspin case, which crashed on live hardware.

    ``static_delay_ms`` is a latency compensation: it can only make a player
    run earlier, and it refuses anything below zero. Aiming at the slowest
    speaker asks for a negative correction, and the server rejects the write
    outright — so the target has to be the fastest speaker instead, with
    everyone else brought forward to meet it.
    """
    solution = solve(
        [
            measurement("jack", 25.8, delay_range_ms=STATIC_DELAY),
            measurement("jbl", 254.8, delay_range_ms=STATIC_DELAY),
        ],
        sign=-1,
    )

    assert solution.strategy == "align_to_fastest"
    assert solution.fits
    assert all(c.target_adjust_ms >= 0 for c in solution.corrections)
    # The fastest speaker is the anchor; the other is advanced onto it.
    assert dict((c.player_id, c.target_adjust_ms) for c in solution.corrections) == {
        "jack": 0,
        "jbl": 229,
    }
    assert solution.spread_after_ms < 1.0


def test_a_range_the_spread_does_not_fit_into_is_reported_not_written_past():
    solution = solve(
        [
            measurement("jack", 0.0, delay_range_ms=(0, 100)),
            measurement("jbl", 400.0, delay_range_ms=(0, 100)),
        ],
        sign=-1,
    )

    assert not solution.fits
    assert all(0 <= c.target_adjust_ms <= 100 for c in solution.corrections)


def test_speakers_with_different_ranges_still_land_together():
    """One speaker on Music Assistant's own ±500 ms setting, one on Sendspin's
    advance-only one — a mixed group is the normal case, not the exception."""
    solution = solve(
        [
            measurement("jack", 25.8, delay_range_ms=STATIC_DELAY),
            measurement("airplay", 254.8, delay_range_ms=(-500, 500)),
        ],
        sign=-1,
    )

    assert solution.fits
    assert solution.spread_after_ms < 1.0
    by_id = {c.player_id: c for c in solution.corrections}
    assert by_id["jack"].target_adjust_ms >= 0


def test_existing_correction_is_backed_out():
    """A speaker measured *with* a correction already applied must not have it
    counted twice, or a second calibration pass would double the delay."""
    fresh = solve([measurement("a", 20.0), measurement("b", 120.0)])
    # Same physical speakers, but 'a' already carries the correction fresh
    # would have produced, so it now measures 100 ms later.
    already = solve([measurement("a", 120.0, current=100), measurement("b", 120.0)])

    assert fresh.corrections[0].target_adjust_ms == 100
    assert already.corrections[0].target_adjust_ms == 100
    assert already.corrections[0].delta_ms == 0
    assert already.changed() == ()


def test_spread_within_limit_prefers_one_sided_delays():
    solution = solve([measurement("a", 0.0), measurement("b", 480.0)])

    assert solution.strategy == "align_to_slowest"
    assert solution.fits
    assert solution.corrections[0].target_adjust_ms == 480


def test_spread_beyond_the_limit_centres_instead_of_clamping():
    """Aligning to the slowest needs the full spread of headroom; centring
    needs only half, which is what doubles the usable range to 1000 ms."""
    solution = solve([measurement("a", 0.0), measurement("b", 900.0)])

    assert solution.strategy == "centered"
    assert solution.fits
    assert solution.corrections[0].target_adjust_ms == 450
    assert solution.corrections[1].target_adjust_ms == -450
    assert solution.spread_after_ms < 1.0


def test_spread_beyond_even_centring_is_reported_not_hidden():
    solution = solve([measurement("a", 0.0), measurement("b", 1400.0)])

    assert not solution.fits
    assert len(solution.clamped_players) == 2
    assert all(abs(c.target_adjust_ms) <= SYNC_ADJUST_LIMIT_MS for c in solution.corrections)
    # The residual is honest about how far off the pair still is.
    assert abs(solution.spread_after_ms) > 300.0


def test_inverted_sign_convention_is_handled():
    """If a positive ``sync_adjust`` made a player run *early*, the same
    measurements must produce mirrored corrections."""
    normal = solve([measurement("a", 0.0), measurement("b", 200.0)], sign=1)
    inverted = solve([measurement("a", 0.0), measurement("b", 200.0)], sign=-1)

    assert normal.corrections[0].target_adjust_ms == 200
    assert inverted.corrections[0].target_adjust_ms == -200
    # Either way the speakers end up in the same place.
    assert max(landings(inverted, sign=-1)) - min(landings(inverted, sign=-1)) < 1.0


def test_integer_rounding_stays_within_half_a_millisecond():
    solution = solve([measurement("a", 0.0), measurement("b", 100.4), measurement("c", 200.6)])

    assert all(isinstance(c.target_adjust_ms, int) for c in solution.corrections)
    assert all(abs(c.residual_error_ms) <= 0.5 for c in solution.corrections)


def test_changed_lists_only_what_needs_writing():
    solution = solve(
        [measurement("a", 0.0, current=200), measurement("b", 200.0, current=0)]
    )

    changed = {c.player_id for c in solution.changed()}
    assert "b" not in changed


def test_already_aligned_speakers_need_no_writes():
    solution = solve([measurement("a", 50.0), measurement("b", 50.0), measurement("c", 50.0)])

    assert solution.changed() == ()
    assert solution.spread_before_ms < 1.0


def test_empty_input_is_not_an_error():
    solution = solve([])

    assert solution.corrections == ()
    assert solution.strategy == "empty"


def test_rejects_a_nonsense_sign():
    with pytest.raises(ValueError):
        solve([measurement("a", 0.0)], sign=0)


# ---------------------------------------------------------------- references


def sendspin(player_id, measured_ms, current=0):
    """A Sendspin speaker: 0-5000, and a larger value plays earlier."""
    return PlayerMeasurement(
        player_id=player_id,
        name=player_id,
        measured_ms=measured_ms,
        current_adjust_ms=current,
        delay_range_ms=(0, 5000),
        sign=-1,
    )


def reference(player_id, measured_ms):
    """A player without a delay setting: measured, never moved."""
    return PlayerMeasurement(
        player_id=player_id, name=player_id, measured_ms=measured_ms, current_adjust_ms=0, fixed=True
    )


def test_speakers_are_brought_forward_onto_an_earlier_reference():
    solution = solve([sendspin("pc", 140.0), sendspin("hifi", 125.0), reference("pixel", 100.0)])

    targets = {c.player_id: c.target_adjust_ms for c in solution.corrections}
    assert targets == {"pc": 40, "hifi": 25, "pixel": 0}
    assert solution.strategy == "align_to_reference"
    assert solution.fits
    assert solution.spread_after_ms < 1.0
    assert [c.player_id for c in solution.changed()] == ["pc", "hifi"]


def test_an_existing_correction_is_backed_out_before_aiming_at_the_reference():
    # pc already plays 30 ms early: measured 110, really 140 without it.
    solution = solve([sendspin("pc", 110.0, current=30), reference("pixel", 100.0)])

    assert {c.player_id: c.target_adjust_ms for c in solution.corrections}["pc"] == 40


def test_a_reference_arriving_after_the_others_writes_nothing():
    """Sendspin can only make a speaker play earlier. A reference that is
    later than the others cannot be met from the server at all."""
    solution = solve([sendspin("pc", 100.0, current=3), sendspin("hifi", 95.0), reference("pixel", 160.0)])

    assert solution.strategy == "reference_too_late"
    # hifi cannot arrive later than its own 95 ms, so that is the limit.
    assert solution.reference_late_ms == pytest.approx(65.0)
    assert solution.changed() == ()
    assert not solution.fits
    # Left exactly as found, including the correction already in force.
    assert {c.player_id: c.target_adjust_ms for c in solution.corrections} == {
        "pc": 3,
        "hifi": 0,
        "pixel": 0,
    }


def test_a_reference_within_rounding_of_reach_still_counts_as_met():
    solution = solve([sendspin("pc", 100.0), reference("pixel", 100.3)])

    assert solution.reference_late_ms is None
    assert solution.strategy == "align_to_reference"


def test_disagreeing_references_meet_halfway_and_say_by_how_much():
    solution = solve([sendspin("pc", 150.0), reference("pixel", 100.0), reference("tablet", 110.0)])

    assert solution.reference_disagreement_ms == pytest.approx(10.0)
    pc = next(c for c in solution.corrections if c.player_id == "pc")
    assert pc.target_adjust_ms == 45  # lands at 105, between the two
    assert {c.player_id: round(c.residual_error_ms, 1) for c in solution.references} == {
        "pixel": -5.0,
        "tablet": 5.0,
    }


def test_a_reference_is_never_among_the_writable_corrections():
    solution = solve([sendspin("pc", 140.0), reference("pixel", 100.0)])

    assert [c.player_id for c in solution.writable()] == ["pc"]


def test_a_late_reference_says_how_much_each_speaker_would_need_holding_back():
    """The live numbers: PC at 0, the hi-fi at +31.7, the phone on Bluetooth
    at +82.3. To meet the phone, the PC has to play 82 ms later and the hi-fi
    51 ms later than their setting allows — the hold-back to add elsewhere."""
    solution = solve([sendspin("pc", 0.0), sendspin("hifi", 31.7), reference("pixel", 82.3)])

    assert solution.strategy == "reference_too_late"
    assert solution.held_back_needed_ms == {
        "pc": pytest.approx(82.3),
        "hifi": pytest.approx(50.6),
    }


def test_a_reachable_reference_needs_no_holding_back():
    solution = solve([sendspin("pc", 140.0), reference("pixel", 100.0)])

    assert solution.held_back_needed_ms == {}
