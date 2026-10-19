# Changelog

## 0.4.0 (fork EmilyMoonstone)
- **Speaker test (by ear)**: each speaker plays on its own, then none, and you answer each time — no hurry. It finds a speaker that keeps playing when muted.
- Every measurement pass ends with a **silent round** (every speaker muted). Test sound heard there means a speaker does not mute: it is named by its arrival, and nothing is written — its sound would otherwise pass for the other speakers' readings.

## 0.3.1 (fork EmilyMoonstone)
- Fix: a delay written to a speaker behind a universal player was reported as "did not arrive" although it had — the read-back took a missing value for 0 and did not wait for Music Assistant to apply it. It now waits up to 3 s and ignores places that report nothing.
- A check no longer blames the track format for a speaker whose delay jumped between its two passes, and says which format each finding comes from.

## 0.3.0 (fork EmilyMoonstone)
- **Live view while measuring**: microphone level meter, which speaker should be playing, whether the test sound is heard (good / quiet / none / overdriven) and a per-speaker tally.
- **Your ear counts**: during each round, "only this speaker audible?" — answering no stops the run from writing anything.
- **Test microphone** button to check the level before measuring.
- More robust: measures twice and takes the median, measures a third time when passes disagree or a speaker went unheard, names a speaker whose delay wanders between passes, and corrects up to twice more when a speaker applied only part of its correction.

## 0.2.0 (fork EmilyMoonstone)
- After a calibration, a check, a sign probe or the listening test, every speaker is back in the group, mute state and volume it was in before — also when the run fails or the browser is closed. No more helper group blocking a sync group ("can not be grouped with").
- A speaker without a delay setting (e.g. MassDroid) is measured as a **reference (not adjustable)**: the others are aligned to it, and it is never written to. When it arrives after the others, nothing is written and the report says why.
- Saved positions are applied the right way round on Sendspin speakers (they were written swapped).
- Each written delay is read back where it takes effect; the verification names a speaker that did not move as far as its correction asked.
- A speaker still in another group is released before grouping, so the test track reaches every speaker.
- The report shows per speaker: arrival, delay before → after, direction, and what the verification saw.
- The generated access token is no longer printed to the add-on log.

## 0.1.9
- Speaker list fits a phone screen: each speaker is a block, the name no longer squeezed into a narrow column.
- A group is no longer reported as missing its delay setting, and has no on/off switch (it is never measured anyway).
- Opened over plain http://, the page says up front that the microphone needs https:// instead of suggesting a separate tab, which would not help.
- The "open without the panel" link is readable in dark mode.

## 0.1.8
- **Check without changes**: measures the speakers as they are, at 44.1 and 48 kHz and all together, and writes nothing.
- **Listen to clicks**: clicks on every speaker at once to judge sync by ear.
- Calibration now uses 44.1 kHz, the format most music is in; the check warns about a speaker whose delay depends on the format.

## 0.1.7
- The verification pass ends with every speaker playing at once and checks that they line up together as they did one by one (about 6.5 s longer).

## 0.1.6
- Softer test sound: a longer, lower sweep (0.5 s, 150–6000 Hz) instead of the shrill whistle.
- More accurate with a reflection right behind the direct sound (e.g. phone on a table).
- An overdriven speaker's distortion can no longer be mistaken for its arrival.

## 0.1.5
- Fix blank panel after an update when a CDN (e.g. Cloudflare) cached the old script.

## 0.1.4
- Refresh button for the speaker list; player settings folded away.
- Updates now really rebuild with the new code (Docker cache fix).

## 0.1.3
- Delay direction known per speaker (Sendspin, AirPlay, Squeezelite); no manual sign check.
- Speaker list: setting names only when the delay setting is missing.

## 0.1.2
- Panel opens even when Music Assistant is unreachable, and says why.
- Music Assistant token is a required option.

## 0.1.1
- First add-on release.
