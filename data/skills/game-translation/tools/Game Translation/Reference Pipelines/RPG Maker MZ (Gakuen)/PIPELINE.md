# RPG Maker **MZ** pipeline - `mztl`

Translation of `体だけは立派な落ちこぼれ陰キャ魔法使い学園トップになるまで帰れません`
(ver 1.03) to English.
**10,501 units, 100% translated, $3.32 on Sonnet 5 batch + cache.**

Adapted from `Reference Pipelines\RPG Maker MV (Mineria)\`.
Everything below is either a per-game FACT (redo the census for the next game)
or a fix that is worth carrying forward.

## Result

| | |
|---|---|
| units | 10,501 (8,323 dialogue, 580 names, 404 descriptions, 374 choices, 263 battle messages, 166 popup/plugin, 41 choice-help, 45 map banners, 76 UI terms/types) |
| glossary | 189 characters, 47 locked terms |
| `js/plugins.js` | 236 leaves across 24 enabled plugins |
| images | 3 (the only ones with baked player-facing text) |
| hard validation failures | 0 |
| structural differences vs source | 0 across 5,195 command lists / 58,070 commands |
| cost | names $0.02 + text batch $3.15 + plugins/retry/tighten $0.15 |

## The per-game work

Every ruling below came from `audit/CENSUS*.txt`, not from a default.

### Event codes

| code | count | ruling |
|---|---|---|
| `401` | 28,236 | ON. 24,024 of them in `CommonEvents.json` - the maps hold almost nothing. |
| `101` | 8,368 | **`parameters[4]` on only 41, a face on only 37.** The MZ speaker field is effectively unused - see Speakers. |
| `102` | 178 | ON |
| `122` | 220 | ON, whitelisted to variables **1, 35, 61, 64, 67**. 43 of them have `parameters[3] == 4`; those five ids hold month names and "who did this to you" labels, all read back only through `\V[n]`. |
| `111` | 586 | **OFF, permanently.** Condition types are `{0,1,2,4,7,8,10,12}` and not one of the 19 script conditions mentions `$gameVariables`, so there is no string comparison to reconcile and the usual 122/111 unwinnable-quest trap does not exist here. |
| `355/655` | 179 / 668 | ON, **`テキスト-` rows only**. Every block is a `CBR_EroStatus` command list; `画像-` is a filename and `左右-`/`上下-` are keys the plugin compares against 左/中/右 and 上/中/下. |
| `357` | 199 | ON, whitelisted to `DTextPicture.text` and `TorigoyaMZ_NotifyMessage.message`. `parameters[2]` is the editor's own command label and the engine never reads it. |
| `657` | 461 | OFF. Every one is an argument echo restating the `357` it follows. No `メッセージ` key anywhere. |
| `108/408` | 91 / 111 | ON for `選択肢ヘルプ` **only** - `MPP_ChoiceEX`'s `Choice Help Commands` parameter lists that marker literally, and the plugin draws the following lines as the choice-help window. Everything else in a comment is dev notes, `<balloon:4 >` or `<Label>` plugin config. |
| `118/119` | 102 / 106 | HARD OFF |
| `320/324/325/356/405` | 0 | absent |

### Speakers: the first physical line of the 401 run

This game stores no speaker in any engine field. It writes the name as the
**first rendered row of the message**, with the dialogue opening on the next
line inside `「」`:

```
401  アズサ
401  「わわわ……こんな恰好で外なんて歩けないよ」
```

4,872 of 8,368 blocks match; the other 3,496 are narration and get an **empty**
speaker rather than an inherited one. 186 distinct names came out of it.

The gate is the skill's `FIRSTLINESPEAKERS` rule plus **two additions this
corpus forced**:

* the candidate must not itself open with a quote - three `「…」` lines whose
  successor was also `「…」` were being eaten as names;
* the candidate must carry **no sentence-terminal punctuation**, which is what
  separates `催眠術師` from the narration line
  `おずおずと男の股間のモノに触れる。` - 20 characters, contains Japanese, and
  followed by a line that opens a quote, so it passed every other gate.

Because the plate is a rendered row, it **costs one of the four rows**, and
`inject` wraps the body to `max_rows - 1` whenever a speaker is present.

### Geometry, measured

```
System.json advanced.screenWidth = 816   -> Graphics.boxWidth
System.json advanced.fontSize    = 20
Scene_Message.messageWindowRect          -> calcWindowHeight(4) = FOUR rows
LL_MessageWindowAdjust (enabled)         -> this.width = boxWidth - 40*2 = 736
Game_System.windowPadding()      = 12    -> innerWidth 712
Window_Message.newLineX          = 4     -> usable 708 px
fonts/x12y12pxMaruMinyaM.ttf: unitsPerEm 1200, exactly two advance spikes
    (1200 x 7,242 glyphs, 600 x 277) -> genuinely monospace, cell = 10.00 px
708 / 10 = 70.8  ->  70 cells hard, wrap at 68
```

`Window_Help` is the full 816 (792 inner -> **79 cells**, 2 rows), and the 37
faced messages get 628 px -> 62 cells. Those are three different caps and
`Config.hard_cap()` is the single function both the injector and the validator
read - see below.

## What was worth fixing, and would have shipped broken

**A plugin visibility condition, deleted.** Four choices read
`はいen(v[3]<=50)(貞操観念が50以下)`. The inherited splitter anchored on
`\b(?:if|en)\(` - and `\b` requires a word/non-word transition, which does not
exist between `い` and `e` because Python's `\w` includes CJK. So it matched
nothing, the clause went to the model as ordinary text, and the translation
came back `Yes (Chastity 50 or Below)` with the gate **gone**: a choice
gated on a stat, permanently visible. Conditions are now masked into `⟦n⟧`
sentinels wherever they sit, which puts them under the placeholder validator.

**And the relaxation that let it through a second time.** Loosening the
placeholder check to compare RESTORED code multisets (see below) re-opened it,
because a condition clause is not a control code and so is invisible to that
comparison. A missing sentinel is now only forgivable when it restores to a
code the regex actually recognises.

**41 Japanese name plates over English dialogue.** `code-101 parameters[4]` is
used by only 41 of 8,368 headers, so the extractor correctly ignores it - but
`Window_NameBox` draws whatever is in it. Nothing in a per-unit check can see
this, because the plate is not part of any unit's text. **The output scan found
it**, and it is now a glossary-driven injection pass like the actor names.

## What was worth fixing in the CHECKS

The first real run reported 150 placeholder failures, 99 plugin-arg failures
and 294 number-drift failures. **Almost none were translations.**

* **placeholder 150 -> 5.** The model routinely restores a code itself,
  writing `%1's attack!` where the payload said `⟦0⟧の攻撃！`. That is
  byte-identical to what the injector would have produced. The sentinel
  comparison is now a cheap pre-filter and the restored multiset decides.
* **plugin-arg 99 -> 0.** The inherited rule was "no ASCII space in a plugin
  argument", which belongs to MV's code 356 and its
  `this._params[0].split(" ")`. **This game has zero code-356 commands.** Its
  three `ptext` hosts each tokenise differently and none on space, so the check
  is now keyed on the HOST command.
* **number-drift 294 -> 248**, by ablation (`audit/numablate.py`), keeping only
  rules measured net-negative:

  | rule | fixes | causes | net |
  |---|---|---|---|
  | digit + scale word (`15 million`) | 4 | 0 | -4 |
  | bare scale word (`the top hundred`) | 2 | 0 | -2 |
  | counters `番` `位` `点` | 5 | 0 | -5 |
  | English ordinal (`7th` vs `7位`) | 6 | 2 | -4 |
  | kana numerals (`ふたつ`) | 3 | 6 | **+3 - REJECTED** |

  The kana rule is the one worth remembering: the full table including ひとり
  and ふたり fixed 3 and created 23, because `ふたりきり` is "alone together".
  It is left in the file, empty and documented.

  After the `+`-sign and condition fixes the **conflict bucket - where a real
  quantity error would have to appear - is empty**, so the remaining 248 are
  English restructuring a quantity and the check is REPORTED but excluded from
  the retry queue, with the reason printed next to the count.
* **`identical` 115 -> 33.** 82 were locked units: the stock-UI seeds and the
  silent-beat boxes, which are `identical` because that is exactly what was
  intended. Counting them buried the 33 real echoes.
* **`overflow`**: three item descriptions were reported at 74 cells against a
  cap of 70 - the MESSAGE box's cap, applied to text that renders in the 79-cell
  help window. `Config.hard_cap(kind, faced)` is now the one function both
  paths read, because the two disagreeing is invisible.

## Four more, found by PLAYING it - and only by playing it

All of these shipped with every validation counter green, because the thing
they have in common is that **none of them produced a unit**, and every check
in this pipeline is per-unit.

**A blanket denylist left Japanese in the opening menu.** `DO_NOT_TRANSLATE`
began as one set checked against every unit of every kind. `普通` is in it
because `Keke_AnyTimeFontChange` resolves a registered font by that call name -
but `普通` is *also* the middle option of the difficulty picker, a texture
choice, and the value picture echoing the chosen difficulty; `ドット` is that
call name *and* a visible font choice. Four player-facing strings were therefore
never extracted, and **a unit that was never extracted cannot fail any check**,
so the character-creation screen shipped reading `Easy / 普通 / Hard`.

What makes translating them safe is the data, not a denylist: code 402 branches
on the choice **index**, the difficulty branch writes `122 [80,80,0,0,n]` by
index, and the font branch passes its call name as a *separate literal* in a
`357 fontName` argument this pipeline never extracts. The source proves the two
are independent by writing the choice as `ノーマル` while the argument says
`普通`. The set is now `KEY_STRINGS`, applied **only** where the extractor can
reach a key - code 122 values. Not to 401, 102, 108/408 help, CBR `テキスト-`
rows, or 357 arguments, because `cfg.plugin357_text` admits nothing but
arguments the plugin *draws*.

**A caption with no box, drawn on top of its own value.** `DTextPicture` renders
in two commands - a `357 dText` prepares the string, the next `231 Show Picture`
with an empty name draws it at that command's x/y. A caption's budget is
therefore the distance to whatever sits to its right, which lives in a
*different command* and which no per-unit width check can see. The author
budgeted this screen to the pixel at fontSize 32:

```
label 性感帯：  4 glyphs = 128 px at x=172,  value at x=300  ->  128 of 128
```

Zero slack. "Erogenous Zone:" is 240 px and landed 112 px on top of the value;
"Difficulty:" landed 48 px on top of it. The bound is a picture's own x, so the
fix is to **raise the bound** - value column 300 -> 430 - not to abbreviate
three labels into meaninglessness. That is the patch's only non-string edit: it
is declared in `config.PICTURE_LAYOUT` with its measurement, guarded on the
value it expects to find so a re-run is a no-op and a game update is a loud
failure, and both `verify_structure` and the no-op test accept it **by exact
path and print it** rather than tolerating non-string changes as a class.
`audit/dtext_layout.py` prints every caption with its real budget;
`audit/mock_creation.py` composites the screen before and after.

**The lesson both share:** every check in this pipeline is per-unit, and neither
of these bugs *had* a unit. One was never extracted; the other was a
relationship between two commands. The only things that catch that class are the
output scan and looking at the screen.

**Three casino minigames shipped 100% Japanese.** `Tatsu_HighAndLowVerMZ`,
`Tatsu_PokerGames` and `Tatsu_BlackJack` draw their whole UI - bet prompts,
Higher/Same/Lower, hand names, the medal counters - from string literals inside
their own source. `plugins_js.py` covers plugin PARAMETERS and cannot see them,
so a player walked into the casino and found the one room the pipeline had
never looked at. That is now the fourth track: `tools/js_strings.py` (a JS
tokenizer, because the `/*: @help` block at the top of every MZ plugin is a
huge Japanese COMMENT) and `tools/plugins_src.py` (an exact-match key guard,
then patch-and-read-the-value-back).

719 literals in 39 enabled plugins -> 393 candidates after the key signals ->
100 approved after adversarial review -> 102 sites patched. **Most Japanese in
plugin source is not display text**, and translating a key breaks the game with
no error.

**The wrapper joined two lines that were already correct.**
`"Those idle little moments had become something irreplaceable to him."` is
exactly 68 characters and `cfg.width` was exactly 68, so a translation that had
arrived properly broken was re-flowed onto one line that ran off the box. The
geometry says 70 cells and re-deriving it only confirmed that; the fix was to
stop treating the derived MAXIMUM as the budget and measure the author instead
(their p99 is 600 px, 64 cells). 64 costs 0 units over `max_rows`; 62 would
cost 2. See the comment on `Config.width`.

## Things that cost nothing and were worth doing

* **129 stock UI strings seeded from RPG Maker MZ's own published English, zero
  API calls.** A model asked to translate `最強装備` in isolation returns "The
  Strongest Equipment Set", which is correct and wrong.
* **The silent-beat rule.** 82 boxes whose body is `「……」` hold no Japanese, so
  a `has_jp` gate skips them - and then inject never sees the unit and its
  Japanese nameplate ships. Extract when the body has Japanese **OR** there is a
  speaker, pre-fill the body with itself, and lock it.
* **`MessageAutoReplace` rebuilt, not re-translated.** The plugin runs
  `new RegExp(item.targetText, 'g')` over live message text to wrap the two
  heroines' names in a colour scope. Leave `targetText` Japanese and it stops
  matching the moment the dialogue is English. `targetText` is translated and
  `text` is DERIVED from it, keeping the exact `\c[18]…\c[0]` wrapper.
* **The four house names are written backwards in the source.** The author
  writes `ドラゴンクラス` and the same plugin flips it to `クラスドラゴン`
  before drawing, so the English is "Class Dragon" and never "Dragon Class".

## Cost, against the estimate

```
estimate (before the names pass filled the roster) : $1.90 - $2.63
actual                                            : $3.15  (text batch)
```

The gap is the cached prefix: the estimate was computed when the roster held 17
names, and the finished roster of 189 with roles and registers took the prefix
from ~4.5k to ~8.1k tokens. Input was otherwise predictable.

**Cache hit rate 42.2%** over 204 requests - above the 22% break-even for the
5m TTL and nowhere near the 53% a 1h TTL would have needed, which is exactly
why the batch driver uses 5m. `client.Usage.cost` bills writes at the TTL
actually used; charging a 5m run at the 1h rate overstates the largest column
by 60%.

## Delivery

MZ keeps `data/`, `js/` and `img/` at the **game root** - there is no `www/`
level, and an export written under one lands a level too deep.

* `data/*.json` - loose-file override, no repack.
* `js/plugins.js` - edited IN PLACE, on its own track with its own ledger.
  Mixing the two models means an export silently reverts an in-place edit.
* `js/plugins/*.js` - also IN PLACE, ledger `tl/plugins_src.json`. The release
  copies **every plugin named in that ledger**; a hardcoded list of filenames in
  the build script is the second way patched plugin code fails to ship.
* Re-injecting reads its base from the live `data/`, which after the first
  `--in-place` run is already English. Always inject from the pre-patch backup
  and diff before copying - span-spliced writes refuse (loudly), but computed
  passes have no span to check and land on top of their own previous output.
* `img/**` - the game ships **encrypted** (`.png_`) with the key in
  `System.json`, and `img.zip` holds the same 1,802 PNGs in the clear.
  `images/rpgmv_crypt.py` does both directions and `verify()` proves the codec
  against the developer's own plaintext before anything is written.
* Saves need no translator: all 58 Japanese strings in a save are asset
  filenames or internal editor labels. Nothing player-facing.

## Later MZ adaptation findings (2026-09-07)

Read [MZ-ADAPTATION.md](MZ-ADAPTATION.md) when adapting this reference to a new
MZ game. It records Tropical Chase tooling-only preparation, corrects numbered
portrait masking/measurement, and documents the parse-only Acorn helper and
its synthetic regression tests. It adds no game corpus or API configuration.
Gakuen's historical results above remain specific to Gakuen; preparation checks
on another game do not establish gameplay or save compatibility.

## Reusable vs per-game

**Reuse primitives after checking their contracts:** `codes.py`, `wrap.py`, `parse.py`,
`store.py`, `fileio.py`, `requests.py`, `driver.py`, `client.py`,
`tools/verify_structure.py`, `images/rpgmv_crypt.py`, `audit/numablate.py`.

**Redo per game:** the census, `config.py` in full, the speaker mechanism
(native MZ nameplates may replace first-401 speaker heuristics), all code
inventories and plugin consumers, `plugins_js.py`'s tables, loaded external JSON,
wrap widths and variable-driven heights, and which images carry text. The new
Acorn helper is an optional parser, not a replacement for display/key review.
