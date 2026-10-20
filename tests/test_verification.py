"""Whether a written correction moved its speaker, told apart from wandering.

The live PC wandered 8.1 ms between passes on its own; asked to move 7 ms, it
measured 0.4 ms. That is no evidence the write was ignored — the measurement
cannot see a move that small on that speaker — and saying "not in force"
sends the listener restarting a client that was fine.
"""

from __future__ import annotations

from speaker_sync.calibration.session import PlayerVerification, _check_the_movements


def test_a_miss_within_the_speakers_own_wandering_is_unclear_not_failed():
    check = PlayerVerification("pc", expected_ms=7.0, observed_ms=0.4, noise_ms=8.1)

    assert not check.held
    assert check.unclear
    (note,) = _check_the_movements({"pc": check}, {"pc": "Emily-PC"})
    assert "«Emily-PC»" in note and "cannot tell" in note
    assert "not (fully) in force" not in note


def test_a_miss_beyond_the_wandering_is_still_a_failure():
    check = PlayerVerification("avr", expected_ms=-51.0, observed_ms=85.4, noise_ms=3.9)

    assert not check.held and not check.unclear
    (note,) = _check_the_movements({"avr": check}, {"avr": "Anlage"})
    assert "not (fully) in force" in note


def test_a_steady_speaker_is_held_to_the_usual_tolerance():
    check = PlayerVerification("pc", expected_ms=7.0, observed_ms=0.4)

    assert not check.held and not check.unclear
