# Census - Dress Quest Ver1.13 (RPG Maker VX Ace)

Every ruling in `acetl/config.py` comes from a count taken here, off the Ruby
Marshal tree directly (`python tl.py census`).
Re-run it after any game update: which optional codes hold text is a property
of the individual game, not of the engine.

Counted over 218 files holding event command lists, 7,712 command lists,
**133,423 commands**.

## Engine and delivery

| | |
|---|---|
| Engine | RPG Maker VX Ace (RGSS3, `Game.ini` `Library=System\RGSS301.dll`) |
| Assets | `Game.rgss3a`, RGSSAD v3, 698 files - extracted with `Tools\Game Archives\RPG Maker RGSSAD\rgssad.py` |
| Data | `Data\*.rvdata2`, 231 files, Ruby `Marshal.dump` |
| Screen | `Graphics.resize_screen(640, 480)` in the `VXA_640x480_1.00` script |
| Delivery | extract the archive, patch the loose `Data\`, then MOVE `Game.rgss3a` away. RGSS3 reads the ARCHIVE first when it is present, so a loose file beside it is ignored - measured by running the game, not assumed |
| Saves | `SaveNN.rvdata2` in the game root, **two** Marshal documents per file |

**RV2JSON is not in the delivery path.** It converts `Data\` to JSON for
reading, but its round trip is not byte-exact: 28 of 231 files come back
different with zero edits made (`Enemies.rvdata2` 35,587 -> 32,337 bytes).
`acetl/rvmarshal.py` reads and writes the format directly and round-trips
**231/231 files byte for byte**, which is what lets `tl.py noop` prove an empty
store changes nothing.

## Event codes

| code | count | with JP | ruling |
|---|---|---|---|
| 401 Show Text line | 20,467 | 20,197 | **ON** - the corpus |
| 101 Show Text header | 12,880 | 4,214 | header only. Parameters are `[face_name, face_index, background, position]`; the face name is an asset key, never translated, but it narrows the box |
| 102 Show Choices | 260 | 260 | **ON** - 532 labels, 36 unique |
| 402 branch label | 532 | 532 | mirrored from its 102 by index, never its own unit |
| 231 Show Picture | 8,716 | 8,691 | **never** - picture filenames |
| 111 Conditional Branch | 9,452 | 0 | **OFF, never enable.** Not one holds Japanese, so no string comparison exists to break |
| 122 Control Variables | 946 | 0 | **OFF** - `parameters[3]` (the operand type) is 0 or 3 on every one; not one is 4 (script) |
| 355 Script | 69 | 0 | **OFF** - every one is `SceneManager.call(Scene_ShortMove)` |
| 118 Label / 119 Jump | 7 / 19 | 7 / 19 | **HARD OFF** - matched by string equality |
| 108 Comment | 0 | - | absent; this author wrote none |
| 405 / 105 scrolling text | 0 | - | absent |
| 320 / 324 / 325 name changes | 0 | - | absent |
| 103 Input Number / 104 Select Item | 0 | - | absent |

Everything else (121 switches, 201 transfer, 205 move route, 250 SE, 301 battle,
302 shop, 605 shop goods, 340, 311, ...) carries no string a player reads.

## Control codes

Counted over every 401, 102 and 402 parameter and every database field:

| code | uses | what it is |
|---|---|---|
| `\NAME[..]` | 11,484 | the game's own name-plate code, from the `メッセージウィンドウ` script |
| `\G` | 19 | currency unit |
| `\$` | 11 | opens the gold window |

Absent: `\C \V \N \P \I \{ \} \. \| \! \> \< \^` and every `%n`. **Not one
orphan backslash in 20,467 lines**, so the `\Helen`-swallows-the-next-word
failure cannot arise from the source - but it can be introduced by a
translation, so `validate` checks for it anyway.

`\NAME[...]` is a NAMETAG, not inline text. The game's script does:

```ruby
result.gsub!(/\eNAME\[(.*?)\]/i){$game_temp.set_mess_name($1)}
```

in `convert_escape_characters`, so it is consumed before a glyph is drawn and
`Window_Name_Plate` draws the capture in its own auto-sized window
(`self.width = contents.text_size(name).width + 24`, at x=16, font size 20).
Consequences the pipeline is built on:

* it costs **zero width** in the message box;
* it must be split off before the model sees the line, or it gets paraphrased
  into the dialogue;
* the 221 distinct names are glossary entries, translated once each, and the
  tag is rebuilt with the English name on inject. An untranslated one ships a
  Japanese name plate over English dialogue - visible on screen and invisible
  to every per-unit check, so `validate` reports them separately.

## Speakers

11,484 of 12,880 message boxes (89.2%) open with `\NAME[...]`. 221 distinct
values; the top of the list:

```
4231 エリス     1354 町人      547 モンスター   302 バロン王   288 クリフ将軍
 281 村の男      250 ならず者警備  184 バロン兵    179 ならず者    161 賭博受付
```

A box with no tag gets **no speaker** rather than inheriting the previous
box's, which is how lines get attributed to the wrong character after a
conditional branch.

The face graphic is a weaker signal and is used only for the width budget:
4,214 headers carry one, 31 distinct sheets, and the eight costume sheets
(`デフォ鎧` `魔術師` `聖職者` `巫女` `チャイナ` `メイド` `強化鎧` `全裸＆触手`)
are all the heroine in one of her seven dresses.

## The message box

`Window_Message#window_width` is `Graphics.width`, and the stock
`standard_padding` of 12 gives **616 px** of content over
`visible_line_number` = **4 rows** of `line_height` 24. With a face graphic
`new_line_x` is 112, leaving **504 px**.

No script sets `Font.default_size` and no `Fonts\` folder ships with the game,
so the cell had to be measured rather than read. **It is 10 px** - i.e.
`Font.default_size` is 20:

> A faced line injected as 54 characters rendered 51 in game before the right
> edge cut it off. 640 - 12 - 112 = 516 px carried those 51 half-width
> characters, and MS Gothic at 20 px reproduces the clip at exactly 51 of 54.

    unfaced  616 px / 10 = 61 cells      budget: wrap 58, veto 61
    faced    504 px / 10 = 50 cells      budget: wrap 47, veto 50

**The author's own lines do not fit this box**, which is why the first build
was wrong to use them as the bound:

| | n | author max | at 10 px | the box |
|---|---|---|---|---|
| unfaced 401 lines | 14,148 | 66 cells | 660 px | 616 px |
| faced 401 lines | 6,319 | 56 cells | 560 px | 504 px |

Shipped source is only a safe envelope where the shipped source itself fits -
check before trusting it. Here the check fails, and 255 of the author's lines
lose a character or two off the right edge in the original game.

**Height is not the same kind of limit.** `Window_Message#process_new_line`
calls `input_pause` then `new_page`, so a message taller than four rows is
paginated - a click, then the rest, with the face redrawn. Nothing is lost and
no commands are added, so `validate` reports it as a soft `pagination` note
instead of forcing a paid shortening pass. Width stays a hard failure, because
`process_normal_character` never tests the right edge and the contents bitmap
simply stops.

Other widgets: `Window_Help` is `Graphics.width` wide and 2 rows tall
(`initialize(line_number = 2)`), so descriptions get 64 cells x 2.
`Window_ChoiceList` sizes itself to its widest choice; the author's widest is
22 cells and the budget is 34.

## Database

| file | field | units | notes |
|---|---|---|---|
| Items / Weapons / Armors | `@name`, `@description` | 120 / 79 / 87 | descriptions are 2-line help text |
| Skills | `@name`, `@description`, `@message1`, `@message2` | 553 | message1/2 are battle-log fragments appended to a name |
| States | `@name`, `@message1..4` | 129 | same |
| Enemies / Classes | `@name` (+ Classes `@description`) | 100 / 9 | |
| Actors | `@name`, `@nickname` -> **glossary** | 2 | only actor 1 is used: エリス / 白蓮の騎士 |
| System | terms, elements, skill/weapon/armor types, currency | 70 | 55 of them seeded with RPG Maker's own English |
| Map*.rvdata2 | `@display_name` | 212 | the map-name banner |

**Common event NAMES are player-visible in this game** (47 of the 56 reach the
Recollection gallery, which draws `$data_common_events[id].name` in its help
window - `回想.rb:181`). Identity there is `event.id`, never the name, so
translating them is safe. On most RPG Maker games this field is an editor
label, and ruling it out by habit would have shipped a Japanese scene list.

**Never translated:** `@note` on every file - this game's notes are
`<成長防具 2>` and `<アイテム消費:38>` config tags read by its own scripts, plus
two of RPG Maker's own editor hints. `MapInfos` names (216) are the editor's
project tree and are never drawn. Switch names (541) and variable names (101)
are editor-only. Troop names and common-event names are editor labels; the
common-event name is used as scene context in the prompt and never written back.

## Three more things the JSON view would have hidden

**RV2JSON drops `terms.etypes`.** `System.rvdata2` really does carry
`@etypes = ['武器', '腕', '頭', '身体', '装飾品']` - the five equip-slot labels
that `Vocab.etype` reads and two windows draw - and `ace_json/System.json` has
no `etypes` key at all. Extracting from the JSON would have missed them
silently, and writing that JSON back with `RV2JSON -u` would have deleted them
from the game. The Marshal layer sees them, and they are translated.

**79 message boxes hold no Japanese in the body at all** - `「………」`, a beat of
silence - while the only Japanese on screen is the speaker inside the
`\NAME[...]` tag. Extraction keys on "contains Japanese", so those were never
units, and they would have shipped a Japanese name plate over an English scene.
They are now extracted, pre-filled with their own body, locked, and carry a
waiver so the `identical` check reports them rather than flagging them.

**Battle-log fragments are name-prefixed by the ENGINE, per field, not per
string.** `Window_BattleLog` draws `subject.name + item.message1` for Skill
message1 and `target.name + state.message1..4` for States, but Skill message2
stands alone (`add_text(item.message2)`). Japanese needs no separator there and
English does. The prefixed fields are listed in `extract.PREFIXED_MESSAGES`,
their translations keep a leading space all the way through injection, and the
363 units concerned are the reason `Erisattacks!` does not ship.

## Two pre-existing bugs in the original game

Neither is caused by the patch and neither is fixed by it. They are recorded so
a playtester does not chase them:

* three code-119 jumps to `魔術師選択冒頭` in `Map132` event 7 page 0 have no
  matching 118 label and fall through silently;
* `Troops.rvdata2` troop 1 page 4 references the face `ルシーダ陵辱顔３`, which
  is not on disk.

## The RGSS3 scripts - the second track

143 script sections in `Data\Scripts.rvdata2`, holding **384 Japanese
literals** across 12 sections. `Vocab` alone holds 51 of them - the whole
battle log and the shop, save and load prompts - and every one has published
Enterbrain English, so `tools/seed_stock_ui.py` fills them with no API call.

The ledger (`tl/scripts_rb.json`) classifies each literal `display` (72),
`key` (72) or `unknown` (240) and marks every entry `translate: false` until a
human says otherwise. That is the whole safety model: a `when` operand, a hash
key or a save-data key looks exactly like a label and breaks silently.

## Total scope

**14,615 units**: 12,531 dialogue, 540 names, 532 choices, 368 battle-log
messages, 362 descriptions, 212 map names, 70 System labels; plus 221 speaker
names and 384 script literals on their own tracks.

## Images - nothing to translate

Decided and closed: **no image in this game needs redrawing.**

The title-screen buttons (`Graphics\Titles1
ewgame`, `continue`,
`recollection`, `shutdown` and their `_active` variants) already ship in
English - "Newgame", "CGmode" - so touching them would be changing art the
author wrote in English. `Titles1\Title.png` carries the subtitle
エリスと七つのドレス under the logo and `Pictures\セーブ背景.png` is a
photograph of a printed book; both are left as they are.

The 302 files in `Graphics\Pictures` are event CGs, costume portraits and
battle poses. Their FILENAMES are Japanese (`eris_巫女（笑み）`,
`戦闘チャイナ①`, `ハンタービー_01`) and are asset keys referenced by code 231
and by the game's own scripts: renaming one breaks the picture with no error.
They are never touched.
