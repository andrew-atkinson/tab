"""
test_time_signatures.py
=======================
Tests for time signature parsing and encoding across the corpus.

Three suites:

1. META SUITE (200 pieces, seed=11)
   Check that the time signature declared in the tab header is correctly
   extracted by topmatter_parser and written as the XML first-measure time
   signature (overriding the MIDI default, which is almost always 4/4).

2. CHANGE SUITE (all pieces with MIDI time sig changes)
   Check that mid-piece time signature changes (from MIDI meta-messages) are
   correctly emitted as <attributes><time> elements in the MusicXML output.
   Every time the MIDI time sig changes relative to the previous measure, the
   XML must have a <time> element in that measure.

3. NO-DUPLICATE SUITE
   Check that the XML never emits two consecutive <time> elements with the
   same value (i.e. no redundant re-declarations).

Usage:
    python pipeline/test_time_signatures.py
"""
from __future__ import annotations
import sys, random, traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import xml.etree.ElementTree as ET

HERE     = Path(__file__).parent
ROOT     = HERE.parent
CLASSTAB = ROOT / 'tab'
sys.path.insert(0, str(HERE))

SEED_META   = 11
N_META      = 150
SEED_CHANGE = 17
N_CHANGE    = 150   # pieces to scan for MIDI time sig changes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def all_txt_paths() -> list[Path]:
    return sorted(CLASSTAB.glob('*.txt'))

def matching_mid(txt_path: Path) -> Optional[Path]:
    mid = txt_path.with_suffix('.mid')
    return mid if mid.exists() else None

def pct(num, den):
    return f'{100*num/den:.1f}%' if den else 'n/a'

def _xml_time_sigs(root: ET.Element) -> list[tuple[int, str, int, int]]:
    """Return [(measure_number_str, measure_el_idx, num, denom)] for every
    <time> element found anywhere in the score."""
    result = []
    for meas_el in root.findall('.//measure'):
        t = meas_el.find('.//time')
        if t is not None:
            num_el  = t.find('beats')
            den_el  = t.find('beat-type')
            if num_el is not None and den_el is not None:
                result.append((
                    meas_el.get('number', '?'),
                    int(num_el.text),
                    int(den_el.text),
                ))
    return result


# ---------------------------------------------------------------------------
# Per-piece helpers
# ---------------------------------------------------------------------------

def _build(txt_path: Path):
    """Parse and build XML; return (tab, timing, root, expanded) or raise."""
    from parse_txt import parse
    from repeat_expander import expand_repeats
    from midi_timing import extract_timing
    from score_builder import build_musicxml

    tab      = parse(str(txt_path))
    mid_path = matching_mid(txt_path)
    timing   = extract_timing(str(mid_path)) if mid_path else None
    if timing is None:
        return tab, None, None, None
    expanded = expand_repeats(tab)
    root     = build_musicxml(expanded, timing)
    return tab, timing, root, expanded


# ---------------------------------------------------------------------------
# SUITE 1 — Meta time signature
# ---------------------------------------------------------------------------

@dataclass
class MetaResult:
    name: str
    meta_ts: str = ''          # declared in header, e.g. "2/4"
    has_mid: bool = False
    xml_first_ts: str = ''     # what the XML first measure actually says
    ok: bool = True
    error: str = ''


def run_meta_piece(txt_path: Path) -> MetaResult:
    res = MetaResult(name=txt_path.stem)
    try:
        tab, timing, root, expanded = _build(txt_path)
        res.meta_ts = tab.metadata.time_sig if tab.metadata else ''
        if not res.meta_ts:
            return res   # nothing to check
        if timing is None or root is None:
            return res   # no .mid, can't generate XML
        res.has_mid = True

        # Read XML first measure time sig
        xml_times = _xml_time_sigs(root)
        if not xml_times:
            res.ok = False
            res.error = 'No <time> element in XML at all'
            return res

        first_num, first_mno, first_ts_num, first_ts_denom = *xml_times[0][:1], *xml_times[0]
        res.xml_first_ts = f'{first_ts_num}/{first_ts_denom}'

        if res.xml_first_ts != res.meta_ts:
            res.ok = False
            res.error = f'XML measure {first_mno} has {res.xml_first_ts}, expected {res.meta_ts}'

    except Exception as e:
        res.ok = False
        res.error = str(e)[:120]
    return res


def report_meta(results: list[MetaResult]):
    with_meta  = [r for r in results if r.meta_ts]
    with_mid   = [r for r in with_meta if r.has_mid]
    errors     = [r for r in results if r.error and not r.ok]
    bad        = [r for r in with_mid if not r.ok]

    print(f'\n{"━"*72}')
    print('META TIME SIGNATURE SUITE')
    print(f'{"━"*72}')
    print(f'  Pieces tested               : {len(results)}')
    print(f'  With time sig in header     : {len(with_meta)}  ({pct(len(with_meta), len(results))})')
    print(f'  With .mid (XML generated)   : {len(with_mid)}  ({pct(len(with_mid), len(with_meta))} of those)')
    print(f'  Correct in XML measure 1    : {len(with_mid) - len(bad)}  {"✓" if not bad else "✗"}')

    if bad:
        print(f'\n  FAILURES ({len(bad)}):')
        for r in bad[:15]:
            print(f'    {r.name}: meta={r.meta_ts}  xml={r.xml_first_ts}  {r.error}')

    print(f'\n  Result: {"PASS ✓" if not bad else "FAIL ✗"}')
    return not bad


# ---------------------------------------------------------------------------
# SUITE 2 — Mid-piece time signature changes
# ---------------------------------------------------------------------------

@dataclass
class ChangeResult:
    name: str
    midi_change_measures: list[int] = field(default_factory=list)  # 0-based midi indices
    xml_change_measures:  list[int] = field(default_factory=list)  # 1-based XML measure numbers
    missing_changes: list[str] = field(default_factory=list)
    ok: bool = True
    error: str = ''


def run_change_piece(txt_path: Path) -> Optional[ChangeResult]:
    """Return None if piece has no time sig changes (nothing to check)."""
    res = ChangeResult(name=txt_path.stem)
    try:
        tab, timing, root, expanded = _build(txt_path)
        if timing is None or root is None:
            return None

        # Parse meta time sig override (same logic as score_builder)
        meta_ts: Optional[tuple[int,int]] = None
        if tab.metadata and tab.metadata.time_sig:
            try:
                parts = tab.metadata.time_sig.strip().split('/')
                meta_ts = (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass

        # Reconstruct the effective time sig per MIDI measure, applying the
        # meta override on measure 0.
        effective: list[tuple[int,int]] = []
        for i, mt in enumerate(timing.measures):
            if i == 0 and meta_ts is not None:
                effective.append(meta_ts)
            else:
                effective.append((mt.time_sig_num, mt.time_sig_denom))

        # Only look at measures the score builder actually emits.
        # Changes beyond n_pairs can't appear in the XML.
        n_exp  = len(expanded.measures)
        n_midi = len(timing.measures)
        n_pairs = min(n_exp, n_midi)

        # Identify which measures have a time sig change vs the previous.
        expected_change_at: list[int] = []   # 1-based XML measure numbers
        prev = None
        for i, ts in enumerate(effective[:n_pairs]):
            if ts != prev:
                if i > 0:   # measure 0 is always written; only flag i>0 here
                    expected_change_at.append(i + 1)   # XML measures are 1-based
            prev = ts

        if not expected_change_at:
            return None   # no mid-piece changes

        res.midi_change_measures = expected_change_at

        # What does the XML actually have?
        xml_times = _xml_time_sigs(root)
        xml_change_set = {int(mno) for mno, _, _ in xml_times if int(mno) > 1}
        res.xml_change_measures = sorted(xml_change_set)

        # Every expected change must appear in the XML.
        for mno in expected_change_at:
            if mno not in xml_change_set:
                # Get the expected and actual time sig for context
                ts = effective[mno - 1]
                res.missing_changes.append(
                    f'measure {mno} ({ts[0]}/{ts[1]}) missing from XML'
                )

        if res.missing_changes:
            res.ok = False

    except Exception as e:
        res.ok = False
        res.error = str(e)[:120]
    return res


def report_changes(results: list[ChangeResult]):
    bad    = [r for r in results if not r.ok]
    errors = [r for r in results if r.error]
    ok_ct  = len(results) - len(bad)

    total_expected = sum(len(r.midi_change_measures) for r in results)
    total_missing  = sum(len(r.missing_changes) for r in results)

    print(f'\n{"━"*72}')
    print('MID-PIECE TIME SIGNATURE CHANGE SUITE')
    print(f'{"━"*72}')
    print(f'  Pieces with MIDI ts changes : {len(results)}')
    print(f'  Total expected XML changes  : {total_expected}')
    print(f'  Missing from XML            : {total_missing}  {"✓" if total_missing == 0 else "✗"}')
    print(f'  Pieces fully correct        : {ok_ct}  {"✓" if not bad else "✗"}')

    if errors:
        print(f'\n  ERRORS ({len(errors)}):')
        for r in errors[:10]:
            print(f'    {r.name}: {r.error}')

    if bad and not errors:
        print(f'\n  MISSING CHANGES (up to 10):')
        for r in bad[:10]:
            for msg in r.missing_changes[:3]:
                print(f'    {r.name}: {msg}')

    print(f'\n  Result: {"PASS ✓" if not bad else "FAIL ✗"}')
    return not bad


# ---------------------------------------------------------------------------
# SUITE 3 — No duplicate <time> elements
# ---------------------------------------------------------------------------

@dataclass
class DupResult:
    name: str
    duplicates: list[str] = field(default_factory=list)
    ok: bool = True
    error: str = ''


def run_dup_piece(txt_path: Path) -> Optional[DupResult]:
    res = DupResult(name=txt_path.stem)
    try:
        tab, timing, root, expanded = _build(txt_path)
        if timing is None or root is None:
            return None

        xml_times = _xml_time_sigs(root)
        prev_ts = None
        for mno, num, denom in xml_times:
            ts = (num, denom)
            if ts == prev_ts:
                res.duplicates.append(f'measure {mno}: {num}/{denom} re-declared (same as previous)')
                res.ok = False
            prev_ts = ts

    except Exception as e:
        res.ok = False
        res.error = str(e)[:120]
    return res


def report_dups(results: list[DupResult]):
    bad = [r for r in results if not r.ok]
    total_dups = sum(len(r.duplicates) for r in results if not r.error)

    print(f'\n{"━"*72}')
    print('NO-DUPLICATE TIME SIGNATURE SUITE')
    print(f'{"━"*72}')
    print(f'  Pieces checked              : {len(results)}')
    print(f'  Redundant <time> elements   : {total_dups}  {"✓" if total_dups == 0 else "✗"}')

    if bad:
        print(f'\n  DUPLICATES (up to 10):')
        for r in bad[:10]:
            for msg in r.duplicates[:2]:
                print(f'    {r.name}: {msg}')

    print(f'\n  Result: {"PASS ✓" if not bad else "FAIL ✗"}')
    return not bad


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_txt = all_txt_paths()
    rng = random.Random(SEED_META)
    meta_sample = rng.sample(all_txt, min(N_META, len(all_txt)))

    print('═' * 72)
    print(f'Time Signature Test Suite  (seed={SEED_META})')
    print('═' * 72)

    # Suite 1 — meta
    print(f'\nSuite 1: Running meta time sig check on {len(meta_sample)} pieces…', flush=True)
    meta_results = [run_meta_piece(p) for p in meta_sample]
    ok1 = report_meta(meta_results)

    # Suite 2 — mid-piece changes (sampled)
    rng2 = random.Random(SEED_CHANGE)
    mid_paths = [p for p in all_txt if matching_mid(p)]
    change_sample = rng2.sample(mid_paths, min(N_CHANGE, len(mid_paths)))
    print(f'\nSuite 2: Scanning {len(change_sample)} pieces for MIDI time sig changes…', flush=True)
    change_results = []
    for p in change_sample:
        r = run_change_piece(p)
        if r is not None:
            change_results.append(r)
    print(f'  Found {len(change_results)} pieces with mid-piece time sig changes.')
    ok2 = report_changes(change_results)

    # Suite 3 — no duplicates (run on same meta_sample that has .mid)
    print(f'\nSuite 3: Checking for redundant <time> elements…', flush=True)
    dup_results = [r for p in meta_sample
                   if (r := run_dup_piece(p)) is not None]
    ok3 = report_dups(dup_results)

    overall = ok1 and ok2 and ok3
    print(f'\n{"═"*72}')
    print(f'Overall: {"PASS ✓" if overall else "FAIL ✗"}')
    print()


if __name__ == '__main__':
    main()
