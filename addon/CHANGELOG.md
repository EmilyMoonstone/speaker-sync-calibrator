# Changelog

## 0.7.3 (fork EmilyMoonstone)
- A correction that misses by less than the speaker wanders on its own is shown as **?** ("cannot tell whether the new delay is in force") rather than a red ✗ claiming the client ignored it. Live, the PC wandered 8 ms between passes and was asked to move 7 ms.
- Notes about a round name the speaker («Emily-PC») instead of its internal id.

## 0.7.2 (fork EmilyMoonstone)
- Fix: a speaker's current delay could read as 0 for every player, not only linked protocols — Music Assistant sends the value as `current_value` next to an empty `value`, and the empty one won. When a setting arrives without its value, the add-on now asks Music Assistant for it directly. Read-back after a write now sees the real value too.

## 0.7.1 (fork EmilyMoonstone)
- Fix: a speaker whose delay belongs to a linked protocol (a universal player over Sendspin) was read as 0 when Music Assistant's copy on the player itself had never been set — while the protocol player behind it played with a different delay. The calibration then started from the wrong value and moved that speaker the wrong way (live: 137 ms read as 0, 51 written, 86 ms later instead of 51 earlier). The delay is now read where it takes effect.

## 0.7.0 (fork EmilyMoonstone)
- **Sync test.** One button below the steps: a single short round measures whether all speakers play together right now, with every setting in force — Music Assistant's delays, a client's own, a mixer's output delay — and changes nothing. In sync, or which speaker is how many ms after which.

## 0.6.1 (fork EmilyMoonstone)
- When the reference arrives too late to be met, the report says per speaker how much later it would have to play — the hold-back to add outside Music Assistant (the player's own delay, or an output delay such as Voicemeeter's) before calibrating again.

## 0.6.0 (fork EmilyMoonstone)
- **Test volume, by ear** (new step 3): each speaker plays on its own while you slide its volume until the microphone hears it well at the measuring spot — the meter shows it. The values are kept as test volumes, used for every measurement, and your music volume comes back afterwards.
- A speaker the microphone does not hear in a pass is turned up for the next one by itself (+20, at least 40), and back afterwards.
- Fix: a phone app (MassDroid) could be left at volume 0 after a run. An unreported volume is no longer read as 0, and a volume is only put back when the run itself changed it or it fell to 0.

## 0.5.1 (fork EmilyMoonstone)
- Rounds are timed from the first chirp the microphone actually hears, and every speaker switch happens halfway through the pause between two chirps. The stream starts well after "play" (set-up and client buffers), so switching by the play command cut the last chirp of a round — heard as a clipped chirp, measured as one reading a few ms off.
- If no test sound is heard within 10 s of the start, the pass stops with a clear message instead of measuring blind.
- Each pass writes a one-line summary to the add-on log (readings, drift, silent round, problems).

## 0.5.0 (fork EmilyMoonstone)
- **Simpler page.** Three numbered steps — check the microphone, speaker test, calibrate. The check, the listening test, the round length and all explanations are under "More".
- **Results in one sentence** with a mark (in sync / better but … / nothing written because …). Notes and the per-speaker table open on request, and by themselves when something is wrong.
- **Speakers** as a short list with a switch each; connection, delay setting and player settings under "Details". Groups and players hidden in Music Assistant are folded away.
- A result in doubt offers no "Save".

## 0.4.1 (fork EmilyMoonstone)
- Rounds keep to the test track's timetable, so slow mute commands no longer slide round boundaries onto the wrong speaker.
- Writing is all or nothing: a write refused half way puts the earlier ones back (also when applying a position).
- Every command to Music Assistant has a time limit; a server that never answers ends the run with a message instead of hanging it.
- A result in doubt (a muted speaker played on, or you heard something else) cannot be saved as a position.
- After a dropped connection the page is usable again without a reload, and stops streaming the microphone.
- Speaker test: a late answer is no longer taken for the next question.
- The socket ignores malformed messages instead of ending the run; the live view switching off never stops a measurement.
- "0 dB unexplained" is now said as a share ("100 % of it unexplained").

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
