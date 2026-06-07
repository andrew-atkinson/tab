"""
generate_site.py
================
Build a static AlphaTab website from a folder of annotated MusicXML files.

Output layout:
  <site_dir>/
    index.html          — searchable list of all pieces
    pieces/<name>.html  — one page per piece
    musicxml/<name>.xml — MusicXML files (copied here)
"""

from __future__ import annotations
import re
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET


def _read_title_composer(xml_path: str) -> tuple[str, str, str]:
    """Quick parse of title, subtitle and composer from a MusicXML file.

    Returns (title, subtitle, composer).

    When the file has <work><work-title> the title is the collection name and
    <movement-title> holds the subtitle/movement name.  When there is no
    <work-title> the full title lives in <movement-title> and subtitle is ''.
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        work_title     = root.findtext('.//work/work-title') or ''
        movement_title = root.findtext('movement-title')     or ''
        if work_title:
            title    = work_title.strip()
            subtitle = movement_title.strip()
        else:
            title    = (movement_title or Path(xml_path).stem).strip()
            subtitle = ''
        composer = ''
        for cr in root.findall('.//creator'):
            if cr.get('type') == 'composer':
                composer = cr.text or ''
                break
        return title, subtitle, composer.strip()
    except Exception:
        return Path(xml_path).stem, '', ''


# ---------------------------------------------------------------------------
# Per-piece HTML page
# MusicXML is embedded inline so the page works without a web server
# (file:// protocol blocks fetch(), so we can't load external XML files).
# ---------------------------------------------------------------------------

_PIECE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: system-ui, sans-serif; background: #fafafa; color: #222; }}
    header {{
      background: #1a1a2e; color: #eee;
      padding: 1rem 1.5rem;
      display: flex; align-items: baseline; gap: 1rem;
    }}
    header h1 {{ margin: 0; font-size: 1.25rem; }}
    header p  {{ margin: 0; font-size: 0.85rem; opacity: 0.75; }}
    header .subtitle {{ font-style: italic; opacity: 0.85; }}
    header .subtitle:empty {{ display: none; }}
    nav a {{ color: #a0c4ff; text-decoration: none; font-size: 0.85rem; }}
    #controls {{
      display: flex; gap: 0.5rem;
      padding: 0.75rem 1.5rem;
      background: #fff; border-bottom: 1px solid #ddd;
      flex-wrap: wrap; align-items: center;
    }}
    button {{
      padding: 0.4rem 0.9rem; border: 1px solid #ccc;
      border-radius: 4px; background: #fff; cursor: pointer; font-size: 0.9rem;
    }}
    button:hover {{ background: #f0f0f0; }}
    button.active {{ background: #1a1a2e; color: #fff; border-color: #1a1a2e; }}
    #speed-label {{ font-size: 0.85rem; color: #555; }}
    #score-container {{ padding: 1rem; }}
    #alphaTab {{ background: #fff; box-shadow: 0 1px 6px rgba(0,0,0,0.1); border-radius: 4px; min-height: 200px; }}
    #status {{ padding: 1rem 1.5rem; color: #888; font-style: italic; }}
  </style>
</head>
<body>
<header>
  <nav><a href="../index.html">← All pieces</a></nav>
  <div>
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
  </div>
  <p>{composer}</p>
</header>

<div id="controls">
  <button id="btn-play">▶ Play</button>
  <button id="btn-stop">■ Stop</button>
  <button id="btn-loop">⟲ Loop</button>
  <label id="speed-label">
    Speed: <input id="speed-slider" type="range" min="25" max="200" value="100" step="5"
                  style="vertical-align:middle;width:100px">
    <span id="speed-val">100%</span>
  </label>
  <button id="btn-tab" class="active">Tab</button>
  <button id="btn-score">Score</button>
  <button id="btn-both">Both</button>
</div>

<div id="status">Loading…</div>
<div id="score-container">
  <div id="alphaTab"></div>
</div>

<!-- MusicXML stored as inert plain text — safe in file:// without a server -->
<script id="musicxml-data" type="text/plain">
{xml_content}
</script>

<script type="module">
const CDN = 'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/';
import * as alphaTab from 'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/alphaTab.min.mjs';

const el  = document.getElementById('alphaTab');

// Wrap the embedded XML in a Blob and create an object URL.
// AlphaTab's normal file-loading path (fetch) works with blob: URLs
// even when the page is opened from file://.
const xmlText  = document.getElementById('musicxml-data').textContent;
const blob     = new Blob([xmlText], {{ type: 'application/vnd.recordare.musicxml+xml' }});
const blobUrl  = URL.createObjectURL(blob);

const api = new alphaTab.AlphaTabApi(el, {{
  core: {{
    scriptFile:    CDN + 'alphaTab.min.mjs',
    fontDirectory: CDN + 'font/'
  }},
  display: {{
    staveProfile: 'TabMixed'
  }},
  player: {{
    enablePlayer: true,
    soundFont: CDN + 'soundfont/sonivox.sf2'
  }}
}});

api.load(blobUrl);

// Status updates
api.scoreLoaded.on(score => {{
  document.getElementById('status').textContent =
    (score.title || '') + (score.artist ? ' — ' + score.artist : '');
}});
api.renderFinished.on(() => {{
  document.getElementById('status').style.display = 'none';
  URL.revokeObjectURL(blobUrl);
}});
api.error.on(e => {{
  const msg = (typeof e === 'string') ? e : (e.message || JSON.stringify(e));
  document.getElementById('status').textContent = 'AlphaTab error: ' + msg;
  document.getElementById('status').style.color = '#c00';
  console.error('AlphaTab error:', e);
}});

// Controls
document.getElementById('btn-play').addEventListener('click', () => api.playPause());
document.getElementById('btn-stop').addEventListener('click', () => api.stop());

const btnLoop = document.getElementById('btn-loop');
btnLoop.addEventListener('click', () => {{
  api.isLooping = !api.isLooping;
  btnLoop.classList.toggle('active', api.isLooping);
}});

const slider = document.getElementById('speed-slider');
slider.addEventListener('input', () => {{
  const pct = parseInt(slider.value, 10);
  document.getElementById('speed-val').textContent = pct + '%';
  api.playbackSpeed = pct / 100;
}});

const staveProfiles = {{ 'btn-tab': 'Tab', 'btn-score': 'Score', 'btn-both': 'TabMixed' }};
for (const [id, profile] of Object.entries(staveProfiles)) {{
  document.getElementById(id).addEventListener('click', () => {{
    for (const bid of Object.keys(staveProfiles))
      document.getElementById(bid).classList.remove('active');
    document.getElementById(id).classList.add('active');
    api.settings.display.staveProfile = alphaTab.StaveProfile[profile];
    api.updateSettings();
    api.render();
  }});
}}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Classical Guitar Tab Library</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, sans-serif;
      background: #fafafa;
      color: #222;
    }}
    header {{
      background: #1a1a2e;
      color: #eee;
      padding: 1.25rem 1.5rem;
    }}
    header h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
    header p  {{ margin: 0; font-size: 0.9rem; opacity: 0.7; }}
    #search-bar {{
      padding: 0.75rem 1.5rem;
      background: #fff;
      border-bottom: 1px solid #ddd;
    }}
    #search {{
      width: 100%;
      max-width: 500px;
      padding: 0.5rem 0.75rem;
      font-size: 1rem;
      border: 1px solid #ccc;
      border-radius: 4px;
    }}
    #count {{ font-size: 0.85rem; color: #777; margin-top: 0.4rem; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th {{
      text-align: left;
      padding: 0.6rem 1.5rem;
      background: #f0f0f0;
      border-bottom: 2px solid #ddd;
      cursor: pointer;
      user-select: none;
    }}
    th:hover {{ background: #e4e4e4; }}
    td {{
      padding: 0.5rem 1.5rem;
      border-bottom: 1px solid #eee;
    }}
    tr:hover td {{ background: #f5f5f5; }}
    a {{ color: #1a1a2e; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .subtitle {{ font-size: 0.8rem; color: #777; font-style: italic; display: block; }}
    .hidden {{ display: none; }}
  </style>
</head>
<body>
<header>
  <h1>Classical Guitar Tab Library</h1>
  <p>{count} pieces</p>
</header>
<div id="search-bar">
  <input id="search" type="search" placeholder="Search by title or composer…" autofocus>
  <div id="count"></div>
</div>
<table>
  <thead>
    <tr>
      <th data-col="0">Title ▲</th>
      <th data-col="1">Composer</th>
    </tr>
  </thead>
  <tbody id="tbody">
{rows}
  </tbody>
</table>
<script>
const rows = Array.from(document.querySelectorAll('#tbody tr'));
const search = document.getElementById('search');
const countEl = document.getElementById('count');

function update() {{
  const q = search.value.toLowerCase();
  let visible = 0;
  rows.forEach(r => {{
    const match = !q || r.textContent.toLowerCase().includes(q);
    r.classList.toggle('hidden', !match);
    if (match) visible++;
  }});
  countEl.textContent = q ? `${{visible}} of ${{rows.length}} pieces` : '';
}}
search.addEventListener('input', update);

// Sorting
let sortCol = 0, sortAsc = true;
document.querySelectorAll('th[data-col]').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = parseInt(th.dataset.col);
    if (sortCol === col) sortAsc = !sortAsc;
    else {{ sortCol = col; sortAsc = true; }}
    const tbody = document.getElementById('tbody');
    rows.sort((a, b) => {{
      const av = a.cells[col].textContent.trim();
      const bv = b.cells[col].textContent.trim();
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    rows.forEach(r => tbody.appendChild(r));
    document.querySelectorAll('th[data-col]').forEach(h => {{
      const c = parseInt(h.dataset.col);
      h.textContent = h.textContent.replace(/[ ▲▼]$/, '');
      if (c === sortCol) h.textContent += sortAsc ? ' ▲' : ' ▼';
    }});
  }});
}});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_site(xml_dir: str, site_dir: str) -> None:
    """
    Build the static site from *xml_dir* (annotated MusicXML files) into *site_dir*.
    """
    xml_dir  = Path(xml_dir)
    site_dir = Path(site_dir)

    pieces_dir  = site_dir / 'pieces'
    mx_dest_dir = site_dir / 'musicxml'
    pieces_dir.mkdir(parents=True, exist_ok=True)
    mx_dest_dir.mkdir(parents=True, exist_ok=True)

    # Only pick up clean *.xml files — exclude any *.tmp.xml or *.foo.xml artifacts
    xml_files = sorted(f for f in xml_dir.glob('*.xml') if f.suffix == '.xml' and f.stem.endswith('.xml') is False and '.' not in f.stem)
    pieces = []  # (title, subtitle, composer, stem, filename)

    for xml_path in xml_files:
        stem     = xml_path.stem
        filename = xml_path.name
        title, subtitle, composer = _read_title_composer(str(xml_path))

        # Copy XML to site/musicxml/ (kept for reference / server-based use)
        dest_xml = mx_dest_dir / filename
        shutil.copy2(str(xml_path), str(dest_xml))

        # Read and embed the MusicXML inline.
        # Use <script type="text/plain"> so the browser never executes or parses it.
        # Keep the <?xml …?> declaration — AlphaTab uses it to detect MusicXML format.
        # Strip DOCTYPE only (it would cause the XML parser to try fetching the DTD).
        xml_content = xml_path.read_text(encoding='utf-8')
        xml_content = re.sub(r'<!DOCTYPE[^>]*>\s*', '', xml_content)

        # Generate piece HTML (xml_content goes verbatim inside <script type="application/xml">)
        html = _PIECE_TEMPLATE.format(
            title=_esc(title),
            subtitle=_esc(subtitle),
            composer=_esc(composer),
            filename=_esc(filename),
            xml_content=xml_content,
        )
        piece_html_path = pieces_dir / f'{stem}.html'
        piece_html_path.write_text(html, encoding='utf-8')

        pieces.append((title, subtitle, composer, stem, filename))

    # Generate index — subtitle shown as a secondary line within the title cell
    def _row(title, subtitle, composer, stem):
        subtitle_html = (
            f'<span class="subtitle">{_esc(subtitle)}</span>' if subtitle else ''
        )
        return (
            f'    <tr><td><a href="pieces/{_esc(stem)}.html">{_esc(title)}</a>'
            f'{subtitle_html}</td>'
            f'<td>{_esc(composer)}</td></tr>'
        )

    rows_html = '\n'.join(
        _row(title, subtitle, composer, stem)
        for (title, subtitle, composer, stem, _)
        in sorted(pieces, key=lambda x: x[0].lower())
    )
    index_html = _INDEX_TEMPLATE.format(count=len(pieces), rows=rows_html)
    (site_dir / 'index.html').write_text(index_html, encoding='utf-8')

    print(f"Site generated: {len(pieces)} pieces → {site_dir}")


def _esc(s: str) -> str:
    """HTML-escape a string."""
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;'))
