#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
config.py - extraction / injection / wrapping configuration.

Every default here came out of a census of THIS game (`audit/CENSUS*.txt`),
not from another project. The event-code rulings are per-game facts:

    401  28,236  dialogue (24,024 of them in CommonEvents.json)   -> ON
    101   8,368  headers. parameters[4] speaker on only 41 of
                 them and a face graphic on only 37, so the MZ
                 speaker field is effectively unused             -> see below
    102     178  choices                                          -> ON
    405       0  scrolling text                                   -> absent
    122     220  operand types {0:140, 1:17, 2:20, 4:43}. The 43
                 string operands are DISPLAY values - month names
                 into var 1 and "who did this to you" labels into
                 vars 35/61/64/67, all read back only through
                 \V[n]                                            -> ON (whitelist)
    111     586  condition types {0,1,2,4,7,8,10,12}. ZERO script
                 conditions mention $gameVariables, so there is
                 no string comparison to reconcile                -> OFF, never
    355/655 179/668  every block is a CBR_EroStatus command list.
                 Only the `テキスト-` rows are drawn; `画像-` is a
                 filename and `左右-`/`上下-` are keys the plugin
                 compares against 左/中/右 and 上/中/下           -> ON (テキスト- only)
    357     199  MZ plugin commands. Two carry text: DTextPicture
                 `text` (16) and TorigoyaMZ_NotifyMessage
                 `message` (14). parameters[2] is the editor's own
                 command label and the engine never reads it      -> ON (whitelist)
    657     461  every one is an editor argument echo restating a
                 357 it follows (`位置参照対象 = `, `フィルター識別名 =
                 filter#3`). No `メッセージ` key anywhere          -> OFF
    108/408  91/111  developer notes, `<balloon:4 >` and `<Label>`
                 plugin config - EXCEPT `選択肢ヘルプ`, which
                 MPP_ChoiceEX draws as the choice help window
                 (its `Choice Help Commands` parameter lists the
                 marker literally)                                -> ON (選択肢ヘルプ only)
    118/119 102/106  3 labels, matched by string equality         -> HARD OFF
    320/324/325  0  absent                                        -> n/a
    356       0  MV-style plugin commands absent (this is MZ)     -> n/a
"""

import os
from dataclasses import dataclass, field


def _default_game_root():
    env = os.environ.get("GAKUEN_GAME_ROOT")
    if env:
        return env
    # <game root>/_tl/mztl/config.py -> up three
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Config:
    # --- paths -------------------------------------------------------------
    game_root: str = field(default_factory=_default_game_root)
    engine: str = "mz"                 # files at the game root, no www/

    # --- which event codes to extract --------------------------------------
    code_text: bool = True             # 401 Show Text
    code_scroll: bool = True           # 405 (absent, costs nothing)
    code_choices: bool = True          # 102 Show Choices
    code_122: bool = True              # Control Variables, whitelisted below
    code_355: bool = True              # CBR_EroStatus `テキスト-` rows only
    code_357: bool = True              # whitelisted plugin arguments
    code_408: bool = True              # `選択肢ヘルプ` comment blocks only
    code_111: bool = False             # no string comparisons; NEVER enable
    code_108_free: bool = False        # non-whitelisted comments stay put
    code_657: bool = False             # editor echo of a 357
    code_356: bool = False             # MV-only, absent

    # --- which data-file fields to extract ---------------------------------
    db_names: bool = True
    actor_names: bool = True           # -> glossary, not units
    classes: bool = True
    system: bool = True
    map_display_names: bool = True

    # CORRECTION. This was False, carried over from another game's config with
    # the comment "editor tree only" - and never re-measured here, which is the
    # exact mistake the census exists to prevent. `MapNameExtend` is ENABLED and
    # configured `showReal: true`, and its override reads
    #     Game_Map.displayName = original() || getRealMapName()
    #     getRealMapName()     = $dataMapInfos[mapId].name
    # so the MapInfos name IS the map-name banner on every map whose editor
    # display name is blank - 42 maps here, all 42 with a Japanese name. `校舎`
    # was showing over the school.
    #
    # Safe to translate: the only code in the folder that resolves a map BY
    # NAME (`FastTravel.js`, `Potadra_nameSearch($dataMapInfos, ..., 'name')`)
    # is NOT REGISTERED in plugins.js, so it never loads. Nothing else reads
    # the field except to draw it.
    map_info_names: bool = True

    # `notes` stays False as a blanket - a note field is plugin CONFIG - but
    # one tag in it is drawn on screen. `EventLabel` (enabled, showDefault
    # false) renders `event().meta['LB']` as a floating label over the event:
    # 95 events carry one, 62 distinct strings, and they are the room and
    # activity captions on every map.
    notes: bool = False
    note_label_tags: tuple = ("LB",)

    system_switches: bool = False      # resolved BY NAME as string keys
    # Variable NAMES are keys in general, but `LL_VariableWindow` draws the
    # name of the variable it shows as that window's label. Only variable 1 is
    # ever passed to it (6 `showWindow` commands, all `variableId: 1`), and its
    # name is `現在の暦：` - the "Current month:" HUD in the top-left corner.
    # Whitelisted by ID, like the 122 values, rather than by string.
    system_variables: bool = True
    system_variable_allow: frozenset = frozenset({1})

    # --- code-122: whitelist by VARIABLE ID, never by string ----------------
    # Every value assigned to one of these is drawn through \V[n] and nothing
    # compares it. Verified: 111 has zero $gameVariables script conditions, and
    # its type-1 (variable) branches compare against a NUMBER, never a string.
    #   1  the current month, shown on the calendar / status HUD
    #   35 "who took your virginity" - the ero-status screen's \V[16]/\V[10] feed
    #   61/64/67  a baby's sex (男の子 / 女の子)
    var122_allow: frozenset = frozenset({1, 35, 61, 64, 67})

    # --- code-357: whitelist by plugin, matched on the TRAILING name --------
    # MZ ships the same plugin under different install paths, so a full-string
    # match silently skips half of them.
    plugin357_text: dict = field(default_factory=lambda: {
        "DTextPicture": ["text"],
        "TorigoyaMZ_NotifyMessage": ["message"],
    })

    # --- code-355/655: CBR_EroStatus ---------------------------------------
    # `A.split(/\-(.*)/, 2)` then `switch (temp[0])`. Only `テキスト` is drawn.
    cbr_text_prefix: str = "テキスト-"

    # --- code-108/408 markers ----------------------------------------------
    # MPP_ChoiceEX `Choice Help Commands` = ["ChoiceHelp", "<ChoiceHelp>",
    # "選択肢ヘルプ", "<選択肢ヘルプ>"]. The marker itself is a key.
    comment_markers: tuple = ("選択肢ヘルプ", "<選択肢ヘルプ>",
                              "ChoiceHelp", "<ChoiceHelp>")

    # --- text wrapping (applied on inject) ---------------------------------
    # Measured, not guessed:
    #   System.json advanced.screenWidth = 816 -> Graphics.boxWidth = 816
    #   Scene_Message.messageWindowRect: ww = boxWidth, wh = calcWindowHeight(4)
    #     -> FOUR rows, hard.
    #   LL_MessageWindowAdjust (enabled) overrides updatePlacement with
    #     this.width = Graphics.boxWidth - adjustValue * 2, and its configured
    #     adjustNoFace is 40 -> 816 - 80 = 736 px.
    #   Game_System.windowPadding() = 12 -> innerWidth = 736 - 24 = 712.
    #   Window_Message.newLineX = 4 with no face -> usable 708 px.
    #   fonts/x12y12pxMaruMinyaM.ttf: unitsPerEm 1200, exactly two advance
    #     spikes (1200 x 7,242 glyphs and 600 x 277) -> genuinely monospace.
    #     advanced.fontSize = 20 -> half-width cell = 600/1200*20 = 10.00 px.
    #   708 / 10 = 70.8 -> 70 cells hard cap.
    #   With a face (37 of 8,368 headers) adjustOnFace is 0, so the window is
    #     the full 816: innerWidth 792, newLineX = faceWidth 144 + 20 = 164,
    #     usable 628 px -> 62 cells.
    #   The author's own widest 401 line is 80 cells and 255 lines exceed 70,
    #     so the shipped Japanese already clips - the budget is the geometry,
    #     not the corpus.
    #
    # THE DERIVED MAXIMUM IS NOT THE BUDGET. The geometry above says 70 cells
    # and a player still reported a 68-cell line running off the box:
    #   "Those idle little moments had become something irreplaceable to him."
    # is exactly 68 characters, so the wrapper saw a perfect fit and JOINED the
    # two lines the translation already had. Re-deriving the geometry only
    # confirmed it (LL_MessageWindowAdjust really is `boxWidth - 40*2`, padding
    # 12, newLineX 4, no \FS or \{ escape anywhere in that scene, no plugin
    # overrides mainFontSize), so a few pixels of the real window are not
    # accounted for here and probably never will be from a screenshot.
    #
    # Anchor the budget to what the AUTHOR demonstrably treats as the limit
    # instead, measured with the real font at the real size over all 18,137 of
    # their unfaced 401 lines:
    #     p95 520 px   p99 600 px   >640 px 0.24%   >660 px 0.15%
    # So ~64 cells is the author's own working ceiling, and everything above it
    # is a handful of lines they shipped clipped. Filling 68 made the English
    # systematically wider than the Japanese it replaced (English p99 was
    # 670 px against the author's 600).
    #
    # 64 costs NOTHING: re-wrapping all 8,328 translated units at 64 leaves 0
    # of them over `max_rows`. 62 would push 2 units to 5 rows in a 4-row
    # window, and the only fixes for those are shortening the text or adding a
    # message page - one degrades the translation, the other changes command
    # counts and breaks save compatibility. So 64 is the floor, not a taste.
    #
    # SECOND FONT: the recollection room (Map038) issues
    # `Keke_AnyTimeFontChange fontChange` between "ドット" (x12y12px, monospace)
    # and "普通" (f910-shin-comic, PROPORTIONAL), so recollection scenes render
    # in a font whose Latin advances run 0.225-0.942 em rather than a flat 0.5.
    # Measured across all 11,240 English lines, f910 is up to 1.254x wider on
    # short runs of repeated letters but NARROWER on long lines (86 lines over
    # 660 px against the pixel font's 236), so the pixel font remains the
    # binding constraint and the measurer is right to use it.
    fix_wrap: bool = True
    width: int = 64                    # the author's own ceiling, not the max
    max_rows: int = 4                  # Scene_Message.calcWindowHeight(4, false)
    hard_width: int = 66               # veto threshold - never exceed
    face_width: int = 60               # the 37 faced blocks
    hard_face_width: int = 62          # 628 px / 10
    # Window_Help is boxWidth wide (816 - 24 = 792 -> 79 cells) and
    # Scene_MenuBase.helpWindowRect is calcWindowHeight(2, false) -> 2 rows.
    list_width: int = 76
    hard_list_width: int = 79
    list_max_rows: int = 2
    # Window_ChoiceList sizes to its widest choice and LL_MessageWindowAdjust
    # syncs it to the message window, so 60 keeps it on screen at 736 px.
    choice_width: int = 56
    ptext_width: int = 60              # CBR ero-status rows and DText pictures

    def hard_cap(self, kind, faced=False):
        """The width a rendered line may NEVER exceed, per widget.

        One function, read by both the injector and the validator, because the
        two disagreeing is invisible: three item descriptions were reported as
        overflowing at 74 cells against the MESSAGE box's 70, while the help
        window they actually render in is 79 wide and they fit fine."""
        if kind == "text":
            return self.hard_face_width if faced else self.hard_width
        if kind == "title":
            # `System.json optDrawTitle` is FALSE on this game: the title
            # screen is an image and `Scene_Title.drawGameTitle` never runs.
            # The only thing that reads gameTitle is
            # `Scene_Boot.updateDocumentTitle`, which assigns it to
            # `document.title` - the WINDOW CAPTION, which has no pixel budget
            # and is elided by the OS if it is too long for the taskbar.
            # Capping it at the help-window width would be measuring against a
            # widget that does not exist.
            return 10 ** 6
        if kind in ("desc", "help", "note", "name", "term", "type"):
            return self.hard_list_width
        if kind == "choice":
            return self.choice_width
        if kind == "ptext":
            return self.ptext_width
        return self.hard_list_width

    # --- speaker attribution -----------------------------------------------
    # This game stores no speaker in any engine field. What it does is write
    # the name as the FIRST LINE of the 401 run, with the dialogue opening on
    # the next line inside 「」:
    #
    #     401  アズサ
    #     401  「わわわ……こんな恰好で外なんて歩けないよ」
    #
    # 4,872 of 8,368 blocks match; the 3,496 that do not are narration and get
    # an EMPTY speaker rather than an inherited one. 186 distinct names.
    # The gate is the skill's FIRSTLINESPEAKERS rule with one addition proved
    # necessary here: the candidate must not itself open with a quote, or three
    # 「…」 lines whose next line is also 「…」 get eaten as names.
    first_line_speaker: bool = True
    speaker_max_len: int = 24
    speaker_openers: str = "「『“\"'(（｢*[.…【"

    # --- misc --------------------------------------------------------------
    game_jp: str = "体だけは立派な落ちこぼれ陰キャ魔法使い学園トップになるまで帰れません"
    game_en: str = ("Body of a Champion, Heart of a Loser: "
                    "You Can't Leave the Magic Academy Until You're the Best")

    # ------------------------------------------------------------------ paths
    @property
    def data_dir(self):
        return os.path.join(self.game_root, "data")

    @property
    def js_dir(self):
        return os.path.join(self.game_root, "js")

    @property
    def plugins_js(self):
        return os.path.join(self.js_dir, "plugins.js")

    @property
    def font_path(self):
        return os.path.join(self.game_root, "fonts", "x12y12pxMaruMinyaM.ttf")

    @property
    def img_dir(self):
        return os.path.join(self.game_root, "img")


# Database files scanned in Phase 0.
DB_FILES = [
    "Actors.json", "Classes.json", "Items.json", "Armors.json", "Weapons.json",
    "Skills.json", "States.json", "Enemies.json", "Troops.json",
]

EVENT_FILES_GLOB = ("Map[0-9][0-9][0-9].json", "CommonEvents.json", "Troops.json")

# Strings something reads back as a KEY.
#
# CORRECTION, made after the opening screen shipped with an untranslated
# difficulty option. This started as one blanket set checked against every unit
# of every kind, and that is wrong twice over:
#
#   * it is REDUNDANT wherever the extractor is already structural. The
#     `選択肢ヘルプ` marker is the code-108 head and only rows[1:] are ever
#     extracted; the CBR keywords are consumed by the `テキスト-` prefix match;
#     `右クリック` lives only in a plugins.js parameter, which has its own NEVER
#     set; the 118/119 labels are never visited at all because those codes are
#     hard off.
#   * and it is WRONG wherever the same characters are also DISPLAY text.
#     `普通` is the font plugin's registered call name AND the middle option of
#     the difficulty picker AND a texture choice; `ドット` is that call name AND
#     a visible font choice. Blanket-skipping them left four player-facing
#     strings in Japanese on the character-creation screen - the very first
#     thing a player sees - while every automated check stayed green, because
#     a unit that was never extracted cannot fail anything.
#
# What makes translating those choices safe is not a denylist, it is the data:
# code 402 branches on the choice INDEX, the difficulty branch writes
# `122 [80,80,0,0,n]` by index, and the font branch passes its call name as a
# SEPARATE literal in a `357 fontName` argument that this pipeline's whitelist
# never extracts. The choice label and the key are different strings already -
# the source proves it, writing the choice as `ノーマル` while the argument says
# `普通`.
#
# So this set is now applied ONLY where the extractor can actually reach a key:
# code 122 variable values and code 357 arguments. Display codes - 401, 102,
# 108/408 help, CBR `テキスト-` rows - are display BY CONSTRUCTION and are never
# filtered against it.
KEY_STRINGS = {
    # MessageWindowHidden.js does `case '右クリック':` against its
    # triggerButton parameter.
    "右クリック",
    # MPP_ChoiceEX matches these literally to find a choice-help comment.
    "選択肢ヘルプ", "<選択肢ヘルプ>",
    # CBR_EroStatus switches on these and compares 左右/上下 against them.
    "テキスト", "画像", "ページ", "初期化", "サイズ", "左右", "上下", "透明度",
    "左", "中", "右", "上", "下",
    # Keke_AnyTimeFontChange resolves a registered font by this call name.
    # Only ever reached as a `357 fontName` argument, never as a choice.
    "普通", "ドット",
    # 118/119 flow labels.
    "エロシーン終了", "ジャンプ",
}

# Kept under the old name for the prompt's do-not-translate block, which tells
# the MODEL about them; it is no longer an extraction gate.
DO_NOT_TRANSLATE = KEY_STRINGS


# --------------------------------------------------------------------------
# Declared LAYOUT repairs
# --------------------------------------------------------------------------
# `DTextPicture` draws a caption in two commands: a `357 dText` prepares the
# string and the next `231 Show Picture` with an empty name renders it at that
# command's x/y. A caption's real budget is therefore the distance to whatever
# is drawn to its RIGHT - which lives in a different command, and which no
# per-unit width check can see.
#
# The character-creation screen is budgeted to the pixel at fontSize 32
# (half-width cell 16 px, full-width 32 px):
#
#     label 特性：    3 glyphs =  96 px at x=204, value at x=300  -> 96 of 96
#     label 性感帯：  4 glyphs = 128 px at x=172, value at x=300  -> 128 of 128
#     label 難易度：  4 glyphs = 128 px at x=172, value at x=300  -> 128 of 128
#
# Zero slack. "Erogenous Zone:" is 15 half-width cells = 240 px and lands 112 px
# on top of the value; "Difficulty:" is 176 px and lands 48 px on top of it.
#
# The bound here is a plugin-drawn picture's own x, so the fix is to RAISE the
# bound rather than compress three labels into abbreviations. Moving the value
# column from 300 to 430 gives the widest English label 258 px against the 240
# it needs, and the widest English value ("Good at Being Spoiled", 336 px)
# still ends at 766 on an 816-wide screen.
#
# This is the ONE place the patch changes a non-string leaf, and
# `verify_structure` requires every such change to appear here and prints them.
# --------------------------------------------------------------------------
# CBR_EroStatus coordinate repairs
# --------------------------------------------------------------------------
# The ero-status header runs `Azusa Now  (Loop Count N time(s))` across the top
# of a framed panel. Measured off `img/pictures/エロステＢＡＣＫ.png`, the frame's
# decorative border begins at **x = 440**, and the English tail ended at 465 -
# outside the frame, which is what showed on screen.
#
# The whole loop-count group moves left, and the tail caption shortens to `)`
# (see the `回目)` entry in the caption table). New layout, at size 20 with a
# 10 px half-cell:
#
#     (Loop Count   x 235 -> 190   ends 300
#     \V[40]        x 350 -> 305   (CE1)
#     \V[40]        x 370 -> 305   (CE18)  same, so both pages agree
#     )             x 385 -> 325   ends 335, a clear 105 px inside the frame
#
# `Azusa Now` ends at 178, so the group still clears it by 12 px.
#
# WHY THE CLOSING PAREN SITS WHERE IT DOES. `\V[40]` is drawn at a FIXED x, so
# the gap after it is the reserve for the widest number the counter can ever
# show - the paren cannot move with the digits. The Japanese had the identical
# gap for the identical reason (`\V[40]` at 350, `回目)` at 385).
#
# The reserve is TWO digits, 20 px, so a one-digit count leaves a 15 px gap
# that reads as an ordinary space. Evidence for two being enough: variable 40
# has exactly two writes in the whole game - `+= 1` once per loop and a `= 4`
# on Map028 - and ZERO comparisons, so nothing caps it, but nothing needs it
# large either. A hundredth loop would touch the paren; if that is ever a real
# playthrough, move this to 335 for three digits and accept a 25 px gap.
# The alternative - right-aligning the value so the paren always sits tight -
# needs a `左右-右` row that does not exist in these blocks, and ADDING a
# command would move the index every save file stores. Not worth it for 15 px.
#
# These are `x-NNN` rows inside 655 SCRIPT strings, so they are ordinary string
# leaves - `verify_structure` does not need a non-string exception for them -
# but they are declared here anyway, guarded on the value they expect to find,
# so a re-run is a no-op and a game update is a loud failure.
CBR_LAYOUT = {
    ("CommonEvents.json", 1): {
        34: ("x-235", "x-190", "(Loop Count"),
        40: ("x-350", "x-305", "the loop counter value"),
        46: ("x-385", "x-325", "the closing paren, 2-digit reserve"),
    },
    ("CommonEvents.json", 18): {
        20: ("x-235", "x-190", "(Loop Count"),
        26: ("x-370", "x-305", "the loop counter value, aligned with page 1"),
        32: ("x-385", "x-325", "the closing paren, 2-digit reserve"),
    },
}


PICTURE_LAYOUT = {
    # file, json-pointer to the command list, command index -> {param: value}
    ("Map002.json", "events/1/pages/0/list", 71): {
        4: (300, 430, "trait value column: make room for 'Erogenous Zone:'"),
    },
    ("Map002.json", "events/1/pages/0/list", 125): {
        4: (300, 430, "erogenous-zone value column"),
    },
    ("Map002.json", "events/1/pages/0/list", 161): {
        4: (300, 430, "difficulty value column"),
    },
}
