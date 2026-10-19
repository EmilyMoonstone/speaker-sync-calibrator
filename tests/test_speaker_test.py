"""The speaker test: each speaker alone, then none, judged by the listener.

A speaker that plays on when muted does not spoil a measurement round, it
replaces it — the numbers still look plausible. The ear in the room is the
one instrument that knows which speaker is sounding, and this test gives it
the time to answer.
"""

from __future__ import annotations

import pytest

from speaker_sync.calibration.session import speaker_test
from tests.test_end_to_end import make_server


def url(signal):
    return f"http://x/signal.wav?chirps={signal.chirp_count}&rate={signal.sample_rate}"


def ear(server, answers):
    """Answers in turn, and notes which speakers were open at each question."""
    asked = []

    async def ask(question):
        open_now = {
            s.player_id for s in server.speakers if not server._reported_mute(s.player_id)
        }
        asked.append((question, open_now))
        return answers[len(asked) - 1]

    return ask, asked


async def test_each_speaker_is_asked_about_alone_and_then_the_silence():
    server, recorder, clock = make_server(snr_db=30.0)
    ask, asked = ear(server, [True, True, True, True])

    result = await speaker_test(server, url, ask, sleep=clock.sleep)

    assert [q["step"] for q, _ in asked] == ["alone", "alone", "alone", "silence"]
    for question, open_now in asked[:3]:
        assert open_now == {question["player_id"]}
    assert asked[3][1] == set()
    assert result.passed and result.problems == []
    assert server.played_urls and "chirps=" in server.played_urls[0]


async def test_what_the_listener_heard_is_reported():
    server, recorder, clock = make_server(snr_db=30.0)
    ask, _ = ear(server, [True, False, None, False])

    result = await speaker_test(server, url, ask, sleep=clock.sleep)

    assert not result.passed
    text = " ".join(result.problems)
    assert "Гостиная (ресивер)" in text and "something else" in text
    assert "no answer for «Спальня (Bluetooth)»" in text
    assert "still heard the test sound" in text


async def test_the_speakers_are_left_as_they_were():
    server, recorder, clock = make_server(snr_db=30.0)
    await server.set_muted("avr", True)
    ask, _ = ear(server, [True, True, True, True])

    await speaker_test(server, url, ask, sleep=clock.sleep)

    assert not any(server.is_grouped(s.player_id) for s in server.speakers)
    assert {p.player_id: p.muted for p in await server.list_players()} == {
        "esp32": False,
        "avr": True,
        "bt": False,
    }


async def test_no_speaker_to_test_is_refused():
    from speaker_sync.ma.backend import SelectedSpeakers

    server, recorder, clock = make_server(snr_db=30.0)
    off = SelectedSpeakers(server, frozenset({"esp32", "avr", "bt"}))

    with pytest.raises(ValueError):
        await speaker_test(off, url, lambda q: None, sleep=clock.sleep)
