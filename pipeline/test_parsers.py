"""
test_parsers.py
===============
Unit tests for the refactored classtab parser modules:
  • topmatter_parser  (find_tuning, find_composer_author_title,
                       find_transcriber, find_chords_fingering, parse_topmatter)
  • tab_parser        (find_systems, content_start, bar_positions,
                       measure_cells, extract_notes, parse_barres,
                       assign_lh_fingering, assign_rh_fingering,
                       detect_repeat_volta, parse_tab)
  • bottom_parser     (find_notes_legend, find_dynamics,
                       find_biographical, parse_bottom)
  • parse_txt.parse   (integration: TabFile round-trip on real files)

Run:
    python pipeline/test_parsers.py
or (from the pipeline/ dir):
    python test_parsers.py
"""

from __future__ import annotations
import sys, os, unittest
from pathlib import Path

HERE  = Path(__file__).parent
ROOT  = HERE.parent
CLASSTAB = ROOT / 'tab'
sys.path.insert(0, str(HERE))


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _load(filename: str) -> list[str]:
    """Load a tab file as a list of stripped lines."""
    path = CLASSTAB / filename
    with open(path, encoding='utf-8', errors='replace') as f:
        return [l.rstrip() for l in f]


# ═══════════════════════════════════════════════════════════════════════════
# topmatter_parser tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFindTuning(unittest.TestCase):

    def test_standard_tuning_default(self):
        """Files with no tuning statement return EADGBE."""
        from topmatter_parser import find_tuning
        lines = ["El Negrito - Antonio Lauro", "Key C", "Time 3/4"]
        self.assertEqual(find_tuning(lines), "EADGBE")

    def test_explicit_tuning_colon(self):
        from topmatter_parser import find_tuning
        lines = ["Tuning: D A D G B E", "some other line"]
        self.assertEqual(find_tuning(lines), "DADGBE")

    def test_explicit_tuning_no_spaces(self):
        from topmatter_parser import find_tuning
        lines = ["tuning: DADGBE", "Key D"]
        self.assertEqual(find_tuning(lines), "DADGBE")

    def test_drop_d(self):
        from topmatter_parser import find_tuning
        lines = ["Some Piece", "Drop D tuning", "Key D"]
        self.assertEqual(find_tuning(lines), "DADGBE")

    def test_tune_sixth_to_d(self):
        from topmatter_parser import find_tuning
        lines = ["Preludes", "Tune the 6th string to D", "Key G"]
        result = find_tuning(lines)
        self.assertTrue(result.endswith('D'), f"Expected 6th string (last char) = D, got {result}")

    def test_tune_first_string(self):
        from topmatter_parser import find_tuning
        lines = ["Some Piece", "Tune the 1st string to D"]
        result = find_tuning(lines)
        self.assertEqual(result[0], 'D')

    def test_real_file_standard_tuning(self):
        from topmatter_parser import find_tuning
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        self.assertEqual(find_tuning(lines), "EADGBE")

    def test_dadgad(self):
        from topmatter_parser import find_tuning
        lines = ["Celtic piece", "DADGAD tuning"]
        self.assertEqual(find_tuning(lines), "DADGAD")


class TestFindComposerAuthorTitle(unittest.TestCase):

    def test_title_dash_composer_dates(self):
        from topmatter_parser import find_composer_author_title
        lines = ["El Negrito - Antonio Lauro (1917-1986)", ""]
        r = find_composer_author_title(lines)
        self.assertEqual(r['title'], "El Negrito")
        self.assertEqual(r['composer'], "Antonio Lauro")
        self.assertEqual(r['composer_dates'], "1917-1986")

    def test_title_dash_composer_no_dates(self):
        from topmatter_parser import find_composer_author_title
        lines = ["Romance - Anonymous", ""]
        r = find_composer_author_title(lines)
        self.assertEqual(r['title'], "Romance")
        self.assertEqual(r['composer'], "Anonymous")

    def test_author_label(self):
        from topmatter_parser import find_composer_author_title
        lines = ["Some Piece", "Author: Fernando Sor", ""]
        r = find_composer_author_title(lines)
        self.assertIn("Sor", r['composer'])

    def test_by_label(self):
        from topmatter_parser import find_composer_author_title
        lines = ["Étude", "By: Leo Brouwer", ""]
        r = find_composer_author_title(lines)
        self.assertIn("Brouwer", r['composer'])

    def test_real_file_lauro(self):
        from topmatter_parser import find_composer_author_title
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        r = find_composer_author_title(lines)
        self.assertIn("Lauro", r['composer'])
        self.assertIn("Negrito", r['title'])

    def test_real_file_villa_lobos(self):
        from topmatter_parser import find_composer_author_title
        lines = _load('villa-lobos_choros_01.txt')
        r = find_composer_author_title(lines)
        self.assertTrue(r['title'])  # should find a title

    def test_spaced_composer(self):
        """Title     Composer with 4+ spaces."""
        from topmatter_parser import find_composer_author_title
        lines = ["Cancion          Antonio Lauro", ""]
        r = find_composer_author_title(lines)
        self.assertIn("Cancion", r['title'])
        self.assertIn("Lauro", r['composer'])


class TestFindTranscriber(unittest.TestCase):

    def test_tabbed_by(self):
        from topmatter_parser import find_transcriber
        lines = ["El Negrito - Antonio Lauro", "",
                 "tabbed by Weed - August 98 - weed@wussu.com"]
        self.assertEqual(find_transcriber(lines), "Weed")

    def test_transcribed_by(self):
        from topmatter_parser import find_transcriber
        lines = ["Romance", "transcribed by John Smith", ""]
        self.assertIn("John Smith", find_transcriber(lines))

    def test_arranged_by(self):
        from topmatter_parser import find_transcriber
        lines = ["Piece", "arranged by Mary Jones", ""]
        self.assertIn("Mary Jones", find_transcriber(lines))

    def test_no_transcriber(self):
        from topmatter_parser import find_transcriber
        lines = ["Romance - Anonymous", "Key Am", "Time 3/4"]
        self.assertEqual(find_transcriber(lines), "")

    def test_real_file_has_transcriber(self):
        from topmatter_parser import find_transcriber
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        t = find_transcriber(lines)
        self.assertNotEqual(t, "")  # this file says "tabbed by Weed"


class TestFindChordsFingeringEmpty(unittest.TestCase):

    def test_no_chords_returns_empty(self):
        from topmatter_parser import find_chords_fingering
        lines = ["El Negrito - Antonio Lauro", "Key C", "Time 3/4"]
        self.assertEqual(find_chords_fingering(lines), [])

    def test_chord_diagram(self):
        """Synthetic chord box detection."""
        from topmatter_parser import find_chords_fingering
        lines = [
            "Am:",
            "x02210",
            "231",
        ]
        # Our detector requires 4+ string lines; this has only 1 → no match
        self.assertEqual(find_chords_fingering(lines), [])


class TestParseTopmatter(unittest.TestCase):

    def test_returns_all_keys(self):
        from topmatter_parser import parse_topmatter
        lines = ["El Negrito - Antonio Lauro (1917-1986)", "Key C", "Time 3/4", "Tempo 120 bpm"]
        r = parse_topmatter(lines)
        for key in ('title', 'composer', 'composer_dates', 'transcriber',
                    'tuning', 'key', 'time_sig', 'tempo', 'tempo_unit', 'capo', 'chords'):
            self.assertIn(key, r, f"Missing key: {key}")

    def test_key_time_tempo(self):
        from topmatter_parser import parse_topmatter
        lines = [
            "El Negrito - Antonio Lauro (1917-1986)",
            "Key C",
            "Time 3/4",
            "Tempo 120 bpm",
        ]
        r = parse_topmatter(lines)
        self.assertEqual(r['key'], 'C')
        self.assertEqual(r['time_sig'], '3/4')
        self.assertEqual(r['tempo'], 120)

    def test_capo(self):
        from topmatter_parser import parse_topmatter
        lines = ["My Piece - Composer", "Capo 2"]
        r = parse_topmatter(lines)
        self.assertEqual(r['capo'], 2)

    def test_real_file(self):
        from topmatter_parser import parse_topmatter
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        r = parse_topmatter(lines)
        self.assertIn("Lauro", r['composer'])
        self.assertEqual(r['tuning'], "EADGBE")
        self.assertEqual(r['time_sig'], "3/4")


# ═══════════════════════════════════════════════════════════════════════════
# tab_parser tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTuningHelpers(unittest.TestCase):

    def test_tuning_to_midi_standard(self):
        from tab_parser import tuning_to_midi
        midi = tuning_to_midi("EADGBE")
        self.assertEqual(len(midi), 6)
        # String 1 (high e) = E4 = MIDI 64
        self.assertEqual(midi[0], 64)
        # String 6 (low E) = E2 = MIDI 40
        self.assertEqual(midi[5], 40)

    def test_tuning_to_midi_drop_d(self):
        from tab_parser import tuning_to_midi
        midi = tuning_to_midi("DADGBE")
        # String 6 (low) should now be D2 = MIDI 38
        self.assertEqual(midi[5], 38)

    def test_note_midi_standard(self):
        from tab_parser import tuning_to_midi, note_midi
        midi = tuning_to_midi("EADGBE")
        # String 1 open = E4 = 64
        self.assertEqual(note_midi(1, 0, midi), 64)
        # String 1 fret 5 = A4 = 69
        self.assertEqual(note_midi(1, 5, midi), 69)
        # String 6 open = E2 = 40
        self.assertEqual(note_midi(6, 0, midi), 40)

    def test_tuning_open_notes_standard(self):
        from tab_parser import tuning_open_notes
        names = tuning_open_notes("EADGBE")
        self.assertEqual(names[0], "E4")   # string 1
        self.assertEqual(names[5], "E2")   # string 6

    def test_tuning_open_notes_drop_d(self):
        from tab_parser import tuning_open_notes
        names = tuning_open_notes("DADGBE")
        self.assertEqual(names[5], "D2")   # string 6 = D


class TestContentStart(unittest.TestCase):

    def test_format_a_pipe(self):
        from tab_parser import content_start
        self.assertEqual(content_start("E|----0-1-"), 2)

    def test_format_a_colon(self):
        from tab_parser import content_start
        self.assertEqual(content_start("E:----0-1-"), 2)

    def test_format_b_dashes(self):
        from tab_parser import content_start
        # letter then dashes: content starts right after the letter
        result = content_start("E----0-1-")
        self.assertGreaterEqual(result, 1)

    def test_format_c_double_pipe(self):
        from tab_parser import content_start
        self.assertEqual(content_start("||----0-1-"), 2)

    def test_format_d_single_pipe(self):
        from tab_parser import content_start
        self.assertEqual(content_start("|----0-1-"), 1)

    def test_format_e_plain(self):
        from tab_parser import content_start
        self.assertEqual(content_start("----0-1-"), 0)


class TestBarPositions(unittest.TestCase):

    def test_no_bars(self):
        from tab_parser import bar_positions
        lines = ["E|----0-1-2-", "B|----------", "G|----------",
                 "D|----------", "A|----------", "E|----------"]
        pos = bar_positions(lines)
        self.assertEqual(pos, [])

    def test_single_bar(self):
        from tab_parser import bar_positions
        lines = ["E|----0---|----1-",
                 "B|--------|------",
                 "G|--------|------",
                 "D|--------|------",
                 "A|--------|------",
                 "E|--------|------"]
        pos = bar_positions(lines)
        self.assertEqual(len(pos), 1)

    def test_multiple_bars(self):
        from tab_parser import bar_positions
        lines = ["E|--0--|--1--|--2-",
                 "B|-----|-----|----",
                 "G|-----|-----|----",
                 "D|-----|-----|----",
                 "A|-----|-----|----",
                 "E|-----|-----|----"]
        pos = bar_positions(lines)
        self.assertEqual(len(pos), 2)


class TestMeasureCells(unittest.TestCase):

    def test_two_cells(self):
        from tab_parser import measure_cells, bar_positions
        lines = ["E|--0--|--1-",
                 "B|-----|----",
                 "G|-----|----",
                 "D|-----|----",
                 "A|-----|----",
                 "E|-----|----"]
        bars = bar_positions(lines)
        cells = measure_cells(lines, bars)
        self.assertEqual(len(cells), 2)

    def test_cell_boundaries_non_overlapping(self):
        from tab_parser import measure_cells, bar_positions
        lines = ["E|--0--|--1--|--2-",
                 "B|-----|-----|----",
                 "G|-----|-----|----",
                 "D|-----|-----|----",
                 "A|-----|-----|----",
                 "E|-----|-----|----"]
        bars  = bar_positions(lines)
        cells = measure_cells(lines, bars)
        for i in range(len(cells) - 1):
            # Each cell starts after the previous ends
            self.assertGreaterEqual(cells[i + 1][0], cells[i][1])


class TestExtractNotes(unittest.TestCase):

    def _midi(self):
        from tab_parser import tuning_to_midi
        return tuning_to_midi("EADGBE")

    def test_single_note(self):
        from tab_parser import extract_notes
        tuning = self._midi()
        notes = extract_notes("--5--", 1, 0, "E4", tuning)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].fret, 5)
        self.assertEqual(notes[0].string, 1)

    def test_two_notes(self):
        from tab_parser import extract_notes
        tuning = self._midi()
        notes = extract_notes("--5--3-", 1, 0, "E4", tuning)
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0].fret, 5)
        self.assertEqual(notes[1].fret, 3)

    def test_harmonic(self):
        from tab_parser import extract_notes
        tuning = self._midi()
        notes = extract_notes("--<7>--", 1, 0, "E4", tuning)
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].harmonic)
        self.assertEqual(notes[0].fret, 7)

    def test_two_digit_fret(self):
        from tab_parser import extract_notes
        tuning = self._midi()
        notes = extract_notes("--12--", 1, 0, "E4", tuning)
        self.assertEqual(notes[0].fret, 12)

    def test_technique_hammer(self):
        from tab_parser import extract_notes
        tuning = self._midi()
        notes = extract_notes("--5h7-", 1, 0, "E4", tuning)
        self.assertEqual(notes[0].technique, "hammer")

    def test_technique_slide(self):
        from tab_parser import extract_notes
        tuning = self._midi()
        notes = extract_notes("--5/7-", 1, 0, "E4", tuning)
        self.assertEqual(notes[0].technique, "slide_up")

    def test_slide_destination_not_separate_note(self):
        """1/5 must produce ONE NoteEvent, not two. The 5 is slide_to, not a new note."""
        from tab_parser import extract_notes, tuning_to_midi
        tuning = tuning_to_midi("EADGBE")
        notes = extract_notes("--1/5--", 4, 0, "D3", tuning)
        self.assertEqual(len(notes), 1,
            f"Expected 1 note for '1/5', got {len(notes)}: "
            f"{[(n.fret, n.technique) for n in notes]}")
        self.assertEqual(notes[0].fret, 1)
        self.assertEqual(notes[0].technique, "slide_up")
        self.assertEqual(notes[0].slide_to, 5)

    def test_slide_up_stores_destination(self):
        """slide_to field carries the target fret."""
        from tab_parser import extract_notes, tuning_to_midi
        tuning = tuning_to_midi("EADGBE")
        notes = extract_notes("--3/7--", 1, 0, "E4", tuning)
        self.assertEqual(notes[0].slide_to, 7)

    def test_slide_down_destination(self):
        """7\\5 (slide down) also stores slide_to and produces one note."""
        from tab_parser import extract_notes, tuning_to_midi
        tuning = tuning_to_midi("EADGBE")
        notes = extract_notes("--7\\5--", 1, 0, "E4", tuning)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].fret, 7)
        self.assertEqual(notes[0].technique, "slide_down")
        self.assertEqual(notes[0].slide_to, 5)

    def test_slide_without_destination_still_works(self):
        """A bare '/' with no trailing digit keeps existing behaviour."""
        from tab_parser import extract_notes, tuning_to_midi
        tuning = tuning_to_midi("EADGBE")
        notes = extract_notes("--5/--", 1, 0, "E4", tuning)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].technique, "slide_up")
        self.assertIsNone(notes[0].slide_to)

    def test_choros_bar4_no_spurious_slide_note(self):
        """Bar 4 of Choros No.1 must NOT have a phantom fret-5 note on string 4."""
        from tab_parser import parse_tab, get_beats
        lines = _load('villa-lobos_choros_01.txt')
        measures = parse_tab(lines, "EADGBE")
        md = measures[4]
        beats = get_beats(md.notes)
        # Confirm no spurious fret-5 note on any string
        all_s4 = [(n.fret, n.technique, n.slide_to)
                  for b in beats for n in b if n.string == 4]
        fret5_notes = [x for x in all_s4 if x[0] == 5 and x[2] is None]
        self.assertEqual(fret5_notes, [],
            f"Spurious fret-5 note still present: {fret5_notes}")

    def test_midi_pitch_computed(self):
        """open note on string 1 (E4) = MIDI 64; fret 5 = MIDI 69."""
        from tab_parser import extract_notes, tuning_to_midi
        tuning = tuning_to_midi("EADGBE")
        notes = extract_notes("--5--", 1, 0, "E4", tuning)
        self.assertEqual(notes[0].midi_pitch, 69)  # E4 + 5 = A4

    def test_open_note_stored(self):
        from tab_parser import extract_notes, tuning_to_midi
        tuning = tuning_to_midi("EADGBE")
        notes = extract_notes("--0--", 1, 0, "E4", tuning)
        self.assertEqual(notes[0].open_note, "E4")

    def test_drop_d_midi(self):
        """String 6 open in Drop D = D2 = MIDI 38."""
        from tab_parser import extract_notes, tuning_to_midi
        tuning = tuning_to_midi("DADGBE")
        notes = extract_notes("--0--", 6, 0, "D2", tuning)
        self.assertEqual(notes[0].midi_pitch, 38)


class TestParseBarres(unittest.TestCase):

    def test_roman_barre(self):
        from tab_parser import parse_barres
        markers = parse_barres("CII              ", 0, 50)
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].fret, 2)
        self.assertFalse(markers[0].partial)

    def test_partial_barre(self):
        from tab_parser import parse_barres
        markers = parse_barres("cIV              ", 0, 50)
        self.assertEqual(markers[0].fret, 4)
        self.assertTrue(markers[0].partial)

    def test_arabic_barre(self):
        from tab_parser import parse_barres
        markers = parse_barres("C5               ", 0, 50)
        self.assertEqual(markers[0].fret, 5)

    def test_out_of_range_ignored(self):
        from tab_parser import parse_barres
        # barre at col 30-35 but our window is 0-10
        markers = parse_barres("               CII  ", 0, 10)
        self.assertEqual(len(markers), 0)


class TestAssignLhFingering(unittest.TestCase):

    def test_assigns_nearest_finger(self):
        from tab_parser import assign_lh_fingering
        from models import NoteEvent
        notes = [NoteEvent(string=1, fret=5, col=5)]
        finger_lines = ["     2    "]   # digit '2' at col 5
        assign_lh_fingering(notes, finger_lines)
        self.assertEqual(notes[0].finger, 2)

    def test_no_finger_lines(self):
        from tab_parser import assign_lh_fingering
        from models import NoteEvent
        notes = [NoteEvent(string=1, fret=5, col=5)]
        assign_lh_fingering(notes, [])
        self.assertIsNone(notes[0].finger)

    def test_multiple_notes(self):
        from tab_parser import assign_lh_fingering
        from models import NoteEvent
        notes = [
            NoteEvent(string=1, fret=5, col=3),
            NoteEvent(string=2, fret=5, col=7),
        ]
        assign_lh_fingering(notes, ["   1   3   "])
        self.assertEqual(notes[0].finger, 1)
        self.assertEqual(notes[1].finger, 3)


class TestAssignRhFingering(unittest.TestCase):

    def test_pima_assigns(self):
        from tab_parser import assign_rh_fingering
        from models import NoteEvent
        notes = [NoteEvent(string=1, fret=0, col=3)]
        assign_rh_fingering(notes, "   p    ")
        self.assertEqual(notes[0].rh_finger, "p")

    def test_no_pima(self):
        from tab_parser import assign_rh_fingering
        from models import NoteEvent
        notes = [NoteEvent(string=1, fret=0, col=3)]
        assign_rh_fingering(notes, None)
        self.assertIsNone(notes[0].rh_finger)

    def test_ima_assignment(self):
        from tab_parser import assign_rh_fingering
        from models import NoteEvent
        notes = [
            NoteEvent(string=1, fret=0, col=2),
            NoteEvent(string=2, fret=0, col=5),
            NoteEvent(string=3, fret=0, col=8),
        ]
        assign_rh_fingering(notes, "  i  m  a")
        self.assertEqual(notes[0].rh_finger, "i")
        self.assertEqual(notes[1].rh_finger, "m")
        self.assertEqual(notes[2].rh_finger, "a")


class TestDetectRepeatVolta(unittest.TestCase):

    def test_repeat_start(self):
        from tab_parser import detect_repeat_volta
        lines = [
            "*|----0-",
            "*|------",
            "*|------",
            "*|------",
            "*|------",
            "*|------",
        ]
        rs, re_, volta = detect_repeat_volta(lines, 0, 10, None)
        self.assertTrue(rs)
        self.assertFalse(re_)

    def test_repeat_end(self):
        from tab_parser import detect_repeat_volta
        lines = [
            "----0-*|",
            "-------*|",
            "-------*|",
            "-------*|",
            "-------*|",
            "-------*|",
        ]
        rs, re_, volta = detect_repeat_volta(lines, 0, len(lines[0]), None)
        self.assertTrue(re_)

    def test_no_repeat(self):
        from tab_parser import detect_repeat_volta
        lines = ["----0-1-"] * 6
        rs, re_, volta = detect_repeat_volta(lines, 0, 10, None)
        self.assertFalse(rs)
        self.assertFalse(re_)
        self.assertIsNone(volta)


class TestFindSystems(unittest.TestCase):

    def test_finds_systems_in_real_file(self):
        from tab_parser import find_systems
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        systems = find_systems(lines)
        self.assertGreater(len(systems), 0)
        for sys in systems:
            self.assertIn('string_idxs', sys)
            self.assertEqual(len(sys['string_idxs']), 6)

    def test_villa_lobos_pipe_format(self):
        from tab_parser import find_systems
        lines = _load('villa-lobos_choros_01.txt')
        systems = find_systems(lines)
        self.assertGreater(len(systems), 10)


class TestParseTab(unittest.TestCase):

    def test_returns_measures_dict(self):
        from tab_parser import parse_tab
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        measures = parse_tab(lines, "EADGBE")
        self.assertIsInstance(measures, dict)
        self.assertGreater(len(measures), 0)

    def test_notes_have_midi_pitch(self):
        from tab_parser import parse_tab
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        measures = parse_tab(lines, "EADGBE")
        for md in measures.values():
            for note in md.notes:
                self.assertGreater(note.midi_pitch, 0,
                    f"Expected positive MIDI pitch for s{note.string}f{note.fret}")

    def test_notes_have_open_note(self):
        from tab_parser import parse_tab
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        measures = parse_tab(lines, "EADGBE")
        for md in measures.values():
            for note in md.notes:
                self.assertTrue(note.open_note,
                    f"Expected open_note to be set for s{note.string}f{note.fret}")

    def test_drop_d_string6_midi(self):
        """With Drop D tuning, open string 6 should be MIDI 38 (D2)."""
        from tab_parser import parse_tab
        # Synthesize a minimal 6-line tab with an open string 6 note
        lines = [
            "My Piece",
            "0   |",
            "E|------|",
            "B|------|",
            "G|------|",
            "D|------|",
            "A|------|",
            "E|--0---|",
        ]
        measures = parse_tab(lines, "DADGBE")
        all_notes = [n for md in measures.values() for n in md.notes if n.string == 6]
        if all_notes:  # only check if we found string-6 notes
            self.assertEqual(all_notes[0].midi_pitch, 38)

    def test_villa_lobos_measure_count(self):
        from tab_parser import parse_tab
        lines = _load('villa-lobos_choros_01.txt')
        measures = parse_tab(lines, "EADGBE")
        self.assertGreater(len(measures), 50)

    def test_repeat_detection(self):
        from tab_parser import parse_tab
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        measures = parse_tab(lines, "EADGBE")
        starts = sum(1 for md in measures.values() if md.repeat_start)
        ends   = sum(1 for md in measures.values() if md.repeat_end)
        self.assertGreater(starts + ends, 0)


# ═══════════════════════════════════════════════════════════════════════════
# bottom_parser tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFindNotesLegend(unittest.TestCase):

    def test_finds_notes_section(self):
        from bottom_parser import find_notes_legend
        lines = [
            "Some Piece - Composer",
            "E|----0-1-|",
            "B|--------|",
            "G|--------|",
            "D|--------|",
            "A|--------|",
            "E|--------|",
            "",
            "Notes and Legend",
            "0 = open string",
            "h = hammer-on",
        ]
        result = find_notes_legend(lines)
        self.assertIn("Legend", result)
        self.assertIn("open string", result)

    def test_returns_empty_if_not_found(self):
        from bottom_parser import find_notes_legend
        lines = ["A piece", "E|----0-|", "B|------|",
                 "G|------|", "D|------|", "A|------|", "E|------|"]
        result = find_notes_legend(lines)
        self.assertEqual(result, "")

    def test_real_file_lauro(self):
        from bottom_parser import find_notes_legend
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        result = find_notes_legend(lines)
        # El Negrito has "tablature explanation at the end"
        # The actual legend section might or might not be there
        self.assertIsInstance(result, str)


class TestFindDynamics(unittest.TestCase):

    def test_finds_dynamics_in_text(self):
        from bottom_parser import find_dynamics
        lines = [
            "Play this section mf and gradually crescendo to f",
            "The ending should be pp",
        ]
        result = find_dynamics(lines)
        self.assertIsInstance(result, list)
        found = set(result)
        self.assertTrue(found & {'mf', 'f', 'pp', 'crescendo'},
                        f"Expected some dynamics, got {result}")

    def test_no_dynamics(self):
        from bottom_parser import find_dynamics
        lines = ["Just a title", "Key C", "Time 4/4"]
        result = find_dynamics(lines)
        self.assertIsInstance(result, list)

    def test_dynamics_deduped(self):
        from bottom_parser import find_dynamics
        lines = ["Play mf, then mf again, then f"]
        result = find_dynamics(lines)
        self.assertEqual(result.count('mf'), 1)


class TestFindBiographical(unittest.TestCase):

    def test_finds_about_section(self):
        from bottom_parser import find_biographical
        lines = [
            "Piece - Composer",
            "E|----0-|", "B|------|", "G|------|",
            "D|------|", "A|------|", "E|------|",
            "",
            "About the Composer",
            "Antonio Lauro was born in 1917 in Venezuela. He was one of the",
            "most important guitar composers of the 20th century.",
        ]
        result = find_biographical(lines)
        self.assertIn("Lauro", result)

    def test_returns_empty_if_none(self):
        from bottom_parser import find_biographical
        lines = ["Title - Composer", "Key C", "Time 4/4"]
        result = find_biographical(lines)
        self.assertIsInstance(result, str)

    def test_heuristic_bio_detection(self):
        """A paragraph with a year (1800s-1900s) and >60 chars should be detected."""
        from bottom_parser import find_biographical
        lines = [
            "E|--0--|", "B|-----|", "G|-----|",
            "D|-----|", "A|-----|", "E|-----|",
            "",
            "Fernando Sor was born in Barcelona in 1778 and died in Paris in 1839.",
            "He is considered one of the greatest guitarists and composers of his era.",
        ]
        result = find_biographical(lines)
        self.assertIn("1778", result)


class TestParseBottom(unittest.TestCase):

    def test_returns_all_keys(self):
        from bottom_parser import parse_bottom
        lines = ["Title - Composer"]
        result = parse_bottom(lines)
        self.assertIn('notes_text', result)
        self.assertIn('dynamics', result)
        self.assertIn('biographical', result)

    def test_real_file(self):
        from bottom_parser import parse_bottom
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        result = parse_bottom(lines)
        self.assertIsInstance(result['notes_text'], str)
        self.assertIsInstance(result['dynamics'], list)
        self.assertIsInstance(result['biographical'], str)


# ═══════════════════════════════════════════════════════════════════════════
# Beat-structure tests  (tab_parser.get_beats + annotate_xml._merge_parts)
# ═══════════════════════════════════════════════════════════════════════════

class TestGetBeats(unittest.TestCase):
    """Unit tests for tab_parser.get_beats() with synthetic note lists."""

    def test_single_note_is_one_beat(self):
        from tab_parser import get_beats
        from models import NoteEvent
        notes = [NoteEvent(string=1, fret=3, col=10)]
        beats = get_beats(notes)
        self.assertEqual(len(beats), 1)
        self.assertEqual(len(beats[0]), 1)

    def test_two_notes_same_col_one_beat(self):
        from tab_parser import get_beats
        from models import NoteEvent
        notes = [NoteEvent(string=1, fret=3, col=10),
                 NoteEvent(string=5, fret=2, col=10)]
        beats = get_beats(notes)
        self.assertEqual(len(beats), 1)
        self.assertEqual(len(beats[0]), 2)

    def test_two_notes_different_col_two_beats(self):
        from tab_parser import get_beats
        from models import NoteEvent
        notes = [NoteEvent(string=1, fret=3, col=10),
                 NoteEvent(string=4, fret=0, col=12)]
        beats = get_beats(notes)
        self.assertEqual(len(beats), 2)
        self.assertEqual(beats[0][0].fret, 3)
        self.assertEqual(beats[1][0].fret, 0)

    def test_beat_order_is_ascending_col(self):
        from tab_parser import get_beats
        from models import NoteEvent
        notes = [NoteEvent(string=1, fret=0, col=20),
                 NoteEvent(string=3, fret=0, col=16),
                 NoteEvent(string=2, fret=3, col=18)]
        beats = get_beats(notes)
        cols = [b[0].col for b in beats]
        self.assertEqual(cols, [16, 18, 20])

    def test_within_beat_sorted_by_string(self):
        from tab_parser import get_beats
        from models import NoteEvent
        notes = [NoteEvent(string=5, fret=2, col=10),
                 NoteEvent(string=1, fret=3, col=10),
                 NoteEvent(string=3, fret=0, col=10)]
        beats = get_beats(notes)
        self.assertEqual(len(beats), 1)
        strings = [n.string for n in beats[0]]
        self.assertEqual(strings, [1, 3, 5])

    def test_empty_returns_empty(self):
        from tab_parser import get_beats
        self.assertEqual(get_beats([]), [])


# ---------------------------------------------------------------------------
# Reusable mixin: structural invariants that must hold for ANY piece
# ---------------------------------------------------------------------------

class BeatInvariantsMixin:
    """
    Structural invariants for get_beats() and _merge_parts that must hold
    for any correctly parsed piece.

    Concrete subclasses must set two class attributes before the tests run:

        txt_stem : str        — filename stem (no .txt) in tab/
        mid_stem : str | None — filename stem (no .mid) in tab/,
                                or None to skip the XML invariant test

    setUpClass loads the TabFile once and stores it in cls._tab.
    """

    txt_stem: str = ''
    mid_stem: str | None = None
    _tab = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    @classmethod
    def setUpClass(cls):
        from parse_txt import parse
        cls._tab = parse(str(CLASSTAB / (cls.txt_stem + '.txt')))

    # ------------------------------------------------------------------
    # Tab-level invariants (purely from the parsed tab, no MIDI needed)
    # ------------------------------------------------------------------

    def test_inv_beats_ascending_col(self):
        """get_beats() returns beats in strictly ascending column order."""
        from tab_parser import get_beats
        for mnum, md in self._tab.measures.items():
            beats = get_beats(md.notes)
            if not beats:
                continue
            cols = [b[0].col for b in beats]
            self.assertEqual(cols, sorted(cols),
                f"Measure {mnum}: beat columns not ascending: {cols}")

    def test_inv_notes_in_beat_share_col(self):
        """Every note within a beat must have the same column value."""
        from tab_parser import get_beats
        for mnum, md in self._tab.measures.items():
            for bi, beat in enumerate(get_beats(md.notes)):
                cols = {n.col for n in beat}
                self.assertEqual(len(cols), 1,
                    f"Measure {mnum} beat {bi}: notes have mixed cols {cols}")

    def test_inv_within_beat_strings_ascending(self):
        """Within each beat, notes are sorted by ascending string number."""
        from tab_parser import get_beats
        for mnum, md in self._tab.measures.items():
            for bi, beat in enumerate(get_beats(md.notes)):
                strings = [n.string for n in beat]
                self.assertEqual(strings, sorted(strings),
                    f"Measure {mnum} beat {bi}: strings not sorted: {strings}")

    def test_inv_no_empty_beats(self):
        """get_beats() never returns an empty beat group."""
        from tab_parser import get_beats
        for mnum, md in self._tab.measures.items():
            for bi, beat in enumerate(get_beats(md.notes)):
                self.assertGreater(len(beat), 0,
                    f"Measure {mnum}: empty beat at index {bi}")

    def test_inv_all_notes_have_midi_pitch(self):
        """Every parsed note must carry a positive MIDI pitch."""
        for mnum, md in self._tab.measures.items():
            for note in md.notes:
                self.assertGreater(note.midi_pitch, 0,
                    f"Measure {mnum} s{note.string}f{note.fret}: "
                    f"midi_pitch={note.midi_pitch}")

    def test_inv_all_notes_have_open_note(self):
        """Every parsed note must carry an open-string note name."""
        for mnum, md in self._tab.measures.items():
            for note in md.notes:
                self.assertTrue(note.open_note,
                    f"Measure {mnum} s{note.string}f{note.fret}: open_note empty")

    # ------------------------------------------------------------------
    # XML-level invariant (requires a MIDI file; skipped if mid_stem=None)
    # ------------------------------------------------------------------

    def test_inv_xml_offsets_non_decreasing_after_merge(self):
        """
        After _merge_parts, non-chord note offsets within every measure
        must be non-decreasing — no note can start before the previous one.
        """
        if not self.mid_stem:
            self.skipTest("mid_stem not set — skipping XML invariant")
        mid_path = CLASSTAB / (self.mid_stem + '.mid')
        if not mid_path.exists():
            self.skipTest(f"MIDI not found: {mid_path.name}")

        import tempfile, os
        import xml.etree.ElementTree as ET
        from convert_mid import mid_to_musicxml
        from annotate_xml import _merge_parts

        tmp = tempfile.mktemp(suffix='.xml')
        try:
            mid_to_musicxml(str(mid_path), tmp)
            root = ET.parse(tmp).getroot()
            _merge_parts(root)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

        for part in root.findall('part'):
            for meas in part.findall('measure'):
                mnum     = meas.get('number', '?')
                prev_off = -1
                offset   = 0
                prev_dur = 0
                for note in meas.findall('note'):
                    is_chord = note.find('chord') is not None
                    is_rest  = note.find('rest')  is not None
                    dur = int(note.findtext('duration', '0'))
                    if is_chord:
                        note_off = offset - prev_dur
                    else:
                        note_off = offset
                        prev_dur = dur
                        offset  += dur
                    if not is_chord and not is_rest:
                        self.assertGreaterEqual(note_off, prev_off,
                            f"Part beat regression in measure {mnum}: "
                            f"offset {note_off} < previous {prev_off}")
                        prev_off = note_off


# ---------------------------------------------------------------------------
# Piece-specific tests for El Negrito (exact bar-2 beat sequence)
# ---------------------------------------------------------------------------

class TestBeatStructureElNegrito(BeatInvariantsMixin, unittest.TestCase):
    """
    Inherits all BeatInvariantsMixin invariants AND adds El-Negrito-specific
    checks for the exact note content of bar 2.

    Tab bar 2 (first full bar, after the pickup):
      beat 1  col~20 : s1f3 (G4)  s5f2 (B2)   ← simultaneous
      beat 2  col~22 : s4f0 (D3)              ← alone
      beat 3  col~24 : s3f0 (G3)              ← alone
      beat 4  col~26 : s4f0 (D3)              ← alone
      beat 5  col~28 : s2f3 (D4)              ← alone
      beat 6  col~30 : s3f0 (G3)              ← alone
    """

    txt_stem = 'lauro_two_venezuelan_waltzes_1_el_negrito'
    mid_stem = 'lauro_two_venezuelan_waltzes_1_el_negrito'

    def test_tab_beat1_has_two_notes(self):
        """Beat 1 of bar 2 must have exactly 2 simultaneous notes."""
        from tab_parser import get_beats
        md    = self._tab.measures[1]   # measure 1 = first full bar
        beats = get_beats(md.notes)
        self.assertGreaterEqual(len(beats), 1)
        self.assertEqual(len(beats[0]), 2,
            f"Expected 2 notes at beat 1, got {len(beats[0])}: "
            f"{[f's{n.string}f{n.fret}' for n in beats[0]]}")

    def test_tab_beat1_strings_and_frets(self):
        """Beat 1 notes must be s1f3 (E-string fret-3) and s5f2 (A-string fret-2)."""
        from tab_parser import get_beats
        beats = get_beats(self._tab.measures[1].notes)
        b1    = beats[0]
        self.assertEqual(b1[0].string, 1); self.assertEqual(b1[0].fret, 3)
        self.assertEqual(b1[1].string, 5); self.assertEqual(b1[1].fret, 2)

    def test_tab_subsequent_beats_are_single_notes(self):
        """Beats 2-6 of bar 2 must each be a single note (no spurious chords)."""
        from tab_parser import get_beats
        beats = get_beats(self._tab.measures[1].notes)
        for i, beat in enumerate(beats[1:], start=2):
            self.assertEqual(len(beat), 1,
                f"Beat {i} should have 1 note, got {len(beat)}: "
                f"{[f's{n.string}f{n.fret}' for n in beat]}")

    def test_tab_beat_sequence(self):
        """Full beat sequence of bar 2 must match the tab text exactly."""
        from tab_parser import get_beats
        beats = get_beats(self._tab.measures[1].notes)
        expected = [
            [(1, 3), (5, 2)],   # beat 1: chord  3XXX2X
            [(4, 0)],            # beat 2:        XXX0XX
            [(3, 0)],            # beat 3:        XX0XXX
            [(4, 0)],            # beat 4:        XXX0XX
            [(2, 3)],            # beat 5:        X3XXXX
            [(3, 0)],            # beat 6:        XX0XXX
        ]
        self.assertEqual(len(beats), len(expected),
            f"Expected {len(expected)} beats, got {len(beats)}")
        for bi, (beat, exp) in enumerate(zip(beats, expected)):
            actual = sorted((n.string, n.fret) for n in beat)
            self.assertEqual(actual, sorted(exp),
                f"Beat {bi+1}: expected {exp}, got {actual}")

    def test_xml_bar2_exact_beat_sequence(self):
        """
        After _merge_parts, bar 2's XML must have exactly this offset/midi
        sequence: G4+B2 chord at 0, then D3/G3/D3/D4/G3 sequentially.
        """
        import tempfile, os
        import xml.etree.ElementTree as ET
        from convert_mid import mid_to_musicxml
        from annotate_xml import _merge_parts, _xml_note_midi

        tmp = tempfile.mktemp(suffix='.xml')
        try:
            mid_to_musicxml(str(CLASSTAB / (self.mid_stem + '.mid')), tmp)
            root = ET.parse(tmp).getroot()
            _merge_parts(root)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

        part  = root.findall('part')[0]
        meas2 = part.findall('measure')[1]

        notes_info = []
        offset = 0; prev_dur = 0
        for note in meas2.findall('note'):
            is_chord = note.find('chord') is not None
            is_rest  = note.find('rest')  is not None
            dur = int(note.findtext('duration', '0'))
            if is_chord:
                note_offset = offset - prev_dur
            else:
                note_offset = offset; prev_dur = dur; offset += dur
            if not is_rest:
                notes_info.append((note_offset, _xml_note_midi(note), is_chord))

        expected = [
            (0,     67, False),   # G4  base
            (0,     47, True),    # B2  chord
            (5040,  50, False),   # D3
            (10080, 55, False),   # G3
            (15120, 50, False),   # D3
            (20160, 62, False),   # D4
            (25200, 55, False),   # G3
        ]
        self.assertEqual(notes_info, expected,
            f"XML beat structure wrong.\nGot:      {notes_info}\nExpected: {expected}")


# ---------------------------------------------------------------------------
# Apply BeatInvariantsMixin to additional pieces
# Each class exercises all 7 invariant tests on a different piece/MIDI combo.
# ---------------------------------------------------------------------------

class TestBeatInvariants_VillaLobos(BeatInvariantsMixin, unittest.TestCase):
    """2-part MIDI, 43 systems, 135 measures."""
    txt_stem = 'villa-lobos_choros_01'
    mid_stem = 'villa-lobos_choros_01'


class TestBeatInvariants_Cardoso(BeatInvariantsMixin, unittest.TestCase):
    """3-part MIDI — exercises merging more than 2 parts."""
    txt_stem = 'cardoso_suite_sudamericana_09_aire_de_milonga'
    mid_stem = 'cardoso_suite_sudamericana_09_aire_de_milonga'


class TestBeatInvariants_Barrios(BeatInvariantsMixin, unittest.TestCase):
    """5-part MIDI — stresses the merge heavily."""
    txt_stem = 'barrios_un_sueno_en_la_floresta'
    mid_stem = 'barrios_un_sueno_en_la_floresta'


class TestBeatInvariants_Bach(BeatInvariantsMixin, unittest.TestCase):
    """Single-part MIDI — merge is a no-op; tests tab-only invariants."""
    txt_stem = 'bach_js_bwv0147_10_jesu_joy_of_mans_desiring'
    mid_stem = 'bach_js_bwv0147_10_jesu_joy_of_mans_desiring_1'


class TestBeatInvariants_Albeniz(BeatInvariantsMixin, unittest.TestCase):
    """4-part MIDI — another multi-part stress test."""
    txt_stem = 'albeniz_isaac_op165_no2_tango_in_d'
    mid_stem = 'albeniz_isaac_op165_no2_tango_in_d'


# ═══════════════════════════════════════════════════════════════════════════
# Slide-destination annotation  (annotate_xml._match_within_measure)
# ═══════════════════════════════════════════════════════════════════════════

class TestSlideDestAnnotation(unittest.TestCase):
    """
    Unit tests for the slide-destination-consume logic in
    _match_within_measure.

    Each test builds minimal (offset, note_el) pairs and tab_notes tuples
    and verifies that a MIDI slide-destination note is correctly annotated
    (string + dest fret) rather than left for pitch-fallback.

    Tab-note tuples have 9 elements:
        (midi, string, fret, finger, tech, rh_finger, harmonic,
         slide_dest_midi, slide_dest_fret)
    """

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _note_el(midi: int):
        """Minimal pitched XML note element for the given MIDI pitch."""
        import xml.etree.ElementTree as ET
        semitone   = midi % 12
        octave     = midi // 12 - 1
        step_names = ['C','C','D','D','E','F','F','G','G','A','A','B']
        alters     = [ 0,  1,  0,  1,  0,  0,  1,  0,  1,  0,  1,  0]
        note  = ET.Element('note')
        pitch = ET.SubElement(note, 'pitch')
        ET.SubElement(pitch, 'step').text   = step_names[semitone]
        if alters[semitone]:
            ET.SubElement(pitch, 'alter').text = '1'
        ET.SubElement(pitch, 'octave').text = str(octave)
        ET.SubElement(note, 'duration').text = '1'
        return note

    def _xml(self, *midis):
        """Return xml_notes list from MIDI values (offset = position index)."""
        return [(i, self._note_el(m)) for i, m in enumerate(midis)]

    def _tab(self, midi, string, fret, tech=None,
             slide_dest_midi=None, slide_dest_fret=None):
        """Return a 9-element tab_notes entry."""
        return (midi, string, fret, None, tech, None, False,
                slide_dest_midi, slide_dest_fret)

    # ── core: direct-match path ──────────────────────────────────────────

    def test_dest_annotated_on_direct_match(self):
        """
        When the slide source matches directly, the immediately following MIDI
        note (matching the slide dest pitch) must be annotated with the dest
        fret, not left for pitch-fallback.

        Simulates Choros No.1 bar 4: s4 1/5, source D#3(51)→dest G3(55).
        """
        from annotate_xml import _match_within_measure
        tab    = [self._tab(51, 4, 1, 'slide_up', 55, 5)]
        xml    = self._xml(51, 55)
        result = _match_within_measure(xml, tab)
        self.assertIn(0, result, "Slide source (xi=0) must be matched")
        self.assertIn(1, result, "Slide dest (xi=1) must be in result, not fallback")
        self.assertEqual(result[0][:2], (4, 1),  "Source: s4 fret=1")
        self.assertEqual(result[1][:2], (4, 5),  "Dest:   s4 fret=5")

    def test_dest_annotated_on_direct_match_bar9(self):
        """
        Simulates Choros No.1 bar 9: s1 3/7, source G4(67)→dest B4(71).
        """
        from annotate_xml import _match_within_measure
        tab    = [self._tab(67, 1, 3, 'slide_up', 71, 7)]
        xml    = self._xml(67, 71)
        result = _match_within_measure(xml, tab)
        self.assertIn(0, result)
        self.assertIn(1, result)
        self.assertEqual(result[0][:2], (1, 3), "Source: s1 fret=3")
        self.assertEqual(result[1][:2], (1, 7), "Dest:   s1 fret=7")

    def test_dest_technique_is_slide_stop(self):
        """
        The dest note must carry 'slide_stop' (not 'slide_up') so the
        renderer draws the arrival endpoint of the slide line.
        """
        from annotate_xml import _match_within_measure
        tab    = [self._tab(67, 1, 3, 'slide_up', 71, 7)]
        result = _match_within_measure(self._xml(67, 71), tab)
        self.assertEqual(result[1][3], 'slide_stop',
            "Dest note must carry 'slide_stop', not 'slide_up' or None")

    def test_dest_uses_slide_string(self):
        """Dest annotation must use the slide's string number."""
        from annotate_xml import _match_within_measure
        tab    = [self._tab(51, 4, 1, 'slide_up', 55, 5)]
        result = _match_within_measure(self._xml(51, 55), tab)
        self.assertEqual(result[1][0], 4,
            "Dest string must match the slide's string (4)")

    def test_dest_not_consumed_if_wrong_pitch(self):
        """
        If the note after the slide source does NOT match the dest pitch
        (beyond ±2 semitones), it must NOT be treated as the dest.
        It should instead be matched normally to the next tab note.
        """
        from annotate_xml import _match_within_measure
        # Slide dest should be 71; next MIDI note is 64 (open e) — no match
        tab    = [self._tab(67, 1, 3, 'slide_up', 71, 7),
                  self._tab(64, 1, 0, None, None, None)]
        xml    = self._xml(67, 64)
        result = _match_within_measure(xml, tab)
        # xi=1 (midi=64) must be matched to tab[1] (fret=0), not treated as dest
        self.assertIn(1, result)
        self.assertEqual(result[1][1], 0,
            "xi=1 (midi=64) must map to fret=0, not slide dest fret=7")

    def test_slide_down_dest_annotated(self):
        """Slide-down (\\) annotation works the same as slide-up."""
        from annotate_xml import _match_within_measure
        # s1 7\3: source B4(71) → dest G4(67)
        tab    = [self._tab(71, 1, 7, 'slide_down', 67, 3)]
        xml    = self._xml(71, 67)
        result = _match_within_measure(xml, tab)
        self.assertIn(1, result)
        self.assertEqual(result[1][:2], (1, 3), "Slide-down dest: s1 fret=3")

    # ── skip-TAB match path ───────────────────────────────────────────────

    def test_dest_annotated_on_skip_tab_match(self):
        """
        When the slide is reached via the skip-TAB path (earlier tab notes
        skipped because no XML note matches them), the dest MIDI note must
        still be consumed.

        Replicates Choros No.1 bar 9: three chord notes are skipped before
        the algorithm reaches the slide note.
        """
        from annotate_xml import _match_within_measure
        # XML: [67(source), 71(dest)]
        # Tab: [note_60_no_xml_match, note_50_no_xml_match, slide_67→71]
        tab    = [self._tab(60, 3, 5),
                  self._tab(50, 5, 5),
                  self._tab(67, 1, 3, 'slide_up', 71, 7)]
        xml    = self._xml(67, 71)
        result = _match_within_measure(xml, tab)
        self.assertIn(0, result, "Source (xi=0) matched via skip-TAB")
        self.assertIn(1, result, "Dest (xi=1) annotated after skip-TAB match")
        self.assertEqual(result[0][:2], (1, 3), "Source: s1 fret=3")
        self.assertEqual(result[1][:2], (1, 7), "Dest:   s1 fret=7")

    # ── skip-XML match path ───────────────────────────────────────────────

    def test_dest_annotated_on_skip_xml_match(self):
        """
        When the slide source is reached via the skip-XML path (one XML note
        skipped first), the dest must still be consumed.
        """
        from annotate_xml import _match_within_measure
        # XML: [extra_80_skipped, 67(source), 71(dest)]
        # Tab: [slide_67→71]
        tab    = [self._tab(67, 1, 3, 'slide_up', 71, 7)]
        xml    = self._xml(80, 67, 71)   # 80 is skipped; 67 matches; 71 is dest
        result = _match_within_measure(xml, tab)
        self.assertIn(1, result, "Source (xi=1) matched via skip-XML")
        self.assertIn(2, result, "Dest (xi=2) annotated after skip-XML match")
        self.assertEqual(result[1][:2], (1, 3))
        self.assertEqual(result[2][:2], (1, 7))

    # ── two slides in one measure ─────────────────────────────────────────

    def test_two_slides_both_dests_consumed(self):
        """
        Two slides in one measure: both MIDI dest notes must be annotated.
        Simulates garcia_gerald bar 34 which has two slides.
        """
        from annotate_xml import _match_within_measure
        # Slide 1: s1 3→7 (67→71), Slide 2: s2 1→5 (60→64)
        tab    = [self._tab(67, 1, 3, 'slide_up', 71, 7),
                  self._tab(60, 2, 1, 'slide_up', 64, 5)]
        xml    = self._xml(67, 71, 60, 64)
        result = _match_within_measure(xml, tab)
        self.assertEqual(len(result), 4,
            "All 4 MIDI notes (2 sources + 2 dests) must be in result")
        self.assertEqual(result[0][:2], (1, 3), "Slide1 source: s1 fret=3")
        self.assertEqual(result[1][:2], (1, 7), "Slide1 dest:   s1 fret=7")
        self.assertEqual(result[2][:2], (2, 1), "Slide2 source: s2 fret=1")
        self.assertEqual(result[3][:2], (2, 5), "Slide2 dest:   s2 fret=5")

    # ── no slide: unchanged behaviour ────────────────────────────────────

    def test_non_slide_match_unaffected(self):
        """Normal (non-slide) note matching is unaffected by the new logic."""
        from annotate_xml import _match_within_measure
        tab    = [self._tab(64, 1, 0),
                  self._tab(59, 2, 0)]
        xml    = self._xml(64, 59)
        result = _match_within_measure(xml, tab)
        self.assertEqual(result[0][:2], (1, 0))
        self.assertEqual(result[1][:2], (2, 0))

    # ── measure isolation ─────────────────────────────────────────────────

    def test_measure_isolation_no_drift(self):
        """
        Two consecutive calls (as _match_by_measure makes them) must be
        independent: excess MIDI notes in measure A cannot push the pointer
        into measure B.

        This is the fundamental regression guard: pre-fix, the slide dest
        in bar 9 of Choros No.1 was causing wrong string/fret annotations
        in bar 10.
        """
        from annotate_xml import _match_within_measure

        # Measure A: 1 tab note (slide), 2 MIDI notes (source + dest)
        tab_a  = [self._tab(67, 1, 3, 'slide_up', 71, 7)]
        xml_a  = self._xml(67, 71)
        result_a = _match_within_measure(xml_a, tab_a)

        # Measure B: simple 2-note match, no slide — must be fully correct
        tab_b  = [self._tab(64, 1, 0),
                  self._tab(59, 2, 0)]
        xml_b  = self._xml(64, 59)
        result_b = _match_within_measure(xml_b, tab_b)

        self.assertEqual(result_b.get(0, (None, -1, None))[:2], (1, 0),
            "Measure B first note corrupted by measure A's slide excess")
        self.assertEqual(result_b.get(1, (None, -1, None))[:2], (2, 0),
            "Measure B second note corrupted by measure A's slide excess")


# ═══════════════════════════════════════════════════════════════════════════
# Real-file slide integration  (Choros No. 1, bars 4, 9, 10)
# ═══════════════════════════════════════════════════════════════════════════

class TestNoDuplicateStringsInChord(unittest.TestCase):
    """
    A guitar has only one string per pitch slot: two notes cannot sound
    simultaneously on the same string.  After annotation, every chord group
    (notes sharing a beat offset in the rendered MusicXML) must use distinct
    string numbers.

    Failure here means the annotator assigned the same string to two MIDI
    notes in the same beat — an impossible voicing that produces overlapping
    tab numbers in the rendered score.
    """

    @classmethod
    def _annotated_measures(cls, txt_stem, mid_stem):
        """Return a list of measure elements from the annotated XML."""
        import warnings, tempfile, os
        warnings.filterwarnings('ignore')
        import xml.etree.ElementTree as ET
        from parse_txt import parse
        from tab_parser import tuning_to_midi
        from convert_mid import mid_to_musicxml
        from annotate_xml import _merge_parts, _match_by_measure, _xml_note_midi

        txt = CLASSTAB / (txt_stem + '.txt')
        mid = CLASSTAB / (mid_stem + '.mid')
        if not txt.exists() or not mid.exists():
            return None, None

        tab = parse(str(txt))
        tuning_midi = tuning_to_midi(tab.metadata.tuning)
        tmp = tempfile.mktemp(suffix='.xml')
        try:
            mid_to_musicxml(str(mid), tmp)
            root = ET.parse(tmp).getroot()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        _merge_parts(root)
        matches = _match_by_measure(root, tab, tuning_midi)
        part = root.find('.//part')
        return part.findall('measure'), matches

    def _check_no_dup_strings(self, txt_stem, mid_stem):
        """
        Run the duplicate-string check for one piece.  Any duplicate is
        logged to the issues log AND causes the test to fail so it cannot
        be silently overlooked.
        """
        from annotate_xml import _xml_note_midi
        from issues_log import log_issue
        from parse_txt import parse
        import xml.etree.ElementTree as ET

        measures, matches = self._annotated_measures(txt_stem, mid_stem)
        if measures is None:
            self.skipTest(f'{txt_stem} files not found in tab/')

        tab        = parse(str(CLASSTAB / (txt_stem + '.txt')))
        tab_keys   = sorted(tab.measures.keys())
        failures   = []

        for midx, meas in enumerate(measures):
            tab_mnum   = tab_keys[midx] if midx < len(tab_keys) else None
            offset = 0; prev_dur = 0
            beat_strings: dict[int, list[int]] = {}
            for note in meas.findall('note'):
                is_chord = note.find('chord') is not None
                is_rest  = note.find('rest')  is not None
                dur = int(note.findtext('duration', '0'))
                if is_chord:
                    off = offset - prev_dur
                else:
                    off = offset; prev_dur = dur; offset += dur
                if is_rest or note.find('pitch') is None:
                    continue
                nid = id(note)
                if nid not in matches:
                    continue
                beat_strings.setdefault(off, []).append(matches[nid][0])

            for off, strings in beat_strings.items():
                dups = [s for s in set(strings) if strings.count(s) > 1]
                if dups:
                    msg = (
                        f'{txt_stem} measure #{meas.get("number")} '
                        f'(tab bar {tab_mnum}) offset={off}: '
                        f'duplicate strings {dups} — full beat: {strings}'
                    )
                    log_issue(
                        stem       = txt_stem,
                        title      = tab.metadata.title,
                        composer   = tab.metadata.composer,
                        bar_number = tab_mnum,
                        issue_type = 'duplicate_string_in_beat',
                        details    = msg,
                    )
                    failures.append(msg)

        self.assertEqual(
            failures, [],
            f'{txt_stem}: {len(failures)} beat(s) have duplicate string '
            f'assignments (see issues log):\n' + '\n'.join(failures[:5]),
        )

    # ── pieces covered ────────────────────────────────────────────────────────

    def test_choros_no1_no_dup_strings(self):
        """Choros No.1 (2-part MIDI): no beat may assign the same string twice."""
        self._check_no_dup_strings(
            'villa-lobos_choros_01', 'villa-lobos_choros_01')

    def test_el_negrito_no_dup_strings(self):
        """El Negrito (1-part MIDI): no beat may assign the same string twice."""
        self._check_no_dup_strings(
            'lauro_two_venezuelan_waltzes_1_el_negrito',
            'lauro_two_venezuelan_waltzes_1_el_negrito')

    def test_barrios_no_dup_strings(self):
        """Barrios Un Sueño (5-part MIDI): no beat may assign the same string twice."""
        self._check_no_dup_strings(
            'barrios_un_sueno_en_la_floresta',
            'barrios_un_sueno_en_la_floresta')

    def test_cardoso_no_dup_strings(self):
        """Cardoso milonga (3-part MIDI): no beat may assign the same string twice."""
        self._check_no_dup_strings(
            'cardoso_suite_sudamericana_09_aire_de_milonga',
            'cardoso_suite_sudamericana_09_aire_de_milonga')

    def test_bach_no_dup_strings(self):
        """Bach Jesu Joy (1-part MIDI, alternate stem): no duplicate strings."""
        self._check_no_dup_strings(
            'bach_js_bwv0147_10_jesu_joy_of_mans_desiring',
            'bach_js_bwv0147_10_jesu_joy_of_mans_desiring_1')

    def test_albeniz_no_dup_strings(self):
        """Albéniz Tango (4-part MIDI): no duplicate strings."""
        self._check_no_dup_strings(
            'albeniz_isaac_op165_no2_tango_in_d',
            'albeniz_isaac_op165_no2_tango_in_d')


class TestBarCountInfo(unittest.TestCase):
    """
    Unit tests for tab_parser.bar_count_info() and bar_index_start().

    Verifies that the helpers correctly detect 0-indexed vs 1-indexed pieces
    and compute span / gap counts that feed into the bar-count comparison.
    """

    def _info(self, keys):
        """Build a fake measures dict and return bar_count_info."""
        from tab_parser import bar_count_info
        from models import MeasureData
        measures = {k: MeasureData(number=k) for k in keys}
        return bar_count_info(measures)

    def test_one_indexed_no_gaps(self):
        info = self._info(range(1, 49))   # bars 1..48
        self.assertEqual(info['bar_index_start'],  1)
        self.assertEqual(info['bar_count_written'], 48)
        self.assertEqual(info['bar_count_span'],    48)
        self.assertEqual(info['bar_count_gaps'],     0)

    def test_zero_indexed_no_gaps(self):
        info = self._info(range(0, 48))   # bars 0..47
        self.assertEqual(info['bar_index_start'],   0)
        self.assertEqual(info['bar_count_written'], 48)
        self.assertEqual(info['bar_count_span'],    48)
        self.assertEqual(info['bar_count_gaps'],     0)

    def test_zero_indexed_with_gaps(self):
        """El-Negrito-style: 0-indexed with two repeated sections as gaps."""
        keys = list(range(0, 20)) + list(range(34, 49)) + list(range(64, 81))
        info = self._info(keys)
        self.assertEqual(info['bar_index_start'],   0)
        self.assertEqual(info['bar_count_written'], 52)  # unique bars
        self.assertEqual(info['bar_count_span'],    81)  # 0..80 = 81 slots
        self.assertEqual(info['bar_count_gaps'],    29)

    def test_one_indexed_with_small_gaps(self):
        """Choros-style: 1-indexed with a handful of gaps."""
        keys = list(range(1, 136))        # 1..135 but some missing
        keys = [k for k in keys if k not in {7, 14, 21, 28, 35}]
        info = self._info(keys)
        self.assertEqual(info['bar_index_start'],   1)
        self.assertEqual(info['bar_count_written'], 130)
        self.assertEqual(info['bar_count_span'],    135)
        self.assertEqual(info['bar_count_gaps'],      5)

    def test_empty_measures(self):
        from tab_parser import bar_count_info
        info = bar_count_info({})
        self.assertEqual(info['bar_count_written'], 0)
        self.assertEqual(info['bar_count_span'],    0)

    def test_el_negrito_real_file(self):
        """Verify the real El Negrito file is detected as 0-indexed with gaps."""
        txt = CLASSTAB / 'lauro_two_venezuelan_waltzes_1_el_negrito.txt'
        if not txt.exists():
            self.skipTest('El Negrito not found')
        from parse_txt import parse
        from tab_parser import bar_count_info
        tab  = parse(str(txt))
        info = bar_count_info(tab.measures)
        self.assertEqual(info['bar_index_start'], 0,
            'El Negrito must be detected as 0-indexed')
        self.assertGreater(info['bar_count_gaps'], 0,
            'El Negrito must have gap bars (repeated sections)')
        # Span should be close to MIDI's 80 non-empty measures
        self.assertAlmostEqual(info['bar_count_span'], 80, delta=2,
            msg=f"span={info['bar_count_span']} should be ≈80")

    def test_choros_real_file(self):
        """Choros No.1 is 1-indexed."""
        txt = CLASSTAB / 'villa-lobos_choros_01.txt'
        if not txt.exists():
            self.skipTest('Choros not found')
        from parse_txt import parse
        from tab_parser import bar_count_info
        tab  = parse(str(txt))
        info = bar_count_info(tab.measures)
        self.assertEqual(info['bar_index_start'], 1,
            'Choros No.1 must be detected as 1-indexed')


class TestXmlBarCountMatchesTab(unittest.TestCase):
    """
    The MIDI must have the same number of non-empty measures as the written
    tab (.txt).  The tab is ground truth; the MIDI should reflect it exactly.

    A mismatch is a transcription problem — for example the MIDI was recorded
    with repeats expanded while the tab is written with repeat signs.  We do
    NOT truncate the MIDI silently; instead we record the discrepancy in the
    issues log and fail the test so the problem is visible.

    Bar counts are compared on the RAW (pre-annotation) merged MIDI so no
    post-processing hides the discrepancy.
    """

    @classmethod
    def _bar_counts(cls, txt_stem, mid_stem):
        """
        Return (bci, midi_nonempty) where bci is the bar_count_info dict.
        Returns (None, None) if either file is missing.
        """
        import warnings, tempfile, os
        warnings.filterwarnings('ignore')
        import xml.etree.ElementTree as ET
        from parse_txt import parse
        from tab_parser import bar_count_info
        from convert_mid import mid_to_musicxml
        from annotate_xml import _merge_parts

        txt = CLASSTAB / (txt_stem + '.txt')
        mid = CLASSTAB / (mid_stem + '.mid')
        if not txt.exists() or not mid.exists():
            return None, None

        tab = parse(str(txt))
        bci = bar_count_info(tab.measures)

        tmp = tempfile.mktemp(suffix='.xml')
        try:
            mid_to_musicxml(str(mid), tmp)
            root = ET.parse(tmp).getroot()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

        _merge_parts(root)
        part = root.find('.//part')
        midi_nonempty = sum(
            1 for m in part.findall('measure')
            if any(
                n.find('pitch') is not None and n.find('rest') is None
                for n in m.findall('note')
            )
        ) if part is not None else 0

        return bci, midi_nonempty

    def _check(self, txt_stem, mid_stem):
        """
        Assert MIDI non-empty measure count ≈ tab bar_count_span.

        Uses bar_count_span (max_key − min_key + 1) rather than the simpler
        len(measures), because gap bars in the measure numbering represent
        repeated sections that the MIDI plays through but the tab writes only
        once.  For 0-indexed pieces a difference of exactly 1 is tolerated
        (the pickup bar is often folded into bar 1 in the MIDI).
        """
        from issues_log import log_issue
        from parse_txt import parse

        bci, midi_count = self._bar_counts(txt_stem, mid_stem)
        if bci is None:
            self.skipTest(f'{txt_stem} files not found in tab/')

        index_start  = bci['bar_index_start']
        bar_span     = bci['bar_count_span']
        bar_written  = bci['bar_count_written']
        bar_gaps     = bci['bar_count_gaps']
        diff         = midi_count - bar_span
        pickup_tol   = 1 if index_start == 0 else 0
        mismatch     = abs(diff) > pickup_tol

        if mismatch:
            tab = parse(str(CLASSTAB / (txt_stem + '.txt')))
            log_issue(
                stem       = txt_stem,
                title      = tab.metadata.title,
                composer   = tab.metadata.composer,
                bar_number = None,
                issue_type = 'bar_count_mismatch',
                details    = (
                    f'MIDI has {midi_count} non-empty measures. '
                    f'Tab: index_start={index_start}, span={bar_span}, '
                    f'written={bar_written}, gaps={bar_gaps}. '
                    f'Diff (MIDI−span)={diff:+d}. '
                    f'Likely cause: repeats expanded in MIDI or missing sections.'
                ),
            )

        self.assertFalse(
            mismatch,
            f'{txt_stem}: MIDI has {midi_count} non-empty measures but '
            f'tab span={bar_span} (index_start={index_start}, '
            f'written={bar_written}, gaps={bar_gaps}), diff={diff:+d} '
            f'— exceeds tolerance of ±{pickup_tol} (see issues log).',
        )

    def test_choros_no1_bar_count(self):
        """
        Choros No.1: MIDI measure count must equal tab measure count.
        Known issue: MIDI has 190 non-empty bars vs 135 in the tab — the
        MIDI was recorded with some passages repeated.  This test documents
        the mismatch so it can be investigated and resolved.
        """
        self._check('villa-lobos_choros_01', 'villa-lobos_choros_01')

    def test_el_negrito_bar_count(self):
        """El Negrito: MIDI and tab must agree on bar count."""
        self._check(
            'lauro_two_venezuelan_waltzes_1_el_negrito',
            'lauro_two_venezuelan_waltzes_1_el_negrito',
        )

    def test_barrios_bar_count(self):
        """Barrios Un Sueño: MIDI and tab must agree on bar count."""
        self._check(
            'barrios_un_sueno_en_la_floresta',
            'barrios_un_sueno_en_la_floresta',
        )


# ═══════════════════════════════════════════════════════════════════════════
# New pipeline: midi_timing, repeat_expander, score_builder
# ═══════════════════════════════════════════════════════════════════════════

class TestMidiTiming(unittest.TestCase):
    """Tests for midi_timing.extract_timing() and ticks_to_duration()."""

    @classmethod
    def setUpClass(cls):
        import warnings
        warnings.filterwarnings('ignore')

    def _tm(self, stem):
        from midi_timing import extract_timing
        p = CLASSTAB / (stem + '.mid')
        if not p.exists():
            self.skipTest(f'{stem}.mid not found')
        return extract_timing(str(p))

    # ── El Negrito (3/4, 192 tpb) ────────────────────────────────────────────

    def test_el_negrito_measure_count(self):
        """El Negrito MIDI should produce exactly 81 non-empty measures."""
        tm = self._tm('lauro_two_venezuelan_waltzes_1_el_negrito')
        non_empty = sum(1 for m in tm.measures if m.beat_groups)
        self.assertEqual(non_empty, 81,
            f'Expected 81 non-empty measures, got {non_empty}')

    def test_el_negrito_time_sig(self):
        """El Negrito is in 3/4."""
        tm = self._tm('lauro_two_venezuelan_waltzes_1_el_negrito')
        # Check a typical full measure (not the pickup)
        full = next(m for m in tm.measures if m.beat_groups)
        self.assertEqual(full.time_sig_denom, 4)

    def test_el_negrito_tempo(self):
        """El Negrito tempo is 132 BPM."""
        tm = self._tm('lauro_two_venezuelan_waltzes_1_el_negrito')
        # After the first set_tempo event
        bpms = {round(m.tempo_bpm) for m in tm.measures if m.beat_groups}
        self.assertIn(132, bpms, f'Expected 132 BPM, found {bpms}')

    def test_beat_groups_have_pitches(self):
        """Every non-empty beat group must have at least one MIDI pitch."""
        tm = self._tm('lauro_two_venezuelan_waltzes_1_el_negrito')
        for m in tm.measures:
            for bg in m.beat_groups:
                self.assertTrue(bg.midi_pitches,
                    f'Beat group at offset {bg.onset_ticks} has no pitches')

    def test_beat_group_durations_positive(self):
        """All beat-group durations must be positive."""
        tm = self._tm('lauro_two_venezuelan_waltzes_1_el_negrito')
        for m in tm.measures:
            for bg in m.beat_groups:
                self.assertGreater(bg.duration_ticks, 0,
                    f'Non-positive duration {bg.duration_ticks} at offset '
                    f'{bg.onset_ticks} in measure {m.measure_idx}')

    # ── Choros No.1 (2/4, 192 tpb) ───────────────────────────────────────────

    def test_choros_time_sig(self):
        """Choros No.1 is in 2/4."""
        tm = self._tm('villa-lobos_choros_01')
        m1 = tm.measures[1]
        self.assertEqual(m1.time_sig_num,   2)
        self.assertEqual(m1.time_sig_denom, 4)

    def test_choros_tempo_88(self):
        """Choros No.1 tempo is 88 BPM."""
        tm = self._tm('villa-lobos_choros_01')
        bpms = {round(m.tempo_bpm) for m in tm.measures if m.beat_groups}
        self.assertIn(88, bpms)

    # ── ticks_to_duration ─────────────────────────────────────────────────────

    def test_quarter_note(self):
        from midi_timing import ticks_to_duration
        dur, ntype, dots = ticks_to_duration(192, 192)
        self.assertEqual(ntype, 'quarter')
        self.assertEqual(dots, 0)

    def test_eighth_note(self):
        from midi_timing import ticks_to_duration
        dur, ntype, dots = ticks_to_duration(96, 192)
        self.assertEqual(ntype, 'eighth')

    def test_dotted_quarter(self):
        from midi_timing import ticks_to_duration
        # 192 + 96 = 288 ticks = dotted quarter at 192 tpb
        dur, ntype, dots = ticks_to_duration(288, 192)
        self.assertEqual(ntype, 'quarter')
        self.assertEqual(dots, 1)

    def test_half_note(self):
        from midi_timing import ticks_to_duration
        dur, ntype, dots = ticks_to_duration(384, 192)
        self.assertEqual(ntype, 'half')


class TestRepeatExpander(unittest.TestCase):
    """Tests for repeat_expander.expand_repeats() and build_gap_alias_map()."""

    def _tab(self, stem):
        import warnings; warnings.filterwarnings('ignore')
        from parse_txt import parse
        p = CLASSTAB / (stem + '.txt')
        if not p.exists():
            self.skipTest(f'{stem}.txt not found')
        return parse(str(p))

    # ── Gap alias map ─────────────────────────────────────────────────────────

    def test_alias_map_empty_for_no_gaps(self):
        from repeat_expander import build_gap_alias_map
        from models import MeasureData
        m = {k: MeasureData(number=k) for k in range(1, 11)}
        self.assertEqual(build_gap_alias_map(m), {})

    def test_alias_map_el_negrito(self):
        """El Negrito must have 29 gap aliases covering bars 20-33 and 49-63."""
        from repeat_expander import build_gap_alias_map
        tab   = self._tab('lauro_two_venezuelan_waltzes_1_el_negrito')
        alias = build_gap_alias_map(tab.measures)
        self.assertEqual(len(alias), 29,
            f'Expected 29 gap aliases, got {len(alias)}: {alias}')
        # All aliases must point to written bars
        for gap, src in alias.items():
            self.assertIn(src, tab.measures,
                f'Gap {gap} → {src} but {src} is not a written bar')

    # ── Gap-encoded expansion ────────────────────────────────────────────────

    def test_el_negrito_expansion_matches_midi(self):
        """
        Gap-encoded expansion of El Negrito must produce exactly 81 measures,
        matching the MIDI's non-empty measure count.
        """
        from repeat_expander import expand_repeats
        from midi_timing import extract_timing
        tab = self._tab('lauro_two_venezuelan_waltzes_1_el_negrito')
        exp = expand_repeats(tab)
        tm  = extract_timing(str(CLASSTAB / 'lauro_two_venezuelan_waltzes_1_el_negrito.mid'))
        midi_ne = sum(1 for m in tm.measures if m.beat_groups)
        self.assertEqual(len(exp.measures), midi_ne,
            f'Expanded {len(exp.measures)} ≠ MIDI {midi_ne}')

    def test_el_negrito_pass_numbers(self):
        """Repeated bars must have pass_number=2; first-time bars pass_number=1."""
        from repeat_expander import expand_repeats
        tab = self._tab('lauro_two_venezuelan_waltzes_1_el_negrito')
        exp = expand_repeats(tab)
        passes = {m.pass_number for m in exp.measures}
        self.assertIn(1, passes, 'No first-pass measures found')
        self.assertIn(2, passes, 'No repeated (pass 2) measures found')

    def test_all_sources_are_written_bars(self):
        """Every ExpandedMeasure.source_num must point to a written bar."""
        from repeat_expander import expand_repeats
        tab = self._tab('lauro_two_venezuelan_waltzes_1_el_negrito')
        exp = expand_repeats(tab)
        for em in exp.measures:
            self.assertIn(em.source_num, tab.measures,
                f'source_num {em.source_num} is not a written bar')

    # ── Sign-encoded expansion ───────────────────────────────────────────────

    def test_sign_encoded_length_gt_written(self):
        """Sign-encoded expansion of Barrios must exceed the written count."""
        from repeat_expander import expand_repeats
        tab = self._tab('barrios_un_sueno_en_la_floresta')
        exp = expand_repeats(tab)
        self.assertGreater(len(exp.measures), len(tab.measures),
            'Sign-encoded expansion must be longer than the written score')

    def test_cardoso_zero_indexed_no_gaps(self):
        """Cardoso (0-indexed, no gaps) expands to the same count as written."""
        from repeat_expander import expand_repeats
        from midi_timing import extract_timing
        tab = self._tab('cardoso_suite_sudamericana_09_aire_de_milonga')
        exp = expand_repeats(tab)
        tm  = extract_timing(str(
            CLASSTAB / 'cardoso_suite_sudamericana_09_aire_de_milonga.mid'))
        midi_ne = sum(1 for m in tm.measures if m.beat_groups)
        # Cardoso should be within 1 of MIDI (pickup bar tolerance)
        self.assertAlmostEqual(len(exp.measures), midi_ne, delta=1,
            msg=f'Expanded={len(exp.measures)} MIDI={midi_ne}')


class TestScoreBuilder(unittest.TestCase):
    """Integration tests for score_builder.build_musicxml()."""

    @classmethod
    def setUpClass(cls):
        import warnings, tempfile, os
        warnings.filterwarnings('ignore')
        import xml.etree.ElementTree as ET
        from parse_txt import parse
        from repeat_expander import expand_repeats
        from midi_timing import extract_timing
        from score_builder import build_musicxml

        txt = CLASSTAB / 'lauro_two_venezuelan_waltzes_1_el_negrito.txt'
        mid = CLASSTAB / 'lauro_two_venezuelan_waltzes_1_el_negrito.mid'
        if not txt.exists() or not mid.exists():
            cls._skip = True
            return
        cls._skip = False

        tab = parse(str(txt))
        exp = expand_repeats(tab)
        tm  = extract_timing(str(mid))
        cls._root = build_musicxml(exp, tm, stem='lauro_two_venezuelan_waltzes_1_el_negrito')
        cls._part = cls._root.find('.//part')

    def setUp(self):
        if self._skip:
            self.skipTest('El Negrito files not found')

    def test_correct_measure_count(self):
        """Built score must have 81 measures (= MIDI measure count)."""
        measures = self._part.findall('measure')
        self.assertEqual(len(measures), 81)

    def test_first_note_has_pitch(self):
        """Every <note> must have a <pitch> child."""
        for note in self._root.findall('.//note'):
            if note.find('rest') is not None:
                continue
            self.assertIsNotNone(note.find('pitch'),
                'Note without <pitch> element')

    def test_all_notes_have_string_and_fret(self):
        """Every pitched note must carry <string> and <fret> in <technical>."""
        for note in self._root.findall('.//note'):
            if note.find('rest') is not None:
                continue
            self.assertIsNotNone(note.find('.//string'),
                f'Note missing <string>: {ET.tostring(note, encoding="unicode")[:80]}')
            self.assertIsNotNone(note.find('.//fret'),
                f'Note missing <fret>: {ET.tostring(note, encoding="unicode")[:80]}')

    def test_all_notes_have_duration(self):
        """All notes must have a positive <duration>."""
        for note in self._root.findall('.//note'):
            dur_text = note.findtext('duration')
            self.assertIsNotNone(dur_text, 'Note missing <duration>')
            self.assertGreater(int(dur_text), 0, f'Zero duration on note')

    def test_string_numbers_in_range(self):
        """All <string> values must be 1–6."""
        for s_el in self._root.findall('.//string'):
            v = int(s_el.text)
            self.assertGreaterEqual(v, 1, f'String {v} < 1')
            self.assertLessEqual(v, 6, f'String {v} > 6')

    def test_fret_numbers_non_negative(self):
        """All <fret> values must be ≥ 0."""
        for f_el in self._root.findall('.//fret'):
            self.assertGreaterEqual(int(f_el.text), 0,
                f'Negative fret: {f_el.text}')

    def test_no_duplicate_strings_in_chord(self):
        """Within each chord group, no two notes may share a string number."""
        import xml.etree.ElementTree as ET
        for meas in self._part.findall('measure'):
            # Group notes into chord clusters
            clusters: list[list[ET.Element]] = []
            for note in meas.findall('note'):
                if note.find('rest') is not None:
                    continue
                if note.find('chord') is not None and clusters:
                    clusters[-1].append(note)
                else:
                    clusters.append([note])
            for cluster in clusters:
                strings = [int(n.findtext('.//string', '0')) for n in cluster]
                dups = [s for s in set(strings) if strings.count(s) > 1]
                self.assertEqual(dups, [],
                    f'Measure {meas.get("number")}: duplicate strings {dups}')

    def test_tempo_direction_present(self):
        """First measure must contain a metronome direction."""
        first = self._part.findall('measure')[0]
        metronome = first.find('.//metronome')
        self.assertIsNotNone(metronome, 'No metronome direction in first measure')
        per_minute = first.findtext('.//per-minute')
        self.assertIsNotNone(per_minute)
        self.assertGreater(int(per_minute), 0)

    def test_staff_tuning_present(self):
        """First measure must have <staff-details> with 6 <staff-tuning> lines."""
        first = self._part.findall('measure')[0]
        tunings = first.findall('.//staff-tuning')
        self.assertEqual(len(tunings), 6,
            f'Expected 6 staff-tuning elements, got {len(tunings)}')


import xml.etree.ElementTree as ET   # needed by TestScoreBuilder


class TestChoros01SlideAnnotation(unittest.TestCase):
    """
    Integration tests verifying the full annotate_xml pipeline on Choros
    No. 1:

      • Bar 4 — 1/5 slide on string 4: MIDI dest (G3=55) → s4 fret=5
      • Bar 9 — 3/7 slide on string 1: MIDI dest (B4=71) → s1 fret=7
      • Bar 9 — slide source (G4=67) correctly kept as s1 fret=3
      • Bar 10 — no invalid string/fret values; fret=10 high note intact

    Each assertion would have failed before the _consume_slide_dest fix.
    """

    @classmethod
    def setUpClass(cls):
        import warnings
        warnings.filterwarnings('ignore')
        import tempfile, os
        import xml.etree.ElementTree as ET
        from parse_txt import parse
        from tab_parser import tuning_to_midi
        from convert_mid import mid_to_musicxml
        from annotate_xml import _merge_parts, _match_by_measure, _xml_note_midi

        txt = CLASSTAB / 'villa-lobos_choros_01.txt'
        mid = CLASSTAB / 'villa-lobos_choros_01.mid'

        if not txt.exists() or not mid.exists():
            cls._available = False
            return

        cls._available = True
        tab = parse(str(txt))
        cls._xml_note_midi = staticmethod(_xml_note_midi)

        tuning_midi = tuning_to_midi(tab.metadata.tuning)

        tmp = tempfile.mktemp(suffix='.xml')
        try:
            mid_to_musicxml(str(mid), tmp)
            root = ET.parse(tmp).getroot()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

        _merge_parts(root)
        cls._matches = _match_by_measure(root, tab, tuning_midi)
        part = root.find('.//part')
        cls._xml_measures = part.findall('measure')

    def setUp(self):
        if not self._available:
            self.skipTest("villa-lobos_choros_01 files not found in tab/")

    def _pitched(self, meas_idx):
        """Pitched, non-rest notes from the given measure index (0-based)."""
        return [n for n in self._xml_measures[meas_idx].findall('note')
                if n.find('pitch') is not None
                and n.find('rest') is None]

    def _annotation(self, note_el):
        """Return (string, fret) from matches, or None if unmatched."""
        nid = id(note_el)
        if nid in self._matches:
            m = self._matches[nid]
            return m[0], m[1]
        return None

    # ── bar 4: 1/5 slide on string 4 ─────────────────────────────────────

    def test_bar4_slide_source_s4_fret1(self):
        """Bar 4: slide source D#3(51) must be annotated as s4 fret=1."""
        sources = [n for n in self._pitched(3)
                   if self._xml_note_midi(n) == 51]
        # Last 51 in the bar is the slide source (earlier 51s are chord hits)
        self.assertTrue(sources, "midi=51 note not found in bar 4")
        ann = self._annotation(sources[-1])
        self.assertIsNotNone(ann, "Slide source (midi=51, last) must be matched")
        self.assertEqual(ann, (4, 1), f"Expected (s4, fret=1), got {ann}")

    def test_bar4_slide_dest_s4_fret5(self):
        """
        Bar 4: slide dest G3(55) must be annotated as s4 fret=5, not left for
        pitch-fallback (which would return s3 fret=0 — a spurious open-G note).
        """
        dest_notes = [n for n in self._pitched(3)
                      if self._xml_note_midi(n) == 55]
        self.assertTrue(dest_notes, "midi=55 (slide dest) not found in bar 4")
        dest = dest_notes[-1]
        self.assertIn(id(dest), self._matches,
            "Slide dest (midi=55) must be in matches, not pitch-fallback")
        ann = self._annotation(dest)
        self.assertEqual(ann[0], 4, f"Dest must be on string 4, got s{ann[0]}")
        self.assertEqual(ann[1], 5, f"Dest must be fret=5, got fret={ann[1]}")

    # ── bar 9: 3/7 slide on string 1 ─────────────────────────────────────

    def test_bar9_slide_source_s1_fret3(self):
        """Bar 9: slide source G4(67) must be annotated as s1 fret=3."""
        sources = [n for n in self._pitched(8)
                   if self._xml_note_midi(n) == 67]
        self.assertTrue(sources, "midi=67 (slide source) not found in bar 9")
        ann = self._annotation(sources[-1])
        self.assertIsNotNone(ann, "Slide source (midi=67) must be matched")
        self.assertEqual(ann, (1, 3), f"Expected (s1, fret=3), got {ann}")

    def test_bar9_slide_dest_s1_fret7(self):
        """
        Bar 9: slide dest B4(71) must be annotated as s1 fret=7, not left
        for pitch-fallback (which would return s1 fret=7 by luck from
        _pitch_to_string_fret, but ONLY because fret=7 happens to be the
        lowest; in other keys the fallback would be wrong).
        """
        dests = [n for n in self._pitched(8)
                 if self._xml_note_midi(n) == 71]
        self.assertTrue(dests, "midi=71 (slide dest) not found in bar 9")
        dest = dests[-1]
        self.assertIn(id(dest), self._matches,
            "Slide dest (midi=71) in bar 9 must be explicitly matched")
        ann = self._annotation(dest)
        self.assertEqual(ann[0], 1, f"Dest must be on string 1, got s{ann[0]}")
        self.assertEqual(ann[1], 7, f"Dest must be fret=7, got fret={ann[1]}")

    # ── bar 10: no corruption from bar 9 slide ────────────────────────────

    def test_bar10_no_invalid_string_or_fret(self):
        """
        Bar 10 must contain no matched note with string < 1, string > 6, or
        fret < 0.  Any such value indicates drift from the bar-9 slide.

        Pre-fix, the bar-9 slide dest landing in pitch-fallback would produce
        a spurious extra note in bar 9.  This is an independent per-measure
        test, but since _match_by_measure is measure-isolated, bar 10 should
        be clean regardless; we verify it explicitly.
        """
        for note in self._pitched(9):
            ann = self._annotation(note)
            if ann is None:
                continue   # unmatched → pitch-fallback; tested separately below
            string, fret = ann
            self.assertGreaterEqual(string, 1, f"bar 10: string={string} < 1")
            self.assertLessEqual(string,   6, f"bar 10: string={string} > 6")
            self.assertGreaterEqual(fret,   0, f"bar 10: fret={fret} < 0")

    def test_bar10_high_note_fret10_on_s1(self):
        """
        Bar 10's highest note is D#5 (midi=74, s1 fret=10).
        Whether matched or pitch-fallback, it must resolve to (s1, fret=10).
        """
        from annotate_xml import _pitch_to_string_fret
        midi74 = next(
            (n for n in self._pitched(9) if self._xml_note_midi(n) == 74),
            None)
        self.assertIsNotNone(midi74,
            "midi=74 (fret 10 on s1) must exist in bar 10")
        ann = self._annotation(midi74)
        if ann is None:
            ann = _pitch_to_string_fret(74)
        self.assertEqual(ann[0], 1,  f"midi=74 must be on s1, got s{ann[0]}")
        self.assertEqual(ann[1], 10, f"midi=74 must be fret=10, got {ann[1]}")


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests — parse_txt.parse
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):

    def _parse(self, filename: str):
        from parse_txt import parse
        return parse(str(CLASSTAB / filename))

    def test_lauro_el_negrito(self):
        tab = self._parse('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        self.assertIn("Lauro", tab.metadata.composer)
        self.assertIn("Negrito", tab.metadata.title)
        self.assertEqual(tab.metadata.tuning, "EADGBE")
        self.assertGreater(len(tab.measures), 30)
        total_notes = sum(len(m.notes) for m in tab.measures.values())
        self.assertGreater(total_notes, 100)

    def test_villa_lobos_choros(self):
        tab = self._parse('villa-lobos_choros_01.txt')
        self.assertGreater(len(tab.measures), 50)

    def test_bach_milonga(self):
        tab = self._parse('cardoso_suite_sudamericana_09_aire_de_milonga.txt')
        self.assertGreater(len(tab.measures), 0)

    def test_metadata_has_transcriber(self):
        tab = self._parse('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        self.assertNotEqual(tab.metadata.transcriber, "")

    def test_all_notes_have_midi_pitch(self):
        tab = self._parse('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        bad = [(n.string, n.fret) for md in tab.measures.values()
               for n in md.notes if n.midi_pitch <= 0]
        self.assertEqual(bad, [], f"Notes with missing MIDI pitch: {bad[:5]}")

    def test_notes_have_open_note(self):
        tab = self._parse('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        bad = [(n.string, n.fret) for md in tab.measures.values()
               for n in md.notes if not n.open_note]
        self.assertEqual(bad, [], f"Notes missing open_note: {bad[:5]}")

    def test_backward_compat_find_systems(self):
        """_find_systems imported from parse_txt should still work."""
        from parse_txt import _find_systems
        lines = _load('lauro_two_venezuelan_waltzes_1_el_negrito.txt')
        systems = _find_systems(lines)
        self.assertGreater(len(systems), 0)

    def test_backward_compat_tuning_to_midi(self):
        from parse_txt import tuning_to_midi
        midi = tuning_to_midi("EADGBE")
        self.assertEqual(midi[0], 64)

    def test_backward_compat_note_midi(self):
        from parse_txt import note_midi, tuning_to_midi
        midi = tuning_to_midi("EADGBE")
        self.assertEqual(note_midi(1, 0, midi), 64)


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

def main():
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for cls in [
        # topmatter_parser
        TestFindTuning,
        TestFindComposerAuthorTitle,
        TestFindTranscriber,
        TestFindChordsFingeringEmpty,
        TestParseTopmatter,
        # tab_parser
        TestTuningHelpers,
        TestContentStart,
        TestBarPositions,
        TestMeasureCells,
        TestExtractNotes,
        TestParseBarres,
        TestAssignLhFingering,
        TestAssignRhFingering,
        TestDetectRepeatVolta,
        TestFindSystems,
        TestParseTab,
        # bottom_parser
        TestFindNotesLegend,
        TestFindDynamics,
        TestFindBiographical,
        TestParseBottom,
        # Beat structure — unit tests
        TestGetBeats,
        # Beat structure — El Negrito specific (inherits invariants too)
        TestBeatStructureElNegrito,
        # Beat structure — general invariants across multiple pieces
        TestBeatInvariants_VillaLobos,
        TestBeatInvariants_Cardoso,
        TestBeatInvariants_Barrios,
        TestBeatInvariants_Bach,
        TestBeatInvariants_Albeniz,
        # Slide-destination annotation
        TestSlideDestAnnotation,
        # Bar-indexing helpers
        TestBarCountInfo,
        # Chord-level annotation correctness
        TestNoDuplicateStringsInChord,
        TestXmlBarCountMatchesTab,
        TestChoros01SlideAnnotation,
        # Integration
        TestIntegration,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
