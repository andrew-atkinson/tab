"""
midi_timing.py
==============
Extract per-measure beat-group timing from a MIDI file using mido (raw MIDI
events, no music21 / MusicXML conversion).

The MIDI is used **only** as a clock.  Pitch data is stored in
BeatGroupTiming.midi_pitches purely as a cross-validation aid; it never
overrides what the tab says.

Public API
----------
    extract_timing(mid_path) -> TimingMap
    ticks_to_duration(ticks, divisions, time_sig_denom) -> (duration_value, note_type, dots)
"""

from __future__ import annotations
import mido
from models import BeatGroupTiming, MeasureTiming, TimingMap


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TEMPO = 500_000   # µs per quarter note = 120 BPM

_NOTE_TYPES: list[tuple[float, str]] = [
    (8.0,    'long'),
    (4.0,    'breve'),
    (2.0,    'half'),
    (1.0,    'quarter'),
    (0.5,    'eighth'),
    (0.25,   '16th'),
    (0.125,  '32nd'),
    (0.0625, '64th'),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bpm(µs_per_quarter: int) -> float:
    return 60_000_000 / max(1, µs_per_quarter)


def _measure_ticks(ts_num: int, ts_denom: int, tpb: int) -> int:
    """Ticks per complete measure."""
    return round(ts_num * (4 / ts_denom) * tpb)


def _merged_events(mid: mido.MidiFile) -> list[tuple[int, mido.Message]]:
    """All tracks merged into one list sorted by absolute tick."""
    out: list[tuple[int, mido.Message]] = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            out.append((tick, msg))
    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------------------
# Duration quantisation
# ---------------------------------------------------------------------------

def ticks_to_duration(
    ticks: int,
    divisions: int,
    time_sig_denom: int = 4,
) -> tuple[int, str, int]:
    """
    Map a tick count to (duration_value, note_type_string, dots).

    duration_value equals ticks directly (we use tpb as our XML divisions
    unit), so AlphaTab gets the exact tick value and renders it correctly.
    note_type and dots are the nearest standard rhythmic label.
    """
    qf = ticks / max(1, divisions)   # duration as fraction of a quarter note
    best_type, best_dots, best_err = 'quarter', 0, float('inf')
    for base_frac, note_type in _NOTE_TYPES:
        for dots in (0, 1, 2):
            dotted = base_frac * (2.0 - 2.0 ** -dots)
            err    = abs(dotted - qf)
            if err < best_err:
                best_err, best_type, best_dots = err, note_type, dots
    return (ticks, best_type, best_dots)


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_timing(mid_path: str) -> TimingMap:
    """
    Read *mid_path* and return a TimingMap with per-measure beat-group timing.

    Algorithm
    ---------
    Single pass through the merged event stream:

    1.  Track the current time signature and tempo, updating whenever
        time_signature / set_tempo meta-messages are encountered.
    2.  Maintain a running measure boundary; advance it (and increment the
        measure index) whenever the current event tick crosses the boundary.
    3.  Accumulate note-on events (velocity > 0) grouped by their absolute
        tick within each measure.
    4.  After the pass, convert each measure's note-on groups into
        BeatGroupTiming objects with onset and duration in ticks.
    """
    mid = mido.MidiFile(mid_path)
    tpb = mid.ticks_per_beat
    events = _merged_events(mid)

    # ── State ────────────────────────────────────────────────────────────────
    tempo      = _DEFAULT_TEMPO
    ts_num, ts_denom = 4, 4
    meas_len   = _measure_ticks(ts_num, ts_denom, tpb)
    meas_start = 0
    meas_idx   = 0

    # Per-measure data: {meas_idx: {abs_tick: set(pitches)}}
    note_ons: dict[int, dict[int, set[int]]] = {}
    # Per-measure metadata snapshot at measure start
    meas_meta: dict[int, tuple[int, int, int, int, int]] = {}
    # (tempo_µs, ts_num, ts_denom, meas_start, meas_len)
    meas_meta[0] = (tempo, ts_num, ts_denom, meas_start, meas_len)

    def _advance_measures(up_to_tick: int) -> None:
        nonlocal meas_start, meas_idx, meas_len
        while up_to_tick >= meas_start + meas_len:
            meas_start += meas_len
            meas_idx   += 1
            meas_meta[meas_idx] = (tempo, ts_num, ts_denom, meas_start, meas_len)

    # ── Single pass ──────────────────────────────────────────────────────────
    for abs_tick, msg in events:
        _advance_measures(abs_tick)

        if msg.type == 'time_signature':
            ts_num, ts_denom = msg.numerator, msg.denominator
            meas_len = _measure_ticks(ts_num, ts_denom, tpb)

        elif msg.type == 'set_tempo':
            tempo = msg.tempo

        elif msg.type == 'note_on' and msg.velocity > 0:
            note_ons.setdefault(meas_idx, {}).setdefault(
                abs_tick, set()
            ).add(msg.note)

    total = meas_idx + 1

    # ── Build MeasureTiming objects ──────────────────────────────────────────
    measures: list[MeasureTiming] = []
    for midx in range(total):
        µs, t_num, t_denom, m_start, m_len = meas_meta.get(
            midx, (tempo, ts_num, ts_denom, midx * meas_len, meas_len)
        )
        raw = note_ons.get(midx, {})
        onsets = sorted(raw)

        beat_groups: list[BeatGroupTiming] = []
        for oi, onset in enumerate(onsets):
            nxt = onsets[oi + 1] if oi + 1 < len(onsets) else m_start + m_len
            beat_groups.append(BeatGroupTiming(
                onset_ticks    = onset,
                duration_ticks = nxt - onset,
                midi_pitches   = frozenset(raw[onset]),
            ))

        measures.append(MeasureTiming(
            measure_idx    = midx,
            onset_ticks    = m_start,
            total_ticks    = m_len,
            beat_groups    = beat_groups,
            tempo_bpm      = _bpm(µs),
            divisions      = tpb,
            time_sig_num   = t_num,
            time_sig_denom = t_denom,
        ))

    return TimingMap(measures=measures, divisions=tpb)
