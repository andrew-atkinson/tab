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
    slide_to: Optional[int] = None  # destination fret for slides, e.g. 1/5 → slide_to=5


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
