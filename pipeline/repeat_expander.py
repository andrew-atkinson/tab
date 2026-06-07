"""
repeat_expander.py
==================
Convert a written tab score (with repeat signs and/or gap bar numbering) into
performance order.

Two distinct repeat encodings appear in the classtab library:

Gap-encoded repeats (El-Negrito style)
    The transcriber numbers bars sequentially through the *full* performance
    (including repeated sections), then writes only the *unique* bars in the
    tab.  The "gap" bar numbers — integers in [min_key, max_key] absent from
    tab.measures — are the bars that a performer plays by returning to an
    earlier section.  A gap-alias map resolves each gap number to its source
    bar.  The full performance sequence is simply bar numbers min_key …
    max_key, with gaps filled from aliases.  No sign expansion is needed.

Sign-encoded repeats (Barrios style)
    No gaps in the numbering; instead explicit repeat signs (||: … :||) and
    optional volta brackets appear on the measures.  The performance sequence
    is the written sequence with repeat sections inserted a second time.

Detection heuristic
    If bar_count_gaps / bar_count_written > GAP_RATIO_THRESHOLD the piece is
    treated as gap-encoded.  Otherwise sign-based expansion is applied.

Public API
----------
    expand_repeats(tab)               -> ExpandedScore
    build_gap_alias_map(measures)     -> dict[int, int]
    expansion_summary(expanded)       -> str
"""

from __future__ import annotations
from models import TabFile, MeasureData, ExpandedMeasure, ExpandedScore

# If more than this fraction of bar-span bars are gaps, treat as gap-encoded.
GAP_RATIO_THRESHOLD = 0.05   # 5 %


# ---------------------------------------------------------------------------
# Gap-alias map (shared by both strategies)
# ---------------------------------------------------------------------------

def build_gap_alias_map(measures: dict[int, MeasureData]) -> dict[int, int]:
    """
    Build {gap_bar_number: source_bar_number} from the repeat structure.

    Each integer in [min_key, max_key] absent from *measures* is a gap bar.
    Gaps are attributed to repeat sections by matching them to the closest
    preceding repeat section in order.

    Algorithm
    ---------
    For each (start_key, end_key) repeat pair (from ||: … :| markers):
      1.  The section bars are keys[start_key .. end_key].
      2.  Gap bars immediately following the :| (before the next written bar)
          are the second-pass bars; they map cyclically to section bars.
    Any remaining unaliased gaps are mapped to the nearest preceding written bar.
    """
    if not measures:
        return {}

    keys = sorted(measures.keys())
    mn, mx = keys[0], keys[-1]
    all_ints = set(range(mn, mx + 1))
    gaps = sorted(all_ints - set(keys))
    if not gaps:
        return {}

    # Collect repeat pairs from markers on the measures.
    stack: list[int] = []
    repeat_pairs: list[tuple[int, int]] = []
    for k in keys:
        md = measures[k]
        if md.repeat_start:
            stack.append(k)
        if md.repeat_end:
            start = stack.pop() if stack else keys[0]
            repeat_pairs.append((start, k))

    alias: dict[int, int] = {}

    for start_key, end_key in repeat_pairs:
        section_bars = [k for k in keys if start_key <= k <= end_key]
        if not section_bars:
            continue
        # Find the next written bar after the section close.
        next_written = next((k for k in keys if k > end_key), mx + 1)
        # Gaps that fall between the section end and the next written bar.
        gap_block = [g for g in gaps if end_key < g < next_written
                     and g not in alias]
        for i, g in enumerate(gap_block):
            alias[g] = section_bars[i % len(section_bars)]

    # Remaining unaliased gaps: map to nearest preceding written bar.
    for g in gaps:
        if g not in alias:
            before = [k for k in keys if k < g]
            alias[g] = before[-1] if before else keys[0]

    return alias


# ---------------------------------------------------------------------------
# Strategy 1 — gap-encoded repeats
# ---------------------------------------------------------------------------

def _expand_gap_encoded(tab: TabFile) -> ExpandedScore:
    """
    Produce performance order by walking bar numbers min_key … max_key and
    filling gaps via the alias map.

    This gives exactly bar_count_span measures, which equals the MIDI's
    non-empty measure count for gap-encoded pieces.
    """
    measures  = tab.measures
    keys      = sorted(measures.keys())
    alias     = build_gap_alias_map(measures)
    mn, mx    = keys[0], keys[-1]

    expanded: list[ExpandedMeasure] = []
    for bar_num in range(mn, mx + 1):
        src_num = alias.get(bar_num, bar_num)
        src_md  = measures.get(src_num)
        if src_md is None:
            continue
        is_repeated = bar_num != src_num
        expanded.append(ExpandedMeasure(
            source_num   = src_num,
            notes        = list(src_md.notes),
            barres       = list(src_md.barres),
            repeat_start = src_md.repeat_start and not is_repeated,
            repeat_end   = src_md.repeat_end   and not is_repeated,
            volta        = src_md.volta,
            pass_number  = 2 if is_repeated else 1,
        ))

    return ExpandedScore(measures=expanded, metadata=tab.metadata)


# ---------------------------------------------------------------------------
# Strategy 2 — sign-encoded repeats
# ---------------------------------------------------------------------------

def _expand_sign_encoded(tab: TabFile) -> ExpandedScore:
    """
    Expand ||: … :|| repeat signs.  Volta brackets are handled: first-ending
    bars are played on pass 1 only; second-ending bars replace them on pass 2.

    Nested repeats are resolved by a stack (innermost first).
    """
    measures = tab.measures
    keys     = sorted(measures.keys())
    expanded: list[ExpandedMeasure] = []

    def _em(k: int, pass_number: int) -> ExpandedMeasure:
        md = measures[k]
        return ExpandedMeasure(
            source_num   = k,
            notes        = list(md.notes),
            barres       = list(md.barres),
            repeat_start = md.repeat_start,
            repeat_end   = md.repeat_end,
            volta        = md.volta,
            pass_number  = pass_number,
        )

    i = 0
    repeat_stack: list[int] = []   # stack of indices into `keys` for ||:
    processed_ends: set[int] = set()

    while i < len(keys):
        k  = keys[i]
        md = measures[k]

        if md.repeat_start:
            repeat_stack.append(i)

        expanded.append(_em(k, 1))

        if md.repeat_end and i not in processed_ends:
            processed_ends.add(i)
            if repeat_stack:
                start_i = repeat_stack.pop()
            else:
                start_i = 0

            # Second pass: replay from start_i to i, respecting volta brackets.
            # Collect the first-ending (volta=1) bar indices within the section.
            volta1_range = {
                j for j in range(start_i, i + 1)
                if measures[keys[j]].volta == 1
            }
            # Find where the 2nd ending begins (if any).
            volta2_start = next(
                (j for j in range(start_i, i + 1) if measures[keys[j]].volta == 2),
                None,
            )

            for j in range(start_i, i + 1):
                if j in volta1_range:
                    continue   # skip 1st ending on second pass
                expanded.append(_em(keys[j], 2))

        i += 1

    return ExpandedScore(measures=expanded, metadata=tab.metadata)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def expand_repeats(tab: TabFile) -> ExpandedScore:
    """
    Expand *tab* into performance order.

    Automatically selects gap-encoded or sign-encoded strategy based on the
    ratio of gap bars to written bars.  See module docstring.
    """
    measures  = tab.measures
    keys      = sorted(measures.keys())
    if not keys:
        return ExpandedScore(measures=[], metadata=tab.metadata)

    mn, mx    = keys[0], keys[-1]
    span      = mx - mn + 1
    written   = len(keys)
    gap_ratio = (span - written) / max(1, written)

    if gap_ratio > GAP_RATIO_THRESHOLD:
        return _expand_gap_encoded(tab)
    else:
        return _expand_sign_encoded(tab)


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------

def expansion_summary(expanded: ExpandedScore) -> str:
    if not expanded.measures:
        return '0 measures'
    repeated = sum(1 for m in expanded.measures if m.pass_number > 1)
    sources  = sorted({m.source_num for m in expanded.measures})
    return (
        f'{len(expanded.measures)} measures in performance order '
        f'({len(expanded.measures) - repeated} unique + {repeated} repeat passes), '
        f'source bars {sources[0]}–{sources[-1]}'
    )
