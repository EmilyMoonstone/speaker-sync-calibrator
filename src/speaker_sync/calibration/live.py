"""Live feedback while a measurement runs: is the test sound reaching the phone?

The measurement itself is only analysed once the recording is complete, which
leaves the person holding the phone watching a progress bar for half a minute
and finding out afterwards that a speaker was too quiet, or not playing at all.
This module looks at the audio as it streams in and answers the questions that
can be answered straight away:

* is a chirp being heard right now, and how far above the noise;
* is the microphone level usable — not lost in the noise, not clipping.

It deliberately does not try to measure latency. That needs the whole
recording, the round schedule and the drift correction; a live guess at it
would only be a second, worse answer. The verdicts here are about whether the
measurement *can* work, so a bad setup is noticed during the round it affects.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from speaker_sync.dsp.detect import (
    DEFAULT_MIN_PSR_DB,
    correlation_envelope,
    detection_threshold,
    estimate_noise_floor,
)
from speaker_sync.dsp.signals import TestSignal

CLIPPING_PEAK = 0.98
"""A sample this close to full scale means the microphone is overdriven."""

COMFORTABLE_MARGIN_DB = 10.0
"""How far above the detection threshold a chirp should land to be "ok".

Just over the threshold is enough to be found, but a chirp that barely clears
it in one window will miss it in the next — on a phone moved slightly, or with
a door closing. Ten decibels of margin is what keeps every round readable.
"""

SILENCE_DB = -120.0
"""What a window of digital silence reports as its level, instead of -inf."""


@dataclass(frozen=True)
class LiveReading:
    """One window of the live recording, judged."""

    at_seconds: float
    """End of the window, in seconds since the recording started."""

    level_db: float
    """RMS level of the window, in dBFS."""

    peak_db: float
    """Largest sample of the window, in dBFS."""

    margin_db: float | None
    """How far the strongest chirp-shaped peak cleared the detection threshold.

    Negative when nothing chirp-like stood out of the noise; ``None`` for a
    window too short to judge.
    """

    @property
    def heard(self) -> bool:
        return self.margin_db is not None and self.margin_db >= 0.0

    @property
    def clipping(self) -> bool:
        return self.peak_db >= float(20.0 * np.log10(CLIPPING_PEAK))

    @property
    def verdict(self) -> str:
        """``clipping``, ``silent``, ``quiet`` or ``ok`` — what the page shows."""
        if self.clipping:
            return "clipping"
        if not self.heard:
            return "silent"
        if self.margin_db < COMFORTABLE_MARGIN_DB:
            return "quiet"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "at_seconds": round(self.at_seconds, 2),
            "level_db": round(self.level_db, 1),
            "peak_db": round(self.peak_db, 1),
            "margin_db": None if self.margin_db is None else round(self.margin_db, 1),
            "heard": self.heard,
            "verdict": self.verdict,
        }


def _db(value: float) -> float:
    return float(20.0 * np.log10(value)) if value > 0.0 else SILENCE_DB


class LiveMonitor:
    """Judges a streamed recording one chirp period at a time.

    Windows are a period plus one chirp long and advance by a period, so every
    chirp lies wholly inside at least one of them however the recording's
    start falls against the track's grid — which is unknown until the end.
    """

    def __init__(self, signal: TestSignal, sample_rate: int) -> None:
        self.sample_rate = int(sample_rate)
        self._reference = signal.reference(self.sample_rate)
        self._f_start = signal.f_start
        self._f_end = signal.f_end
        self._step = max(1, int(round(signal.period_seconds * self.sample_rate)))
        self._window = self._step + len(self._reference)
        self._pending = np.zeros(0, dtype=np.float64)
        self._consumed = 0
        """Samples already stepped past, for the readings' timestamps."""

    def feed(self, samples: np.ndarray) -> list[LiveReading]:
        """Take the next block of audio; return the windows it completed."""
        self._pending = np.concatenate([self._pending, np.asarray(samples, dtype=np.float64)])
        readings = []
        while len(self._pending) >= self._window:
            readings.append(self._judge(self._pending[: self._window]))
            self._pending = self._pending[self._step :]
            self._consumed += self._step
        return readings

    def _judge(self, window: np.ndarray) -> LiveReading:
        rms = float(np.sqrt(np.mean(window**2)))
        peak = float(np.max(np.abs(window)))
        envelope = correlation_envelope(
            window,
            self._reference,
            sample_rate=self.sample_rate,
            f_start=self._f_start,
            f_end=self._f_end,
        )
        noise = estimate_noise_floor(envelope)
        threshold = detection_threshold(noise, len(envelope), DEFAULT_MIN_PSR_DB)
        strongest = float(np.max(envelope)) if len(envelope) else 0.0
        margin = (
            None
            if threshold <= 0.0 or strongest <= 0.0
            else float(20.0 * np.log10(strongest / threshold))
        )
        return LiveReading(
            at_seconds=(self._consumed + len(window)) / self.sample_rate,
            level_db=_db(rms),
            peak_db=_db(peak),
            margin_db=margin,
        )
