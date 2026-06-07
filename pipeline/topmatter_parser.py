"""
topmatter_parser.py
===================
Functions for parsing the header / top-matter section of classtab ASCII tabs.

The "top matter" is everything before the first tab system: title, composer,
transcriber, tuning declarations, and any chord diagrams or fingerings.

Public API
----------
  find_tuning(lines)               -> str        e.g. "EADGBE"
  find_composer_author_title(lines)-> dict        keys: title, composer, composer_dates
  find_transcriber(lines)          -> str
  find_chords_fingering(lines)     -> list[dict]  chord shapes with fingering
  parse_topmatter(lines)           -> dict        all fields combined
"""

from __future__ import annotations
import re


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SEP_RE = re.compile(
    r'^[\s#*=\-_|]{5,}$'
    r'|^\s*#\s*[-=*]{5,}'
    r'|^\s*#+\s*PLEASE\s+NOTE'
    r'|^\s*#+\s*This\s+file\s+is',
    re.IGNORECASE
)

def _is_separator(line: str) -> bool:
    return bool(_SEP_RE.match(line))


def _clean_value(s: str) -> str:
    """Strip surrounding *, #, -, _, whitespace from a string."""
    return s.strip().strip('*#-_ \t').strip()


_SKIP_LINE_RE = re.compile(
    r'^last\s+updated'
    r'|^this\s+(is|file|tab)'
    r'|^note\s*:'
    r'|^\s*\d+\s+\w+\s+\d{4}'   # "30 December 2023"
    r'|^from\s*:'
    r'|^date\s*:'
    r'|^to\s*:'
    r'|^vid\s*:'                  # YouTube video links
    r'|^http',
    re.IGNORECASE
)

_URL_LINE_RE = re.compile(r'https?://', re.IGNORECASE)

# Number of lines at the top of a file to scan for metadata
_HEADER_LINES = 60


def _header(lines: list[str]) -> str:
    """Join the first _HEADER_LINES lines for regex searching."""
    return "\n".join(lines[:_HEADER_LINES])


# ---------------------------------------------------------------------------
# 1. Tuning
# ---------------------------------------------------------------------------

_TUNING_RE = re.compile(
    r'tuning\s*[:\-–]\s*'
    r'([A-Ga-g][#b]?\s*[A-Ga-g][#b]?\s*[A-Ga-g][#b]?\s*'
    r'[A-Ga-g][#b]?\s*[A-Ga-g][#b]?\s*[A-Ga-g][#b]?)',
    re.IGNORECASE
)
_TUNE_6_RE = re.compile(
    r'tune\s+(?:the\s+)?(?:6(?:th)?|sixth)\s+string\s+to\s+([A-Ga-g][#b]?)',
    re.IGNORECASE
)
_TUNE_1_RE = re.compile(
    r'tune\s+(?:the\s+)?(?:1(?:st)?|first)\s+string\s+to\s+([A-Ga-g][#b]?)',
    re.IGNORECASE
)
_DROP_D_RE = re.compile(r'drop[\s-]*d\b', re.IGNORECASE)
_OPEN_G_RE = re.compile(r'open[\s-]*g\b', re.IGNORECASE)
_OPEN_D_RE = re.compile(r'open[\s-]*d\b', re.IGNORECASE)
_DADGAD_RE = re.compile(r'dadgad', re.IGNORECASE)

_STD_TUNING = "EADGBE"

# Known named tunings (low → high)
_NAMED_TUNINGS: dict[str, str] = {
    "drop d":  "DADGBE",
    "drop-d":  "DADGBE",
    "open g":  "DGDGBD",
    "open d":  "DADF#AD",
    "dadgad":  "DADGAD",
}


def find_tuning(lines: list[str]) -> str:
    """
    Extract the guitar tuning from the header section.

    Returns a 6-character string (low→high), e.g. "EADGBE" or "DADGBE".
    Falls back to standard tuning if nothing is found.
    """
    header = _header(lines)
    tuning = _STD_TUNING

    # Check named tunings first
    for name, t in _NAMED_TUNINGS.items():
        if re.search(re.escape(name), header, re.IGNORECASE):
            tuning = t
            break

    # Explicit "tuning: E A D G B E" or "tuning: EADGBE"
    m = _TUNING_RE.search(header)
    if m:
        tuning = re.sub(r'\s+', '', m.group(1)).upper()

    # Modify individual strings
    t_list = list(tuning)
    if len(t_list) == 6:
        m6 = _TUNE_6_RE.search(header)
        if m6:
            t_list[5] = m6.group(1).upper()
        m1 = _TUNE_1_RE.search(header)
        if m1:
            t_list[0] = m1.group(1).upper()
        tuning = ''.join(t_list)

    return tuning


# ---------------------------------------------------------------------------
# 2. Composer, Author, Title
# ---------------------------------------------------------------------------

_COMPOSER_SPLIT_RE = re.compile(r'^(.+?)\s+-\s+(.+?)(?:\s+\((\d{4}[^\)]*)\))?\s*$')

# Subtitle helpers ───────────────────────────────────────────────────────────
# A segment that starts with a digit or "No. N" is a movement indicator, not a
# composer name (e.g. "3. Danza de las Hachas", "No. 11 in Am").
_MOVEMENT_PREFIX_RE = re.compile(r'^\d+[\.:]|^No\.?\s*\d', re.IGNORECASE)


def _split_subtitle_from_composer(raw_composer: str) -> tuple[str, str]:
    """
    If *raw_composer* is actually 'Subtitle - Composer', separate the two.

    Returns (subtitle, actual_composer).  If the last ' - ' segment doesn't
    look like a composer name, returns ('', raw_composer) unchanged.
    """
    if ' - ' not in raw_composer:
        return '', raw_composer

    parts = [p.strip() for p in raw_composer.split(' - ')]
    last  = parts[-1]

    # Reject if the last segment looks like a movement label
    if _MOVEMENT_PREFIX_RE.match(last):
        return '', raw_composer

    # Accept if it looks like a proper name (capitalised, no leading digit)
    if re.match(r'^[A-Z][a-z]', last) and len(last) < 60:
        subtitle = ' - '.join(parts[:-1])
        return subtitle, last

    return '', raw_composer


_AUTHOR_RE = re.compile(
    r'(?:author|by|composer|arranged?\s+by)\s*[:\-–]?\s*(.+)',
    re.IGNORECASE
)
_TITLE_RE  = re.compile(r'(?:title|song|piece)\s*[:\-–]\s*(.+)', re.IGNORECASE)
_SUBJECT_RE = re.compile(r'^subject\s*:\s*(?:tab|cg|re)[\s:]*(.+)', re.IGNORECASE)
_SUBJECT_BY_RE = re.compile(r'^(?:tab[:\s]+)?(.+?)\s*[;,]\s*(?:cg\s+)?by\s+(.+)', re.IGNORECASE)
_SPACED_COMPOSER_RE = re.compile(r'^(.+?)\s{4,}(.+)$')


def find_composer_author_title(lines: list[str]) -> dict:
    """
    Extract title, subtitle, composer, and composer_dates from the header.

    Returns a dict with keys: 'title', 'subtitle', 'composer', 'composer_dates'.

    Three-segment title lines of the form "Collection - Movement - Composer (dates)"
    are split so that the middle segment becomes the subtitle rather than being
    absorbed into the composer field.
    """
    title = ""
    subtitle = ""
    composer = ""
    composer_dates = ""

    # ── Step 1: Subject: line ───────────────────────────────────────────────
    for raw in lines[:20]:
        sm = _SUBJECT_RE.match(raw.strip())
        if sm:
            subj = sm.group(1).strip()
            bym  = _SUBJECT_BY_RE.match(subj)
            if bym:
                title    = _clean_value(bym.group(1))
                composer = _clean_value(bym.group(2))
            else:
                title = _clean_value(subj)
            break

    # ── Step 2: Scan first N lines for title ────────────────────────────────
    if not title:
        for raw in lines[:_HEADER_LINES]:
            line = raw.strip()
            if not line or _is_separator(line):
                continue
            if _SKIP_LINE_RE.match(line) or _URL_LINE_RE.search(line):
                continue

            # Explicit "Title:" label
            tm = _TITLE_RE.match(line)
            if tm:
                title = _clean_value(tm.group(1))
                break

            # Skip very long prose lines
            if len(line) > 90:
                continue

            # "Title - Composer (dates)"  or  "Title - Subtitle - Composer (dates)"
            m = _COMPOSER_SPLIT_RE.match(_clean_value(line))
            if m:
                title          = _clean_value(m.group(1)).strip('"\'')
                raw_composer   = _clean_value(m.group(2))
                composer_dates = m.group(3) or ""
                # Separate subtitle from composer when the "composer" field
                # still contains ' - ' (three-segment title line).
                subtitle, composer = _split_subtitle_from_composer(raw_composer)
                break

            # "Title          Composer" (4+ spaces separator)
            sm2 = _SPACED_COMPOSER_RE.match(line)
            if sm2:
                cand_title    = _clean_value(sm2.group(1))
                cand_composer = _clean_value(sm2.group(2))
                if cand_title and cand_composer and cand_title[0].isupper():
                    title    = cand_title.strip('"\'')
                    if not composer:
                        composer = cand_composer
                    break

            # Quoted title: "Foo Bar"
            if line.startswith('"') and line.endswith('"'):
                title = line.strip('"')
                break

            # Short capitalized line → probable title
            if len(line) < 80 and line[0].isupper() and not _SKIP_LINE_RE.match(line):
                title = _clean_value(line).strip('"\'')
                break

    # ── Step 3: Find composer if not yet found ──────────────────────────────
    if not composer:
        header = _header(lines)
        am = _AUTHOR_RE.search(header)
        if am:
            val = _clean_value(am.group(1))
            dm  = re.search(r'\((\d{4}[^\)]*)\)', val)
            if dm:
                composer_dates = dm.group(1)
                val = val[:dm.start()].strip()
            composer = val

    return {
        'title':          title,
        'subtitle':       subtitle,
        'composer':       composer,
        'composer_dates': composer_dates,
    }


# ---------------------------------------------------------------------------
# 3. Transcriber
# ---------------------------------------------------------------------------

_TRANSCRIBER_RE = re.compile(
    r'(?:'
    r'tabbed?\s+by'
    r'|transcribed?\s+by'
    r'|tab(?:ulation)?\s+by'
    r'|arranged?\s+by'
    r'|edited?\s+by'
    r'|notation\s+by'
    r')\s*[:\-–]?\s*(.+)',
    re.IGNORECASE
)

# Lines that look like "tabbed by <Name> - <date> - <email>"
_TABBED_BY_INLINE_RE = re.compile(
    r'tabbed?\s+by\s+([^-\n]+?)(?:\s*[-–]\s*(?:\w+\s+\d{2,4}|$))',
    re.IGNORECASE
)


def find_transcriber(lines: list[str]) -> str:
    """
    Find who tabbed / transcribed / arranged the piece.

    Returns a string (name only, without dates or email), or "" if not found.
    """
    header = _header(lines)

    m = _TRANSCRIBER_RE.search(header)
    if not m:
        return ""

    val = m.group(1).strip()

    # Strip trailing date, email, or comment after ' - '
    val = re.split(r'\s*[-–]\s*(?:\w+\s+\d{2,4}|\w+@\w+)', val)[0].strip()
    # Strip trailing email
    val = re.sub(r'\s+\S+@\S+', '', val).strip()
    # Strip trailing year in parens
    val = re.sub(r'\s*\(\d{4}\)', '', val).strip()

    return _clean_value(val)


# ---------------------------------------------------------------------------
# 4. Chords and Fingering
# ---------------------------------------------------------------------------

# Chord box patterns in classtab:
#   e|---  (standard string line used in a chord diagram)
#   A chord diagram is a compact 4-5 line block with fret numbers and an
#   optional chord name above it.
#
# Many classtab files also have barre annotations (CII, cIV) — these are
# captured by the tab parser as BarreMarker objects.  Here we look for
# explicitly named chord diagrams in the header.

_CHORD_NAME_RE = re.compile(
    r'^([A-G][#b]?(?:m|maj|min|dim|aug|sus|add|dom)?\d*(?:/[A-G][#b]?)?)\s*[:\-–]?\s*$',
    re.IGNORECASE
)
# A chord-box string line: short (≤ 10 chars), digits 0-9, dashes, pipes, x/o
_CHORD_STRING_RE = re.compile(r'^[xo0-9\-|]{3,10}$')

# Fingering row: digits 1-4 and spaces/dashes only, short
_CHORD_FINGER_RE = re.compile(r'^[1-4\s\-]{2,8}$')


def find_chords_fingering(lines: list[str]) -> list[dict]:
    """
    Find named chord diagrams with fingering in the header.

    Each entry is a dict:
        {
          'name':       str,          e.g. "Am"
          'strings':    list[str],    6 entries, low→high, each "0"/"x"/"<fret>"
          'fingering':  list[int],    finger numbers (0 = open/muted)
          'barre_fret': int | None,   capo/barre fret if detected
        }

    In standard classtab files these explicit chord boxes are rare; the
    function returns an empty list for most files.
    """
    chords: list[dict] = []
    i = 0
    limit = min(len(lines), _HEADER_LINES)

    while i < limit:
        line = lines[i].strip()

        # Look for a chord name line followed by a string pattern
        nm = _CHORD_NAME_RE.match(line)
        if nm:
            chord_name = nm.group(1)
            # Collect up to 6 string lines below
            string_lines: list[str] = []
            finger_line: str = ""
            j = i + 1
            while j < limit and len(string_lines) < 6:
                sl = lines[j].strip()
                if _CHORD_STRING_RE.match(sl):
                    string_lines.append(sl)
                    j += 1
                else:
                    break
            if len(string_lines) >= 4:
                # Optional fingering line
                if j < limit and _CHORD_FINGER_RE.match(lines[j].strip()):
                    finger_line = lines[j].strip()
                    j += 1

                fingering = [int(d) for d in re.findall(r'[1-4]', finger_line)] if finger_line else []
                chords.append({
                    'name':       chord_name,
                    'strings':    string_lines,
                    'fingering':  fingering,
                    'barre_fret': None,
                })
                i = j
                continue

        i += 1

    return chords


# ---------------------------------------------------------------------------
# 5. Combined entry point
# ---------------------------------------------------------------------------

_KEY_RE   = re.compile(r'key(?:\s*sig(?:nature)?)?\s*[:\-–]?\s+([^\n,\t\d]{1,20}?)(?:\s{2,}|\t|\n|$)', re.IGNORECASE | re.MULTILINE)
_TIME_RE  = re.compile(r'time(?:\s*sig(?:nature)?)?\s*(?:is\s*|[:\-–]\s*)?(\d+/\d+)', re.IGNORECASE | re.MULTILINE)
_TEMPO_RE = re.compile(r'tempo\s*[:\-–]?\s+(\d+)\s*(?:bpm)?(?:\s*[-–]\s*(\d+)\s*(?:bpm)?)?(?:\s*\(([^)]+)\))?', re.IGNORECASE | re.MULTILINE)
_CAPO_RE  = re.compile(r'capo\s*[:\-–]?\s*(\d+)', re.IGNORECASE)


def parse_topmatter(lines: list[str]) -> dict:
    """
    Parse the full top-matter of a classtab file.

    Returns a dict with keys:
        title, composer, composer_dates, transcriber,
        tuning, key, time_sig, tempo, tempo_unit, capo,
        chords
    """
    cat = find_composer_author_title(lines)
    header = _header(lines)

    # Tempo: handle range "120-132" — take lower bound
    tempo = 0
    tempo_unit = "quarter"
    m = _TEMPO_RE.search(header)
    if m:
        tempo = int(m.group(1))
        tempo_unit = m.group(3) or "quarter"

    capo = 0
    m = _CAPO_RE.search(header)
    if m:
        capo = int(m.group(1))

    key = ""
    m = _KEY_RE.search(header)
    if m:
        key = m.group(1).strip()

    time_sig = ""
    m = _TIME_RE.search(header)
    if m:
        time_sig = m.group(1)

    return {
        'title':          cat['title'],
        'subtitle':       cat['subtitle'],
        'composer':       cat['composer'],
        'composer_dates': cat['composer_dates'],
        'transcriber':    find_transcriber(lines),
        'tuning':         find_tuning(lines),
        'key':            key,
        'time_sig':       time_sig,
        'tempo':          tempo,
        'tempo_unit':     tempo_unit,
        'capo':           capo,
        'chords':         find_chords_fingering(lines),
    }
