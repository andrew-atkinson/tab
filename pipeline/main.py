"""
main.py
=======
Orchestrator for the classtab → annotated MusicXML → static site pipeline.

Usage:
  python main.py [options]

Options:
  --input   DIR|FILE  Folder of .mid/.txt pairs, or a single file  [../tab]
  --output  DIR       Output root folder                            [../output]
  --jobs    N         Parallel worker processes                     [4]
  --limit   N         Process at most N files (alphabetical order)  [all]
  --pieces            Process only the validated reference pieces
                      defined in test_pipeline.PIECES
  --site-only         Skip conversion; regenerate site from existing XML
  --no-site           Skip site generation (conversion only)
  --force             Reprocess files even if output XML exists

Output layout:
  <output>/
    musicxml/    annotated .xml files (one per paired midi+txt)
    site/        static AlphaTab website
"""

from __future__ import annotations
import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Suppress the harmless RequestsDependencyWarning from music21's requests import
import warnings
warnings.filterwarnings('ignore', message='.*urllib3.*', category=Warning)
warnings.filterwarnings('ignore', message='.*chardet.*', category=Warning)
warnings.filterwarnings('ignore', message='.*charset_normalizer.*', category=Warning)

# Make sure local modules are importable regardless of cwd
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))


# ---------------------------------------------------------------------------
# Single-file worker (runs in a subprocess)
# ---------------------------------------------------------------------------

def _process_one(args: tuple) -> tuple[str, bool, str]:
    """
    Worker function.  Returns (stem, success, message).
    Importing here so the worker process doesn't re-import unnecessarily.

    Pipeline (tab-primary architecture):
      txt  → parse()          → TabFile
      tab  → expand_repeats() → ExpandedScore
      mid  → extract_timing() → TimingMap
      (expanded, timing) → build_musicxml() → ET.Element
      root → write_musicxml() → out_xml_path
    """
    mid_path, txt_path, out_xml_path, force = args

    stem = Path(mid_path).stem

    # Skip if already done and not forcing
    if not force and Path(out_xml_path).exists():
        return stem, True, 'skipped (already exists)'

    try:
        import xml.etree.ElementTree as ET
        from parse_txt        import parse
        from repeat_expander  import expand_repeats
        from midi_timing      import extract_timing
        from score_builder    import build_musicxml, write_musicxml

        # 1. Parse the .txt tab (source of truth)
        tab = parse(txt_path)

        # 2. Expand repeats → performance order
        expanded = expand_repeats(tab)

        # 3. Extract beat-group timing from the MIDI (timing oracle only)
        timing = extract_timing(mid_path)

        # 4. Build annotated MusicXML from tab + timing
        root = build_musicxml(expanded, timing, stem=stem)

        # 5. Write to disk
        write_musicxml(root, out_xml_path)

        return stem, True, 'ok'

    except Exception as exc:
        tb = traceback.format_exc()
        return stem, False, f'{exc}\n{tb}'


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def find_pairs(input_path: Path) -> list[tuple[Path, Path]]:
    """
    Return all (.mid, .txt) pairs for *input_path*.

    *input_path* may be:
    • A directory  — every .mid file that has a matching .txt is included.
    • A single .txt or .mid file — returns that one pair (if the partner exists).
    """
    if input_path.is_file():
        # Single-file mode: derive the partner from the same stem
        if input_path.suffix == '.txt':
            txt, mid = input_path, input_path.with_suffix('.mid')
        elif input_path.suffix == '.mid':
            mid, txt = input_path, input_path.with_suffix('.txt')
        else:
            return []
        if txt.exists() and mid.exists():
            return [(mid, txt)]
        return []

    # Directory mode: scan for all paired files
    pairs = []
    for mid in sorted(input_path.glob('*.mid')):
        txt = mid.with_suffix('.txt')
        if txt.exists():
            pairs.append((mid, txt))
    return pairs


def find_reference_pairs(input_dir: Path) -> list[tuple[Path, Path]]:
    """
    Return the hand-picked reference pairs from test_pipeline.PIECES.
    These are the validated pieces used in the end-to-end test suite.
    """
    from test_pipeline import PIECES
    pairs = []
    for p in PIECES:
        mid = input_dir / p['mid']
        txt = input_dir / p['txt']
        if mid.exists() and txt.exists():
            pairs.append((mid, txt))
        else:
            print(f"  WARNING: reference piece not found — {p['name']} "
                  f"({p['mid']} / {p['txt']})")
    return pairs


def run(input_path: Path, output_dir: Path, jobs: int, limit: int | None,
        pieces: bool, site_only: bool, no_site: bool, force: bool) -> None:

    xml_dir  = output_dir / 'musicxml'
    site_dir = output_dir / 'site'
    xml_dir.mkdir(parents=True, exist_ok=True)

    if not site_only:
        if pieces:
            # Use the validated reference set from test_pipeline.PIECES.
            # --input must be (or contain) the tab directory in this mode.
            tab_dir = input_path if input_path.is_dir() else input_path.parent
            pairs = find_reference_pairs(tab_dir)
            print(f"Reference-piece mode: {len(pairs)} piece(s)")
        else:
            pairs = find_pairs(input_path)
            if not pairs:
                print(f"No paired .mid/.txt files found for {input_path}")
                sys.exit(1)
            if limit:
                pairs = pairs[:limit]
            print(f"Found {len(pairs)} pairs.  Processing with {jobs} workers…")

        worker_args = [
            (str(mid), str(txt), str(xml_dir / (mid.stem + '.xml')), force)
            for mid, txt in pairs
        ]

        ok_count = 0
        skip_count = 0
        fail_count = 0
        t0 = time.time()

        with ProcessPoolExecutor(max_workers=jobs) as executor:
            futures = {executor.submit(_process_one, a): a[0] for a in worker_args}
            done = 0
            for fut in as_completed(futures):
                done += 1
                stem, success, msg = fut.result()
                if not success:
                    fail_count += 1
                    print(f"  [FAIL] {stem}: {msg[:120]}")
                elif msg.startswith('skipped'):
                    skip_count += 1
                else:
                    ok_count += 1

                # Progress every 50 files
                if done % 50 == 0 or done == len(worker_args):
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed else 0
                    eta  = (len(worker_args) - done) / rate if rate else 0
                    print(f"  {done}/{len(worker_args)}  "
                          f"ok={ok_count} skipped={skip_count} fail={fail_count}  "
                          f"({rate:.1f}/s  ETA {eta:.0f}s)")

        print(f"\nConversion complete: {ok_count} converted, {skip_count} skipped, "
              f"{fail_count} failed in {time.time()-t0:.1f}s")

    if not no_site:
        print("\nGenerating static site…")
        from generate_site import generate_site
        generate_site(str(xml_dir), str(site_dir))
        print(f"Done.  Open {site_dir / 'index.html'} in your browser.")


def main() -> None:
    here    = Path(__file__).parent
    default_input  = here.parent / 'tab'
    default_output = here.parent / 'output'

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--input',     default=str(default_input),  metavar='DIR|FILE')
    p.add_argument('--output',    default=str(default_output), metavar='DIR')
    p.add_argument('--jobs',      type=int, default=4,         metavar='N')
    p.add_argument('--limit',     type=int, default=None,      metavar='N')
    p.add_argument('--pieces',    action='store_true',
                   help='Process only the reference pieces from test_pipeline.PIECES')
    p.add_argument('--site-only', action='store_true')
    p.add_argument('--no-site',   action='store_true')
    p.add_argument('--force',     action='store_true')
    args = p.parse_args()

    run(
        input_path = Path(args.input),
        output_dir = Path(args.output),
        jobs       = args.jobs,
        limit      = args.limit,
        pieces     = args.pieces,
        site_only  = args.site_only,
        no_site    = args.no_site,
        force      = args.force,
    )


if __name__ == '__main__':
    main()
