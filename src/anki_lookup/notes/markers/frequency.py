"""Aggregate frequency across dictionaries.

Two axes, and mixing them is meaningless:

* **rank-based** — 1 is the most common word. Lower is commoner.
* **occurrence-based** — a raw corpus count. Higher is commoner.

A dictionary declares which it is, and the two are never averaged together.
"""

from __future__ import annotations

import re

from ...dictionary.models import FrequencyInfo

RANK_MODE = "rank-based"
OCCURRENCE_MODE = "occurrence-based"

#: What a marker renders when no dictionary has a figure.
#:
#: Not empty, and not the same for both: Anki sorts fields as text, and these exist to
#: be sorted on. "Unknown" has to land at the *uncommon* end, which is a large number
#: for ranks and a small one for occurrences. An empty field would sort first and
#: quietly put every unknown word at the front of a frequency-sorted deck.
NO_RANK = "9999999"
NO_OCCURRENCE = "0"

_LEADING_NUMBER = re.compile(r"^\s*(\d+)")


def frequency_numbers(
    frequencies: tuple[FrequencyInfo, ...],
    frequency_mode: str,
) -> tuple[float, ...]:
    """Usable figures for one mode, one per dictionary.

    First entry per dictionary wins. A dictionary can list several figures for the
    same headword (one per reading); taking all of them would weight that dictionary
    more heavily than the others purely because it is more detailed.
    """

    seen: set[str] = set()
    numbers: list[float] = []

    for item in frequencies:
        if item.frequency_mode != frequency_mode:
            continue
        if item.dictionary in seen:
            continue

        value = _usable_value(item)
        if value is None or value <= 0:
            continue

        seen.add(item.dictionary)
        numbers.append(value)

    return tuple(numbers)


def _usable_value(item: FrequencyInfo) -> float | None:
    """Prefer a number written into the display value, else the numeric field.

    Dictionaries often carry a display value like ``"1234 (common)"`` alongside a less
    precise numeric field, so the leading integer of the display string is the better
    source when it is there.
    """

    match = _LEADING_NUMBER.match(item.display_value or "")
    if match:
        return float(match.group(1))
    return item.value


def harmonic_mean(numbers: tuple[float, ...]) -> int:
    """Harmonic mean, floored. ``-1`` when there is nothing to average.

    The right aggregation for ranks, and the default for that reason: it is dominated
    by the smallest value, so if any dictionary says a word is common, it is common.
    An arithmetic mean lets one obscure dictionary's rank of 50,000 drag a genuinely
    everyday word down the list.
    """

    if not numbers:
        return -1
    total = sum(1 / number for number in numbers)
    if total <= 0:
        return -1
    return int(len(numbers) / total)


def average_mean(numbers: tuple[float, ...]) -> int:
    """Arithmetic mean, floored. ``-1`` when there is nothing to average."""

    if not numbers:
        return -1
    return int(sum(numbers) / len(numbers))


def render_aggregate(
    frequencies: tuple[FrequencyInfo, ...],
    frequency_mode: str,
    harmonic: bool,
) -> str:
    numbers = frequency_numbers(frequencies, frequency_mode)
    value = harmonic_mean(numbers) if harmonic else average_mean(numbers)
    if value < 0:
        return NO_RANK if frequency_mode == RANK_MODE else NO_OCCURRENCE
    return str(value)


def render_list(frequencies: tuple[FrequencyInfo, ...]) -> str:
    """Every dictionary's figure, attributed, one per line."""

    lines = []
    for item in frequencies:
        shown = item.display_value or (str(int(item.value)) if item.value is not None else "")
        if not shown:
            continue
        lines.append(f"{item.dictionary}: {shown}")
    return "\n".join(lines)
