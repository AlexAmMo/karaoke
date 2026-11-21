"""Restore narrow, acoustically corroborated spelling details after fitting a score."""

from bisect import bisect_left, bisect_right
import re

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_ROW = re.compile(r"^[:*FRG]\s+(-?\d+)\s+\d+\s+-?\d+ ")
_APOSTROPHES = {
    "im",
    "youre",
    "theyre",
    "ive",
    "youve",
    "weve",
    "theyve",
    "couldve",
    "wouldve",
    "shouldve",
    "cant",
    "couldnt",
    "didnt",
    "doesnt",
    "dont",
    "hadnt",
    "hasnt",
    "havent",
    "isnt",
    "mustnt",
    "shouldnt",
    "wasnt",
    "werent",
    "wouldnt",
    "arent",
}


def _correction(printed, sung, titles):
    original = printed.casefold()
    heard = sung.casefold().replace("’", "'")
    if original in _APOSTROPHES and "'" in heard and heard.replace("'", "") == original:
        i = heard.index("'")
        fixed = printed[:i] + "'" + printed[i:]
        return fixed.capitalize() if original in {"im", "ive"} else fixed
    if heard in titles and len(original) == len(heard) and len(heard) >= 6:
        differences = [i for i, (a, b) in enumerate(zip(original, heard)) if a != b]
        if len(differences) == 2:
            a, b = differences
            if b == a + 1 and original[a] == heard[b] and original[b] == heard[a]:
                return printed[:a] + printed[b] + printed[a] + printed[b + 1 :]
    return None


def restore_spelling(chart, transcript, title, language):
    """Change only the printed characters. Preserve note types, timing, pitch and syllable breaks."""
    if language != "en":
        return chart, 0
    timeline = sorted(
        (row["start"], m.group())
        for phrase in transcript
        for row in phrase
        for m in _WORD.finditer(row["word"])
    )
    if not timeline:
        return chart, 0
    times = [t for t, _ in timeline]
    titles = {w.casefold() for w in _WORD.findall(title)}
    # chart_text emits absolute time with 60 ticks/s and zero GAP. Read both headers so
    # the frozen benchmark, including compatible older production charts, uses the same code.
    tick = 15 / float(re.search(r"^#BPM:(.+)$", chart, re.M)[1].strip().replace(",", "."))
    gap = float(re.search(r"^#GAP:(.+)$", chart, re.M)[1].strip().replace(",", ".")) / 1000
    chars, locations, when = [], [], []
    for line in re.finditer(r"^.*$", chart, re.M):
        row = _ROW.match(line[0])
        if row:
            position = gap + int(row[1]) * tick
            for i in range(row.end(), len(line[0].rstrip("\r"))):
                if line[0][i] != "~":
                    chars.append(line[0][i])
                    locations.append(line.start() + i)
                    when.append(position)
        elif line[0].startswith("-"):
            chars.append(" ")
            locations.append(None)
            when.append(None)
    edits = []
    changed = 0
    for word in _WORD.finditer("".join(chars)):
        start = when[word.start()]
        nearby = timeline[bisect_left(times, start - 0.35) : bisect_right(times, start + 0.35)]
        candidates = {
            fixed for _, heard in nearby if (fixed := _correction(word[0], heard, titles))
        }
        if len(candidates) != 1:
            continue
        replacement = candidates.pop()
        index = replacement.find("'")
        # Keep every music and line-break character intact, including intervening melismas.
        for k, old in enumerate(word[0]):
            pos = locations[word.start() + k]
            if index >= 0 and k == index:
                value = replacement[k : k + 2]
            else:
                value = replacement[k + int(0 <= index < k)]
            if value != old:
                edits.append((pos, value))
        changed += 1
    if edits:
        output = list(chart)
        for index, value in edits:
            output[index] = value
        chart = "".join(output)
    return chart, changed
