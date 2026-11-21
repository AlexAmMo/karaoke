"""Apply Tune Studio's published 24-feature note corrector to this chart's vocal events.

Feature definitions follow the MIT-licensed Tune Studio training pipeline by ZerNico.
https://github.com/ZerNico/tunestudio/blob/88d4fac5cb6df35c593cc16e730eddd10d96de39/training/src/tunestudio_training/pipeline/notefix.py
"""

import numpy as np

SHIFTS = np.array([-2, -1, 0, 1, 2])


def fold(interval):
    return (interval + 6) % 12 - 6


def refine(notes, pitch, session):
    """Apply corrections only to pitched notes. Report changes for the local review manifest."""
    scored = [n for n in notes if n.get("pitch") is not None and not n.get("is_rap")]
    hz, times = np.asarray(pitch["frequencies"]), np.asarray(pitch["times"])
    positive = hz > 0
    if not scored or positive.sum() < 4:
        return 0
    f0 = np.full(len(hz), np.nan, dtype=np.float32)
    f0[positive] = 69 + 12 * np.log2(hz[positive] / 440)
    voiced = f0[positive]
    tuning = float(np.angle(np.mean(np.exp(2j * np.pi * voiced))) / (2 * np.pi))
    histogram = np.bincount(np.rint(voiced - tuning).astype(int) % 12, minlength=12)
    major = np.array([0, 2, 4, 5, 7, 9, 11])
    root = max(range(12), key=lambda k: histogram[(major + k) % 12].sum())
    scale = set((major + root) % 12)

    matrix = []
    pitches = [n["pitch"] for n in scored]
    for i, note in enumerate(scored):
        midi = pitches[i]
        left, right = np.searchsorted(times, (note["start"], note["end"]))
        frames = f0[left:right]
        observed = frames[np.isfinite(frames)]
        raw = float(np.median(observed)) if len(observed) else midi
        if len(observed):
            relative = fold(observed - np.float32(tuning) - midi)
            third = max(1, len(relative) // 3)
            tail = relative[third:] if len(relative) > 1 else relative
            contour = [
                np.median(relative),
                np.mean(relative),
                *np.percentile(relative, [10, 25, 75, 90]),
                np.std(relative),
                np.median(relative[:third]),
                np.median(tail),
                len(observed) / len(frames),
            ]
        else:
            contour = [0.0] * 10
        continuation = int(note["syllable"].strip() == "~")
        matrix.append(
            [
                fold(raw - midi),
                fold(raw - tuning - round(raw - tuning)),
                tuning,
                note["end"] - note["start"],
                continuation,
                1 + continuation,
                0,
                *(float((midi + d) % 12 in scale) for d in SHIFTS),
                *contour,
                np.clip(midi - pitches[i - 1], -12, 12) if i else 0,
                np.clip(pitches[i + 1] - midi, -12, 12) if i + 1 < len(scored) else 0,
            ]
        )
    probabilities = session.run(
        ["probabilities"], {"features": np.asarray(matrix, dtype=np.float32)}
    )[0]
    changed = 0
    for note, row in zip(scored, probabilities, strict=True):
        choice = int(np.argmax(row))
        if row[choice] >= 0.5 and SHIFTS[choice]:
            note["pitch"] += int(SHIFTS[choice])
            changed += 1
    return changed
