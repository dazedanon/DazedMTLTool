# Playtest Instrumentation

Turning "I saw Japanese on screen" into "edit `Map003.json` line 4127, column 31".

## Native MZ fixtures must prove the engine is still updating

An IPC request can succeed after MZ has stopped. `SceneManager.catchException`
handles failures internally, writes `Graphics._errorPrinter.textContent` and
stops the ticker; `window.onerror` may never fire while Node timers continue
answering requests. Require an empty engine error panel, advancing frame count,
the expected scene/map, and the actual rendered consumer's updated value.
Reusable QA helper: `RPG Maker MZ (Tropical Chase)/tools/mz_health.js` in the
stable reference pipelines. Its tests simulate the failure; the accompanying
game evidence comes from the shipped executable.

Prefer actual `Scene_Save` / `Scene_Load` handlers. Before a direct fixture load,
leave the old map for Title/Load and wait for the scene to start, then replace
objects/load data and enter the map. Loading over an active map caused a sensor
plugin to read undefined `event.pages`; do not patch gameplay to hide a harness
lifecycle error. Wait for observable scene/consumer state instead of treating a
fixed sleep as proof. Historical example scripts include measured sleeps and
must be adapted to another runtime's timing.

Unfocused and hidden are distinct states. `SceneManager.isGameActive()` may
pause an unfocused game; Chromium may separately suspend requestAnimationFrame
when hidden. First observe frame progress. If QA needs an override, scope it to
the isolated process, record it, avoid double ticking, and remove it on teardown.
Do not ship focus/scheduling changes as part of a translation patch.

Use a separate profile and save directory for each QA instance. Restore exact
startup-file bytes in `finally`, even on a failed launch, and ignore stale queued
commands on boot. A filesystem IPC fallback is useful when the shipped NW.js
does not expose working CDP. Own processes by the exact executable/profile path;
never stop every process with the game's basename. Native cold-boot checks must
run without the startup hook and derive the expected title from the game's
actual title source, not a shortened project nickname.

For UI captures, selecting a custom list row may not scroll it into view:
verify visibility and call the consumer's scrolling method if needed. A helper
that presses OK to advance dialogue can also choose battle attacks. Use the
actual active menu handlers and normal battle preparation; map-only utility
actors can otherwise produce a fictitious combat UI. Record fixture changes.

## Why OCR plus grep fails

**Screenshot-and-grep is not a location method, it is a guess.** It breaks in the three cases that dominate a real playtest pass:

- **Short strings.** `はい`, `いいえ`, `戻る`, `所持金` occur hundreds of times across `Map*.json`, `CommonEvents.json`, `System.json` terms, and plugin parameters. grep returns every hit and none of them is marked as the one that was on screen.
- **Duplicated strings.** Authors copy an event page into five maps. Identical bytes, five distinct edit sites, one correct answer. Text matching cannot rank them.
- **Runtime assembly.** `'%1 turn(s) remaining'.format(2)` draws as `2 turn(s) remaining`. That literal exists nowhere on disk. grep returns zero hits and you wrongly conclude the string is baked into the binary.

The fix is an in-game inspector that answers the question at the moment the text is drawn, while the engine still holds the objects that produced it. Reference implementation: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js` (3142 lines, RPG Maker MV/MZ, NW.js).

## Lookup table

| On screen | Anchor used | Section |
|---|---|---|
| Dialogue, choices, scrolling text | `===` identity of `Game_Interpreter._list` | [Identity resolution](#rule-resolve-event-text-by-object-identity-never-by-string-match) |
| Menu labels, status windows, buttons | Six-tier value index over `TextManager` / `$dataSystem` / notetags / plugin params / JS literals | [UI text](#rule-hook-the-draw-chokepoint-then-resolve-the-value-not-the-caller) |
| Text with numbers in it (`2 turn(s)`) | `String.prototype.format` template log | [Composed strings](#rule-log-format-templates-a-composed-string-has-no-literal-on-disk) |
| Untranslated `img/pictures/*.png` | `command231` (Show Picture) trigger record | [Images](#rule-record-the-event-command-that-loaded-each-picture) |
| Have a JSON path, need `line:col` | Raw-text offset walker with verify-then-reanchor | [Path to offset](#rule-walk-the-raw-text-jsonparse-throws-away-offsets) |
| Have a source line, need the scene | Read the path prefix backwards | [Reverse direction](#reverse-direction-source-line-to-scene) |

## Rule: resolve event text by object identity, never by string match

**`Game_Interpreter._list` is the same array object the engine parsed out of the data file. Compare with `===` and the file falls out for free.** Nothing about the text is involved, so duplicate lines across maps are never confused and a string that appears 200 times still resolves to exactly one site.

`resolveList(list)` walks candidate containers in this order and returns on the first identity hit:

| Order | Container | Path prefix produced |
|---|---|---|
| 1 | `$dataMap.events[e].pages[p].list` | `['events', e, 'pages', p, 'list']` |
| 2 | `$dataCommonEvents[c].list` | `[c, 'list']` |
| 3 | `$dataTroops[troopId].pages[tp].list` | `[troopId, 'pages', tp, 'list']` |
| 4 | `$dataScenario[sceneName]` (scenario-plugin dictionaries) | plugin-defined |

The command index is appended to reach the exact string: `prefix.concat([idx, 'parameters', 1])`. That full JSON path is the handoff to the offset walker below.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:387-445`.

**Search troops and scenario dictionaries too, not just maps and common events.** Battle-only lines live in `Troops.json` pages and are the most commonly missed category in a first pass, because a normal playthrough rarely reaches every troop.

## Rule: hook the draw chokepoint, then resolve the value, not the caller

A status-window label has no event command behind it, so there is no `_list` to identify. Hook where text becomes pixels instead:

```js
Bitmap.prototype.drawText          // every low-level draw
Window_Base.prototype.drawTextEx   // control-code text, and where plugins funnel
```

Both are required. Plugin code writes `this.contents.drawText(...)`, which lands in `Bitmap.prototype.drawText`, so hooking window classes alone misses most of the UI.

**Skip capture while `$gameMessage.isBusy()`.** Dialogue already resolved by identity, and capturing it again floods the log with duplicates that resolve worse.

Capture floors, both required, applied before anything is logged:

| Floor | Test | Why |
|---|---|---|
| Length | at least 2 non-whitespace chars | single glyphs are unresolvable noise |
| Content | at least one char matching `/[^\s\d.,:%\/+\-()]/` | drops pure numbers and punctuation |

The content floor is what kills the per-character draws that `drawTextEx` emits while rendering control-code text one glyph at a time.

**De-duplicate on a digit-normalized key: `'ui ' + text.replace(/\d+/g, '#')`.** A ticking gold counter draws `所持金: 12` then `所持金: 13`. Without normalization it logs once per frame.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:598-618` (hooks), `:619-648` (floors and key).

### The six-tier value index

`buildUiValueIndex()` builds `value -> candidates[]` from every place a display string can live. **Build it on a null-prototype map (`Object.create(null)`).** Game text is literally sometimes `constructor` or `__proto__`, and a plain object silently returns a function for those keys.

| Tier | `t:` | Source |
|---|---|---|
| 0 | `tm` | own DATA properties of `TextManager` |
| 1 | `json` | `$dataSystem.terms.{basic,commands,params,messages}`, plus `elements`, `skillTypes`, `weaponTypes`, `armorTypes`, `equipTypes`, `gameTitle`, `currencyUnit` |
| 2 | `meta` | notetag values |
| 3 | `param` | `$plugins[].parameters` |
| 4 | `metaseg` | sub-fields parsed out of a notetag value |
| 5 | `jslit` | every string literal in every enabled plugin `.js` |

Database display fields are indexed per file, only the fields that can reach the screen: `Actors: name/nickname/profile`, `Skills: name/description/message1/message2`, `States: name/message1..4`, and the equivalents for items, weapons, armors, enemies, classes.

`resolveUiSource` picks the winner by the fixed order `{tm:0, json:1, meta:2, param:3, metaseg:4, jslit:5}` and reports `(+N other matches)` rather than hiding the ambiguity. **`jslit` is last and capped at 8 sites per value, with comments skipped.** An uncapped literal scan otherwise buries the real answer under every plugin that happens to contain the same word.

**On a miss, rebuild the index, but at most once per 5 seconds.** Language-toggle and vocab plugins rewrite `TextManager` and `$dataSystem.terms` at runtime, so an index built at boot goes stale the moment the player switches language. The 5 s floor stops a miss storm from rebuilding every frame.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:722-810` (index build), `:828-843` (rebuild throttle), `:979-1013` (jslit), `:1040-1060` (tier order).

### Disambiguating `TextManager.<prop>` across plugins

Multiple plugins assign the same `TextManager` property, typically a Japanese vocab plugin and an English one. **Scan plugin files in `$plugins` load order and prefer the assignment whose literal equals the property's CURRENT runtime value.** Load order alone picks the wrong file whenever the later plugin is the one that won. Value matching picks the file that actually produced what is on screen.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:887-925`.

## Rule: log `format` templates, a composed string has no literal on disk

Monkey-patch `String.prototype.format` into a rolling `FORMAT_LOG` of `{tpl, out}` pairs, 40 entries deep. When a drawn string fails to resolve against the value index, match it against `out` and resolve `tpl` instead. `2 turn(s) remaining` resolves to `'%1 turn(s) remaining'`, which does exist on disk and is what needs translating.

40 entries is enough because the lookup happens in the same frame as the draw. Do not grow it into a full history.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:1018-1036`.

## Rule: record the event command that loaded each picture

Hook `command231` (Show Picture) and record which event command loaded each `img/pictures/<name>.png`. An untranslated image on screen then traces back to its trigger event, which is the only practical way to find which of 400 pictures needs redrawing and under what condition it appears.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:570-583`.

## Rule: walk the raw text, `JSON.parse` throws away offsets

A logical path is not an edit location. `locateOffset(text, pathArr)` is a character scanner over the RAW file text, built from four primitives:

| Primitive | Job |
|---|---|
| `skipWs` | whitespace between tokens |
| `readKey` | read one object key |
| `scanString` | consume a string including escapes |
| `skipValue` | brace and bracket count with a `depth` counter, skipping over strings |

**`skipValue` must skip strings while counting depth.** A `}` or `]` inside a dialogue string otherwise closes a scope early and every subsequent offset is wrong. This is the single most likely place a reimplementation breaks, and it fails silently by landing on plausible-looking neighbouring text.

Numeric path steps walk N commas at the current array level. String steps read keys until a match. The offset feeds `offsetToLineCol`, which counts newlines.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:249-263`, `:286-302`, `:306-340`.

### Verify, then re-anchor

**Never trust a computed offset. Verify it against the expected text first.** `locateLine` compares `text.substr(off, quoted.length)` against `JSON.stringify(expectedText)`. Files drift constantly during a translation project - re-exported, re-indexed, or edited while the running game still holds an older parse - and an unverified path points at the wrong line with full confidence.

On mismatch, fall back to `reanchorByText`:

1. Collect every occurrence of the exact quoted string, capped at 5000.
2. If one hit, take it.
3. If several, pick the one NEAREST in byte distance to `locateOffset(text, pathArr.slice(0, 1))`, the start of the owning top-level container.

**The container-proximity tiebreak is the whole point.** It is what stops a duplicate line belonging to another event or another scene from winning the re-anchor, and it is the reason this survives the duplicate-string case that defeats grep.

Cache under `file + '::' + path.join('/') + '::' + mtime`. Including mtime means saving one file invalidates only that file's entries, so the inspector stays usable while you are actively editing.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/TLInspector.js:347-359`, `:362-382`.

## Reverse direction: source line to scene

The path prefix read backwards names the scene. Given a hit in a data file:

| Path | Where it plays |
|---|---|
| `Map017.json` → `events[3].pages[0].list[12]` | map ID 17, event 3, page 1, twelfth command |
| `CommonEvents.json` → `[8].list[...]` | common event 8, called from wherever it is invoked |
| `Troops.json` → `[22].pages[1].list[...]` | troop 22 battle event, page 2 |

Page index matters as much as event index.
Page 0 is often the pre-flag version of a scene that the player will never see again after an early switch flips.
**Read the page's conditions before trying to reach it.** The fast route to a scene is setting the page's condition switch or variable directly (F9 debug window in playtest) and transferring to the map, not replaying to it.
Replaying a 20 hour game to verify one line is how a QA pass dies.

If the path is a `Troops.json` page, the scene is a specific battle and the only reliable route is forcing that encounter.

## Install and uninstall

- Drop the plugin `.js` in `www/js/plugins/` and add one entry to `www/js/plugins.js`.
- **Place the entry LAST.** It hooks other plugins' overrides, so anything loaded after it is invisible to the draw hooks and the `TextManager` scan.
- Remove that line for release. Never ship the inspector in a patch.

**When patching the plugin's `CFG` block programmatically, the regex replacement must be a FUNCTION, not a template string.** A template string reinterprets backslashes, so a Windows path such as `C:\Users\...` becomes an invalid JS escape sequence and the plugin fails to parse with an error that points at the wrong line.

Evidence: `DAZEDTL_ROOT/util/tl_inspector/config.py:118-133`.

## Porting to other engines

Two properties make this design work. Check both before rebuilding it elsewhere:

1. **The interpreter still holds a reference to the parsed data structure at draw time.** If it does, identity comparison replaces all text matching and the hard problems disappear.
2. **There is a narrow chokepoint where text becomes pixels.** In MV/MZ that is `Bitmap.prototype.drawText` plus `Window_Base.prototype.drawTextEx`. Hooking callers instead of the chokepoint always misses plugin-drawn UI.

Where property 1 does not hold - compiled engines that copy strings out of their source at load - only the chokepoint hook is available, and the value index becomes the primary resolver rather than the fallback. See `engine-unity-mono.md` and `engine-unity-il2cpp.md` for the Unity text sinks.
