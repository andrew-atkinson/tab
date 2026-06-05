"""
convert_mid.py
==============
Convert a .mid file to MusicXML using music21.

Fixes applied automatically:
  - Clef set to guitar clef (treble clef sounding an octave lower)
  - Staff-details added for standard guitar tuning (overridden by annotator)
  - Part name set to "Guitar"
"""

from __future__ import annotations
import os
import warnings
# Suppress the RequestsDependencyWarning from music21's requests import
# (urllib3/charset_normalizer version mismatch — harmless)
warnings.filterwarnings('ignore', category=Warning, module='requests')
from music21 import converter, stream, clef, instrument


def mid_to_musicxml(mid_path: str, out_xml_path: str) -> str:
    """
    Convert *mid_path* → MusicXML at *out_xml_path*.
    Returns the output path.
    """
    score: stream.Score = converter.parse(mid_path)

    if not score.parts:
        raise ValueError(f"No parts found in {mid_path}")

    part = score.parts[0]
    part.insert(0, instrument.Guitar())

    # Guitar clef: treble clef sounding an octave lower.
    first_measure = part.getElementsByClass(stream.Measure).first()
    if first_measure:
        for c in first_measure.getElementsByClass(clef.Clef):
            first_measure.remove(c)
        first_measure.insert(0, clef.Treble8vbClef())

    # Keep all parts so bass/inner-voice MIDI tracks survive into the XML.
    # annotate_xml.py annotates notes across all parts via global pitch matching,
    # then calls _merge_parts() to fold them into a single guitar staff before
    # writing — so AlphaTab sees one part with all strings populated.
    single_score = stream.Score()
    single_score.append(part)          # Part 0 always goes first (gets Guitar instrument + clef)
    for extra in score.parts[1:]:
        single_score.append(extra)     # retain additional tracks (bass, inner voices)
    single_score.metadata = score.metadata  # preserve tempo / key / time sig

    os.makedirs(os.path.dirname(out_xml_path), exist_ok=True)
    single_score.write('musicxml', fp=out_xml_path)
    return out_xml_path
