#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py - extraction / injection / wrapping configuration.

Every default here was derived from a census of THIS game (see
`docs/CENSUS.md`), not copied from another project. The event-code rulings in
particular are per-game facts:

    401  4,193   dialogue                                    -> ON
    102     53   choices (22 unique labels)                  -> ON
    405      0   scrolling text                              -> absent
    356    912   MV plugin commands, only 4 distinct strings
                 carry text, all `LL_InfoPopupWIndowMV
                 showWindow`                                 -> ON (whitelist)
    355    129 / 655 173  every JP inside them is a `//` dev
                 comment; zero display text                  -> OFF
    122  1,243   only ONE has parameters[3] == 4, and its
                 value is `AudioManager.currentBgmVolume`    -> OFF
    111    943   no `$gameVariables` string comparison at
                 all (types are 0/1/3/8/12)                  -> OFF, never
    108    162 / 408 12   all developer notes (`▼ここに…`),
                 no plugin markers                           -> OFF
    118    459 / 119 244  labels + jumps                     -> HARD OFF
    320/324/325/357/657    absent                            -> n/a
"""

import os
from dataclasses import dataclass, field


def _default_game_root():
    env = os.environ.get("MINERIA_GAME_ROOT")
    if env:
        return env
    return (r"c:\Users\sw\Desktop\Games"
            "\\" + "魔王ミネリアと名もなき村のエロトラップダンジョン1.0")


@dataclass
class Config:
    # --- paths -------------------------------------------------------------
    game_root: str = field(default_factory=_default_game_root)
    engine: str = "mv"                 # www/ layout, no code-101 parameters[4]

    # --- which event codes to extract --------------------------------------
    code_text: bool = True             # 401 Show Text
    code_scroll: bool = True           # 405 Show Scrolling Text (absent here)
    code_choices: bool = True          # 102 Show Choices
    code_356: bool = True              # MV plugin commands, whitelist below
    code_355: bool = False             # scripts: dev comments only in this game
    code_122: bool = False             # no string operands in this game
    code_111: bool = False             # no string comparisons; NEVER enable
    code_108: bool = False             # dev notes only
    code_357: bool = False             # MZ-only, absent
    code_657: bool = False             # absent

    # --- which data-file fields to extract ---------------------------------
    db_names: bool = True              # Items/Armors/Weapons name+description
    actor_names: bool = True           # Actors -> glossary, not units
    classes: bool = True
    system: bool = True                # System.json terms / types / title
    map_display_names: bool = True     # Map*.json displayName (19 of them)
    map_info_names: bool = False       # MapInfos.name is editor-only here:
                                       # MapNameExtend 実名表示 = false
    notes: bool = False                # <MaxItems: 3> etc. are config, not text
    system_switches: bool = False      # resolved by NAME by plugins/events
    system_variables: bool = False

    # --- code-356 whitelist ------------------------------------------------
    # `LL_InfoPopupWIndowMV showWindow <text> <dur> <x> <y> <bg>`.
    # MV splits plugin-command parameters on ASCII space (command356 ->
    # this._params[0].split(" ")), so args[1] must stay ONE token. The M+ 1m
    # font ships U+00A0 at half width, and the split never sees it, so English
    # that needs a space uses NBSP -- see inject.enforce_single_token().
    plugin356_text: dict = field(default_factory=lambda: {
        "LL_InfoPopupWIndowMV": {"showWindow": [1]},
    })

    # --- text wrapping (applied on inject) ---------------------------------
    # Measured, not guessed:
    #   Community_Basic screenWidth = 1020  -> Graphics.boxWidth = 1020
    #   Window_Base.standardPadding()  = 18 -> contentsWidth = 1020 - 36 = 984
    #   Window_Base.standardFontSize() = 28 (MV stock, no plugin override)
    #   fonts/mplus-1m-regular.ttf: unitsPerEm 1000, two advance spikes only
    #     (1000 = 6,270 glyphs, 500 = 1,488) -> genuinely monospace,
    #     half-width cell = 28 * 500/1000 = 14.00 px
    #   984 / 14 = 70.28 -> 70 cells hard cap.
    #   Window_Message.numVisibleRows() = 4 (MV stock) -> 4 rows hard cap.
    #   101 parameters[0] (face graphic) is '' on all 2,596 headers, so
    #   newLineX() is 0 and there is no separate face width.
    fix_wrap: bool = True
    width: int = 68                    # message box (cap 70, 2 cells of margin)
    max_rows: int = 4                  # Window_Message.numVisibleRows()
    hard_width: int = 70               # veto threshold - never exceed
    list_width: int = 68               # Window_Help is boxWidth too...
    list_max_rows: int = 2             # ...but only 2 lines tall
    choice_width: int = 60             # Window_ChoiceList sizes to content;
                                       # 60 cells keeps it on screen at 1020px
    ptext_width: int = 68

    # --- speaker attribution -----------------------------------------------
    # This game stores NO speaker anywhere: code 101 arity is 4 on all 2,596
    # headers (so no MZ parameters[4]) and parameters[0] (face) is empty on all
    # of them. What it does have is LL_StandingPictureMV portrait codes, and
    # every one of the 132 portraits is the SAME character:
    #   \F[C_*] 1,247 uses, \FF[C_*] 15   (C/B/M/N are costume prefixes -
    #   normal / bunny / micro / naked, matching the 通常/バニー/マイクロ/裸族
    #   costume menu).
    # So: a 401 block whose first line opens with \F[..] is the protagonist
    # speaking; anything else is an NPC or narration and gets NO speaker rather
    # than a guessed one.
    portrait_speaker: str = "ミネリア"
    portrait_code_re: str = r"^\s*(?:\\+F{1,4}\[[^\]]*\]|\\+AA\[[^\]]*\]|\\+M{1,4}\[[^\]]*\]|\\+FH\[[^\]]*\])+"

    # One evidence-based exception to "refuse to guess". A CommonEvent named
    # `E<monster>接触` is a trap-encounter CG scene: the portrait code is
    # absent because the CG replaces the portrait, but the protagonist is the
    # only speaker. Verified across all 22 of them - zero lines carry a male
    # marker (俺 / てめえ / だぜ / グオオ / やがる / ぞー), and every one reads
    # as her first person. This is a per-SCENE rule proved over the corpus, not
    # a per-line inheritance, so it does not reintroduce the stateful
    # last-101-seen failure. BADEND events are deliberately excluded: CE87 has
    # three hero-party lines in it.
    solo_speaker_scene_re: str = r"E.+接触"

    # --- misc --------------------------------------------------------------
    game_jp: str = "魔王ミネリアと名もなき村のエロトラップダンジョン"
    game_en: str = "Demon Lord Mineria and the Nameless Village's Ero Trap Dungeon"

    # ------------------------------------------------------------------ paths
    @property
    def www(self):
        return os.path.join(self.game_root, "www")

    @property
    def data_dir(self):
        return os.path.join(self.www, "data")

    @property
    def js_dir(self):
        return os.path.join(self.www, "js")

    @property
    def plugins_js(self):
        return os.path.join(self.js_dir, "plugins.js")

    @property
    def font_path(self):
        return os.path.join(self.www, "fonts", "mplus-1m-regular.ttf")

    @property
    def img_dir(self):
        return os.path.join(self.www, "img")


# Database files scanned in Phase 0. Order matters only for readability.
DB_FILES = [
    "Actors.json", "Classes.json", "Items.json", "Armors.json", "Weapons.json",
    "Skills.json", "States.json", "Enemies.json", "Troops.json",
]

# Files that hold event command lists.
EVENT_FILES_GLOB = ("Map[0-9][0-9][0-9].json", "CommonEvents.json", "Troops.json")

# Never translated. Each entry is here because something reads it back.
DO_NOT_TRANSLATE = {
    # MessageWindowHidden.js:334 does `case '右クリック':` against the
    # triggerButton parameter value. Translating it disables the hide-window
    # right-click with no error.
    "右クリック",
    # MapInfos names are the editor tree; MapNameExtend 実名表示 = false, so
    # they are never drawn.
}
