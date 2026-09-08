# Per-game decisions

Evidence is in the pristine `source/` tree and the generated `reports/` files.
These decisions apply to this exact MZ 1.9.0 build, not to every MZ game.

## Data and event text

28 JSON files under `data/`; 14 maps. All 14 `displayName` fields are blank.
There is no enabled MapNameExtend or map-name lookup/fallback consumer, so
MapInfos and event editor names remain protected.

| Code | Count | Ruling |
|---|---:|---|
| 101 | 1,964 | Native nameplates in `parameters[4]`; 920 populated, no faces |
| 401 | 3,943 | Join consecutive lines into 1,939 nonempty message units |
| 102 / 402 | 160 / 320 | Six distinct choices; branch labels mirror choice by index |
| 122 | 501 | No direct display-string assignments; three script operands are arithmetic |
| 111 | 741 | No Japanese string comparison; preserve conditions |
| 355 / 655 | 167 / 94 | Only the 23 JP-bearing assignments to display variable 125 are extracted |
| 357 | 790 | Whitelist LL_InfoPopupWIndow.showMessage.messageText and TextPicture.set.text |
| 657 | 760 | Editor argument echoes, untouched |
| 108 / 408 | 499 / 1 | Comments/editor instructions; no display-comment consumer found |
| 118 / 119 | 5 / 21 | Control-flow labels, always protected |
| 303 / 405 / 320 / 324 / 325 | 0 | Not used by this game |

`EventCommandByCode.execute` contains six calls, all technical `Stamina SetMax`
commands. The other enabled code-357 consumers manipulate timers, sensors,
switches, achievements by ID, window IDs or scene IDs. `seName` in popup
commands is an audio resource path, not popup text.

Variable 125 is assigned three distinct status labels by
`$gameVariables.setValue(125, "...");`. The only shipped consumers render it
from SceneCustomMenu's ItemDrawScript. Neither event conditions nor enabled
plugin source compare those three values as keys. Only the parsed quoted
literal is editable; the script expression and variable ID remain unchanged.

LL_VariableWindow draws `$dataSystem.variables[id]` as the label. IDs 86 and 102
are the only IDs passed to it; 86 needs translation, 102 already says HP.
All other switch/variable names remain protected editor/technical labels.

CustomizeFailureMessage draws the value in `<失敗メッセージ:...>` (three notes).
The value is a span edit; the tag name and every adjacent tag remain intact.
Other shipped tags are command keys, belongings, stamina and sensor settings.

## Extra text tracks

- SceneCustomMenu has labels, help text and JS templates inside repeatedly
  JSON-encoded parameter strings. Parse each layer; edit only Text/HelpText or
  literal/template-fragment spans in ItemDrawScript. Interpolated expressions,
  IDs, scripts, asset names and filter logic stay intact.
- TorigoyaMZ_Achievement2 uses title/description/hint plus popup and menu labels.
  Achievement keys/IDs and switch IDs are separate and remain unchanged.
- RecollectionModeMZ loads **img/system/RecollectionModeMZData.json**, containing
  25 titles. Its loader explicitly uses the img/system path. This is JSON text,
  not image translation. Picture paths, common-event IDs and switch IDs remain
  untouched. Its five configured UI labels are separate units.
- Mano_InputConfig selects its Japanese branch via the game's locale. Extract
  the JP display leaves, keeping input symbols/keys and locale unchanged. Three
  normal display labels also occur in source; other Japanese source literals
  are key names, parser enums, diagnostics, or configured fallback values.
- CharacterPictureManager compares a message speaker to `gameActor.name()`.
  Actor names and identical native MZ speaker names share the same name unit;
  picture IDs and the picture-definition Name metadata are untouched.
- Game title is shared across System.gameTitle, package.window.title and
  index.html's title. `optDrawTitle` is false, so this text is a window caption.
- Engine source's 170 Japanese literals are name-entry keyboard tables; no
  Name Input Processing command exists in this game.

All 38 enabled plugin scripts and six root JS scripts were parsed with Acorn.
The source tree also preserves the two disabled registered plugins, unregistered
plugin files and shipped JS libraries. They are not blanket-translated.

## Control codes and layout

The enabled LL_StandingPicture plugin processes numbered `F1`–`F8` and `M1`–`M8`
codes, including nested variable arguments, before MZ parses text escapes.
The reference mask was adapted to protect these whole. `AA`, `C`, `V`, currency
and numbered `%` inserts are also preserved. Source text is never cleaned or
typographically normalized during extraction.

M+ 1m regular WOFF at 26px; screen and UI area 816×624; window padding 12px;
unfaced message newLineX 4px, hence 816−24−4 = 788px. NRP_MessageWindow reads
height from variable 103: 34 assignments to 144 and one to 192. The practical
baseline is three rows, with four-row tutorial cases needing the tall window.
The status windows are 200px wide; their label allocation is 60%, or 120px.

After correct portrait-code removal, source p99 static width is 780px. Sixteen
source messages exceed the derived width and three exceed three physical rows;
these remain runtime calibration cases, not reasons to alter the game during
setup. The shipped font lacks one source glyph (25 occurrences). English font
coverage, variable expansion widths and actual menu layout still need review
on the translated build. No fit pass is claimed for this preparation.

## Save and validation contract

Injection changes strings only: same files, object keys, array lengths, command
counts, codes, indents, IDs and numeric values. Extra message line breaks use
existing command slots, which the shipped command101/allText probe verifies.
The full synthetic test exercises every real write location, then reparses JS
and reads decoded values back. It also checks every written JSON value and
message block. Empty output matches the 106 source files byte for byte.

This proves structural tooling behavior. It does not prove gameplay, English
quality, fitting, read-history migration or cached save-display text. Those
checks belong to the later translation/export task. No synthetic output was
installed and every real translation target remains empty.
