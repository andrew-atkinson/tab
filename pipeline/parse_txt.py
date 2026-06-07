"""
parse_txt.py
============
Parser for the classtab.org ASCII guitar tab format — handles many variants.

This module is the main entry point.  Parsing is delegated to three
focused sub-modules:

  topmatter_parser  — title, composer, transcriber, tuning, chords
  tab_parser        — tab systems, notes, fingering
  bottom_parser     — notes/legend, dynamics, biographical info

Format variants supported
--------------------------
• Standard classtab (Roman barres CII, cIV; measure number at system start)
• Arabic-numeral barres (C2, C7)
• Systems with no leading measure number → global counter continues
• String-line prefixes: E|  e|  E-|  E-||  e:  E:
• Right-hand pima fingering lines above the string block
• Harmonics:  <7>  →  NoteEvent.harmonic = True
• Repeats:    *|  |*  ||: :|  :|: → repeat_start / repeat_end
• Triplets:   |-3-|  →  NoteEvent.triplet = True
• Held notes: ===  →  NoteEvent.tied = True
• Techniques: /  \\  h  p  b  ~
• Title lines preceded by #---PLEASE NOTE---# or *** separators
• Tuning "tuning: EADGBE" or "tuning - E A D G B E" or "Tune 6th to D"
  or "Drop D" etc.
• Authors given on "Author:" / "By:" / "Composer:" lines
"""

from __future__ import annotations

# ── Re-export the data model so existing imports keep working ────────────────
from models import NoteEvent, BarreMarker, MeasureData, TabMetadata, TabFile

# ── Sub-parsers ──────────────────────────────────────────────────────────────
from topmatter_parser import parse_topmatter
from tab_parser import (
    parse_tab,
    tuning_to_midi,
    note_midi,
    tuning_open_notes,
    find_systems as _find_systems,
)
from bottom_parser import parse_bottom

# Public API — includes re-exports kept for backward compatibility
__all__ = [
    'parse',
    # data model
    'NoteEvent', 'BarreMarker', 'MeasureData', 'TabMetadata', 'TabFile',
    # pitch utilities (originally in parse_txt, now delegated to tab_parser)
    'tuning_to_midi', 'note_midi', 'tuning_open_notes',
    # system detection (used by test_pipeline.py)
    '_find_systems',
]


# ---------------------------------------------------------------------------
# Main parse
# ---------------------------------------------------------------------------

def parse(path: str) -> TabFile:
    """
    Parse a classtab .txt file and return a TabFile.

    Delegates to:
      • topmatter_parser.parse_topmatter  — header fields
      • tab_parser.parse_tab              — measure / note data
      • bottom_parser.parse_bottom        — footer text
    """
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()

    lines = text.splitlines()

    # ── Top matter ──────────────────────────────────────────────────────────
    tm = parse_topmatter(lines)

    meta = TabMetadata(
        title          = tm['title'],
        subtitle       = tm['subtitle'],
        composer       = tm['composer'],
        composer_dates = tm['composer_dates'],
        transcriber    = tm['transcriber'],
        tuning         = tm['tuning'],
        key            = tm['key'],
        time_sig       = tm['time_sig'],
        tempo          = tm['tempo'],
        tempo_unit     = tm['tempo_unit'],
        capo           = tm['capo'],
        chords         = tm['chords'],
    )

    # ── Tab body ────────────────────────────────────────────────────────────
    measures = parse_tab(lines, tuning_str=meta.tuning)

    # ── Bottom matter ───────────────────────────────────────────────────────
    bm = parse_bottom(lines)
    meta.notes_text   = bm['notes_text']
    meta.dynamics     = bm['dynamics']
    meta.biographical = bm['biographical']

    return TabFile(metadata=meta, measures=measures, raw_text=text)
