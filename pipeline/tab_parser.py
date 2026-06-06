"""
tab_parser.py
=============
Functions for parsing the tab-body section of classtab ASCII guitar tabs.

The tab body consists of one or more *systems* — groups of 6 string lines
representing a segment of the piece.  Each system may be preceded by a
measure-number line, a barre annotation line, and/or a right-hand (pima)
fingering line, and followed by left-hand fingering digit lines.

Tuning awareness
----------------
The parser accepts a *tuning_str* (e.g. "EADGBE", low→high) and uses it to:
  • Label each string with its open-string note name
  • Compute the sounding MIDI pitch of every NoteEvent (stored as
    NoteEvent.midi_pitch for downstream use)

Public API
----------
  parse_tab(lines, tuning_str)  -> dict[int, MeasureData]

Internal helpers (also importable for testing):
  find_systems(lines)                          -> list[dict]
  content_start(ref_line)                      -> int
  bar_positions(string_lines)                  -> list[int]
  measure_cells(string_lines, bar_positions)   -> list[tuple[int,int]]
  extract_notes(cell, string_num, col_offset,
                open_note, tuning_midi)        -> list[NoteEvent]
  parse_barres(barre_line, col_start, col_end) -> list[BarreMarker]
  assign_lh_fingering(notes, finger_lines)     -> None  (mutates notes)
  assign_rh_fingering(notes, pima_line)        -> None  (mutates notes)
"""

from __future__ import annotations
import re
from typing import Optional

from models import NoteEvent, BarreMarker, MeasureData


# ---------------------------------------------------------------------------
# Tuning helpers
# ---------------------------------------------------------------------------

_NOTE_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
_STD_TUNING_MIDI   = [64, 59, 55, 50, 45, 40]   # high→low (e4 B3 G3 D3 A2 E2)
_STD_MIDI_LOW_HIGH = [40, 45, 50, 55, 59, 64]

# Standard note names for each semitone (prefer sharps)
_SEMI_TO_NAME = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def tuning_to_midi(tuning_str: str) -> list[int]:
    """
    Convert tuning string (low→high, e.g. 'EADGBE') to a list of 6 MIDI
    pitches ordered high→low (string 1 first).
    """
    t = re.sub(r'\s+', '', tuning_str.upper())
    if len(t) < 6:
        return list(_STD_TUNING_MIDI)
    t = t[:6]
    result = []
    for i, ch in enumerate(t):
        sharp = (len(t) > i + 1 and t[i + 1] == '#')
        semi  = _NOTE_SEMI.get(ch, 4) + (1 if sharp else 0)
        std   = _STD_MIDI_LOW_HIGH[i]
        best  = min(range(1, 7), key=lambda o: abs(12 * (o + 1) + semi - std))
        result.append(12 * (best + 1) + semi)
    return list(reversed(result))


def tuning_open_notes(tuning_str: str) -> list[str]:
    """
    Return the open-string note names (with octave) ordered high→low,
    e.g. ['E4', 'B3', 'G3', 'D3', 'A2', 'E2'] for standard tuning.
    """
    midi_list = tuning_to_midi(tuning_str)
    names = []
    for midi in midi_list:
        semitone = midi % 12
        octave   = midi // 12 - 1
        names.append(f"{_SEMI_TO_NAME[semitone]}{octave}")
    return names


def note_midi(string_num: int, fret: int, tuning_midi: list[int]) -> int:
    """Return the MIDI pitch for a given string number (1=high) and fret."""
    if 1 <= string_num <= 6:
        return tuning_midi[string_num - 1] + fret
    return -1


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------

_STRING_LINE_RE = re.compile(
    r'^\s*[a-gA-G][#b]?[-]?\s*[|:]'      # A/A'/A": letter[#b] + pipe/colon
    r'|^\s*[a-gA-G][#b]?-+'              # B:        letter[#b] + 1+ dashes
    r'|^\s*\|\|[-0-9]'                   # C:        ||-- or ||digit
    r'|^\s*\|[-0-9]'                     # D:        |-- or |digit
    r'|^\s*-+[-0-9|/\\hpb~=<>*.]*\|'    # E/F:      dash(es)…barline
)

_MNUM_STRICT_RE = re.compile(r'^\s*\d+\s+[|.$]|^\s*\d+\s*$')

_BARRE_RE = re.compile(
    r'(?<![a-zA-Z])(?P<type>[cC])'
    r'(?P<num>[IVXivx]{1,5}|\d{1,2})'
    r'(?P<trail>[-_\s]*)',
)

_ROMAN = {
    'XII': 12, 'XI': 11, 'X': 10, 'IX': 9, 'VIII': 8,
    'VII': 7,  'VI': 6,  'V': 5,  'IV': 4, 'III': 3,
    'II': 2,   'I': 1,
}

def _parse_fret_num(s: str) -> int:
    su = s.upper()
    if su.isdigit():
        return int(su)
    return _ROMAN.get(su, 0)


_PIMA_RE  = re.compile(r'^[\s\-pima]+$', re.IGNORECASE)
_HAS_PIMA = re.compile(r'[pima]', re.IGNORECASE)
_FINGER_RE = re.compile(r'^[\d\s]+$')
_TRIPLET_RE = re.compile(r'-3-')


# ---------------------------------------------------------------------------
# System detection
# ---------------------------------------------------------------------------

def find_systems(lines: list[str]) -> list[dict]:
    """
    Find all tab systems in *lines* and return structural info for each.

    Each system dict has:
        mnum_idx    : int | None   — line index of the measure-number line
        barre_idx   : int | None   — line index of the barre annotation line
        pima_idx    : int | None   — line index of the right-hand pima line
        string_idxs : list[int]    — line indices of the 6 string lines
        finger_idxs : list[int]    — line indices of left-hand finger digit lines
    """
    systems: list[dict] = []
    i = 0
    while i < len(lines):
        if _STRING_LINE_RE.match(lines[i]):
            string_idxs = [i]
            j = i + 1
            while j < len(lines) and _STRING_LINE_RE.match(lines[j]) and len(string_idxs) < 6:
                string_idxs.append(j)
                j += 1

            if len(string_idxs) < 4:
                i += 1
                continue

            if len(string_idxs) == 6:
                mnum_idx  = None
                barre_idx = None
                pima_idx  = None

                for k in range(i - 1, max(i - 6, -1), -1):
                    ln = lines[k]
                    if _STRING_LINE_RE.match(ln):
                        break
                    if _MNUM_STRICT_RE.match(ln):
                        mnum_idx = k
                        break
                    if _BARRE_RE.search(ln) and barre_idx is None:
                        barre_idx = k

                # pima line immediately before string block
                if i > 0 and _HAS_PIMA.search(lines[i - 1]) and _PIMA_RE.match(lines[i - 1]):
                    pima_idx = i - 1

                # Fingering lines after the strings
                finger_idxs: list[int] = []
                fj = j
                while fj < len(lines) and len(finger_idxs) < 3:
                    fl = lines[fj].rstrip()
                    if not fl or _STRING_LINE_RE.match(fl) or _MNUM_STRICT_RE.match(fl):
                        break
                    if _FINGER_RE.match(fl) and re.search(r'\d', fl):
                        finger_idxs.append(fj)
                        fj += 1
                    else:
                        break

                systems.append({
                    'mnum_idx':    mnum_idx,
                    'barre_idx':   barre_idx,
                    'pima_idx':    pima_idx,
                    'string_idxs': string_idxs,
                    'finger_idxs': finger_idxs,
                })
                i = j
                continue
        i += 1
    return systems


# ---------------------------------------------------------------------------
# Bar / cell geometry
# ---------------------------------------------------------------------------

def content_start(ref_line: str) -> int:
    """
    Column where tab content starts — strips string-letter or pipe prefix.

    Handles all classtab format variants:
      A  E|----    letter + pipe
      B  E----     letter + dashes
      C  ||----    double-pipe
      D  |----     single-pipe
      E  ----      plain dashes
    """
    m = re.match(r'^\s*[a-gA-G][#b]?[-]?\s*[|:]+', ref_line)
    if m:
        return m.end()
    m = re.match(r'^\s*([a-gA-G][#b]?)-+', ref_line)
    if m:
        return m.end(1)
    m = re.match(r'^\s*\|\|', ref_line)
    if m:
        return m.end()
    m = re.match(r'^\s*\|', ref_line)
    if m:
        return m.end()
    return 0


def bar_positions(string_lines: list[str]) -> list[int]:
    """
    Return column positions of true barline '|' characters, excluding the
    string-name prefix.  Consecutive '||' (double bar) is collapsed to one.
    """
    ref    = string_lines[0]
    cstart = content_start(ref)

    true_bars: list[int] = []
    prev = -99
    for m in re.finditer(r'\|', ref):
        pos = m.start()
        if pos < cstart:
            continue
        if pos == prev + 1:
            if true_bars:
                true_bars[-1] = pos
        else:
            true_bars.append(pos)
        prev = pos
    return true_bars


def measure_cells(string_lines: list[str], bar_pos: list[int]) -> list[tuple[int, int]]:
    """Return (col_start, col_end) for each measure cell in the system."""
    ref   = string_lines[0]
    start = content_start(ref)
    cells: list[tuple[int, int]] = []

    if not bar_pos:
        cells.append((start, len(ref)))
        return cells

    if bar_pos[0] > start:
        cells.append((start, bar_pos[0]))

    for i in range(len(bar_pos) - 1):
        cells.append((bar_pos[i] + 1, bar_pos[i + 1]))

    last_start = bar_pos[-1] + 1
    if last_start < len(ref):
        snippet = ref[last_start:].replace('-', '').replace('=', '').replace('|', '').strip()
        if snippet:
            cells.append((last_start, len(ref)))

    return cells


def _first_measure_number(mnum_line: Optional[str]) -> Optional[int]:
    if not mnum_line:
        return None
    m = re.search(r'(\d+)', mnum_line)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Note extraction (tuning-aware)
# ---------------------------------------------------------------------------

_HARMONIC_RE = re.compile(r'<(\d{1,2})>')

_TECH_MAP = {
    '/':  'slide_up',
    '\\': 'slide_down',
    'h':  'hammer',
    'p':  'pull',
    'b':  'bend',
    '~':  'vibrato',
}


def extract_notes(
    cell: str,
    string_num: int,
    col_offset: int,
    open_note: str,
    tuning_midi: list[int],
) -> list[NoteEvent]:
    """
    Extract NoteEvents from a single measure cell for one string.

    Parameters
    ----------
    cell        : tab content for this string/measure slice (no prefix)
    string_num  : 1 = high e … 6 = low E
    col_offset  : column of the start of *cell* in the full line (for col bookkeeping)
    open_note   : open-string note name, e.g. "E4"  (for annotation)
    tuning_midi : list of 6 MIDI pitches, high→low
    """
    events: list[NoteEvent] = []
    inside_triplet = bool(_TRIPLET_RE.search(cell))
    pos = 0

    while pos < len(cell):
        ch = cell[pos]

        # Harmonic <7>
        hm = _HARMONIC_RE.match(cell, pos)
        if hm:
            fret = int(hm.group(1))
            midi = note_midi(string_num, fret, tuning_midi)
            events.append(NoteEvent(
                string=string_num, fret=fret,
                col=col_offset + pos,
                harmonic=True, triplet=inside_triplet,
                open_note=open_note, midi_pitch=midi,
            ))
            pos = hm.end()
            continue

        if ch.isdigit():
            j = pos + 1
            while j < len(cell) and cell[j].isdigit():
                j += 1
            fret = int(cell[pos:j])
            tech_ch = cell[j] if j < len(cell) else ''
            technique = _TECH_MAP.get(tech_ch)
            post = j + (1 if technique else 0)

            # Slide notation: 1/5 or 7\5 — the digit(s) after the technique
            # character are the *destination* fret, not a separately struck note.
            # Consume them and store as slide_to so they don't become a phantom
            # NoteEvent on the next iteration.
            slide_to: int | None = None
            if technique in ('slide_up', 'slide_down'):
                k = post
                while k < len(cell) and cell[k].isdigit():
                    k += 1
                if k > post:
                    slide_to = int(cell[post:k])
                    post = k   # skip past the destination fret

            tied = post < len(cell) and cell[post] == '='
            midi = note_midi(string_num, fret, tuning_midi)
            events.append(NoteEvent(
                string=string_num, fret=fret,
                col=col_offset + pos,
                technique=technique, tied=tied,
                triplet=inside_triplet,
                open_note=open_note, midi_pitch=midi,
                slide_to=slide_to,
            ))
            pos = post
        else:
            pos += 1

    return events


# ---------------------------------------------------------------------------
# Barre detection
# ---------------------------------------------------------------------------

def parse_barres(barre_line: str, col_start: int, col_end: int) -> list[BarreMarker]:
    """Parse barre markers (CII, cIV, C5, etc.) within the given column range."""
    markers = []
    for m in _BARRE_RE.finditer(barre_line):
        b_start, b_end = m.start(), m.end()
        if b_start < col_end and b_end > col_start:
            fret = _parse_fret_num(m.group('num'))
            if fret > 0:
                markers.append(BarreMarker(
                    fret=fret, partial=(m.group('type') == 'c'),
                    col_start=b_start, col_end=b_end,
                ))
    return markers


# ---------------------------------------------------------------------------
# Fingering alignment
# ---------------------------------------------------------------------------

def assign_lh_fingering(notes: list[NoteEvent], finger_lines: list[str]) -> None:
    """
    Assign left-hand finger numbers (1-4) to notes by column proximity.
    Mutates notes in place.
    """
    col_to_finger: dict[int, int] = {}
    for fl in finger_lines:
        for fm in re.finditer(r'[1-4]', fl):
            col_to_finger[fm.start()] = int(fm.group())
    if not col_to_finger:
        return
    for note in notes:
        best_dist, best = 4, None
        for fc, ff in col_to_finger.items():
            d = abs(fc - note.col)
            if d < best_dist:
                best_dist, best = d, ff
        note.finger = best


def assign_rh_fingering(notes: list[NoteEvent], pima_line: Optional[str]) -> None:
    """
    Assign right-hand pima finger labels to notes by column proximity.
    Mutates notes in place.
    """
    if not pima_line:
        return
    col_to_rh: dict[int, str] = {}
    for fm in re.finditer(r'[pima]', pima_line, re.IGNORECASE):
        col_to_rh[fm.start()] = fm.group().lower()
    for note in notes:
        best_dist, best = 4, None
        for fc, ff in col_to_rh.items():
            d = abs(fc - note.col)
            if d < best_dist:
                best_dist, best = d, ff
        note.rh_finger = best


# ---------------------------------------------------------------------------
# Repeat / volta detection
# ---------------------------------------------------------------------------

_VOLTA_RE = re.compile(r'(\d)_{3,}')


def detect_repeat_volta(
    string_lines: list[str], col_start: int, col_end: int,
    mnum_line: Optional[str],
) -> tuple[bool, bool, Optional[int]]:
    """
    Detect repeat signs and volta brackets within the given column range.

    Returns (repeat_start, repeat_end, volta_number | None).
    """
    repeat_start = False
    repeat_end   = False
    volta        = None

    for sline in string_lines:
        seg = sline[col_start:col_end] if col_end <= len(sline) else sline[col_start:]
        stripped = seg.rstrip()
        if seg.startswith('*') or seg.startswith(':') or stripped.startswith('*'):
            repeat_start = True
        stripped_no_bar = stripped.rstrip('|')
        if stripped_no_bar.endswith('*') or stripped_no_bar.endswith(':'):
            repeat_end = True

    if mnum_line:
        mnum_cell = mnum_line[col_start:col_end] if col_end <= len(mnum_line) else ''
        vm = _VOLTA_RE.search(mnum_cell)
        if vm:
            volta = int(vm.group(1))

    return repeat_start, repeat_end, volta


# ---------------------------------------------------------------------------
# Main tab parser
# ---------------------------------------------------------------------------

def get_beats(notes: list[NoteEvent]) -> list[list[NoteEvent]]:
    """
    Group NoteEvents into beats — lists of notes that are simultaneous
    (same column value), returned in ascending column order.

    Within each beat group, notes are sorted by string number (1 = highest).

    This is the canonical way to inspect what sounds together vs. what is
    sequential within a measure or across measures.

    Example::

        beats = get_beats(measures[1].notes)
        for beat in beats:
            print([f's{n.string}f{n.fret}' for n in beat])
    """
    col_to_notes: dict[int, list[NoteEvent]] = {}
    for note in notes:
        col_to_notes.setdefault(note.col, []).append(note)
    return [
        sorted(group, key=lambda n: n.string)
        for col in sorted(col_to_notes)
        for group in [col_to_notes[col]]
    ]


def parse_tab(lines: list[str], tuning_str: str = "EADGBE") -> dict[int, MeasureData]:
    """
    Parse all tab systems in *lines* and return a dict of MeasureData objects.

    Parameters
    ----------
    lines      : all lines of the file (from splitlines())
    tuning_str : 6-note tuning, low→high, e.g. "EADGBE" or "DADGBE"

    Returns
    -------
    dict mapping measure_number -> MeasureData
    """
    tuning_midi  = tuning_to_midi(tuning_str)
    open_notes   = tuning_open_notes(tuning_str)  # high→low: string 1 first

    systems  = find_systems(lines)
    measures: dict[int, MeasureData] = {}

    next_global_mnum = 0
    has_repeat_end   = False
    has_repeat_start = False

    for sys in systems:
        mnum_idx    = sys['mnum_idx']
        barre_idx   = sys['barre_idx']
        pima_idx    = sys['pima_idx']
        string_idxs = sys['string_idxs']
        finger_idxs = sys['finger_idxs']

        string_lines = [lines[i] for i in string_idxs]
        finger_lines = [lines[i] for i in finger_idxs]
        mnum_line    = lines[mnum_idx] if mnum_idx is not None else None
        barre_line   = lines[barre_idx] if barre_idx is not None else None
        pima_line    = lines[pima_idx]  if pima_idx  is not None else None

        explicit_mnum = _first_measure_number(mnum_line)
        if explicit_mnum is not None:
            first_mnum       = explicit_mnum
            next_global_mnum = explicit_mnum
        else:
            first_mnum = next_global_mnum

        bar_pos = bar_positions(string_lines)
        cells   = measure_cells(string_lines, bar_pos)

        for cell_idx, (col_start, col_end) in enumerate(cells):
            mnum = first_mnum + cell_idx

            if mnum not in measures:
                measures[mnum] = MeasureData(number=mnum)
            md = measures[mnum]

            rs, re_, volta = detect_repeat_volta(
                string_lines, col_start, col_end, mnum_line)
            if rs:
                md.repeat_start = True
                has_repeat_start = True
            if re_:
                md.repeat_end = True
                has_repeat_end = True
            if volta:
                md.volta = volta

            if barre_line:
                md.barres.extend(parse_barres(barre_line, col_start, col_end))

            all_notes: list[NoteEvent] = []
            for str_idx, sline in enumerate(string_lines):
                string_num = str_idx + 1          # 1 = high e
                open_note  = open_notes[str_idx]  # e.g. "E4"
                if col_start < len(sline):
                    raw   = sline[col_start:col_end] if col_end <= len(sline) else sline[col_start:]
                    clean = raw.replace('*', '-').replace(':', '-')
                    notes = extract_notes(clean, string_num, col_start, open_note, tuning_midi)
                    all_notes.extend(notes)

            assign_lh_fingering(all_notes, finger_lines)
            assign_rh_fingering(all_notes, pima_line)

            md.notes.extend(all_notes)

        next_global_mnum = first_mnum + len(cells)

    # Ensure repeat pairs: if there's a backward repeat but no forward one,
    # add a forward repeat at measure 1.
    if has_repeat_end and not has_repeat_start and measures:
        first_mnum_key = min(measures.keys())
        measures[first_mnum_key].repeat_start = True

    return measures
