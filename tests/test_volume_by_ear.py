"""Test volumes: how loud each speaker plays while it is measured.

The level a speaker needs to be heard clearly at the measuring spot is not
the level the listener plays music at. The listener sets a test volume per
speaker by ear; every measurement uses it and puts the music volume back
afterwards. A speaker that goes unheard in a pass is turned up by itself.
"""

from __future__ import annotations

from speaker_sync.calibration.session import calibrate, check_alignment, volume_by_ear
from tests.test_end_to_end import make_server


def url(signal):
    return f"http://x/signal.wav?chirps={signal.chirp_count}&rate={signal.sample_rate}"


async def test_each_speaker_plays_alone_while_its_test_volume_is_set():
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes.update({"esp32": 30, "avr": 90, "bt": 55})
    seen = []

    async def listener(question):
        open_now = {s.player_id for s in server.speakers if not server._reported_mute(s.player_id)}
        seen.append((question["player_id"], question["volume"], open_now))
        # The page moves the slider: the volume goes straight to the server.
        await server.set_volume(question["player_id"], 70)
        return True

    result = await volume_by_ear(server, url, listener, sleep=clock.sleep)

    assert [(pid, vol) for pid, vol, _ in seen] == [("esp32", 30), ("avr", 90), ("bt", 55)]
    assert all(open_now == {pid} for pid, _, open_now in seen)
    assert result.finished
    assert result.volumes == {"esp32": 70, "avr": 70, "bt": 70}
    # The music volumes come back; the test volumes are the caller's to keep.
    assert server.volumes == {"esp32": 30, "avr": 90, "bt": 55}
    assert not any(server.is_grouped(s.player_id) for s in server.speakers)
    assert not any(p.muted for p in await server.list_players())


async def test_the_step_starts_from_the_test_volumes_already_kept():
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes.update({"esp32": 30, "avr": 30, "bt": 30})
    seen = []

    async def listener(question):
        seen.append(question["volume"])
        return True

    await volume_by_ear(server, url, listener, sleep=clock.sleep, test_volumes={"avr": 85})

    assert seen == [30, 85, 30]
    assert server.volumes["avr"] == 30


async def test_stopping_early_ends_the_step_and_leaves_things_tidy():
    server, recorder, clock = make_server(snr_db=30.0)
    asked = []

    async def listener(question):
        asked.append(question["player_id"])
        return False

    result = await volume_by_ear(server, url, listener, sleep=clock.sleep)

    assert asked == ["esp32"]
    assert not result.finished
    assert not any(server.is_grouped(s.player_id) for s in server.speakers)


async def test_a_calibration_measures_at_the_test_volumes_and_puts_music_volume_back():
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes.update({"esp32": 20, "avr": 25, "bt": 30})
    during = {}
    real = server.play_url

    async def noting(player_id, url_):
        during.update(server.volumes)
        await real(player_id, url_)

    server.play_url = noting

    report = await calibrate(
        server, recorder, sleep=clock.sleep, test_volumes={"esp32": 80, "bt": 75}
    )

    assert during == {"esp32": 80, "avr": 25, "bt": 75}
    assert server.volumes == {"esp32": 20, "avr": 25, "bt": 30}
    assert report.spread_after_ms is not None and report.spread_after_ms < 2.0


async def test_a_check_uses_the_test_volumes_too():
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes["avr"] = 10
    during = []
    real = server.play_url

    async def noting(player_id, url_):
        during.append(server.volumes.get("avr"))
        await real(player_id, url_)

    server.play_url = noting

    await check_alignment(server, recorder, sleep=clock.sleep, test_volumes={"avr": 60})

    assert during == [60, 60]
    assert server.volumes["avr"] == 10


async def test_a_speaker_unheard_in_a_pass_is_turned_up_for_the_next():
    server, recorder, clock = make_server(snr_db=30.0)
    server.volumes["bt"] = 15
    server.dropouts = {"bt": {1}}  # silent in the first pass
    levels = []
    real = server.play_url

    async def noting(player_id, url_):
        levels.append(server.volumes["bt"])
        await real(player_id, url_)

    server.play_url = noting

    report = await calibrate(server, recorder, sleep=clock.sleep)

    assert levels[0] == 15 and 40 in levels[1:]
    assert any("turned up to 40" in p for p in report.problems)
    assert server.volumes["bt"] == 15  # back to the music volume
