"""
bottom_parser.py
================
Functions for parsing the footer / bottom section of classtab ASCII tabs.

The "bottom matter" is everything after the last tab system: tablature
explanation notes, legends, performance notes, biographical information
about the composer, and dynamic markings embedded in text.

Public API
----------
  find_notes_legend(lines)   -> str         the notes/legend section text
  find_dynamics(lines)       -> list[str]   dynamic markings (p, mf, f, etc.)
  find_biographical(lines)   -> str         composer biographical notes
  parse_bottom(lines)        -> dict        all fields combined
"""

from __future__ import annotations
import re


# ---------------------------------------------------------------------------
# Section boundary detection
# ---------------------------------------------------------------------------

# Patterns that mark the start of a "notes and legend" section
_NOTES_START_RE = re.compile(
    r'^\s*(?:notes?\s+(?:and\s+)?(?:legend|explanation|tablature)'
    r'|tablature\s+(?:notes?|explanation|legend)'
    r'|legend\s*[:\-–]?'
    r'|explanation\s*[:\-–]?)',
    re.IGNORECASE
)

# Patterns that mark the start of a biographical section
_BIO_START_RE = re.compile(
    r'^\s*(?:about\s+the\s+(?:composer|artist|author)'
    r'|biography\b'
    r'|biographical\s+(?:notes?|information)'
    r'|composer\s+(?:notes?|biography|information)'
    r'|background\b)',
    re.IGNORECASE
)

# Standard dynamic markings (as whole words in the text)
_DYNAMIC_RE = re.compile(
    r'\b(pppp|ppp|pp|mp|mf|ff|fff|ffff|sfz?|fp|rfz?|cresc(?:endo)?|decresc(?:endo)?|dim(?:inuendo)?|crescendo|forte|piano)\b',
    re.IGNORECASE
)

# Dynamic direction words in context
_DYNAMIC_CONTEXT_RE = re.compile(
    r'(?:dynamics?|marking)[:\-–]?\s*(.+)',
    re.IGNORECASE
)


def _find_tab_end(lines: list[str]) -> int:
    """
    Find the line index where the tab body ends (last string line + a few lines).

    We scan from the bottom for the last group of string-like lines.
    Returns the index of the first non-tab line after the last system,
    or 0 if not determinable.
    """
    # Import here to avoid circular dependency
    from tab_parser import _STRING_LINE_RE

    last_string_line = 0
    for i, line in enumerate(lines):
        if _STRING_LINE_RE.match(line):
            last_string_line = i

    # After the last string line, skip a few finger-digit / blank lines
    end = last_string_line + 1
    while end < len(lines) and end < last_string_line + 5:
        stripped = lines[end].strip()
        if not stripped or re.match(r'^[\d\s]+$', stripped):
            end += 1
        else:
            break
    return end


# ---------------------------------------------------------------------------
# 1. Notes / legend
# ---------------------------------------------------------------------------

def find_notes_legend(lines: list[str]) -> str:
    """
    Find and return the notes / legend / tablature explanation section.

    Looks for a section header like "Notes and Legend", "Tablature Notes", etc.
    Returns the full text of that section (header included), or "" if not found.
    """
    for i, line in enumerate(lines):
        if _NOTES_START_RE.match(line.strip()):
            # Collect until we hit another major section header or EOF
            section_lines = [line]
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                if _BIO_START_RE.match(next_line.strip()):
                    break
                section_lines.append(next_line)
            return "\n".join(section_lines).strip()
    return ""


# ---------------------------------------------------------------------------
# 2. Dynamics
# ---------------------------------------------------------------------------

def find_dynamics(lines: list[str]) -> list[str]:
    """
    Find dynamic markings mentioned in the bottom text.

    Returns a deduplicated list of dynamic strings found (e.g. ["p", "mf", "f"]).
    Searches all lines but gives priority to anything after the tab body.
    """
    tab_end = _find_tab_end(lines)
    bottom_text = "\n".join(lines[tab_end:])

    # Also check full text for inline dynamics in performance notes
    full_text = "\n".join(lines)

    found: list[str] = []
    seen: set[str] = set()

    # Priority: explicit "dynamics: ..." lines anywhere
    for m in _DYNAMIC_CONTEXT_RE.finditer(full_text):
        val = m.group(1).strip()
        for dm in _DYNAMIC_RE.finditer(val):
            d = dm.group(1).lower()
            if d not in seen:
                found.append(d)
                seen.add(d)

    # General dynamic terms — search bottom section if available, else full text
    search_text = bottom_text if bottom_text.strip() else full_text
    for dm in _DYNAMIC_RE.finditer(search_text):
        d = dm.group(1).lower()
        if d not in seen:
            found.append(d)
            seen.add(d)

    return found


# ---------------------------------------------------------------------------
# 3. Biographical information
# ---------------------------------------------------------------------------

def find_biographical(lines: list[str]) -> str:
    """
    Find biographical information about the composer or artist.

    Returns the text of the biographical section, or "" if not found.
    """
    for i, line in enumerate(lines):
        if _BIO_START_RE.match(line.strip()):
            section_lines = [line]
            for j in range(i + 1, len(lines)):
                section_lines.append(lines[j])
            return "\n".join(section_lines).strip()

    # Fallback: look for a paragraph that mentions the composer's name
    # surrounded by years/dates  (heuristic — used in many classtab footers)
    bio_paras: list[str] = []
    tab_end = _find_tab_end(lines)
    para: list[str] = []

    for line in lines[tab_end:]:
        stripped = line.strip()
        if not stripped:
            if para:
                text = " ".join(para)
                # A paragraph with a birth/death year looks biographical
                if re.search(r'\b1[5-9]\d{2}\b', text) and len(text) > 60:
                    bio_paras.append(text)
                para = []
        else:
            para.append(stripped)

    if para:
        text = " ".join(para)
        if re.search(r'\b1[5-9]\d{2}\b', text) and len(text) > 60:
            bio_paras.append(text)

    return "\n\n".join(bio_paras)


# ---------------------------------------------------------------------------
# 4. Combined entry point
# ---------------------------------------------------------------------------

def parse_bottom(lines: list[str]) -> dict:
    """
    Parse the full bottom matter of a classtab file.

    Returns a dict with keys:
        notes_text    : str         tablature explanation / legend
        dynamics      : list[str]   dynamic markings found
        biographical  : str         composer biographical text
    """
    return {
        'notes_text':   find_notes_legend(lines),
        'dynamics':     find_dynamics(lines),
        'biographical': find_biographical(lines),
    }
