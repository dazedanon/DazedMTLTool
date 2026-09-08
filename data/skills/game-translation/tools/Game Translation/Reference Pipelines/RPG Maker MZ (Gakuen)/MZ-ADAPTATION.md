# MZ adaptation findings: Tropical Chase preparation

Recorded 2026-09-07 from the local RPG Maker MZ 1.9.0 build of
`とろぴかる・ちぇいす！`. This is an offline tooling-preparation case study.
At that preparation milestone, no API, glossary/prompt setup, translation,
game launch or save migration had been performed. Later in the same session,
the manual English translation and native QA were completed; see the separate
`../RPG Maker MZ (Tropical Chase)/PIPELINE.md`. The historical preparation
claims below are not a description of the final state.

## Inventory by the code that consumes the text

The source contained 28 data JSON files, 14 maps and 38 enabled plugins
(two disabled). All map `displayName` values were blank. There were 1,964
`101` headers, 920 nonempty native speakers and no face images; 3,943 `401`
rows produced 1,939 nonempty message units. Recount these for each new game.

| Source/consumer | Finding and extraction rule |
|---|---|
| `RecollectionModeMZ` | `recoCgSettingList` loads `img/system/` plus its configured filename. `RecollectionModeMZData.json` contains 25 gallery titles. Whitelist `title`; retain pictures, thumbnails and event/switch IDs. JSON under `img/` is text scope. |
| `SceneCustomMenu` | Nested JSON-in-string parameters hold `Text`, `HelpText` and `ItemDrawScript`. Parse each layer, then parse scripts and static template fragments; protect interpolation and actions. |
| `LL_InfoPopupWIndow` | Of 790 code `357` commands, 61 use `showMessage.messageText`; sound names are asset identifiers. Preserve the plugin's actual spelling. |
| `TextPicture` | Fourteen code `357` commands use `set.text`; translate the configured text argument only. |
| `EventCommandByCode` | Six commands were technical stamina `SetMax` operations, excluded after consumer review. |
| Script assignments | 501 code `122` commands included three script operands, all numeric. Twenty-three code `355` assignments instead produced three display labels in variable 125 for `SceneCustomMenu`. |
| `LL_VariableWindow` | Only IDs 86 and 102 are drawn. ID 102 already reads `HP`; ID 86 needs a display-label unit. Other variable names stay internal. Label width here is 60% of 200 px = 120 px. |
| `CustomizeFailureMessage` | Three `<失敗メッセージ:...>` values are displayed. Splice the value; preserve tag syntax and other note content. |
| `CharacterPictureManager` | `isSpeakerActor` compares actor names with native `101` speakers. Link matching names to one unit and retain phase eligibility on EACH site. |
| `Mano_InputConfig` | The configured Japanese locale leaves remain selected unless game locale changes. Inventory those display leaves and the three source labels; forcing locale is not a generic prerequisite. |
| Engine source | The 170 Japanese literal hits were name-input keyboard tables. There were no code `303` commands, so these were not selected for this game's normal text scope. |

An enabled plugin's loader and display calls determine scope. A Japanese
literal, editor label, filename or parameter key is not automatically text.
Record exclusions with evidence so a zero-unclassified count is reviewable.

## Protect complete control codes in every text operation

The previous alphabetical bracket matcher consumed only `\F` in
`\F3[sn_01]`. Its round trip was exact while `3[sn_01]` remained exposed.
Test the masked shape as well as exact restoration and token identity.

The shared `mztl/codes.py` now defines `BRACKET_CODE_PATTERN`, used also by
`measure.py` and `wrap.py`. It recognizes alphabetic bracket codes and the
numbered `F1`-`F8` / `M1`-`M8` forms, including one nested bracket level such
as `\F3[\V[1]]`. `LL_StandingPicture` consumes these selectors before the
base window escape parser. Their whole token is zero-width, including a nested
variable that selects a portrait; ordinary displayed `\V[1]` still needs a
value-width budget. The same pattern is used for stripping leading codes.
Deeper nesting or a different numbered plugin grammar requires another audit.

`\F`, `\FF`, `\FFF`, `\FFFF` and numbered variants select portraits in this
plugin; they do not themselves create a new message box. Reusing an F-code
block-splitting heuristic would incorrectly fragment consecutive `401` runs.
Whole-code measurement reduced this source's width flags from 53 to 16.

## Parse JavaScript without running the game

`tools/js_literals_acorn.cjs` is a standalone, optional AST helper. It does not
replace the existing Gakuen injector or classify literals as safe to translate.

* Input on stdin: a JSON array of `{ "name": "file.js", "source": "..." }`.
* Output on stdout: a JSON array of `{ "name": "file.js", "literals": [...] }`.
* Literal entries contain decoded `text`, delimiter `quote`, `start`/`end`,
  line number, AST parent and context (truncated to 500 characters). Obtain
  full context from the source when reviewing longer expressions.
* Template quasis additionally contain `raw`, `fragment`, `tagged` and
  `review_required`. Expressions are not part of a quasi; string literals
  inside expressions are separate candidates requiring consumer review.
* Tagged templates and null cooked values require explicit handling because
  tag code may observe raw spelling. Do not inject into them automatically.
* Parse errors identify the input name and produce no partial JSON output.

Use an available Node plus Acorn. The helper first tries `require('acorn')`,
then Node's internal Acorn with `--expose-internals` (tested with Node 22.18.0).
That internal path is not a stable public API; use a provided Acorn package
if another Node version does not expose it. No npm install or API credentials
are required when the tested internal parser is available.

Run from this reference directory, using an explicit Node path if necessary:

```powershell
python -B -X utf8 tests/test_codes.py
python -B -X utf8 tests/test_js_literals_acorn.py --node 'C:\path\to\node.exe'
```

The code tests use deterministic width cells and synthetic strings rather than
a removed game's font path. The JS tests cover CRLF, astral Unicode before a
literal, escaped Unicode, comments/regex, templates, preserved expressions,
replacement escaping, decoded-value readback and malformed syntax.

The shared control-code update was also compared against 90,890 serialized
string values in Gakuen's 86 stored unit files: masking, wrapping atoms and
visible-width representations were unchanged. That comparison read the
existing corpus in place; it did not copy it into this addition.

Extract and inject against the SAME bytes decoded with the same encoding.
`Path.read_text()` normalized CRLF in an early extractor, but injection used
`read_bytes().decode()` and failed its source-span guard. Preserve newlines.
The helper converts Acorn UTF-16 offsets to Python code-point offsets. Reparse
patched scripts AND assert decoded target values; syntax alone misses changed
escaping. Preserve expression syntax and use a serializer for each enclosing
JSON layer. Code `122` operand type 4 is evaluated JavaScript, not a direct
string assignment; blanket conversion to backticks is incorrect.

## Derive layout from this game's settings and assignments

`NRP_MessageWindow` uses `$gameVariables.value(103)` for height: 34 assignments
set 144 px and one tutorial assignment sets 192 px. The usual budget is three
rows, with four in that tutorial. **The initial 788 px static estimate was
superseded by native measurement:** the actual outer window is 808 px wide,
visible inner width 784 px, and `newLineX` 4 px, giving **780 px** at 26 px M+.
NRP's oversized contents bitmap does not enlarge the visible clip. The source audit reported
p99 width 780 px, 16 width outliers and three four-row blocks. It also found
25 occurrences of a missing source glyph, `腟`. These are static source
findings; English fit and actual fallback rendering still need runtime QA.

## What preparation proved

The local catalog has 2,340 units / 4,002 sites with blank targets and zero
unresolved classifications. An empty staged build preserved all 106 source
files byte-for-byte. Synthetic replacement exercised every selected site and
checked JSON structure, IDs, command codes, indents and array lengths, plus
JavaScript reparsing and decoded replacement values. This reference addition
contains documentation, reusable code and synthetic tests; no game corpus.

Probes extracted functions from the shipped engine/plugin scripts:
`Game_Interpreter.command101`, `Game_Message.add/allText`,
`Window_Base.obtainEscapeCode` and `LL_StandingPicture` escape conversion.
They checked spaces, embedded newlines in existing `401` slots, unchanged
command indices, greedy Latin-letter escape parsing and numbered/nested
portrait removal. These are isolated function probes, not a launched game.

For another preparation adapter, preserve an immutable hashed snapshot;
fingerprint source catalog metadata separately from editable targets; bind
config/tool hashes and a store/output stamp; retain targets on re-extraction
and refuse unexplained site loss. Use fresh staging output and exercise real
validator rejection paths. A deduplicated unit's minimum phase cannot stand
in for its individual sites' phase eligibility.

At preparation time, cached names/display variables were an inferred concern.
Later native old-save tests verified exact display migrations and preserved
read flags using the shipped SkipAlreadyReadMessage original-text override.
Command positions alone were insufficient for read-history identity. No
gameplay/save/image certificate follows from the preparation checks themselves;
the completed case study names its separate native evidence and remaining limits.

## Local Windows observations

In this sandbox, Python 3.14.6 `TemporaryDirectory` produced a directory whose
children could not be created (`WinError 5`); ordinary project `mkdir` with
inherited permissions worked. This is an environment observation, not a
general Python diagnosis. A `.cmd` launcher also worked where PowerShell
script execution was disabled, without changing global execution policy.
