# Loccubus preparation census

## Build and language

The shipped engine identifies itself as RPG Maker MZ 1.9.0.
The game title is Loccubus v1.0 and `System.json.locale` is `zh_CN`.
The authoritative source is Simplified Chinese; Japanese content is a separate localized route.
There are 51 recursively discovered JSON files under `data/`, including MUUI layouts and locale dictionaries.
The initial inventory recorded 130 text/runtime/font files and 26 enabled plugins among 30 registrations.
Concurrent DazedTL initialization subsequently appended the enabled `TranslationUpdateCheck` plugin, bringing the tracked inventory to 131 files and enabled plugins to 27 among 31 registrations.
The verified baseline archive preserves that current setup.

## Localization findings

`MUUI_Localization` registers `zh` and `ja` only, with `zh` as the default.
It loads `data/locales/<locale>.json`, resolves `#...#` tags, and also supports exact plain-text dictionary matches.
`data/locales/en.json` contains 49 stock English entries, while the source layouts mostly use Chinese lookup keys.
Those entries are not an existing English translation of this game.
`BY_CommonEventLocale` declares 80 Japanese routes and 80 English routes.
The English replacement events contain 5,345 message lines, including 5,100 lines with Chinese/Japanese characters.
Simply enabling English would select unfinished story content.
No locale is activated by these preparation tools.

## Event-code rulings

| Code | Count | Preparation ruling |
|---|---:|---|
| 101 | 18,118 | Native nameplates; narrative outside this prepared UI scope |
| 401 | 18,120 | Message rows; narrative outside this prepared UI scope |
| 102 | 25 | Scene choices outside this prepared UI scope |
| 402 | 38 | Branch labels; preserve branch indices and original text |
| 108 / 408 | 468 / 2 | Comments/metadata; no blanket translation |
| 118 / 119 | 451 / 111 | Exact control-flow labels; protected |
| 122 | 504 | 133 script operands; no display-variable whitelist established |
| 111 | 313 | Conditions; never independent translation units |
| 355 / 655 | 1,337 / 32 | Script blocks; identifiers, calls, and expressions protected |
| 357 / 657 / 356 | 0 / 0 / 0 | Absent; do not copy other games' plugin-command whitelists |
| 405 / 320 / 324 / 325 | 0 / 0 / 0 / 0 | Absent |

The complete 49,436-command census is in `reports/census.json`.
Raw narrative text is not exported into the translation catalog.
Source content explicitly identifies minors in sexual scenes; those scenes are excluded.
`reports/content_exclusions.json` records evidence coordinates and excluded message/nameplate/choice command locations without their text.
Other content-specific interfaces and unreviewed script/database fields remain outside this prepared subset.

## Reviewed text tracks

| Track | Sites | Handling |
|---|---:|---|
| Standard System terms, currency, type labels | 132 | Exact display leaves, phase 0 |
| MUUI Save/Load/Skip confirmation text | 11 | Preserve original hash keys; add English dictionary values |
| General plugin labels | 7 | Exact reviewed `plugins.js` parameters, phase 2 inventory |
| Runtime save-slot labels/status | 8 | AST-located static literals/templates in `MU_SavefileHelper`, phase 2 inventory |

These 158 sites produce 137 deduplicated units, all with empty targets.
The preparation builder makes a staged subset for review only and never installs it.
Synthetic phase 2 checks do not authorize a translated phase 2 deployment.

## Further consumer findings

MUUI text commonly lives in `root.children[].content`, with nested containers and separate action scripts.
Component `name` fields, bindings, style action code, resource paths, and font families are not automatically display text.
Bound save-preview content includes variable expressions, numeric examples, and a sample timestamp; these were deliberately excluded from dictionary authoring.
`MU_SavefileHelper` also contains Chinese comparison keys for save data access; only the eight reviewed runtime label sites are eligible.
The plugin source census uses Acorn so comments and regexes are not mistaken for display literals.
Other Chinese/Japanese plugin literals remain inventory entries requiring consumer review, not automatically translatable text.
`UI/MU_Internal` contains modules loaded by the MUUI framework beyond the directly registered plugins.
The source inventory records these separately as dynamic dependency candidates.

Speaker fields may contain portrait metadata such as `@5$rah1_1` after the visible name.
Do not translate or discard the suffix, and do not prepend a second speaker name to an MZ message body.
Some native nameplate fields contain long narrative sentences, so length alone is not a safe identity heuristic.
`BY_MessageWindow.specialNameConfigs` contains exact source-name matches that would need a coordinated update with any permitted name translation.
`Actors.json` contains stock RPG Maker actors; those names must not be mistaken for the story's cast.

## Layout and delivery

The game uses a 1920 by 1330 interface, the `yuyang-W03` main font, and a custom message window.
The message plugin declares a 1720-pixel text width, 42-pixel font, three rows, and automatic wrapping.
Those are static configuration findings, not measurements of rendered clipping.
General MUUI widgets have their own font sizes and dimensions; see `reports/layout_source.json`.
Settings also use image-backed controls; their artwork is outside this request's image scope.
Only the reviewed dictionary, System fields, and exact plugin sites are staged for this preparation.
No game executable was launched and no save compatibility claim is made.
