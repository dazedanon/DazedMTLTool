# RPG Maker MV / MZ / VX Ace

**MV and MZ** are the JSON engines and share everything below. **VX Ace** (and VX/XP) store the same data as serialized Ruby instead, but **convert to JSON first and the rest of this file applies unchanged** - see the Ace section at the end.

| | MV | MZ | VX Ace |
|---|---|---|---|
| Indicators | `package.json` + `nw.dll`, `www/` folder | `package.json` + `nw.dll`, files at root, `game.rmmzproject` | `Data/*.rvdata2`, `Game.rgss3a`, `Game.ini` with `RGSS3` |
| Data | `www/data/*.json` | `data/*.json` | `Data/*.rvdata2` (Ruby Marshal) |
| Scripts | `js/plugins.js` + `js/plugins/` | same | `Data/Scripts.rvdata2` (RGSS3 Ruby source) |
| Encrypted assets | `.rpgmvp` / `.rpgmvo` | `.png_` / `.ogg_` | inside `Game.rgss3a` |
| Delivery | loose files over the original | loose files over the original | repack `.rvdata2` |

Text is human-editable JSON on MV/MZ - no repack, loose-file override. Decrypt encrypted variants first.

**Reference implementations** (`RP/` = `tools/Game Translation/Reference Pipelines/`):
- `RP/RPG Maker MV (Mineria)/` - **start here, and read its `PIPELINE.md` first.** A finished MV translation (2,866 units, 100%, $1.15 on Sonnet 5). `mvtl/` package: config/codes/measure/wrap/store/fileio/extract/inject/prompts/requests/parse/validate/client/driver/estimate/plugins_js/qa, plus `tools/` (`verify_structure.py` the save-safety proof, `trace_parser.py` the engine-parser harness, `seed_stock_ui.py`, `translate_save.py`, `build_release.py`, `tag_evidence.py`, `forum_post.py`), `tests/`, `docs/CENSUS.md`, and an image redraw in `images/title.py`. Font-exact widths, command-count-preserving injection, batch **and** live off one request builder.
- `RP/RPG Maker MZ (Gakuen)/` - **the MZ reference, and the one to read for
  everything OUTSIDE `data/`.** 10,665 units, 100%, $3.32 on Sonnet 5 batch.
  `mztl/` is the MV `mvtl` package re-cut for MZ (root-level `data/`, no
  `www/`). What is only here: the six-track inventory below, `PICTURE_LAYOUT` /
  `CBR_LAYOUT` (declared, guarded, *reported* layout overrides for widgets with
  no box), `audit/numablate.py` (per-rule ablation of the number-drift
  canonicaliser), `audit/cbr_fit.py` and `audit/dtext_layout.py` (pairing a
  caption with the thing drawn to its right), `images/rpgmv_crypt.py` (the
  `.png_` codec, verified against the developer's own plaintext),
  `tools/skilltree_config.py`, `tools/window_title.py`,
  `tools/install_patch_plugin.py`, and `js_plugins/GakuenTL_Patch.js` (a
  load-time repair for display text a save cached from the pre-patch build).
- `RP/RPG Maker MVMZ (BroodGeneral)/` - the MZ-flavoured pipeline (`tl.py` + `batches.py` + `rpgmvtl/`). Take its `helpwrap.py`, its `122`-display-variable subset, `clean_text.py`, `reflow_help.py`, `fix_plugin_strings.py`, `decrypt_rpgmv.py`/`encrypt_rpgmv.py`, and its native `101 parameters[4]` speaker handling, which MV does not have.
- `DAZEDTL_ROOT/` - GUI multi-engine tool with the most mature RPG Maker coverage anywhere. `modules/rpgmakermvmz.py` is the authority on per-event-code behaviour, `util/rpgmaker_qa.py` on post-translation QA, and `data/skills/*.md` on the per-game audits below. Read it before writing a new extractor.
- Decrypt/dump helpers: `tools/Game Archives/RPG Maker MZ/` (`decrypt_rpgmz_data.js`, `decrypt_rpgmz_audio.js`, `run_runtime_image_dump.js`).

---

**Later MZ adaptation findings (2026-09-07):** read
`RP/RPG Maker MZ (Gakuen)/MZ-ADAPTATION.md` alongside its `PIPELINE.md`.
It records Tropical Chase preparation checks, numbered portrait-code fixes,
and the parse-only `tools/js_literals_acorn.cjs` helper. Those preparation checks remain historical. The completed manual/no-API
translation and the later results-panel correction are now recorded in
`RP/RPG Maker MZ (Tropical Chase)/PIPELINE.md` and
[rpgmaker-mz-native-qa.md](rpgmaker-mz-native-qa.md). Start there for the
780 px native dialogue bound, index-preserving manual injection, original-text
read flags, scene-safe fixtures and a panel check that rejects the old release.

## Step 0: census the event codes before writing any extractor

Which optional codes hold text is **a property of the individual game**, not of the engine. Guessing wastes a translation pass in one direction and ships Japanese in the other. Count every code first, then decide. A census takes a minute and settles a dozen questions:

```python
# walk data/*.json -> each entry's list[] and pages[].list[], Counter on c["code"]
```

A real MZ game (48,650 translatable units) came back:

```
401 Show Text line       72,759      111 Conditional Branch   48,034
  0 (empty)              63,290      412 branch end           48,034
122 Control Variables    44,452      101 Show Text header     42,717
231 Show Picture         23,007      250 Play SE              21,566
657 plugin arg echo      12,013      357 MZ plugin command     7,377
119 Jump to Label         6,534      411 else                  6,286
402 choice branch         3,174      108 Comment                 860
118 Label                   489      408 Comment cont.            40
405 Scrolling Text            0      320/324/325                    0
```

That census immediately answered: 405 and the actor-setter codes do not exist here, `657` is enormous and needs a ruling, `122` is enormous and needs a ruling, `118`/`119` are present so labels must be protected.

**Also count `401` per file.** Dialogue does not have to live in `Map*.json`. In the game above, `401` inside all 78 map files was **zero** - every line was in `CommonEvents.json` (22 MB) and `Troops.json`. Extracting 78 empty map files wastes a pass and distorts the budget.

DazedTL codifies this as a per-game LLM audit rather than a static config: hand the model `Actors.json`, `CommonEvents.json`, `Troops.json`, `Map*.json` and `js/plugins.js`, and have it rule ENABLE/SKIP on each optional code with evidence. See `DAZEDTL_ROOT/data/skills/risky_codes.md` for the exact prompt - it is directly reusable.

---

## Step 0b: run four passes, not one

**Do not run one extraction with every code enabled.** Four passes over different file sets with different code profiles:

| Phase | Files | Codes enabled | Why separate |
|---|---|---|---|
| **0** | the ten database files: `Actors`, `Armors`, `Classes`, `Enemies`, `Items`, `MapInfos`, `Skills`, `States`, `System`, `Weapons` | **all event codes forced OFF** | Database text is in top-level `name`/`description`/`note`. Doing it first glossary-locks every proper noun before dialogue mentions it. |
| **1** | `CommonEvents.json`, `Troops.json`, `Map*.json` | `101`, `401`, `405`, `102` only | Pure display text. This plus Phase 0 must make the game playable end to end. |
| **1b** | same event files | **`111` only** | Reconcile conditional-branch string comparisons against the `122` map (below). |
| **2** | same event files | `122`, `357` by default. `355`/`655`, `356`, `108`, `320`/`324`/`325` only after the per-game audit | These hold strings the game uses as *instructions*, not display text. |

**Never enable a Phase 2 code before Phase 0 + Phase 1 alone plays through.** A translated plugin keyword, script identifier or flag value stops matching the branch that reads it, and the failure has no crash and no diff.

Keep `408` a per-game opt-in on the Phase 1 profile only.

**Store phase eligibility per injection site.** A deduplicated actor-name unit
may have a Phase 0 database site and a Phase 1 native `101` nameplate site.
Filtering only by the unit's minimum phase writes Phase 1 events during the
Phase 0 build. Extraction and synthetic preparation checks may inventory all
audited phases without authorizing a translated Phase 2 deployment.

---

## Step 0c: inventory the TRACKS, because `data/` is not all of it

`data/*.json` plus `js/plugins.js` is the usual mental model and it is
incomplete. One MZ game needed **six** independent tracks, and four of them
have no unit in the store at all. Census each before quoting a scope:

| track | where | how it is written |
|---|---|---|
| event + database text | `data/*.json` | store -> export -> game |
| plugin parameters | `js/plugins.js` | **in place**, own ledger |
| a hand-written JS config | `js/plugins/<Name>Config.js` | **in place**, span splice |
| plugin-loaded JSON | any loader-selected path, including `img/system/*.json` | leaf edits, preserving surrounding structure |
| **text hardcoded in plugin CODE** | `js/plugins/*.js` string literals | **in place**, literal splice |
| drawn note tags | `data/Map*.json` `events[].note` | **in place**, span splice |
| the window caption | `package.json`, `index.html` | **in place** |
| baked image text | `img/**` (often encrypted) | re-encrypt and drop in |

Mixing the export track and the in-place track is what makes an export silently
revert an in-place edit. Decide which track each kind of text is on and never
move it.

### Follow external data loaders, even into `img/`

`RecollectionModeMZ` resolves its configured `recoCgSettingList` as
`"img/system/" + src`. Tropical Chase's `RecollectionModeMZData.json` holds
25 gallery titles. Translate only `title`; preserve picture/thumbnail paths,
common-event IDs and switch IDs. A JSON file under `img/` belongs in the text
inventory; its directory does not make it an encrypted image asset.

### A plugin can draw text that is nowhere in its parameters

`js/plugins.js` holds a plugin's *configured* text. It does not hold text the
plugin hardcodes in its own source, and a plugin that implements a whole SCREEN
usually hardcodes most of it. Three casino minigames
(`Tatsu_HighAndLow`, `Tatsu_PokerGames`, `Tatsu_BlackJack`) shipped 100%
Japanese - bet prompts, Higher/Same/Lower buttons, hand names, the medal
counters - while every check in the pipeline reported complete, because none of
that text ever became a unit. A player found it by walking into the casino.

So scan the SOURCE of every enabled plugin, not just its parameters. Use a JS
tokenizer, never a regex: the `/*: @help` annotation block at the top of every
MZ plugin is a large Japanese comment, and only a walker that tracks
comment/string/regex state can tell it from a literal that is drawn.

**Then the real work: which literals are DRAWN and which are MATCHED?** One
game had 719 Japanese literals across 39 enabled plugins and only a minority
were display text. Translating a key breaks the game silently - there is no
error, the lookup just stops matching. Four deterministic signals find keys
before any judgement is applied; test each literal against each:

| the literal also appears in | means |
|---|---|
| a `data/*.json` **`note`** field | a notetag name |
| a code 356/357 **plugin command** argument | a command or arg name |
| a `js/plugins.js` **parameter** value | author-typed config, e.g. a call name |
| a **database `name`** (Skills/Items/States/...) | matched by name at runtime |

The last one is the easiest to miss and it must be tested against the
**pristine Japanese** database - against the already-patched `data/` the names
are English, a Japanese literal never matches, and the guard passes everything
while looking like it ran.

Two ways to get this test wrong, and both were made here:

* **Scope.** Do not test against the whole of `data/` as one blob. `大きい`
  appears in ordinary dialogue somewhere in almost any game, which would
  condemn the High/Low button that is the whole point of the screen. Test the
  four fields above and nothing else.
* **Exactness.** Even scoped correctly, `needle in haystack` is wrong - build a
  SET of the individual key strings and test membership. `所持金` ("Money",
  drawn in the shop) was condemned because an unrelated plugin declares a
  notetag named `所持金消費`, which merely CONTAINS it. Short strings are
  exactly the ones that are UI labels, so a containment test fails hardest
  where it matters most.

Building that set means unwrapping what the fields actually hold: a notetag's
KEY is the name in `<name:value>`, not the whole note; and plugin parameters
and plugin-command arguments nest JSON inside strings several levels deep, so
recurse into any value that parses, adding object keys as well as leaves.

What the signals cannot decide, code reading has to: `addCommand(...)`,
`drawText(...)`, `$gameMessage.add(...)` are display; `===`, `switch`, an
object key, or a `.find(x => x.name() === s)` is a key. Note that a string can
be **both** drawn and compared - if it is compared anywhere, it is a key.

**Write the replacement back by parsing, not by string substitution.** Patch
the literal in place preserving its quote character, serialize delimiter and backslash escapes,
then re-parse the file and read the literal's DECODED value back to confirm it
is what you intended. "The file still parses" is not the gate - a mangled
escape or an absorbed quote changes the string the game shows without ever
being a syntax error. And a plugin with a real syntax error does not warn: RPG
Maker throws at boot and the player gets a black screen.

Finally, make the release copy every plugin source the patch touched. A
hardcoded list of plugin filenames in the build script is how patched plugin
code fails to ship.

**A concatenated line is ONE string, and judging its pieces separately loses
the tail.** This ships:

```js
this.drawText('獲得枚数:' + this._dispCoin + '枚', 0, 10, ...)
```

Reviewed literal by literal, `獲得枚数:` is obviously a label and becomes
`Winnings: `, while a lone `枚` looks like a unit suffix or a key and gets left
alone - so the screen reads `Winnings: 0枚`, which is worse than before,
because now it looks like a bug rather than a language. Group literals by the
expression they are concatenated in and translate the group, and expect the
English to need a DIFFERENT number of pieces: here the counter is dropped
entirely (`en: ""`), since "Winnings:" already carries the noun.

**Always re-scan after applying, and filter to what a player could see.** The
same tokenizer, run over the patched files, with lines containing `alert(`,
`console.`, `throw`, `===` or `||` filtered out, reduced 33 remaining Japanese
literals to one - and that one was a genuine `throw` for plugin load order.
It also found the `枚` the per-literal pass had missed. The scan is the check
that closes this track; a per-item review cannot see what it never grouped.

For reference, on that game: 719 Japanese literals in 39 enabled plugins ->
393 candidates after the key signals -> 100 approved after refutation ->
102 sites patched. The ratio is the point: most literals in plugin source are
NOT display text, and a pass that translates a majority of them has misread the
code.

### Parse nested JavaScript and preserve its coordinates

`SceneCustomMenu` parameters contain JSON strings inside JSON strings, then
`ItemDrawScript` expressions with template literals. Decode each JSON layer,
parse the expression, and translate only reviewed static string/quasi spans.
Keep `${...}`, identifiers and actions unchanged; review the whole expression
so short suffixes are not classified without their displayed context.

The MZ reference's `tools/js_literals_acorn.cjs` extracts decoded literals and
template fragments without executing the game. It also reports source spans,
line and parent context; it does not decide whether a literal is displayed.
Tagged templates require separate review because tags can consume raw text.

**Extract and inject from the same byte-decoded source.** Python `read_text()`
normalizes CRLF, whereas `read_bytes().decode()` preserves it. Mixing those
paths caused `Source span changed` during the synthetic injection check.
Acorn offsets are UTF-16 indices; convert them to Python code-point indices
before splicing, including astral characters before the target literal.
Preserve the original delimiter, escape it and backslashes correctly, and
escape literal `${` in templates. Reparse and compare DECODED values after
writing. Syntax validity alone does not prove the displayed value survived.

### Note tags can be DRAWN, and the field is plugin config around them

`notes: False` as a blanket is right - a note field is configuration - but a
single tag inside it is often on screen. `EventLabel` (enabled, `showDefault`
false) renders `event().meta['LB']` as a floating caption over the event: 95
events, 62 distinct strings, and they were every room and activity label on
every map.

Two rules, and the second is the one that bites:

* **Whitelist the tag NAME, translate only its VALUE.** The name is what
  `meta[...]` is keyed on.
* **Write back by SPAN SPLICE, never by setting the field.** Assigning the
  translated value to `events[i].note` replaces `<LB:アズサの部屋>` with
  `Azusa's Room` - which does not merely drop the other tags, it destroys the
  tag itself, so `meta['LB']` is undefined and the plugin draws **nothing at
  all**. Record `start`/`count` of the value at extract time, assert the span
  still matches before writing, and apply a note's units **highest offset
  first** so two tags on one field do not shift each other. Reject a
  translation containing `>`, which closes the tag early.

### `MapInfos.json` names can be the map-name banner

`Map###.json`'s `displayName` is the banner - *unless* a plugin says otherwise.
`MapNameExtend` with `showReal: true` overrides `Game_Map.displayName()` to
fall back to `$dataMapInfos[mapId].name` whenever the editor display name is
blank. Count the maps with a blank `displayName` before ruling: 42 of 88 here,
all 42 with a Japanese MapInfos name.

Before translating them, grep for anything that resolves a map **by name** -
`FastTravel.js` does `Potadra_nameSearch($dataMapInfos, mapName, 'id', 'name')`.
Here it was safe only because that plugin is **not registered in `plugins.js`**
and therefore never loads. "Present in `js/plugins/`" is not "enabled": check
the registration, not the folder.

### `System.json` `variables` / `switches` - whitelist by ID where one is DRAWN

The default stays off: plugins and events resolve these by NAME. But a plugin
that displays a variable often draws the variable's NAME as the label beside
it - `LL_VariableWindow` does. Whitelist the specific ids, exactly like the
`122` values, and verify nothing looks a name up:
`grep -n "variables\.indexOf\|switches\.indexOf"` over `js/`.

**Also audit script assignments.** Tropical Chase has 501 code `122`
commands, but its three script operands are numerical expressions. Its display
status labels instead come from 23 code `355` assignments to variable 125,
consumed by `SceneCustomMenu`. Whitelist the producer variable ID only after
tracing display and comparison consumers; retain the assignment expression.
`LL_VariableWindow` draws only configured IDs 86 and 102 here, with a 120 px
label budget. Other editor variable names remain internal. These IDs and
budgets are game-specific evidence, not defaults.

### `js/plugins/<Something>Config.js` - a hand-written config file

Some plugins take their data from a JS file rather than from `plugins.js`
parameters, and nothing in a normal pipeline touches it. `SkillTreeConfig.js`
held every skill-tree tab and its help line as `[typeKey, label, help, ...]`
triples. **Element 0 is a lookup key** - `skt_learn`, `skt_enableType` and
`skt_disableType` all match it with
`types.find(t => t.skillTreeName() === typeName)` - and the file proves the key
and the label are independent by shipping `["剣技", "パッシブ", …]`. Translate
1 and 2, span-splice them, and assert every key is byte-identical afterwards.

### The window caption lives in `package.json` and `index.html`

`Scene_Boot.updateDocumentTitle` assigns `$dataSystem.gameTitle` to
`document.title`, but only once the engine has booted. Before that the window
and taskbar show `package.json` `window.title`, and the page shows
`index.html`'s `<title>` - both still Japanese unless you patch them. All three
must agree; take the English from the store rather than retyping it.

**And check `optDrawTitle` before giving `gameTitle` a width budget.** When it
is `false` the title screen is an image, `Scene_Title.drawGameTitle` never runs,
and the string is *only* a window caption - which has no pixel bound at all.
Capping it at some window's width is measuring against a widget that does not
exist.

### Images are usually ENCRYPTED, and the key is in `System.json`

`hasEncryptedImages: true` plus `encryptionKey` means the encrypted PNG assets
under `img/` ship as `.png_`; the image loader does not select a plain `.png`
replacement through the same path. This does not apply to plugin-loaded JSON
or other non-image files in that directory. The encrypted-image format is
positional: a fixed 16-byte header, then the real file's first 16 bytes XORed
with the key, then the rest verbatim.

Two things make this easy rather than fiddly:

* Many releases ALSO ship the plaintext - an `img.zip` beside the game with the
  same PNGs in the clear. Survey and edit from that, re-encrypt into `img/`.
  (Check whether anything references it before shipping it: on this game
  nothing did, and it was 383 MB of a 919 MB folder.)
* **Verify the codec against the developer's own plaintext before writing
  anything** - decrypt a shipped `.png_`, compare byte-for-byte with the same
  file in the zip, and re-encrypt the zip copy and compare with the shipped
  one. Both directions, on real data, or do not write.

### Installing a patch plugin into `plugins.js`

Sometimes the only fix is a few lines of JS (see `save-compatibility.md` for
the case that forces it). A structural edit to `plugins.js` is the one change
that can stop the game booting outright, so: write the `.js` file FIRST (an
entry pointing at a missing file throws at boot), append the entry LAST so it
can alias the plugin it patches, make it idempotent, re-parse your own output
before `os.replace`, and assert every other entry's name and status is
unchanged.

---

## Event codes

### Always translate

| Code | Field | Notes |
|---|---|---|
| **401** | `parameters[0]` | One line of a Show Text block. Consecutive 401s after a 101 are **one message** - join them. See the joining rules below. |
| **405** | `parameters[0]` | Show Scrolling Text. Joined the same way but **re-split one command per line on inject**. Absent in many games, real dialogue when present. |
| **102** | `parameters[0]` (array) | Show Choices. Each entry is one choice, tight width limit. Strip embedded plugin conditions first. |
| **101** | `parameters[4]` | **MZ speaker name.** See below - glossary, not a unit. |

### Translate with care

| Code | Field | Rule |
|---|---|---|
| **402** | `parameters[1]` | Choice branch label. The engine branches on `parameters[0]` (the **index**), so this string is editor-facing. Do NOT translate it as its own unit - **mirror the matching 102 choice into it by index.** Translating it separately doubles the cost and lets the two drift. |
| **108 / 408** | `parameters[0]` | Comment and comment continuation. Marker whitelist only - see below. |
| **320 / 324 / 325** | `parameters[1]` | Change Actor Name / Nickname / Profile. Player-visible when used. Check they are not being used to stash an internal id. 320 is persisted into save data, so strip `.` `"` `'` and literal `\n` from the translation or a quote breaks script evaluation on load. |
| **355 / 655** | `parameters[0]` | Script. 355 opens the block, 655 continues it, so a block spans both. See the pattern table below. |
| **356** | `parameters[0]` | MV plugin command, a single **space-delimited string** like `D_TEXT テキスト 24`. Parse by leading keyword. Known text-bearing keywords: `D_TEXT`, `ShowInfo`, `PushGab`, `addLog`, `DW_*`, `CommonPopup`, `AddCustomChoice`. Arguments are whitespace-delimited - see the space-to-underscore rule. |
| **357** | `parameters[3]` | MZ plugin command. Per-plugin argument whitelist - see below. |
| **657** | `parameters[0]` | **Context dependent, rule per game.** |
| **122** | literals inside `parameters[4]` | Control Variables. Operand type `parameters[3] == 4` is evaluated JavaScript, which may contain display strings or only arithmetic. See below. |

### Never translate

- **118 (Label) and 119 (Jump to Label).** These are control-flow targets matched by **string equality**. Translate a label and the jump silently stops matching - the event just runs past it, and nothing errors. Hard off, no override flag. A game with 6,534 `119`s has 6,534 chances to break a scene invisibly.
- **111 (Conditional Branch), except as a *signal*.** Never send a 111 to the model. Do read it, and rewrite it only by replaying the 122 map - see below.
- Asset filenames, switch/variable names, script identifiers, plugin keys.

---

### Joining a 401/405 run: the break rule, the tombstone, and the re-split asymmetry

**Merge a run of consecutive 401/405 commands into one translation unit, and cut the run at the first command whose `parameters[0]` opens with a block-level escape.**

```python
BLOCK_BREAK = r'^(\s*[\\]+[aAbBdDeEfFgGhHjJlLmMoOpPqQrRsStTuUwWxXyYzZ]+\[[\w\d\[\]\\]+\])'
```

`c`, `n`, `i`, `k`, `v` are **deliberately absent** from that letter class. `\c[2]` colour, `\n[1]` actor name, `\i[327]` icon and `\v[1]` variable are inline *content* and must stay merged.
Treat a line opening `\f[..]` or `\p[..]` as a box boundary only when the consuming plugin proves that behavior. `LL_StandingPicture` uses `\F[...]` and numbered variants to select portraits; they do not themselves create a new message box. A blanket F-code split fragments valid consecutive `401` runs.
Translating each 401 separately is the opposite failure - it destroys sentence context and wraps per line into garbage.

Stop the run early on any of: the next entry is not a dict, its code is not in the run set, or **it already carries its own `_original` marker**. That last one is the condition people miss. Without it a correction to one message silently overwrites the *next* speaker's line where two message blocks are adjacent.

**Never delete an absorbed command mid-scan. Tombstone it.** Set `parameters = []` and `code = -1`, leave it in place, and filter every `code == -1` out **once at the end of the whole scan**, reassigning the rebuilt list to `page["list"]`. Index arithmetic and the two-pass walk (collect, then apply) stay aligned only if nothing shifts during the scan. Accept `-1` as a legal continuation member when scanning a run, and convert any 401 that already carries an empty `parameters` into `-1` and skip it.

`108` joins forward over its following `408`s the same way. `355` joins forward over its `655`s.

**Write-back branches on the anchor command's code.**

- **401: the whole multi-line string, embedded `\n` included, goes into the single anchor `parameters[0]`.** Splitting it changes message-box paging.
- **405: one command per line.** The scroll-text renderer draws exactly one line per 405 command, so an embedded `\n` renders as literal garbage or mis-timed scroll. Split on `\n`, drop blanks, write `lines[0]` into the anchor, and for each remaining line insert a `copy.deepcopy(anchor)` at `j+idx+1` with `parameters = [line]` and `new_item.pop("_original", None)` so the preserved-source marker is not cloned onto the copies.

**Inserting commands invalidates the loop index. Publish a `syncIndex` and honour it.** After a 405 split set `syncIndex = j + len(lines)`, after a 401 set `syncIndex = i + 1`, and re-read it at the top of every iteration (`if syncIndex > i: i = syncIndex`). Skip it and the loop walks straight back into the English lines it just inserted and re-translates them.

The alternative discipline - wrap each 401 in place and **preserve the command count** - is what a post-export rewrap pass must do, because it runs after the structure is settled.
Both are valid, but pick one per pipeline: any change to the number of commands in an event list moves the command index a save file stores, so see `save-compatibility.md` before changing counts on a game with an existing player base.

**On a correction pass, a record spanning more than one command requires `replacement.split("\n")` to yield exactly `len(values)` lines, else raise.** A correction may rewrite the words. It must never change the display line count of a message box.

---

### Code 122: the variable-comparison trap

```json
{ "code": 122, "parameters": [startVarId, endVarId, 0, 4, "\"some string\""] }
```

`parameters[3] == 4` means a **script operand**: the engine evaluates the JavaScript stored in `parameters[4]`. It can be a quoted string, arithmetic, or a compound expression. Other operand types select constants, variables, random values, or game data; they are not direct display-text fields. In one audited game all 44,452 commands used other operand types and this extraction track was off. Count script operands, parse them, and trace their consumers before selecting literals.

**Whitelist by variable id, not by string.** Keep a compact range string per game (`'17, 26, 30, 37, 39-40, 43-49, 51-52, 59-60, 80, 85, 116, 135'`) that pastes straight into the tool, and carry the do-not list separately with reasons. A variable that is compared anywhere is excluded wholesale.

The older BroodGeneral adapter used the following conservative skip markers. They are adapter heuristics, not JavaScript syntax rules; an AST-based adapter should classify the actual expression and its consumers:

| Marker | Meaning |
|---|---|
| `gameV` | variable-of-variable indirection |
| `_` | identifier or filename |
| `"[` | array index |
| `＠` | plugin sigil |

Translate only an audited string literal or static template fragment inside the expression. Counting quote characters is not a parser and does not handle escaped delimiters or interpolation.

**Preserve the JavaScript expression and serialize each layer correctly.**
Decode the outer JSON, parse the script, splice only the approved literal,
then JSON-serialize the parameter again. Double quotes are valid when escaped
by the JSON serializer. Do not globally switch literals to backticks, strip
quotes/newlines, or double backslashes without regard to the current layer.
Preserve surrounding operators and semicolons. Reparse the script and assert
the decoded replacement value before emitting the enclosing JSON.

### Code 111: replay the 122 map, never translate it

**If the same string is also compared in a `111` `$gameVariables` test, either skip both or rewrite both from one map. Never do one alone.** Translating an assignment while its comparison stays Japanese makes a quest flag, shop gate or ending condition permanently unreachable, with no crash and no visible symptom until a player is stuck. This is the single most common way to make a translated RPG Maker game unwinnable.

Leaving both Japanese is the safe floor. The better rule is a flat file-backed `{japanese: english}` map:

- **`122` is the producer.** Every source/translation pair calls `set_var_translation(original, translated)`. **Refuse to record a pair where `original == translated`** - that is an untranslated fallback and it poisons the map.
- **`111` is the consumer.** Require `"$gameVariables" in jaString`, extract every `['\"`](.*?)['\"`]` literal, and substitute **only on a map hit**. Never send 111 text to the model. On a miss, leave the literal in Japanese: a visible failure beats a branch that never fires.
- **Ordering trap: run the `122` pass BEFORE the `111` pass.** A tool that runs 111 first leaves every branch Japanese on a first run because the map is still empty, and the map is not cleared between runs, so the bug looks intermittent. Fix the order, or run 111 twice.
- Re-read and merge the on-disk map before every write (re-read, `update`, write `.tmp`, `os.replace`) so parallel workers never clobber each other.

### Codes 108 / 408: markers, not comments

Comments are invisible to the player by default, but plugins parse comment blocks and render them. **Extract only known marker forms, matched by substring first and then by regex:**

```python
"info:"           -> r"info:([^,]+)"
"<ActiveMessage:" -> r"<ActiveMessage:(.*)>?"
"event_text"      -> r"event_text\s*:\s*(.*)"
"Menu Name"       -> r"Menu\sName\s*:\s*(.*)>"
"text_indicator"  -> r"text_indicator\s?:\s?(.+)"
"NW名前指定"       -> r"NW名前指定\s+(.+)"
"<namePop:"       -> r"<namePop:\s*([^>]+)>"
```

**A `408` is never translatable on its own merits.** Walk backward past intervening 408s and past `-1` tombstones to the owning `108` and require *that* comment's `parameters[0].strip()` to be whitelisted. In production the 408 marker set holds exactly one entry: `選択肢ヘルプ` (choice help). Everything else in a comment block is developer notes or plugin configuration, and blanket-translating it rewrites runtime directives like `<ActiveMessage:...>` and note-tag config.

**Do not infer runtime visibility from the presence of Japanese text.** Audit by inventorying every 408 value grouped with its preceding 108, then grepping the *enabled* plugin sources for the discovered tags and parsing APIs. Enumerate every suspected player-facing marker that is NOT whitelisted with its plugin consumer and block counts, and print `No unsupported player-facing code-408 markers found` rather than omitting the section.

**Space-to-underscore.** Plugin arguments and note tags are whitespace-delimited. Strip every `"` and replace every space with `_` before splicing a capture back in: `階層移動` -> `<namePop:Floor_Movement>`. An English translation with spaces turns one argument into several, and the plugin either errors or renders only the first word, on one screen only, so casual QA never sees it. Same rule on `356` arguments, where you additionally collapse `__` to `_` for every command except `D_TEXT ` (whose parser wants the doubles) and exempt `addLog` from the `.`/`"` strip because dots are safe in log text. `LL_InfoPopupWIndowMV showWindow` runs the round trip inverted - underscores to spaces before translation, back after.

**Better than an underscore, when the font allows it: U+00A0.** The delimiter is
an *ASCII* space - `Game_Interpreter.command356` is literally
`this._params[0].split(" ")` - so a NO-BREAK SPACE passes straight through the
split and renders as an ordinary word gap, where an underscore renders as an
underscore. Check the game's own font first (`fontTools`: is U+00A0 in the cmap,
and at what advance?) - M+ 1m ships it at half width, so `Lewdness +\V[2]`
draws exactly as intended. Verify by splitting the finished command and counting
the args: the plugin's declared arity is the assertion.

Read the delimiter out of the shipped `rpg_objects.js` rather than assuming it,
and re-read it after any engine update.

On write-back a merged 408 group replaces `parameters` wholesale, while an unmerged 408 does a targeted `param0.replace(source, translation)` with a newline-flattened fallback before finally overwriting.
**If a returned batch is shorter than the submitted list, or was flagged mismatched, discard the entire batch and apply nothing.** A partial apply shifts every later translation onto the wrong command, invisible until playtest.

### Code 102: choices carry plugin conditions

Choice labels frequently embed plugin visibility conditions as a lowercase `if(...)` or `en(...)` clause - as a prefix (`if(v[31]>=4)迷宮四階：図書館`), as a suffix (`▼トランテルラif(s[61])`), chained, and with nested calls (`？？？ 必要な欠片：30 en(foo(v[88])>99) if(s[278]&!s[276])`).

**Split them with a balanced-paren scanner, never a regex.** A regex ending at the first `)` truncates inside `$gameSwitches.value(1)`, producing a condition that no longer parses and a choice window that hides an option or crashes. Scan for a literal `if(` or `en(`, then walk characters counting depth to the true close. A suffix scanner accepts one or more chained clauses separated by whitespace and strips them only when the clauses run to end-of-string. **On any unbalanced or mixed input return the string untouched** (`("", source)` for a prefix split, `(source, "")` for a suffix split) so a parse failure can never delete visible choice text.

Send only the bare label to the model, then re-concatenate the exact condition bytes and force-uppercase the first character: `conditionPrefix + t[0].upper() + t[1:] + conditionSuffix`. Translating the condition turns a conditional choice into a permanently visible or permanently hidden one.

**Do NOT anchor the scanner on `\b`, and do not assume prefix-or-suffix.** A
clause is commonly wedged in the middle - `はいen(v[3]<=50)(貞操観念が50以下)` is
label + clause + a human-readable annotation - and `\b(?:if|en)\(` matches
**nothing at all** there, because Python's `\w` includes CJK so there is no word
boundary between `い` and `e`. Four choices went to the model as ordinary prose
and came back as `Yes (Chastity 50 or Below)` with the gate deleted: a
stat-gated option made permanently visible, no crash, no diff.

The robust shape is to scan for a bare `if(` / `en(` **anywhere**, balanced-paren
to its close, and replace each clause IN PLACE with an ordinary `⟦n⟧` sentinel
added to the unit's code map. That puts the condition under the placeholder
validator - losing one becomes a hard failure instead of a silent change to what
the player can pick - and it restores byte-exact wherever it sat.

**Then scan the finished output with the ENGINE's own pattern.** MPP_ChoiceEX
uses an unanchored `/\s?en\((.+?)\)/`, which is why `Yesen(v[3]<=50)` still
parses and strips correctly - but that same lack of an anchor means any English
label containing `en(` or `if(` would be silently eaten as a condition. Copy the
plugin's two regexes, run them over every injected choice, and confirm the set
it treats as conditional is exactly the set you intended.

**`parameters[0]` is a LIST, so provenance is a parallel per-index list.** `_original[i]` mirrors `parameters[0][i]`, padded with `None` for untranslated slots. **If the returned list length differs from the submitted length, write NOTHING and record the filename as a mismatch.** A length-shifted batch moves every label onto the wrong branch index, and the player picks "Yes" and gets the "No" outcome.

**Send every 102 to human or deep review unconditionally**, however clean the automated flags look. Choices are the only text where a wrong translation changes what the player *does* rather than what they read. The remaining parameters are positional indices into the choice array (`[1]` cancel type, `[2]` default type, `[3]` position type, `[4]` background), so inverting the sense of two options silently rewires which branch the cancel key takes. **Capture the branch bodies alongside the labels**: scan forward from the 102 collecting every `code == 402` whose `indent` equals the 102's, stop at the first `code == 404` at that indent, and record each branch's `parameters[0]` (index) and `parameters[1]` (label). Without those in front of them a reviewer cannot see that Yes and No were swapped relative to what the branches actually do.

### Code 657: editor echo or picture text

`657` means two different things and the counts do not tell you which:

- **Editor argument echo.** It immediately follows a `357` and restates arguments the engine already read from it, one `Key = Value` per line. Translating it duplicates every string into a field the engine ignores. Look at what precedes each `657` and at the shape of the value:
  ```
  657 preceded by [355, 357, 357] -> 'Horizontal Wave = true'
  657 preceded by [401, 357, 657] -> 'File Name = MV_Forest1'
  ```
  That is an echo. 12,013 of them, all off.
- **Picture text.** Some plugins draw `parameters[0]` straight onto a picture. Then it is prose, it is on screen, and it must be translated.

When a game does have live 657s, gate them twice rather than by shape alone: **skip any parameter containing `_`** outright as a filename or identifier, then parse the pair with `re.match(r"^'?([^=]+?)\s*=\s*(.*?)'?$", s, re.DOTALL)` and **translate only when the key is exactly `メッセージ`**. `ページ番号`, `イベントID` and `アイコンID` are internal references and writing English into them makes the plugin silently show nothing.
Re-emit the exact `f"'{kvKey} = {translatedText}'"` shape after deleting `"` and `'` from the translation.

### Code 357: whitelist by plugin *and* argument key

`parameters` is `[pluginName, commandName, label, argsObject]`. Most commands carry no text at all - 5,688 of one game's 7,377 were `PictureCallCommon` picture events. A blanket on/off is wrong in both directions. These commands carry popup, quest-log, notification and picture text that never appears in 401/102/405, so missing them ships fully Japanese quest logs under finished-looking dialogue.

Match on the **trailing plugin name by substring**, not the full string: MZ ships the same plugin as both `DTextPicture` and `triacontane/DTextPicture` depending on install path, and a full-string match silently skips half of them.

**Substring matching overlaps, so keep a per-command set of already-translated arg keys.** `TextPicture` matches inside `DTextPicture`, and without the guard the translation queue is popped twice for one command, shifting every later positional pop by one.

DazedTL's accumulated table (`modules/rpgmakermvmz.py:287`, `HEADER_MAPPINGS_357`) is the best starting list in existence - copy it wholesale and add to it:

```python
"LL_InfoPopupWIndow":       ["messageText"]    "DTextPicture":          ["text"]
"QuestSystem":              ["DetailNote"]     "TextPicture":           ["text"]
"BalloonInBattle":          ["text"]           "MM_UltimateTextAnimation": ["text"]
"MNKR_CommonPopupCoreMZ":   ["text"]           "TRP_SkitMZ":            ["name"]
"DestinationWindow":        ["destination"]    "LogMessage":            ["text"]
"_TMLogWindowMZ":           ["text"]           "LogWindow":             ["text"]
"TorigoyaMZ_NotifyMessage": ["message"]        "BattleLogOutput":       ["message"]
"SoR_GabWindow":            ["arg1"]           "NUUN_SaveScreen":       ["AnyName"]
"DarkPlasma_CharacterText": ["text"]           "EventLabel":            ["text"]
"KN_MapBattle":             ["enemyName"]      "KN_Shop":               ["goodsType"]
"KN_StillManager":          ["label"]          "Mano_CurrencyUnit":     ["unit"]
"SceneGlossary":            ["category"]       "build/ARPG_Core":       ["Text", "SkillByName"]
"TorigoyaMZ_NotifyMessage_CommandMessage": ["message"]
"LL_GalgeChoiceWindow":     ["messageText"]
```

Default the *enabled* set small (`DTextPicture`, `MM_UltimateTextAnimation`, `TextPicture`, `TorigoyaMZ_NotifyMessage`) and add a plugin only after reading its source. Resolve an unknown header by finding it in `js/plugins.js` first.

**Gate `parameters[2]` on the command name, not on the slot.** KN_StillManager's `parameters[2]` is the gallery button label only when `parameters[1] == "OPEN_GALLERY"`. For `SHOW_BY_ID` and `HIDE` that same slot is a still identifier, and translating it silently stops the gallery working deep in the game.

**Second trap: an argument whose value is a JSON string containing more text.** `LL_GalgeChoiceWindow`'s `choices` is a JSON array of objects each with a `label`. Decode, translate the leaf, re-encode. Declare these separately:

```python
PLUGIN_357_JSON = {"LL_GalgeChoiceWindow": {"choices": "label"}}
```

**Third trap: double encoding.** `VisuMZ_4_ProximityMessages` stores `params_obj["Text:json"]` as a JSON string inside the already-parsed dict, shaped `"\"\\\\{\\\\{text\""`. Peel the outer quote pair with `re.match(r'^"(.*)"$', raw, re.DOTALL)`, split the leading font-size run off with `re.match(r'^((?:\\\\[{}])+)', inner)` and the trailing run with `re.search(r'((?:\\\\[{}])+)$', rest)`, translate only the middle, downgrade `"` to `'` in the result, and reassemble as `f'"{prefix}{tl}{suffix}"'`. Losing the leading `\\{` shrinks the popup font for the rest of the scene.

**Renormalize control codes on the way out.** The model returns them at inconsistent depth, so force them to four backslashes before reassembly:

```python
re.sub(r'\\{1,3}([cCnNiIvV]\[\d+\])', r'\\\\\\\\\1', translatedText)
```

A code left at two backslashes prints on screen as a literal `\c[6]`.

Other per-arg rules: strip `"` and newlines from any 357 value because it lives in JSON, re-double `\*item` to `\\*item`, apply the `\ac` centering rule below on this path too, overwrite `parameters[3]["fontSize"]` from the map when the plugin needs it, and leave non-text arguments (`presetId`, `x`, `y`, JSON-in-string flags) alone.

**If the candidate count after filtering the whitelist against the keys actually present is not exactly 1, emit the record `unresolved` rather than picking one.** Treat any unresolved record as a hard failure of the run, not a warning, so ambiguity surfaces at build time instead of in game.

### Codes 355/655: script patterns

Display text hides inside inline JS. Extract with a per-idiom regex whose last capture group is the visible substring, and record whether the block spans 655s. Registry entry shape is `"<keyword>": (r"<regex>", <spans_655: bool>)`. DazedTL's table (`modules/rpgmakermvmz.py:318`, `PATTERNS_355655`) covers the common idioms:

```python
"$gameVariables.setValue": r'\$gameVariables\.setValue\(\d+,\s*"([^"]*)"\)'
"$gameMessage.add":        r"\$gameMessage\.add\(.+?\)(.+?)"                      # multiline
"BattleManager._logWindow.addText":
    r"BattleManager\._logWindow\.addText\(\s*(?:(?:[^()]|\([^)]*\))*\+\s*)?(['\"])((?:\\.|(?!\1).)*)\1\s*\)"
".setNickname":            r'.setNickname\(\\?"(.+?)\\?"\)'
"const text":              r'(const\stext\s?=\s?"(.+)";?)'
"logtxt = ":               r"logtxt\s=\s'(.+)'"
"テキスト-":                r"テキスト-(.+)"
"Fuki_Set":                r"Fuki_Set\(.*?\)"
```

Default the enabled set to a single pattern and make every other one opt-in per game.

**Take the text from `match.group(match.lastindex)` and splice it back by `match.span(match.lastindex)`, never with `re.sub`.** The last-group convention lets a regex wrap outer context in group 1 and still target only the display substring. Naive substitution clobbers an identical substring elsewhere in the plugin syntax and crashes the game on load:

```python
value[:m.start(idx)] + replacement + value[m.end(idx):]
```

**Re-escape the quote character of the host literal.** Inside a `'...'` continuation, `I can't` must be written back as `'I can\'t believe I fainted...\nIt\'s exactly...'` with the literal two-character `\n` preserved and every 655 row's `indent` untouched. Escape by walking the string and counting preceding backslashes so only unescaped apostrophes get one. One unescaped apostrophe in a 655 line is a JavaScript syntax error that crashes that event, and English `don't` produces it where Japanese never could.

Expose JavaScript `\n` escapes as real line breaks before handing a script string to the model, and re-escape on inject (`_decode_game_message_show_text`, `rpgmakermvmz.py:383`).

### Notetags: index the raw `note`, not `o.meta`

`DataManager.extractMetadata` keeps only the **last** occurrence of a repeated tag, but plugins that re-scan the note themselves (command tables, skill lists) use **every** one. So run RPG Maker's own pattern over the raw `note` field and index from that, falling back to `o.meta` only for values not already seen from the raw note (those were set programmatically by a plugin):

```javascript
/<([^<>:]+)(:?)([^>]*)>/g      // require m[2] === ':' and a non-empty value
valOff = m.index + 1 + key.length + 1
```

**Index each delimited sub-field with its own byte offset.** Table-style tags pack type, sort order and display name into one value - `<コマンド:スキル/5,2,高出力ビーム>`, where only the third field is ever drawn. Split the value on `/[,\/|\t\n]/` and index each part at `valOff + runningOffset`, advancing by `len(part)+1` per separator. Drop candidates that are pure numbers (`/^[-+]?\d+(\.\d+)?$/`) - ids, sort orders, icon indexes. Index each value **also** under its whitespace-stripped form, because many plugins do `data[2].replace(/\s/g,'')` before drawing.

To turn a recorded raw offset into a file position, walk the JSON-escaped string body counting one decoded char per escape sequence (`\uXXXX` = 6 source chars, other escapes = 2). That is what separates three repeated `<コマンド:…>` tags on the same note line from each other.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:672-722` (patterns and candidate rules), `:795-802` (raw-note-before-`o.meta`), `:939-977` (offset walk and `locateMetaValue`).

---

## Speaker names

- **MZ** stores the name natively in `101`'s `parameters[4]`. In one game, 24,005 of 42,717 headers had one.
- **MV and Ace** have no such field. The speaker is recovered by the cascade below.

**`\N[X]` and `\n[X]` with SQUARE brackets are actor-name substitution codes, not speaker markup.** Never count them as speaker hits. The angle-bracket versus square-bracket distinction is the whole difference, and counting `\N[3]` as a speaker makes the tool believe the game already labels every line, silently disabling the heuristics the game actually needs and shipping a whole cast unattributed.

### The author may have put the WRONG name plate on a line

A faithful translation reproduces the author's mistakes, and a name plate is
where that reads as a bug in YOUR patch rather than theirs. In one game a
couple in the library are both labelled 女子 ("girl"); the second speaks
「いいだろ？な？」, which is unambiguously masculine, and his event graphic is the
boyfriend. Rendering both as "Girl" is a correct translation of an incorrect
label, and the player reports it as a translation bug.

Screen for it DETERMINISTICALLY before spending any model time - the check is
cheap and precise. Take only units whose speaker is a GENERIC gendered label
(女子/男子/女/男/学園生/同級生/モブ...), since a named character cannot be
mislabelled this way, and flag a line whose register contradicts its label:

```
masculine-only : だろ[？?]  だぜ  だぞ  かよ  俺  てめ  じゃねー  んだよ
feminine-only  : かしら  わよ  わね  のよ  あたし  だわ  ですわ
```

Over ~4,600 speaker-labelled units this returned **two** hits, one of them the
player's report and the other a false positive worth knowing about: `のよ`
matched inside ミルク**のよ**うに. Substring matching on kana will do that -
confirm each hit by reading the line, and confirm the gender from the event's
`characterName` where the sprite filename says anything (`図書室彼女` = "library
girlfriend" settled this one).

Fix it with a PER-SITE override, never in the glossary. 女子 maps to "Girl"
correctly for the other 59 units that use it; changing the glossary to fix one
line renames every mob girl in the game. Give the unit its own
`speaker_en` field and have the speaker resolver prefer it:

```python
en = u.get("speaker_en") or store.name_en(glossary["names"].get(jp))
```

Record WHY on the unit too. A bare override looks like a mistranslation to the
next person who reads the store.

### When the game stores no speaker AT ALL

Run the arity and face census before reaching for the cascade, because a game can
have neither signal:

```
101 total: 2,596   arity 4 on all of them (so no MZ parameters[4])
                   parameters[0] (face) empty on all of them
【】 nameplates: 0   Name「 : 5 of 2,596 (noise)   trailing ： : 0
```

Every gate in the cascade below is then dead and the honest answer is "this game
does not label its speakers". Look instead for a **portrait plugin's control
code**, which is often the only per-line signal there is: a
`LL_StandingPictureMV` `\F[id]` run, a `TRP_SkitMZ` name, a bust-swap command.
Check whether all the portrait ids resolve to ONE character before trusting it -
here all 132 did, because the `C_` / `B_` / `M_` / `N_` prefixes were **costume**
variants (normal / bunny / micro / naked, matching the game's own costume menu),
not different people. Then:

> A 401 block whose first line opens with a portrait run is that character.
> Anything else gets an **empty** speaker.

That gave 1,274 attributed and 1,212 unattributed out of 2,486 - and the
unattributed half leans on the scene label instead, which is the correct failure
mode.

**One evidence-based exception is worth hunting for, and it is a per-SCENE rule,
never per-line inheritance.** Trap-encounter common events named `E<monster>接触`
carry no portrait code, because a CG replaces the portrait - but the protagonist
is the only speaker in them. Prove it over the corpus before encoding it: across
all 22 such events, **zero** lines carried a male marker
(`俺` / `てめえ` / `だぜ` / `グオオ` / `やがる` / `ぞー`) and every one read as her
first person. Because the rule keys on the scene's own name and not on "the last
101 I saw", it does not reintroduce the stateful failure below. Exclude the BAD
END events explicitly: one of them had three hero-party lines in it.

### Attribution is stateless

For a `401` or `102`, set `owner = index - 1` and decrement only while the command there is a dict with `code == 401`. If what you land on is not `code == 101`, the speaker is **empty**, provenance `none`. **Do not inherit from an earlier 101.** Stateful last-101-seen tracking is the obvious implementation and it is wrong: after a conditional branch, a common-event call or an unnamed narration box it attributes lines to the wrong character, and every downstream pronoun, honorific and register decision inherits the error.
Refusing to guess is the correct failure mode.

Extract the name by parameter arity, because half of shipped games put the name in `params[0]`:

| Arity | Display name | Face |
|---|---|---|
| `len(params) > 4` | `params[4]` (MZ shape) | `params[0]` |
| `0 < len(params) < 4` | `params[0]` | none |
| otherwise | empty | none |

Record `provenance` as `code-101` versus `adjacent-code-101` so a reviewer can see how firm the attribution is.

### The detection cascade

Look for the speaker **only on the first line of a 401 group**, and try the conventions in a fixed order, each only when the previous found nothing.

| # | Form | Test | Default |
|---|---|---|---|
| 1 | Plugin nameplate | `(.*?)\\m[\d+]\\z[\d+]`, re-run through the colour regex when the capture contains `\c` | on |
| 2 | `【Name】` | see the anchoring rule below | on |
| 3 | Colour-wrapped | `^[\\]+[cC]\[\d+\]【?(.+?)】?[\\]+[cC]\[\d+\]` with optional trailing plugin codes | on |
| 4 | Fullwidth colon | `(.+)：$` | on |
| 5 | Bare `[Speaker]` | the form your own pipeline writes back | on |
| 6 | Inline `Name「`, `Name: "`, `[Name] (` | name capped at 20 chars, `「」。、！？…\\"(:[]` forbidden inside it | **off** |
| 7 | First line of the block is the speaker | see FIRSTLINESPEAKERS below | **off** |
| 8 | Face-graphic filename | last resort, see below | **off** |

**Gates 6 and 7 stay off by default.** Turn 6 on only when some speakers lack an always-on format. Without that discipline a short opening sentence gets deleted as a name, which is unrecoverable in a shipped patch.

**The `【】` anchoring rule.** Two cases. `^\s*【([^】]+)】(.+)` means name and dialogue share the line, so strip the name and keep the dialogue. Otherwise accept a bracketed name **only** when the line starts with `【` and ends with `】` or with a run of trailing control codes:

```python
r'(?:[\\]+[A-Za-z]+(?:\[(?:[^\[\]]|\[[^\]]*\])+\])+\s*)$'
```

That admits `【名前】\n[2]` and multi-speaker `【A】【B】` while rejecting mid-sentence `【】` emphasis. For `【A】【B】` translate each name separately and re-substitute with `re.sub(r'【\s*'+re.escape(sp)+r'\s*】', ...)` rather than replacing the whole line.

**FIRSTLINESPEAKERS is not "short line".** A lone first 401 line is a nameplate only if the **next** line opens a quote. Require all of:

1. The candidate is under 40 characters and contains Japanese,
2. The following command is `401`, `405` or `-1` with a non-empty `parameters[0]`,
3. After stripping the next line's leading escape-code runs, its first character is one of `「 " ( （ * [ .`

Strip with `^((?:[\\]+[^cCnNiIkKvVSs{}]+?\[[\d\w\W]+?\]?\])+)` plus a bare `^[\\]+[\W]+?` prefix.
The negated class deliberately omits `c n i k v s` so `\v[007]\AA[N]` is not stripped away to nothing.
This accepts `メア\F[tme01]\FF[tl05]\AA[F]\FH[ON]` followed by `「また、立派なものを建ててしまった…」` and rejects ordinary two-line narration.
Too loose and the first line of every narration block is deleted as a speaker name.
Too strict and half the game loses speaker context, which wrecks pronoun and politeness choices.

**Face-graphic mapping is the last resort** because a face filename is not reliably a display name. `101`'s `parameters[0]` names a face image, and games name them after the character. DazedTL's rule (`modules/rpgmakermvmz.py:201`, `FACENAME101_MAP`): if the face string contains `_talk`, split on it and look up the prefix, otherwise match `startswith` against each key **longest key first** so `___princess2_2` does not get eaten by `___princess2`. Build the map once per game from the distinct face names. It **ignores the face index**, so any sheet holding multiple characters disqualifies it outright.

### The nameplate is three different values

Split it and use each in exactly one place.

| Value | Derivation | Used for |
|---|---|---|
| **Display name** | strip every `\X[...]` run with `[\\]+[A-Za-z]+\[(?:[^\[\]]\|\[[^\]]*\])*\]`. When that leaves nothing, fall back to concatenating only the `[\\]+[nNvV]\[\d+\]` matches | glossary key, `[Speaker]: ` transport prefix |
| **Code-locked identity** | a `\n[N]` or `\v[N]` that resolves to an actor | the prompt only. The parameter stays byte-identical |
| **Raw string** | the original parameter | write-back, replaced exactly once |

```
メア\F[tme01]\FF[tl05]\AA[F]\FH[ON]  ->  メア
\C[2]アリス\C[0]\F[tt07]             ->  アリス
\v[007]\AA[N]\F[tmi11]\FH[ON]       ->  \v[007]
\n[1]                               ->  \n[1]
```

On write-back replace **once**, trying in order: the `\C[n]…\C[n]` colour wrapper, the first `【…】` content, the display name, then the raw name. `椿\F[tt07]` plus "Tsubaki" gives `Tsubaki\F[tt07]`. Sending the codes to the model gets them translated or mangled. Stripping them from the written file kills the portrait, font or animation the plugin drives.

### `\n[N]` and `\v[N]` nameplates are code-locked

**Correction to an earlier belief: "inject rewrites `parameters[4]` from the glossary" is true only when the nameplate is a literal name. When the nameplate IS a control code, write the ORIGINAL code back, never the English name.** Detect with `re.fullmatch(r'[\\]+[nN]\[(\d+)\]')` / `[\\]+[vV]\[(\d+)\]`, resolve the actor for glossary and prompt purposes, set a `code_locked` flag, and re-emit the parameter unchanged apart from the prepended nametag. The engine resolves the code at runtime, so a hard-written name freezes the protagonist at translation time - the player's chosen name stops appearing and any later actor rename desyncs.

**Resolve `\v[N]` to an actor by scanning code 122 across every map.** Games that show a speaker through a variable fill it with Control Variables in script mode:

```json
{"code":122,"parameters":[varId, varId, 0, 4, "$gameActors.actor(1).name()"]}
```

Walk all `Map*.json` and `CommonEvents.json` for `operandType == 4` with an operand matching `\$gameActors\.actor\s*\(\s*(\d+)\s*\)\.name\s*\(\s*\)`, and map every id in `range(startId, endId+1)` to that actor.
Build the map from the **untranslated** `files/` copy in preference to the `translated/` copy, cache it module-wide with an explicit reset, and parse leading zeros as int so `\v[007]` is variable 7.
**Return None for an unmapped id and leave the nameplate unresolved rather than guessing.** Resolve `\n[N]` directly against `Actors.json`.

### Blank `Actors.json` names are player-named slots

An actor whose `name` is `""` is a slot the player fills in, not an empty record.
A raw `\N[id]` in the prompt makes the model produce ungrammatical English around it, so substitute a **deterministic per-id fake given name** from a fixed roster: Alex, Blake, Casey, Drew, Eden, Finley, Harper, Jordan, Kai, Logan, Morgan, Quinn, Riley, Skyler, Taylor.
Skip any name a real actor already uses, and fall back to `Alex{id}`. Two blank slots must never collapse onto one name.
Ids that are neither named nor blank return None and fall through to generic control-code protection.

**Do not extract speaker names as translatable units.** Register each as a glossary character. One English spelling then serves the name box, `\N[id]` references and battle-log `%1` substitutions at once. Consequence worth knowing before it alarms you: a store with **zero** translations still legitimately rewrites every literal `parameters[4]` on inject.

**"Effectively unused" is not "unused", and the difference ships on screen.**
A census may rule the MZ speaker field out - 41 of 8,368 headers here, against a
first-401-line convention that covered 4,872. That correctly decides how to
ATTRIBUTE lines, and it is the wrong conclusion for INJECTION: `Window_NameBox`
draws whatever is in `parameters[4]` whenever it is non-empty, so those 41
shipped Japanese name plates over English dialogue. Nothing per-unit can see it,
because the plate is not part of any unit's text - **the output scan found it.**
Add a glossary-driven pass over `parameters[4]` alongside the actor-name pass,
guarded the same way (a value with no English stays byte-exact, so an empty
glossary changes nothing and the no-op test still holds).

The same shape applies to a speaker written as its own rendered ROW rather than
a field. Then the plate **costs one of the window's rows** - wrap the body to
`max_rows - 1` whenever a speaker is present - and a box whose body is
`「………」` holds no source language, so a `has_jp` gate drops the whole unit and
its plate never gets translated. Extract when the body has Japanese **OR** there
is a speaker, pre-fill such a body with itself, and lock it.

For the MV inline forms, reshape `Name\nbody` into `[Name]: body` for translation and restore the original markup on inject - byte-safe both ways. Substitute an actor code into that transport prefix in **display-only form with no reverse-map entry**, or the restore pass writes a control code into the prefix.

### Picking the scheme, and not over-fitting it

**Score all three storage schemes over the event corpus before choosing one**, evaluating the 401-based ones first: INLINE401SPEAKERS (`Name「dialogue」`), FIRSTLINESPEAKERS, FACENAME101. Report per-mode hit counts, a recommended flag per mode, and a best mode, with the counts inside the reason string so a human can sanity-check.

**Collecting names is a two-pass loop.** Collect, audit, and if the audit says another mode should be on, enable it and **collect again** - the first collection was structurally blind to nameplates stored in the mode that was off. Hand harvested names to the setup model as explicitly **provisional machine guesses**, never as approved glossary decisions. A nameplate translated in isolation has no story context, and locking a wrong reading there propagates through every line.

**Prefer a three-entry data repair over enabling a global fallback.** A fallback turned on to rescue two lines mislabels hundreds, and the damage is uniform enough to look intentional in review. Before enabling face-filename attribution, inspect only messages with a non-empty face filename AND empty `parameters[4]`, exclude narration, notifications and SFX that legitimately have no speaker, and cross-tabulate each candidate filename against **all** 101 uses including those that already carry an explicit name, requiring a stable one-to-one filename-to-speaker mapping. Skip when the sheet is generic or shared, appears with multiple explicit speakers, needs the face index to disambiguate, or rescues only one or two isolated lines.

Apply a deterministic micro-repair instead when all four hold: at most three entries need the same repair, the speaker is proven by adjacent narration or the same event's explicit names (**the face filename is not proof**), the edit only fills an empty `parameters[4]` and does not translate dialogue or invent a name, and the files are writable with formatting preserved.
Then reparse, rescan, and record that the fallback is no longer needed.

---

## Control codes - mask before translating

```
\c[2]  color        \i[327] icon        \v[1]  variable value
\n[1]  actor name   \p[1]   party name  \g     currency unit
\{ \}  font size    \.  \|  \! \^       pauses / instant
\FS[n] font size    %1 %2               printf params
```

Replace each with a sentinel (`⟦0⟧`, `⟦1⟧`, …), keep a local map, restore on inject.

### A successful round trip does not prove the whole code was masked

The old alphabetical pattern masked only `\F` in `\F3[sn_01]`, exposing
`3[sn_01]` to translation. Both mask/unmask equality and a no-orphan-backslash
check still passed. Assert the MASKED shape and exact token inventory too.

`LL_StandingPicture` supports `\F`, `\FF`, `\FFF`, `\FFFF`, `\F1`-`\F8`
and `\M1`-`\M8`, including a nested variable such as `\F3[\V[1]]`.
The updated reference shares `BRACKET_CODE_PATTERN` across masking, wrapping
atoms, leading-code stripping and measurement. It handles one nested bracket
level; audit deeper or different plugin grammars separately. A nested variable
inside a portrait selector contributes ZERO displayed width. Strip the entire
portrait before budgeting variables that actually print a value. Fixing this
reduced Tropical Chase's source-width flags from 53 to 16 without changing text.
The plugin consumes these codes before the base engine's alphabetical escape
parser; inspect both layers instead of inferring grammar from only one.

### Validating restored codes

**Compare as a multiset, then compare scope pairs as an ordered list on top.** An order-sensitive comparison rejects correct translations, because English word order legitimately moves a standalone `\I[12]` or `\V[3]`. A plain *set* comparison accepts a line that emitted `\C[6]` twice and dropped `\C[0]`, which leaves every message window from that point on tinted. So:

1. `Counter(source_codes) != Counter(target_codes)`, reporting missing and extra by Counter subtraction. Spelling, parameter, count and slash-run length are all locked while position stays free.
2. Then a per-kind open/close signature that must match exactly: colour (`\C[n]` where `n == "0"` closes and any other `n` opens), font size (`\{` open, `\}` close), speed (`\>` open, `\<` close).

**Mask already-restored codes out of both strings before running the generic code regex.** Search for each known restored value by exact string and blank it to an equal-length run of spaces. An unparameterized code restored directly against English (`\vcThat's`) is otherwise greedily eaten by a generic pattern as the invented code `\vcThat`. Report a masked code that went missing as its own error class ("missing protected codes") *before* the generic comparison runs, so the diagnostic names the real problem.

A mismatch is a hard failure that retries.

### Bare letter escapes eat the following Latin word

**MV/MZ lex an escape as `\` plus a run of letters, so `\acWhat` parses as one unknown code named `acwhat` and the word is never drawn.** Japanese never trips this because kana terminates the code. Translating into English is what *creates* the bug, and it survives every text-level check: token counts match, no residual Japanese, the JSON diff is clean, and the first word is simply invisible in game. It silently blanks centred credits, chapter titles and system messages.

- Detect with `re.compile(r"\\(?:ac|cl)(?=[A-Za-z])", re.IGNORECASE)` over the **whole live string**, not just its start, so occurrences after an embedded `\n` are caught.
- **Fix by inserting a space, never by deleting the code.** `\ac\C[6]` is already self-delimiting and needs nothing.
- **Generalising that fix is where it goes wrong: the lexer is GREEDY, so the
  repair has to know the code NAMES.** A rule shaped "insert a space after the
  escape letter" splits every MULTI-letter code down the middle. `\gold` - the
  notify-message money insert - became `\g old`, and the shipped notification
  read **"Got G oldG!"**: the gold value, the literal word "old", then the
  currency unit. `\name` became `\n ame` and `\count` became `\c ount` the same
  way, and `\ac` splits into `\a c`. Match the whole `[A-Za-z]+` run, compare it
  against a table of the escape names this game actually defines (engine plus
  plugins), longest first, and split after that name - returning the run
  untouched when it IS a name, or when no known name prefixes it.
- Hide it from the model entirely: `centerLineFlag = bool(re.search(r"\\ac", src, re.I))`, delete `\ac[ \t]*`, translate, **wrap**, then re-emit in front of every non-blank output line:
  ```python
  "\n".join(f"\\ac {l}" if l.strip() else l for l in out.split("\n"))
  ```
  Re-emit **after** wrapping, or the wrapper counts the code as visible characters and can break the line between `\ac` and its text. A model told to preserve the code will happily emit `\acWhat`.
- Centering is per line, not per string. For a 401 whose *source* contains `\ac`, split the result on newlines, drop blanks, and require every remaining line to match `^\s*\\ac(?=[^A-Za-z]|$)`.
- Keep the untouched source, leading newline and bare `\ac` included, in `_original`.
- Two standing QA checks, because any later rewrap that adds a line reintroduces it: `unsafe-bare-center-code` (bare `\ac` directly against a Latin letter) and `missing-center-alignment` (a wrapped line that lost its `\ac`).
- Same treatment on the 357 plugin-argument path.

### Orphan backslashes manufacture new control codes

**Protect a bare backslash run that sits immediately before a word character, even when it is not a control code.** `\ヘレン` is inert at runtime because ヘレン is not ASCII, but the model translates it to `\Helen`, which RPG Maker then parses as a real code and eats. The line vanishes and **no validator fires, because the source held no code to compare against.**

Add `[\\]+(?=[^\W\d_])` to the protected-pattern set as a token in its own right, alongside the real codes.

**Escape on the write path only.** When restoring for the final file, append one extra backslash to any slash-only replacement whose length is **odd**, so `\` becomes `\\` and renders as one literal backslash instead of opening a command. Restoration done purely for validation must NOT escape, or the multiset check compares against a string the player never sees. Values coming back from a cache or from an already-patched file carry the doubled form, so every re-protect and mask step must try the **escaped form first** and fall back to the raw form.

### Codes that expand to a word need spaces in English

`\n[1]`, `\p[1]`, `%1` insert a noun.
Japanese sets no space around one, so a faithful translation keeps none and the player reads `NeroIs that alright?`. Split sentinels into word-inserts (pad) and everything else (`\.`, `\|`, `\c[n]` - never pad), and skip padding next to an apostrophe or hyphen so `⟦0⟧'s` stays tight.
Enforce it on inject, not only in the prompt: the insert is often peeled into a prefix the model never sees.

### Actor-code substitution around the model call

`\n[1]`-style actor references are best **unmasked to the actual actor name before translation** so the model has context, then re-masked - the name flows through the glossary either way. Record a per-item reverse map and restore with **two ordered regexes over the names sorted longest-first**:

```python
r'(?<=[A-Za-z0-9])(names)(?![A-Za-z0-9])'   # glued form FIRST - the model re-glues "PlayerAlex"
r'(?<!\w)(names)(?!\w)'                      # then word-bounded
```

**Stop the fusing at source too.** Prepend a space to the substituted name when the preceding character is ASCII alphanumeric, or when the preceding text already ends in another `\[nNvV]\[\d+\]` code - a one-pass `re.sub` cannot see its own earlier replacement. So `なんでPlayer\N[4]` -> `なんでPlayer Alex` and `\N[3]\N[4]` -> `Player Alex`. Skip the space guard and the restore regex never matches, so the player's chosen name silently disappears from the patched line. A plain `str.replace` on the way back corrupts any sentence using the same word in prose.

### Pre- and post-model sanitation of a 401 group

Pre-pass, before the model sees the joined group:

- Drop `ﾞ` and fullwidth `　`, convert corner brackets, `\,` -> `,`.
- Flatten furigana two ways or the output carries doubled readings: `[\\]+[rR][bB]?\[(.*?),.*?\]` keeps group 1, and `\{([^|{}]+)\|[^|{}]+?\}` keeps the base of `{base|reading}`.
- **Hoist the leading presentation-code run into a nametag and re-prepend it after translation**, but never hoist `\c \n \i \k \v`:
  ```python
  r'^((?:[\\]+[^cCnNiIkKvV{}]+?\[[\d\w\W]+?\]?\])+)'
  ```
  The negated class excludes colour, actor name, icon, key and variable because those are *content* that must stay inline. `\F`, `\FF`, `\AA`, `\FH` and `\M` are presentation prefixes the model would paraphrase or drop.
  Follow with a second pass stripping bare escapes at the start (`\mn\tmn|\tmn|\mn|\vc`) and a third stripping a literal `_ABL` prefix, accumulating all of them into the same nametag.
- **Derive the model input from the stored source, not from the current parameter.** That is what makes the pass *repair* a file already carrying a doubled `\F4[2]\AA[4]\M4[yes]\F4[2]...` prefix from an earlier buggy run instead of tripling it.
- Remove `\CL`, `\#`, `\px[200]`. Treat `\>` as an instant-line flag and re-apply it as a `\>` prefix to **every** wrapped output line.

Post-pass on the translation:

```python
r'\.\.\.(。)+'          -> '...'
r'([!?])([A-Z])'        -> r'\1 \2'   # JP sets no space after ！/？ so the model omits it
r'([^\s\\])((?:\\[.!|^])+)' -> r'\1 \2'   # one space before a whole RUN of pause codes
'"- "'                  -> '"-"'
```

Match the pause codes as a **run** so no intra-run spaces appear.

### Cosmetic cleanup

Strip stranded sokuon (っ/ッ) left in English (`Nhagiッ!` -> `Nhagi!`), normalize `「」『』` to `"`, ignore full-width `　` indentation. **Guard every whole-file cleanup pass on "is this still Japanese"** - see the no-op inject test below.

---

## Word wrap: measure it, never quote a default

Three sources inside the game give the exact number and they cross-check each other. Do all three.

**1. `data/System.json` -> `advanced`:**
```json
"mainFontFilename": "mplus-1m-regular.woff", "fontSize": 30,
"uiAreaWidth": 1280, "screenWidth": 1280
```

**2. Open that font with fontTools and look at the advance-width histogram.**
```
unitsPerEm 1000
  advance 1000  (30.00px at fontSize 30)  6,607 glyphs   <- full-width CJK
  advance  500  (15.00px at fontSize 30)  1,489 glyphs   <- half-width Latin
  advance  364 / 333                          2 glyphs
```
Two spikes and nothing else means the font is **genuinely monospace**, so cell counting is exact at 15.00px per half-width cell. A proportional font shows a spread instead, and then a character-count wrap must use a measured average of representative English glyphs, stated explicitly. Never copy a pixel figure into a character-count setting.

**3. The message plugin's *configured parameters* in `js/plugins.js`** - not its source defaults, which are usually overridden:
```
NRP_MessageWindow: WindowWidth = Graphics.boxWidth      (1280)
                   WindowHeight = this.fittingHeight(3) + 8   <- 3 rows, not the stock 4
                   AdjustMessageX = 178
```

Usable width = `1280 - 178 (AdjustMessageX) - 24 (window padding, 12/side)` = **1078px**. `1078 / 15 = 71.8` -> 71 cells, configured at **70**.

**Cross-check against the author.** Histogram the visible cell width of every shipped `401`. A hard ceiling at your computed number confirms it.

### Message height may depend on a game variable

Trace the height expression and every assignment to its input. Tropical Chase's
`NRP_MessageWindow` uses `$gameVariables.value(103)`: 34 assignments select
144 px, while one tutorial assignment selects 192 px. With this game's line
metrics, the normal budget is three rows and the tutorial allows four.
Its static body-width budget is `816 - 24 - 4 = 788` px with M+ 1m regular at
26 px. These are measured source-profile facts, not universal MZ defaults.
Keep source overflow and missing-glyph findings separate from English fit QA;
do not silently clip, shrink or apply another game's four-row assumption.

### Faces and portraits reserve width

`101`'s `parameters[0]` is the face image name, and a non-empty one steals roughly 168px, which is a *different* wrap width for those lines. Count it rather than assuming:

```
101 total: 42,717   with face graphic: 0
```

Zero here, so `face_width == width` and that code path is dead. Nonzero means maintaining two widths and selecting per message group, tracking the face **forward** across the 401 block that follows the 101.

**A plugin portrait drawn as a picture reserves the same space with no `101` signal at all.** The face-graphic count will not see it. Look for portrait plugins in `plugins.js` and treat their scenes as exceptions needing a conservative width.

### Horizontal and vertical are simultaneous constraints

The message window is fixed-height, which is the normal case here: `fittingHeight(3)` hard-codes three visible rows. A fourth row is clipped or spills into another box, so **row count is a hard constraint, not a cosmetic one**. `text-fitting.md` has the general treatment.

So the two constraints fight.
**Narrowing the wrap to fix a horizontal overflow produces more lines and makes a vertical overflow worse.** A recommendation is only valid when every rendered line fits horizontally *and* the rendered row count stays within the window's visible-row limit.
Test both, on representative short, long, icon-heavy, code-heavy and font-changed values.
If nothing satisfies both, the answer is pagination, manual reflow, or raising the window's own height - not a narrower wrap.

Distinguish fixed/clipped windows from scrolling, paging and auto-sizing ones before applying any of this. Only the fixed ones have a hard row limit.

If the game uses an auto-wrapping plugin (YEP_MessageCore and friends), do not hard-wrap yourself. Just avoid emitting manual `\n`.

### Rewrap is a separate pass over exported data, and it needs four widths

| Width | Applies to |
|---|---|
| `dialogue_width` | plain 401 blocks |
| `face_dialogue_width` | 401 blocks under a 101 with a non-empty face graphic |
| `list_width` | `122` / `324` list and help text |
| `note_width` | note fields |

**Handle 401 and 405 asymmetrically here.** A 401 is a command boundary, not a rendered row, so wrap each one in place and preserve the command count - merging 401s to rebalance lines corrupts the event structure a save file indexes into. 405 rows are one block: join with `\n`, rewrap, redistribute across the commands.

**Veto rather than apply when the rewrap overflows the window.** Set `max_protected_rows` from the game's own measured row limit (stock is 4, the game above is 3) and **reject and count** any result that renders more rows. The extra row is simply never drawn - no crash, no diff, invisible.

Count rendered rows by splitting on `\n` and `<br>`. Do not count a name-window control prefix as a row.
Do count a literal `[Speaker]` first line.
**Default to touching only lines already over the limit**, measured with the same control-code-aware counter the wrapper uses (`<br>` and `\n` are breaks, but `\n[` is an actor-name code and is not), so text that already fits stays byte-identical.
Preserve `<br>` where the source used `<br>` with no real newline, keep a leading speaker prefix outside the wrap, and split on `\n\n` first so hard paragraph breaks survive.

---

### Captions with no box at all: the budget is in a DIFFERENT command

The wrap widths above cover windows. A large share of an RPG Maker game's UI is
not in a window: it is text drawn at an absolute x/y, whose only bound is
whatever is drawn to its right. Nothing in the caption's own record mentions
that neighbour, so no per-unit width check can ever see it.

Two shapes, both common:

**`DTextPicture`** draws in a PAIR of commands - a `357 dText` prepares the
string, and the **next `231 Show Picture` with an EMPTY picture name** renders
it at that command's x/y. So to budget a caption you must walk the event list
pairing each `357` with the `231` that follows it.

**A script-block screen** (`CBR_EroStatus` and friends) builds a whole page out
of `355`/`655` rows of the form `<key>-<value>`, grouped one entry per
`テキスト-`: `テキスト-オナニー回数：`, `x-60`, `y-200`, `サイズ-20`, `左右-右`.
The coordinates are ordinary string leaves, so *moving* one needs no structural
exception - which makes "raise the bound" cheap here.

Authors budget these to the pixel, so English has no slack:

```
label 性感帯：  4 full-width glyphs at fontSize 32 = 128 px, drawn at x=172
value          drawn at x=300
172 + 128 = 300     exactly touching, zero slack
```

"Erogenous Zone:" is 240 px and lands 112 px on top of the value.

**Three modelling facts, every one of them learned by running the checker
against the JAPANESE source and watching it accuse the author** (61 flags, then
7, then 0 - see the SKILL rule):

1. Captions sharing one `(page, y, x)` are mutually-exclusive VARIANTS of one
   slot, chosen at draw time by game state. One column, as wide as its widest
   variant - not a stack of colliding columns.
2. A right-aligned caption (`左右-右`) is drawn ENDING at its x and grows
   LEFTWARD, occupying `x - width .. x`. The budget for the caption to its left
   stops at `x - width`.
3. Two captions on one row can belong to DIFFERENT screens that share y
   coordinates. That one cannot be derived statically - which is the argument
   for a **differential** check plus a per-slot waiver carrying its evidence.

**Fixing it: raise the bound where you can, shorten where you cannot.** The
value column's x is a plugin-drawn picture's own parameter, so moving it from
300 to 430 buys the label 258 px against the 240 it needs - far better than
abbreviating three labels into meaninglessness. Where the row is genuinely
tight, shorten to the MEASURED character budget and record the number in the
comment. Either way the override belongs in a **declared table** that is
guarded on the value it expects to find (so a re-run is a no-op and a game
update is a loud failure) and that both the structural verifier and the no-op
test accept **by exact path and print** - never as a tolerated class.

**A number between two fixed captions costs a reserve, not a gap.** `(Loop Count
\V[40] time(s))` has to place its closing text far enough right to clear the
widest value the counter can reach, so a one-digit value shows the difference as
empty space. That is inherent, and the Japanese has it too. Size the reserve
from the data - `grep` the writes and comparisons of that variable - rather than
from the measurer's default.

---

### MV `drawText` SQUEEZES, it does not clip

`Bitmap.prototype.drawText(text, x, y, maxWidth, ...)` scales the text
horizontally to fit `maxWidth`. An over-long label therefore renders **visibly
compressed** rather than cut off or erroring, which is why a squashed menu label
survives every automated check and every screenshot skim. Measure the widget's
declared width, do not wait for something to look wrong.

Where the widget's bound is itself a plugin **parameter**, raise the bound instead
of compressing the English. Where it is hardcoded in the plugin source - the
`TMMenuLabel` status window returns a literal 240 - abbreviate on the **widget
only** and keep the full term in prose, and record that as a decision in the
glossary so the publication-time consistency audit does not read it as drift.

### A gauge that silently drops half its readout

`TMMapHpGauge.drawVnCurrentAndMax` is the shape to look for:

```js
x3 = x + width - valueWidth - slashWidth - valueWidth;
if (x3 >= x + labelWidth) { draw current, '/', max } else { draw current }
```

The `/max` half is **dropped without an error** the moment the label plus the
numbers no longer fit. At fontSize 25 a half-width cell is 12.5px, so `淫乱度`
(3 full-width glyphs, 75px) cleared the 82.5px budget at `width: 195` and
`"Lewdness"` (8 half-width glyphs, 100px) did not - the English build would
quietly lose the maximum from the HUD. Widening `gaugeA.width` to 250 and moving
`gaugeB.x` to match is a three-value edit; shortening the word is not.

Any "draw the label, then right-align the value, unless they collide" widget has
this property. Grep the plugin for a conditional around the value draw.

### Seed the stock UI from the engine's own English, and LOCK it

`System.json`'s `terms` are unchanged RPG Maker boilerplate that ships with the
editor in both languages. Fill them from the engine's published English and mark
those units `locked` so no pass touches them: 96 units on the reference game,
**zero API calls**, and better than any model pass. A model asked to translate
`最強装備` in isolation returns "The Strongest Equipment Set", which is correct
and wrong.

Two mechanics the seeding needs:

- **Write the table in readable `%1` / `\G` form and convert to the store's
  sentinels at seed time**, longest-code-first, consuming each sentinel once, or a
  code the source uses twice collapses onto one.
- **`%1 %2 %3` are `(name, parameter, value)`** in that order - `Window_BattleLog`
  formats them as `fmt.format(target.name(), TextManager.hp, value)`. Keeping the
  canonical order is what stops a battle line reading "Mineria recovered 100 HP"
  where the engine substitutes "HP" into `%2`.

### A plugin parameter that is a LOOKUP KEY into another translated field

`LL_MenuScreenCustomMV.menuHelpTexts[].symbol` is read as
`menuHelpLists[this._commandWindow.currentName()]` - keyed on the **displayed
command name**, which comes from `System.json terms.commands`. Translate the
command and leave the symbol and every menu help line silently disappears; there
is no error and nothing to see except an empty row.

Declare that dependency as a **mirror** and assert it in CI:

```python
MIRRORS = {"LL_MenuScreenCustomMV.menuHelpTexts[].symbol": "System:terms:commands"}
```

The general shape - a plugin parameter whose value must equal the English chosen
for a *different* file's field - is common and invisible. Grep enabled plugins for
`[` indexing by a `.name()` / `currentName()` / `currentSymbol()` result.

## Database and `System.json`

Phase 0 covers `name`, `description` and `note` on the ten database files. `System.json` needs per-field rules:

- **`switches` and `variables` stay untranslated by default.** Plugins and events resolve them by NAME as string keys. Translating them breaks quests in a way that looks like random game logic failure rather than a translation bug.
- **`terms.messages` is handled separately from the rest of `terms`** because its values carry `%1`/`%2` runtime substitutions. Remove `.`, `"` and literal `\n` from every translated battle message - a stray quote corrupts the JSON escape level and a literal `\n` splits a battle message mid-render. Normalize the common model rewrite of `escapeFailure` from `but couldn't escape!` back to the canonical `But escape failed!`.
- The other lists (`armorTypes`, `skillTypes`, `equipTypes`, `elements`, `weaponTypes`, the `terms` categories) get `.replace('"','').strip()`, and **collect only the entries that need translation while preserving their original index**. Slot 0 is usually null or empty, and shifting it renames every type by one.
- Strip a trailing `.` from `gameTitle`.

---

## Plugin parameters

`js/plugins.js` holds a large fraction of the UI text and none of it is in `data/`. Each entry is `{name, status, description, parameters}` where `parameters` values are **strings**, including ones that are really JSON: nested objects, arrays of JSON strings, and `struct<>` types serialized as a string.
Parse, translate the leaves, re-serialize with the same escaping.
Only touch parameters of **enabled** plugins (`status: true`). Preserve filenames, switch/variable IDs and key names. A JS expression stays structurally unchanged; translate only its separately audited display literals using a parser and decoded-value readback (see the nested-JavaScript section above).

### Beautify before a legacy line-based pass

The following formatting recipe is for legacy line-based adapters. A structural
adapter should parse the shipped bytes directly and preserve untouched spans;
it needs no beautification. Keep its immutable snapshot unformatted so an empty
build can prove byte-exact identity.

**Shipped `plugins.js` packs the whole `$plugins` array onto one to three physical lines.** A line-oriented extractor then sees every parameter of a plugin as one string, and any `data[i].replace(orig, tl)` rewrites every identical Japanese substring in every plugin at once. Per-line regex scoping (drawTextEx-only matches, brace-counted regions) is impossible while the file is one line.

Run jsbeautifier first with exactly:

```python
indent_size=2, indent_char=' ', max_preserve_newlines=2,
preserve_newlines=True, end_with_newline=True
```

Rewrite in place as UTF-8, and use that identical option set in **every** tool that touches the file so a GUI formatter and programmatic edits converge on one canonical layout.
Order is fixed: beautify, then extract and translate line-wise, then ship the beautified file.
RPG Maker does not care about whitespace here, so the reformat costs nothing.
For that legacy line-based workflow, format before recording any extraction offsets. Do not apply this prerequisite to structural adapters.

### Structural edits go through `raw_decode`, not `json.load`

The file is `var $plugins = [ ... ];` - JSON embedded in JS with a trailing semicolon. A `json.load`/`json.dump` round trip reformats every unrelated entry and destroys the diff. A regex edit can leave a double comma that makes RPG Maker load **zero** plugins.

Locate the array with a literal `var $plugins\s*=` followed by `[`, call `json.JSONDecoder().raw_decode(content, array_start)` for the whole array, assert the trailer lstrips to `;`, then walk element offsets calling `raw_decode` per entry and **store each entry's original raw substring** so untouched entries stay byte-identical after a rewrite.
Enforce exactly one comma between entries, that every element is an object, and that entry count equals value count.
Recover indentation from the file itself (item indent, falling back to closing indent plus four spaces).

Before committing, re-parse your own output, re-check every `name` is a string, and assert the target plugin appears exactly once (zero times if removing), raising rather than writing on any failure. Repair the known corruption of a leading comma immediately after `[`. When installing a plugin, write the plugin file first and roll it back byte-for-byte if the `plugins.js` write fails.

### Escaping depth: extraction is depth-agnostic, write-back is not

Array-of-struct parameters store each entry as a JSON string inside a JSON string, so the same leaf sits at 1, 3 or 7 backslashes depending on nesting. A fixed-depth regex silently extracts zero strings from a deeply nested plugin. **Anchor on the known key name and let a `[\\]+` run absorb whatever depth applies:**

```python
r'[\\]+"QuestName[\\]+":[\\]+"(.*?)[\\]+"'
```

Same shape works for `QuestClientName`, `QuestLocation`, `PlaceInformation`, `ObjectiveContent`, SceneCustomMenu `Text`, `CommonHelpText`, `HelpText`, and NUUN_SaveScreen `ParamName`. A leaf one layer deeper needs the doubled quote pair: `r'[\\]+"QuestContent[\\]+":[\\]+"[\\]+"(.*?)[\\]+"[\\]+"'`. The same trick reaches choice labels inside a 357 payload: `r'"label[\\]*":[\\]*"(.*?)[\\]'`. **Always anchor on a parameter or struct member key you have enumerated.
Never run a blanket "find Japanese in the file" scan over plugin source.**

**On write-back, re-emit escapes at the exact backslash count that leaf uses.** Count the run in the source for that specific key and reuse it. Do not normalize the file to one depth.

| Field | Newline token | Colour code |
|---|---|---|
| shallow non-JSON parameter | `\n` (1 backslash) | - |
| `QuestContent` | 8 literal backslashes + `n` | 16 backslashes + `c`, normalized to `\c` for the model and back up on write |
| `ObjectiveContent` | 32 literal backslashes + `n` | - |

Wrong depth produces either a visible literal `\\\\n` in the quest window or a real newline that breaks the enclosing JSON string, and RPG Maker then fails the whole plugin parameter parse at boot.

### Quote neutralization differs by container

An unescaped apostrophe from an ordinary English translation ("Adventurer's Guild") terminates the JS string literal and the plugin throws at load, black-screening the game.

```python
# JSON-encoded struct leaves (quest fields, SceneCustomMenu Text/HelpText, ParamName)
translatedText = translatedText.replace('"', "'")
translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

# raw JavaScript source, where the enclosing quote character is unknowable
# -> replace BOTH ' and " with U+055A ARMENIAN APOSTROPHE (՚), same negative class
```

That `[^\\']` class is load-bearing: it leaves already-escaped `\'` and doubled `''` alone, so the pass is idempotent and safe to re-run over a partially processed file. Labels landing inside single-quoted template segments (drawTextEx text) only need `"` -> `'` with no escaping.

### Scope a greedy scan to a brace-counted region

Free-floating Japanese arrays inside plugin JS (`this.disp_list = { key: { sub: ["str1","str2"] } }`) are reachable only by a greedy scan, and a global one also hits note-tag keys, switch names and `$gameVariables` lookups that code reads back, breaking game logic.

Open the region on a known anchor token (`if 'data_map_name_list' in line: in_region = True; brace_count = 0`), track `brace_count += line.count('{') - line.count('}')`, and close when `brace_count < 0`, which is exactly when the enclosing object's closing brace arrives.
Inside the region use a **narrower** Japanese class than your global one - `r'"([^"]*[一-龠ぁ-ゔァ-ヴー]+[^"]*)"'`, no fullwidth alnum, no halfwidth katakana - so identifier-like fullwidth tokens are not swept up.
Write back by re-quoting the whole literal, `line.replace(f'"{orig}"', f'"{tl}"')`, after escaping `"` in the translation, and rewrap only when the original contained `\n`. Region scoping is what makes the greedy pattern safe at all.

### Collect, then replace longest-first

**Never replace as you match when several source strings share one physical line.** Accumulate `original -> translation` into a dict during the match loop, skipping any original already queued, then after the loop:

```python
for orig in sorted(pending, key=len, reverse=True):
    line = line.replace(orig, pending[orig])
```

The concrete failure: replacing `回数：` before `使用回数：` corrupts the longer label into `使用<English>`, and the damage is invisible until that menu is opened in game.
If the collection pass and the writeback pass both dedupe, **the dedupe must be symmetric on both sides** (`if s.strip() not in seen`) or a FIFO queue of translations desynchronizes and every later label receives the wrong text.
Applies wherever one line carries several related labels: plugin source, CSV rows, script lines, concatenated UI expressions.

### Translatability gates

Gate every candidate through four filters before it reaches a queue:

```python
LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ]+"   # fullwidth Latin + halfwidth katakana included
if re.search(r"^[\\]+$", s): continue          # captured only a backslash run
if not s.replace("　", "").strip(): continue    # ideographic-space padding, not text
if '$gameVariables' in s: continue              # interpolated code fragment
```

A plain kana/kanji class is blind to fullwidth UI labels.
The backslash-only artifact is standard for a `(.*?)` sitting between two `[\\]+` groups, and feeding it to the model returns real English for it and shifts every later positional pop by one.
Where a pattern spans control codes, exclude structural characters from the capture class itself so a capture can never run past a delimiter: `r'C\[\d+\]([^C\\,`\[\]]+?)[\\]+C\[0\]'`.

---

## The `_original` sidecar

**If you translate in place instead of through an external store, keep the Japanese in the same file under an `_original` key the engine ignores.** Without it a second pass feeds English back to the model, glossary corrections cannot be re-applied, the rewrap pass cannot tell a control code from source text, and QA has nothing to diff against.

### The dual-read invariant

- **Translation input comes from `_original`** when it holds a non-empty string, falling back to `parameters[i]`.
- **The skip decision comes from the LIVE parameter**, never from `_original`.

Getting these backwards produces the two classic failures. Skip-checking `_original` re-translates the whole game on every run, because the stored source is always Japanese. Sourcing from `parameters` feeds English back into the model on pass 2, degrading text every run and destroying honorifics and control codes with no recoverable source.

**`_original` is write-once.** If the slot already holds a non-empty value, return early. Otherwise the second pass overwrites the Japanese with the first pass's English and the game is permanently un-retranslatable.

Run corner-bracket normalization **before** the "is this still Japanese" test, so a decorative CJK wrapper such as `〝phytoncide〟` around English does not count as untranslated source. Gate database and `System.json` writes on the raw value actually containing Japanese.

**Regression-test it by running the whole extractor twice.** The second pass must make zero translation calls, zero speaker lookups, and produce a byte-identical structure.

### Four node shapes

| Shape | Where | Form |
|---|---|---|
| scalar string | single-text codes | `_SCALAR_ORIGINAL_PARAMETER_BY_CODE = {108:0, 320:1, 324:1, 325:1, 355:0, 356:0, 655:0, 657:0}` |
| positional list | code `102` choices | `_original[i]` mirrors `parameters[0][i]`, `None` padding for untranslated slots |
| sparse path-mirrored dict | codes `111`, `357` | list indices become string keys: `{"parameters": {"3": {"text": "ログ表示"}}}` |
| field-keyed dict | database entries, `System.json` | `_original["armorTypes"]["1"]`, `_original["terms"]["basic"]["1"]` |

Build the sparse tree by walking the before and after parameter trees together, recording a leaf **only when `before.strip()` is truthy AND `before != after`**, and merge into an existing tree without ever replacing an existing leaf.

**Consequence for any QA or patch tool: presence of `_original` proves a field was CHANGED, not that it was reviewed.** A plugin argument the pipeline never touched has no entry. Code that assumes `_original` is always a string crashes or silently skips the riskiest commands.

Every walker must `continue` on the key and every node clone must pop it, or the sidecar leaks into output or gets translated as content.
A QA correction pass **writes only the live field, never `_original`**, and addresses a string by a stable identity of the form `File.json#<json-pointer>` (`Items.json#/1/description`) rather than by index, so an unrelated entry sharing the same source string is left alone.

---

## Inject and deliver

Write translated strings back into the JSON preserving key order and structure, and ship `data/*.json` (MV: `www/data/`) as **loose files over the original**. The game loads them directly, no repack.

On a Japanese OS, force locale to `en_US` in project metadata so text renders correctly, and bundle the MSVC runtime DLLs if the game needs them.

### Re-render in the file's own serialization conventions

**RPG Maker ships `Map001.json` as a single minified line and some data files with a UTF-8 BOM.** `json.dump` defaults turn a three-string fix into a whole-file diff, which breaks binary patch distribution and makes review impossible.

```python
raw = path.read_bytes()
has_bom = raw.startswith(b"\xef\xbb\xbf")
decoded = raw.decode("utf-8-sig")
m = re.search(r"\n([ \t]+)[\"\[\]{}]", decoded)
indent = m.group(1) if (m and "\t" in m.group(1)) else (len(m.group(1)) if m else None)
# indent None -> separators=(",", ":")
```

Always `ensure_ascii=False`, or the file inflates into `\uXXXX`. Read everything with `utf-8-sig` so the BOM never leaks into a key, re-prepend the BOM if it was there, restore `\r\n` if the decoded original ended with it, and restore the trailing newline.

### Write incrementally and atomically

Create the temp file **in the destination directory** so `os.replace` stays on one volume (`tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir="translated")`), open it with `newline="\n"` so Windows does not turn every `\n` into CRLF inside a JS or JSON file, serialize the replace across worker threads with a lock, and retry `os.replace` 5 times with `time.sleep(0.1 * (attempt + 1))` on `PermissionError` - that is the Windows antivirus and indexer race, not a bug in your code.
Never hold the destination file open while translating.
Throttle so a pass that consumed nothing does not rewrite.
For a structural edit to a file the game must parse at boot, add `handle.flush()` plus `os.fsync`, preserve the original `stat.S_IMODE`, and refuse to write when the path is a symlink or not a regular file.
An interrupted run that leaves `plugins.js` truncated means the game will not boot, and CRLF injection produces a file that looks fine locally and is corrupt in the shipped patch.

### Inject from the PRISTINE base, never from the tree you already patched

`inject` reads its base from the game's live `data/`, which after the first
`--in-place` run is already English. Re-running it there is not idempotent:

- Span-spliced writes (a `<LB:>` label inside a bigger `note`, anything keyed to
  a recorded offset) **refuse to write** - `note span moved ('Alc' != '錬金室')`.
  That guard is doing its job, but dozens of those lines are easy to skim past
  as noise when they actually mean the whole run is against the wrong base.
- Computed passes have no span to check, so they run anyway and land on top of
  the previous run's output. A layout pass reading the live note sees offsets it
  wrote last time and re-derives from an already-shifted position.

So keep the pre-patch `data/` backup that `--in-place` makes on its FIRST run,
and treat it as the base for every later re-inject. The safe loop, which never
touches the live tree until the diff has been read:

```
mv data data_EN_live && cp -r data_backup_<first> data
python tl.py inject                 # non-in-place: writes _tl/out/data
mv data data_JP_tmp && mv data_EN_live data
diff _tl/out/data against data      # what would actually change, leaf by leaf
```

Read that diff before copying. When only the leaves you meant to change differ
- 9 `<LB_X:>` offsets and nothing else - you have also proved that no
post-inject tool's work is about to be reverted, which is the other thing a
re-inject silently does.

### The no-op inject property test

**A store with no translations must inject as a no-op.** Wipe every translation, inject to a scratch directory, and deep-compare *parsed* JSON against the source. The only values allowed to differ are those injected from the glossary rather than from a unit - that is, speaker and actor names. Anything else means the injector is editing source text on its own initiative.

This is not hypothetical. A file-wide quote normalizer running after injection rewrote `「」『』` to ASCII quotes on every database field including untranslated ones:

```
Skills.json[904]/message2
  'アウレリオ「エステル　大丈夫ですか！」'
  'アウレリオ"エステル　大丈夫ですか！"'
```

Japanese text wearing English punctuation in the shipped data, with no translation behind it.
**Every unit-level check passed, because the mutation was not in a unit** - it was a whole-file pass.
Guard such passes on "does this value still contain untranslated Japanese" and write untranslated fields back byte-exact.
Note corner brackets are CJK *punctuation* and will not be caught by a hiragana/kanji detector, so the guard keys on the text around them.

Generalizes past this engine: any post-injection cleanup that walks the whole file rather than the unit list can silently edit source text, and only a whole-file property test sees it.

---

## Preparation validation and its limits

For tooling-only preparation, keep translation targets empty and leave API,
glossary and prompt setup for the authorized translation stage. Inventory all
audited tracks, then prove an empty build is byte-exact against an immutable,
hashed source snapshot. Bind the catalog's source metadata (excluding editable
targets), config, tools and output stamp to the build; preserve targets on
re-extraction and refuse unexpected site loss. Write into a fresh staging
directory instead of merging over a previous build.

Exercise EVERY selected injection site with synthetic text, including quotes,
backslashes, embedded newlines and template delimiters. Compare JSON structure,
IDs, command codes, indents and array lengths; reparse JavaScript and read back
decoded values. Deliberately break inputs to test that the real validator
rejects stale sources, bad tokens and changed protected structure.

Tropical Chase preparation proved 106 files byte-exact with empty targets and
synthetically exercised 2,340 units / 4,002 sites. Probes using functions read
from the shipped engine/plugin scripts checked existing `401` slots with
embedded newlines, preserved command indices, greedy Latin escape parsing and
portrait removal. No game launch, gameplay, old-save migration or English fit
check was performed. State these proof levels separately.

Native MZ `101 parameters[4]` speakers and actor names may need one shared name
unit: `CharacterPictureManager.isSpeakerActor` compares them. Existing saves
may cache actor names and display-variable strings even when command structure
is unchanged. Inspect these caches and test migration before claiming save
compatibility; structural identity alone does not establish it.

## State-dependency index: which scenes exist and how to reach them

Statically deriving switch/variable/item dependencies from `data/*.json` gives you a reachability map, which is exactly the checklist a translation playtest needs. `DAZEDTL_ROOT/data/skills/build-game-walkthrough/scripts/index_rpgmaker_dependencies.py` does this.
Without it you translate all N pages of an event blind and never learn that pages 2-4 are a dev-room variant, or that a line only renders after switch 412.
It is also the only reliable way to enumerate proofreadable scenes: a scene whose carrier you cannot set is a scene you cannot check in-game.

### Carrier sites come from exactly five command families

A carrier site is a read or write of a switch, variable, item, weapon, armor or actor. Treat every other code as opaque.

| Code | Role | Carrier |
|---|---|---|
| `111` Conditional Branch | read | `parameters[0]` is the type, mapped `{0:switch, 1:variable, 4:actor, 5:enemy, 8:item, 9:weapon, 10:armor}`, `parameters[1]` is the id |
| `121` Control Switches | write | `parameters[0]`..`parameters[1]` |
| `122` Control Variables | write | `parameters[0]`..`parameters[1]` |
| `126`/`127`/`128` Change Items/Weapons/Armors | write | record id in `parameters[0]` |
| `129` Change Party Member | write | actor id in `parameters[0]` |

Condition types `2` (self-switch) and `12` (script) are **not** carrier reads. Record them as opaque conditions and resolve them by hand. When `122` has `parameters[3]==1`, or `126`/`127`/`128` have `parameters[2]==1`, the operand is a variable and a **second** site must be emitted: a `read` of the variable at `parameters[4]` for `122`, `parameters[3]` for `126/127/128`.

Page conditions index separately from a fixed valid/id field-pair table, all reads: `(switch1Valid, switch1Id)`, `(switch2Valid, switch2Id)`, `(switchValid, switchId)`, `(variableValid, variableId)`, `(itemValid, itemId)`, `(actorValid, actorId)`. Skip any pair whose Valid flag is falsy or whose id is `None`/`0`/`""`.

**`121` and `122` write a RANGE, not a single id.** `parameters[0]` is the start and `parameters[1]` the end, so one `Control Switches 400..450 = ON` in a chapter-transition event flips fifty gates at once. Any lookup matching only `carrier == {kind, id}` misses every batch write and concludes a scene is unreachable, so its text gets marked dead and never translated or proofread. Match both shapes: exact, or `kind` matches and `start_id <= N <= end_id`. Validate the start id is a real `int` and **reject `bool` explicitly** - Python treats `True` as `1`, so a JSON `true` in a params slot would otherwise index as carrier id 1 - and coerce `end = start` when end is not an int or is less than start.

### Flow sites are indexed separately

Worth recording with their full `parameters`: `102` choice, `117` common-event call, `201` transfer, `301` battle, `601` battle win, `602` battle escape, `603` battle loss, `355`/`655` script, `356`/`357` plugin command, `657` plugin annotation.

`601`/`602`/`603` are the branch labels that follow a `301`, and **the loss branch routinely holds a whole alternate dialogue path** - defeat scenes, capture scenes, game-over-avoiding variants - that a naive reachability pass writes off as unreachable filler and ships in Japanese. `117` is how dialogue leaves a map and lands in `CommonEvents.json`, so follow it or your scene graph stops at the map boundary.

Treat `{opaque-condition, script, script-continuation, plugin-command}` as **discovery sites, never as evidence**, until a focused audit resolves each one. Write flow sites to their own artifact (`state-dependency-index-flows.json`) so the carrier index stays small enough to review, and carry the same `source_files` hash list in both.

### Hash-pin the index, and hard-fail on drift

A translation patch edits the very `data/*.json` the index was built from, so an unpinned index keeps describing the pre-patch game while you make reachability decisions from it. It will say a scene is reachable after your own patch broke the switch that gates it.

Record one `{file, sha256}` row per indexed file across every `Map[0-9][0-9][0-9].json` plus `CommonEvents.json` and `Troops.json`, deriving the map id from `path.stem[3:]`. On reuse recompute each digest (require 64 lowercase hex) and abort on the **first** mismatch, naming the file.
Snapshot `glossary.json` and the game bible the same way.
Resolve every path through a guard that rejects absolute paths, any `..` component, and anything resolving outside the game root after `.resolve()`.

**Pin an event-command claim by the whole `{code, parameters}` object, never by `command_index` alone.** A shifted index still points at a command with the same code, so an index-only check passes on the wrong line.

---

## Save-file translator

RPG Maker bakes JP strings (actor names, party, message log, map state) into saves, so existing players' saves show Japanese after patching. Ship a save translator (`translate_save.py`):

- **Codec**: MZ = zlib(level 1) UTF-8 (`.rmmzsave`), MV = LZString Base64 (`.rpgsave`).
- Build a JP->EN map from the extracted data + glossary. Apply only to **safe sections** (`map, messageLog, party, player, actors`). Never touch keys (they start with `$+<@`) or asset paths (`.png/.ogg/.m4a`).
- **Exact match** whole strings. Allow **partial** name substitution only inside strings that already contain a control code (`\c[`, `\n[`, `\i[`, `\{`) - never bare labels or keys.
- **Round-trip assert** `decode(encode(data)) == data` before writing, and auto-backup to `save_backup/` first.

See `save-compatibility.md` for the general problem, including the command-index issue: a save stores a *position* in the event list, so any edit that changes the number of commands moves it. That is the constraint behind the 401/405 write-back choice above.

---

## Re-translating after a game update

**Normalize every valid JSON file on BOTH baselines before diffing**, or the first three-way merge reports one hundred percent of every file as changed and forces a manual redo of the whole translation. Run `js/plugins.js` through the **same formatter** the preparation step uses (the jsbeautifier options above), because minified-versus-beautified formatting alone turns the entire plugin configuration into a single unresolvable conflict, and resolving that in the official file's favour silently drops the translation patch's own plugin registrations - the updated build then loads with no translation hooks at all. Leave any JSON that cannot be safely formatted byte-unchanged and surface it as a warning rather than mangling it.

**Conflict policy: when both the official release and the translation changed the same file, the official file wins** so game structure stays intact, and the log must name exactly which files therefore need re-review. **Scope the localization pass by the diff, but include the files that official-wins replaced wholesale**, not only the cleanly merged hunks, and for each of those compare the new file against its **pre-update translated counterpart** so surviving translations are recovered instead of re-translated.

Evidence precedence for the re-localization: curated glossary and skill guidance > established usage already in the translation > the source text in context.

Operational rules that cost a redo when missed: commit unfinished translation work **before** starting the update, select the translated game's **root** folder and not its `data` subfolder (or every patch path nests one level too deep), and use patch-folder mode only for developer-supplied incremental patches, since an update that must **delete** files needs a complete official game folder.
Report the official release delta and the translation impact as two separate counts, and record an official change already identical on the translation branch as a metadata-only version marker rather than a content patch.
Prohibit the pass from switching branches, editing the `original` branch, resetting or cleaning the worktree, rewriting history, or creating a commit.

---

## Capturing a corpus for benchmarking

**Run the production event parser with its send function monkeypatched. Never write a second, simpler extractor.** A separate extractor produces different grouping, different history and different 101/401 merging, so any model you pick from it is optimal for a corpus the shipping pipeline never sees.

Replace `rpgmaker.translateAI` with a capture function and call the production `rpgmaker.searchCodes(page, None, [], filename)` under a module-level RLock, saving and restoring every parser global the call mutates.
**Force `CODE101`, `CODE401`, `CODE405` and `CODE102` on for the capture regardless of the caller's live code profile**, or a user's current "skip 405" setting silently removes whole categories from the corpus, and inject the glossary so speaker-name resolution matches production.
Key each captured group as `{filename}:{event-N,page-M}:call-K` with items at `...:item-J`, retain `initial_history` plus the full source location, and skip lines with no Japanese character.

---

## VX Ace (and VX / XP)

**Ace is the same engine design with a different serialization.** The event command codes are the same numbers - `101` Show Text, `401` line, `102` Show Choices, `402` branch, `108` comment, `355/655` script, `111` conditional, `118/119` label and jump. So the entire code table above transfers. What differs is how you reach the data, how the patch reaches the player, and where the hardcoded UI text lives.

**There is a finished, proven pipeline: `Reference Pipelines/RPG Maker VX Ace (DressQuest)/` - read its `PIPELINE.md` first and copy `acetl` rather than rebuilding it.** 14,750 units, 100%, $8.36 on Sonnet 5 batch. Everything below is why it is shaped the way it is.

### Read and write the Marshal directly. Do not put RV2JSON in the delivery path.

`RV2JSON.exe` (ships with DazedTL under `util/ace/offline/`; not bundled here, see `tools/THIRD-PARTY.md`) converts `Data\` to JSON and back, and it is genuinely useful for READING - a JSON tree greps and diffs, a Marshal blob does not. It is not safe to write back:

* `-c` then `-u` with **zero edits** returns **28 of 231 files changed** on a real game (`Enemies.rvdata2` 35,587 -> 32,337 bytes). Its round trip is not byte-exact, so no patch built on it can prove it changed only what it meant to.
* it **silently drops `System.terms.etypes`**. The five equip-slot labels that `Vocab.etype` reads and two windows draw are absent from its JSON, so extracting from JSON misses them and writing that JSON back DELETES them from the game.

`acetl/rvmarshal.py` is a Ruby Marshal 4.8 reader/writer, ~450 lines, that round-trips **231/231 shipped files byte for byte**. Take it as-is. It also gets you save files for free, which is the other half of an Ace patch.

Two design points in it that are not optional:

* **Every non-immediate value is a wrapper object** (`RString`, `RArray`, ...), never a Python native. Marshal emits a back-reference the second time it writes the SAME OBJECT, judged by identity; CPython interns short strings, so mapping Marshal strings onto `str` collapses two distinct Ruby strings into one and the writer emits a link where the original had a full copy.
* **A map's events are a Hash keyed by event id**, not the sparse array MV uses. A write-back pointer must carry the KEY, or a hash written in a different order sends a translation to the wrong event.

Archive extensions by generation: `.rgss3a` = Ace, `.rgss2a` = VX, `.rgssad` = XP. Data: `.rvdata2` = Ace, `.rvdata` = VX, `.rxdata` = XP. The Marshal layer is version-independent; only the class names inside change.

### Delivery: the archive beats loose files, so the archive has to go

**RGSS3 reads `Game.rgss3a` BEFORE it reads a loose file of the same name.** A patch dropped into the game folder next to the archive does nothing at all, and does it silently: the game starts in Japanese with a fully translated `Data\` sitting right there. This was measured by running the game after assuming the opposite and shipping it.

Audio is loose in a stock Ace game and is NOT in the archive - that is the proof that RGSS falls back to the filesystem for anything the archive does not contain. So the install is three steps and the third is not optional:

```
1. extract Game.rgss3a into the game folder   -> Data\ and Graphics\
2. copy the patch over the extracted Data\
3. MOVE Game.rgss3a out of the folder
```

`tools/Game Archives/RPG Maker RGSSAD/` has `rgssad.py` (v1/v3 extractor) and `install-template.ps1` - a player-facing installer that does all three with an embedded C# unpacker, so the player needs neither Python nor an extractor. Its `-Uninstall` restores a byte-identical archive.

### Where the text is that MV/MZ does not have

**`Scripts.rvdata2` - the second track.** MV/MZ keeps UI text in `js/plugins.js` parameters; Ace keeps it in Ruby source, an array of `[id, name, zlib-deflated code]`. On one real game that was **384 Japanese literals across 12 of 143 sections**, and skipping the track means shipping Japanese menus over an otherwise finished patch.

Two sub-cases, and they are handled differently:

* **`Vocab`** is stock Enterbrain boilerplate - the whole battle log plus the shop, save and load prompts. Every one has published English. Seed them from a table, mark them `locked`, spend nothing. On that game: 51 strings, zero API calls.
* **Everything else** is the game's own scripts: custom menus, a volume screen, a world map, extra status rows. These need an audit pass with **two gates** before anything is written - the model must classify a literal as DISPLAY and say where it is drawn, AND a static check must not find that literal used as a `when`/`==` operand, a hash key, a `Cache.` argument or a filename anywhere in the scripts. `tools/translate_scripts.py` in the reference pipeline is that pass.

The static gate has its own false positives, and a veto that fires on correct text gets the whole gate switched off:

* `when\s+[^\n]*LITERAL` matches any `when` that merely shares a line, and this game writes `when 3 then name = "王都バロン"; desc = "..."` - it vetoed fourteen correct world-map labels. Require the literal to BE the operand, in quotes.
* `["text"]` DEFINING an array is not `hash["key"]` READING one. Require a receiver (`[\w\)\]]`) immediately before the bracket.

**The patch gets played on hosts you do not have, and RGSS3 scripts lean on Ruby incidentals.** JoiPlay and the other reimplementations are not RGSS3; a script that is correct by accident on Ruby 1.9.2 can fail there silently. The worked example: a recollection gallery whose `usable_event?` has no explicit return, so the method's value is its trailing `if` branch - which ends in `p debug`. Ruby 1.9+ returns the argument from `p`, so it works on desktop; a console-less host stubs the print to nil, every event is rejected, and the unguarded confirm handler raises `undefined method 'event_id' for nil:NilClass`. The page counter reading **1/1 instead of 1/6** was the tell that the list was empty rather than the index wrong.

Two habits follow. **Prove the patch is neutral before debugging it**: reimplement the game's own filter over the pristine and the patched data and compare - identical counts (47 entries, 197 CGs) ruled out the translation in one step and pointed at the host. And **make the fix explicit rather than clever** - adding `return true` is a no-op under a `p` that returns its argument and a fix under one that does not, which is verifiable by running both versions under both `p` implementations.

**Run `ruby -c` over every section after any script write.** The read-back in the write path proves a section holds the text intended, which catches a corrupted write but not text that is invalid Ruby - an apostrophe closing a single-quoted literal, an anchor spliced at the wrong indent. A portable RubyInstaller build extracted with Windows' own `tar.exe` is enough, and the check should SKIP rather than fail when Ruby is absent so the release path still runs without it.

**Code patches need their own path.** A string ledger swaps one quoted literal for another and cannot express a fix to the Ruby itself. Give code patches the same discipline - exact anchor, unique match, only edited sections recompressed, backup, read-back, idempotent - and define them as LISTS OF LINES: these sections use CRLF, and an anchor built with LF matches nothing.

**An in-place track's source of truth lives in the GAME folder, not the workspace, which is what makes it silently revert.** The release builder correctly takes `Scripts.rvdata2` from the game copy rather than from the injected output - but that means refreshing the working game folder from a clean copy, or re-extracting the archive, throws the script track away while every workspace artifact still looks finished. It resurfaces as a release that ships Japanese menus with perfect English dialogue. Re-run the in-place apply before every release build, and assert the built release actually contains a known English UI string.

Write-back rules: keep the ledger's `jp`/`en` at **source level** (the characters between the quotes, escapes included) so `Vocab::ObtainGold`'s `お金を %s\\G 手に入れた！` survives - re-escaping on write turns `\\G` into `\\\\G` and prints a literal backslash. Recompress only the sections you edited; every other section keeps its original deflate bytes. Then **read the file back and compare each section against what you intended** - not "does it inflate", which is both too weak and, on a game with legitimately EMPTY separator sections, too strong: an inflate-only check condemned 14 empty sections and rolled back a correct write.

**Two tracks means two chances to disagree, and nothing compares them.** The units and the script ledger are translated by separate passes, so the same source string can be rendered differently in each and *both tracks stay internally consistent* - every per-unit check passes, and the defect is only visible by playing. On Dress Quest `マッスルーム` shipped as "Mussroom" in 85 lines of dialogue and "Muscleroom" on the world map, and `レーゲンヘーレ` as "Regenhere" against "Regenhoehle" - a player found the first and the second was sitting right beside it.

Add a check that joins the tracks on the source string: for every ledger literal marked translate, compare its English against the glossary entry and against every unit whose `src` is that same string. Report, never block - a map pin legitimately shortens what prose spells out (`王都バロン` is "the Royal Capital of Baron" in dialogue and "Baron" on an 11-cell pin), and a stat window abbreviates (`魔法回避` -> "M.Evasion" beside "Magic Evasion"). On the finished game the check found 8 conflicts: 2 real defects and 6 deliberate. `validate.cross_track_conflicts` in the reference pipeline is that check.

**Whoever wins the disagreement, decide it from the source, not from the majority.** 85 units said "Mussroom" and one script literal said "Muscleroom", and the single outlier was right: `マッシュルーム` is *mushroom* and `マッスルーム` swaps one kana to spell `マッスル`, *muscle* - and the town is the martial-arts town. Grep the whole corpus for the other half of a pun before preserving it: zero of 14,750 units mentioned a mushroom, which is what settled it. The later pass is also often the better-informed one - the script-track audit ran with more context than the glossary seed did, which is why the map was right twice.

**`CommonEvents[].name` may be player-visible.** It is an editor label on most games and was on this one too - until the recollection gallery drew it: `回想.rb:181` does `draw_text(..., $data_common_events[id].name)` for 47 of 56 events. Identity there is `event.id`, so translating is safe, but ruling the field out by habit ships a Japanese scene list. Grep for `$data_common_events` before deciding.

### Speakers: Ace has no speaker field, so find what the game uses

`101` parameters are `[face_name, face_index, background, position]` - arity 4, no MZ `parameters[4]`. So a speaker comes from one of:

1. **a custom escape code**, which is the common case in commercial doujin games. Dress Quest's own `メッセージウィンドウ` script defines `\NAME[名前]`, consumed in a `convert_escape_characters` alias and drawn in a separate auto-sized window: **11,484 of 12,880 boxes**, 221 distinct speakers.
2. **the face graphic**, which is usually a costume rather than a person - all 31 face sheets in that game were the same heroine.
3. **nothing**, in which case give the unit an empty speaker rather than inheriting the last one.

A custom nametag code is a NAMETAG, not inline text. It costs zero width (consumed before drawing), must be split off before the model sees the line or it gets paraphrased into the dialogue, and its values are glossary entries translated once each and rebuilt on inject. Three consequences worth writing down:

* an untranslated speaker ships a **Japanese name plate over English dialogue** - visible on screen, invisible to every per-unit check, because the tag is not part of any unit's text. Report them separately.
* the English name **must not contain `]`**: the tag regex is non-greedy, so a bracket closes it early and the remainder prints into the message body.
* **the "silent beat" units.** A box whose body is `「………」` holds no Japanese, so extraction skips it - and then inject never sees it and its plate stays Japanese. 79 of them on one game. Extract when the body has Japanese **OR** there is a tag, pre-fill the body with itself, and lock it.

### Battle-log fragments are name-prefixed per FIELD

`Window_BattleLog` draws `subject.name + item.message1` for Skill message1 and `target.name + state.message1..4` for States - but Skill message2 stands alone (`add_text(item.message2)`). Japanese needs no separator; English does. Read the prefixed set off the game's own `Window_BattleLog` rather than guessing from a leading particle, give those units a dummy subject in the prompt, and restore a **leading space** on the way back. Dropping it ships `Erisattacks!` in a log that only appears in combat and survives every text-only review.

### Geometry: calibrate the cell, and know which overflow is fatal

Ace draws at `Font.default_size` in `Font.default_name`. A game that sets neither - the common case - leaves both to the engine and to whatever font the player has, so the cell size is not in the data. Get it by **photographing one clipped line** and solving for it:

```
a faced line runs from new_line_x to Graphics.width - padding
640 - 12 - 112 = 516 px carried 51 half-width characters -> 10.1 px/cell
MS Gothic at 20 px reproduces the clip at exactly 51 of 54 -> the cell is 10 px
```

Then `616 / 10 = 61 cells` unfaced and `504 / 10 = 50` faced. **Do not take the author's widest shipped line as the budget without checking it fits** - on that game the corpus said 66/56, which at a 10 px cell is 660 px and 560 px in boxes of 616 and 504, and 255 of the author's own lines lose characters off the right edge in the original.

**Height paginates, width clips.** `Window_Message#process_new_line` calls `input_pause` then `new_page`, so a message taller than `visible_line_number` costs a click and loses nothing. `process_normal_character` advances x and draws without testing the right edge, so a wide line is cut off by the contents bitmap. Make width a hard failure and height a soft note - treating both as hard makes the pipeline pay a model to compress prose the engine would have handled by itself.

### Other Ace differences

- **Control codes** are the same family minus the MV/MZ additions: `\C[n]`, `\N[n]`, `\V[n]`, `\G`, `\$`, `\.`, `\|`, `\!`, `\>`, `\<`, `\^`. No `\I[n]`, `\FS[n]`, `\{`, `\}` unless a script adds them - and scripts do add them, so census the corpus rather than assuming this list.
- **The window is much smaller.** Ace's default resolution is 544x416 against MZ's 816x624, and a `Graphics.resize_screen` in the scripts is common (640x480 here). The same English needs materially tighter wrapping.
- **Saves** are `.rvdata2` Ruby Marshal, **two concatenated documents** (header then contents), each with its own symbol and object tables. See `save-compatibility.md`.

## In-game editing and testing

forge-mvmz (`Forge_MV.js`/`Forge_MZ.js`, not bundled; DazedTL carries the same overlay under `util/forge/`) is a drop-in F10 overlay to jump to any map, set variables/switches and run common events - invaluable for reaching untranslated scenes fast. Copy to `js/plugins/`, add to `plugins.js` last.

To find a string you saw on screen: Snipping Tool OCR, then `Ctrl+Shift+F` in VSCode over `data/`.
