# Wrapping, resizing & layout fixes

This is where English actually gets *made to fit*. SRPG Studio's message boxes are
fixed-size and the M+ 2m font is monospace, so fitting is a pure cell-counting
problem — but the JP author hand-tuned line breaks, page breaks and voice timing to
the *Japanese* text, and English shifts every one of them. The text pipeline
(`tools/srpgtl/inject.py`) rebuilds all of that at inject time; the plugin layer
(`assets/plugins/Plugin/02 俺オリジナル/文字変更.js`) fixes the UI tables the text
pipeline can't reach; and the exe's Patch 6 swaps in a font whose metrics the
monospace assumption depends on.

Everything below runs as the **inject** stage (`tools/srpgtl/inject.py`), reading the
translated store and writing the patch JSON / `js_strings.json`. It is idempotent —
it always rebuilds wraps from the original JP, so re-running never double-wraps
(`inject.py` module docstring, lines 14-16).

---

## 1. The core wrap: `_reflow` (greedy MAX-FILL)

`_reflow(text, width)` (`inject.py:205`) is the heart of the fitter. The translation
and the `store` step keep the JP's *soft* line breaks, and wrapping each author-line
independently leaves ugly orphan tail-words. `_reflow` instead **greedy-reflows each
prose block so every line fills to `width` before it breaks**, merging soft `\n`
away. The docstring's own worked example (lines 207-211):

```
"...H-scene\nvoices,\nplease set..."  ->  "...H-scene voices, please set..."
```

Without max-fill you get a lone `voices,` on its own line. That is the exact bug this
function exists to kill (see also `memory/text-wrap-max-fill.md`).

**How it decides what to merge vs. keep.** `_reflow` walks the block line by line
(`inject.py:226-235`) and only treats a line break as *structural* in two cases:

- a **blank line** (paragraph break) — flush the buffer, emit the blank;
- a **speaker header** (`_is_speaker_header`, see §5) — flush, emit the header on its
  own line, so named H-scene dialogue keeps each `【Name】` on its own line.

Everything else is appended to a buffer and `flush()`ed through `codes.wrap_text`
(the control-code-aware greedy wrapper in `codes.py:234`). `wrap_text` counts in
monospace **cells**, not characters: `_cell_width` (`codes.py:196`) charges
East-Asian Wide/Fullwidth/Ambiguous glyphs (CJK, kana, `…`, `♡`, `。`, `※`) **2
cells**, ASCII 1 cell, and `_visible_len` (`codes.py:203`) ignores `⟦n⟧`
placeholders and `\xx[..]` control codes entirely so zero-width codes never eat
width budget. A single token wider than the box is hard-broken on atom boundaries by
`_break_long` (`codes.py:218`) so a long unbroken moan can't overflow.

> **Gotcha — hard `\n\n` survives the wrapper, soft `\n` does not.** `wrap_text`
> splits on `\n\n` and re-joins with `\n\n` (`codes.py:240,260`). Inside `_reflow`
> the buffer is joined with a single space, so a *single* `\n` between two prose
> lines is intentionally destroyed (that's the max-fill). If you need a forced break
> mid-paragraph, it must be a **blank line** (paragraph) or a `【Name】` header —
> nothing else is honored.

> **Gotcha — control codes must already be `⟦n⟧`-masked before reflow.** `_restore`
> (`inject.py:46`) runs `unmask_codes` *before* `_reflow`, so by the time wrapping
> happens, codes like `\vo[...]` are real text again and counted at zero width by
> `_visible_len`. A code accidentally containing a literal space would be split — but
> the engine codes here don't, so this holds.

---

## 2. Keeping linguistic units together: `_bind_units`

Before wrapping, `flush()` runs `_bind_units` (`inject.py:180`) so a line break can
never strand a token from the word it belongs with (kinsoku / "keep linguistic units
together" from subtitle style guides). It swaps the protected space for a `\x00`
sentinel that `wrap_text` treats as part of the token, then `_reflow` restores
`\x00` -> space *after* wrapping (`inject.py:223`). Three binders:

- **`_BIND_TITLE`** (`inject.py:175`): a title/honorific glued to the following
  capitalized name — `Lady`, `Lord`, `General`, `Captain`, `Commander`, `St.`, `Dr.`,
  … (`_TITLE`, lines 165-168). So you never break `General\nBalam` or `Lady\nEschalot`.
- **`_BIND_UNIT`** (`inject.py:176`): a number glued to its unit — `turns`, `HP`,
  `MP`, `Lv`, `gold`, `%`, … (`_UNIT`, line 169). So `3\nturns` can't split.
- **`_BIND_LEAD`** (`inject.py:177`): a short leading function word glued to the word
  after it — `a an the to of in on for and or my your its` … (`_LEAD`, lines
  173-174). This guarantees a line never *ends* on a stranded `The`/`its`/`to`;
  breaks fall at phrase starts. Note `_BIND_LEAD` uses a leading `(?<![\w'])` and
  `re.IGNORECASE`, so sentence-final function words with punctuation attached are
  left alone.

The sentinel is `\x00`, restored to a literal space in `_reflow` (line 223) and the
restore happens *after* `_fix_widow` so a bound unit can't be widow-split either.

---

## 3. Widow control: `_fix_widow`

`_fix_widow(wrapped, width)` (`inject.py:187`) is the user-requested polish pass: if a
block's last line is a **lone short word** (no space in it, visible length ≤
`max(12, width//4)`), pull the previous word down so the paragraph doesn't end on a
stub:

```
"...sink into the\nlight?"   ->   "...sink into\nthe light?"
```

It only acts when the merged last line **still fits** the width (line 199) — so it
never *creates* an overflow — and it splits the previous line on real spaces only, so
a `General\x00Balam`-bound unit is never broken (the `\x00` isn't a space). Per
`memory/text-wrap-max-fill.md`, ~54 cases can't be fixed without overflow and are
left as-is.

---

## 4. The message-box WIDTHS

Width is chosen per text kind in `_build_maps` (`inject.py:239-282`). There are three:

| constant | value | applies to | why (`inject.py`) |
|---|---:|---|---|
| `DEFAULT_WIDTH` | **54** | dialogue & info `text`/`info` | the wide map message window is ~60 cells; 54 is the safe text column (line 26). |
| `PAGES_WIDTH` | **44** | dictionary/Manual `pages` | the CharacterScreen draws a right-side illustration at ~x720; full 54-cell lines run **under the art and clip** (`...the player, swor[n]`), so dictionary pages wrap narrower to clear it (lines 27-31). |
| `SHOP_BOX_WIDTH` | **32** | the keeper-greeting cluster `info_misc:1056-1157` | a **narrow 2-line face box** (445px wide, ~104px ≈ 2 lines) beside the keeper portrait, shown `\at[1]` (non-blocking) so it must fit in ≤2 lines. 54 never wraps (overflow into Buy/Sell panel); too-tight over-wraps to 3+ lines that clip/auto-advance (lines 33-43). |

The shop range is `SHOP_NARROW_IDS = set(range(1056, 1158))` (inclusive 1056..1157,
`inject.py:43`). For any unit whose id is `info_misc:<n>` with `n` in that set,
`_build_maps` forces `wrap = SHOP_BOX_WIDTH` **and disables page-align/page-pack**
(`inject.py:262-269`) — these tiny boxes must not be padded.

> **Gotcha — greetings still too long at width 32 are shortened by hand in `tl/`**
> (`inject.py:40-41`). No width can make a 3-line greeting fit a 2-line box; that's an
> editorial fix, not a wrap fix.

---

## 5. Page alignment & page packing (voice / `【Name】` timing)

Two different paginators run *after* the wrap, selected by kind in `_build_maps`
(lines 252-256) and dispatched in `_restore` (lines 52-56):

### `_page_align` — for `kind == "text"` (dialogue & H-scene narration)

The event message box **clears every `MESSAGE_PAGE_LINES` (= 3) lines**
(`inject.py:69`), and each `\vo` voice fires when its page opens. The JP author sized
every speaker turn to a multiple of 3 lines and used blank lines as pauses that
landed at a page bottom. English merging is shorter and desyncs both — the next
`【Name】` creeps up, a pause floats into mid-screen, and a voice fires on the wrong
page.

`_page_align(text, 3)` (`inject.py:138`) rebuilds the page structure: a new
page-*segment* starts at a speaker header (`_is_speaker_header`) **or** after a blank
line (a pause). Every segment but the last is padded with blank lines to a whole
number of pages (`(-len(seg)) % n`, line 159), so each name/pause tops a fresh page.
Verified in `memory/text-wrap-max-fill.md`: 93% of JP turns are ×3 lines; the user
chose "pause = screen break" over collapsing pauses.

### `_page_pack` — for `kind == "info"` (InfoWindow briefings)

The InfoWindow paginates at `INFO_PAGE_ROWS` (= 15) and the player advances with the
down arrow (`inject.py:101-109`). `_page_pack(text, 15)` (line 112) greedily packs
whole blank-line-delimited **paragraphs** into ≤15-row pages, padding a page to its
bottom when the next paragraph wouldn't fit, so page breaks land at paragraph gaps
instead of mid-sentence (`...If such people`). A lone paragraph longer than 15 is
left for the engine to break.

### `_is_speaker_header` — the segment-boundary detector (and the H-scene trap)

`_is_speaker_header(line)` (`inject.py:82`) is shared by both `_reflow` and
`_page_align`. It returns true if the line contains `【` or `】`, **or** (the
belt-and-suspenders path, lines 84-98) the line — after stripping `\vo[...]`/`\C[..]`
codes via `_CTRLCODE` — is a short (≤30 char) Title-Case `Name:` with no sentence
punctuation and no lowercase-initial word. The lowercase test rejects prose
fragments that merely end in `:` (`...spoke up:`), giving zero false positives.

> **Gotcha — dropping `【】` merges speakers into one box.** H-scene / recollection
> narration lives in `tl/info_misc.json` as long multi-speaker `text` blocks, each
> turn a `【Name】` header (`memory/hscene-speaker-headers.md`). If a translation
> drops the brackets (renders `Name:` colon-style **with a non-name** form, or omits
> the name), `_page_align`/`_reflow` can't see the segment boundary and consecutive
> speakers pile into ONE box (`Name: … Name: … Name:` all visible — the Prototype
> Enhanced Slave / Balam Grang screenshot bug, ~99 entries). **The canonical fix is
> to restore the `【】` in the data to match the JP** (and the majority — 276/375 JP
> entries kept them), not to special-case the colon form. The `_is_speaker_header`
> colon path is only a defensive net; the bracket count in each entry must match its
> JP source.

---

## 6. Plugin-side layout: `文字変更.js` StringTable / ContentLayout

Wrapping fixes the *text*; the UI label tables need fixing in the plugin. The runtime
`StringTable` and `ContentLayout` are **full replacements** declared in
`assets/plugins/Plugin/02 俺オリジナル/文字変更.js` — `var StringTable = {…}`
(line 2) and `var ContentLayout = {…}` (line 323). Plugins load **after** `Script/`,
so this file **shadows** `Script/constants/constants-stringtable.js`, which is INERT
(`memory/active-stringtable-plugin.md`). **Make all StringTable / UI-label edits in
文字変更.js** (mirror to the constants file for safety — they share keys/line
numbers). Both files ship loose as UTF-16LE via exe Patch 2.

- **`ContentLayout.ITEM_SPACE`** (`文字変更.js:324`) controls the info-window
  label→value gap. It was raised **60 → 84** to stop label/value overlap (English
  labels like `Effective`, `Exclusive`, `Range` are longer than the JP). Confirmed in
  the file: `ITEM_SPACE: 84`. Many of those labels come from editor data via
  `root.queryCommand(...)`, **not JS**, so widening `ITEM_SPACE` (or editing the
  editor project) is the only lever for them.
  - The wider 84 then overflowed the **2-column** info rows (Attack/Hit, Crit/Range,
    Wlv/Weight). Fixed in `Script/window/window-iteminfo.js` by tightening **only
    col-2**: inter-column gap `42 → 30` (lines 146/170/213) and col-2 label→value
    gap `getSpaceX()=84 → 60` literal (lines 150/174/219); col-1 keeps 84.
- **`Chapter_Footer`** (`文字変更.js:211`) is now `''`. It was the JP `章`, which
  combined with `Chapter_Header: 'Chapter '` to render `Chapter1Chapter`. Emptying the
  footer fixes it.
- Both tables were also left with a handful of untranslated entries (the `アイテム`
  suffix, class-change / item-full messages) per the memory note — worth auditing
  when translating.

> **Gotcha — UTF-16LE only.** Per Patch 2 (`memory/exe-patches.md`) every loose `.js`
> must be UTF-16LE **with BOM**; a UTF-8 file mojibakes (`—` -> `â€"`) or, with a
> UTF-8 BOM, throws `property 'ï»¿' is null` at parse. The shipped `文字変更.js` is
> already UTF-16LE (the `\xFF\xFE` BOM is visible at byte 0).

The JS string layer itself is extracted/applied by `tools/jstools/js_text_tool.py`
(`extract` -> fill `js_strings.json` -> `apply`); it keys each literal by position and
re-checks `original` before replacing, so it's idempotent and skips hand-edited files
(`docs/reference/JS_TRANSLATION.md`). `inject.py:inject_js` (line 355) fills those
`translation` fields from the translated store.

---

## 7. The font fix (Patch 6) — why cell-counting is even valid

The whole wrap model assumes M+ 2m is monospace, but the **embedded** copy in the
game has broken metrics. Patch 6 (`memory/exe-patches.md`) swaps it for a known-good
loose font, and it ships as `assets/font/M+ 2m.ttf` placed loose in `Fonts/`.

At a high level: the game text font is an in-memory DirectWrite custom font
collection (loaded in `sub_43CA10`, **not** GDI). Fonts *with* embedded bytes (M+ 2m,
`[node+0x20]!=0`) normally take the embedded branch `loc_40227A` and never look for a
loose file — which is why a player dropping a font into `Fonts/` was ignored. Patch 6
hooks `0x40227A`, builds `<base>\Fonts\<name>.ttf` (name at **node+0x10**, *not*
+0x0C), calls the engine's own loose reader `sub_441450`, and on success loads the
loose TTF instead of the embedded one; on failure it reproduces the embedded store.
The cave lives at VA `0x5581b8` in the RWX `.mtl` section, PIC.

Two debug-costing gotchas (from the memory note, useful if you ever rebuild the
exe with `tools/loosekit/patch_exe.py`):

- the font **name is at node+0x10**, not +0x0C — the wrong offset yields the path
  `\Fonts\.ttf`, a silent fallback to the broken embedded font (no crash, no swap);
- the original `mov eax,lpMem` instruction the hook overwrites carries a **base
  reloc** (HIGHLOW at RVA 0x227B); the `jmp rel32` reuses those bytes, so the loader
  relocates the rel32 under ASLR and the jump lands in garbage -> graceful
  `ゲームの起動に失敗しました。`. Fix: turn that reloc entry into type-0 (skip).

Proof it works: `lpMem[0].len == 1610624` (the loose fixed M+ 2m, TTF sig
`00 01 00 00`) vs `1622368` for the embedded broken one; menu text then renders clean
and at the monospace metrics the cell-count wrapper assumes.

---

## Quick reference — where each fix lives

| concern | symbol / file | path |
|---|---|---|
| greedy max-fill, kill orphans | `_reflow` | `tools/srpgtl/inject.py:205` |
| cell-aware greedy wrapper | `wrap_text`, `_visible_len`, `_cell_width` | `tools/srpgtl/codes.py:234,203,196` |
| glue title/number/function-word | `_bind_units` (`_BIND_TITLE/UNIT/LEAD`) | `inject.py:180,165-177` |
| no stub last line | `_fix_widow` | `inject.py:187` |
| dialogue/info widths | `DEFAULT_WIDTH=54`, `PAGES_WIDTH=44`, `SHOP_BOX_WIDTH=32` | `inject.py:26,31,42` |
| page = 3 lines, voice timing | `_page_align`, `MESSAGE_PAGE_LINES=3` | `inject.py:138,69` |
| info-window paragraph packing | `_page_pack`, `INFO_PAGE_ROWS=15` | `inject.py:112,109` |
| speaker boundary / `【】` | `_is_speaker_header` | `inject.py:82` |
| live UI table + label gaps | `StringTable`, `ContentLayout.ITEM_SPACE=84`, `Chapter_Footer=''` | `assets/plugins/Plugin/02 俺オリジナル/文字変更.js:2,324,211` |
| 2-column row fix | inter-col 30 / col-2 gap 60 | `assets/plugins/Script/window/window-iteminfo.js:146,150` |
| fixed monospace font | loose M+ 2m (Patch 6) | `assets/font/M+ 2m.ttf` -> loose `Fonts/` |
