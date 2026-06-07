# Parser Format Reference

Complete reference for every notation format the classtab parser understands.
Covers `topmatter_parser.py`, `tab_parser.py`, and `repeat_expander.py`.

Each section links to a real corpus piece that demonstrates the format.

---

## Contents

1. [String line formats](#1-string-line-formats)
2. [Frets and notes](#2-frets-and-notes)
3. [Chords](#3-chords)
4. [Techniques](#4-techniques)
5. [Harmonics](#5-harmonics)
6. [Ties](#6-ties)
7. [Triplets](#7-triplets)
8. [Barlines and measure numbering](#8-barlines-and-measure-numbering)
9. [Repeats](#9-repeats)
10. [Volta brackets (1st/2nd endings)](#10-volta-brackets-1st2nd-endings)
11. [Barre markers](#11-barre-markers)
12. [Left-hand fingering](#12-left-hand-fingering)
13. [Right-hand fingering (pima)](#13-right-hand-fingering-pima)
14. [Header fields](#14-header-fields)
15. [Tuning variants](#15-tuning-variants)
16. [Priority rules](#16-priority-rules)

---

## 1. String line formats

The parser recognises six prefix styles. Identification is tried in this order
(first match wins):

| Code | Pattern | Example |
|------|---------|---------|
| A | `<letter>[#b][-] <pipe/colon>` | `E\|----5---3---` |
| A′ | Letter with accidental | `F#\|---0-------` |
| A″ | Lowercase letter | `b\|----3---1---` |
| B | `<letter>[#b] <dashes only>` | `E----5---3---` |
| C | `\|\|<digit or dash>` | `\|\|----5---3---` |
| D | `\|<digit or dash>` | `\|----5---3---` |
| E/F | `<dashes/digits>…<barline>` | `----5---3---\|` |

**Rules:**

- Formats A–D carry an explicit string-name prefix. That prefix is stripped before
  beat geometry is computed; it does not appear in any output field.
- A system must have **at least 4 consecutive string lines** to be recognised as
  a valid tab block. Exactly 6 is the normal case; 4–5 can occur in partial
  systems and are accepted.
- Lowercase string letters (format A″) are treated identically to uppercase.
- A colon `:` in the prefix position is treated as a pipe `|` (format A with
  repeat context — see §9).
- Mixed formats within a single system are accepted (e.g. line 1 is format A,
  line 2 is format D). The prefix of the **first** string line is used to
  compute `content_start` (the column where tab content begins).

**Examples:**

*Format A* — `weiss_sl_sw025_5_sonata_in_gm_5_menuet`:
```
e|----|-------3===1--|-------3===1--|
b|----|-3===1--------|-3===1--------|
```

*Format A′ (accidental in string name)* — `zamboni_op01_sonata_01_2_alemanda`
(lute in G, F# string):
```
E |-2-------0-------0===============|
B |-0=============4-4p------2-----0-|
F#|---------------------------------|
D |---------------------------------|
A |-----------------0===============|
E |-4===============----------------|
```

*Format B (letter + dashes, no pipe)* — `oginski_hej_sloveni`:
```
E-------------------------------------|--8--8-8-7-5--------------------|
```

*Format C (double pipe)* — `desportes_yvonne_modes_dantan_3_phrygien`:
```
e||--------------5---|-0-0-0-------|
B||----------5-----6-|-0---0-3---0-|
G||*-----5-----5-----|----------5--|
D||*-7-----7---------|-------------|
A||----7-------------|-0-----------|
E||--5---------------|-----4-------|
```

*Format D (single pipe, no letter)* — `scarlatti_d_k175`:
```
|----5-----6-|-0---0-3---0-|
```

*Format E/F (dashes first, barline embedded)* — `giuliani_op055_12_landler_03`
(the string lines begin with digits or dashes, barlines embedded):
```
--0---------------|------------------||
```

---

## 2. Frets and notes

### Single-digit frets
```
E|---0---3---5---
```
The digit(s) at a column position become a `NoteEvent` with `fret=N`.

### Two-digit frets

`koshkin_the_porcelain_tower_0_theme_by_stepan_rak`:
```
e|--9-------9---|--9-8-0=======|==========9///|//12---11--------11p8p0---|
```
`12` and `11` are parsed as two-digit frets. Consecutive digit characters are
consumed together. There is no upper bound; frets up to 24 are common in harmonics.

### Open string (fret 0)
```
e|---0-----------
```
`fret=0` is valid. `midi_pitch` equals the open-string MIDI pitch from the tuning.

### Muted / dead notes
Not encoded in classtab notation. Cells containing only dashes produce no `NoteEvent`.

---

## 3. Chords

Notes at the **same column** across different strings form a chord (a
simultaneous beat group). The parser assigns the same `col` value to all of
them. `get_beats()` groups by `col` and sorts by string number (1 = highest).

`lauro_two_venezuelan_waltzes_1_el_negrito` — the arpeggio piece has chords on
every beat, all six strings aligned to the same column:
```
e|---------------||--3=----------|-----------1-0-|
B|---------------||----------3---|-------1-3-----|
G|---------------||*-----0-----0-|-------2-------|
D|---------------||*---0---0-----|-----2---------|
A|---------------||--2=----------|---0=----------|
E|---------------||--------------|---------------|
```

---

## 4. Techniques

Technique characters appear **immediately after** the source fret digit(s).

| Character | `technique` value | Meaning |
|-----------|-------------------|---------|
| `/` | `slide_up` | Slide upward to destination |
| `\` | `slide_down` | Slide downward to destination |
| `h` | `hammer` | Hammer-on |
| `p` | `pull` | Pull-off |
| `b` | `bend` | Bend (destination fret = bent pitch) |
| `~` | `vibrato` | Vibrato (no destination) |

### Destination fret

For `slide_up`, `slide_down`, `hammer`, and `pull`, the digit(s) **after** the
technique character are the destination fret. They are consumed into
`NoteEvent.slide_to`; **no separate `NoteEvent` is emitted** for the
destination in the parser (the score builder synthesises one).

Transcribers often insert alignment dashes between the technique character and
the destination. All intermediate dashes are skipped before reading the
destination digit:

```
e|---5p--0---    →  fret=5, technique='pull', slide_to=0
e|---5p0------   →  fret=5, technique='pull', slide_to=0   (same result)
e|---3p--2----   →  fret=3, technique='pull', slide_to=2
```

**Slide up** — `desportes_yvonne_modes_dantan_3_phrygien`:
```
e|--9-------9---|--9-8-0=======|==========9///|//12---
```
`9///` = fret 9 with three consecutive slide-up characters; each `/` is parsed
as a new slide_up note, destination determined by the digit after the last `/`.

**Slide down** — `caymmi_saudades_da_bahia`:
```
E|---------0-6-5h6p5---5---5/-3-1-0---
B|-------2-----------8-6---6/-1-1-1---
```

**Hammer-on** — `carcassi_op21_no11_andantino_in_am`:
```
e|---0-h1-----0=======
```
`0h1` → fret 0 hammer-on to fret 1.

**Pull-off** — `koshkin_the_porcelain_tower_0_theme_by_stepan_rak`:
```
e|--9-------9---|--9-8-0=======|==========9///|//12---11--------11p8p0---|
```
`11p8p0` = chain pull-offs: 11 pull to 8, then 8 pull to 0.

**Bend** — `orbon_preludio_y_danza_1_preludio`:
```
----------------------------------------4~7----0-----0-------------------8-----
```
(vibrato `~` also visible; bend `b` examples appear in the same file.)

**Vibrato** — `shafransky_legends_of_ancient_ephesus`:
```
--0---------------|------------------||*--3---2~-0--3---2~-0--|
```
`2~` = fret 2 with vibrato. No destination is read; `slide_to` stays `None`.

### Open-ended techniques

If no digit follows the technique character (after skipping any dashes),
`slide_to` is `None`. This is **valid notation**, not a parse error — it
represents a glissando without a written endpoint.

`ryan_lough_caragh`:
```
e|-----------------5------7\-|--\3--------2--0---------2-|
```
`7\` = fret 7 slide-down with no destination. `garcia_gerald_25_etudes_equisses_25`
also has many open-ended slides: `8\`, `11\`, `15\`.

### Technique characters at measure boundaries

A technique character at the far end of a cell (before the barline) with no
following digit is open-ended. The destination, if written at all, will appear
at the start of the next measure — but the parser does not cross measure
boundaries when reading `slide_to`.

---

## 5. Harmonics

Three distinct notations are supported, handled in priority order:

### Priority 1 — Bracket natural harmonics `<fret>`

`ponce_variations_sur_folia_de_espana_06_var_6`:
```
D|-------------<7>-----|--------------7-----|
```
`<7>` = natural harmonic at the 7th fret. Sets `NoteEvent.harmonic = True`.
Accepted at **any** fret.

`croucher_elegy`:
```
E|-----------------|-0----------<7>--|-----------------|-----------------||
```

### Priority 2 — Bracket artificial harmonics `fret[touch]`

`parodi_poema`:
```
e|--5-----------------|--5[17]----||
```
`5[17]` = left hand on fret 5, right hand touches fret 17. Sets
`NoteEvent.harmonic = True` and `NoteEvent.touch_fret = 17`.

`grau_berceuse_ancienne` uses both notations:
```
B|--5[17]---8[20]---5[17]----------|--------------------|
```

### Priority 3 — Text annotation `Harm.` / `nat.harm.` / `(Harm)`

`villa-lobos_choros_01`:
```
32                                 Harm.
--------2--------2--5-----|--0------12--||
     2-----5--4--------4--|-----0---12--||
--3-----------2-----------|-----0---12--||
```
The `Harm.` label appears on the measure-number line above the string block.
The parser finds its column span and marks notes at frets {5,7,9,12,19,24}
within ±2 columns as `harmonic=True`.

`albeniz_isaac_op202_mallorca` uses `Harm. oct` and `|-Harm.19-|` span notation.

---

## 6. Ties

A `=` character **immediately after** a fret (or technique destination)
marks the note as tied to the next occurrence.

`desportes_yvonne_modes_dantan_3_phrygien`:
```
D|-2=================|-3=================|-2-----------------|
```
Sets `NoteEvent.tied = True`. Strings of `=` across columns are also recognised.

`scarlatti_d_k175`:
```
b|----|-3===1--------|-3===1--------|
```
`3===1` = fret 3 tied across multiple columns, then fret 1.

---

## 7. Triplets

A `|-3-|` marker anywhere in a measure cell sets `NoteEvent.triplet = True`
on **all** notes in that cell.

`croucher_elegy` (measure-number line shows triplet groupings):
```
1  | . | . | . | .   |-3-| | . | .   | . | .   | . | . |-3-| | .
e|-----------------|-----0-3-5-8-5-|-5-------|-0-----------------|
```

The `|-3-|` markers appear in the measure-number / beat-grid line; the parser
detects them in the cell content for the affected measures.

---

## 8. Barlines and measure numbering

### Barline detection

`|` characters within the content region mark measure boundaries. Consecutive
`||` is collapsed to a single boundary at the rightmost pipe position.

### Measure numbering

**Explicit numbers** — `lauro_two_venezuelan_waltzes_1_el_negrito`:
```
0   |   |   |       |   |   |       |   |   |       |   |   |
E-----0-1-2-5-3-||--3=----------|-----------1-0-|---0=----------|
```
The `0` is read as the first measure number; subsequent measures in the system
increment sequentially.

**Zero-indexed pickup bar** — the same piece labels its anacrusis as bar 0.
`min(measures.keys())` is 0, not 1.

**Implicit continuation** — `desportes_yvonne_modes_dantan_3_phrygien` has no
measure-number line above several systems; the parser continues from
`next_global_mnum`.

---

## 9. Repeats

### Repeat sign detection

`scarlatti_d_k175` — `*||` / `||*` style:
```
G|-------------*||-----||*---|---------|-3-4-6-4-|
D|-2-3-2-0-----*||--2--||*---|---------|---5-4-5-|
```
`*||` (or `*|`) ends a repeat section; `||*` (or `|*`) starts one.

`oginski_hej_sloveni` — `||*` / `*|` style:
```
G||*-5--5-5--5-----0---------5-------------*|
```

`desportes_yvonne_modes_dantan_3_phrygien` — the `||` format:
```
e||--------------5---|-0-0-0-------|
G||*-----5-----5-----|----------5--|
D||*-7-----7---------|-------------|
```
The `*` at the start of a cell marks `repeat_start`; at the end marks `repeat_end`.

**Implied start** — if a backward repeat exists but no forward repeat does, the
parser automatically adds `repeat_start=True` to the first measure. This handles
the common case where the entire piece repeats.

### Gap-encoded repeats (El Negrito / Lauro style)

`lauro_two_venezuelan_waltzes_1_el_negrito` — bar numbers jump from 18 to 20,
then 34 to 50 etc.; the tab writes only unique bars. The gap bar numbers (19,
35–49…) are aliases for their source bars:

```
Written bars:  0  1…18  20…34  50…80
Gap bars:            19  35…49
Performance:   0  1…18  1…18  20…34  20…34  50…80
```

`expand_repeats()` detects the gap ratio > 5 % and selects gap-encoded strategy.

### Sign-encoded repeats (Barrios / Choros style)

`villa-lobos_choros_01` — explicit `||:` and `:|` signs; no gap bars. The
expander walks the written sequence and replays sections on `repeat_end`.

---

## 10. Volta brackets (1st/2nd endings)

`visee_suite_09_in_dm_4_sarabande`:
```
                         CV  CIII      cII_____       cII_____
                                     1_____________ 2_____________
6  | . | . | .   | . | . | .   | . | . | .    | . | . | .
E|-8---5-----5-|-6---3-----5-|-5---5--------|-5---5-----0-|
B|-8---3-------|-----3=======|-2---2-----6--|-2---2-------|
```
`1_____________` over a set of measures marks `volta=1`; `2_____________` marks
`volta=2`. The regex `(\d)_{3,}` reads the number from the measure-number line.

`arlen_over_the_rainbow` labels them explicitly in the legend:
```
1____  play the 1st time       2_______  play on repeat
```

During repeat expansion: pass 1 plays volta-1 measures and skips volta-2; pass 2
skips volta-1 and plays volta-2.

---

## 11. Barre markers

Barre annotations appear on a line **above** the string block.

### Roman numeral barre (full — uppercase C)

`ponce_variations_sur_folia_de_espana_06_var_6`:
```
  p           CII           CIV
1  | . . | . . | . .   | . . | . . | . .
e|---------0---------|-------------------|
```
`CII` = full barre at fret 2; `CIV` = full barre at fret 4.

`koshkin_the_porcelain_tower_0_theme_by_stepan_rak` uses `CII` and also
documents it: `CII    full barre on the 2nd fret`.

### Partial barre (lowercase c)

`koshkin_the_porcelain_tower_0_theme_by_stepan_rak`:
```
    CII_____________           cII_____________________
```
`CII` = full barre, `cII` = partial barre — both at fret 2. Sets
`BarreMarker.partial = False` vs `True`.

`carcassi_op21_no11_andantino_in_am`:
```
       cII_              cII_                              cII_______
```

### Arabic numeral barre

`desportes_yvonne_modes_dantan_3_phrygien` (from legend):
```
C7      - barre on the 7th fret
```

`croucher_elegy` uses Arabic barres extensively inline:
```
   c1__________                      c5____c4__________  c5____c4__________
```

---

## 12. Left-hand fingering

Digit lines (containing only digits 1–4 and spaces) appearing **immediately
after** the 6 string lines.

`ponce_variations_sur_folia_de_espana_06_var_6`:
```
e|---------0---------|-------------------|-----------------0-|
B|-------------------|-----2---7p6-------|-----6---0h1---1---|
G|-----6-----6-5p4---|-------------5-4---|-------------------|
D|---2-------------2-|---2-------------7-|---6---------3-----|
A|-0-----------------|-0-----4-----------|-------------------|
D|-------6-----------|-------------------|-0-----------0-----|
     1 4 3   4 4 3 1         1 4 3 2 1 4     2 4     1 3 1
```
The digit row `1 4 3   4 4 3 1 …` is the left-hand fingering line. Each digit
is matched to the nearest note within 3 columns.

`lauro_two_venezuelan_waltzes_1_el_negrito` uses a similar pattern:
```
E-----0-1-2-5-3-||--3=----------|-----------1-0-|---0=----------|
        1-1 4 2     4       3         2 1 4 1         2 3-3
```

---

## 13. Right-hand fingering (pima)

A pima line (containing only `p`, `i`, `m`, `a` and spaces/dashes) appearing
**immediately before** the first string line.

`carulli_op114_no07_prelude_in_am` — the pima line and the strings:
```
   p i m a m i p i m a m i            p a m i m a p a m i m a
e|-------0-----------0-----||      e|---0-------0---0-------0-||
B|-----1---1-------1---1---||      B|-----1---1-------1---1---||
G|---2-------2---2-------2-||      G|-------2-----------2-----||
D|-------------------------||      D|-------------------------||
A|-0-----------0-----------||      A|-0-----------0-----------||
E|-------------------------||      E|-------------------------||
```

`morel_danza_brasilera`:
```
   p       i       m       a
e|---------0---------|-------------------|-----------------0-|
```
Each letter is matched to the nearest note by column (within 3 columns).
`NoteEvent.rh_finger` is set to the matched character (lowercase).

---

## 14. Header fields

`parse_topmatter()` scans the first 60 lines of the file.

### Title and composer

**`Subject:` line** — `bach_js_bwv1012_cello_suite_no6_in_d_1_prelude`:
```
Subject: Bach - cello suite 6 - prelude
```

**`Title – Composer (dates)` pattern** — `lauro_two_venezuelan_waltzes_1_el_negrito`:
```
El Negrito (from Two Venezuelan Waltzes) - Antonio Lauro (1917-1986)
```

**Wide-space layout** — many baroque transcriptions use 4+ spaces between title
and composer on the same line. `koshkin_the_porcelain_tower_0_theme_by_stepan_rak`:
```
Key: A minor     Tuning: Standard (EADGBE)
```

### Time signature

`carcassi_op21_no11_andantino_in_am` — colon separator:
```
tuning: E A D G B E        key: A minor / A major         time: 2/4
```

`liszt_s541_liebestraum_no3_in_ab` — "is" separator:
```
Time signature is 6/4.
```

`bach_js_bwv1005_violin_sonata_no3_in_c_4_allegro_assai`:
```
time signature is 3/4, 120 beats per minute
```

### Key

`koshkin_the_porcelain_tower_0_theme_by_stepan_rak`:
```
Key: A minor     Tuning: Standard (EADGBE)
```

`milan_6_pavanes_4`:
```
key: D major (capo on 2nd fret = key E major)
```

### Tempo

`desportes_yvonne_modes_dantan_3_phrygien`:
```
standard tuning: EADGBE    time: 6/8    tempo: 56 bpm (dotted quarter notes)
```

`lauro_two_venezuelan_waltzes_1_el_negrito`:
```
Tempo 120-132
```
Range → lower bound taken; `TabMetadata.tempo = 120`.

### Capo

`milan_6_pavanes_4`:
```
key: D major (capo on 2nd fret = key E major)
```
`TabMetadata.capo = 2`.

`telemann_twv40_14_fantasia_01_3_grave`:
```
tuning: EADGBE - Capo on 1st fret   key: transposed to F# minor   time: 3/2, 2/2
```

---

## 15. Tuning variants

### Named tunings (checked first)

**Drop D** — `bach_js_bwv0659_nun_komm_der_heiden_heiland`:
```
Drop D tuning: D A D G B E          key: G minor          time: 4/4
```

**Drop D** also — `granados_danzas_espanolas_h142_04_villanesca`:
```
1st version - by Gary Jones, based on the Julian Bream version, drop-D tuning
```

**Drop D via per-string override** — `tarrega_rosita_polka`:
```
Tune 6th string down to D
```
And `figueredo_privaresuello`:
```
Tune 6th string to D
```

### Explicit `Tuning:` line

`carcassi_op21_no11_andantino_in_am`:
```
tuning: E A D G B E        key: A minor / A major         time: 2/4
```
Spaces between note letters are stripped: `E A D G B E` → `EADGBE`.

`ponce_variations_sur_folia_de_espana_06_var_6` (Drop D via explicit line):
```
tuning: D A D G B E          key: A major          time: 9/8
```

`albeniz_isaac_op202_mallorca`:
```
Tuning: DADGBE
```

### Format A′ — non-standard string name in tab itself

`zamboni_op01_sonata_01_2_alemanda` — a lute transcription with F# string:
```
F#|---------------------------------|-----------------0===============|
```
The `F#` string letter is detected as format A′ and the tuning is applied
accordingly.

---

## 16. Priority rules

Where multiple inputs compete, these rules determine the winner:

### String line format detection

Tried in the order listed in §1 (A, A′, A″, B, C, D, E/F). First match wins
on each line independently. `content_start` uses the **first** string line of
a system.

### Technique destination fret

Source fret → technique character → optional alignment dashes → destination
fret. This is consumed left-to-right in a single pass; there is no
backtracking. If the character after the technique is not a digit or dash,
`slide_to` is `None` (open-ended).

`koshkin_the_porcelain_tower_0_theme_by_stepan_rak` — chain techniques:
```
11p8p0
```
The parser reads `11` → `p` → destination `8`, producing one `NoteEvent`
(fret=11, slide_to=8). The `p0` is then a new note: fret=8, technique='pull',
slide_to=0. The destination fret of each technique becomes the source fret of
the next.

### Harmonic detection priority

1. `<N>` bracket — matched before any digit scan; immediately creates a
   `NoteEvent` with `harmonic=True` and advances past the closing `>`.
2. `N[T]` artificial bracket — matched before the plain digit scan.
3. Plain digit `N` — may be retroactively marked `harmonic=True` by text annotation.

### Tuning resolution

Named tuning → explicit `Tuning:` line (overrides named) → per-string
`Tune Nth string to X` modifications (applied last, on top of whatever was set).

`sor_op11_minuet_no01_in_g` uses a prose description rather than a keyword:
```
in which the 5th string is tuned to G  and the 6th string is tuned
```
This matches the `_TUNE_6_RE` per-string override regex and correctly lowers
the 6th string.

### Measure numbering

Explicit number line → implicit continuation from `next_global_mnum`. Explicit
numbers reset the counter and take absolute priority.

### Repeat expansion strategy

Gap ratio = (span − written) / written.
- Gap ratio > 5 % → gap-encoded strategy (`lauro_two_venezuelan_waltzes_1_el_negrito`).
- Gap ratio ≤ 5 % → sign-encoded strategy (`villa-lobos_choros_01`, `scarlatti_d_k175`).

### Barre assignment

A `BarreMarker` is assigned to a measure if the barre text's column range
overlaps the measure's column range. Multiple barres can overlap the same
measure — `croucher_elegy` regularly has two barre markers on the same line:
```
   c1__________                      c5____c4__________  c5____c4__________
```

### Left-hand fingering column proximity

Nearest digit within 3 columns wins. If two digits are equidistant, the
later one (higher column) wins. If no digit is within 3 columns, `finger`
stays `None`.

### Right-hand fingering column proximity

Same algorithm as left-hand: nearest `p`/`i`/`m`/`a` character within 3
columns. Later character wins on ties.

---

*Generated from source: `tab_parser.py`, `topmatter_parser.py`,
`repeat_expander.py`, `models.py`. Corpus examples drawn from the classtab.org library.*
