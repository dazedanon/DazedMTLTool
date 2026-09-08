#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py - every per-game path and ruling in one place.

The values here are MEASURED on this build, not carried across from another
game. Where a number came out of a census, the census file is named next to it
so it can be re-run rather than re-argued.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULTS = {
    # --- where things live -------------------------------------------------
    # The game folder is a WORKING COPY and may be deleted. Nothing in this
    # package may depend on it except through these two settings.
    "game_dir":   r"c:\Users\sw\Desktop\Games\執聖官アルテシアVer1.06",
    "proj_dir":   os.path.join(ROOT, "proj"),      # descrambled rom tree
    "work_dir":   os.path.join(ROOT, "work"),      # BakinTL export
    "store_dir":  os.path.join(ROOT, "tl"),        # the translation store
    "out_dir":    os.path.join(ROOT, "out"),       # injected rom tree
    "dist_dir":   os.path.join(ROOT, "dist"),      # the shippable patch
    "bakintl":    os.path.join(ROOT, "BakinTL", "BakinTL.exe"),
    "keywords":   os.path.join(ROOT, "tools", "codes_raw.txt"),
    # `BakinTL layout` output. Without it EVERY overflow check is skipped, and
    # `validate` says so out loud rather than passing silently.
    "layout_tsv": os.path.join(ROOT, "layout.tsv"),
    # The pixel size to measure at. Bakin r64268 exposes no font-size field on
    # the widget, so this cannot be read - it has to be CALIBRATED against a
    # real render.
    #
    # 24 was a guess and it was wrong. Calibrated from an in-game screenshot
    # (`tools/calibrate_font.py`), which is the only ground truth available:
    # the message panel broke a known line after "you're a" and fitted a known
    # 68-character line on one row, and exactly one (font, size, width) triple
    # satisfies both - **Yu Gothic Light at 22px in a 690px panel**.
    #
    # Note what that says about the FONT. `GameSettings.gameFont` asks for
    # 游明朝 Demibold, which is not installed on this machine, so the engine
    # substituted - and it substituted a SANS, not a Mincho. A player who has
    # Yu Mincho sees different metrics from these. That is inherent to a game
    # that names an installed font instead of shipping one, and it is reported
    # rather than hidden.
    "font_size": 22,

    # LAYOUT WIDGETS RENDER AT A DIFFERENT SIZE FROM THE MESSAGE BOX, and
    # assuming one size for both is what made the menu look broken while every
    # check passed. 24px, and this is the best-evidenced number in the file.
    #
    # Seven menu labels in node 9847d4a0 are hand positioned (`origin =
    # MiddleLeft`, `pos.X` nudged per label) so the JAPANESE sits centred on its
    # plate. Their widths run 48px to 154px, so the size that makes all seven
    # centres agree is heavily overdetermined - six independent constraints on
    # one unknown:
    #
    #     size    centre spread across the seven labels
    #     20px            10.0 px
    #     22px             5.6 px
    #     24px             1.2 px      <-
    #     26px             3.5 px
    #
    # That is a sharper instrument than reading a screenshot, and it is
    # self-checking: `recentre.detect` reports the spread it achieved, so a
    # wrong size shows up as a group that fails to cohere.
    #
    # The message box really is a different size - the same screenshot's wrap
    # needs a box in [678, 708) at 22px, which the declared 690px Message node
    # satisfies, while 24px would need [747, 774) and no declared node is that
    # wide. Two renderers, two defaults; this build has no `Font` rom resource
    # for either to read.
    "layout_font_size": 24,

    # --- model -------------------------------------------------------------
    # Sonnet 5 is the volume workhorse; Opus 5 costs ~2.5x and is worth it only
    # if the prose review says so. State the effort next to any cost figure:
    # an estimate at `low` is wrong by a multiple against the API default.
    "model":  "claude-sonnet-5",
    "effort": "low",
    # 5m, not 1h. A batch fans requests out independently, so most of them
    # WRITE the cached prefix rather than read it. Break-even hit rate is
    # (1-f)*write + f*0.10 < 1.00, i.e. f > 53% at the 1h write multiplier of
    # 2.0 and f > 22% at 5m's 1.25. Measured batches land at 31-42%: over the
    # 5m break-even, nowhere near the 1h one.
    "batch_ttl": "5m",
    "live_ttl":  "5m",

    # --- chunking ----------------------------------------------------------
    # Scene-aligned but NOT one request per scene: this game has 1,487 owners
    # and packing them keeps the per-request overhead off the bill.
    # 150, ABOVE the skill's 40-90 dialogue guidance, and raised only after
    # running the test that the guidance exists to protect against.
    #
    # The cached prefix is 32,221 tokens (MEASURED, not proxied) and the dynamic
    # payload is 4,393 per request at 80 units, so on a batch the PREFIX is most
    # of the bill and the request COUNT is the lever. Costed from measured
    # tokens at a 35% cache-hit rate, which is what real batches reach:
    #
    #     max_units    requests   all-writes   35% hit   all-reads
    #        80           307       $17.83      $13.85     $6.46
    #       120           205       $13.73      $11.07     $6.13
    #       150           164       $12.08       $9.95     $6.00
    #       200           123       $10.42       $8.83     $5.87
    #
    # The guidance range exists because an oversized request truncates and then
    # masquerades as "the model is bad at following the schema". That is a
    # testable claim, so it was tested: `tl.py smoke --max-units 150` returned
    # **132 of 132 keys** with `stop_reason: end_turn` and 4,433 output tokens -
    # 33.6 per unit against a 21,000 cap, five times the headroom. 200 is
    # cheaper still and is NOT set, because nothing has measured it.
    "max_units":     150,
    "context_lines": 3,
    # The roster is the largest cached block and it is written far more often
    # than it is read on a batch. 465 distinct speakers would make it ~18k
    # tokens on every request; the tail is served by the per-request matched
    # terms instead. A speaker under this many lines is not in the roster.
    "roster_min": 25,
    # How much of a glossary row's role/register reaches the cached roster. The
    # FILE keeps the full evidence for a human; the block is a compressed
    # one-liner by design. Untruncated, 146 rows are 12,317 tokens; at 150
    # chars they are 10,399.
    "roster_field_chars": 150,

    # --- dedup -------------------------------------------------------------
    # MEASURED (tools/dedup_risk.py): 83,999 dialogue units reduce to 22,914
    # distinct (speaker, body) pairs - a 3.7x factor that is most of the bill.
    # The skill's default is "never dedupe dialogue", because a line reused in
    # another scene can be right where it was translated and wrong elsewhere.
    # Here the risk surface is small and measurable: only 156 distinct bodies
    # are spoken by more than one speaker, and they are almost all ellipses and
    # moans. Deduping on (speaker, body) rather than body alone costs 275 extra
    # units and removes the pronoun class entirely.
    #
    # What remains - a line reused across two scenes by the SAME speaker - is
    # caught after the fact: `qa.py repeats` re-reviews any deduped dialogue
    # that spans 2+ owners and whose translation contains a third-person
    # pronoun. Set this False to fall back to the conservative default.
    "dedup_dialogue": True,

    # --- files the catalog cannot reproduce byte-for-byte -------------------
    # MEASURED by `tl.py roundtrip`: 328 of 329 rom files write back
    # byte-identical. The one exception carries a stray `Folder` record with
    # signature 768 (the editor's MAP ROOT folder) saved into a map file by an
    # older Bakin build. The writer does not emit it, so the file comes out 88
    # bytes shorter and the Map record loses its 16-byte reference to it.
    #
    # It holds no player-facing data - the folder's name is empty and the tree
    # is editor metadata - but "probably harmless" is not a reason to ship a
    # file the tooling cannot reproduce. So it is never written: its units are
    # skipped and the pristine file is copied through byte-for-byte.
    #
    # The cost is exactly one unit: the map's own name, `テストニンジャ`
    # ("Test Ninja"), a developer test map with no events and no dialogue.
    "unwritable_files": [
        r"map\テストニンジャ_5efb9b10-d9cb-45fb-9b85-1f74dd33b3c9.rbr",
    ],

    # --- layout ------------------------------------------------------------
    # There is no Font rom resource on this engine build. GameSettings.gameFont
    # names an INSTALLED system font, so both our measurement and the player's
    # screen depend on what they have. Report a substitution, never hide it.
    "game_font": "游明朝 Demibold",

    # --- WHICH FONT THE GAME ACTUALLY ASKS FOR -----------------------------
    # Written into `GameSettings.gameFont`. None leaves the author's value.
    #
    # WHY THIS IS SET. The author asks for `游明朝 Demibold`, which is not
    # installed outside a Japanese Windows, so the native layer substitutes
    # something of its own choosing - and the substitute in play here has no
    # glyph for U+2661 WHITE HEART SUIT, which the SOURCE uses **229,107 times
    # across 50,427 units**. Every one of them draws as a tofu box. It is not
    # something the translation introduced; it is what this game does on a
    # machine without Japanese fonts.
    #
    # Character substitution cannot fix it: the likely substitutes (Microsoft
    # YaHei, JhengHei, SimSun) have no U+2661, no U+2665 and no U+266A either,
    # so there is no heart to fall back to. The font has to be named.
    #
    # `Yu Gothic Medium` because it is all three of:
    #   * PRESENT - it shares YuGothM.ttc with `Yu Gothic UI Regular`, and the
    #     Yu Gothic UI family is a Windows system font in every locale rather
    #     than part of the removable Japanese supplemental pack;
    #   * COMPLETE - it carries ♡ ♥ ♪ ～, kana and kanji;
    #   * HEAVY ENOUGH TO SURVIVE THE UPSCALE, which `Yu Gothic Light` is not.
    #
    # THAT LAST POINT IS A REPORTED DEFECT, not a preference. The message body
    # and the nameplate render from DIFFERENT rasters: `GraphicsCore.refreshFont`
    # builds `mFont = createFont(24, 1f)` and `mLargeFont = createFont(72, 1f)`,
    # layout text (the nameplate) draws mLargeFont at scale.X/3 - a 72px raster
    # shown small - while the message path measures and draws mFont. On a window
    # scaled ~1.755x the body is a 24px raster stretched to ~42px and the name is
    # a 72px raster shrunk to it, so the name is crisp and the body is soft. That
    # is the ENGINE's, and lowering the window resolution is what makes it better.
    # The WEIGHT is ours: the author asks for a DEMIBOLD and the first fix here
    # substituted a LIGHT, whose thin stems the upscale destroys. Medium restores
    # the weight without pretending to fix the raster.
    #
    # WHAT THIS COSTS, measured over all 83,999 translated dialogue units at the
    # 670px panel - units needing more than `message_lines` rows:
    #
    #       face                  at PIL 22px      at 24px
    #       Yu Gothic Light        834 (0.99%)    1495 (1.78%)
    #       Yu Gothic Regular     1370 (1.63%)    2195 (2.61%)
    #       Yu Gothic Medium      1365 (1.63%)    2199 (2.62%)
    #       Yu Gothic Bold        1849 (2.20%)    3072 (3.66%)
    #       bundled font.ttf      2498 (2.97%)    3658 (4.35%)
    #
    # Regular and Medium are within 5 units of each other; Medium is chosen for
    # the extra weight, which is the whole point of the change.
    #
    # WHAT DID NOT HAVE TO BE RE-DERIVED, and why that is a measurement rather
    # than an assumption:
    #   * `layout_ink_offset_ratio`. Measured with PIL on descender-free text,
    #     (line_centre - ink_centre)/px is +0.0547 for Light, Regular AND Medium
    #     alike (Bold is +0.0625, a 0.19px difference at 24px). The face does not
    #     move it, so the screenshot-measured -0.277 carries over untouched, and
    #     so does `layout_pos_overrides` entry :131, which is a function of it.
    #   * `layout_font_size` 24. Its evidence is seven JAPANESE menu labels, and
    #     CJK advances are bit-identical across the four Yu Gothic weights.
    #   * every budget whose bound comes from the author's own Japanese.
    #
    # WHAT IS CARRIED OVER ON AN ASSUMPTION, stated so it is not mistaken for
    # evidence: `font_size` 22 is the size at which PIL reproduces the engine's
    # native rasteriser at its nominal 24px. That discrepancy is a rasterisation
    # artifact rather than a weight one, and CJK advances do not move between
    # these faces, so 22 is carried over - but it was fitted against a Light
    # render and has not been re-observed on a Medium one. `tools/calibrate_font.py`
    # settles it from one screenshot of the running game.
    #
    # The alternative is `""`, which makes `useSystemFont` false and loads the
    # game's own bundled `font.ttf` (M+SmileBoom) - GUARANTEED present because
    # it ships inside data.rbpack, and it covers everything. It is not the
    # default because it is a much wider bold face: at the engine's true 24px it
    # takes dialogue pagination from 687 units (0.8%) to 3,156 (3.8%) and
    # changes the game's whole typeface. Switch to it if a player reports tofu
    # anyway. (Note `""` really does reach font.ttf - the `メイリオ` line in
    # `GraphicsCore.createFont` sits after the `!useSystemFont` early return and
    # is unreachable.)
    "game_font_override": "Yu Gothic Medium",
    # The rom item that carries it. Derived, not guessed: it is the GameSettings
    # whose `name` field is the window title.
    "game_settings_guid": "d24df012-3177-49f2-8bf3-12481548dcba",
    # Ordered by what this machine ACTUALLY falls back to, verified against the
    # screenshot: Yu Gothic Light is what rendered. The Mincho entries stay
    # ahead of it so a machine that has the requested font measures with it.
    "font_fallbacks": ["Yu Mincho Demibold", "Yu Mincho", "YuMincho",
                       "Yu Gothic Medium", "Yu Gothic", "Yu Gothic Light",
                       "MS Mincho"],
    # The message panel, measured: the layout declares both 690x140 and
    # 670x136 Message nodes and the calibration says the live one is 690.
    "message_px": 690.0,
    "message_lines": 3,
    # The width the ENGINE wraps at, PER KIND, for the layout-repair pass.
    # A kind absent from this table is never rebalanced.
    #
    #   text     690, CALIBRATED against a real screenshot (see font_size).
    #   message  670, the SMALLER of the two declared Message nodes. Both
    #            `LayoutStateMessage` and `LayoutStateDialogue` reach
    #            `MessageReader.ReadMessage`, and no screenshot of the plain
    #            Message box exists to say which node it uses - so pick the
    #            conservative one. A line balanced to 670 fits a 690 box too,
    #            so it is never re-wrapped whichever node is live. The reverse
    #            is not true, which is why the calibrated 690 is not reused.
    #   telop    ABSENT on purpose. `LayoutStateTelop` is a third node with no
    #            measured width, and it calls `wordWrap` WITHOUT
    #            `splitByLines`, so it never paginates - a mis-sized repair
    #            there overflows the telop area silently instead of costing a
    #            key press. 13 affected units, left alone and reported.
    "wrap_px": {"text": 690.0, "message": 670.0},

    # --- vertical centring --------------------------------------------------
    # `origin` on a TEXT_PANEL sets BOTH alignments: MiddleLeft means vertical
    # Center AND horizontal Left. A Middle* label is then centred on its OWN
    # box, not on the plate it sits on, and the two coincide only when
    # `pos.Y == (plateH - size.Y)/2`. This game's menu labels are 45px boxes on
    # a 35px plate at pos.Y 2, so they centre at 24.5 against a plate centre of
    # 17.5 - seven pixels low, with the descenders clipped by the sub
    # container's 35px window.
    #
    # This is the AUTHOR's offset, not damage the translation did: the Japanese
    # sat equally low, and the same habit shows up on the title screen and the
    # fast-travel list. It is a deliberate improvement and it is one switch to
    # revert. 15 labels qualify game-wide - only those ALONE on their plate,
    # because pos.Y is also how several labels are stacked on one plate and
    # centring those would pile them on top of each other (the save slots put
    # five fields on one 80px plate).
    # WHICH NODES the vertical pass may touch. Empty list = none, None = all.
    #
    # Deliberately just the main menu. The ink offset below is MEASURED off a
    # screenshot of that one screen, and applying it everywhere turned 15
    # candidate labels into 207 - across the Config, Inn, Shop, Member,
    # Dictionary and Title screens, none of which I have ever seen rendered.
    # Most of those sit at pos.Y = 0 in the author's own data; moving them all
    # on the strength of one screen's calibration is not a repair, it is a
    # guess applied at scale. Add a node here only once its screen has been
    # captured and measured the same way.
    # --- eyeballed position nudges ------------------------------------------
    # Keyed "<nodeGuid>:<idx>" -> {"posX": x, "posY": y}. Applied verbatim.
    #
    # UNLIKE every other geometry number in this file these are NOT measured -
    # the battle-result screen needs a won battle to reach, so it cannot be
    # captured and measured the way the menu was (`tools/vcentre_calibrate.py`).
    # They are read off a player screenshot and are meant to be tuned, which is
    # why they live here as literals rather than being derived.
    #
    # Both are the AUTHOR's positions, unchanged by any pass in this pipeline:
    #   132 "Level"  pos.Y -12, TopLeft, scale 0.6 - sits ABOVE the level
    #                triangle it belongs in. Nudged down.
    #   133/134 "Next" and its value, pos.Y 36 - asked to sit slightly lower.
    # BattleResult_1's EXP gauge (container idx 5, 400x52, window
    # `window_shadow_11.png`: a downward triangle at the left, then the bar).
    # `recentre.vcentre` DECLINES this container and is right to - not one of
    # its four labels sits centred in the 52px band, so every pos.Y in it is
    # the author's deliberate placement and the centring term does not apply.
    # Only the INK term does, and only where the symptom is the font swap.
    #
    #   131  the level number, MiddleCenter, scale 1.0, drawn at 24px.
    #        The author centred its line box at pos.Y + size.Y/2 = 18, which
    #        is the downward triangle's centroid (art spans texture y 6..61 of
    #        72; at 52px that is ~4..45, centroid ~4 + 41/3 = 17.7). Correct in
    #        the original font. `game_font_override` substitutes a face whose
    #        ink sits `layout_ink_offset_ratio` of the drawn size ABOVE the
    #        line-box centre, so the digit now draws at ~11 and reads as high
    #        in the triangle. Lower it by that one term and nothing else:
    #            pos.Y = 2 - (-0.277 * 24 * 1.0) = 8.65
    #        This is the same correction `vcentre` applies on the main menu,
    #        computed by hand because the centring half of that pass does not
    #        belong here.
    #   133/134  'Next' and its value, MiddleRight, scale 0.6, below the bar.
    #        36 -> 42 by eye, confirmed on screen. The ink term alone would
    #        give 40; the extra 2px is not derived and is kept only because
    #        the shipped result was checked and accepted.
    #
    # 132 ('Level', TopLeft, scale 0.6) is NOT here on purpose. Top-aligned
    # text draws at the box top, so the ink model above does not describe it,
    # and moving it to -4 collided the caption with the number. The author's
    # -12 stands.
    "layout_pos_overrides": {
        "7549377f-4054-476d-9a8a-7bbe6b582a7f:131": {"posY": 8.65},
        "7549377f-4054-476d-9a8a-7bbe6b582a7f:133": {"posY": 42.0},
        "7549377f-4054-476d-9a8a-7bbe6b582a7f:134": {"posY": 42.0},
    },

    "layout_vcentre_nodes": ["9847d4a0-c4c6-4a43-96d5-8739260152d1"],

    # PANEL shapes approved for band centring, as [width, height].
    #
    # A RENDER_CONTAINER is not a button - it is a panel that may hold several
    # things at deliberate positions, so centring everything inside one would be
    # vandalism. Two gates before anything moves:
    #
    #   * the author must have SHOWN the intent, by having already placed the
    #     box centred in its band (the band being the panel split at any thin
    #     rule inside it - a heading above the rule is not centred in the panel);
    #   * the panel must be an APPROVED SHAPE, listed here.
    #
    # The shape gate is what keeps this honest. Scoping by NODE let every
    # Middle* label in any screen that merely contained a money panel through -
    # BattleResult, MainMenu - which is the same over-reach in a different hat.
    # A shape is one widget: verified once, identical everywhere it appears.
    #
    # 186x98 is the two-cell money panel (a heading over a rule at y=48, a value
    # under it), reported off a screenshot of the inn. 26 labels game-wide, all
    # of them that same widget in Inn, ShopSelect, MainMenu and BattleResult.
    # Its heading sat at pos.Y 4, which centres the LINE BOX on the cell and so
    # leaves the ink 6.6px high.
    "layout_vcentre_panel_shapes": [[186, 98]],

    # --- labels the extractor could never see -------------------------------
    # A layout label containing NO Japanese is never extracted, so it is never
    # a unit, so no check in this pipeline can ever look at it. Usually that is
    # right. It is wrong when the label is part of a GROUP whose other members
    # were translated, because the translation changes them and not it.
    #
    # The H-status screen pairs two stat labels per row. The author aligned them
    # by padding the short one with a leading IDEOGRAPHIC SPACE (U+3000, 24px):
    #
    #     攻撃力 ＋   at pos.X 121        　MP ＋   at pos.X 127
    #     防御力 ＋   at pos.X 123        　HP ＋   at pos.X 132
    #
    # `　魔力 ＋` had the same padding and WAS extracted (it has kanji), so its
    # translation "Mana +" dropped the space and it lines up. `　MP ＋` and
    # `　HP ＋` are pure Latin, were never extracted, and still carry a 24px
    # indent their partners lost - which is exactly the misalignment on screen.
    #
    # So they are written literally. `align_to_partner` also copies pos.X from
    # the translated sibling in the same container, because the author's 6-9px
    # offset was compensating for full-width text that is no longer there.
    #
    # `　{code}` spacers are deliberately NOT in this table: the 119 uses of
    # `　\\itemnum` are a gap between an item name and its count, not a label.
    # `BakinTL effectparams` output. A Condition stores its battle messages
    # TWICE - the flat `messageFor*` family, and again inside
    # `EffectParamSettings.EffectParamList[]` - and the ENGINE reads the nested
    # copy. Translating only the flat one leaves Japanese on screen while every
    # unit in the store is translated and every check is green.
    #
    # All 33 distinct nested strings are EXACT duplicates of strings already
    # translated elsewhere, so they need no translation of their own: they are
    # filled by source match, which also guarantees the two copies never drift.
    "effectparams_tsv": os.path.join(ROOT, "work", "effectparams.tsv"),

    "layout_literal_fixups": [
        # THE AUTHOR'S OWN TYPO, shipped in the Japanese release too: a stray
        # literal `text` after the getter, so the battle-result gauge reads
        # "102text" instead of "102". It has no Japanese, so it was never
        # extracted and nothing in the pipeline could reach it.
        #
        # Fixed anyway. A defect the author already ships is not one the patch
        # introduced - but we are the ones shipping this screen now, and it
        # costs one declared literal.
        {"src": r"\partystatus[0][10]text", "en": r"\partystatus[0][10]"},
        {"src": "　MP ＋", "en": "MP +", "align_to_partner": True},
        {"src": "　HP ＋", "en": "HP +", "align_to_partner": True},
    ],
    "layout_vcentre": True,
    # Centring the LINE BOX is not centring the TEXT. `DrawString` centres
    # `MeasureString(text).Y`, which is the engine's native line height - much
    # taller than the visible ink and NOT symmetric about it, so a label whose
    # line box is centred still reads as sitting high.
    #
    # The size of that error cannot be computed from the font's own tables. For
    # Yu Gothic Light none of them predicts it: hhea gives -0.9px, OS/2 win
    # gives -0.6px, typo gives +0.1px, and the truth is -5.2px. The native
    # measureString is doing something none of those describe.
    #
    # So it is MEASURED off the screen instead. `tools/vcentre_calibrate.py`
    # screenshots the running game, finds each button's frame lines and its text
    # ink, and reports the offset between the two centres. At pos.Y = -5 on the
    # 192x35 menu plates the ink came out 9.8 capture px high; the button pitch
    # of 82.5 capture px against a known design pitch of 45 gives a scale of
    # 1.833, so that is **-5.32 design px** at a drawn size of 19.2px.
    #
    # Expressed as a fraction of the drawn size, because every term in it
    # (ascent, descent, cap height) scales linearly with the size:
    #
    #     ink_centre = pos.Y + size.Y/2 + ratio * (layout_font_size * scale.X)
    #
    # Cross-check: at scale 1.0 this predicts pos.Y = 6.5 for a label whose box
    # equals its plate, and the author hand-placed the title-screen buttons -
    # same shape - at 7 and 8. The formula lands inside the author's own eye.
    "layout_ink_offset_ratio": -0.277,

    # --- resizing a label that no longer fits its plate ---------------------
    # `MenuItem.scale.X` is the ONLY per-widget font size this engine has: it
    # draws one 72px face at `scale.X / 3`, so 1.0 is 24px. Lowering it is how a
    # label is made to sit inside its button.
    #
    # WHY THE MAIN MENU NEEDED IT, when the English is NARROWER than the
    # Japanese it replaced. Width was never the problem - height was, and only
    # for Latin. The plate is 192x35 and its art (`window_02.png`, 9-sliced)
    # draws its frame across y=7..56 of a 64px texture, so the visible interior
    # is about 27px. A 24px line box is 28px. CJK sits tidily inside its em
    # square with no descenders; Latin hangs 'g', 'p', 'q' below the baseline
    # and pushes caps above the CJK cap line, so at the SAME nominal size it
    # occupies the full interior and reads as spilling out of the button.
    #
    # Judged by compositing the real plate texture with the real font
    # (`tools/menu_mock.py`, which reproduces the in-game screenshot): at 1.00
    # and 0.90 the glyphs cross the frame on every button, at 0.85 two still
    # touch, at 0.80 all eight sit clear.
    #
    # 0.80 is also the AUTHOR's own number - it is what they set by hand on
    # ファストトラベル and ゲームを終える, the two buttons whose Japanese was longest.
    # Applying it to all eight both fixes the fit and makes the menu uniform,
    # which it was not before.
    #
    # Keyed "<nodeGuid>:<idx>". `recentre` recomputes the centre from the
    # RESIZED width, so a resize never un-centres a label.
    #
    # THE DESCRIPTION PANELS, 0.90, for a different reason: ROW COUNT.
    #
    # Every `\currentitemdes` slot declares `maxLineNum = 3`, and the author
    # writes the MP cost INTO the description behind a hard newline
    # (`...\\n消費MP40`). So the body gets two rows and the MP line is
    # the
    # third. English that needs three rows on its own pushes the MP line to a
    # fourth, and the player sees "MP Cost: 40" drawn TWICE - once spilling
    # over the panel border and once in its proper place below.
    #
    # Measured over the 279 translated descriptions at the narrowest slot
    # (360px effective), units needing more than three rows:
    #
    #       scale   eff px   all descriptions   skill descriptions
    #       1.00     360           65                  14
    #       0.95     379           54                   5
    #       0.90     400           39                   0
    #
    # 0.90 clears every skill description, which is the visible defect. It also
    # leaves the general item descriptions BETTER than they shipped before -
    # 39 over, against 43 under Yu Gothic Light at 1.00 - so this is not a
    # trade made at their expense. Those 39 are clipped rather than doubled
    # (`clipping = True` on every slot but one) and are a pre-existing defect,
    # not one the font change introduced; `tools/rowfit_audit.py` counts them.
    #
    # Two slots are deliberately absent. `6e673db1...:17` is 64x64 with
    # `wordWrap = False` - not a description body. `651e3d24...:31` already
    # ships at 0.80, and raising it to 0.90 would make it worse.
    "layout_scale_overrides": dict(
        [("9847d4a0-c4c6-4a43-96d5-8739260152d1:%d" % i, 0.80)
         for i in (17, 18, 19, 20, 21, 22, 23, 24)]
        + [(k, 0.90) for k in (
            "6168be18-10d7-4048-97c7-285cc6e72e75:22",    # BattleItem
            "46f04304-ad75-4f87-affa-c119bab7d81e:47",    # ItemSelect
            "90e29105-4c1b-42fd-8b53-26c6d9bedf74:47",    # EquipmentItem
            "681396d6-4829-4e57-8e08-d14cd184b137:30",    # EquipmentCategoly
            "2d55c3ba-dc9a-44f7-80a9-6e0eba1c0281:27",    # DiscardedItemSelect
            "324d93bd-933c-4bcf-934d-6271bdbeccea:47",    # EnhancementItemSelect
            "da0562d2-d501-4cf5-9318-c44a5be1967d:127",   # ItemSelect_1
            "539e6da7-87ae-41e4-a78a-1949addd8edf:47",    # EquipmentItem_1
            "e26e3ab1-c146-4a7c-a967-d052d7fd132d:127",   # 情報
            # ...and the SKILL and SHOP panels, which draw the same records
            # through DIFFERENT codes. Missing these first time round is the
            # whole reason `rowfit_audit` now derives its slot set from the
            # layout instead of naming one code: the fix and the check were
            # written from the same wrong assumption, so the check passed.
            "3ca3f89d-8ce0-42a2-9b06-5535e77eaf07:18",    # BattleSkill
            "945d0c5f-fd10-4c60-8c45-eafaa2c77078:36",    # SkillSelect
            "0ac47675-904a-4470-9036-bec74fa640d9:36",    # SkillSelect_1
            "170f73ef-70be-4c9b-8eec-11d9fa4a289f:16",    # BattleSkill_1
            "5fe2feef-a23d-496c-8a26-b7538c2af0b9:47",    # ShopBuy
            "0df8282e-899f-4188-8dac-319c4f1de450:46",    # ShopSell
            "55dbf3cd-40e7-48be-934e-93eae7455cb3:47",    # ShopBuy_1
            "6ef5cd46-5ae6-4ab8-87d6-ce1b0df81908:46",    # ShopSell_1
        )]),
}

CONFIG_NAME = "artl.config.json"


def load(path=None):
    cfg = dict(DEFAULTS)
    p = path or os.path.join(ROOT, CONFIG_NAME)
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    env = os.environ.get("ARTL_MODEL")
    if env:
        cfg["model"] = env
    return cfg


def save(cfg, path=None):
    p = path or os.path.join(ROOT, CONFIG_NAME)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return p
