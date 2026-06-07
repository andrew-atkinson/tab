"""
score_builder.py
================
Build an annotated MusicXML document from an ExpandedScore (tab as ground
truth) and a TimingMap (MIDI as timing oracle).

The tab is authoritative for everything musical:
  notes, strings, frets, techniques, fingering, barres, repeats, dynamics.

The MIDI contributes one thing only: how long each beat lasts.

Beat-group alignment
--------------------
For each paired (expanded_measure, midi_measure):
  tab_beats  = get_beats(expanded_measure.notes)   # sorted by column
  midi_beats = midi_measure.beat_groups             # sorted by onset tick

The two lists are zipped by sequential position.  No pitch matching is done.

  Extra MIDI beat groups  → skipped (slide destinations, ornaments)
  Extra tab beat groups   → duration estimated from remaining measure time
                            divided equally among unmatched groups; logged

Measure alignment
-----------------
expanded.measures[i] pairs with timing.measures[i].  When the counts differ
(Barrios/Choros style mismatch) the shorter list determines how many pairs
are formed; surplus measures from either side are logged as issues.

Public API
----------
    build_musicxml(expanded, timing, stem='') -> ET.Element
"""

from __future__ import annotations
import xml.etree.ElementTree as ET
import re
from typing import Optional

from models import (
    ExpandedScore, ExpandedMeasure,
    TimingMap, MeasureTiming, BeatGroupTiming,
    NoteEvent,
)
from tab_parser import get_beats, tuning_to_midi, tuning_open_notes
from midi_timing import ticks_to_duration
from issues_log import log_issue


# ---------------------------------------------------------------------------
# Pitch helpers
# ---------------------------------------------------------------------------

_STEP_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
_SEMI_TO_STEP = [
    ('C', 0), ('C', 1), ('D', 0), ('D', 1), ('E', 0),
    ('F', 0), ('F', 1), ('G', 0), ('G', 1), ('A', 0),
    ('A', 1), ('B', 0),
]   # (step_name, alter) indexed by semitone 0-11


def _midi_to_pitch_el(midi: int) -> ET.Element:
    """Build a <pitch> element from a MIDI note number."""
    semitone = midi % 12
    octave   = midi // 12 - 1
    step, alter = _SEMI_TO_STEP[semitone]
    pitch = ET.Element('pitch')
    ET.SubElement(pitch, 'step').text = step
    if alter:
        ET.SubElement(pitch, 'alter').text = str(alter)
    ET.SubElement(pitch, 'octave').text = str(octave)
    return pitch


def _int_to_roman(n: int) -> str:
    vals = [(10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
    r = ''
    for v, s in vals:
        while n >= v:
            r += s; n -= v
    return r


# ---------------------------------------------------------------------------
# Technical annotation
# ---------------------------------------------------------------------------

def _add_technical(
    note_el : ET.Element,
    ev      : NoteEvent,
) -> None:
    """
    Append <notations><technical> children derived from *ev*.

    Handles: string, fret, left-hand fingering, right-hand pluck (pima),
    slide start/stop, hammer-on, pull-off, bend, vibrato, harmonic.
    """
    notations = ET.SubElement(note_el, 'notations')
    technical = ET.SubElement(notations, 'technical')
    ET.SubElement(technical, 'string').text = str(ev.string)
    ET.SubElement(technical, 'fret').text   = str(ev.fret)

    if ev.finger is not None:
        fi = ET.SubElement(technical, 'fingering')
        fi.text = str(ev.finger)
        fi.set('placement', 'below')

    if ev.rh_finger:
        pl = ET.SubElement(technical, 'pluck')
        pl.text = ev.rh_finger.upper()

    if ev.harmonic:
        h = ET.SubElement(technical, 'harmonic')
        # touch_fret present → artificial harmonic (3[15] notation)
        # touch_fret absent  → natural harmonic (<7> or Harm. annotation)
        ET.SubElement(h, 'artificial' if ev.touch_fret is not None else 'natural')

    tech = ev.technique
    # <slide> is a direct child of <notations>, NOT inside <technical>
    if tech in ('slide_up', 'slide_down'):
        sl = ET.SubElement(notations, 'slide')
        sl.set('type', 'start')
        sl.set('number', '1')
    elif tech == 'slide_stop':
        sl = ET.SubElement(notations, 'slide')
        sl.set('type', 'stop')
        sl.set('number', '1')
    elif tech == 'hammer':
        h = ET.SubElement(technical, 'hammer-on')
        h.set('type', 'start'); h.text = 'H'
    elif tech == 'hammer_stop':
        h = ET.SubElement(technical, 'hammer-on')
        h.set('type', 'stop'); h.text = 'H'
    elif tech == 'pull':
        po = ET.SubElement(technical, 'pull-off')
        po.set('type', 'start'); po.text = 'P'
    elif tech == 'pull_stop':
        po = ET.SubElement(technical, 'pull-off')
        po.set('type', 'stop'); po.text = 'P'
    elif tech == 'bend':
        ET.SubElement(technical, 'other-technical').text = 'bend'
    elif tech == 'vibrato':
        ET.SubElement(technical, 'other-technical').text = 'vibrato'


# ---------------------------------------------------------------------------
# Beat-group → MusicXML note elements
# ---------------------------------------------------------------------------

def _beat_to_xml_notes(
    beat      : list[NoteEvent],
    dur_ticks : int,
    note_type : str,
    dots      : int,
    divisions : int,
    tuning    : list[int],
    voice     : int = 1,
    tech_overrides: Optional[dict[int, str]] = None,
) -> list[ET.Element]:
    """
    Convert one simultaneously-struck tab beat group into MusicXML <note>s.

    The first note is a regular note; subsequent ones carry <chord/> so they
    sound together.  All share the same duration derived from MIDI timing.

    tech_overrides: optional {string → technique} to override ev.technique for
    notes that have been identified as technique stop destinations (slide_stop,
    hammer_stop, pull_stop).
    """
    elements: list[ET.Element] = []
    for idx, ev in enumerate(beat):
        note_el = ET.Element('note')
        if idx > 0:
            ET.SubElement(note_el, 'chord')
        midi = tuning[ev.string - 1] + ev.fret
        note_el.append(_midi_to_pitch_el(midi))
        ET.SubElement(note_el, 'duration').text = str(dur_ticks)
        ET.SubElement(note_el, 'voice').text = str(voice)
        ET.SubElement(note_el, 'type').text = note_type
        for _ in range(dots):
            ET.SubElement(note_el, 'dot')
        # Apply technique override if provided (marks this note as a stop)
        if tech_overrides and ev.string in tech_overrides:
            import copy
            ev_copy = copy.copy(ev)
            ev_copy.technique = tech_overrides[ev.string]
            _add_technical(note_el, ev_copy)
        else:
            _add_technical(note_el, ev)
        if ev.tied:
            tie_el = ET.Element('tie')
            tie_el.set('type', 'start')
            note_el.append(tie_el)
        elements.append(note_el)
    return elements


def _make_dest_note(
    src_ev    : NoteEvent,
    dest_fret : int,
    stop_tech : str,
    dur_ticks : int,
    note_type : str,
    dots      : int,
    tuning    : list[int],
    is_chord  : bool = False,
) -> ET.Element:
    """
    Synthesize a technique-destination <note> (slide stop, pull-off stop, etc.)
    from a source NoteEvent.  The pitch is computed from dest_fret on the same
    string.  The technique is set to stop_tech so _add_technical emits the
    correct stop annotation.
    """
    import copy
    dest_ev = copy.copy(src_ev)
    dest_ev.fret      = dest_fret
    dest_ev.technique = stop_tech
    dest_ev.slide_to  = None
    dest_ev.tied      = False
    dest_ev.midi_pitch = tuning[src_ev.string - 1] + dest_fret

    note_el = ET.Element('note')
    if is_chord:
        ET.SubElement(note_el, 'chord')
    note_el.append(_midi_to_pitch_el(dest_ev.midi_pitch))
    ET.SubElement(note_el, 'duration').text = str(dur_ticks)
    ET.SubElement(note_el, 'voice').text = '1'
    ET.SubElement(note_el, 'type').text = note_type
    for _ in range(dots):
        ET.SubElement(note_el, 'dot')
    _add_technical(note_el, dest_ev)
    return note_el


# ---------------------------------------------------------------------------
# Single-measure builder
# ---------------------------------------------------------------------------

def _build_measure(
    meas_num     : int,
    em           : ExpandedMeasure,
    mt           : MeasureTiming,
    tuning       : list[int],
    stem         : str,
    title        : str,
    composer     : str,
    first_meas   : bool = False,
    prev_time_sig: tuple[int, int] | None = None,
    meta_time_sig: tuple[int, int] | None = None,
) -> ET.Element:
    """Build one <measure> element from an ExpandedMeasure + MeasureTiming.

    prev_time_sig : (num, denom) from the preceding measure, or None on the first.
    meta_time_sig : (num, denom) from the tab header, used to override the MIDI
                    time signature on the first measure (MIDI often defaults to
                    4/4 even when the piece is in 2/4, 3/4, etc.).
    """
    # Determine effective time signature for this measure.
    # On the first measure: prefer the tab header's explicit time sig over the
    # MIDI's (which may default to 4/4 regardless of the actual metre).
    if first_meas and meta_time_sig is not None:
        eff_ts = meta_time_sig
    else:
        eff_ts = (mt.time_sig_num, mt.time_sig_denom)

    ts_changed = (prev_time_sig is None) or (eff_ts != prev_time_sig)

    meas_el = ET.Element('measure')
    meas_el.set('number', str(meas_num))

    # ── Repeat barlines ──────────────────────────────────────────────────────
    if em.repeat_start and em.pass_number == 1:
        bl = ET.Element('barline'); bl.set('location', 'left')
        ET.SubElement(bl, 'bar-style').text = 'heavy-light'
        ET.SubElement(bl, 'repeat').set('direction', 'forward')
        meas_el.append(bl)

    # ── Attributes (first measure, or whenever time signature changes) ───────
    if first_meas or ts_changed:
        attrs = ET.SubElement(meas_el, 'attributes')
        if first_meas:
            ET.SubElement(attrs, 'divisions').text = str(mt.divisions)
            key_el = ET.SubElement(attrs, 'key')
            ET.SubElement(key_el, 'fifths').text = '0'   # updated from metadata
        time_el = ET.SubElement(attrs, 'time')
        ET.SubElement(time_el, 'beats').text = str(eff_ts[0])
        ET.SubElement(time_el, 'beat-type').text = str(eff_ts[1])
        if first_meas:
            clef_el = ET.SubElement(attrs, 'clef')
            ET.SubElement(clef_el, 'sign').text = 'G'
            ET.SubElement(clef_el, 'line').text = '2'
            ET.SubElement(clef_el, 'clef-octave-change').text = '-1'

    # ── Volta direction ──────────────────────────────────────────────────────
    if em.volta is not None:
        d = ET.Element('direction'); d.set('placement', 'above')
        dt = ET.SubElement(d, 'direction-type')
        ET.SubElement(dt, 'words').text = f'{em.volta}.'
        meas_el.append(d)

    # ── Beat groups ──────────────────────────────────────────────────────────
    tab_beats  = get_beats(em.notes)
    midi_beats = mt.beat_groups

    n_tab  = len(tab_beats)
    n_midi = len(midi_beats)

    if n_tab == 0:
        # Rest measure
        rest_el = ET.Element('note')
        ET.SubElement(rest_el, 'rest').set('measure', 'yes')
        ET.SubElement(rest_el, 'duration').text = str(mt.total_ticks)
        ET.SubElement(rest_el, 'voice').text = '1'
        ET.SubElement(rest_el, 'type').text = 'whole'
        meas_el.append(rest_el)
    else:
        # ── Pair tab beats to MIDI beat groups ───────────────────────────────
        # Walk both lists with explicit indices so that slide notes can consume
        # two consecutive MIDI beats (source + arrival) as a single duration.
        #
        # A slide `4/7` in the tab is one beat, but the MIDI records two
        # note-on events: one at the source pitch (fret 4) and one at the
        # destination pitch (fret 7).  Without correction the source note gets
        # the short "transit" duration and the next tab beat gets the longer
        # "arrival" duration — shifting every subsequent note by one beat.
        #
        # Fix: when a tab beat contains a slide and the immediately following
        # MIDI beat's pitches include the slide destination, merge both MIDI
        # durations into the slide beat and advance the MIDI index by 2.

        durations: list[int] = []
        midi_idx = 0
        estimation_count = 0

        for tb in tab_beats:
            if midi_idx >= n_midi:
                # No more MIDI beats: estimate from remaining measure ticks
                used = sum(durations)
                remaining = max(1, mt.total_ticks - used)
                left = n_tab - len(durations)
                durations.append(max(1, remaining // max(1, left)))
                estimation_count += 1
                continue

            dur = midi_beats[midi_idx].duration_ticks

            # Slide detection: does this tab beat have a slide with a known
            # destination, and does the next MIDI beat contain that pitch?
            slide_ev = next(
                (ev for ev in tb
                 if ev.technique in ('slide_up', 'slide_down')
                 and ev.slide_to is not None),
                None,
            )
            if slide_ev is not None and midi_idx + 1 < n_midi:
                dest_pitch = tuning[slide_ev.string - 1] + slide_ev.slide_to
                next_pitches = midi_beats[midi_idx + 1].midi_pitches
                if any(abs(p - dest_pitch) <= 1 for p in next_pitches):
                    # Merge: slide transit + slide arrival = full slide duration
                    dur += midi_beats[midi_idx + 1].duration_ticks
                    midi_idx += 1   # consume the destination beat

            durations.append(dur)
            midi_idx += 1

        if estimation_count:
            log_issue(
                stem=stem, title=title, composer=composer,
                bar_number=em.source_num,
                issue_type='timing_estimation',
                details=(
                    f'Tab has {n_tab} beat groups but MIDI has {n_midi} in '
                    f'source bar {em.source_num}; {estimation_count} beat(s) '
                    f'estimated from remaining measure time.'
                ),
            )

        # ── Pre-pass: identify technique stop destinations ────────────────────
        # Maps (beat_idx, string) → stop_technique for notes in the NEXT beat
        # that are explicit slide destinations already present in the tab.
        # Also collects (beat_idx, string) pairs that have implicit destinations
        # (pull-offs, hammer-ons, and slides with no matching next-beat note).
        _STOP_MAP = {
            'slide_up': 'slide_stop', 'slide_down': 'slide_stop',
            'hammer': 'hammer_stop', 'pull': 'pull_stop',
        }
        explicit_stops: dict[tuple[int, int], str] = {}  # (beat_idx, string) → stop_tech
        has_explicit: set[tuple[int, int]] = set()       # (src_beat_idx, string)

        for bi, tb in enumerate(tab_beats):
            for ev in tb:
                if ev.technique not in _STOP_MAP or ev.slide_to is None:
                    continue
                stop = _STOP_MAP[ev.technique]
                # Slides: look for explicit destination in the immediately next beat
                if ev.technique in ('slide_up', 'slide_down') and bi + 1 < len(tab_beats):
                    for nev in tab_beats[bi + 1]:
                        if nev.string == ev.string and nev.fret == ev.slide_to:
                            explicit_stops[(bi + 1, ev.string)] = stop
                            has_explicit.add((bi, ev.string))
                            break
                # pull / hammer: destination was consumed by parser; always implicit

        # ── Emit notes ───────────────────────────────────────────────────────
        for bi, (tb, dur) in enumerate(zip(tab_beats, durations)):
            _, note_type, dots = ticks_to_duration(dur, mt.divisions, mt.time_sig_denom)

            # Collect stop overrides for notes in THIS beat
            stop_overrides: dict[int, str] = {
                string: stop
                for (beat_i, string), stop in explicit_stops.items()
                if beat_i == bi
            }

            # Collect technique sources needing synthesized destinations
            synth: list[tuple[NoteEvent, int, str]] = []   # (src_ev, dest_fret, stop_tech)
            for ev in tb:
                if ev.technique not in _STOP_MAP or ev.slide_to is None:
                    continue
                if (bi, ev.string) in has_explicit:
                    continue  # explicit destination handled above
                synth.append((ev, ev.slide_to, _STOP_MAP[ev.technique]))

            if synth:
                # Split duration: source gets 2/3, destination gets 1/3
                src_dur = max(1, dur * 2 // 3)
                dst_dur = max(1, dur - src_dur)
                _, src_type, src_dots = ticks_to_duration(src_dur, mt.divisions, mt.time_sig_denom)
                _, dst_type, dst_dots = ticks_to_duration(dst_dur, mt.divisions, mt.time_sig_denom)

                # Emit source beat (with start annotations)
                for ne in _beat_to_xml_notes(tb, src_dur, src_type, src_dots, mt.divisions, tuning, tech_overrides=stop_overrides):
                    meas_el.append(ne)

                # Emit synthesized destination notes (not chord relative to each other
                # only if there are multiple synth sources; first is always non-chord)
                for idx, (src_ev, dest_fret, stop_tech) in enumerate(synth):
                    dn = _make_dest_note(
                        src_ev, dest_fret, stop_tech,
                        dst_dur, dst_type, dst_dots, tuning,
                        is_chord=(idx > 0),
                    )
                    meas_el.append(dn)
            else:
                # Normal beat (possibly with stop overrides for explicit destinations)
                for ne in _beat_to_xml_notes(tb, dur, note_type, dots, mt.divisions, tuning, tech_overrides=stop_overrides):
                    meas_el.append(ne)

    # ── Closing repeat barline ───────────────────────────────────────────────
    if em.repeat_end and em.pass_number <= 1:
        bl = ET.Element('barline'); bl.set('location', 'right')
        ET.SubElement(bl, 'bar-style').text = 'light-heavy'
        ET.SubElement(bl, 'repeat').set('direction', 'backward')
        meas_el.append(bl)

    return meas_el


# ---------------------------------------------------------------------------
# Staff tuning
# ---------------------------------------------------------------------------

def _build_staff_tuning(tuning_midi: list[int]) -> ET.Element:
    """<staff-details> element with per-string tuning for AlphaTab."""
    sd = ET.Element('staff-details')
    sd.set('print-object', 'yes')
    ET.SubElement(sd, 'staff-lines').text = '6'
    for line_num, midi in enumerate(reversed(tuning_midi), start=1):
        st = ET.SubElement(sd, 'staff-tuning')
        st.set('line', str(line_num))
        semitone = midi % 12
        octave   = midi // 12 - 1
        step, alter = _SEMI_TO_STEP[semitone]
        ET.SubElement(st, 'tuning-step').text = step
        if alter:
            ET.SubElement(st, 'tuning-alter').text = str(alter)
        ET.SubElement(st, 'tuning-octave').text = str(octave)
    return sd


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_musicxml(
    expanded : ExpandedScore,
    timing   : TimingMap,
    stem     : str = '',
) -> ET.Element:
    """
    Build a complete annotated MusicXML document from the expanded tab score
    and MIDI timing map.

    The tab is the source of truth for all musical content.
    The MIDI provides beat durations only.

    Parameters
    ----------
    expanded : ExpandedScore produced by repeat_expander.expand_repeats()
    timing   : TimingMap produced by midi_timing.extract_timing()
    stem     : filename stem for issue-log entries

    Returns
    -------
    ET.Element — the <score-partwise> root of a valid MusicXML document.
    """
    meta     = expanded.metadata
    title    = meta.title    if meta else ''
    subtitle = meta.subtitle if meta else ''
    composer = meta.composer if meta else ''
    tuning_s = meta.tuning   if meta else 'EADGBE'
    tuning   = tuning_to_midi(tuning_s)   # high→low MIDI pitches

    n_exp  = len(expanded.measures)
    n_midi = len(timing.measures)

    if n_exp != n_midi:
        log_issue(
            stem=stem, title=title, composer=composer,
            bar_number=None, issue_type='bar_count_mismatch',
            details=(
                f'Expanded score has {n_exp} measures but MIDI timing map has '
                f'{n_midi}.  Matching up to min({n_exp}, {n_midi}) measures; '
                f'{abs(n_exp - n_midi)} measure(s) will be unmatched.'
            ),
        )

    n_pairs = min(n_exp, n_midi)

    # ── Score skeleton ───────────────────────────────────────────────────────
    root = ET.Element('score-partwise')
    root.set('version', '3.1')

    # Title / subtitle structure:
    #   Subtitle present → <work><work-title> = collection,  <movement-title> = movement
    #   No subtitle      → <movement-title> = full title  (backwards-compatible)
    if subtitle:
        work = ET.SubElement(root, 'work')
        ET.SubElement(work, 'work-title').text = title
        ET.SubElement(root, 'movement-title').text = subtitle
    elif title:
        ET.SubElement(root, 'movement-title').text = title
    ident = ET.SubElement(root, 'identification')
    cr = ET.SubElement(ident, 'creator')
    cr.set('type', 'composer')
    cr.text = composer

    # Part list
    part_list = ET.SubElement(root, 'part-list')
    sp = ET.SubElement(part_list, 'score-part')
    sp.set('id', 'P1')
    ET.SubElement(sp, 'part-name').text = 'Guitar'

    # Part
    part = ET.SubElement(root, 'part')
    part.set('id', 'P1')

    # Parse the tab's declared time signature (e.g. "2/4") so it can override
    # the MIDI's default on the first measure.  MIDI files often default to 4/4
    # even when the piece is in 2/4 or 3/4.
    meta_time_sig: tuple[int, int] | None = None
    if meta and meta.time_sig:
        try:
            parts = meta.time_sig.strip().split('/')
            meta_time_sig = (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass

    prev_time_sig: tuple[int, int] | None = None

    for i in range(n_pairs):
        em = expanded.measures[i]
        mt = timing.measures[i]
        meas_el = _build_measure(
            meas_num      = i + 1,
            em            = em,
            mt            = mt,
            tuning        = tuning,
            stem          = stem,
            title         = title,
            composer      = composer,
            first_meas    = (i == 0),
            prev_time_sig = prev_time_sig,
            meta_time_sig = meta_time_sig if i == 0 else None,
        )
        # Track the effective time sig for this measure so the next measure
        # can detect changes.  Use the meta override for the first measure.
        if i == 0 and meta_time_sig is not None:
            prev_time_sig = meta_time_sig
        else:
            prev_time_sig = (mt.time_sig_num, mt.time_sig_denom)

        # On the first measure, append staff-details and tempo direction.
        if i == 0:
            attrs = meas_el.find('attributes')
            if attrs is not None:
                attrs.append(_build_staff_tuning(tuning))
            direction = ET.Element('direction')
            direction.set('placement', 'above')
            dt = ET.SubElement(direction, 'direction-type')
            mm = ET.SubElement(dt, 'metronome')
            mm.set('parentheses', 'no')
            ET.SubElement(mm, 'beat-unit').text = 'quarter'
            ET.SubElement(mm, 'per-minute').text = str(round(mt.tempo_bpm))
            meas_el.append(direction)

        part.append(meas_el)

    # ── Trailing unmatched tab measures (no timing) ──────────────────────────
    if n_exp > n_midi:
        # Append remaining expanded measures with fallback timing.
        fallback_mt = timing.measures[-1] if timing.measures else MeasureTiming(
            measure_idx=0, onset_ticks=0, total_ticks=timing.divisions * 2,
            tempo_bpm=120, divisions=timing.divisions,
            time_sig_num=4, time_sig_denom=4,
        )
        for i in range(n_midi, n_exp):
            em = expanded.measures[i]
            fallback_ts = (fallback_mt.time_sig_num, fallback_mt.time_sig_denom)
            meas_el = _build_measure(
                meas_num      = i + 1,
                em            = em,
                mt            = fallback_mt,
                tuning        = tuning,
                stem          = stem,
                title         = title,
                composer      = composer,
                prev_time_sig = prev_time_sig,
            )
            prev_time_sig = fallback_ts
            part.append(meas_el)

    _indent(root)
    return root


# ---------------------------------------------------------------------------
# XML formatting
# ---------------------------------------------------------------------------

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


def write_musicxml(root: ET.Element, out_path: str) -> str:
    """Write *root* to *out_path* with XML declaration.  Returns *out_path*."""
    import os
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    tree = ET.ElementTree(root)
    tree.write(out_path, encoding='utf-8', xml_declaration=True)
    return out_path
