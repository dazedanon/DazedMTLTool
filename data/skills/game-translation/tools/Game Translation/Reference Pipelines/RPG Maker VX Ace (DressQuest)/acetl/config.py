#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
config.py - every per-game ruling, with the count that produced it.

Nothing here is an engine default carried over from another project. The
numbers come from a census of THIS game's `Data\*.rvdata2`, read straight off
the Ruby Marshal tree (`python tl.py census`); `docs\CENSUS.md` records the
full tables.

EVENT CODES - 63 distinct codes, 133,893 commands
    401  Show Text line          20,467 (20,197 hold Japanese)      -> ON
    101  Show Text header        12,880 - parameters are
                                 [face_name, face_index, background,
                                 position]; face_name is an ASSET KEY and is
                                 never translated, but it identifies the
                                 speaker                            -> header only
    102  Show Choices               260 -> 532 labels, 36 unique     -> ON
    402  choice branch label        532 - mirrored from its 102 by index
    355  Script                      69 - every one is
                                 `SceneManager.call(Scene_ShortMove)`,
                                 zero display text                  -> OFF
    122  Control Variables          946 - operand type (parameters[3])
                                 is 0 or 3 on every one; NOT ONE is 4
                                 (script), so no string operand      -> OFF
    111  Conditional Branch       9,452 - zero hold Japanese, so no
                                 string comparison exists to break   -> OFF, never
    118  Label / 119 Jump          7 / 19 - matched by string equality
                                                                     -> HARD OFF
    108  Comment                        0 - this author wrote none
    231  Show Picture             8,716 - picture filenames          -> never
    405  Scrolling text / 105           0 - absent
    320/324/325 name changes           0 - absent
    103  Input Number / 104 Select Item 0 - absent

CONTROL CODES - counted over every 401/102/402 and every database field
    \NAME[..]  11,484   a custom name-plate code from the game's own
                        `メッセージウィンドウ` script. `convert_escape_characters`
                        gsubs `/\eNAME\[(.*?)\]/i` away and pushes the capture
                        into `$game_temp.mess_name`, which `Window_Name_Plate`
                        draws in its own auto-sized window. So it is a NAMETAG,
                        not inline text: it is split off before the model sees
                        the line and re-prepended byte-exact on inject, and the
                        221 distinct names are translated once each through the
                        glossary.
    \G             19   currency unit (renders `Ｇ`)
    \$             11   opens the gold window
    Absent: \C \V \N \P \I \{ \} \. \| \! \> \< \^ and every %n. Not one orphan
    backslash in 20,467 lines, so the `\Helen` swallow-the-next-word failure
    cannot arise here - but the masker still handles the full Ace set, because
    a translator or a later hand edit can introduce one.

TEXT BOX WIDTH - measured from the corpus, not from a font size
    `Window_Message#window_width` is `Graphics.width` and this game runs
    `Graphics.resize_screen(640, 480)` (script `VXA_640x480_1.00`), with the
    stock `standard_padding` of 12, so the drawable width is 616 px and
    `visible_line_number` is 4 rows. What that is in CHARACTERS depends on
    `Font.default_size`, which no script in this game sets - and the corpus
    answers it more reliably than the engine default would:

        unfaced 401 lines   n=14,148   99.99% <= 66 cells   max 70
        faced   401 lines   n= 6,319   99.86% <= 56 cells   max 58

    The 10-cell gap between the two is `new_line_x` = 112 px of face graphic,
    which pins the cell at ~18 px and makes the drawable width ~68 cells
    unfaced and ~56 faced. Both distributions cut off exactly there, with a
    handful of author overflows just past it. So the budget is the author's own
    proven line, which is what the skill's text-fitting reference calls for
    when a widget has no declared box: fit inside what the shipped Japanese
    already fits inside, and the English cannot clip where the Japanese did
    not.
"""

import os
from dataclasses import dataclass, field


def _default_game_root():
    return os.environ.get("DRESSQUEST_GAME_ROOT",
                          r"c:\Users\sw\Desktop\Games\Dress Quest")


@dataclass
class Config:
    # --- paths -------------------------------------------------------------
    game_root: str = field(default_factory=_default_game_root)

    # --- which event codes to extract --------------------------------------
    code_text: bool = True             # 401 Show Text
    code_choices: bool = True          # 102 Show Choices
    code_scroll: bool = True           # 405 (absent, costs nothing)
    code_355: bool = False             # scripts: Scene_ShortMove only
    code_122: bool = False             # no script operands in this game
    code_111: bool = False             # no string comparisons; NEVER enable
    code_108: bool = False             # absent
    code_320: bool = False             # absent

    # --- which database fields to extract ----------------------------------
    db_names: bool = True              # Items/Weapons/Armors/Skills/States/...
    actor_names: bool = True           # Actors -> glossary, not units
    system: bool = True                # System terms / types / title
    map_display_names: bool = True     # 212 maps draw a name banner
    map_info_names: bool = False       # MapInfos is the editor tree, never drawn
    common_event_names: bool = True    # NOT editor labels here: the
                                       # recollection gallery draws them
                                       # (回想.rb:181 reads
                                       # $data_common_events[id].name)
    troop_names: bool = False          # editor labels, not drawn by this game
    notes: bool = False                # `<成長防具 2>` etc. are script config
    system_switches: bool = False      # 541 switch names, editor-only
    system_variables: bool = False     # 101 variable names, editor-only

    # --- text wrapping (applied on inject) ---------------------------------
    # MEASURED, not inferred. The half-width cell is 10 px (Font.default_size
    # 20, confirmed against a clipped line in game), so:
    #     unfaced  616 px / 10 = 61 cells
    #     faced    504 px / 10 = 50 cells   (new_line_x = 112)
    # The wrap target sits ~3 cells under the veto so a proportional fallback
    # font on someone else's machine still has room.
    #
    # The author's own envelope (66 / 56) is deliberately NOT used: at 10 px
    # those are 660 px and 560 px in boxes of 616 px and 504 px, so the shipped
    # Japanese clips too. Source text is only a safe bound where the source
    # itself fits.
    fix_wrap: bool = True
    width: int = 58                    # unfaced message: wrap target
    hard_width: int = 61               # ...and the veto threshold
    face_width: int = 47               # faced message (new_line_x = 112 px)
    face_hard_width: int = 50
    max_rows: int = 4                  # Window_Message#visible_line_number
    # Window_Help is Graphics.width wide and 2 rows tall (`Window_Help#
    # initialize(line_number = 2)`), same 616 px of content.
    desc_width: int = 58
    desc_max_rows: int = 2
    # Window_ChoiceList sizes itself to the widest choice and is capped at the
    # screen. The author's widest is 22 cells; 34 keeps the window under half
    # the screen so it never covers the message it belongs to.
    choice_width: int = 34
    # Item / skill / armour names are drawn in a 2-column list: 616 px of
    # content over two columns is 304 px, minus the 24 px icon = 280 px,
    # which is 28 cells at 10 px.
    name_width: int = 26
    # A type label or command sits in a narrow window - `Window_MenuCommand`
    # is 160 px wide, 136 px of content, 13 cells. 16 is the compromise across
    # the wider status columns; every stock term is seeded and locked anyway,
    # so this only guards model output.
    term_width: int = 16
    # A recollection-gallery row. The list window is the full screen
    # width with an icon column, so this is generous.
    cename_width: int = 40
    # `Window_MapName` is 360 px wide, 336 px of content = 33 cells at 10 px.
    mapname_width: int = 32
    # The name plate auto-sizes (`self.width = contents.text_size(name).width
    # + 24`) at x=16, so the only real bound is the screen.
    speaker_width: int = 40

    # --- speaker attribution -----------------------------------------------
    # 11,484 of 12,880 message boxes open with `\NAME[...]`, so the speaker is
    # stated outright and nothing has to be guessed. A box without one is
    # narration and gets NO speaker rather than inheriting the previous box's -
    # which is how lines get attributed to the wrong character after a
    # conditional branch.
    #
    # The face graphic is a WEAKER second signal, used only for the scene note:
    # every face sheet in this game (デフォ鎧 / 魔術師 / 聖職者 / 巫女 /
    # チャイナ / メイド / 強化鎧 / 全裸＆触手) is the heroine in one of her
    # seven dresses, so a faced line with no name tag is hers.
    heroine_jp: str = "エリス"
    heroine_faces: tuple = ("デフォ鎧", "魔術師", "聖職者", "巫女", "チャイナ",
                            "メイド", "強化鎧", "全裸＆触手")

    # --- misc --------------------------------------------------------------
    game_jp: str = "Dress Quest Ver1.13"
    game_en: str = "Dress Quest Ver1.13"
    encoding: str = "utf-8"            # every RString in this game is :E => true

    # ------------------------------------------------------------------ paths
    @property
    def data_dir(self):
        return os.path.join(self.game_root, "Data")

    @property
    def scripts_file(self):
        return os.path.join(self.data_dir, "Scripts.rvdata2")

    @property
    def graphics_dir(self):
        return os.path.join(self.game_root, "Graphics")

    @property
    def save_dir(self):
        """VX Ace writes `Save01.rvsave` into the game root by default; this
        game keeps `DataManager.save_file_path` stock (checked in
        `DataManager.rb`)."""
        return self.game_root

    def font_path(self):
        """The message font, if it can be found, for exact measurement.

        This game ships no `Fonts\\` folder and no script sets
        `Font.default_name`, so RGSS3 uses its default (VL Gothic, from the
        RTP) and falls back to a system font when that is missing. Returns None
        when nothing is found - `measure` then reports `exact=False` instead of
        pretending."""
        for p in (os.path.join(self.game_root, "Fonts"),
                  r"C:\Windows\Fonts"):
            for name in ("VL-Gothic-Regular.ttf", "VL-PGothic-Regular.ttf",
                         "vlgothic.ttf", "msgothic.ttc", "meiryo.ttc"):
                q = os.path.join(p, name)
                if os.path.exists(q):
                    return q
        return None


# Database files scanned in phase 0, and the fields that hold player-visible
# text in each. `note` is deliberately absent everywhere: this game's notes are
# `<成長防具 2>` / `<アイテム消費:38>` config tags read by its own scripts, plus
# two of RPG Maker's own editor hints, and translating any of them breaks a
# lookup with no error.
DB_FIELDS = {
    "Items.rvdata2":   ["@name", "@description"],
    "Weapons.rvdata2": ["@name", "@description"],
    "Armors.rvdata2":  ["@name", "@description"],
    "Skills.rvdata2":  ["@name", "@description", "@message1", "@message2"],
    "States.rvdata2":  ["@name", "@message1", "@message2", "@message3",
                        "@message4"],
    "Enemies.rvdata2": ["@name"],
    "Classes.rvdata2": ["@name", "@description"],
}

# Files that hold event command lists.
EVENT_FILES = ("Map", "CommonEvents.rvdata2", "Troops.rvdata2")

# Never translated, because something reads the string back as a key. Empty for
# now and checked on every census run: this game's 111s hold no Japanese, its
# 122s take no script operand, and its 355s carry no text, so nothing in the
# event data is read back by value. The two entries are the RPG Maker editor's
# own hint notes, which are not drawn anywhere.
DO_NOT_TRANSLATE = {
    "スキル２番は［防御］コマンドを選択したときに使用されます。",
    "ステート１番はＨＰが０になったときに自動的に付加されます。",
}
