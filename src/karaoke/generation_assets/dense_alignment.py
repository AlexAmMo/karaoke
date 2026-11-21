"""Exact CTC Viterbi traceback for long songs with a bounded working set."""

import math

import numpy as np


def checkpointed_path(log_probs, targets, error=ValueError, *, block_frames=None):
    """Keep sparse forward scores. Reconstruct one interval's decisions at a time."""
    frames = len(log_probs)
    repeats = sum(a == b for a, b in zip(targets, targets[1:]))
    if not len(targets) or frames < len(targets) + repeats:
        raise error("La letra contiene más caracteres de los que caben en la grabación.")
    labels = np.zeros(2 * len(targets) + 1, dtype=np.intp)
    labels[1::2] = targets
    # The CTC graph can advance two states only onto a different nonblank label.
    skip = (labels[2:] != 0) & (labels[2:] != labels[:-2])
    dtype = np.result_type(log_probs.dtype, np.float32)
    alpha = np.full(len(labels), -np.inf, dtype=dtype)
    alpha[:2] = log_probs[0, labels[:2]]
    # A checkpoint uses one float per state; a traceback decision uses one byte.
    block = block_frames or max(1, math.isqrt(frames * np.dtype(dtype).itemsize))
    checkpoints = [alpha]

    def advance(before, t, moves=None):
        after = before.copy()
        if moves is None:
            np.maximum(after[1:], before[:-1], out=after[1:])
            np.maximum(after[2:], before[:-2], out=after[2:], where=skip)
        else:
            # Strict comparisons give the usual CTC tie order: stay, one, two.
            moves.fill(0)
            step_better = before[:-1] > after[1:]
            np.copyto(after[1:], before[:-1], where=step_better)
            moves[1:][step_better] = 1
            skip_better = skip & (before[:-2] > after[2:])
            np.copyto(after[2:], before[:-2], where=skip_better)
            moves[2:][skip_better] = 2
        after += log_probs[t, labels]
        return after

    for t in range(1, frames):
        alpha = advance(alpha, t)
        if t % block == 0:
            checkpoints.append(alpha)
    state = len(labels) - (1 if alpha[-1] >= alpha[-2] else 2)
    if not np.isfinite(alpha[state]):
        raise error("La letra no tiene una alineación válida con esta grabación.")
    path = np.empty(frames, dtype=np.int64)
    end = frames - 1
    while end > 0:
        start = (end - 1) // block * block
        alpha = checkpoints[start // block]
        decisions = np.empty((end - start, len(labels)), dtype=np.uint8)
        for t in range(start + 1, end + 1):
            alpha = advance(alpha, t, decisions[t - start - 1])
        for t in range(end, start, -1):
            path[t] = state
            state -= int(decisions[t - start - 1, state])
        end = start
    path[0] = state
    return path


def align(aligner, voice, lyrics, pitch, language, *, cell_limit=240_000_000):
    """Use the original path for small inputs, sized by the actual CTC graph."""
    original = aligner.forced_align
    stats = {}

    def bounded(emissions, targets):
        cells = len(emissions) * (2 * len(targets) + 1)
        if cells <= cell_limit:
            return original(emissions, targets)
        stats["alignment_checkpointed"] = True
        stats["alignment_traceback_cells"] = cells
        return checkpointed_path(emissions, targets, error=aligner.AlignmentError)

    # A generation worker serves one song at a time in its own interpreter.
    # The pinned adapter passes gated emissions and its exact token graph to forced_align.
    aligner.forced_align = bounded
    try:
        timing = aligner.align_lyrics(str(voice), lyrics, pitch_data=pitch, language=language)
    finally:
        aligner.forced_align = original
    return timing, stats
