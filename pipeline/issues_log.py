"""
issues_log.py
=============
Append structured issue entries to a date-stamped JSONL log file under
output/logs/.

Each entry records:
  timestamp   ISO-8601 datetime of the log call
  stem        filename stem (no extension), e.g. "villa-lobos_choros_01"
  title       human-readable piece title
  composer    composer name
  bar_number  measure number in the .txt tab file (None if not bar-specific)
  issue_type  short machine-readable tag, e.g. "bar_count_mismatch",
              "duplicate_string_in_beat", "pitch_fallback_excess"
  details     free-text description of the problem

Format: one JSON object per line (JSONL) — easy to stream, grep, or load
into pandas.  Each pipeline run appends to today's file; older files are
preserved.

Usage::

    from issues_log import log_issue

    log_issue(
        stem='villa-lobos_choros_01',
        title='Choro No.1',
        composer='Heitor Villa-Lobos',
        bar_number=None,
        issue_type='bar_count_mismatch',
        details='MIDI has 190 measures but tab has 135 (55 extra, likely repeats expanded).',
    )
"""

from __future__ import annotations
import json
import datetime
from pathlib import Path

# Default log directory: output/logs/ relative to the repository root.
# The pipeline root is one directory above this file.
_REPO_ROOT = Path(__file__).parent.parent
_LOG_DIR   = _REPO_ROOT / 'output' / 'logs'


def log_issue(
    stem:       str,
    title:      str,
    composer:   str,
    bar_number: int | None,
    issue_type: str,
    details:    str,
    *,
    log_dir: Path | None = None,
) -> dict:
    """
    Append one issue entry to the current day's JSONL log and return the
    entry as a dict.

    Parameters
    ----------
    stem        : filename stem without extension
    title       : piece title
    composer    : composer name
    bar_number  : 1-based measure number from the .txt file, or None
    issue_type  : short tag:
                    'bar_count_mismatch'      MIDI measure count ≠ tab count
                    'duplicate_string_in_beat' two matched notes on same string
                    'pitch_fallback_excess'   too many notes fell to fallback
    details     : human-readable explanation
    log_dir     : override the output directory (used in tests)
    """
    base = log_dir or _LOG_DIR
    base.mkdir(parents=True, exist_ok=True)

    today    = datetime.date.today().isoformat()
    log_path = base / f'{today}_issues.jsonl'

    entry = {
        'timestamp':  datetime.datetime.now().isoformat(timespec='seconds'),
        'stem':       stem,
        'title':      title,
        'composer':   composer,
        'bar_number': bar_number,
        'issue_type': issue_type,
        'details':    details,
    }

    with open(log_path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + '\n')

    return entry


def read_log(date: str | None = None, *, log_dir: Path | None = None) -> list[dict]:
    """
    Return all entries for *date* (YYYY-MM-DD, default = today) as a list.
    Returns an empty list if the file does not exist.
    """
    base = log_dir or _LOG_DIR
    if date is None:
        date = datetime.date.today().isoformat()
    log_path = base / f'{date}_issues.jsonl'
    if not log_path.exists():
        return []
    entries = []
    with open(log_path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def summarise(entries: list[dict]) -> str:
    """Return a short human-readable summary of a list of log entries."""
    if not entries:
        return 'No issues logged.'
    by_type: dict[str, int] = {}
    for e in entries:
        by_type[e['issue_type']] = by_type.get(e['issue_type'], 0) + 1
    lines = [f'{len(entries)} issue(s) logged:']
    for issue_type, count in sorted(by_type.items()):
        lines.append(f'  {issue_type}: {count}')
    return '\n'.join(lines)
