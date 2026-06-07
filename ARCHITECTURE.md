# Parser Architecture — Tab-Primary Design

## Problem with the current approach

The current pipeline converts the MIDI to MusicXML and then tries to reconcile it
with the tab by matching notes pitch-by-pitch (±2 semitones, with lookahead).
This causes:

- **Bar-count mismatches** — the MIDI plays repeated sections through; the tab
  writes them once with repeat signs.  The pipeline had no concept of repeats.
- **Chord ordering errors** — MIDI encodes chords low→high; the tab orders them
  by string (high→low).  Pitch matching produced duplicate string assignments.
- **Slide artifacts** — the MIDI emits two note-on events for a slide (source +
  destination); the tab has one `NoteEvent` with `slide_to`.  The extra MIDI note
  fell through to pitch-fallback.
- **Cross-beat drift** — the lookahead allowed MIDI notes from beat N to match
  tab notes from beat N+1, corrupting voicing.

The root cause is architectural: treating the MIDI as the score and the tab as an
annotation instead of the other way around.

---

## New design principle

> **The `.txt` tab file is the complete musical score.**
> The `.mid` file is a timing oracle — it provides only beat durations.

| Source | Provides |
|--------|----------|
| `.txt` tab | Notes, strings, frets, rhythm (beat order), techniques (slide, hammer, pull, bend, vibrato, harmonic), left-hand fingering, right-hand (pima) fingering, barres, repeats, voltas, dynamics, time signature, key, tempo hint, tuning, title, composer |
| `.mid` MIDI | Absolute duration of each beat group within each measure, tempo map |

The MIDI is *never* used to determine which notes are played, on which strings,
or in what order.  It is used solely to answer: "how long does beat group i last?"

---

## Module structure

```
pipeline/
├── parse_txt.py          (existing — entry point)
├── topmatter_parser.py   (existing — header parsing)
├── tab_parser.py         (existing — tab body; add bar_count_info helpers)
├── bottom_parser.py      (existing — footer / dynamics)
│
├── repeat_expander.py    (NEW)
│   Expands the written score (with repeat signs) into performance order.
│
├── midi_timing.py        (NEW)
│   Reads raw MIDI events to produce a per-measure timing map.
│   Does NOT use music21 MusicXML conversion.
│
├── score_builder.py      (NEW)
│   Builds annotated MusicXML directly from the expanded tab score
│   plus the MIDI timing map.  No pitch matching.
│
├── annotate_xml.py       (DEPRECATED — replaced by score_builder)
├── convert_mid.py        (DEPRECATED — no longer needed)
│
├── issues_log.py         (existing — logging)
├── check_issues.py       (existing — diagnostic runner)
├── generate_site.py      (existing — static site; unchanged)
└── main.py               (updated orchestrator)
```

---

## Data models

### New models (add to `models.py`)

```python
@dataclass
class BeatGroupTiming:
    """
    Timing for one simultaneous beat group within a measure, derived from MIDI.

    onset_ticks   : absolute tick position of this beat group's first note-on
    duration_ticks: length of this beat in ticks (gap to next beat group onset,
                    or to end of measure for the last group)
    midi_pitches  : frozenset of MIDI pitches at this beat (for cross-validation
                    only — never used to override tab notes)
    """
    onset_ticks   : int
    duration_ticks: int
    midi_pitches  : frozenset[int]


@dataclass
class MeasureTiming:
    """
    Timing for one measure as extracted from the MIDI.

    measure_idx     : 0-based sequential index in the MIDI file
    onset_ticks     : absolute tick of the measure's first beat
    beat_groups     : beat groups in onset order
    tempo_bpm       : tempo at the start of this measure (quarter notes / min)
    divisions       : MIDI ticks per quarter note
    time_sig_num    : numerator  (e.g. 2 for 2/4)
    time_sig_denom  : denominator (e.g. 4 for 2/4)
    """
    measure_idx   : int
    onset_ticks   : int
    beat_groups   : list[BeatGroupTiming]
    tempo_bpm     : float
    divisions     : int
    time_sig_num  : int
    time_sig_denom: int


@dataclass
class TimingMap:
    """Complete timing information extracted from one MIDI file."""
    measures  : list[MeasureTiming]   # one per MIDI measure, in order
    divisions : int                    # ticks per quarter note (global)


@dataclass
class ExpandedMeasure:
    """
    One measure in performance order after repeat expansion.

    source_num    : original bar number in the .txt file
    notes         : NoteEvents (from tab_parser — complete, unchanged)
    barres        : BarreMarkers (from tab_parser)
    repeat_start  : True if a forward repeat opens on this bar
    repeat_end    : True if a backward repeat closes on this bar
    volta         : 1 or 2 for first/second ending; None otherwise
    pass_number   : 1 = first time through, 2 = repeat pass, etc.
    """
    source_num  : int
    notes       : list            # list[NoteEvent]
    barres      : list            # list[BarreMarker]
    repeat_start: bool
    repeat_end  : bool
    volta       : int | None
    pass_number : int


@dataclass
class ExpandedScore:
    """
    The tab score in performance order (repeats expanded).
    len(measures) should equal TimingMap.len(measures) after expansion.
    """
    measures: list[ExpandedMeasure]
    metadata: object   # TabMetadata (unchanged)
```

---

## Module interfaces

### `repeat_expander.py`

```python
def expand_repeats(tab: TabFile) -> ExpandedScore:
    """
    Convert the written score into performance order by expanding repeat signs.

    Algorithm
    ---------
    Uses a stack-based state machine that scans through tab.measures in key
    order and tracks the current repeat context:

    1.  Walk measure keys in ascending order.
    2.  When a measure has repeat_start=True, push the current key onto the
        repeat_stack.
    3.  When a measure has repeat_end=True:
        a.  Pop the matching repeat_start key (start_key).
        b.  If volta brackets exist within this span:
            - First pass:  include measures from start_key to the '1.' volta end.
            - Second pass: skip the '1.' volta; include from start_key to the
              '2.' volta end.
        c.  Without voltas: append the section [start_key..current] twice.
    4.  Continue until all measures are consumed.
    5.  Any measures after the last repeat end are appended once (coda).

    Gap bars (measure numbers that appear in the range but not in tab.measures)
    are naturally handled: on the second pass, those absent measure numbers
    are mapped back to the original source measures (they are the repeated
    content, not new material).

    Returns
    -------
    ExpandedScore whose measures are in the order a performer would play them.
    Each ExpandedMeasure retains its original source_num so that bar numbers
    reported in the issues log remain traceable to the written score.
    """
```

### `midi_timing.py`

```python
def extract_timing(mid_path: str) -> TimingMap:
    """
    Read a MIDI file and return per-measure beat-group timing.

    Uses `mido` (raw MIDI events) instead of music21/MusicXML conversion.
    No pitches are needed; only note-on onset times are collected.

    Algorithm
    ---------
    1.  Read all tracks; merge into a single event stream sorted by
        absolute tick.
    2.  Build a tempo map: list of (tick, microseconds_per_quarter) from
        set_tempo events.
    3.  Identify measure boundaries from time_signature events and the
        total ticks per measure.
    4.  Within each measure, group simultaneous note-on events (same tick)
        into BeatGroupTiming objects.
    5.  Compute duration_ticks for each beat group = next group's onset −
        this group's onset (or measure end for the last group).

    Returns
    -------
    TimingMap with one MeasureTiming per MIDI measure.

    Notes
    -----
    -  MIDI pitch data is stored in BeatGroupTiming.midi_pitches only as a
       cross-validation aid.  It is never used to override tab notes.
    -  Multiple MIDI tracks are merged; simultaneous notes from different
       tracks at the same tick are combined into one beat group.
    """


def ticks_to_musicxml_duration(
    ticks: int,
    divisions: int,
    time_sig_denom: int,
) -> tuple[int, str, int]:
    """
    Convert a raw tick duration into MusicXML duration components.

    Returns (duration_value, note_type_string, dots) where:
      duration_value : the <duration> element value (in divisions)
      note_type_string: 'quarter', 'eighth', 'half', '16th', etc.
      dots           : number of augmentation dots (0, 1, or 2)

    Uses the nearest standard rhythmic value; logs a warning for
    irregular durations that don't map cleanly.
    """
```

### `score_builder.py`

```python
def build_musicxml(
    expanded: ExpandedScore,
    timing:   TimingMap,
) -> ET.Element:
    """
    Construct a complete annotated MusicXML document from the tab (source of
    truth) and MIDI timing.

    Measure alignment
    -----------------
    expanded.measures[i] is paired with timing.measures[i] by sequential
    position — no pitch matching.  After repeat expansion the counts must
    match; any residual mismatch is logged as a 'bar_count_mismatch' issue.

    Beat-group alignment within a measure
    --------------------------------------
    For measure i:
      tab_beats  = get_beats(expanded.measures[i].notes)   # grouped by col
      midi_beats = timing.measures[i].beat_groups           # grouped by onset

    The two lists are zipped by position:
      tab_beats[j] ↔ midi_beats[j]

    When the lists have different lengths:
    -  Extra MIDI beats: treated as MIDI artifacts (slide destinations,
       ornamentation); skipped.  A note is logged if the excess is large.
    -  Extra tab beats: assigned an estimated duration derived from the
       measure's remaining time divided equally among the unmatched beats.
       Logged as a 'timing_estimation' notice.

    For each matched (tab_beat, midi_beat) pair:
      - Each NoteEvent in tab_beat becomes a MusicXML <note>.
      - Pitch is computed from (string, fret, tuning) — never from MIDI.
      - Duration comes from midi_beat.duration_ticks.
      - <technical>: <string>, <fret> from NoteEvent.
      - <technical>: <fingering> (LH), <pluck> (RH pima) from NoteEvent.
      - <technical>: <slide>, <hammer-on>, <pull-off>, <bend> from technique.
      - Simultaneous notes within the beat → chord (<chord/> elements).
      - First note in chord: non-chord; rest: <chord/>.

    Repeats
    -------
    Repeat barlines are written once, at the source measure's first
    performance pass (pass_number == 1).  Volta brackets are written as
    <ending> elements.

    Returns
    -------
    ET.Element root of a valid MusicXML document ready for AlphaTab.
    """


def _beat_to_xml_notes(
    beat     : list,           # list[NoteEvent], simultaneous
    duration : tuple,          # (duration_value, note_type, dots) from ticks_to_musicxml_duration
    tuning   : list[int],      # MIDI pitches per string, high→low
    voice    : int = 1,
) -> list[ET.Element]:
    """
    Convert one tab beat group into a list of MusicXML <note> elements.

    The first note in the group is a regular note; subsequent notes carry
    <chord/> so they sound simultaneously.  All share the same duration.
    """


def _add_technical(
    note_el  : ET.Element,
    ev       : object,         # NoteEvent
) -> None:
    """
    Append <notations><technical> children to a <note> element from a
    NoteEvent.  Handles: string, fret, fingering (LH), pluck (RH),
    slide start/stop, hammer-on, pull-off, bend, vibrato, harmonic.
    """
```

---

## Orchestration (`main.py`)

```
txt → parse_txt()         →  TabFile
                                │
                          expand_repeats()   →  ExpandedScore
                                │                    │
mid → extract_timing()   →  TimingMap               │
                                │                    │
                          build_musicxml(expanded, timing)
                                │
                          annotated MusicXML (ET.Element)
                                │
                          write XML → output/musicxml/
                                │
                          generate_site()   →  output/site/
```

---

## How repeats solve the bar-count mismatch

**El Negrito example** (0-indexed, written bars 0–80, 52 unique, 29 gap bars):

```
Written score:            Performance order after expand_repeats():
bar 0  (pickup)       →   bar 0
bars 1-16 (||: :||)   →   bars 1-16   (pass 1)
                          bars 1-16   (pass 2)  ← gap bars 20-33 in tab numbering
bars 17-18            →   bars 17-18
bars 19-48 (||: :||)  →   bars 19-48  (pass 1)
                          bars 19-48  (pass 2)  ← gap bars 49-63
bars 64-80            →   bars 64-80
```

Expanded: 1 + 16 + 16 + 2 + 30 + 30 + 17 = **112 measures**
MIDI non-empty: 80

Hmm — still doesn't match.  This means El Negrito's MIDI does *not* play both
repeats in full; it plays each section once.  The gap bars encode section-label
offsets, not repeats.  `expand_repeats()` must detect this case and NOT double
the sections; instead it uses the gap structure from `bar_count_info()` to
determine how many passes the MIDI actually makes.

This is why the gap-aware `bar_count_span` (81) ≈ MIDI (80) worked: the gaps
ARE the repeated bars, not bars that need to be generated by expanding.  The
tab numbering itself already encodes the full sequence; the gaps are just
skipped labels for the second pass.

**Corrected understanding:**

The tab's measure-number gaps do *not* mean "these bars are absent from the
tab"; they mean "the bar at position X in the performance corresponds to
source bar Y".  The gap bar numbers are *aliases* for repeated source bars.

`expand_repeats()` must therefore build a mapping:

```
gap_bar_number → source_bar_number
```

For El Negrito:
- gap bars 20–33 → source bars 1–14  (repeat of section A, shifted by 19)
- gap bars 49–63 → source bars 34–48 (repeat of section B, shifted by 15)

This mapping is derivable from the `||:` and `:|` positions and the gap positions.

---

## Cross-validation (not matching)

`score_builder.py` can optionally compare its MIDI pitch set against the tab
pitch set for each beat group — not to correct the tab, but to log discrepancies:

```python
def _validate_beat(
    tab_beat   : list,      # list[NoteEvent]
    midi_beat  : BeatGroupTiming,
    tuning     : list[int],
    context    : str,       # "bar N beat M" for log messages
) -> None:
    """
    Log a warning if the set of tab MIDI pitches differs materially from
    the set of MIDI note-on pitches at this beat.

    This never changes the output — it only logs to issues_log so the
    transcriber can investigate.
    """
```

---

## Migration path

1. Implement `midi_timing.py` — pure MIDI reader, no music21.
2. Implement `repeat_expander.py` — expand + gap-alias mapping.
3. Implement `score_builder.py` — build MusicXML from tab + timing.
4. Update `main.py` to use the new pipeline.
5. Keep `annotate_xml.py` and `convert_mid.py` as legacy fallbacks during
   transition; deprecate once the new pipeline passes the test suite.
6. Extend `TestXmlBarCountMatchesTab` to compare `len(expanded.measures)`
   against MIDI measure count (should be near-exact after expansion).
