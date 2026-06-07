"""
check_issues.py
===============
Diagnostic script: scan every piece in the library for transcription
inconsistencies and write a structured log to output/logs/.

Run from the repository root::

    python pipeline/check_issues.py [--limit N] [--pieces-only]

Flags
-----
--limit N       Process only the first N .txt/.mid pairs (alphabetical).
                Default: all pairs.
--pieces-only   Process only the four validated reference pieces defined in
                test_pipeline.py (fast sanity check).
--verbose       Print each issue as it is found.

Issues detected
---------------
bar_count_mismatch
    The MIDI has a different number of non-empty measures than the tab.
    Indicates the MIDI was recorded with repeats expanded or has missing
    sections relative to the written score.

duplicate_string_in_beat
    After annotation, two matched notes in the same beat are assigned to
    the same guitar string — physically impossible and indicates an
    annotation error.

Output
------
output/logs/YYYY-MM-DD_issues.jsonl  — one JSON object per line
output/logs/YYYY-MM-DD_summary.txt   — human-readable summary
"""

from __future__ import annotations
import sys, os, argparse, warnings, tempfile, datetime
from pathlib import Path

warnings.filterwarnings('ignore')

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from parse_txt import parse
from tab_parser import tuning_to_midi, bar_count_info
from convert_mid import mid_to_musicxml
from annotate_xml import _merge_parts, _match_by_measure, _xml_note_midi
from issues_log import log_issue, read_log, summarise, _LOG_DIR
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Per-piece checks
# ---------------------------------------------------------------------------

def _count_midi_nonempty(root: ET.Element) -> int:
    part = root.find('.//part')
    if part is None:
        return 0
    return sum(
        1 for m in part.findall('measure')
        if any(
            n.find('pitch') is not None and n.find('rest') is None
            for n in m.findall('note')
        )
    )


def check_piece(txt_path: Path, mid_path: Path, *, verbose: bool = False) -> list[dict]:
    """
    Run all checks for one piece.  Returns a (possibly empty) list of issue
    dicts that were logged.
    """
    stem = txt_path.stem
    issues_found: list[dict] = []

    try:
        tab = parse(str(txt_path))
    except Exception as exc:
        issue = log_issue(
            stem=stem, title=stem, composer='',
            bar_number=None, issue_type='parse_error',
            details=f'Failed to parse {txt_path.name}: {exc}',
        )
        return [issue]

    title    = tab.metadata.title
    composer = tab.metadata.composer
    bci      = bar_count_info(tab.measures)
    index_start  = bci['bar_index_start']
    bar_span     = bci['bar_count_span']    # full numeric range incl. gap bars
    bar_written  = bci['bar_count_written']
    bar_gaps     = bci['bar_count_gaps']
    tab_keys     = sorted(tab.measures.keys())

    # ── Convert MIDI to XML ──────────────────────────────────────────────────
    tmp_xml = tempfile.mktemp(suffix='.xml')
    try:
        mid_to_musicxml(str(mid_path), tmp_xml)
        tree = ET.parse(tmp_xml)
        root = tree.getroot()
    except Exception as exc:
        issue = log_issue(
            stem=stem, title=title, composer=composer,
            bar_number=None, issue_type='midi_conversion_error',
            details=f'Failed to convert {mid_path.name}: {exc}',
        )
        return [issue]
    finally:
        if os.path.exists(tmp_xml):
            os.remove(tmp_xml)

    _merge_parts(root)

    # ── Check 1: bar count ───────────────────────────────────────────────────
    # Compare MIDI non-empty measure count against bar_count_span.
    # bar_count_span = max_key - min_key + 1 and already accounts for gap bars
    # (measure-number jumps that represent repeated sections).
    # For 0-indexed pieces a discrepancy of exactly 1 is tolerated: the pickup
    # bar (bar 0) is often folded into bar 1 in the MIDI, so span is 1 larger.
    midi_nonempty = _count_midi_nonempty(root)
    diff          = midi_nonempty - bar_span
    pickup_offset = 1 if index_start == 0 else 0
    mismatch      = abs(diff) > pickup_offset

    if mismatch:
        detail_parts = [
            f'MIDI has {midi_nonempty} non-empty measures.',
            f'Tab: index_start={index_start}, bar_count_span={bar_span}, '
            f'bar_count_written={bar_written}, bar_count_gaps={bar_gaps}.',
            f'Difference (MIDI - span): {diff:+d}.',
        ]
        if bar_gaps > 0:
            detail_parts.append(
                f'{bar_gaps} gap bar(s) in tab numbering represent repeated '
                f'sections already included in bar_count_span.'
            )
        detail_parts.append(
            'Likely cause: MIDI recorded with additional repeats or '
            'tab is missing sections.'
        )
        issue = log_issue(
            stem=stem, title=title, composer=composer,
            bar_number=None, issue_type='bar_count_mismatch',
            details=' '.join(detail_parts),
        )
        issues_found.append(issue)
        if verbose:
            print(f'  [bar_count_mismatch] {stem}: '
                  f'MIDI={midi_nonempty} span={bar_span} '
                  f'(index_start={index_start}) diff={diff:+d}')

    # ── Check 2: duplicate strings in beats ─────────────────────────────────
    try:
        tuning_midi = tuning_to_midi(tab.metadata.tuning)
        matches = _match_by_measure(root, tab, tuning_midi)
    except Exception as exc:
        issue = log_issue(
            stem=stem, title=title, composer=composer,
            bar_number=None, issue_type='annotation_error',
            details=f'_match_by_measure failed: {exc}',
        )
        return issues_found + [issue]

    part = root.find('.//part')
    if part is not None:
        for midx, meas in enumerate(part.findall('measure')):
            if midx >= bar_written:   # only annotated measures have tab data
                break
            tab_mnum = tab_keys[midx]
            offset = 0; prev_dur = 0
            beat_strings: dict[int, list[int]] = {}

            for note_el in meas.findall('note'):
                is_chord = note_el.find('chord') is not None
                is_rest  = note_el.find('rest')  is not None
                dur      = int(note_el.findtext('duration', '0'))
                if is_chord:
                    off = offset - prev_dur
                else:
                    off = offset; prev_dur = dur; offset += dur
                if is_rest or note_el.find('pitch') is None:
                    continue
                ann = matches.get(id(note_el))
                if ann is None:
                    continue
                beat_strings.setdefault(off, []).append(ann[0])

            for off, strings in beat_strings.items():
                dups = [s for s in set(strings) if strings.count(s) > 1]
                if dups:
                    detail = (
                        f'Beat at offset {off} in measure '
                        f'{meas.get("number")} (tab bar {tab_mnum}): '
                        f'strings = {strings}; duplicates = {dups}.'
                    )
                    issue = log_issue(
                        stem=stem, title=title, composer=composer,
                        bar_number=tab_mnum, issue_type='duplicate_string_in_beat',
                        details=detail,
                    )
                    issues_found.append(issue)
                    if verbose:
                        print(f'  [dup_string] {stem} bar {tab_mnum}: {detail}')

    return issues_found


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--limit', type=int, default=None,
                        help='Process only the first N .txt/.mid pairs.')
    parser.add_argument('--pieces-only', action='store_true',
                        help='Run only the four validated reference pieces.')
    parser.add_argument('--verbose', action='store_true',
                        help='Print each issue as it is found.')
    args = parser.parse_args(argv)

    today  = datetime.date.today().isoformat()
    tab_dir = ROOT / 'tab'

    if args.pieces_only:
        stems = [
            ('lauro_two_venezuelan_waltzes_1_el_negrito',
             'lauro_two_venezuelan_waltzes_1_el_negrito'),
            ('villa-lobos_choros_01',
             'villa-lobos_choros_01'),
            ('cardoso_suite_sudamericana_09_aire_de_milonga',
             'cardoso_suite_sudamericana_09_aire_de_milonga'),
            ('barrios_un_sueno_en_la_floresta',
             'barrios_un_sueno_en_la_floresta'),
        ]
        pairs = [
            (tab_dir / (t + '.txt'), tab_dir / (m + '.mid'))
            for t, m in stems
            if (tab_dir / (t + '.txt')).exists() and (tab_dir / (m + '.mid')).exists()
        ]
    else:
        import glob
        all_txt = sorted(glob.glob(str(tab_dir / '*.txt')))
        pairs = [
            (Path(t), Path(t.replace('.txt', '.mid')))
            for t in all_txt
            if Path(t.replace('.txt', '.mid')).exists()
        ]
        if args.limit:
            pairs = pairs[:args.limit]

    total_pieces  = len(pairs)
    total_issues  = 0
    pieces_with_issues = 0

    print(f'Checking {total_pieces} piece(s)…')
    for txt_path, mid_path in pairs:
        stem = txt_path.stem
        if args.verbose:
            print(f'\n{stem}')
        issues = check_piece(txt_path, mid_path, verbose=args.verbose)
        if issues:
            total_issues += len(issues)
            pieces_with_issues += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    summary_path = _LOG_DIR / f'{today}_summary.txt'
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    from collections import Counter

    run_entries = read_log(today)[-total_issues:] if total_issues > 0 else []
    by_type: dict[str, int] = Counter(e['issue_type'] for e in run_entries)

    summary_lines = [
        f'Issue scan — {today}',
        f'Run started     : {datetime.datetime.now().isoformat(timespec="seconds")}',
        f'Pieces checked  : {total_pieces}',
        f'Pieces with issues : {pieces_with_issues}',
        f'Issues this run : {total_issues}',
        '',
    ]
    if by_type:
        summary_lines.append('By type:')
        for issue_type, count in sorted(by_type.items()):
            summary_lines.append(f'  {issue_type}: {count}')
        summary_lines.append('')

    # Top 20 affected pieces by issue count (this run)
    all_run_issues = run_entries
    piece_counts = Counter(e['stem'] for e in all_run_issues)
    if piece_counts:
        summary_lines.append('Most affected pieces (this run):')
        for stem_val, count in piece_counts.most_common(20):
            title = next((e['title'] for e in all_run_issues if e['stem'] == stem_val), stem_val)
            summary_lines.append(f'  {count:4d}  {stem_val}  ({title})')

    summary_text = '\n'.join(summary_lines)
    with open(summary_path, 'w', encoding='utf-8') as fh:
        fh.write(summary_text + '\n')

    print(f'\n{summary_text}')
    print(f'\nLog  → {_LOG_DIR / (today + "_issues.jsonl")}')
    print(f'Summary → {summary_path}')
    return 0 if total_issues == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
