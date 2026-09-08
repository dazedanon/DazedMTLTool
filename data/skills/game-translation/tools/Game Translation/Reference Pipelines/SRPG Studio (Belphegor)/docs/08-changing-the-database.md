# Changing the database — what you can edit in the `Project\` folder

## The model

The `Project\` folder is the **unpacked form of `project.dat`** — the game's database broken out into per-domain JSON files. **Every field the folder exposes is LIVE: edit it, relaunch, done — no build step, no loose `project.dat`, no extra files.** Two patches in the exe make that true, between them covering everything in the tree:

- **Strings — Patch 5b.** Every Japanese string is stored as a `{"jp":"…","en":"…"}` pair; the exe reads the **`en`** side at parse time and substitutes it. This is almost the whole tree: `name`, `desc`, dialogue/`data`, menu labels, objective lines, **and `customParameters`** — the entire `{ … }` block is one wrapped string, so *any numbers or flags you write inside its `en`* (a skill `range:`, a `text1:` line) are applied too. Blank `en` → stays Japanese.
- **`fontSize` — Patch 8.** `fontSize` is the one database field that isn't a string (it's a bare number, so the text path can't key on it). At font-system init the exe reads the ten `fontSize` values straight out of `Project\fonts.json` and writes them onto the parsed font records — same edit-and-relaunch promise, no rebuild.

So in the tables below, treat **`{jp,en}` strings (incl. `customParameters`) and `fontSize` as LIVE** — they hot-apply from the folder. There is **no BUILD step** in this kit.

**Two things the folder can't change** (both belong in the SRPG Studio editor, not here):

1. **Deep numeric tables.** This `Project\` tree is a *translation-extraction* of `project.dat`, not the engine's full native record — the unpacker kept the stable `id` plus the translatable strings (and the `customParameters` block) and **dropped the raw numeric tables**. Unit stats/growths/weapon-ranks/promotions, tile coordinates, turn timers, terrain costs, hit/crit/might/weight/price, skill activation %/duration **are not fields here** — they stay baked in `data.dts`. The numbers you *see* inside `desc`/`text1` ("Defense -5", "Turn 11", "Hit+15%") are **descriptive prose**: editing them relabels what the player reads but does **not** change the math.
2. **Structure.** Adding, deleting, retiming, or reordering events / pages / commands would change the database layout, which the loose model doesn't repack. Reword existing lines freely; don't change *how many* there are.

In every table below: `id` is a stable engine join key — **never renumber it** (ids are often non-contiguous and map to fixed offsets); leave it alone.

---

## Units & classes

Files: `players.json` (playable/named units), `classes.json` (job/class defs), `classesgroups.json` (class-change groupings), `classtypes.json` (Infantry/Cavalry/Flying categories driving effective-damage & terrain). **All four are text-only here** — stats/growths/weapon ranks/promotion targets are *not* present.

| field | controls | type | applies? | example |
|---|---|---|---|---|
| `players[].id` | unit identity used by maps/events | int (key) | fixed — leave alone | `0`, `23`, `49` |
| `players[].name` | unit display name | `{jp,en}` | LIVE | `{"jp":"ルート","en":"Root"}` |
| `players[].desc` | unit bio (unit/recruit info) | `{jp,en}` | LIVE | Elron-domain young lord bio |
| `players[].events[].name` | internal label of a per-unit event (on-death, when-wounded) | `{jp,en}` | LIVE | `{"jp":"負傷時","en":"When Wounded"}` |
| `players[].events[].command` | field command label the unit exposes | `{jp,en}` | LIVE | `{"jp":"橋をかける","en":"Build bridge"}` |
| `players[]…commands[].data[]` | spoken/message text from a unit event | `{jp,en}` | LIVE | "What are you doing, Root!" |
| `players[]…commands[].speaker` | who says the line (JP unit name) | bare string | n/a — leave alone | `"シュバイク"` |
| `classes[].id` | class identity (units/promotion) | int (key) | fixed — leave alone | `176`, `199` |
| `classes[].name` | class display name | `{jp,en}` | LIVE | `{"jp":"アサルトナイト","en":"Assault Knight"}` |
| `classes[].desc` | class desc; lists usable weapons after `使用武器：` | `{jp,en}` | LIVE | `…Weapons: Axe, Sword, Lance, Poleaxe` |
| `classesgroups[].id` | class-change group key | int (key) | fixed — leave alone | `2`, `14` |
| `classesgroups[].name` | promotion/class-change group label | `{jp,en}` | LIVE | `Common Tier-1 Class (M)` |
| `classtypes[].id` | unit-category key (effective-vs / terrain) | int (key) | fixed — leave alone | `0`, `3` |
| `classtypes[].name` | category display name | `{jp,en}` | LIVE | `Cavalry`, `Flying`, `Heavy Armor` |
| `classtypes[].desc` | category desc (all `""` here) | `{jp,en}` | LIVE if filled | `""` |
| `classtypes[].customParameters` | designer hook (all `""` here) | string | LIVE if filled | `""` |

**Notes:** Keep `▼▼▼` divider markers in separator class names (just translate the words). Duplicate class names across ids are normal — translate consistently. Weapon usability is *shown* only via the `desc` tail after `使用武器：`, so translate that list consistently. Keep base names identical across `LvN` variants (e.g. "Ben-Ami" / "Ben-Ami Lv1"). Class names live in tight panels — keep them compact ("Dark King", not "Heavily-Armored Bow Cavalier"); `desc` is free prose.

---

## Items & weapons

Files: `items.json` (162), `weapons.json` (213), and `WeaponTypes\{fighters,archers,mages,items}.json`. **Only four keys exist** (`id`, `name`, `desc`, `customParameters`) — **zero numeric stat fields**: might/hit/crit/weight/range/uses/price/weapon-level are *not here* and cannot be changed via this folder.

| field | controls | type | applies? | example |
|---|---|---|---|---|
| `id` | join key back to full data in `data.dts` | int (bare) | fixed — leave alone | `22`, `107` |
| `name` | name in inventory/shop/forecast | `{jp,en}` | LIVE | `{"jp":"馬殺し","en":"Horseslayer"}` |
| `desc` | help/effect text (effective-vs, range, special rules are **only** conveyed here as prose) | `{jp,en}` (sometimes `""`) | LIVE | "An axe with effective damage against cavalry units" |
| `customParameters` | JS object-literal string read by flag plugins; mostly `""` | `{jp,en}` string (the whole JS block) | LIVE | `{ text1: 'Unlimited Uses' }` |

**WeaponTypes** files have the same four-key shape and define the weapon *categories* + triangle relationships, with the bonus written only as prose in `desc` (e.g. Sword: "When fighting axes: Hit+15%, Avoid+15%"). The +15%/+10% numbers are baked in `data.dts` — editing the text changes the explanation, not the math. (`fighters`: Sword/Lance/Axe/Poleaxe/…; `archers`: Bow/Heavy Bow/Siege Bow/Cannon/…; `mages`: Tome/Necromancy/Holy Scripture/Dragon Magic/…; `items`: Staff/Item/Jewel/Fairy Nectar/Crafting Materials/…)

**Notes:** Keep `name` short (forecast/shop truncate — "Long Heal Staff", not "Principality Long-Range Staff"). `desc` is the main surface and the *only* place effect wording appears. In `customParameters`, translate the inner flag strings (`'Unlimited Uses'`, `'Nullifies Iron Wall'`) but preserve the exact JS shape — the `{ … }`, `text1:`/`text2:` keys, single quotes, and literal `\r\n`; one stray brace/quote breaks the parse. Duplicate-name records (different ids for different story/shop contexts) are intentional — translate identically, don't dedupe by editing ids.

---

## Skills, states & mechanics

Files: `skills.json` (334), `states.json` (53), `fusionsettings.json` (2), `transformations.json` (4), `races.json` (9), `movetypes.json` (12), `difficulties.json` (10). **skills/states expose only `id`/`name`/`desc`/`customParameters`** — raw stat tables (bonuses, activation %, duration) are not here; you generally cannot rebalance a skill from these files.

**skills.json & states.json**

| field | controls | type | applies? | example |
|---|---|---|---|---|
| `id` | skill/state id (classes/items/events ref it) | int | fixed | `96` (Cover), `157` (Meat-Shield) |
| `name` | name in skill list / state icons | `{jp,en}` | LIVE | `{"jp":"かばう","en":"Cover"}` |
| `desc` | help text (may be `""`) | `{jp,en}` or `""` | LIVE | `Movement -3` |
| `customParameters` | JS object-literal string; `""` when unused | `{jp,en}` string or `""` | LIVE (incl. the numbers inside) | `{ escort_word:'Cover', range:3 }` |

Inside `customParameters` there are two kinds of content: **localizable lookup words** that must stay in sync with names elsewhere or the skill stops matching — `escort_word` (`'Escort: Root'`), `damage_guard_word` (`'Armor-type'`, `'竜系'`, or the literal keyword `'all'`), `W_Attack_word`, and free help lines `text1`/`text2` (LIVE); and **tunable numbers/flags** whose *effect is the value* — `range`, `death_cancel`, `command`, `reinforce_per`, `break_per`, `unitinfo_num`, `EC_isSrc`, and the bow-range block (`category`/`add_start`/`add_end`/`start_color`/`end_color`). Both are **LIVE**: the whole `customParameters` block is one wrapped string, so to change a number you just write the value you want into the `en` (keeping it valid JS). Watch-outs: many ids share a name on purpose (three "Critical", seven "Masturbating" states) — translate identically; list-header rows (`▼Enemy-Only Skills`) and `(Dummy)`/`（ダミー）` placeholders should be translated but won't appear in-game.

**fusionsettings.json** (Rescue/Capture): `id` (0=Rescue, 1=Capture, fixed), `name`/`desc` (`{jp,en}`, LIVE), and `command` — an **array** of menu verbs ("Carry"/"Put down"/"Swap"), each `{jp,en}`, LIVE.

**transformations.json** (4): `id` (fixed); `name`, `desc` (duration is prose, not a live timer), and `command` (revert verb, may be `""`) — all `{jp,en}`, LIVE.

**races.json** (9): `id` (fixed); `name` (`{jp,en}`, LIVE — "Dragonkin", "Monster: Demon", "Undead"; also doubles as sex tag Male/Female and as the family `damage_guard_word` keys off — keep consistent with skills); `desc`/`customParameters` all `""`.

**movetypes.json** (12): `id` (fixed; per-terrain MP costs are bound to it but **not exposed**); `name` only (`{jp,en}`, LIVE — "Cavalry", "Sky", "Mountain/Desert"). ids 9–11 = spare `Undefined` slots.

**difficulties.json** (10): `id` (fixed); `name` (`{jp,en}`, LIVE — A/B suffix = RNG-reset variant); `desc` (multi-line `\n` blurb, LIVE); `customParameters` all `""` (scaling multipliers not exposed).

**Notes:** keep `escort_word`/`damage_guard_word` in sync with `races.json`/`classes.json` names (leave the literal `'all'`); give identical English to identical duplicate concepts; convert full-width punctuation (`ＨＰ`→`HP`, `＋`→`+`, `Ａ`→`A`) and re-balance `\n` breaks since English expands; stat figures in `desc`/`text1` are display-only — real behavior tweaks are limited to the numeric `customParameters` keys, which are LIVE — edit the `en`.

---

## Maps & events

Files: per-chapter `Maps\map_NNN.json`, global banks under `Base\` (`openingevents`, `talkevents`, `communicationevents`, `autoevents`, `placeevents`, `endingevents`), and `mapcommonevents.json` / `bookmarkevents.json`. Each map holds metadata, the enemy roster (`EnemyUnits`/`EvEnemyUnits`), and event scripts (`pages[].commands[]`, command `type` ∈ `message`/`choice`/`script`). **Rewording dialogue/objectives = LIVE; adding/deleting/retiming/reordering events/pages = structural (editor only).**

| field | controls | type | applies? | example |
|---|---|---|---|---|
| `name` (root) | stage/chapter title | `{jp,en}` | LIVE | `The Enemy Within` |
| `desc` (root) | one-line objective blurb | `{jp,en}` | LIVE | `Wipe out the bandits!` |
| `mapName` | internal map-graphic ref | string | fixed | `""` |
| `id` (root) | map index | number | fixed | `0`, `1` |
| `victoryConds[]` | win-condition lines (4; `""` unused) | `{jp,en}` per slot | LIVE | `Annihilate all enemies` |
| `defeatConds[]` | lose-condition lines (4) | `{jp,en}` per slot | LIVE | `Turn 11 begins` |
| `EnemyUnits[]` | placed-enemy roster | list | structure = editor only | — |
| `EnemyUnits[].id` | unit instance id | number | fixed | `65537` |
| `EnemyUnits[].name` | enemy display name | `{jp,en}` | LIVE | `Bandit Archer` |
| `EnemyUnits[].events[].name` | per-unit trigger label | `{jp,en}` | LIVE | `On Death` |
| `EvEnemyUnits[]` | reinforcement/spawned enemies | list | structure = editor only | `Goblin` |
| `autoEvents[]` | auto-fired stage events | list | text LIVE; retiming = editor | `Transport Unit Deploy` |
| `openingEvents[]` | pre-battle intro | list | text LIVE; structure = editor | `Display Info` |
| `endingEvents[]` | post-clear (rewards/switches) | list | text LIVE; structure = editor | `First Clear Reward` |
| `…events[].id`, `pages[].id` | event/page slot index | number | fixed | `2`, `0` |
| `pages[].commands[]` | ordered event commands | list | structure/order = editor only | — |
| `commands[].type` | `message`/`choice`/`script` | string | editor only | `"message"` |
| `commands[].data` (message) | spoken/displayed line(s) | array of `{jp,en}` | LIVE | `What's the situation?!` |
| `commands[].data` (choice) | player menu options | array of `{jp,en}` | LIVE | — |
| `commands[].data` (script) | raw JS (flags/switches) | array of strings | leave as-is — do not localize | `root.getExternalData()…` |
| `commands[].speaker` | name-plate (bare JP, no `en`) | string | leave as-is* | `"エシュロット"` |
| `commands[].infoText` | full-screen narration/notice | `{jp,en}` | LIVE | `The citizens have sent their thanks!` |
| `commands[].comment` | editor-only note | string | leave as-is | `""` |
| mid-event `victoryConds`/`defeatConds` | change-objectives command | `{jp,en}` per slot | LIVE | — |
| `command`/`commandMsg`/`customParameters` | per-event hooks (usually empty) | string | leave as-is | `""` |

\* `speaker` is a raw JP string with no `en` key, so the LIVE swap can't reach it — the box shows JP unless remapped elsewhere; flag it for the separate name-mapping step, don't type English here.

**Notable absences:** no tile placement, coordinates, appear-turn, deploy-zone, `className`, `weapon`, or stat-override fields exist in `Maps\*.json` — repositioning units, retiming reinforcements, and stat overrides live in the binary `project.dat` and belong in the SRPG Studio editor. Turn/zone *numbers* appear only as objective **text** — editing "Turn 11 begins" relabels the goal but does not retime the limit.

**Notes:** keep chapter titles/objectives terse (fit-sensitive boxes; unused slots stay `""`). Preserve embedded engine codes verbatim in EN — line breaks `\n`, color spans `\C[1]…\C[0]`, full-width punctuation. Mind `infoText`'s existing `\n` hard-wraps (max-fill reflow). Never translate `script` `data`. Don't add/remove/reorder commands or pages during a text pass — that's structural (editor only) and risks desyncing event ids.

---

## Fonts, UI & system

Engine-wide presentation/system layer. Files: `fonts.json`, `titles.json`, `CommandLayout\*.json`, `CommandStrings\*.json`, `ResourceLocation\{screens,strings}.json`, `Variables\variabledata1-6.json`, `bookmark.json` (empty — ignore).

**fonts.json** — ten slots (`id` 0–9), each tied to a screen context.

| field | controls | type | applies? | example |
|---|---|---|---|---|
| `id` | slot index | int | fixed — leave alone | `0`, `4` |
| `fontName` | typeface for the slot | string | not exposed | `"ＭＳ ゴシック"`, `"HGｺﾞｼｯｸE"` |
| `fontSize` | **pixel size — applied live by Patch 8** | int | **LIVE (Patch 8)** | `14` Default, `18` Message, `26` Scroll |
| `name` | author label only (cosmetic) | `{jp,en}` | LIVE | `Title` |

**`fontSize` hot-applies from `fonts.json` (Patch 8 writes it onto the parsed font records at startup), but shrinking it globally to force English to fit is almost always wrong** — each slot's size is tuned to its window geometry, so dropping it fixes one overflow while breaking line-height/centering/spacing on every other screen sharing that slot. Prefer `_reflow` (max-fill) and per-screen layout tuning; reserve a `fontSize` change for a single slot whose window you've verified. `fontName` is a bare (un-wrapped) string the loose path doesn't read, so it isn't folder-editable — the embedded font is swapped by the loose `Fonts\` loader (Patch 6) instead.

**titles.json** — single object, all `{jp,en}`, all LIVE: `windowTitle` (OS caption — applied by **Patch 7**, which reads it from here: `en` if filled, else `jp`, else the engine's own caption), `gameTitle` (in-engine title), `saveFileTitle` (save/bonus label, via P5b).

**CommandLayout\*.json** — top-level menus (`title`, `base`, `mapcommands`, `battleprep`, `manage`). **Array order = on-screen order** (reorder/remove = editor only); only `commandName` (`{jp,en}`) is LIVE. Keep decorative glyphs like the leading `★` in `★Communication`.

**CommandStrings\*.json** — interaction verbs (`placeevents` = environment actions; `talkevents` = unit actions). `id` (int, fixed, don't touch); `command` (`{jp,en}`, LIVE — "Move Drawbridge", "Talk", "Capture").

**ResourceLocation\screens.json / strings.json** — engine system-string tables. `screens.json` = top-level screen labels (31, ids 0–30). `strings.json` = dense in-battle vocab: menu verbs (Steal/Seize/Wait), **stat labels/abbreviations** (Strength/Magic/Skill/Speed/Defense/Res/Movement/Constitution), forecast labels (Attack/Hit/Crit/Avoid/Range/Effective/Might/Weight). Each `{id, name:{jp,en}}` — `id` fixed, `name` LIVE. These are the **highest-value fit-sensitive LIVE strings**: keep them short (`魔防`→`Res`, `回避`→`Avoid`, `必殺`→`Crit`) for the narrow stat/forecast panels. **Leave `strings.json` id 17 (`ＨＰ`) as `"en":""`** — that's deliberate so the bare `HP` graphic shows; don't fill it.

**Variables\variabledata1-6.json** — author-facing names/descs of save variables & switches (same tables as `tooling/saveeditor/savevars.py`). `id` (int, fixed, **never renumber** — non-contiguous, maps to fixed save offsets); `name` and `desc` (`{jp,en}` or `""`, LIVE). These are **dev-only documentation** (surface only in dev menus / the save editor, not normal play) — translate for tooling clarity; near-zero player impact, low localization priority.

---

## Other domains (same model)

These folders/files weren't broken out above but follow the identical rule — `id`
is a fixed join key (leave alone), every `{jp,en}` `name`/`desc`/`command` is LIVE text, and `pages[]`
structure/order is editor-only. Audited field shapes from the live tree:

- **`Extra\` — gallery & recollection mode (high player value).** `characters.json` (35), `gallery.json` (2), `glossary.json` (108), `recollection.json` (123), `soundroom.json` (13). All carry `id`/`name`/`desc` (+ `pages` on the event-bearing ones, + `customParameters`). The CG gallery, the in-game **glossary/encyclopedia**, scene-recollection titles, and the sound-room track names all live here — `name`/`desc` LIVE, `pages[]` (recollection event scripts) editor-only. Don't skip these: the glossary and gallery are a large, very visible body of player-facing prose.
- **`NPCSettings\npcN.json`** — generic/enemy unit templates: `id`/`name`/`desc`/`customParameters`. `name`/`desc` LIVE (enemy display names + bios); stats live in `data.dts`, not here.
- **`shoplayout.json`** (11) — shop-screen layout strings: `id` (fixed), `name`/`msg` (LIVE — shop labels and prompts).
- **`Terrain\`** — `terraingroups.json` (5) has `id`/`name` (LIVE — terrain category names); `originalterrains.json` (40) is `id`/`terrains` (raw terrain records, **no text** — movement costs/defense are baked here and, like all numeric tables, not exposed for editing). `runtimeterrains.json` likewise has no editable text.
- **`OriginalData\originaldataN.json`** — designer custom-data slots; empty in this game (nothing to translate). `bookmark.json` is empty too — ignore both.

---

## Common localization tweaks

- **`fontSize` for fit — last resort, with caveat.** It's the only direct "make text smaller" knob (live via Patch 8), but it's shared across screens; shrinking it globally breaks line-height/centering elsewhere. Prefer reflow (max-fill) and wording; if you must, change one verified slot.
- **Item/skill/weapon `desc` trims.** `desc` is free prose (nothing is parsed from it) and the *only* place effects, ranges, effective-vs targets, and triangle bonuses are explained — rewrite for clarity, but keep it within the help box and preserve `\n`/`\C[…]`/full-width codes.
- **Command-label & menu-label widths.** `CommandLayout`/`CommandStrings` verbs and `ResourceLocation` stat/forecast labels render in narrow panels — keep them compact (`End Turn`, `Res`, `Crit`, `Avoid`); never reorder the arrays.
- **Names short.** Unit names, class names, and weapon/item names render in tight panels, shops, and the forecast box — keep them compact to avoid truncation; bios and class `desc` are freer.
- **Preserve markers & codes verbatim.** Carry `▼▼▼` dividers, leading `★`, color spans `\C[1]…\C[0]`, line breaks `\n`, and the `{ text1:'…' }` JS shape (with `\r\n` and single quotes) unchanged into EN.
- **Keep lookup words in sync.** `escort_word` / `damage_guard_word` must match the race/class names you used — rename a family in both places or the skill silently stops matching (leave literal `'all'`).
- **Convert full-width punctuation** (`ＨＰ`→`HP`, `＋`→`+`, `Ａ`→`A`) and re-balance `\n` breaks as English expands — except deliberately-blank slots like `strings.json` id 17.
- **Translate duplicates identically; never touch `id`.** Same-named records/skills/states are intentional engine duplicates — give them the same English; `id` is a positional join key everywhere.