"""
test_pipeline.py
================
Validation suite: compare pipeline-generated MusicXML against source TXT files.

Usage:
    python pipeline/test_pipeline.py

For each piece it reports:
  - Tab parsing quality  (systems found, measures, notes per string)
  - XML generation       (parts, note count, annotation coverage)
  - Pitch accuracy       (annotated string+fret → expected MIDI pitch)
  - Chord accuracy       (tab-simultaneous notes → XML chord elements)
  - Per-measure diff     (first N measures: expected tab notes vs XML notes)
"""
from __future__ import annotations
import os, sys, tempfile, warnings, traceback
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

warnings.filterwarnings('ignore')
HERE    = Path(__file__).parent
ROOT    = HERE.parent
CLASSTAB = ROOT / 'tab'
sys.path.insert(0, str(HERE))

# ── Pieces to test ─────────────────────────────────────────────────────────
PIECES = [
    {
        'name':  'El Negrito (Lauro)',
        'txt':   'lauro_two_venezuelan_waltzes_1_el_negrito.txt',
        'mid':   'lauro_two_venezuelan_waltzes_1_el_negrito.mid',
    },
    {
        'name':  'Choro No.1 (Villa-Lobos)',
        'txt':   'villa-lobos_choros_01.txt',
        'mid':   'villa-lobos_choros_01.mid',
    },
    {
        'name':  'Aire de Milonga (Cardoso)',
        'txt':   'cardoso_suite_sudamericana_09_aire_de_milonga.txt',
        'mid':   'cardoso_suite_sudamericana_09_aire_de_milonga.mid',
    },
    {
        'name':  'Jesu, Joy of Man\'s Desiring (Bach)',
        'txt':   'bach_js_bwv0147_10_jesu_joy_of_mans_desiring.txt',
        'mid':   'bach_js_bwv0147_10_jesu_joy_of_mans_desiring_1.mid',
    },
]

SHOW_MEASURES = 8   # how many measures to show in per-measure diff

# ── Helpers ─────────────────────────────────────────────────────────────────

def _midi_pitch(string: int, fret: int, tuning: list[int]) -> int:
    if 1 <= string <= 6:
        return tuning[string - 1] + fret
    return -1

def _xml_pitch(note_el) -> int:
    import xml.etree.ElementTree as ET
    pitch = note_el.find('pitch')
    if pitch is None:
        return -1
    step_semi = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}
    step   = pitch.findtext('step', 'C').upper()
    alter  = int(float(pitch.findtext('alter', '0') or 0))
    octave = int(pitch.findtext('octave', '4') or 4)
    return 12*(octave+1) + step_semi.get(step, 0) + alter

# ── Per-piece result ─────────────────────────────────────────────────────────

@dataclass
class PieceResult:
    name: str
    # parse_txt
    systems_found: int = 0
    measures_parsed: int = 0
    tab_notes_total: int = 0
    tab_strings: dict = field(default_factory=dict)   # string → count
    repeat_starts: int = 0
    repeat_ends: int = 0
    parse_error: str = ''
    # XML generation
    xml_parts: int = 0
    xml_notes_total: int = 0
    xml_annotated: int = 0   # notes with string+fret
    gen_error: str = ''
    # Bar-count validation (new pipeline)
    expanded_measures: int = 0
    midi_measures: int = 0
    bar_count_delta: int = 0
    # Accuracy
    pitch_match: int = 0     # annotated notes where pitch ≈ expected
    pitch_total: int = 0
    chord_correct: int = 0   # simultaneous tab pairs that are chords in XML
    chord_total: int = 0
    # Per-measure diff (first SHOW_MEASURES measures)
    measure_diff: list = field(default_factory=list)

# ── Test runner ──────────────────────────────────────────────────────────────

def run_piece(p: dict) -> PieceResult:
    res = PieceResult(name=p['name'])
    txt_path = str(CLASSTAB / p['txt'])
    mid_path = str(CLASSTAB / p['mid'])

    # ── 1. Parse TXT ────────────────────────────────────────────────────────
    try:
        from parse_txt import parse, _find_systems, tuning_to_midi, note_midi
        with open(txt_path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        lines = [l.rstrip() for l in lines]
        systems = _find_systems(lines)
        res.systems_found = len(systems)

        tab = parse(txt_path)
        res.measures_parsed = len(tab.measures)
        res.tab_notes_total = sum(len(md.notes) for md in tab.measures.values())
        res.tab_strings     = dict(Counter(
            str(n.string)
            for md in tab.measures.values()
            for n in md.notes
        ))
        res.repeat_starts = sum(1 for md in tab.measures.values() if md.repeat_start)
        res.repeat_ends   = sum(1 for md in tab.measures.values() if md.repeat_end)
        tuning_midi = tuning_to_midi(tab.metadata.tuning)
    except Exception as e:
        res.parse_error = str(e)
        return res

    # ── 2. Generate XML (new tab-primary pipeline) ───────────────────────────
    import xml.etree.ElementTree as ET
    try:
        from repeat_expander import expand_repeats, expansion_summary
        from midi_timing     import extract_timing
        from score_builder   import build_musicxml

        expanded = expand_repeats(tab)
        timing   = extract_timing(mid_path)

        # Bar-count validation: expanded score should closely match MIDI
        n_expanded = len(expanded.measures)
        n_midi     = len(timing.measures)
        res.expanded_measures = n_expanded
        res.midi_measures     = n_midi
        res.bar_count_delta   = n_expanded - n_midi

        root = build_musicxml(expanded, timing)
    except Exception as e:
        res.gen_error = traceback.format_exc()[-400:]
        return res

    parts = root.findall('.//part')
    res.xml_parts = len(parts)
    all_notes = root.findall('.//note')
    res.xml_notes_total = sum(1 for n in all_notes if n.find('rest') is None)
    res.xml_annotated   = sum(1 for n in all_notes if n.find('.//string') is not None)

    # ── 3. Pitch accuracy: for each annotated note, check pitch ─────────────
    for note_el in all_notes:
        tech = note_el.find('.//technical')
        if tech is None:
            continue
        s_el = tech.find('string')
        f_el = tech.find('fret')
        if s_el is None or f_el is None:
            continue
        try:
            s, f = int(s_el.text), int(f_el.text)
        except (TypeError, ValueError):
            continue
        expected_midi = _midi_pitch(s, f, tuning_midi)
        actual_midi   = _xml_pitch(note_el)
        if actual_midi < 0 or expected_midi < 0:
            continue
        res.pitch_total += 1
        if abs(actual_midi - expected_midi) <= 2:
            res.pitch_match += 1

    # ── 4. Chord accuracy: tab-simultaneous notes → XML chords ───────────────
    # Build a map: measure_number → list of (col, string) pairs from tab
    # Then check whether those notes appear as chords in the XML

    # Collect XML note annotations per measure (by sequential measure index)
    xml_measures = root.findall('.//measure')
    xml_measure_notes: dict[int, list] = defaultdict(list)  # idx → [(string, fret, is_chord)]
    for midx, meas_el in enumerate(xml_measures):
        for note_el in meas_el.findall('note'):
            tech = note_el.find('.//technical')
            if tech is None:
                continue
            s_el = tech.find('string')
            f_el = tech.find('fret')
            if s_el is None or f_el is None:
                continue
            try:
                s, f = int(s_el.text), int(f_el.text)
            except (TypeError, ValueError):
                continue
            is_chord = note_el.find('chord') is not None
            xml_measure_notes[midx].append((s, f, is_chord))

    tab_keys = sorted(tab.measures.keys())
    for mnum_idx, mnum in enumerate(tab_keys):
        md = tab.measures[mnum]
        # Group tab notes by column
        col_groups: dict[int, list] = defaultdict(list)
        for n in md.notes:
            col_groups[n.col].append(n)
        # For columns with 2+ notes (simultaneous), check XML chords
        for col, notes in col_groups.items():
            if len(notes) < 2:
                continue
            res.chord_total += len(notes)
            # Look up in XML measure at same index
            xml_notes_in_meas = xml_measure_notes.get(mnum_idx, [])
            xml_string_set = {(s, f) for s, f, _ in xml_notes_in_meas}
            xml_chord_set  = {(s, f) for s, f, ic in xml_notes_in_meas if ic}
            for n in notes:
                if (n.string, n.fret) in xml_chord_set:
                    res.chord_correct += 1

    # ── 5. Per-measure diff ──────────────────────────────────────────────────
    for mnum_idx, mnum in enumerate(tab_keys[:SHOW_MEASURES]):
        md = tab.measures[mnum]
        tab_notes_sorted = sorted(md.notes, key=lambda n: (n.col, n.string))
        tab_repr = ', '.join(f's{n.string}f{n.fret}' for n in tab_notes_sorted)

        xml_in_meas = xml_measure_notes.get(mnum_idx, [])
        xml_repr = ', '.join(
            f's{s}f{f}{"*" if ic else ""}' for s, f, ic in xml_in_meas
        )

        res.measure_diff.append({
            'mnum':     mnum,
            'tab':      tab_repr or '(empty)',
            'xml':      xml_repr or '(empty)',
            'tab_count': len(tab_notes_sorted),
            'xml_count': len(xml_in_meas),
        })

    return res

# ── Report printer ────────────────────────────────────────────────────────────

def pct(num, den):
    return f'{100*num/den:.1f}%' if den else 'n/a'

def print_result(res: PieceResult):
    SEP = '─' * 72
    print(f'\n{"━"*72}')
    print(f'  {res.name}')
    print(f'{"━"*72}')

    # Parse
    if res.parse_error:
        print(f'  ❌ PARSE ERROR: {res.parse_error}')
        return
    print(f'\n  ── Tab parser ──────────────────────────────────────────')
    print(f'  Systems detected : {res.systems_found}')
    print(f'  Measures parsed  : {res.measures_parsed}')
    print(f'  Tab notes total  : {res.tab_notes_total}')
    print(f'  String dist      : ' +
          '  '.join(f's{s}={c}' for s, c in sorted(res.tab_strings.items())))
    print(f'  Repeats          : {res.repeat_starts} start  {res.repeat_ends} end')

    # XML
    if res.gen_error:
        print(f'\n  ❌ XML GEN ERROR:\n{res.gen_error}')
        return
    print(f'\n  ── XML generation ──────────────────────────────────────')
    bar_ok = '✓' if abs(res.bar_count_delta) <= 2 else '✗'
    print(f'  Expanded measures: {res.expanded_measures}  MIDI measures: {res.midi_measures}  '
          f'delta: {res.bar_count_delta:+d}  {bar_ok}')
    print(f'  XML parts        : {res.xml_parts}')
    print(f'  XML notes total  : {res.xml_notes_total}')
    print(f'  Annotated        : {res.xml_annotated}  ({pct(res.xml_annotated, res.xml_notes_total)} of XML notes)')
    print(f'  Coverage         : {pct(res.xml_annotated, res.tab_notes_total)} of tab notes reached XML')

    # Accuracy
    print(f'\n  ── Accuracy ────────────────────────────────────────────')
    print(f'  Pitch accuracy   : {res.pitch_match}/{res.pitch_total}  ({pct(res.pitch_match, res.pitch_total)})')
    print(f'  Chord accuracy   : {res.chord_correct}/{res.chord_total}  ({pct(res.chord_correct, res.chord_total)})')

    # Per-measure diff
    if res.measure_diff:
        print(f'\n  ── First {SHOW_MEASURES} measures: tab vs XML ─────────────────────────')
        for d in res.measure_diff:
            ok = '✓' if d['tab_count'] == d['xml_count'] else '✗'
            print(f'  m{d["mnum"]:3d} {ok} tab({d["tab_count"]}): {d["tab"][:55]}')
            print(f'         xml({d["xml_count"]}): {d["xml"][:55]}')

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print('Pipeline Test Suite')
    print('=' * 72)
    results = []
    for p in PIECES:
        print(f'\nRunning: {p["name"]}…', flush=True)
        try:
            res = run_piece(p)
        except Exception as e:
            res = PieceResult(name=p['name'], parse_error=traceback.format_exc())
        results.append(res)
        print_result(res)

    # Summary
    print(f'\n{"━"*72}')
    print('SUMMARY')
    print(f'{"━"*72}')
    print(f'{"Piece":<35} {"Systems":>7} {"Meas":>5} {"Notes":>6} {"Exp":>5} {"MIDI":>5} {"Δ":>4} {"Pitch%":>7} {"Chord%":>7}')
    print('─' * 80)
    for r in results:
        if r.parse_error or r.gen_error:
            status = 'FAILED'
            print(f'{r.name:<35} {status}')
        else:
            delta_str = f'{r.bar_count_delta:+d}'
            print(f'{r.name:<35} '
                  f'{r.systems_found:>7} '
                  f'{r.measures_parsed:>5} '
                  f'{r.tab_notes_total:>6} '
                  f'{r.expanded_measures:>5} '
                  f'{r.midi_measures:>5} '
                  f'{delta_str:>4} '
                  f'{pct(r.pitch_match, r.pitch_total):>7} '
                  f'{pct(r.chord_correct, r.chord_total):>7}')
    print()

if __name__ == '__main__':
    main()
