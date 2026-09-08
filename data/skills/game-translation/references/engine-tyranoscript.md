# TyranoScript / TyranoBuilder (Electron or NW.js)

**Indicators:** `resources/app.asar` (or a loose `resources/app/`) containing
`data/scenario/*.ks`, `tyrano/`, `index.html`, `main.js`. Chromium DLLs
(`libEGL.dll`, `ffmpeg.dll`, `chrome_*.pak`). `data/system/Config.tjs`.

Three reusable projects under `tools/Game Translation/`:

| Project | Evidence and scope |
|---|---|
| `Reference Pipelines/TyranoScript (AjinSyoujyo)/` | TyranoScript v5 / Electron 7.1.2; 5,088 units, byte-reversible extraction, tested ~2 MB loader shim |
| `Active Projects/Musi Dream (TyranoScript)/` | Electron 24.8.8 / Node 18.14.0; completed manual offline text/image translation, verified ASAR installer and player Git project |
| `Active Projects/Yume Yoshiwara (TyranoScript)/` | v1.041ex / Electron 7.1.2 / Node 12.8.1; extraction and Claude Batch preparation, mixed UTF-8/CP932, state/display separation; no English release or paid API run |

Read the selected project's `README.md` before copying code. Musi Dream's
`reports/RELEASE_VALIDATION.json` records 509 units / 574 occurrences, 30 image
replacements, unchanged structure across 33 scenarios / 5,138 parsed elements,
rendered fit, live legacy/English save checks, a nine-scene run back to title,
and exact archive restoration. Its `DROPIN_PROJECT.md` and `reports/dropin_qa.json`
separately document the Git packaging retest. Not every alternate route was
played individually. One image, `data/bgimage/ev_Hdouga.jpg`, is excluded because
it contains sexual depictions explicitly labeled as minors; it remains unchanged
and absent from the patch. Preserve these limitations in coverage claims.

Most examples below come from AjinSyoujyo; newer-build differences are identified
explicitly. Read the shipped `Config.tjs` and parser first. A configuration schema
number or stale package description is not proof of an engine release. In
particular, the old unconditional NBSP workaround is wrong for Musi Dream.

**Even matching Electron and Tyrano versions do not establish matching game
semantics.** Yume Yoshiwara shares AjinSyoujyo's Electron 7.1.2 and space-deleting
parser, but adds registered/literal/dynamic speakers, Japanese state values,
CP932 plugins, disabled editor interfaces, and direct JavaScript UI calls.
Re-probe the parser and re-derive the content rules independently. This session
did not test Yume Yoshiwara's application search order or a loader shim.

### Yume Yoshiwara preparation evidence (2026-09-06)

Read its `README.md`, `scripts/project.py`, and reports before reusing the adapter.
The saved catalog has **13,948 units / 18,702 occurrences**, including 10,418
dialogue units; 603 scenario/plugin files are included in extraction. The source
snapshot retains all 607 shipped KS files. `reports/identity.json` records a
byte-exact identity splice over 519 text-bearing files, and
`reports/parser_probe.json` records all 607 files / 202,853 parsed elements.
These counts establish the recorded extraction/probe scope, not exhaustive
player-visible coverage or save compatibility of an English build.

`scripts/test_tooling.py` passed 12 offline tests, including actual validation,
out-of-order result import and an uncertain submission response. No paid batch,
live model smoke test, renderer mapping, English layout, installation or save/load
test was completed. The glossary remains a seed, including provisional minor
readings and character metadata. **Do not treat this preparation adapter as a
completed translation pipeline.** `reports/extraction.json`, `file_census.json`,
`dynamic_display_sites.json`, `excluded.jsonl`, and `images.json` retain the
evidence and exclusions in the durable project.

---

## ASAR extraction: check the index beyond the reference prefixes

The reference unpacker's prefixes are an optimization for its source game, not
a statement of where Tyrano content can live. Diff the ASAR index against the
extracted paths and classify omitted text/font candidates. On Yume Yoshiwara,
the initial filter missed **`data/others/other_check.js`** and eight font files
directly under `data/others/`. `[loadjs storage="other_check.js"]` in `night2.ks`
and `night2_sub.ks` resolves there, outside `data/others/plugin/`.
`scripts/supplement_snapshot.py` added these to the immutable snapshot. The helper
contains no translatable prose, but it compares displayed traits and therefore
affects translation correctness; an empty string count is not a reason to ignore
its consumers. Re-extract/re-fingerprint before preparing API requests whenever
the source inventory grows.

If the user asks for images for manual review immediately, **extract them first
and provide the folder before continuing text analysis**. Enumerate image/artwork
extensions across the whole archive, not only `data/image/`: include plugin art,
root icons and source artwork such as PSD when shipped. Preserve relative paths
and original bytes. A local lazy-loading HTML index can link to originals, and a
CSV can hold review notes; regenerating the inventory must preserve those notes.
This authorizes extraction, not OCR, visual classification or replacement art.

Yume Yoshiwara's 3,073,723,398-byte ASAR contained 4,537 extracted image/artwork
entries totaling 1,775,964,044 bytes. `scripts/image_inventory.py` checked paths
and lengths; it did **not** prove content hashes, native decoding or text coverage.
Text/font and image extraction did not duplicate audio or produce a full unpack.
Its ASAR had no linked or unpacked entries; reject unsupported entry types rather
than treating a missing offset as zero. Check resolved output paths and collisions
under the target filesystem's case rules before trusting an extraction.

## Delivery: verify application search order for this executable

Application precedence varies by build. AjinSyoujyo / Electron 7.1.2 searches
`app`, `app.asar`, `default_app.asar`; Musi Dream / Electron 24.8.8 searches
`app.asar`, `app`, `default_app.asar`. A loose `resources/app` does not override
Musi Dream's existing archive. Inspect the bundled bootstrap and, if necessary,
native search-path construction and fuses; a successful ASAR read in Node mode
does not establish application precedence or browser protocol interception.
Musi Dream's evidence is in `manual/runtime_audit/AUDIT.md` and
`manual/runtime_audit/binary_evidence.json`.

Musi Dream uses a tested ASAR rebuild preserving the original launcher, preload,
dependencies, package identity and executable-facing app path. Read preload from
the archive even if a text-only extraction omitted it; `package.json` dependencies
need not enumerate everything the preload imports. A tiny bootstrap or renamed
archive needs separate live proof, including `getAppPath()` / `getExePath()` save
normalization. Preserve the actual `TyranoErectron` user-agent suffix and projectID.

### Loose-folder shim: verified AjinSyoujyo example

Before adapting this shim, inspect `main.js`, preload/context settings,
app-directory resolution, and protocol handling, then prove a visible override.

The AjinSyoujyo executable resolves the app directory in this order - **verified
by grepping that binary**, not assumed:

```
const searchPaths = ['app', 'app.asar', 'default_app.asar'];
```

```bash
# the JS is stored UTF-16LE inside the exe
python -c "
from pathlib import Path
d=Path('game.exe').read_bytes(); i=d.find('searchPaths'.encode('utf-16-le'))
print(d[i-400:i+3000].decode('utf-16-le',errors='replace'))"
```

On that executable, a loose `resources/app/` **wins over `app.asar`** and
permits this small delivery:

```
resources/app/
  package.json     name + window block copied verbatim from the original
  main.js          loader shim (~90 lines)
  override/        only the changed files, mirroring their asar paths
```

The shim does two things:

1. `mainWindow.loadURL('file://' + path.join(process.resourcesPath, 'app.asar', 'index.html'))`
 - loading `index.html` from *inside* the archive keeps every relative path in
   the game resolving into the original 745 MB, so nothing else must be copied.
2. `protocol.interceptFileProtocol('file', …)` - for each request under the asar
   path, look up the relative path in a `Map` built once from `override/`, and
   serve the loose file if present.

```js
const rel = path.relative(ASAR, target).split(path.sep).join('/').toLowerCase();
const replacement = overrides.get(rel);
callback(replacement ? { path: replacement } : { path: target });
```

Index the override tree into a `Map` at startup rather than `fs.existsSync` per
request - the intercept sees every image the game loads.

**Two things the shim must keep or saves break:**

* `webContents.setUserAgent(ua + ' TyranoErectron')` - `$.isElectron()` keys off
  that suffix, and without it the save-tamper check and audio unlock take the
  browser path.
* `package.json`'s `name` - Electron derives `app.getPath('userData')` from it,
  and TyranoScript hashes `getExePath() + projectID` into its save-tamper key.

Uninstall removes only the patch-owned `resources/app` tree after verifying its
resolved path. Same-path images use the same override rule.

**Fallbacks depend on precedence.** Full extraction into `resources/app` works
only if that directory actually wins; on an archive-first build, leaving the
original `app.asar` in place still launches the archive. Prefer a tested repack
when it preserves startup and save identity without a new bootstrap.

### Verified ASAR rebuild and player installer

Use Electron's `original-fs` for raw archive bytes; ordinary Electron `fs`
transparently handles ASAR member paths. Capture every original offset before
rewriting the header. Stream the new archive, update replacement sizes/offsets
and SHA256 integrity blocks, then read it back: verify all replacement and
unchanged entry bytes, metadata, integrity blocks and the complete checksum.
An archive that opens can still serve wrong bytes from shifted offsets.

Pin the supported original and reviewed payload hashes. Reject unsafe paths,
unknown/independently modified installations, and unsupported links or unpacked
entries. Verify a candidate before a same-directory atomic replacement and keep
the exact original backup. Test build, install, repeat install, restore, corrupt
inputs, out-of-order source offsets, running-process rejection and environment
restoration in an isolated fixture. Musi Dream's `release_tools/` implementation
and `release_tools/INSTALLER_DEVELOPMENT.md` retain these checks.

The Windows wrapper uses the game's bundled executable with
`ELECTRON_RUN_AS_NODE=1`, requiring no separate player interpreter. It restores
the prior environment value in `finally`; piping the GUI executable through
`Out-Host` makes PowerShell wait and retain its exit code. Remove Node mode for
actual GUI QA. Preserve each previous release before an upgrade: restore the old
revision with its own package before replacing that package or installing a new
manifest whose identity check may reject the previous patched archive.

### Saves: parsed positions and cached display are separate

**On AjinSyoujyo, saves live beside the executable.** Confirm the save backend
and real paths on each new game; `configSave=file` is configuration evidence,
not an observed save/load test.
`<projectID>_tyrano_data.sav`, `_tyrano_auto_save.sav` and `_sf.sav` sit next to
the exe as URL-encoded JSON (`%7B%22kind%22%3A%22save%22...`), even though the
engine has a localStorage path, a compress path and a `userData` directory. Read
them with `json.loads(urllib.parse.unquote(raw))`.`data` is a **list** of slots,
each with `stat.current_scenario`, `stat.current_line` and `current_order_index`.
Test a save migration against these real files - a synthetic corpus reported
0.0% wrong line while an actual slot was broken.

**Saves store a parsed index that structural edits can invalidate.** A save
carries `current_order_index` into the scenario's parsed element array. Ajin's
rewrap added/dropped tags and required the shim's `save_compat.js` migration;
see `save-compatibility.md` for source-line mapping and legacy/stamped-save proof.

First compare source and output with the shipped parser: element counts, names
and line coordinates, label maps, control parameters, registered character keys,
and script structure/syntax. Musi Dream preserved all element positions, so an
index remapper was unnecessary. Leading `_ ` continuation spacing and fit edits
also preserved structure. Re-evaluate this guarantee if later edits add/drop tags.

Old saves can nevertheless restore cached Japanese layer HTML, nameplates,
choices and captions. Musi Dream's separate display-refresh helper handles those
without changing event attributes or non-display state. Test a real legacy slot,
advance, save in English and reload; check visible captions/backlog as well as the
resume position. Synthetic structural checks alone cannot prove cached display.
See `manual/runtime_audit/SAVE_COMPAT.md` for the display mutation allowlist and
scenario/index-scoped handling of ambiguous repeated prose. Preserve technical
keys and unrecognized saved DOM shapes; do not globally replace saved strings.

**Avoid the unverified built-in `.tpatch` path.** The inspected TyranoScript v5
`checkUpdate` archive branch races un-awaited `asar.extractAll` and
`asar.createPackage` operations, then deletes the patch file. The tested Ajin
shim or Musi Dream installer avoids that path. Reinspect another build before
making claims about its updater.

---

## Where the text is - scenario text, nameplates, and runtime UI

AjinSyoujyo had no separate name box or localisation table: 4,238 dialogue,
451 code, 208 choice, 106 ptext, 56 js, 22 punct, 7 misc. **That is not an
engine-wide absence of nameplates.** Musi Dream uses both literal names and
registered character IDs through `#` lines, plus a theme configuration reader.

| Kind | Where |
|---|---|
| `dialogue` | message runs in `.ks`, including text beside tags; classify comments, labels, `@`, `#`, `_`, and script blocks first |
| `name` | literal `#name` nameplates; registered character references remain keys |
| `choice` | `[glink text=]`, `[button text=]`, `[link text=]` |
| `ptext` | `[ptext text=]` - free-positioned labels |
| `code` | **JS string literals inside `exp=` / `cond=` / `&`-expressions / `[iscript]`** |
| `js` | engine + plugin `.js` |

### `#` is a speaker control, and may contain an identifier

The shipped parser turns `#name[:face]` into `chara_ptext`, not dialogue.
Read that tag's consumer as well: Musi Dream resolves `stat.jcharas` aliases,
then `stat.charas[name]`; registered characters display `cpm.jname`, while an
unresolved name is displayed literally. An empty `#` clears the nameplate.

- Classify these lines before the generic message extractor. Capture the speaker
  as context for following dialogue; preserve the `#` and any `:face` suffix.
- Collect registrations and aliases first. Freeze technical references such as
  `#undress_bug`, `#sanran_ch`, and `#ev_baby`; translating them breaks character
  lookup or bubble behavior. If a registered character has a Japanese `jname`,
  inspect its display/alias consumers and translate that field coherently rather
  than renaming the character ID.
- Extract an actual literal nameplate separately, including punctuation-only
  names such as `#？？？`. Keep the reveal boundary; do not replace it with the
  later identity. Do not emit `#name` as a dialogue translation.
- A bubble's sprite anchor is not proof of the story speaker. Musi Dream's
  `ev_baby` anchors the heroine's dialogue, not a child speaker. Likewise, `俺`
  in an ending viewer's nameplate does not identify that viewer with a creature
  using the same first-person pronoun. Resolve identity/gender from scene evidence.

**Check the copied extractor's actual dedup key.** The AjinSyoujyo extractor's
`_add` uses `unit_id(kind, masked)` for every kind despite documentation saying
dialogue is never deduped. Musi Dream's adapter keys dialogue/punctuation by
file, line, span start, and source; UI remains deduped with occurrence-local maps.
Those dialogue IDs are stable for the preserved source snapshot, not across
upstream line insertions. Use an explicit merge strategy for a new game version.

Yume Yoshiwara needs all three speaker paths: `#char0` resolves through a roster,
`#夜見世客` can be a literal label, and `#&tf.mob_name` is dynamic. Initialization
passes `jname` through `char_sample*_clone`, `char_sample*_m`, and `home_char*`
macros; inspect those consumers rather than limiting name extraction to
`chara_new`. Its `m_` registrations are alternate instances, not evidence of new
people. An internal spelling can disambiguate a reading: `甜瓜` is paired with
`meron`, supporting **Meron** rather than an invented kanji reading. IDs do not
establish gender, age, or whether a prefix should appear on screen.

The same census added `[dialog text=]` and `[pushlog text=]` as visible text,
while `[night2_layer_change char=]` selects a character and stays technical.
Classify by the actual tag/macro consumer; the spelling of a parameter is not
enough to decide. Preserve unknown-identity and punctuation-only nameplates too.

### Code literals are easy to miss

**`exp=` / `cond=` are code, and code holds display strings.**
`[eval exp="f.hidename=['扉','演算機','廃品',…]"]` builds the hideout menu.
`[ptext text="&'同棲' + f.day + '日目'"]` builds the day counter by
concatenation. Scan *inside* the expression and emit one unit per literal,
carrying the whole expression as prompt context so a fragment can be made to read
correctly in place (`同棲` → `Day `, `日目` → ` together`). Translating the whole
attribute breaks the game. Skipping it leaves Japanese on screen.

**`[iscript] … [endscript]` blocks.** The reference game keeps five ranked arrays
of lewd words there, spliced into dialogue at random by `[emb]`. 100+ units of
real content that only a JS-literal scan finds.

### Masking

Mask every `[...]` tag and HTML token to a sentinel before translating. Peel a
*leading* and *trailing* run of bare sentinels off - `[cm][s_e6]text[p]` should
reach the model as `text`, not `⟦0⟧⟦1⟧text⟦2⟧` - but keep inline ones
(`[emb exp=…]`, `[l]`, `[r]`) in place, since their position matters.

Mask the engine's format placeholders too: Musi Dream's `tyrano/lang.js`
contains `{ name }`, `{ line }`, `{ path }`, `{ before }`, and `{ after }`.
Preserve their exact spelling and whitespace. If an included JS template literal
uses `${...}`, keep the expression opaque **before** a KAG matcher can mistake
an array subscript for a tag. A simple brace regex is not a general JS parser;
nested templates/expressions need a capable lexer or explicit review. Also audit
Japanese inside masked HTML attributes: a token-only unit can otherwise conceal
the entire visible label.

Yume Yoshiwara's `data/scenario/result_night.ks:143,145` exercises both
`${tiredCharacters[0]}` and `${tiredCharacters.join(', ')}` inside backtick
strings. Mask the **whole interpolation first**, including brackets and quotes;
retain only the surrounding prose as translatable text. The adapter handles
these simple single-line expressions and rejects unsupported nested templates;
that narrow matcher is not a general JavaScript grammar. Decoded literal newlines
also need masking so replies stay single-line and JS injection restores escapes.

Do not apply KAG masking blindly to every JS string: a selector such as
`input[data-part='表情セット']` is technical, and `[リセット]` in an HTML button
can be a visible bracketed label rather than a KAG tag. A unit left with only
sentinels must be classified, not counted as translated. Those examples came
from disabled editor UI in this build, so their exclusion was established from
the plugin flags and guards below, not from their superficial string shape.

**The token map belongs to the occurrence, not the unit.** Two lines can mask to
the same string while standing for different tags. Keying tokens by unit
silently restored the wrong tag on 338 lines before this was caught.

---

## Attribute spaces: select behavior from the shipped parser

**Probe before applying NBSP.** Musi Dream has a newer state-machine `makeTag`
and ships `KeepSpaceInParameterValue=2`. Loading its own `kag.parser.js` under
its own Electron runtime preserved `glink text="Two words"` and the inner
string in `eval exp="f.sample='Two words'"` with ordinary ASCII spaces.
Its adapter therefore removes the reference injector's `protect_spaces` call.

In that parser's source, mode `1` removes internal ASCII spaces from ordinary
quoted values, mode `2` preserves them but trims the value's edges, and mode `3`
also preserves edge whitespace. Backtick-quoted values have a separate exception
to the mode-1 deletion. Mode `2` was exercised in the preparation probe; measure
other modes before depending on them. Do not change the game's configuration
globally just to make one literal fit. Whitespace at the ends of JS fragments
and nested quotes must survive the complete parse, not only Python escaping.

### Older parser: NBSP only where space deletion was observed

Yume Yoshiwara independently confirmed this path under its own Electron 7.1.2:
`glink text="Two words"` parses to `Twowords`; U+00A0 survives in that attribute
and in a nested JS string inside `eval exp=`, while `_ Second sentence.` retains
its leading message space. See `reports/parser_probe.json`. This confirms parser
behavior only; it does not establish English wrapping, UI fit or renderer output.

On **AjinSyoujyo**, `kag.parser.js`, `makeTag()` contains:

```js
else { "="==c && (c="#"); " "==c && (c=""); tmp_str+=c; cnt_quot_c++ }
```

Inside a quoted attribute value, `=` is swapped for `#` (and restored later) and
**a literal space is deleted outright**. The parser then does `str.split(" ")` to
separate the parameters, which is why - but the space never comes back. Japanese
never noticed. It does not use spaces. English ships as:

    [glink text="Just talk normally"]   ->   Justtalknormally

This affects **every** `form=attr` unit and every JS string literal inside an
`exp=` / `cond=` attribute. It does **not** affect message text (collected
outside any tag), `[iscript]` bodies, or standalone `.js` files - none of those
go through `makeTag`.

Scope on the reference game: **488 attribute values**, i.e. Most of the UI -
every `glink text=`, every `ptext`, notices, hints, the window title, the
name-entry default, and the JS literals inside `exp=` (`f.hidename=['Bench Press']`
was shipping as `'BenchPress'`).

**For that older parser, write U+00A0 instead of U+0020** in those values.
The following results apply to its space-deleting path, not Musi Dream's mode 2.

**Verify against the game's own parser, not the minified source.** Load
`kag.parser.js` inside the shipped runtime and feed it candidate strings - the
binary is a Node interpreter when asked:

```bash
ELECTRON_RUN_AS_NODE=1 ./game.exe probe.js     # probe.js requires kag.parser.js
#   plain space  ->  "Thistitlecontainscross-sectionviews."
#   U+00A0       ->  "This title contains cross-section views."
```

| written as | survives `makeTag` | renders as a space in |
|---|---|---|
| U+0020 space | **no** | - |
| **U+00A0** | yes | `.html()`, `.text()`, `document.title` |
| `&nbsp;` | yes, as literal text | `.html()` only |
| U+3000 | yes | everywhere, but double width |

`&nbsp;` is the trap: it looks right in menus and then shows up literally in
`[title name=]`, which reaches `document.title` as plain text. U+00A0 is the only
candidate that works in all three consumers - and the shipped `tyrano/libs.js`
already contains U+00A0 in its own indentation, so it is known-good in this
engine. The reference game's author used `&nbsp;` as a workaround in `macro.ks`,
which is the clue that leads here.

```python
def inside_kag_attribute(site):
    if site.form in ("attr", "nested"):
        return True                      # a KAG attribute value
    return site.form == "jsstr" and site.tag not in ("iscript", "js")
```

Caveat: NBSP is non-breaking, so a `glink` label that would have wrapped inside
its `width=` box now will not. For one-line UI labels that is what you want
anyway.

**Two traps when verifying this:**

* Some shipped files already contain NBSP of their own - `tyrano/libs.js` has
  seven in its indentation. A round-trip check that "un-protects" only the output
  is a lossy inverse and will report an untouched file as modified. Normalise
  both sides.
* A few *Japanese* attribute values contain ASCII spaces the engine was already
  silently eating (`text="仕 事 受 注"`, spaced for visual effect - it had been
  rendering as `仕事受注`). Those change under the fix, correctly.
* A "words are glued together" heuristic over the output will throw false
  positives: the game's own `&nbsp;` runs, labels separated with `・` rather than
  spaces, and `&'￥' + f.yen` expressions that need no spaces at all.

## Message-line trimming is independent of attribute-space behavior

The older-parser NBSP fix above is for **quoted attribute values**. Message
text has a separate trim/join path, including in Musi Dream's newer parser.
U+00A0 does **not** fix that path. Do not generalise one workaround to the other.

Consecutive message lines have no implied separating space or visible line
break; explicit tags such as `[r]` and page controls determine the display flow.
Japanese needs no space at a line junction, so the scripts rely on that.
English does not:

```
...an entirely different physiology.They sustain their vital functions...
```

A trailing space cannot fix it, and neither can U+00A0: `parseScenario` runs
`$.trim()` on every line before it looks at anything, and jQuery's `rtrim`
character class **includes U+00A0**. Both are gone before the parser starts.

What survives is KAG's own marker. A leading `_` is stripped *after* the trim,
so the space behind it is kept:

```
_ and Lewdness rises when you have sex.
```

| Where the space is lost | Cause | Fix |
|---|---|---|
| inside an attribute on a confirmed space-deleting build | `makeTag()` deletes U+0020 | write **U+00A0** at those sites only |
| inside an attribute on Musi Dream, mode 2 | internal U+0020 is preserved | retain ordinary spaces |
| at a line junction in message text | `$.trim()` strips U+0020 *and* U+00A0 | write a leading **`_`** |

Musi Dream's probe also confirmed that `_ Second sentence.` preserves the
space after the marker. Its completed patch uses reviewed continuation sites,
with unchanged parsed structure and final renderer fit checks. Check each stage
between file and screen separately; a plugin can bypass KAG entirely, as the
configuration sample reader below does.

## `[ruby]` glosses one character, and English words are longer than that

`[ruby text="ザーメン"]精液` is 精液 shown with a slangy reading above it. The tag
attaches its reading to the **next character only**, which is right for a kanji
and wrong for a word - so once both halves translate to "semen", the tag's only
remaining effect is to break the word in two:

```
could I have some   s emen?
```

A gloss whose reading and base come out as the same English word carries
nothing. Drop the tag and let the base text stand. Where the two do differ, the
gloss has to be re-expressed some other way (a parenthetical, or folded into the
line) - it cannot stay as ruby over a multi-letter word.

## The message box is state, not a constant

In AjinSyoujyo, `show_mesL` / `S` / `H` / `T` in `system/macro.ks` each `[position]` the
`message0` layer at a different width, so the text budget changes as the script
runs:

| macro | layer width | margins | text budget |
|---|---|---|---|
| `show_mesL` / `H` / `T` | 1920 | 50 / 70 | **1800px** |
| `show_mesS` | 1210 | 50 / 70 | **1090px** |

Parse the macros for these rather than hard-coding a number, then track the last
one called forward through each file. A file that never calls one - `hint.ks` is
such a file - runs in whatever box its caller set, so resolve it one level by
finding who jumps to it. `Config.tjs`'s `defaultFontSize=37` is not the size in
use either: `[deffont size=42 face=mfrules]` in `first.ks` overrides it globally.

### Theme overrides and speech bubbles (Musi Dream)

Follow initialization and the final DOM consumer before assigning a width.
Musi Dream's theme overrides message0 to 1160 x 193 at (60,522). The layer consumer
subtracts 10px before its 140px side padding and 55/10px top/bottom padding, giving
**870 x 118px** of content. At 28px font plus 8px line spacing, that fits three
complete normal rows. The separate nameplate is **360px wide at 26px**.

`tb_fuki_start` uses **message1**, with its own margins and per-character
`max_width`, `fix_width`, font and anchor. Bubble height grows; do not impose the
normal box's width or a universal three-row cap. Track active mode, font overrides
and inherited line-height; measure the actual character-span DOM and screen
clamping/subject occlusion. A commented-out `font.css` example proves no bundled
font. Musi Dream's `manual/fit_report.json` records final renderer comparisons
covering 442 text units without overflow; `reports/layout_sites.json` is the
source site map, not that rendering proof.

## Use the project's own tag regex, never a fresh one

A naive `\[[^\]]*\]` looks adequate until it meets an attribute holding array
subscripts:

```
[elsif exp="f.koko_status[0][1]>=f.koko_status[0][3]"]
```

It stops at the first `]` inside the quotes. **The usual symptom is an empty
or absurd value, not an exception** - a `[ptext text="&'Storage Lv:' + f.hide[3]"]`
scanned this way yields `''`, measures 0px, and passes every width check in
silence. Here the leftover
which then measures 50,535px and lands at the top of the overflow report. That
one was loud enough to spot. The quiet version of the same bug silently drops
real text from a scan and reports a clean result.

`codes.TAG_RE` is quote-aware, and every pass must go through it:

```python
TAG_RE = re.compile(r"\[(\w+)((?:[^\]\"']|\"[^\"]*\"|'[^']*')*)\]")
```

## Inline word-inserts carry no spaces either

The same family as the space-deletion bug, and it will bite in the same place:
between the file and the screen.

Some inline tags expand to a **word** at run time - `[name2]` becomes the
player's name, `[emb exp=…]` evaluates anything, and the lewd-word macros pick a
noun out of a randomised array. Japanese needs no space around an inserted word,
so the source has none, and a faithful translation keeps none:

```
[emb exp="f.name2"]で宜しいでしょうか。   ->   [emb exp="f.name2"]Is that alright?
```

which reaches the screen as **"NeroIs that alright?"**.

**Read which tags emit a word out of the project's own `macro.ks`**, don't guess:
a macro qualifies when its whole body is a single `[emb]` (a leading `[getrand]`
is only picking the index). That correctly excludes `[p]`, `[r]`, the
face-change macros, and `like_lv1` - which emits an entire line, not a word.

Watch the regex. The lewd-word macros index with
`[emb exp="f.ingo_tinko[f.ingo_LV][tf.rd]"]`, so a naive `\[emb[^\]]*\]` stops at
the first `]` and silently misses all four. Use the quote-aware tag matcher.

**Two places need the fix, because they see different things:**

* **Inside a unit**, where the tag arrives as a sentinel - pad either side unless
  the neighbour is an apostrophe, a hyphen or a decoration, so `⟦0⟧'s cock` and
  `⟦0⟧-chan` stay tight.
* **Against a unit's edge.** `split_affixes` peels a leading/trailing tag run off
  so the model sees clean text, which puts the emitter *outside* the unit
  entirely - `[emb exp="f.name2"]で宜しいでしょうか。` extracts as just
  `で宜しいでしょうか。`. No in-unit pass can reach it. It has to be done at
  injection time, where the neighbouring tags are visible.

Put the rule in the prompt as well, so a future run needs neither pass. Then
sweep: count every emitter tag in the output and assert no junction is flush
against a letter (121 inserts, 0 glued, on the reference game).

## State values can be display text and executable logic at once

Yume Yoshiwara compares Japanese values such as `不調`, `普通`, character names
and courtesan ranks in `if exp=`, `cond=`, and iscript, then assigns and displays
the same values through character/inventory tables. Freezing only labels and
jump targets misses this class. Collect comparison operands and technical keys,
trace their producers and display consumers, and preserve the stored values
unless a complete, explicitly tested coupled rename is intended. Never apply a
state-value denylist to unrelated dialogue or literal choice labels.

Its preparation adapter retained **12,414 code occurrences** under
`state-value-preserved`, created **125 `display_value` candidates** without source
edit spans, and inventoried **3,748 dynamic KAG display attributes**. This is
conservative triage, not data-flow proof: validate which candidates are actually
displayed, and include direct JS calls such as `ftag.startTag("ptext", {...})`
when auditing consumers. The attribute-only inventory does not cover those calls.
The renderer mapping and cached-save display repair remain **unimplemented**.
Keeping the keys safe alone still leaves their visible values Japanese.

There is a second coupling after rendering: `data/others/other_check.js` reads
two elements' `textContent`, splits on `' / '`, compares trait labels, and
highlights matches. Both displays must use the same canonical translated labels
and delimiters. Verify that match sets remain unchanged; do not translate just
one side, collapse the delimiter, or assume an exact-match display dictionary
handles larger concatenated strings automatically.

## Things that will break the game if translated

* **Labels** (`*ラベル名`), **`target=` / `storage=`**, and identifier-bearing
  **`name=`** values. Classify by tag and consumer: `[title name=...]` is display
  text, and a literal nameplate is not the same thing as a registered character ID.
* **Strings that are *both* data and a jump target.** Collect every label and
  target first, then freeze any `code`/`js` unit whose text collides. On the
  reference game a task table's column [11] is read as `[jump target="&f.task[i][11]"]`
  and holds `ネモタスク1`…. Those stayed Japanese while the same table's display
  columns were translated.
* **Japanese inside identifiers** - `f.orgasm_in_a中に_count` is a variable name.
  Detect it (a `cond=` with JP but no JP *literal*) and log it, don't translate.
* **Asset filenames.** Anchor the extension test at both ends: `^\S+\.png$`. A
  loose `\.png$` matched an error message ending `(例)data/fgimage/file.png` and
  excluded it from translation.

Log every rejection with its reason, and treat an unrecognised `(tag, param)`
carrying Japanese as `unknown-site` so a game update surfaces it.

**Malformed tags exist.** The reference game has `[eval exp="f.hote=[…]]` with no
closing quote. The tag regex simply doesn't match, so the whole line looked like
prose and would have been translated as dialogue. Guard: if a message run still
contains a bare `[` or `]` after masking, it is a broken tag - drop it and log.
Yume Yoshiwara has a separate original defect at
`data/scenario/status_char1.ks:156`: an `elsif` missing its closing quote/bracket.
The adapter records and preserves that exact source defect. Tie any exception to
the source bytes/version; a blanket waiver for future malformed tags would hide
new extraction failures. A successful source parser invocation is not proof that
the authored control flow or embedded JavaScript is valid.

---

## Engine and plugin strings outside the scripts

* `tyrano/lang.js` - confirmation prompts, save-tamper messages.
* `tyrano/plugins/kag/kag.menu.js` - the save-slot caption, often hand-edited by
  the author to show game stats (`"好感度：" + … + " / 淫乱度：" + …`).
* `tyrano/plugins/kag/kag.js` - `current_message_str` default ("ゲームスタート"),
  the `.tpatch` dialogs.
* `tyrano/libs.js` - playtime units 日/時間/分/秒, save-corruption dialogs.
* `tyrano/plugins/kag/kag.tag*.js` - mostly script errors gated behind
  `debugMenu.visible`, but the update prompt in `kag.tag_system.js` is shown.

**Discover runtime files, not just plugin directories.** AjinSyoujyo ships 15
plugin folders and loads 8. Musi Dream shows why neither "all files in a loaded
folder" nor "all sample files are editor-only" is a valid classification:

- Start with `index.html` script sources, `main.js`/preload references, the first
  scenario, and engine configuration/menu entry points. Follow `[call]`, `[jump]`,
  Builder's `[_tb_system_call]`, `[plugin]`, `[loadjs]`, `[sysview]`, `getScript`,
  and paths read by loaded JS. Resolve storage relative to each loader's actual
  base; the same `storage` spelling does not imply the same directory.
- `theme_kopanda_16/init.ks` loads `setting.js` and `testMessagePlus/gMessageTester.js`.
  The former opens the theme's own `config.ks`; the latter fetches `sampletext.ks`.
  Those three sample lines are player-facing text on the configuration screen.
- `individual_image.builder.js` is editor metadata, even though the plugin's
  `init.ks` is active. Duplicate `_preview.ks` files and unused Live2D definitions
  were excluded by references, not by assuming every underscore filename is dead:
  the game's `system/_scene*.ks` files are actively called.
- A loaded vendor library may contain Japanese **algorithm data**. Musi Dream's
  `html2canvas.js` holds CJK numeral alphabets; translating them would damage a
  formatter. Its disabled 3D tooling and console-only messages were also classified
  separately. Re-evaluate these rulings per build; do not copy the adapter's broad
  vendor/template exclusions as general rules.

Scan JS with comment state preserved across the whole file/block, then map literal
offsets back to source lines. The reference's line-by-line scan extracted quoted
examples from multiline comments. Keep raw spans for injection, including escaped
quotes, and reject an attribute render that changes punctuation to fit its quote
delimiter. Do not silently replace the translator's quote characters.

Log dynamic references and unresolved runtime text for review. Musi Dream's
conservative file graph includes conditional engine references and the fallback
configuration; it is not a runtime trace. A line census reported no unresolved
classified runtime lines, but **one extracted literal cannot certify every literal
on the same minified line**. Review remaining strings and text-bearing attributes,
including HTML templates, before claiming coverage. When images are in scope,
perform their separate visual census and consumer mapping below.

### A loaded plugin can have a disabled editor interface

Yume Yoshiwara's `data/scenario/title.ks:121` loads `chara_part_manager` with
`onlypartset=true`; line 125 loads `tempura_camera2` with `manager=false`.
The former returns before its editor interface at the `ONLY_PART_SET` guard;
the latter returns before its manager when `mp.manager !== "true"`. Keep the
active runtime portions, but exclude the disabled UI, selectors and HTML metadata
after verifying those branches. Loading a `.js` file does not make every string
inside it player-facing.

The prepared adapter uses line cutoffs 54 and 409 for these exact source files.
Those are build-specific rulings, **not reusable engine constants**. On adaptation
or update, re-identify the guards and check their source identity/structure before
using a cutoff. Likewise, its two `_SAMPLE.ks` exclusions are for unreferenced
examples; do not copy a filename-based exclusion onto a loaded config sample.

### The configuration sample reader has its own whitespace bug

In Musi Dream's active
`data/others/plugin/theme_kopanda_16/testMessagePlus/gMessageTester.js`, the sample
fetch callback removes comments and then calls:

```js
data = data.replace(/(\n|\s|\t)/g, "");
```

That removes internal English spaces (including NBSP) before splitting on `[p]`.
The same regex also appears in the **CSS** parser, which has a different purpose.
Musi Dream's implemented repair changes only the sample callback: remove semicolon
comment lines, normalize/trim source lines and join with spaces before page
splitting. Preserve semicolons within prose and exercise `[p]`, `[r]`, and
`[kidoku]`/`[endkidoku]` conversion; leave the CSS reader unchanged. Source probes
and the final configuration screen verified preserved English word spaces.
KAG's `_ ` marker cannot repair a reader that does not interpret it.

## Image paths, inventory and runtime proof

Use `image-translation.md` for the artwork workflow. Resolve each path through
its actual tag/macro consumer. On Musi Dream, `[bg]` uses `data/bgimage`;
Builder's `[tb_image_show]` and `[individual_image]` wrap a non-base `[image]`
consumer defaulting to `data/fgimage`; `[button graphic]` defaults to `data/image`.
Character parts resolve through registration keys. `_clickable_img` is Builder
metadata, not a rendered load. Preserve filenames, canvas/alpha and hotspots.

Inventory all shipped images, including animation frames, flattened tutorial
insets, stock/editor copies and theme overrides. Resolve generated hover names
and CSS backgrounds as well as literal `src=` references. Same-stem files can
differ: Musi Dream's background and foreground tutorial copies have different
bytes, and the foreground copy is active. Fan out reviewed outputs only to
original entries with matching hashes; review distinct variants separately.

For lettering over flat-color illustration, broad RGB inpainting can smear pale
art across old glyphs. Reconstruct the erased base from clean matching regions
or the local palette, confined to the glyph mask. Preserve neighboring symbols,
arrows and decorations; inspect the erased base enlarged before adding English,
then review the final image at its native and actual displayed sizes.

Separate census, native decode, and live scene claims. Musi Dream's 30 replacements
all decoded; 14 active assets were reviewed at their actual scene scale, while
16 other shipped assets had native-size/source-output review without a claim of
live use. Record excluded/untranslated assets explicitly, including the excluded
path identified above; a completed manifest does not mean every visible image
was translated. Bind approval and runtime reports to both image-manifest and
installed-archive hashes.

Chromium accepted lossless PNG bytes at preserved `.jpg` paths in this build,
avoiding recompression outside edit masks; prove this in another target runtime.
Compare the encoded entry to the reviewed file first, then decoded dimensions
and premultiplied RGBA to handle alpha round trips. Embedded ICC profiles require
an independent conversion to sRGB before judging pixel mismatch. Permit only
justified color-conversion rounding with exact alpha, not a blanket tolerance.
Successful native decoding does not establish scaled readability or art quality.

---

## Layout

Read `data/system/Config.tjs`, active macros/themes and the final consumers:

| Widget | Bound |
|---|---|
| message box | active layer dimensions and padding; measure rows using final font/line-height |
| `[glink]` | declared width or actual free space/source bound; text does **not** shrink to fit |
| `[ptext]` | **never wraps** - a hard constraint |

**A `glink` with no `width=` has no box** - it sizes to its own text and will run
into whatever sits beside it. Do not fall back to the 600 px default: that lets
anything under ~576 px pass, which is how `次の日へ進む` → "Advance to Next Day"
shipped overlapping the screen edge and `バグ、要望報告` → "Report Bug / Request"
shipped across the time icons. Bound an undeclared glink by the **Japanese's own
rendered width**, or by the measured gap to the next positioned widget on its row.

**Much of the UI text is table data, not tags.** Item names, status labels and
task descriptions are literals inside `f.item = [[…]]` / `f.koko_status = [[…]]`
declared in `[iscript]` blocks and drawn by generic `foreach` layout macros. Budget
them per `(array, column)` from the widest Japanese in that column - see
`text-fitting.md`. The status table draws label and value at the *same* `x` with
the value right-aligned in a 320px box, so the label's budget is the box minus
the value. Exceed it and they overlap mid-word.

**`[ptext]` is often drawn on a background image, and the image is the budget.**
The day counter sits at `x=20` on `blui/taskbar.png` - a 220 px bar. No attribute
says so. You have to look at the asset. Any label on a plate, panel or bar has its
width set by the picture underneath.

**Measure `ptext` against the Japanese's own width, not the screen edge.**
Several labels in the reference game are *already* wider than the room between
their `x` and the right edge, so the screen cannot be the real bound - the
Japanese is the evidence of how much space exists. Using a screen-derived limit
produced 28 false overflows out of 34.

Use the active resolved font. AjinSyoujyo bundles its face under
`data/others/*.otf`, wired through `font.css` and `[deffont]`; glyph width can be
measured with `ImageFont.truetype(...).getlength()`. Browser fallback, character
spans, wrapping and row capacity still require final renderer measurement.

---

## Encoding

* AjinSyoujyo's `.ks` files are UTF-8 without BOM, with **mixed line endings per
  file** (31 CRLF, 17 LF). Determine encoding/BOM per source file on another game;
  do not generalize a scenario-file observation to plugin JavaScript.
* Yume Yoshiwara's `data/others/plugin/rightClickButton/main.js` and
  `data/others/plugin/wrapmenu/wrapmenu.js` fail strict UTF-8 decoding but decode
  as CP932. Its reader carries the selected encoding and each line separator;
  identity serialization re-encodes with that encoding. Do not use replacement
  decoding or blanket UTF-8 conversion to make the scan pass. Confirm readable
  source and byte round trips before accepting a fallback, and check that eventual
  translated characters are representable. Identity success does not prove that
  English smart quotes or runtime decoding will work in a CP932 script.
* Injection should be a pure span splice - store `(file, line, start, end)` plus
  the original characters at that span, then assert on every run that the span
  still matches and that identity injection is byte-identical.

---

## Run the engine's own code to answer engine questions

The executables of all three projects above support `ELECTRON_RUN_AS_NODE=1`, which turns
"what does the engine do with X?" from a reading exercise into an experiment:

```bash
ELECTRON_RUN_AS_NODE=1 ./game.exe -e "console.log(process.versions)"
ELECTRON_RUN_AS_NODE=1 ./game.exe script.js       # use this game's runtime
```

AjinSyoujyo's probe also exercised ASAR paths and override lookup through `fs`.
Do not assume those behaviors from a successful Node-mode invocation alone.
Musi Dream's `scripts/probe_parser.cjs` reads the extracted parser and actual
Config.tjs in a VM context with minimal `$`/KAG stubs; it tests the parser, not
browser rendering, ASAR routing, or a loader shim. Keep those claims separate.
For another build, confirm Node mode is supported before using this technique.
Musi Dream's later `reports/RELEASE_VALIDATION.json` supplies the separate final
archive, renderer and save proof; do not treat its earlier read-only audit as the
current release status.

### Separate probe bugs from source diagnostics

The first Yume Yoshiwara VM probe threw `TypeError: $.lang is not a function`
on four scenarios. The source parser was trying to format duplicate-label
warnings, and the harness lacked that stub. Add the missing diagnostic dependency
and collect the messages; do not repair the game or exclude those files to make
the probe green. With the stub, all **607 files / 202,853 elements** parsed,
with five original duplicate-label warnings across four files and no alerts.
`scripts/probe_parser.cjs` and `reports/parser_probe.json` retain that baseline.
Compare original and translated diagnostics separately from index/control-flow,
embedded-JS syntax, renderer and save tests.

### Reliable live QA fixtures

Use a separate executable/game directory and save root; `--user-data-dir` alone
does not isolate Tyrano's executable-adjacent file saves. Verify the CDP target's
loaded archive path and hash before driving it. Use local fixture slots rather
than overwriting user saves, and record observed changes without guessing their
cause.

For targeted scene checks, load a known clean save first, wait for restoration,
then enter the scene start and use ordinary controls. A direct jump from arbitrary
state can inherit stale flags/layers. Wait for transitions, image decoding and
stable visible controls before screenshots. Capture transient warning images
when they appear; a later screenshot may miss them. Use the game's normal Hide
control to inspect baked captions obscured by dialogue. Trigger hover on the
actual bound `img` element and verify both alternate filename and restoration.
Keep these targeted checks distinct from a normal new-game playthrough.

## Player Git and drop-in packaging

Keep the player repository separate from the durable translation project. Use a
strict allowlist for reviewed runtime replacements, manifest, installer/restore
scripts and a short player README. Exclude original archives, executables, saves,
source snapshots and private QA. A drop-in layout still needs an installer when
the executable searches the archive first.

Preserve reviewed bytes through Git: Musi Dream uses `.gitattributes` with
`* -text`, verifies staged/checked-out blobs against release hashes, and builds
the player ZIP from committed blobs. Do not run automatic whitespace fixes on
payloads: original CRLF, trailing spaces or blank lines can be intentional.
Classify `git diff --check` findings against pristine source and validate the
exact payload; fix only introduced defects, without normalizing inherited bytes.

Test a fresh checkout/export in a clean game copy, including a path with spaces:
install, repeat install, launch and exact restore. If all runtime files and the
resulting archive are byte-identical to an already tested release, reuse that
release's gameplay/fit/save evidence and label the new test packaging-only.
Changed runtime bytes require the relevant checks again. Musi Dream's
`DROPIN_PROJECT.md` and `reports/dropin_qa.json` retain the scoped proof.

## Offline preparation, manual completion and quick recon

For no-API work, use Musi Dream's **adapter** through `tl.py`,
not the old `extract.run` or API entry point. It uses the standard library for
extraction, masked source/context packets, strict local JSON import, history,
source/store fingerprints, and separate preparation/completion validation.
Do not copy provider clients or credentials. Keep the working project in Tools
with an immutable text snapshot so deleting the game does not delete the work.

Read `Config.tjs` for `projectID`, `configSave`, `scWidth`/`scHeight`, font settings,
`KeepSpaceInParameterValue`, and feature flags, then follow the overrides in the
loaded theme/scripts. Use the quote-aware lexer over included `.ks` files for tag
and attribute counts; a `\[[^\]]*\]` grep truncates quoted array expressions.
Inventory `#` lines, registration/alias fields, plugin/script/template references,
and exclusions alongside the translated-text catalog.

Preparation verification should exercise the real validator with both valid and
invalid translations even while the production store is empty. Musi Dream checked
wrong/missing IDs, duplicate JSON keys, empty/Japanese replies, overwrite guards,
successful import into a test store, and preservation of the production store.
The initial empty-store completion check correctly failed; the current manual
store is complete and `validate --complete` passes. Initial blank packet replies
are historical exports, not current translations. For revisions, keep manual
maps, combined reply and authoritative store synchronized through the validated
import path; the build and generated legacy-save display helper consume these
records. Never overwrite completed work with a stale blank reply.

No-op bytes and a clean source parse establish extraction integrity only. Run
the actual parser on final output, then renderer/save/playtest and installed-byte
checks. Keep the image workspace, source snapshots, glossary, prompts, history
and evidence in a durable tools project outside the game folder; only reviewed payloads enter the
player repository. Manual/no-API authoring changes how translations are written,
not the completion and release gates.


## Claude Batch preparation: group before chunking, and test failure paths

For an explicitly requested API workflow, Yume Yoshiwara's `scripts/claude_batch.py`
is a preparation example; see `llm-pipeline.md` for provider rules and current
pricing. Sort into name, dialogue and UI streams **before** applying the chunker.
Sorting everything by source file/order while switching the bucket between that
file's dialogue and a global UI group repeatedly flushed tiny requests. During
this session it produced 1,846 requests; separating the streams reduced the final
plan to 358, retaining separate dialogue occurrences. Carry file/scene/speaker
metadata and preceding context through chunk splits. Log both units and request
counts before estimating cost; a large prefix repeated on tiny chunks dominates
input even when the text corpus is modest.

The final dry run used a compact ID-to-string map, low effort, adaptive thinking
and a 5-minute cache. `reports/estimate.json` records optimistic, assumed-hit,
cold-cache and uncached costs plus an uncertainty allowance. Those are **offline
estimates, not measured billing**. Re-estimate after filling the glossary and
compare once with actual usage when a paid run is authorized and performed.

The 12-test suite exercises the real import validator and mocked batch transport:
duplicate/missing/extra JSON IDs, placeholder order, residual Japanese, overwrite
guards, out-of-order results, usage aggregation, locks and submission ambiguity.
Write the pending custom IDs **before** the POST; if its response is lost, block
resubmission until the provider job is reconciled. Checkpoint each successful
split before the next one. Bind manifests to source/catalog/config/instructions,
and fetch with the submitting credential/endpoint. Mock success does not establish
live SDK/model/account access. Preparation validation passes with an empty store;
completion validation must fail. No full-price fallback or English deployment
was enabled in this prepared project.

## Windows tooling pitfalls observed during preparation

* **Python UTF-8 mode cannot repair text already damaged by the shell pipe.** A
  PowerShell here-string containing Japanese dictionary keys piped to
  `python -X utf8 -` lost those keys in the shell's native-process encoding, making
  every glossary lookup miss. Writing `seed_glossary.py` as a UTF-8 file and running
  that file restored the matches. Prefer UTF-8 source/JSON files for non-ASCII
  payloads; if piping is necessary, set and restore the sender's encoding and
  verify a known Japanese key. Stdout encoding and file encoding are separate.
* In this Python 3.14/sandbox session, `TemporaryDirectory` fixtures were created
  but their contents could not be accessed, even under the writable workspace.
  The apparent cause was the restrictive temporary-directory ACL. Normal
  UUID-named workspace directories with inherited permissions worked. The
  `fixture()` helper in `scripts/test_tooling.py` uses that pattern and verifies
  the resolved cleanup path remains under its dedicated test root. This is an
  environment workaround, not a Tyrano or CP932 failure; do not loosen game-folder
  permissions or interpret the failed fixture I/O as a failed content validator.
