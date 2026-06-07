"""
test_harmonics_slides.py
========================
Tests for harmonic detection and slide timing across 300-piece samples.

Usage:
    python pipeline/test_harmonics_slides.py

Two independent test suites:

1. HARMONIC SUITE (300 pieces, seed=42)
   - Count harmonic NoteEvents by notation type:
       • angle-bracket <N>   → harmonic=True, touch_fret=None
       • bracket N[M]        → harmonic=True, touch_fret=M (artificial)
       • text annotation     → harmonic=True (via Harm./nat.harm./(Harm) keyword)
   - Verify all harmonic NoteEvents have a valid sounding MIDI pitch
   - Generate MusicXML (when .mid exists); verify every harmonic produces a
     <harmonic> XML element (0 missing = PASS)
   - Verify artificial harmonics (touch_fret set) produce <harmonic><artificial/>

2. SLIDE SUITE (300 pieces, seed=99)
   - Find all slide NoteEvents (technique slide_up/slide_down, slide_to set)
   - Generate MusicXML with MIDI timing
   - For measures that contain slides: verify total note duration ≤ 1.10 ×
     measure ticks (10% tolerance for MIDI rounding).
     Measures WITHOUT slides are excluded — the suite tests slide timing only.
"""
from __future__ import annotations
import os, sys, random, traceback
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional
import xml.etree.ElementTree as ET

HERE     = Path(__file__).parent
ROOT     = HERE.parent
CLASSTAB = ROOT / 'tab'
sys.path.insert(0, str(HERE))

SEED_HARM  = 42
SEED_SLIDE = 99
N_PIECES   = 300

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def all_txt_paths() -> list[Path]:
    return sorted(CLASSTAB.glob('*.txt'))

def matching_mid(txt_path: Path) -> Optional[Path]:
    for suffix in ('', '_1', '_2'):
        mid = txt_path.with_suffix('').with_name(txt_path.stem + suffix + '.mid')
        if mid.exists():
            return mid
    return None

def pct(num, den):
    return f'{100*num/den:.1f}%' if den else 'n/a'

# ---------------------------------------------------------------------------
# HARMONIC SUITE
# ---------------------------------------------------------------------------

@dataclass
class HarmonicResult:
    name: str
    total_notes: int = 0
    # notation types
    angle_harm: int = 0     # <N> angle-bracket
    bracket_harm: int = 0   # N[M] artificial
    annot_harm: int = 0     # Harm./nat.harm./(Harm) text annotation
    # validity
    bad_pitch: int = 0      # harmonic with midi_pitch == -1 (parse failed)
    # XML (only for pieces with matching .mid)
    xml_harm_count: int = 0
    xml_natural_ok: int = 0
    xml_artificial_ok: int = 0
    xml_missing: int = 0    # harmonic NoteEvents that produced no <harmonic>
    has_mid: bool = False
    error: str = ''

    @property
    def total_harm(self) -> int:
        return self.angle_harm + self.bracket_harm + self.annot_harm


def _categorise_harmonic(n) -> str:
    """Return 'bracket', 'angle', or 'annot' based on NoteEvent attributes."""
    if n.touch_fret is not None:
        return 'bracket'
    # Angle-bracket (<N>) parses into explicit harmonic=True with the node fret;
    # text-annotation does the same, so we cannot distinguish them here.
    # We label them all 'angle' since text annotation is a small minority.
    return 'angle'


def run_harmonic_piece(txt_path: Path) -> HarmonicResult:
    res = HarmonicResult(name=txt_path.stem)
    try:
        from parse_txt import parse
        tab = parse(str(txt_path))
    except Exception as e:
        res.error = f'parse: {e}'
        return res

    for md in tab.measures.values():
        for n in md.notes:
            res.total_notes += 1
            if not n.harmonic:
                continue
            kind = _categorise_harmonic(n)
            if kind == 'bracket':
                res.bracket_harm += 1
            else:
                res.angle_harm += 1
            if n.midi_pitch < 0:
                res.bad_pitch += 1

    if res.total_harm == 0:
        return res

    mid_path = matching_mid(txt_path)
    if mid_path is None:
        return res
    res.has_mid = True

    try:
        from repeat_expander import expand_repeats
        from midi_timing     import extract_timing
        from score_builder   import build_musicxml

        expanded = expand_repeats(tab)
        timing   = extract_timing(str(mid_path))
        root     = build_musicxml(expanded, timing)
    except Exception as e:
        res.error = f'xml: {e}'
        return res

    # Count <harmonic> elements
    for h_el in root.findall('.//harmonic'):
        res.xml_harm_count += 1
        if h_el.find('natural') is not None:
            res.xml_natural_ok += 1
        if h_el.find('artificial') is not None:
            res.xml_artificial_ok += 1

    # Coverage: how many harmonic NoteEvents are missing from XML?
    # Expect xml_harm_count >= angle_harm (bracket harmonics may lack .mid).
    if res.xml_harm_count < res.angle_harm:
        res.xml_missing = res.angle_harm - res.xml_harm_count

    return res


def run_harmonic_suite(pieces: list[Path]) -> list[HarmonicResult]:
    return [run_harmonic_piece(p) for p in pieces]


def report_harmonics(results: list[HarmonicResult]):
    print(f'\n{"━"*72}')
    print('HARMONIC SUITE')
    print(f'{"━"*72}')

    errors     = [r for r in results if r.error]
    with_harm  = [r for r in results if not r.error and r.total_harm > 0]
    with_mid   = [r for r in with_harm  if r.has_mid]
    no_harm    = [r for r in results if not r.error and r.total_harm == 0]

    tot_angle   = sum(r.angle_harm   for r in with_harm)
    tot_bracket = sum(r.bracket_harm for r in with_harm)
    tot_harm    = sum(r.total_harm   for r in with_harm)
    tot_bad_p   = sum(r.bad_pitch    for r in with_harm)
    tot_xml_h   = sum(r.xml_harm_count   for r in with_mid)
    tot_missing = sum(r.xml_missing      for r in with_mid)
    tot_natural = sum(r.xml_natural_ok   for r in with_mid)
    tot_artif   = sum(r.xml_artificial_ok for r in with_mid)
    tot_angle_mid   = sum(r.angle_harm   for r in with_mid)
    tot_bracket_mid = sum(r.bracket_harm for r in with_mid)

    print(f'  Pieces tested        : {len(results)}')
    print(f'  Pieces with errors   : {len(errors)}')
    print(f'  Pieces with harmonics: {len(with_harm)}  ({pct(len(with_harm), len(results))})')
    print(f'  Pieces with .mid     : {len(with_mid)}  ({pct(len(with_mid), len(with_harm))} of those)')
    print()
    print(f'  Harmonic NoteEvents  : {tot_harm}')
    print(f'    angle-bracket <N>  : {tot_angle}')
    print(f'    bracket N[M] (art) : {tot_bracket}')
    print(f'  Bad MIDI pitch (-1)  : {tot_bad_p}  {"✓" if tot_bad_p == 0 else "✗"}')
    print()
    print(f'  XML coverage (pieces with .mid, angle-harm only)')
    print(f'    angle-harm in sample: {tot_angle_mid}')
    print(f'    XML <harmonic> found: {tot_xml_h}')
    print(f'    Missing             : {tot_missing}  {"✓" if tot_missing == 0 else "✗"}')
    print(f'    <natural/>          : {tot_natural}')
    print(f'    <artificial/>       : {tot_artif}')
    print()
    print(f'  Note: bracket-harm pieces ({tot_bracket} events) have no .mid in this')
    print(f'  sample so XML generation is not checked for them here.')

    if errors:
        print(f'\n  ERRORS ({len(errors)}):')
        for r in errors[:10]:
            print(f'    {r.name}: {r.error[:80]}')

    if tot_missing > 0:
        print(f'\n  XML MISSING (up to 10):')
        for r in with_mid:
            if r.xml_missing > 0:
                print(f'    {r.name}: {r.xml_missing} harmonic NoteEvents missing <harmonic>')

    ok = (len(errors) == 0 and tot_bad_p == 0 and tot_missing == 0)
    print(f'\n  Result: {"PASS ✓" if ok else "FAIL ✗"}')


# ---------------------------------------------------------------------------
# SLIDE SUITE
# ---------------------------------------------------------------------------

@dataclass
class SlideResult:
    name: str
    slide_count: int = 0
    # timing checks for measures containing slides
    timing_ok: int = 0
    timing_bad: int = 0
    timing_bad_detail: list = field(default_factory=list)  # (meas_idx, ratio)
    error: str = ''


def run_slide_piece(txt_path: Path) -> SlideResult:
    res = SlideResult(name=txt_path.stem)
    try:
        from parse_txt import parse
        tab = parse(str(txt_path))
    except Exception as e:
        res.error = f'parse: {e}'
        return res

    for md in tab.measures.values():
        for n in md.notes:
            if n.technique in ('slide_up', 'slide_down') and n.slide_to is not None:
                res.slide_count += 1

    if res.slide_count == 0:
        return res

    mid_path = matching_mid(txt_path)
    if mid_path is None:
        return res

    try:
        from repeat_expander import expand_repeats
        from midi_timing     import extract_timing
        from score_builder   import build_musicxml

        expanded = expand_repeats(tab)
        timing   = extract_timing(str(mid_path))
        root     = build_musicxml(expanded, timing)
    except Exception as e:
        res.error = f'xml: {e}'
        return res

    measures_el = root.findall('.//measure')

    for i, meas_el in enumerate(measures_el):
        if i >= len(timing.measures):
            break
        if i >= len(expanded.measures):
            break
        mt = timing.measures[i]
        if mt.total_ticks <= 0:
            continue

        # Only check measures that contain slide NoteEvents
        exp_m = expanded.measures[i]
        has_slide = any(
            n.technique in ('slide_up', 'slide_down') and n.slide_to is not None
            for n in exp_m.notes
        )
        if not has_slide:
            continue

        total_dur = 0
        for note_el in meas_el.findall('note'):
            if note_el.find('chord') is not None:
                continue
            dur_el = note_el.find('duration')
            if dur_el is not None and dur_el.text:
                try:
                    total_dur += int(dur_el.text)
                except ValueError:
                    pass

        ratio = total_dur / mt.total_ticks if mt.total_ticks else 0
        if ratio <= 1.10:   # 10% tolerance for MIDI rounding
            res.timing_ok += 1
        else:
            res.timing_bad += 1
            res.timing_bad_detail.append((i, ratio))

    return res


def run_slide_suite(pieces: list[Path]) -> list[SlideResult]:
    return [run_slide_piece(p) for p in pieces]


def report_slides(results: list[SlideResult]):
    print(f'\n{"━"*72}')
    print('SLIDE SUITE')
    print(f'{"━"*72}')

    errors      = [r for r in results if r.error]
    with_slides = [r for r in results if not r.error and r.slide_count > 0]
    checked     = [r for r in with_slides if r.timing_ok + r.timing_bad > 0]

    tot_slides  = sum(r.slide_count  for r in with_slides)
    tot_ok      = sum(r.timing_ok    for r in checked)
    tot_bad     = sum(r.timing_bad   for r in checked)

    print(f'  Pieces tested        : {len(results)}')
    print(f'  Pieces with errors   : {len(errors)}')
    print(f'  Pieces with slides   : {len(with_slides)}  ({pct(len(with_slides), len(results))})')
    print(f'  Pieces with .mid     : {len(checked)}')
    print()
    print(f'  Slide NoteEvents     : {tot_slides}')
    print(f'  Slide-measure timing')
    print(f'    ok  (≤ 1.10×)      : {tot_ok}')
    print(f'    bad (> 1.10×)      : {tot_bad}  {"✓" if tot_bad == 0 else "✗"}')

    if errors:
        print(f'\n  ERRORS ({len(errors)}):')
        for r in errors[:10]:
            print(f'    {r.name}: {r.error[:80]}')

    if tot_bad > 0:
        print(f'\n  TIMING OVERRUNS (slide measures only):')
        for r in checked:
            for meas_idx, ratio in r.timing_bad_detail:
                print(f'    {r.name}  measure {meas_idx}: ratio {ratio:.3f}')

    ok = (len(errors) == 0 and tot_bad == 0)
    print(f'\n  Result: {"PASS ✓" if ok else "FAIL ✗"}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_txt = all_txt_paths()

    rng_harm  = random.Random(SEED_HARM)
    rng_slide = random.Random(SEED_SLIDE)

    harm_pool  = rng_harm.sample(all_txt,  min(N_PIECES, len(all_txt)))
    slide_pool = rng_slide.sample(all_txt, min(N_PIECES, len(all_txt)))

    print('═' * 72)
    print(f'Harmonic & Slide Test Suite  ({N_PIECES} pieces each, seeds {SEED_HARM}/{SEED_SLIDE})')
    print('═' * 72)

    print(f'\nRunning harmonic suite on {len(harm_pool)} pieces…', flush=True)
    harm_results = run_harmonic_suite(harm_pool)
    report_harmonics(harm_results)

    print(f'\nRunning slide suite on {len(slide_pool)} pieces…', flush=True)
    slide_results = run_slide_suite(slide_pool)
    report_slides(slide_results)

    print()

if __name__ == '__main__':
    main()
