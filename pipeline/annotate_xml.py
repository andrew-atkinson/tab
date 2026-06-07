"""
annotate_xml.py
===============
Merge parsed classtab data (TabFile) into a MusicXML file.

Annotations added:
  • Title / composer in <movement-title> and <identification>
  • Guitar tuning via <staff-details><staff-tuning>
  • Per-note <technical>: <string>, <fret>, <fingering> (left hand)
  • Barre markings as <direction><words>
  • Hammer-on / pull-off / slide via <technical> elements
  • Capo as a <direction><words> marker

NOTE ON MEASURE ALIGNMENT
--------------------------
Guitar MIDI files frequently embed 4/4 time signatures regardless of the actual
musical metre, so the measure structure produced by music21 rarely matches the
measure numbers in the ASCII tab.

We therefore use *global sequential matching*:
  1. Collect all pitched, non-rest notes from the XML in document order.
  2. Collect all tab NoteEvents in order: sorted by (measure_number, col).
  3. Match them 1-to-1 positionally, with pitch-validation fallback.
  4. Distribute barre annotations to the closest XML measure.
"""

from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Optional
from parse_txt import TabFile, tuning_to_midi, note_midi
from issues_log import log_issue


# ---------------------------------------------------------------------------
# Tuning → staff-tuning XML
# ---------------------------------------------------------------------------

_STEP_NAMES = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
_CHROMATIC  = [0,   2,   4,   5,   7,   9,  11]


def _midi_to_step_octave(midi: int) -> tuple[str, int, int]:
    semitone = midi % 12
    octave   = midi // 12 - 1
    best_step, best_alter, best_dist = 'C', 0, 99
    for i, s in enumerate(_STEP_NAMES):
        for alter in (0, 1, -1):
            note_semi = (_CHROMATIC[i] + alter) % 12
            dist = min(abs(note_semi - semitone), 12 - abs(note_semi - semitone))
            if dist < best_dist or (dist == best_dist and abs(alter) < abs(best_alter)):
                best_dist, best_step, best_alter = dist, s, alter
    return best_step, best_alter, octave


def _build_staff_details(tuning_midi: list[int]) -> ET.Element:
    """
    <staff-details> with <staff-tuning> for all 6 strings.

    tuning_midi is ordered high→low (index 0 = high e, index 5 = low E).
    MusicXML/AlphaTab convention: line 1 = bottom = low E, line 6 = top = high e.
    So we enumerate reversed(tuning_midi): line 1 → low E, line 6 → high e.
    """
    sd = ET.Element('staff-details')
    sd.set('print-object', 'yes')
    ET.SubElement(sd, 'staff-lines').text = '6'
    for line_num, midi in enumerate(reversed(tuning_midi), start=1):
        st = ET.SubElement(sd, 'staff-tuning')
        st.set('line', str(line_num))
        step, alter, octave = _midi_to_step_octave(midi)
        ET.SubElement(st, 'tuning-step').text = step
        if alter:
            ET.SubElement(st, 'tuning-alter').text = str(alter)
        ET.SubElement(st, 'tuning-octave').text = str(octave)
    return sd


# ---------------------------------------------------------------------------
# Pitch helpers
# ---------------------------------------------------------------------------

_STEP_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def _xml_note_midi(note_el: ET.Element) -> int:
    pitch = note_el.find('pitch')
    if pitch is None:
        return -1
    step   = pitch.findtext('step', '')
    alter  = float(pitch.findtext('alter', '0') or '0')
    octave = int(pitch.findtext('octave', '4') or '4')
    return 12 * (octave + 1) + _STEP_SEMI.get(step.upper(), 0) + int(alter)


# ---------------------------------------------------------------------------
# Global note extraction from the full XML score
# ---------------------------------------------------------------------------

def _all_xml_pitched_notes(part: ET.Element) -> list[tuple[int, ET.Element]]:
    """
    Return [(global_beat_offset, note_element), ...] for every pitched,
    non-rest note in the part, in document order.

    global_beat_offset is measured in <divisions> units accumulated across
    the entire part (rests and chords handled correctly).
    """
    result = []
    offset = 0          # running offset in divisions
    prev_dur = 0        # duration of the last non-chord note

    for measure_el in part.findall('measure'):
        for note_el in measure_el.findall('note'):
            is_chord = note_el.find('chord') is not None
            is_rest  = note_el.find('rest')  is not None
            dur_text = note_el.findtext('duration') or '0'
            dur      = int(dur_text)

            if is_chord:
                note_offset = offset - prev_dur
            else:
                note_offset = offset
                prev_dur    = dur
                offset      += dur

            if not is_rest and note_el.find('pitch') is not None:
                result.append((note_offset, note_el))

    return result


# ---------------------------------------------------------------------------
# Per-measure matching  (tab is canonical)
# ---------------------------------------------------------------------------

def _match_within_measure(
    xml_notes: list[tuple[int, ET.Element]],
    tab_notes: list[tuple],
) -> dict[int, tuple]:
    """
    Match *xml_notes* to *tab_notes* within a single measure using
    pitch proximity (±2 semitones) with a short lookahead.

    Tab-note tuples (index meanings):
      0 midi  1 string  2 fret  3 finger  4 tech  5 rh_finger  6 harmonic
      7 slide_dest_midi  8 slide_dest_fret  9 col (beat column)

    Chord deduplication and pitch-descending sort of each XML beat group
    must be applied by the caller (*_match_by_measure*) before this function
    is invoked.

    Skip-TAB beat-boundary rule: when searching for a closer tab note by
    skipping ahead (e.g. the MIDI chord has fewer notes than the tab chord),
    the algorithm must not jump past notes that belong to the *same* tab beat
    column.  Crossing a beat boundary would assign a beat-N MIDI note to a
    beat-N+1 tab slot, producing two notes on the same string within the same
    chord group.

    Slide handling: a slide (e.g. 3/7) is one tab NoteEvent but the MIDI
    typically records both the source pitch and the destination pitch as
    separate note-on events.  After matching a slide note, the algorithm
    looks at the immediately following XML note and consumes it silently if
    its pitch matches the slide destination (±2 semitones), annotating it
    with 'slide_stop' so the renderer draws the arrival endpoint.

    Returns {local_xml_index: (string, fret, finger, tech, rh_finger, harmonic)}.
    """
    LOOKAHEAD = 4
    result: dict[int, tuple] = {}
    xi = 0
    ti = 0

    def _consume_slide_dest(xi: int, tab_tup: tuple) -> int:
        """
        If *tab_tup* is a slide note and the XML note at *xi* matches the
        slide's destination pitch, annotate that XML note with the slide's
        destination fret (and a 'slide_stop' technique so the renderer draws
        the arrival endpoint) and return xi+1.  Otherwise return xi unchanged.
        """
        if tab_tup[4] not in ('slide_up', 'slide_down') or len(tab_tup) <= 8:
            return xi
        slide_dest_midi = tab_tup[7]
        slide_dest_fret = tab_tup[8]
        if slide_dest_midi is None or slide_dest_fret is None:
            return xi
        if xi >= len(xml_notes):
            return xi
        dest_xml_midi = _xml_note_midi(xml_notes[xi][1])
        if abs(dest_xml_midi - slide_dest_midi) <= 2:
            # Annotate with dest fret and 'slide_stop' so the renderer draws
            # the arrival side of the slide line.
            result[xi] = (tab_tup[1], slide_dest_fret, tab_tup[3],
                          'slide_stop', tab_tup[5], tab_tup[6])
            return xi + 1
        return xi

    while xi < len(xml_notes) and ti < len(tab_notes):
        _, xml_note = xml_notes[xi]
        tab_tup  = tab_notes[ti]
        tab_midi, string, fret, finger, tech, rh_finger, harmonic = tab_tup[:7]
        xml_midi = _xml_note_midi(xml_note)

        if abs(xml_midi - tab_midi) <= 2:
            result[xi] = (string, fret, finger, tech, rh_finger, harmonic)
            xi += 1
            ti += 1
            xi = _consume_slide_dest(xi, tab_tup)
            continue

        # Try skipping XML notes (extra MIDI notes not in the tab)
        matched = False
        for skip_x in range(1, LOOKAHEAD + 1):
            if xi + skip_x >= len(xml_notes):
                break
            _, cand = xml_notes[xi + skip_x]
            if abs(_xml_note_midi(cand) - tab_midi) <= 2:
                result[xi + skip_x] = (string, fret, finger, tech, rh_finger, harmonic)
                xi = xi + skip_x + 1
                ti += 1
                xi = _consume_slide_dest(xi, tab_tup)
                matched = True
                break

        if matched:
            continue

        # Try skipping tab notes (e.g. the tab chord has more notes than the
        # MIDI chord because some inner voices are absent from the MIDI).
        # Beat-boundary rule: never jump past the current tab beat column.
        # Crossing a beat boundary can assign a MIDI chord note to a later
        # beat's tab slot, producing two different tab positions on the same
        # string within what the renderer treats as one chord group.
        current_col = tab_tup[9] if len(tab_tup) > 9 else None
        for skip_t in range(1, LOOKAHEAD + 1):
            if ti + skip_t >= len(tab_notes):
                break
            alt = tab_notes[ti + skip_t]
            # Stop searching once we've crossed into the next beat.
            alt_col = alt[9] if len(alt) > 9 else None
            if current_col is not None and alt_col is not None and alt_col != current_col:
                break
            if abs(xml_midi - alt[0]) <= 2:
                result[xi] = (alt[1], alt[2], alt[3], alt[4], alt[5], alt[6])
                xi += 1
                ti = ti + skip_t + 1
                xi = _consume_slide_dest(xi, alt)
                matched = True
                break

        if not matched:
            xi += 1

    # ── Post-match deduplication ─────────────────────────────────────────────
    # Resolve same-string conflicts within each beat group.  When two matched
    # XML notes end up on the same string at the same beat offset — typically
    # because a multi-part MIDI has two inner-voice notes both close (±2 st)
    # to the same tab note — keep only the first (lower-xi) match since it was
    # assigned to a tab note with a tighter pitch error.  The later one falls
    # through to pitch-fallback, which places it on a different string.
    beat_string_first: dict[tuple[int, int], int] = {}  # (offset, string) → xi
    for xi_val in sorted(result):
        m = result[xi_val]
        string = m[0]
        off    = xml_notes[xi_val][0]
        key    = (off, string)
        if key in beat_string_first:
            del result[xi_val]   # duplicate: remove later match
        else:
            beat_string_first[key] = xi_val

    return result


def _match_by_measure(
    root: ET.Element,
    tab: TabFile,
    tuning_midi: list[int],
) -> dict[int, tuple]:
    """
    Match MIDI notes to tab notes **measure by measure**, using the tab as
    the canonical reference.

    Tab measure N is paired sequentially with MIDI measure N.  Within each
    measure, pitch-based matching (via _match_within_measure) assigns each
    XML note the tab's (string, fret, finger, technique, rh_finger, harmonic).
    MIDI notes that find no tab match within their measure receive
    pitch-fallback annotation later; tab notes that find no MIDI match are
    simply skipped (the nearest MIDI note in the measure keeps its pitch
    fallback).

    This prevents drift: a note-count imbalance in one bar cannot push the
    pointers out of sync for subsequent bars.

    Returns {id(note_el): (string, fret, finger, tech, rh_finger, harmonic)}.
    """
    part = root.find('.//part')
    if part is None:
        return {}

    xml_measures = part.findall('measure')
    tab_keys     = sorted(tab.measures.keys())
    result: dict[int, tuple] = {}   # id(note_el) → annotation tuple

    for meas_idx, tab_mnum in enumerate(tab_keys):
        if meas_idx >= len(xml_measures):
            break

        xml_meas = xml_measures[meas_idx]
        md       = tab.measures[tab_mnum]

        # Collect XML pitched notes from this measure with local beat offsets.
        # Within each chord group (same beat offset), sort by pitch descending
        # so the order matches the tab's natural string-1-first ordering
        # (string 1 = highest pitch in standard tuning).  This prevents the
        # skip-heavy lookahead from misassigning strings within chords.
        raw_xml: list[tuple[int, ET.Element]] = []
        offset   = 0
        prev_dur = 0
        for note_el in xml_meas.findall('note'):
            is_chord = note_el.find('chord') is not None
            is_rest  = note_el.find('rest')  is not None
            dur      = int(note_el.findtext('duration', '0'))
            if is_chord:
                note_off = offset - prev_dur
            else:
                note_off = offset
                prev_dur = dur
                offset  += dur
            if not is_rest and note_el.find('pitch') is not None:
                raw_xml.append((note_off, note_el))

        # Sort each chord group (same offset) by pitch descending so the order
        # matches the tab's natural string-1-first (= high-pitch-first) ordering.
        # Also deduplicate by pitch within the group: MIDI files sometimes have
        # two parts both notating the same pitch at the same beat (e.g. treble
        # and bass lines doubling), which would otherwise produce two XML notes
        # that both match the same tab entry and land on the same string.
        xml_notes: list[tuple[int, ET.Element]] = []
        i = 0
        while i < len(raw_xml):
            j = i + 1
            while j < len(raw_xml) and raw_xml[j][0] == raw_xml[i][0]:
                j += 1
            group = raw_xml[i:j]
            group.sort(key=lambda x: _xml_note_midi(x[1]), reverse=True)
            # Deduplicate by MIDI pitch within the group (keep first occurrence).
            seen_pitches: set[int] = set()
            for item in group:
                p = _xml_note_midi(item[1])
                if p not in seen_pitches:
                    seen_pitches.add(p)
                    xml_notes.append(item)
            i = j

        # Collect tab notes for this measure sorted by (col, string)
        tab_notes: list[tuple] = []
        for ev in sorted(md.notes, key=lambda n: (n.col, n.string)):
            midi = note_midi(ev.string, ev.fret, tuning_midi)
            # For slide notes, compute (dest_midi, dest_fret) so the matcher
            # can annotate the MIDI slide-destination note-on with the correct
            # string/fret rather than letting it fall through to pitch-fallback.
            slide_dest_midi = (
                note_midi(ev.string, ev.slide_to, tuning_midi)
                if ev.slide_to is not None else None
            )
            slide_dest_fret = ev.slide_to  # None if not a slide
            tab_notes.append((midi, ev.string, ev.fret, ev.finger,
                              ev.technique, ev.rh_finger, ev.harmonic,
                              slide_dest_midi, slide_dest_fret,
                              ev.col))         # index 9: beat column

        if not xml_notes or not tab_notes:
            continue

        local_matches = _match_within_measure(xml_notes, tab_notes)
        for local_xi, match_val in local_matches.items():
            result[id(xml_notes[local_xi][1])] = match_val

    return result


# ---------------------------------------------------------------------------
# Pitch-only fallback: assign string/fret from written MIDI pitch alone
# ---------------------------------------------------------------------------

# Sounding pitch of each open string (no transposition — matches MIDI pitches in XML)
_OPEN_STRING_MIDI = [64, 59, 55, 50, 45, 40]   # strings 1-6: e4 B3 G3 D3 A2 E2


def _pitch_to_string_fret(midi: int) -> Optional[tuple[int, int]]:
    """
    Return (string, fret) for *midi* written pitch using the lowest possible
    fret across all 6 strings. Returns None if out of guitar range.
    """
    candidates = []
    for str_num, open_midi in enumerate(_OPEN_STRING_MIDI, start=1):
        fret = midi - open_midi
        if 0 <= fret <= 24:
            candidates.append((fret, str_num))
    if not candidates:
        return None
    # Prefer lowest fret; break ties by choosing the lower-pitched string
    # (higher string number) so bass notes land on bass strings naturally
    candidates.sort(key=lambda x: (x[0], -x[1]))
    fret, str_num = candidates[0]
    return str_num, fret


# ---------------------------------------------------------------------------
# Technical annotation
# ---------------------------------------------------------------------------

def _add_technical(xml_note: ET.Element, string: int, fret: int,
                   finger: Optional[int], technique: Optional[str],
                   rh_finger: Optional[str] = None,
                   harmonic: bool = False) -> None:
    notations = xml_note.find('notations')
    if notations is None:
        notations = ET.SubElement(xml_note, 'notations')
    technical = notations.find('technical')
    if technical is None:
        technical = ET.SubElement(notations, 'technical')

    # MusicXML string 1 = highest string = high e = top of TAB.
    # Internal string numbering matches: 1=high e … 6=low E. Write directly.
    ET.SubElement(technical, 'string').text = str(string)
    ET.SubElement(technical, 'fret').text   = str(fret)

    # Left-hand fingering
    if finger is not None:
        fi = ET.SubElement(technical, 'fingering')
        fi.text = str(finger)
        fi.set('placement', 'below')

    # Right-hand (pima) fingering
    if rh_finger:
        pl = ET.SubElement(technical, 'pluck')
        pl.text = rh_finger.upper()

    # Natural harmonic
    if harmonic:
        harm = ET.SubElement(technical, 'harmonic')
        ET.SubElement(harm, 'natural')

    # Articulation / technique
    if technique == 'hammer':
        h = ET.SubElement(technical, 'hammer-on')
        h.set('type', 'start'); h.text = 'H'
    elif technique == 'pull':
        po = ET.SubElement(technical, 'pull-off')
        po.set('type', 'start'); po.text = 'P'
    elif technique in ('slide_up', 'slide_down'):
        sl = ET.SubElement(technical, 'slide')
        sl.set('type', 'start')
        sl.set('line-type', 'solid')
    elif technique == 'slide_stop':
        sl = ET.SubElement(technical, 'slide')
        sl.set('type', 'stop')
        sl.set('line-type', 'solid')
    elif technique == 'bend':
        ET.SubElement(technical, 'other-technical').text = 'bend'
    elif technique == 'vibrato':
        ot = ET.SubElement(technical, 'other-technical')
        ot.text = 'vibrato'


# ---------------------------------------------------------------------------
# Barre direction elements
# ---------------------------------------------------------------------------

def _int_to_roman(n: int) -> str:
    vals = [(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]
    r = ''
    for v, s in vals:
        while n >= v:
            r += s; n -= v
    return r


def _add_barre_to_first_measure(part: ET.Element, fret: int, partial: bool) -> None:
    """Add a barre direction word to the first measure of the part."""
    first = part.find('measure')
    if first is None:
        return
    direction = ET.Element('direction')
    direction.set('placement', 'above')
    dt = ET.SubElement(direction, 'direction-type')
    words = ET.SubElement(dt, 'words')
    words.text = ('c' if partial else 'C') + _int_to_roman(fret)
    words.set('font-style', 'italic')
    first.insert(0, direction)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def annotate(xml_path: str, tab: TabFile, out_path: str,
             stem: str = '') -> str:
    """
    Load *xml_path*, annotate with *tab* data, write to *out_path*.

    Parameters
    ----------
    xml_path : path to the raw (un-annotated) MusicXML file
    tab      : parsed TabFile (ground truth)
    out_path : destination path for the annotated MusicXML
    stem     : filename stem of the source .txt (used in issue log entries)

    Returns *out_path*.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    tuning_midi = tuning_to_midi(tab.metadata.tuning)

    # ── Metadata ────────────────────────────────────────────────────────────
    mv = root.find('movement-title')
    if mv is None:
        mv = ET.SubElement(root, 'movement-title')
    if tab.metadata.title:
        mv.text = tab.metadata.title

    ident = root.find('identification')
    if ident is None:
        ident = ET.SubElement(root, 'identification')
    for cr in ident.findall('creator'):
        if cr.get('type') == 'composer':
            ident.remove(cr)
    cr = ET.SubElement(ident, 'creator')
    cr.set('type', 'composer')
    cr.text = tab.metadata.composer
    if tab.metadata.composer_dates:
        cr.text += f' ({tab.metadata.composer_dates})'

    # ── Staff details (tuning) ───────────────────────────────────────────────
    part = root.find('.//part')
    if part is not None:
        first_measure = part.find('measure')
        if first_measure is not None:
            attrs = first_measure.find('attributes')
            if attrs is None:
                attrs = ET.SubElement(first_measure, 'attributes')
            for sd in attrs.findall('staff-details'):
                attrs.remove(sd)
            attrs.append(_build_staff_details(tuning_midi))

            if tab.metadata.capo:
                d = ET.Element('direction')
                d.set('placement', 'above')
                dt = ET.SubElement(d, 'direction-type')
                ET.SubElement(dt, 'words').text = f'Capo {tab.metadata.capo}'
                first_measure.insert(0, d)

    # ── Note matching: tab is canonical, matched measure-by-measure ────────────
    # _merge_parts has already collapsed all MIDI parts into one.
    # _match_by_measure pairs tab measure N with MIDI measure N and matches
    # notes locally so that note-count imbalances in one bar cannot drift
    # into subsequent bars.
    _merge_parts(root)

    matches = _match_by_measure(root, tab, tuning_midi)

    for note_el in root.findall('.//note'):
        if note_el.find('pitch') is None or note_el.find('rest') is not None:
            continue
        note_id = id(note_el)
        if note_id in matches:
            string, fret, finger, tech, rh_finger, harmonic = matches[note_id]
            _add_technical(note_el, string, fret, finger, tech,
                           rh_finger=rh_finger, harmonic=harmonic)
        else:
            midi = _xml_note_midi(note_el)
            pos  = _pitch_to_string_fret(midi)
            if pos:
                _add_technical(note_el, pos[0], pos[1], None, None)

    # Collapse all voices to voice 1 (cleans up MIDI polyphony artefacts).
    for note_el in root.findall('.//note'):
        voice_el = note_el.find('voice')
        if voice_el is not None:
            voice_el.text = '1'
        else:
            ET.SubElement(note_el, 'voice').text = '1'

    # Add repeat barlines and barre direction text
    _add_repeat_barlines(root, tab)

    # ── Bar-count consistency check ──────────────────────────────────────────
    # The tab (.txt) is ground truth.  The MIDI should contain exactly as many
    # non-empty measures.  A mismatch signals a transcription problem (e.g. the
    # MIDI was recorded with repeats expanded while the tab is written once).
    # We do NOT truncate — we log the issue and leave the MIDI untouched so the
    # rendered score faithfully reflects both sources.  Any extra MIDI measures
    # beyond the tab will receive pitch-fallback-only annotation (no tab data).
    part = root.find('.//part')
    if part is not None:
        tab_count   = len(sorted(tab.measures.keys()))
        xml_all     = part.findall('measure')
        xml_nonempty = sum(
            1 for m in xml_all
            if any(n.find('pitch') is not None and n.find('rest') is None
                   for n in m.findall('note'))
        )
        if xml_nonempty != tab_count:
            log_issue(
                stem       = stem,
                title      = tab.metadata.title,
                composer   = tab.metadata.composer,
                bar_number = None,
                issue_type = 'bar_count_mismatch',
                details    = (
                    f'MIDI has {xml_nonempty} non-empty measures but tab has '
                    f'{tab_count}.  Difference: {xml_nonempty - tab_count:+d}.  '
                    f'Likely cause: MIDI recorded with repeats expanded or '
                    f'missing sections.'
                ),
            )

    # ── Duplicate-string detection ───────────────────────────────────────────
    # After annotation, scan every beat group for notes that share the same
    # string.  A guitar cannot play two notes on one string simultaneously, so
    # any duplicate indicates an annotation error (usually a pitch-proximity
    # false match).  Log each occurrence so the transcription can be reviewed.
    part = root.find('.//part')
    if part is not None:
        tab_keys = sorted(tab.measures.keys())
        for midx, meas in enumerate(part.findall('measure')):
            tab_mnum = tab_keys[midx] if midx < len(tab_keys) else None
            offset = 0; prev_dur = 0; beat_strings: dict[int, list[int]] = {}
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
                    log_issue(
                        stem       = stem,
                        title      = tab.metadata.title,
                        composer   = tab.metadata.composer,
                        bar_number = tab_mnum,
                        issue_type = 'duplicate_string_in_beat',
                        details    = (
                            f'Beat at offset {off} in XML measure '
                            f'{meas.get("number")} (tab bar {tab_mnum}): '
                            f'strings assigned = {strings}; duplicates = {dups}.'
                        ),
                    )

    # ── Write ────────────────────────────────────────────────────────────────
    import os
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    _indent(root)
    tree.write(out_path, encoding='utf-8', xml_declaration=True)
    return out_path


def _add_repeat_barlines(root: ET.Element, tab: TabFile) -> None:
    """
    Insert <barline> elements for repeat signs and barre text directions.

    Tab measure 0 = pickup; XML measure numbers start at 1.
    We map by sequential position: xml_measure[i] ↔ tab_measure[sorted_tab_keys[i]].
    """
    part = root.find('.//part')
    if part is None:
        return

    xml_measures = part.findall('measure')
    tab_keys     = sorted(tab.measures.keys())

    for xml_idx, xml_meas in enumerate(xml_measures):
        if xml_idx >= len(tab_keys):
            break
        md = tab.measures[tab_keys[xml_idx]]

        # ── Repeat barlines ─────────────────────────────────────────────────
        if md.repeat_start:
            bl = ET.Element('barline')
            bl.set('location', 'left')
            ET.SubElement(bl, 'bar-style').text = 'heavy-light'
            ET.SubElement(bl, 'repeat').set('direction', 'forward')
            xml_meas.insert(0, bl)

        if md.repeat_end:
            bl = ET.Element('barline')
            bl.set('location', 'right')
            ET.SubElement(bl, 'bar-style').text = 'light-heavy'
            rep = ET.SubElement(bl, 'repeat')
            rep.set('direction', 'backward')
            xml_meas.append(bl)

        # Volta bracket — rendered as a direction word above the measure
        if md.volta is not None:
            d = ET.Element('direction')
            d.set('placement', 'above')
            dt = ET.SubElement(d, 'direction-type')
            ET.SubElement(dt, 'words').text = f'{md.volta}.'
            xml_meas.insert(0, d)

        # ── Barre text directions ────────────────────────────────────────────
        for barre in md.barres:
            d = ET.Element('direction')
            d.set('placement', 'above')
            dt = ET.SubElement(d, 'direction-type')
            w  = ET.SubElement(dt, 'words')
            prefix = 'c' if barre.partial else 'C'
            w.text = f'{prefix}{_int_to_roman(barre.fret)}'
            w.set('font-style', 'italic')
            xml_meas.insert(0, d)


def _merge_parts(root: ET.Element) -> None:
    """
    Merge extra <part> elements into the first part.

    Previous approach — "snap to nearest Part-0 note within half a beat" —
    incorrectly turned sequential inner-voice notes into chords whenever the
    MIDI divisions happened to make the snap distance exactly equal to the
    tolerance (common with high-resolution MIDIs like divs=10080).

    New approach
    ------------
    For each measure, collect ALL pitched notes from every part with their
    true beat offsets.  Sort them by offset (Part-0 notes first at ties so
    they stay as the "base" chord note).  Rebuild the Part-0 measure with
    this unified sorted list:

    • Notes at the same offset → chord  (first one non-chord, rest marked
      <chord/>).
    • Notes at different offsets → sequential.  Each note's duration is
      *truncated* to the gap until the next onset so that the running offset
      advances exactly to the next note's start, producing a gapless,
      correctly-timed single-voice sequence with no <backup> elements.
    """
    parts = root.findall('part')
    if len(parts) <= 1:
        return

    part_list  = root.find('part-list')
    first_part = parts[0]

    p1_measures: dict[str, ET.Element] = {
        m.get('number', ''): m for m in first_part.findall('measure')
    }

    def _collect_pitched(
        meas_el: ET.Element,
    ) -> list[tuple[int, int, ET.Element]]:
        """Return [(beat_offset, duration, note_el)] for all pitched notes."""
        result: list[tuple[int, int, ET.Element]] = []
        offset   = 0
        prev_dur = 0
        for note_el in meas_el.findall('note'):
            is_chord = note_el.find('chord') is not None
            is_rest  = note_el.find('rest')  is not None
            dur = int(note_el.findtext('duration') or '0')
            if is_chord:
                note_offset = offset - prev_dur
            else:
                note_offset = offset
                prev_dur    = dur
                offset      += dur
            if not is_rest and note_el.find('pitch') is not None:
                result.append((note_offset, dur, note_el))
        return result

    for extra_part in parts[1:]:
        extra_id = extra_part.get('id', '')

        for extra_meas in extra_part.findall('measure'):
            mnum    = extra_meas.get('number', '')
            p1_meas = p1_measures.get(mnum)
            if p1_meas is None:
                continue

            p0_notes = _collect_pitched(p1_meas)
            px_notes = _collect_pitched(extra_meas)

            if not px_notes:
                continue  # nothing from this extra part in this measure

            # Combine: tag each entry with its source part index so that at
            # equal offsets Part-0 notes sort before extra-part notes.
            all_notes: list[tuple[int, int, ET.Element, int]] = (
                [(off, dur, n, 0) for off, dur, n in p0_notes] +
                [(off, dur, n, 1) for off, dur, n in px_notes]
            )
            all_notes.sort(key=lambda x: (x[0], x[3]))

            # All distinct onset times — used to compute truncated durations.
            onsets = sorted({off for off, _, _, _ in all_notes})

            def _trunc(off: int, dur: int) -> int:
                """Shorten dur so the note ends exactly at the next onset."""
                for o in onsets:
                    if o > off:
                        return min(dur, o - off)
                return dur  # last onset: keep original duration

            # ── Rebuild Part-0 measure ─────────────────────────────────────
            # Pull out the right barline so we can re-append it last.
            right_bl = None
            for ch in list(p1_meas):
                if ch.tag == 'barline' and ch.get('location') == 'right':
                    right_bl = ch
                    p1_meas.remove(ch)

            # Remove all existing notes (pitched + rests).
            for note in list(p1_meas.findall('note')):
                p1_meas.remove(note)

            # Re-insert notes in onset order with corrected chord markers
            # and truncated durations.
            prev_off = -1
            for off, dur, note, _ in all_notes:
                old_chord = note.find('chord')
                if off == prev_off:          # same beat as previous → chord
                    if old_chord is None:
                        note.insert(0, ET.Element('chord'))
                else:                        # new beat → remove any old chord tag
                    if old_chord is not None:
                        note.remove(old_chord)
                    prev_off = off

                # Truncate duration to close the gap to the next onset.
                new_dur = _trunc(off, dur)
                dur_el  = note.find('duration')
                if dur_el is not None:
                    dur_el.text = str(new_dur)

                p1_meas.append(note)

            if right_bl is not None:
                p1_meas.append(right_bl)

        # Remove the extra part from the score.
        root.remove(extra_part)
        if part_list is not None:
            for sp in part_list.findall('score-part'):
                if sp.get('id') == extra_id:
                    part_list.remove(sp)
                    break


def _indent(elem: ET.Element, level: int = 0) -> None:
    indent = '\n' + '  ' * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + '  '
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent
