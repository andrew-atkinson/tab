# Classical Guitar Tab → MusicXML Pipeline

Converts the [classtab.org](https://www.classtab.org) library of ASCII guitar tablature into annotated MusicXML files and renders them as an interactive static website using [AlphaTab](https://www.alphatab.net).

Each piece ends up as a single HTML page showing the tab and standard notation side-by-side, with string/fret annotations, left- and right-hand fingering, barre markings, tuning, repeats, and harmonics.

---

## Getting the source files

The tab files come from [classtab.org](https://www.classtab.org), a long-running archive of classical guitar tablature.

1. Go to **https://www.classtab.org** and download the full zip archive (linked on the homepage as something like *"Download all files"*).
2. Unzip the archive. It will contain a large collection of `.txt` and `.mid` files.
3. Place the unzipped contents into a folder called **`tab/`** at the root of this repository:

```
tab/           ← create this folder and put the files here
├── lauro_two_venezuelan_waltzes_1_el_negrito.txt
├── lauro_two_venezuelan_waltzes_1_el_negrito.mid
├── villa-lobos_choros_01.txt
├── villa-lobos_choros_01.mid
└── … (~2 300 pairs)
```

The `tab/` folder is listed in `.gitignore` and will not be committed.

---

## Repository layout

```
tab/                    ← root of the repo (same name as the source folder)
├── tab/                Source files — .txt and .mid pairs (git-ignored)
├── pipeline/           Processing code
│   ├── models.py           Shared data classes (NoteEvent, MeasureData, …)
│   ├── topmatter_parser.py Header parsing: tuning, title, composer, transcriber, chords
│   ├── tab_parser.py       Tab-body parsing: systems, beats, fingering, notes
│   ├── bottom_parser.py    Footer parsing: legend, dynamics, biographical info
│   ├── parse_txt.py        Main entry point – ties the three parsers together
│   ├── convert_mid.py      MIDI → raw MusicXML  (via music21)
│   ├── annotate_xml.py     Merges tab annotations into the raw MusicXML
│   ├── generate_site.py    Builds the static AlphaTab website
│   ├── main.py             CLI orchestrator for the full pipeline
│   ├── test_parsers.py     Unit & integration test suite (145 tests)
│   └── test_pipeline.py    End-to-end pipeline validation (4 reference pieces)
├── output/             Generated files (git-ignored)
│   ├── musicxml/           Annotated .xml files
│   └── site/               Static website
├── pieces.json         Catalogue of all pieces with metadata
├── .gitignore
└── README.md
```

---

## How the pipeline works

```
tab/*.txt ──┐
            ├──► parse_txt.py ──► TabFile (metadata + measures + notes)
tab/*.mid ──┘         │
                      │
convert_mid.py ───────┤
  MIDI → raw MusicXML │
                      ▼
               annotate_xml.py
                 • Merges MIDI parts beat-by-beat
                 • Assigns string, fret, fingering to each note
                 • Adds tuning, capo, barres, repeats
                      │
                      ▼
               output/musicxml/*.xml   (annotated MusicXML)
                      │
                      ▼
               generate_site.py
                 • One HTML page per piece
                 • AlphaTab renders notation + TAB
                      │
                      ▼
               output/site/index.html  (searchable library)
```

### Parser modules

**`topmatter_parser.py`** scans the first 60 lines of the tab file for:

| Function | Extracts |
|---|---|
| `find_tuning()` | Explicit `Tuning: DADGBE`, named tunings (Drop D, Open G, DADGAD), per-string overrides (`Tune 6th string to D`) |
| `find_composer_author_title()` | `Title – Composer (dates)` pattern, `Subject:` lines, `Author:`/`By:` labels, wide-space layout |
| `find_transcriber()` | `tabbed by`, `transcribed by`, `arranged by` (strips dates and email) |
| `find_chords_fingering()` | Named chord-box diagrams |
| `parse_topmatter()` | All of the above plus key, time signature, tempo, capo |

**`tab_parser.py`** is tuning-aware: every `NoteEvent` carries the sounding MIDI pitch and the open-string note name computed from the tuning at parse time.

| Function | Does |
|---|---|
| `find_systems()` | Locates all 6-string tab blocks; records measure number, barre, pima, and fingering line indices |
| `bar_positions()` / `measure_cells()` | Splits each system into per-measure column slices |
| `extract_notes()` | Parses frets, harmonics `<7>`, techniques (`h p / \ b ~`), ties `=`, triplets `-3-` |
| `parse_barres()` | Detects Roman (`CII`, `cIV`) and Arabic (`C5`) barre markers |
| `assign_lh_fingering()` | Aligns digit lines (1–4) to notes by column proximity |
| `assign_rh_fingering()` | Aligns pima lines to notes by column proximity |
| `get_beats()` | Groups a measure's notes into simultaneous beat groups by column |
| `parse_tab()` | Full pipeline: returns `dict[int, MeasureData]` |

**`bottom_parser.py`** extracts post-tab content:

| Function | Extracts |
|---|---|
| `find_notes_legend()` | Tablature explanation / legend section |
| `find_dynamics()` | Dynamic markings (pp, mf, f, cresc, …) |
| `find_biographical()` | Composer bio paragraphs |

### Annotation (`annotate_xml.py`)

The key challenge is that guitar MIDI files are often multi-track. `_merge_parts` collects all pitched notes from every MIDI part with their true beat offsets, sorts them by offset (Part-0 notes first at ties), and rebuilds each measure as a single-voice sequence. Note durations are truncated to the gap until the next note onset so that sequentially placed notes land at the correct beat without overlapping.

Note matching uses a global sequential algorithm with a 4-note lookahead: XML notes (from the MIDI) are matched 1-to-1 with tab notes ordered by `(measure, col, string)`, verified by MIDI pitch within ±2 semitones. Unmatched notes fall back to a pitch-only string/fret guess.

---

## Setup

### Requirements

- Python 3.10 or later
- One external library: [music21](https://web.mit.edu/music21/)

### Recommended: virtual environment

```bash
# 1. Clone the repo
git clone <repo-url>
cd tab

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows

# 3. Install the package and its dependencies
pip install -e .
```

`pip install -e .` installs `music21` automatically (declared in `pyproject.toml`) and registers the `tab-pipeline` command so you can run the pipeline from any directory.

### Minimal install (no entry point)

If you prefer not to install the package, just install the dependency directly:

```bash
pip install music21
```

Then run the scripts with `python pipeline/main.py` from the repo root.

### Process the full library

```bash
# If installed with pip install -e .
tab-pipeline

# Or directly from the repo root
python pipeline/main.py

# Common options (both forms accept the same flags)
tab-pipeline \
    --input   tab/   \   # source folder or single file     [default: tab/]
    --output  output/ \  # output root                      [default: output/]
    --jobs    8       \  # parallel workers                 [default: 4]
    --limit   50      \  # first N files, alphabetically    [all]
    --pieces          \  # only the 4 validated reference pieces (see below)
    --force           \  # reprocess even if output exists
    --no-site            # skip site generation (conversion only)
```

`--limit` and `--pieces` are mutually exclusive selection modes:

- `--limit N` takes the first N `.txt`/`.mid` pairs found in `tab/`, sorted alphabetically. Useful for a quick smoke-test across random pieces.
- `--pieces` runs only the four hand-validated reference pieces defined in `test_pipeline.PIECES` — the same set used by the end-to-end test suite. This is the recommended way to verify the pipeline after a code change:

```bash
tab-pipeline --pieces --force    # re-run just the 4 reference pieces
python pipeline/test_pipeline.py # then check pitch/chord accuracy
```

To add a piece to the reference set, add an entry to `PIECES` in `test_pipeline.py`.

Output goes to `output/musicxml/` (annotated XML) and `output/site/` (website). Open `output/site/index.html` in a browser.

### Process a single file

Pass a `.txt` or `.mid` file directly to `--input`; the pipeline finds the partner automatically:

```bash
python pipeline/main.py \
    --input tab/lauro_two_venezuelan_waltzes_1_el_negrito.txt \
    --no-site
```

Or parse programmatically:

```python
from pipeline.parse_txt import parse

tab = parse('tab/lauro_two_venezuelan_waltzes_1_el_negrito.txt')

print(tab.metadata.title)       # "El Negrito (from Two Venezuelan Waltzes)"
print(tab.metadata.composer)    # "Antonio Lauro"
print(tab.metadata.tuning)      # "EADGBE"
print(tab.metadata.transcriber) # "Weed"
print(len(tab.measures))        # 52

# Iterate beat-by-beat through a measure
from pipeline.tab_parser import get_beats
for beat in get_beats(tab.measures[1].notes):
    print([f's{n.string}f{n.fret} ({n.midi_pitch})' for n in beat])
```

### Adding a piece to `test_pipeline.py`

Add an entry to the `PIECES` list with the filename stems (without extensions):

```python
PIECES = [
    ...
    {
        'name': 'Recuerdos de la Alhambra (Tárrega)',
        'txt':  'tarrega_recuerdos_de_la_alhambra.txt',
        'mid':  'tarrega_recuerdos_de_la_alhambra.mid',
    },
]
```

Then run:

```bash
python pipeline/test_pipeline.py
```

---

## Running the tests

```bash
# Unit + integration tests (fast, ~10 s)
python pipeline/test_parsers.py

# End-to-end pipeline validation (4 reference pieces)
python pipeline/test_pipeline.py
```

`test_parsers.py` has 145 tests organised into:

| Group | Tests | What's covered |
|---|---|---|
| `TestFindTuning` | 8 | All tuning formats (explicit, Drop D, Open G, DADGAD, per-string) |
| `TestFindComposerAuthorTitle` | 7 | All title/composer patterns |
| `TestFindTranscriber` | 5 | Tab credit extraction |
| `TestFindChordsFingeringEmpty` | 2 | Chord diagram detection |
| `TestParseTopmatter` | 4 | Key, time, tempo, capo |
| `TestTuningHelpers` | 5 | MIDI pitch and open-note computation |
| `TestContentStart` | 6 | All 5 string-line prefix formats |
| `TestBarPositions` | 3 | Barline detection |
| `TestMeasureCells` | 2 | Measure slice geometry |
| `TestExtractNotes` | 9 | Frets, harmonics, techniques, MIDI pitches |
| `TestParseBarres` | 4 | Roman and Arabic barre markers |
| `TestAssignLhFingering` | 3 | Left-hand fingering alignment |
| `TestAssignRhFingering` | 3 | Right-hand pima alignment |
| `TestDetectRepeatVolta` | 3 | Repeat signs |
| `TestFindSystems` | 2 | System detection on real files |
| `TestParseTab` | 6 | Full tab parse including tuning and repeat detection |
| `TestFindNotesLegend` | 3 | Legend section |
| `TestFindDynamics` | 3 | Dynamic marking extraction |
| `TestFindBiographical` | 3 | Biographical paragraph detection |
| `TestParseBottom` | 2 | Combined bottom-matter parse |
| `TestGetBeats` | 6 | `get_beats()` with synthetic note lists |
| `TestBeatStructureElNegrito` | 12 | Exact beat sequence for El Negrito bar 2, incl. post-merge XML |
| `TestBeatInvariants_*` (×5) | 35 | Beat invariants on 5 pieces (1–5 MIDI parts each) |
| `TestIntegration` | 9 | Full `parse()` round-trip on real files |

### Adding beat-structure tests for a new piece

Subclass `BeatInvariantsMixin` and set two class attributes:

```python
class TestBeatInvariants_Tarrega(BeatInvariantsMixin, unittest.TestCase):
    txt_stem = 'tarrega_recuerdos_de_la_alhambra'
    mid_stem = 'tarrega_recuerdos_de_la_alhambra'
```

This automatically runs all 7 structural invariants (beat column ordering, string ordering within beats, positive MIDI pitches, open-note labels, and non-decreasing XML beat offsets after merge) against the new piece. Add it to the runner list in `main()`.

---

## Tab format variants supported

The parser handles every format variant found across the classtab.org library:

| Code | Example prefix | Description |
|---|---|---|
| A | `E\|----` | String letter + pipe |
| A' | `F#\|---` | Letter with accidental (non-standard tuning) |
| A" | `b\|----` | Lowercase string letter |
| B | `E----` | Letter + dashes, barlines embedded |
| C | `\|\|----` | Double-pipe prefix, no letter |
| D | `\|----` | Single-pipe prefix, no letter |
| E/F | `-0---\|` | Dash/digit first, barline embedded |

Additional features parsed:

- **Barre markers**: Roman (`CII`, `cIV`) and Arabic (`C5`, `c7`)
- **Harmonics**: `<7>` → `NoteEvent.harmonic = True`
- **Repeats**: `*|` `|*` `||:` `:|` → `repeat_start` / `repeat_end` on `MeasureData`
- **Volta brackets**: `1____` patterns in measure-number lines
- **Triplets**: `|-3-|` → `NoteEvent.triplet = True`
- **Held notes**: `===` → `NoteEvent.tied = True`
- **Techniques**: `/` `\` `h` `p` `b` `~` → slide up/down, hammer-on, pull-off, bend, vibrato
- **Tuning variants**: Standard, Drop D, Open G/D, DADGAD, explicit per-string overrides

---

## `pieces.json`

The file `pieces.json` is a catalogue of all pieces in `tab/`. Each entry has:

```json
{
  "stem":     "lauro_two_venezuelan_waltzes_1_el_negrito",
  "title":    "El Negrito (from Two Venezuelan Waltzes)",
  "composer": "Antonio Lauro",
  "format":   "A",
  "tuning":   ["E4", "B3", "G3", "D3", "A2", "E2"]
}
```

The `format` field records the string-line prefix style (A–F above). The `tuning` array lists open-string pitches high-to-low (string 1 first) as note-name + octave strings.

---

## Data model

```
TabFile
├── metadata : TabMetadata
│   ├── title, composer, composer_dates, transcriber
│   ├── tuning          "EADGBE"  (low→high)
│   ├── key, time_sig, tempo, capo
│   ├── notes_text      tablature legend
│   ├── dynamics        ["p", "mf", …]
│   ├── biographical    composer bio text
│   └── chords          [{"name": "Am", "strings": […], "fingering": […]}, …]
├── measures : dict[int, MeasureData]
│   └── MeasureData
│       ├── number
│       ├── repeat_start, repeat_end, volta
│       ├── barres   : list[BarreMarker]   fret, partial, col_start, col_end
│       └── notes    : list[NoteEvent]
│           ├── string       1 (high e) … 6 (low E)
│           ├── fret
│           ├── col          absolute column (beat proxy)
│           ├── midi_pitch   sounding MIDI pitch (tuning-computed)
│           ├── open_note    e.g. "E4"
│           ├── finger       left-hand 1–4
│           ├── rh_finger    right-hand p/i/m/a
│           ├── technique    slide_up/down/hammer/pull/bend/vibrato
│           ├── tied, harmonic, triplet
└── raw_text : str
```
