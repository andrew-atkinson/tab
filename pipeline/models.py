"""
models.py
=========
Shared data model classes for the classtab parser pipeline.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NoteEvent:
    string: int              # 1 = highest string, 6 = lowest string
    fret: int
    col: int                 # column in the full line (for alignment)
    finger: Optional[int] = None       # left-hand: 1-4
    rh_finger: Optional[str] = None   # right-hand: p/i/m/a
    technique: Optional[str] = None   # slide_up/slide_down/hammer/pull/bend/vibrato
    tied: bool = False
    harmonic: bool = False
    triplet: bool = False
    open_note: str = ""      # open-string note name, e.g. "E4" (tuning-derived)
    midi_pitch: int = -1     # sounding MIDI pitch (-1 = unknown)
    slide_to: Optional[int] = None    # destination fret for slides, e.g. 1/5 → slide_to=5
    touch_fret: Optional[int] = None  # artificial harmonic: fret to touch (e.g. 3[15] → touch_fret=15)


@dataclass
class BarreMarker:
    fret: int
    partial: bool            # True = partial barre (lowercase c)
    col_start: int
    col_end: int


@dataclass
class MeasureData:
    number: int
    notes: list[NoteEvent] = field(default_factory=list)
    barres: list[BarreMarker] = field(default_factory=list)
    repeat_start: bool = False
    repeat_end: bool = False
    volta: Optional[int] = None


@dataclass
class TabMetadata:
    title: str = ""
    subtitle: str = ""
    composer: str = ""
    composer_dates: str = ""
    transcriber: str = ""
    edition: str = ""
    tuning: str = "EADGBE"
    key: str = ""
    time_sig: str = ""
    tempo: int = 0
    tempo_unit: str = "quarter"
    capo: int = 0
    notes_text: str = ""
    dynamics: list[str] = field(default_factory=list)
    biographical: str = ""
    chords: list[dict] = field(default_factory=list)


@dataclass
class TabFile:
    metadata: TabMetadata
    measures: dict[int, MeasureData]
    raw_text: str


# ---------------------------------------------------------------------------
# New pipeline data models (tab-primary architecture)
# ---------------------------------------------------------------------------

@dataclass
class BeatGroupTiming:
    """
    Timing for one simultaneous beat group within a measure, derived from MIDI.

    onset_ticks   : absolute tick of this group's first note-on
    duration_ticks: ticks until the next group's onset (or measure end)
    midi_pitches  : MIDI pitches present (cross-validation only — never used
                    to override tab notes)
    """
    onset_ticks   : int
    duration_ticks: int
    midi_pitches  : frozenset = field(default_factory=frozenset)


@dataclass
class MeasureTiming:
    """
    Timing information for one MIDI measure.

    measure_idx    : 0-based sequential index in the MIDI file
    onset_ticks    : absolute tick of the first beat of this measure
    total_ticks    : length of the measure in ticks
    beat_groups    : BeatGroupTiming objects in onset order
    tempo_bpm      : tempo at measure start (quarter notes / minute)
    divisions      : ticks per quarter note
    time_sig_num   : e.g. 2 for 2/4
    time_sig_denom : e.g. 4 for 2/4
    """
    measure_idx   : int
    onset_ticks   : int
    total_ticks   : int
    beat_groups   : list = field(default_factory=list)  # list[BeatGroupTiming]
    tempo_bpm     : float = 120.0
    divisions     : int   = 480
    time_sig_num  : int   = 4
    time_sig_denom: int   = 4


@dataclass
class TimingMap:
    """Complete timing information extracted from one MIDI file."""
    measures : list = field(default_factory=list)  # list[MeasureTiming]
    divisions: int  = 480                          # ticks per quarter note


@dataclass
class ExpandedMeasure:
    """
    One measure in performance order after repeat expansion.

    source_num  : original bar number in the .txt file
    notes       : NoteEvents (from tab — unchanged, complete)
    barres      : BarreMarkers (from tab — unchanged)
    repeat_start: True if a forward-repeat barline opens on this bar (first pass)
    repeat_end  : True if a backward-repeat barline closes on this bar (last pass)
    volta       : 1 or 2 for first/second ending; None otherwise
    pass_number : 1 = first playing, 2 = repeated playing, etc.
    """
    source_num  : int
    notes       : list = field(default_factory=list)   # list[NoteEvent]
    barres      : list = field(default_factory=list)   # list[BarreMarker]
    repeat_start: bool = False
    repeat_end  : bool = False
    volta       : Optional[int] = None
    pass_number : int  = 1


@dataclass
class ExpandedScore:
    """Tab score in performance order (repeats expanded)."""
    measures: list = field(default_factory=list)  # list[ExpandedMeasure]
    metadata: Optional[TabMetadata] = None
