#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py — extraction/injection configuration.

Defaults are tuned for this game (RPG Maker MZ, native code-101 speaker boxes:
the speaker name is parameters[4] of each Show-Text command). Each flag can be
overridden from the CLI.  Anything risky (scripts, control-variable strings,
plugin commands) is OFF by default so a first run only ever touches clearly
player-visible text.
"""

from dataclasses import dataclass, field


@dataclass
class Config:
    engine: str = "mz"            # "mv" or "mz". mz => read/write code-101
                                  # parameters[4] as the native speaker name.

    # --- which event codes to extract --------------------------------------
    code_text: bool = True        # 401 / 405 show-text & scrolling-text
    code_choices: bool = True     # 102 show-choices
    code_scroll: bool = True      # treat 405 like 401
    code_122: bool = False        # ALL control-variable string assignments (risky:
                                  # many are internal keys/CG filenames — leave off)
    code_122_display: bool = True # SAFE subset: code-122 strings whose variable is
                                  # later shown to the player via \V[n] (warnings,
                                  # menu/recollection labels, tutorial text). Logic-
                                  # only vars (expression keys, CG filenames) are
                                  # never \V-referenced, so they're excluded.
    code_356: bool = False        # MV plugin commands (D_TEXT etc.) (risky)
    code_357: bool = True         # MZ plugin commands — targeted, player-facing args
                                  # only (see PLUGIN_357_TEXT in extract.py). ON: this
                                  # game's prologue + status/UI text lives in DTextPicture.
    code_355: bool = False        # script lines (very risky)
    code_108: bool = False        # comment annotations (risky)

    # --- which data-file fields to extract ---------------------------------
    names: bool = True            # item/skill/enemy/class/state names + descriptions
    actor_names: bool = True      # actor name/nickname/profile (-> glossary names)
    system: bool = True           # System.json terms / types / title / currency
    map_names: bool = True        # Map displayName + MapInfos names
    notes: bool = False           # <tag:...> note fields (off by default)
    note_labels: bool = True      # display note tags <LB:..> (EventLabel) — auto-extracted
    code_355_text: bool = True    # safe code-355/655 display strings (addText, …)
    help_reflow: bool = True      # re-flow the CE100 help/tutorial screens (vars
                                  # 501-516) so translated English fits the fixed
                                  # per-line picture layout (see helpwrap.py)
    system_switches: bool = False
    system_variables: bool = False

    # --- text wrapping (applied on inject) ---------------------------------
    # Calibrated for THIS game: RPG Maker MZ, 1280x720 UI, M+ 1m MONOSPACE font @
    # 26px. Monospace => width is in half-width cells (ASCII/space = 1, full-width
    # CJK = 2), so char-count wrapping is exact. Measured box capacity (Pillow +
    # the game's own hand-broken lines): message window 96 cells wide, 84 with a
    # face portrait, help/description window 96 cells, message window 4 rows tall.
    # Values sit just under those caps for a safe margin.
    fix_wrap: bool = True
    width: int = 88               # message box, no face (cap 96 cells = 1256px / 13px)
    face_width: int = 80          # message box WITH a face portrait (cap 84 cells = 1104px)
    list_width: int = 90          # item/skill descriptions: help window is full-width (cap 96)
                                  # but only ~2 ROWS tall — wrap WIDE so a description stays <=2 lines
    note_width: int = 88
    max_rows: int = 4             # message window height (rows; MZ default 4, matches the data).
                                  # Longer wrapped text splits into continuation boxes.
    # `\{` (makeFontBigger) renders larger text; wrap narrower / fewer rows so it
    # doesn't spill. (This game uses almost no \{-enlarged dialogue.)
    big_width: int = 60           # wrap width for \{-enlarged dialogue
    big_max_rows: int = 2         # enlarged text fits fewer rows
    ptext_width: int = 72         # CENTERED DTextPicture narration (prologue crawl):
                                  # re-wrap the (longer) English to fit on screen.
                                  # Position-anchored UI picture labels are NOT wrapped.

    # code-122 variable IDs that hold ASSET KEYS, NOT display text — their value builds
    # a 立ち絵/CG image filename (or is matched with ==), so they must stay Japanese even
    # when the SAME literal is legitimately translated elsewhere as display (e.g. 魔王: a
    # codex title -> "Demon Lord", vs var4671: the Demon-Lord bust key). apply_var_text
    # is global-by-string, so without this the codex translation clobbers the key. This
    # is the full image-name register (CE1930/1932/1933): expression + costume-state
    # selectors (通常/裸/ボテ…), bust/character NAME keys (魔王/勇者/モレク/侍/賢者/
    # リバイアサン…), and path fragments. None are ever shown to the player.
    vartext_skip_vars: tuple = (
        *range(4622, 4636), *range(4642, 4657),    # expression + costume-state selectors
        *range(4664, 4670), *range(4671, 4679),    # character NAME keys (busts)
        *range(4681, 4685), 4690, 4691, 4901,      # path fragments + extra busts
    )

    # --- misc --------------------------------------------------------------
    carry_speaker: bool = True    # carry \kw speaker forward across a page for context
    game_jp: str = ""
    game_en: str = ""
