# Census - the evidence behind every ruling

Which optional codes hold text is a property of *this game*, not of the engine.
Guessing wastes a translation pass in one direction and ships Japanese in the
other. Everything below was counted, not assumed. Re-run `python tl.py census`
after any game update and re-read this file before changing a flag.

## Engine

| | |
|---|---|
| Engine | RPG Maker **MV** (`www/` layout, `nw.dll`, `package.json`) |
| Build | v1.0, **trial version** - the script itself says so (`体験版では淫乱度最大値の上昇はありません`) |
| Screen | `Community_Basic screenWidth = 1020`, `screenHeight = 780` |
| Font | `www/fonts/mplus-1m-regular.ttf`, `Window_Base.standardFontSize() = 28` (MV stock, no plugin override) |
| Delivery | loose files over `www/data` + an in-place `www/js/plugins.js` |

## Event code census

```
    0  10408      401   4193      505   3604      117   2691
  101   2596      230   1450      123   1408       15   1338
  121   1336      122   1243      111    943      412    943
  250    938      356    912      205    670      118    459
  119    244      655    173      108    162      355    129
  402    116      102     53      408     12
  405      0      357      0      657      0      320/324/325  0
```

### Rulings

| Code | Count | Ruling | Evidence |
|---|---|---|---|
| **401** Show Text | 4,193 | **ON** | The dialogue. Runs are 1-4 commands long (`{1:1350, 2:921, 3:299, 4:26}`), matching `Window_Message.numVisibleRows() = 4`. |
| **102** Show Choices | 53 | **ON** | 22 unique labels, `はい`/`いいえ` dominating. No plugin visibility conditions in any of them, but the balanced-paren splitter runs anyway. |
| **402** branch label | 116 | **mirrored** | The engine branches on `parameters[0]`, the index, so `parameters[1]` is editor-facing. Injected by index from the matching 102 so the two cannot drift. |
| **356** MV plugin cmd | 912 | **ON, whitelisted** | Eight distinct keywords. Only **`LL_InfoPopupWIndowMV showWindow`** carries text, and only 4 distinct strings across 41 commands (`淫乱度+\V[2]`, `淫乱度\V[2]`, `魔力\V[66]`, `魔力-\V[2]`). The other 871 are `PSS start`, `CRTA_TimerManager pause`, `showHpGauge`, `SetCharLight 0 4 4 50`, `ShopInventory apply shop1`, `SetMapDarkness 100` - pure control. |
| **355 / 655** script | 129 / 173 | **OFF** | 108 of the 129 blocks contain Japanese and **every one of them is a `//` developer comment** (`//▼淫乱度上昇開始`, `//▼宝箱と敵を強制リスポーン`). Zero display strings. |
| **122** Control Variables | 1,243 | **OFF** | Operand types are `{0: 829, 1: 222, 2: 99, 3: 92, 4: 1}`. **Exactly one** has `parameters[3] == 4`, and its value is `AudioManager.currentBgmVolume`. There is no text here. |
| **111** Conditional Branch | 943 | **OFF, permanently** | Condition types are `{0: 502, 1: 387, 12: 29, 8: 23, 3: 2}`. Every type-12 script test is `$gameParty.isAnyMemberEquipped($dataArmors[N])`. **There is not one `$gameVariables` string comparison in the game**, so the 122/111 reconciliation that makes most RPG Maker patches unwinnable does not apply here. |
| **108 / 408** comments | 162 / 12 | **OFF** | Four distinct 108 values, all developer notes (`▼ここに障害物消滅フラグON` ×73, `▼ここに初回会話フラグ諸々` ×65, …). All 12 408s are the same string, `魔力消費量をtempに代入`. No plugin markers - no `info:`, no `<ActiveMessage:`, no `選択肢ヘルプ`. |
| **118 / 119** label / jump | 459 / 244 | **HARD OFF** | Jump targets matched by string equality. 244 chances to break a scene invisibly. No override flag exists. |
| **405** Scrolling Text | 0 | absent | The 405 write-back path exists anyway and is exercised by the tests. |
| **357 / 657** | 0 | absent | MZ-only. |
| **320 / 324 / 325** actor setters | 0 | absent | |

### Where the dialogue lives

Not all in `Map*.json`: `CommonEvents.json` holds 635 of the 4,193 lines, and
`Map029` (the village), `Map036`/`Map006` (the forest), `Map035` (the cave) and
`Map034` (the castle) hold most of the rest. `Troops.json` holds none - there
are no battles in this game at all.

## Control codes actually present

Counted over every 401, 102, 356 and database description:

```
\F[..]   1247   LL_StandingPictureMV portrait 1   ALWAYS a leading run
\FF[..]    15   portrait 2                        ALWAYS a leading run
\V[..]     67   variable value                    inline content
\.         17   quarter-second pause
\^          7   close without waiting
\G          4   currency unit
\|          2   one-second pause
```

**Absent:** `\C` colour, `\I` icon, `\N` actor name, `\P` party name, `\{`/`\}`
font size, `\FS`, `\r` ruby, `%1` outside System.json. And **not one orphan
backslash in the corpus**, so the `\ヘレン -> \Helen` failure class cannot arise
from the source - only from a model inventing one, which `bare-escape-eats-word`
catches.

## Speaker attribution

This game stores no speaker anywhere:

* **Code-101 arity is 4 on all 2,596 headers**, so there is no MZ
  `parameters[4]` name box.
* **`parameters[0]` (the face graphic) is empty on all 2,596 of them**, so
  `Window_Message.newLineX()` is 0, there is no reserved portrait width, and
  face-filename attribution is not even available as a last resort.
* There are no `【Name】` brackets, no `Name「` inline forms and no trailing
  `：` nameplates. A scan of the first line of every 401 block found 5 possible
  `Name「` hits out of 2,596 - noise.

What it *does* have is `LL_StandingPictureMV`. All 132 portraits are the same
character: the `C_` / `B_` / `M_` / `N_` prefixes are **costume** variants
(normal / bunny / micro / naked, matching the 通常/バニー/マイクロ/裸族 costume
menu), not different people. So:

> A 401 block whose first line opens with a portrait run is **Mineria**.
> Anything else gets an **empty** speaker and leans on the scene label.

That yields 1,274 attributed and 1,212 unattributed lines.

### The one evidence-based exception

Common events named `E<monster>接触` are trap-encounter CG scenes. The portrait
code is absent because a CG replaces the portrait, but the protagonist is the
only speaker. Checked across **all 22** of them: zero lines carry a male marker
(`俺` / `てめえ` / `だぜ` / `グオオ` / `やがる` / `ぞー`) and every one reads as
her first person. That is a per-scene rule proved over the corpus, not a
per-line inheritance, so it does not reintroduce the stateful
last-101-seen failure.

BAD END events are **excluded** from the rule: `CE87 '犬みたいなBADEND'` has
three hero-party lines in it.

## Text box geometry

Measured three ways, and they agree.

1. **Window geometry.** `Graphics.boxWidth = 1020` (Community_Basic),
   `Window_Message.windowWidth() = Graphics.boxWidth`,
   `Window_Base.standardPadding() = 18` -> contents width **984px**.
   `numVisibleRows() = 4`.
2. **The font.** `mplus-1m-regular.ttf`, `unitsPerEm 1000`, and the advance
   histogram has exactly two spikes: **1000 (6,270 glyphs)** and
   **500 (1,488 glyphs)**. Genuinely monospace, so a cell count is exact.
   At `fontSize 28` a half-width cell is **14.00px** -> `984 / 14 = 70.28`,
   so **70 cells** is the hard cap and the wrap is configured at **68**.
3. **The author's own lines.** The shipped 401 width histogram clusters hard at
   60-72 cells and thins out immediately above it. A handful of lines reach
   76-99 cells - those are **already clipped in the Japanese build**, which is
   why the author's own maximum is a cross-check and not the budget.

Characters the shipped font cannot draw, which therefore render from a browser
fallback whose metrics we do not control (already true of the Japanese build):
**U+2764 ❤** and **U+266A ♪**. `measure.missing_glyphs()` lists them rather
than silently assuming a width.

`U+00A0` NBSP **is** in the font at half width, which is what makes the
single-token plugin-argument trick work.

## What the engine does to a translated string

Traced with `python tools/trace_parser.py`, which reads every regex, delimiter
and replacement **out of the shipped JavaScript at run time** and raises if an
anchor has moved.

| Stage | Behaviour | Consequence |
|---|---|---|
| `Game_Interpreter.command356` | `this._params[0].split(" ")` - **ASCII space only** | One space inside a popup's text argument truncates it to the first word. NBSP survives the split and renders. |
| `Game_Message.allText` | `this._texts.join('\n')` | k wrapped lines across c commands render `max(k, c)` rows. |
| `LL_StandingPictureMV.convertEscapeCharacters` | strips `\F` `\FF` `\FFF` `\FFFF` `\M*` `\AA` `\FH` | Portrait codes cost zero width - the measurer treats them as such. |
| `Window_Base.convertEscapeCharacters` | `\` -> `\x1b`, `\x1b\x1b` -> `\`, then `\V[n]` `\N[n]` `\P[n]` `\G` substitution | Value codes are consumed before the lexer sees them. |
| `Window_Base.obtainEscapeCode` | `/^[\$\.\|\^!><\{\}\\]\|^[A-Z]+/i` | **`\Helen` lexes as one code named `helen` and the word is never drawn.** Japanese never trips this; English is what creates it. |

Only `LL_StandingPictureMV` overrides `convertEscapeCharacters` in the enabled
set. `YEP_CoreEngine`, `HalfMove` and `DTextPicture` ship as files but are not
registered in `plugins.js`, so they never run.

## `js/plugins.js`

33 entries, 30 enabled. 29 translatable text leaves, found by decoding each
parameter recursively while its decoded value was still an object, an array or
another serialized string - never by a blanket "find Japanese in the file" scan.

Two facts nothing else would catch:

* **`LL_MenuScreenCustomMV.menuHelpTexts[].symbol` is keyed on the DISPLAYED
  command name** (`menuHelpLists[this._commandWindow.currentName()]`,
  `LL_MenuScreenCustomMV.js:613`), which comes from `System.json terms.commands`.
  Translate the command and leave the symbol and every menu help line silently
  disappears. `tl.py plugins check` proves the two agree.
* **`MessageWindowHidden.triggerButton` contains `右クリック`**, and
  `MessageWindowHidden.js:334` matches it with `case '右クリック':`. It is on the
  do-not-translate list.

`MapNameExtend` has `実名表示 = false`, so `MapInfos.json` names are the
editor's map tree and are never drawn. Only `Map*.json displayName` reaches the
screen - 19 of them.

## Images

Only **`img/titles1/_Title.png`** carries baked text. `system/GameOver.png` is
already English; the 57 `S_*` CG stills carry none. See `images/title.py`.

Both text blocks on it are replaced: the two-line logo (set as **three** lines
in English, because 44 characters against 16 cannot share a size on a 1020px
canvas) and the circle badge `さざめき通り`, **romanised** to `Sazameki-dori`.
A circle name is a brand, so it is romanised rather than translated - a literal
"Rustle Street" is what nobody searches for. Nothing on the image is left in
Japanese.
