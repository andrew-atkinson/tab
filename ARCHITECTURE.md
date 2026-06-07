# Architecture — Tab-Primary Pipeline

## Design principle

> **The `.txt` tab file is the complete musical score.**
> The `.mid` file is a timing oracle — it provides only beat durations.

| Source | Provides |
|--------|----------|
| `.txt` tab | Notes, strings, frets, beat order, techniques (slide, hammer-on, pull-off, bend, vibrato, harmonic), left-hand fingering, right-hand (pima) fingering, barres, repeats, voltas, time signature, key, tempo hint, tuning, title, composer |
| `.mid` MIDI | Duration in ticks of each beat group within each measure; tempo map; per-measure time signature (used for mid-piece changes) |

The MIDI is never used to determine which notes are played, on which strings, or
in what order. It answers one question only: "how long does beat group *i* last?"

---

## Why this matters

The previous pipeline converted the MIDI to MusicXML and matched tab notes into
it pitch-by-pitch (±2 semitones, 4-note lookahead). That caused:

- **Bar-count mismatches** — the MIDI plays repeated sections in full; the tab
  writes them once with repeat signs. The old pipeline had no concept of repeats.
- **Chord ordering errors** — MIDI encodes chords low→high; tab orders by string
  (high→low). Pitch matching produced duplicate string assignments.
- **Slide artifacts** — a slide `4/7` in the MIDI is two note-on events; in the
  tab it's one `NoteEvent` with `slide_to=7`. The extra MIDI note fell through to
  a pitch-fallback path.
- **Cross-beat drift** — lookahead allowed MIDI notes from beat N to match tab
  notes from beat N+1, corrupting voicing.

---

## Module structure

```
pipeline/
├── parse_txt.py          Entry point — ties the three parsers together
├── topmatter_parser.py   Header parsing (tuning, title, composer, time sig, …)
├── tab_parser.py         Tab body — systems, beats, fingering, notes, techniques
├── bottom_parser.py      Footer — legend, dynamics, biographical info
│
├── repeat_expander.py    Expands written score into performance order
├── midi_timing.py        Reads raw MIDI events → per-measure TimingMap (uses mido)
├── score_builder.py      Builds annotated MusicXML from ExpandedScore + TimingMap
│
├── generate_site.py      Static AlphaTab website generator (unchanged)
├── main.py               CLI orchestrator
│
├── annotate_xml.py       Legacy (superseded by score_builder; kept for reference)
├── convert_mid.py        Legacy (superseded by midi_timing; kept for reference)
│
├── issues_log.py         Structured issue logging
└── check_issues.py       Diagnostic runner over the corpus
```

---

## Data flow

```
txt → parse_txt()       →  TabFile
                               │
                         expand_repeats()  →  ExpandedScore
                               │                   │
mid → extract_timing()  →  TimingMap               │
                               │                   │
                         build_musicxml(expanded, timing)
                               │
                         annotated MusicXML (ET.Element)
                               │
                         write XML → output/musicxml/
                               │
                         generate_site()  →  output/site/
```

---

## Data models

All models live in `models.py`.

### Parse-time models

```
TabFile
├── metadata : TabMetadata
│   ├── title, composer, composer_dates, transcriber
│   ├── tuning          "EADGBE"  (low→high)
│   ├── key, time_sig, tempo, tempo_unit, capo
│   ├── notes_text, dynamics, biographical, chords
├── measures : dict[int, MeasureData]
│   └── MeasureData
│       ├── number
│       ├── repeat_start, repeat_end, volta
│       ├── barres   : list[BarreMarker]
│       └── notes    : list[NoteEvent]
│           ├── string (1=high e … 6=low E), fret, col
│           ├── midi_pitch, open_note
│           ├── finger (LH 1-4), rh_finger (pima)
│           ├── technique  (slide_up/slide_down/hammer/pull/bend/vibrato)
│           ├── slide_to   (int | None — destination fret)
│           ├── touch_fret (int | None — artificial harmonic touch point)
│           ├── tied, harmonic, triplet
└── raw_text : str
```

### Pipeline models

```
ExpandedScore
└── measures : list[ExpandedMeasure]
    └── source_num, notes, barres,
        repeat_start, repeat_end, volta, pass_number

TimingMap
└── measures : list[MeasureTiming]
    └── measure_idx, onset_ticks, total_ticks, divisions,
        tempo_bpm, time_sig_num, time_sig_denom,
        beat_groups : list[BeatGroupTiming]
            └── onset_ticks, duration_ticks, midi_pitches
```

---

## `repeat_expander.py`

Converts the written score into performance order. Two strategies are selected
automatically based on the ratio of gap bar numbers to written bar numbers
(threshold: 5 %):

### Gap-encoded repeats (El Negrito / Lauro style)

The transcriber numbers bars as if repeats are already played out, then writes
only unique bars. Gap bar numbers in the range `[min_key, max_key]` are aliases
for repeated source bars.

```
Written bars:  1  2  3  4     7  8
Gap bars:               5  6
Gap alias:     5→3  6→4
Performance:   1  2  3  4  3  4  7  8
```

The alias map is built by matching gap positions to the nearest preceding repeat
section (identified by `||:` / `:|` markers). Remaining unaliased gaps fall back
to the nearest preceding written bar.

### Sign-encoded repeats (Barrios / Choros style)

Explicit `||:` and `:|` signs on the string lines. A stack-based expander walks
measure keys in order, pushing on `repeat_start` and replaying sections on
`repeat_end`.

Volta brackets (`1___`, `2___` in the measure-number line):
- Pass 1: plays `volta=1` measures, skips `volta=2`.
- Pass 2: skips `volta=1`, plays `volta=2`.

If a backward repeat exists but no forward repeat, `repeat_start` is
automatically added to the first measure of the piece.

---

## `midi_timing.py`

Uses `mido` (raw MIDI events, no MusicXML conversion) to produce a `TimingMap`.

1. Reads all MIDI tracks; merges into a single event stream sorted by absolute tick.
2. Builds a tempo map from `set_tempo` events.
3. Identifies measure boundaries from `time_signature` events and ticks-per-measure.
4. Within each measure, groups simultaneous `note_on` events (same tick) into
   `BeatGroupTiming` objects.
5. `duration_ticks` for each beat group = next group's onset − this group's onset
   (or measure end for the last group).

`midi_pitches` in each `BeatGroupTiming` are stored for cross-validation only —
they are never used to override tab content.

`ticks_to_duration(ticks, divisions, time_sig_denom)` maps a tick count to the
nearest standard note value: `(duration_value, note_type_str, n_dots)`.

---

## `score_builder.py`

### Measure alignment

`expanded.measures[i]` is paired with `timing.measures[i]` by sequential
position — no pitch matching. When counts differ, the shorter list determines
how many pairs are formed; surplus measures on either side are logged.

### Beat-group alignment

Within each measure:

```
tab_beats  = get_beats(expanded_measure.notes)   # grouped by col
midi_beats = timing_measure.beat_groups           # grouped by onset tick
```

The two lists are zipped by position.

- **Extra MIDI beats** (slide destinations, ornaments) → skipped.
- **Extra tab beats** → duration estimated from remaining measure ticks divided
  equally; logged as `timing_estimation`.

### Slide duration merging

A slide `4/7` in the tab is one beat, but the MIDI records two note-on events:
one at the source pitch and one at the destination. Without correction the
MIDI-index would shift, misaligning every subsequent beat.

Fix: when a tab beat contains a slide with a known `slide_to`, and the next MIDI
beat's pitches include the destination pitch (within ±1 semitone), the two MIDI
durations are merged into the slide beat and the MIDI index advances by 2.

### Technique destination synthesis

Slides, hammer-ons, and pull-offs in the tab have `slide_to` set and no
separate destination `NoteEvent` (the parser consumes the destination fret into
`slide_to`). The score builder synthesises a destination note:

```
source note  →  duration × 2/3   (technique start annotation)
dest note    →  duration × 1/3   (technique stop annotation)
```

Both notes are emitted into the same measure. If the destination note was
already written explicitly in the tab (at the next beat, same string, correct
fret), no synthesis occurs — the explicit note is annotated as a stop instead.

Open-ended techniques (`slide_to=None`) emit only a start annotation; no
destination note is synthesised.

### `<slide>` XML placement

`<slide>` is a **direct child of `<notations>`**, not inside `<technical>`.
This is required by AlphaTab's MusicXML parser. `@line-type` is not included
(not supported by AlphaTab). `@number="1"` is always set.

`<hammer-on>` and `<pull-off>` remain inside `<technical>`, which is the
MusicXML spec location and what AlphaTab expects.

### Time signature handling

- **First measure**: the tab header's `time_sig` (e.g. `"2/4"`) overrides the
  MIDI default, which is almost always 4/4 regardless of actual metre.
- **Mid-piece changes**: taken from `MeasureTiming.time_sig_num/denom` from MIDI
  meta-events. A `<attributes><time>` block is emitted only when the time
  signature changes relative to the preceding measure.
- **Fallback measures** (when `n_exp > n_midi`): the last known MIDI time
  signature is carried forward; `prev_time_sig` threading prevents redundant
  `<time>` re-declarations.

### Harmonic encoding

| Tab notation | `harmonic` | `touch_fret` | MusicXML output |
|---|---|---|---|
| `<7>` (bracket) | True | None | `<harmonic><natural/>` inside `<technical>` |
| `3[15]` (artificial) | True | 15 | `<harmonic><artificial/>` inside `<technical>` |
| `Harm.` text | True (if fret ∈ {5,7,9,12,19,24}) | None | `<harmonic><natural/>` |

---

## Test suite

| Script | Scope | Sample |
|--------|-------|--------|
| `test_parsers.py` | Unit + integration (145 tests) | Fixed synthetic inputs |
| `test_pipeline.py` | End-to-end XML correctness | 4 hand-validated reference pieces |
| `test_harmonics_slides.py` | Harmonic + slide XML encoding | 300 pieces each |
| `test_techniques.py` | Pull-off / hammer-on XML pairs, timing | 100 pieces, seed=7 |
| `test_time_signatures.py` | Time sig parsing + mid-piece changes | 150 pieces, seeds 11 & 17 |

`test_techniques.py` distinguishes open-ended techniques (`slide_to=None` —
valid notation) from broken pairs (destination written but no matching stop in
the XML). The real broken count is `max(0, unpaired − open_ended_count)`.

Timing tolerance for technique-containing measures is 1.30× because destination
synthesis adds up to 1/3 of the original beat duration.

---

## Known edge cases

**Open-ended techniques** — `6\`, `1h-` without a destination fret. `slide_to`
is `None`; the score builder emits only a start annotation. Not an error.

**Bar-count mismatch after expansion** — Choros No. 1 and similar pieces have
MIDI files that don't match the tab bar count even after expansion. The shorter
list controls pairing; surplus measures from either side are logged and skipped.

**MIDI measure 0 defaulting to 4/4** — very common. Overridden by the tab
header's `time_sig` on the first measure.

**`_TIME_RE` separator variants** — the time signature regex accepts `is` as a
separator (`"The time signature is 2/4"`) in addition to `:`, `-`, and `–`.
