#!/usr/bin/env python3
"""Patch UTF-8 string constants inside compressed Godot .gdc files."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


VENDOR_DIR = Path(__file__).resolve().parents[1] / "zstd_vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import zstandard as zstd
except ImportError as exc:  # pragma: no cover - dependency message only
    raise SystemExit(
        "Missing zstandard module. Install it locally with: "
        "python -m pip install zstandard --target .\\zstd_vendor"
    ) from exc


SOURCE_DEFAULT = Path("unpacked_pck")
OUTPUT_DEFAULT = Path("translated_assets")
REPORT_DEFAULT = Path("tooling") / "gdc_constants_patch_report.json"
GDSC_MAGIC = b"GDSC"
ZSTD_MAGIC = bytes.fromhex("28b52ffd")


@dataclass(frozen=True)
class PatchSpec:
    files: tuple[str, ...]
    replacements: dict[str, str]


PATCH_SPECS = (
    PatchSpec(
        files=("usecase/economy/get_unrevealed_key_items_use_case.gdc",),
        replacements={
            "\u3064\u304e\u306e[color=gray][s]\u307c\u3063\u305f\u304f\u308a[/s][/color]"
            "\u30a4\u30d9\u30f3\u30c8\u3067\u958b\u653e": (
                "Unlocked in next [color=gray][s]rip-off[/s][/color] event"
            ),
            "\u7279\u5b9a\u306e\u30a2\u30a4\u30c6\u30e0\u3092\u5165\u624b\u3059\u308b\u3068\u89e3\u653e": (
                "Unlocked by a certain item"
            ),
        },
    ),
    PatchSpec(
        files=("presentation/autoloads/overlay/overlays/config/config.gdc",),
        replacements={
            "\u30bf\u30a4\u30c8\u30eb\u306b\u623b\u308a\u307e\u3059\u304b\uff1f\n"
            "\u73fe\u5728\u306e\u9032\u884c\u72b6\u6cc1\u306f\u5931\u308f\u308c\u307e\u3059": (
                "Return to title?\nCurrent progress will be lost."
            ),
        },
    ),
    PatchSpec(
        files=(
            "presentation/autoloads/overlay/overlays/save/load_slot_item.gdc",
            "presentation/autoloads/overlay/overlays/save/save_slot_item.gdc",
            "presentation/ingame/views/home/panels/time_display_panel.gdc",
        ),
        replacements={
            "\u671d": "AM",
            "\u663c": "Noon",
            "\u591c": "Eve",
            "%02d\u65e5\u76ee %s": "Day %02d %s",
            "%d\u5206\u524d": "%dm ago",
            "%d\u6642\u9593\u524d": "%dh ago",
        },
    ),
    PatchSpec(
        files=("presentation/ingame/views/home/panels/me_status_panel.gdc",),
        replacements={
            "\u3064\u3088\u3055: %d ": "Power:%d     ",
            "\u3064\u3088\u3055: %d-%d ": "Power:%d-%d      ",
            "HP: %d": "HP:%d",
        },
    ),
    PatchSpec(
        files=("presentation/common/formatters/item_description_formatter.gdc",),
        replacements={
            " (\u3064\u3088\u3055\uff1a%d\uff5e%d)": " (Power Range: %d-%d)",
            " (HP\uff1a+%d)": " (HP: +%d)",
            "\uff08\u8aac\u660e\u306a\u3057\uff09": "(No description.)",
        },
    ),
    PatchSpec(
        files=(
            "presentation/autoloads/overlay/overlays/save/load_slot_item.gdc",
            "presentation/autoloads/overlay/overlays/save/save_slot_item.gdc",
        ),
        replacements={
            "\u3044\u307e": "Now",
        },
    ),
    PatchSpec(
        files=(
            "presentation/autoloads/overlay/overlays/save/load_menu.gdc",
            "presentation/autoloads/overlay/overlays/save/save_menu.gdc",
        ),
        replacements={
            "%s \u3092\u524a\u9664\u3057\u307e\u3059\u304b\uff1f": "Delete %s?",
        },
    ),
    PatchSpec(
        files=("presentation/autoloads/overlay/overlays/save/load_menu.gdc",),
        replacements={
            "\u30ed\u30fc\u30c9\u3057\u307e\u3059\u304b\uff1f\n"
            "\u73fe\u5728\u306e\u9032\u884c\u72b6\u6cc1\u306f\u5931\u308f\u308c\u307e\u3059": (
                "Load this save?\nCurrent progress will be lost."
            ),
        },
    ),
    PatchSpec(
        files=("presentation/autoloads/overlay/overlays/save/save_menu.gdc",),
        replacements={
            "%s \u3092\u4e0a\u66f8\u304d\u3057\u307e\u3059\u304b\uff1f\n"
            "\u4ee5\u524d\u306e\u30c7\u30fc\u30bf\u306f\u5931\u308f\u308c\u307e\u3059\u3002": (
                "Overwrite %s?\nPrevious data will be lost."
            ),
        },
    ),
    PatchSpec(
        files=(
            "presentation/common/formatters/item_description_formatter.gdc",
            "presentation/ingame/views/home/battle/quest_info.gdc",
            "presentation/ingame/views/home/panels/equipment_panel.gdc",
            "presentation/ingame/views/home/shop/shop_item_row.gdc",
            "presentation/ingame/views/home/statistic/statistics_modal.gdc",
        ),
        replacements={
            "\u306a\u3057": "None",
        },
    ),
    PatchSpec(
        files=("presentation/ingame/views/home/statistic/statistics_modal.gdc",),
        replacements={
            "\u5168\u8eab": "Body",
            "\u982d\u3092\u64ab\u3067\u305f\u56de\u6570": "Head pats",
            "\u306a\u3067\u3089\u308c\u305f:": "Patted:",
            "\u982d": "Top",
            "\u30ad\u30b9\u3057\u305f\u56de\u6570": "Kisses",
            "\u30ad\u30b9\u3055\u308c\u305f:": "Kissed:",
            "\u53e3\u3067\u30a4\u30c3\u305f\u56de\u6570": "Mouth climax",
            "\u30a4\u30c3\u305f\u2665:": "Came\u2665:",
            "\u9854\u306b\u5c04\u7cbe\u3057\u305f\u56de\u6570": "Face finishes",
            "\u9854\u306b\u5c04\u7cbe\u3055\u308c\u305f:": "On face:",
            "\u304a\u304f\u3061": "Mouth",
            "\u3061\u3093\u304b\u304e\u3057\u305f\u56de\u6570": "Close sniffs",
            "\u3061\u3093\u304b\u304e\u3055\u305b\u3089\u308c\u305f:": "Sniffed:",
            "\u55c5\u899a\u3067\u30a4\u30c3\u305f\u56de\u6570": "Smell climax",
            "\u306b\u304a\u3044\u3067\u30a4\u30c3\u305f\u2665:": "By smell\u2665:",
            "\u306b\u304a\u3044": "Smell",
            "\u4e73\u9996\u3092\u3064\u307e\u3093\u3060\u56de\u6570": "Nipple pinches",
            "\u3064\u307e\u307e\u308c\u305f:": "Pinched:",
            "\u80f8\u3067\u30a4\u30c3\u305f\u56de\u6570": "Chest climax",
            "\u4e73\u9996\u3067\u30a4\u3063\u305f\u2665:": "Nip climax\u2665:",
            "\u80f8\u306b\u5c04\u7cbe\u3057\u305f\u56de\u6570": "Chest finishes",
            "\u80f8\u306b\u5c04\u7cbe\u3055\u308c\u305f:": "On chest:",
            "\u4e73\u9996": "Nipple",
            "\u5c3b\u5c3e\u3092\u63c9\u3093\u3060\u56de\u6570": "Tail rub count",
            "\u5c3b\u5c3e\u3092\u63c9\u307e\u308c\u305f\u56de\u6570": "Tail rubbed",
            "\u304a\u5c3b\u3092\u63c9\u3093\u3060\u56de\u6570": "Butt rub count",
            "\u304a\u3057\u308a\u3092\u63c9\u307e\u308c\u305f\u56de\u6570": "Butt rubbed",
            "\u5c3b\u3067\u30a4\u30c3\u305f\u56de\u6570": "Butt climax",
            "\u304a\u3057\u308a\u3067\u30a4\u30c3\u305f\u56de\u6570": "Butt climax",
            "\u5c3b\u306b\u5c04\u7cbe\u3057\u305f\u56de\u6570": "Butt finishes",
            "\u304a\u3057\u308a\u306b\u5c04\u7cbe\u3055\u308c\u305f\u56de\u6570": "On butt count",
            "\u304a\u3057\u308a": "Butt",
            "\u30af\u30ea\u30c8\u30ea\u30b9\u3092\u89e6\u3063\u305f\u56de\u6570": "Clit touches",
            "\u30af\u30ea\u3077\u306b\u30b7\u30b3:": "Clit rub:",
            "\u30af\u30ea\u3067\u30a4\u30c3\u305f\u56de\u6570": "Clit climax",
            "\u30af\u30ea\u30a4\u30ad\u2665:": "Clit came\u2665:",
            "\u30af\u30ea\u30c8\u30ea\u30b9": "Clitoris",
            "\u30af\u30ea": "Clit",
            "\u81a3\u306b\u6307\u3092\u5165\u308c\u305f\u56de\u6570": "Fingers inserted",
            "\u6307\u3092\u5165\u308c\u3089\u308c\u305f:": "Fingered:",
            "\u81a3\u306b\u30c1\u30f3\u30b3\u3092\u5165\u308c\u305f\u56de\u6570": "Penetrations",
            "\u633f\u5165\u3055\u308c\u305f:": "Inserted:",
            "\u81a3\u3067\u30a4\u30c3\u305f\u56de\u6570": "Vag climax",
            "\u81a3\u306b\u5c04\u7cbe\u3057\u305f\u56de\u6570": "Inside finishes",
            "\u306a\u304b\u3060\u3057\u2665:": "Inside\u2665:",
            "\u81a3": "Vag",
            "\uff1f\uff1f\uff1f: \uff1f\u56de": "???: ?x",
            "%s %d\u56de": "%s %dx",
        },
    ),
    PatchSpec(
        files=("presentation/ingame/views/home/battle/quest_info.gdc",),
        replacements={
            "%d\uff5e%d": "%d-%d",
        },
    ),
    PatchSpec(
        files=("presentation/common/osawari/components/novel_hint_panel.gdc",),
        replacements={
            "\uff08\u30d2\u30f3\u30c8\u672a\u8a2d\u5b9a\uff09": "(No hint set)",
        },
    ),
    PatchSpec(
        files=("presentation/common/osawari/components/sleep_hint_panel.gdc",),
        replacements={
            "\uff1f": "?",
            "\uff08\u30d2\u30f3\u30c8\u672a\u8a2d\u5b9a\uff09": "(No hint set)",
            "\u4e0a\u7d1a": "Hard",
            "\u4e2d\u7d1a": "Normal",
            "\u521d\u7d1a": "Easy",
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_hand/config.gdc",),
        replacements={
            "\u64cd\u4f5c": "Controls",
            "\u30fb\u63e1\u624b:\u624b\u3092\u30af\u30ea\u30c3\u30af": "Shake: click hand",
            "\u30d2\u30f3\u30c8": "Hint",
            "\u30fb\u63e1\u624b\u3057\u3066\u307f\u3088\u3046\uff01": "Try shaking hands!",
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_minuki/config.gdc",),
        replacements={
            "\u64cd\u4f5c": "Controls",
            "\u30fb\u3061\u3093\u3061\u3093\u3092\u89e6\u308b:\u3061\u3093\u3061\u3093\u3092\u30af\u30ea\u30c3\u30af": (
                "Touch: click yourself"
            ),
            "\u30d2\u30f3\u30c8": "Hint",
            "\u30fb\u3061\u3093\u3061\u3093\u3092\u89e6\u3063\u3066\u3001\u898b\u629c\u304d\u3057\u3088\u3046!": (
                "Touch yourself and peek!"
            ),
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_minuki_hanyou/config.gdc",),
        replacements={
            "\u64cd\u4f5c": "Controls",
            "\u30fb\u30b7\u30b3\u308b:\u3061\u3093\u3061\u3093\u3092\u30af\u30ea\u30c3\u30af\n"
            "\u30fb\u30d1\u30f3\u30c4\u3092\u305a\u3089\u3059:\u30af\u30ea\u30c3\u30af\u2192\u4e0b\u306b\u30c9\u30e9\u30c3\u30b0": (
                "Stroke: click yourself\nMove panties: click, drag down"
            ),
            "\u30d2\u30f3\u30c8": "Hint",
            "\u30d1\u30f3\u30c4\u304c\u898b\u3048\u3066\u3044\u308b\u3068\u304d\u306b\u3001\u305a\u3089\u305b\u307e\u3059": (
                "You can move them when visible."
            ),
            "\u30fb\u3059\u307e\u305f:\u304a\u304b\u306a\u3092\u30af\u30ea\u30c3\u30af": "Grind: click belly",
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_hand/ticket_hand.gdc",),
        replacements={
            "\uff71\uff78\uff7c\uff6d\uff7c\uff83\uff78\uff80\uff9e\uff7b\uff72": (
                "Shake hands, please!"
            ),
            "\u63e1\u624b\u3057\u3066\u304f\u3060\u3055\u3044\uff01": "Please shake my hand!",
            "\u304d\u3083\u3042\u301c\u2665": "Kyaa~\u2665",
            "\u3054\u301c": "Five~",
            "\u3088\u301c\u3093": "Four~",
            "\u3055\u301c\u3093": "Three~",
            "\u306b\u301c": "Two~",
            "\u3044\u301c\u3061\u2665": "One~\u2665",
            "\u3054\u301c\u2665": "Five~\u2665",
            "\u3088\u301c\u3093\u2665": "Four~\u2665",
            "\u3055\u301c\u3093\u2665": "Three~\u2665",
            "\u306b\u301c\u2665": "Two~\u2665",
        },
    ),
    PatchSpec(
        files=("addons/osawari_toolkit/vfx/vfx_osawari_text.gdc",),
        replacements={
            "もみ": "Rub it",
            "むに": "Squish",
            "もみ\uf004": "Rub it\uf004",
            "なで": "Patpat",
            "なで\uf004": "Patpat\uf004",
            "しこ": "Stroke",
            "くちゅ": "Squelch",
            "ちゅこ": "Smooch",
            "ちゃっ\uf004": "Splat\uf004",
            "ずっ": "Slide!",
            "ずりっ": "Slide",
            "ぎゅっ": "Squeeze!",
            "にぎっ": "Grip!",
            "にぎ": "Grip",
            "ぎゅ": "Sqz",
            "にぎゅ\uf004": "Squeeze\uf004",
            "もふっ": "Fluff",
            "ふあっ": "Fwah",
            "ふわっ": "Soft",
            "ふり": "Waggle",
            "ふり\uf004": "Waggle\uf004",
            "ぷり": "Jiggle",
            "むみ": "Mmf",
            "むに\uf004": "Squish\uf004",
            "むにゅ": "Squoosh",
            "み": "Mm",
            "む": "Mmm",
            "むぎゅ": "Squish",
            "にゅ": "Nyu",
            "みゅ": "Myu",
            "みぃ": "Mii",
            "もち": "Soft",
            "にゃ": "Nya",
            "むにぃ": "Squish",
            "ちま": "Tiny",
            "ちゃ": "Chak",
            "ぽっ": "Pop",
            "ちゅ": "Chu",
            "にち": "Nch",
            "むちゃ": "Mucha",
            "ぬぽっ": "Npop",
            "ぬちゅ\uf004": "Nchu\uf004",
            "にゅ\uf004": "Nyu\uf004",
            "のぽ": "Nopo",
            "むわっ\uf004": "Mwah\uf004",
            "むわ\uf004": "Mwah\uf004",
            "むわぁ\uf004": "Mwaah\uf004",
            "かり\uf004": "Scratch\uf004",
            "すり\uf004": "Rub\uf004",
            "すり": "Rub it",
            "ちゅっ": "Smooch",
            "ちゅ\uf004": "Chu\uf004",
            "ぴちゃ": "Splash",
            "ぺちゃ": "Splash",
            "ちゃ\uf004": "Chak\uf004",
            "ぴと": "Press",
            "ぴた\uf004": "Press\uf004",
            "ぴと\uf004": "Press\uf004",
            "ぐっ\uf004": "Grip\uf004",
            "ぐぐっ\uf004": "Grip\uf004",
            "ぱ": "Pa",
            "ぱっ": "Pah",
            "ぶっ": "Buh",
            "ぼ": "Bo",
            "ごっ": "Thud",
            "っ\uf004": "Ah\uf004",
            "ぢゅ\uf004": "Jyu\uf004",
            "ご\uf004": "Thud\uf004",
            "ぢゅる\uf004": "Slurp\uf004",
            "じゅ": "Jyu",
            "じゅっ": "Jyu!",
            "ぷに": "Puni",
            "ぷに\uf004": "Puni\uf004",
            "ぎゅっ\uf004": "Squeeze\uf004",
            "くん…": "Sniff",
            "くん": "Sniff",
            "とろっ\uf004": "Melt\uf004",
            "びゅっ\uf004": "Spurt\uf004",
            "びゅるっ\uf004": "Spurt\uf004",
            "ぷしっ\uf004": "Pshh\uf004",
            "ぷしゃっ\uf004": "Splash\uf004",
            "がばっ\uf004": "Grab\uf004",
            "しゅっ": "Shff",
            "ちゃっ": "Chak",
            "しゃっ\uf004": "Shah\uf004",
            "くちゅ\uf004": "Squelch\uf004",
            "じゅ\uf004": "Jyu\uf004",
            "むちゃ\uf004": "Mucha\uf004",
            "ぱち": "Snap",
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_foot/ticket_foot.gdc",),
        replacements={
            "\u3054\u301c": "Five",
            "\u3088\u301c\u3093": "Four",
            "\u3055\u301c\u3093": "Three",
            "\u306b\u301c": "Two",
            "\u3044\u301c\u3061": "One",
            "\u3054\u301c\u2665": "Five!",
            "\u3088\u301c\u3093\u2665": "Four!",
            "\u3055\u301c\u3093\u2665": "Three!",
            "\u306b\u301c\u2665": "Two!",
            "\u3044\u301c\u3061\u2665": "One!",
            "わ〜♥": "Waaah~♥",
            "あ〜": "Ahhh~",
            "\u64cd\u4f5c": "Controls",
            "\u30fb\u8db3\u88cf:\u30af\u30ea\u30c3\u30af": "Soles: click",
            "\u30d2\u30f3\u30c8": "Hint",
            "\u8db3\u88cf\u309210\u56de\u63c9\u3080\u3068\u6b21\u306e\u30b7\u30ca\u30ea\u30aa\u3078": (
                "Massage soles 10 times to continue"
            ),
            "\u4e21\u8db3\u3092\u3082\u3093\u3067\u304b\u3089\u3001\u5408\u8a0810\u56de\u63c9\u3080\u3068\u6b21\u306e\u30b7\u30ca\u30ea\u30aa\u3078": (
                "Massage both feet, then 10 total to continue"
            ),
            "\u5408\u8a0810\u56de\u63c9\u3080\u3068\u7d42\u4e86": "10 total to finish",
            "\u8db3\u89e6\u3089\u305b\u3066\u304f\u3060\u3055\u3044": "Let me touch your feet",
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_tail/ticket_tail.gdc",),
        replacements={
            "[wave]わ♥[/wave]": "[wave]Wah♥[/wave]",
            "[wave]くすぐった〜[/wave]": "[wave]Tickles~[/wave]",
            "[wave]あはは〜♥[/wave]": "[wave]Ahaha~♥[/wave]",
            "[wave]ひら…ひら…[/wave]": "[wave]Flutter...[/wave]",
            "[wave]ひらり〜[/wave]": "[wave]Flutter~[/wave]",
            "ん〜?": "Hmm~?",
            "え〜♥ 尻尾かあ〜?": "Eh~♥ My tail~?",
            "あ♥": "Ah♥",
            "あ〜♥？": "Ahh~♥?",
            "なんかちがうような〜♥": "This feels different~♥",
            "え〜♥": "Eh~♥",
            "\u64cd\u4f5c": "Controls",
            "\u30d2\u30f3\u30c8": "Hint",
            "\n\t\u30fb\u5c3b\u5c3e\u3092\u89e6\u308b:\u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u670d\u3092\u305f\u304f\u3057\u4e0a\u3052\u308b:\u88fe\u3092\u4e0a\u306b\u30c9\u30e9\u30c3\u30b0\n"
            "\t": "\n\tTail: click\n\tLift clothes: drag hem up\n\t",
            "\n\t\u5c3b\u5c3e\u309210\u56de\u89e6\u308b\u3068\u30ea\u30a2\u30af\u30b7\u30e7\u30f3\u304c\u3042\u308a\u307e\u3059\u3002\n"
            "\t\u305d\u306e\u30ea\u30a2\u30af\u30b7\u30e7\u30f3\u5f8c\u670d\u3092\u305f\u304f\u3057\u4e0a\u3052\u308b\u3068\u6b21\u306e\u30b7\u30ca\u30ea\u30aa\u3078\n"
            "\t": (
                "\n\tTouch tail 10 times for a reaction.\n"
                "\tAfter that reaction, lift the clothes to continue.\n"
                "\t"
            ),
            "\n\t\u30fb\u670d\u3092\u623b\u3059:\u88fe\u3092\u4e0b\u306b\u30c9\u30e9\u30c3\u30b0\n\t": (
                "\n\tReturn clothes: drag hem down\n\t"
            ),
            "\u670d\u3092\u3082\u3068\u306b\u623b\u3059\u3068\u6b21\u306e\u30b7\u30ca\u30ea\u30aa\u3078": (
                "Return clothes to continue"
            ),
            "\n\t\u30fb\u670d\u3092\u305f\u304f\u3057\u4e0a\u3052\u308b:\u88fe\u3092\u4e0a\u306b\u30c9\u30e9\u30c3\u30b0\n\t": (
                "\n\tLift clothes: drag hem up\n\t"
            ),
            "\u670d\u3092\u9650\u754c\u307e\u3067\u305f\u304f\u3057\u4e0a\u3052\u308b\u3068\u6b21\u306e\u30b7\u30ca\u30ea\u30aa\u3078": (
                "Lift clothes fully to continue"
            ),
            "\n\t\u30fb\u5c3b\u5c3e\u3092\u89e6\u308b:\u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u304a\u3057\u308a\u3092\u63c9\u3080:\u30af\u30ea\u30c3\u30af/\u30c9\u30e9\u30c3\u30b0\n"
            "\t": "\n\tTail: click\n\tButt: click/drag\n\t",
            "\n\t\u5c3b\u5c3e\u309210\u56de\u89e6\u308b\u3068\u7d42\u4e86\n\t": "\n\tTouch tail 10 times to finish\n\t",
            "\u5c3b\u5c3e\u89e6\u3089\u305b\u3066\u304f\u3060\u3055\u3044": "Let me touch your tail",
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_breath/ticket_breath.gdc",),
        replacements={
            "むに〜?": "Squishy~?",
            "わ〜♥": "Waaah~♥",
            "む♥": "Mmm♥",
            "む〜♥": "Mmmm~♥!",
            "は〜わ♥": "Haaah~♥",
            "は〜あいお♥": "Haaah...♥",
            "おあいは♥": "Mwaah♥",
            "[tornado]あぇ♥？[/tornado]": "[tornado]Aeh♥?[/tornado]",
            "[tornado]えあぁ〜♥?[/tornado]": "[tornado]Eaaah~♥?[/tornado]",
            "[tornado]へっ♥?[/tornado]": "[tornado]Heh♥?[/tornado]",
            "[tornado]えあ♥?[/tornado]": "[tornado]Eah♥?[/tornado]",
            "[tornado]へぁ♥[/tornado]": "[tornado]Hea♥[/tornado]",
            "[tornado]はほ♥[/tornado]": "[tornado]Haho♥[/tornado]",
            "[tornado]はえあ♥[/tornado]": "[tornado]Haea♥[/tornado]",
            "[tornado]えあ♥[/tornado]": "[tornado]Eah♥[/tornado]",
            "[tornado]ほほ〜[/tornado]": "[tornado]Hoho~[/tornado]",
            "[tornado]はははいへふほ♥[/tornado]": "[tornado]Hahaha...♥[/tornado]",
            "[tornado]ぇ♥?[/tornado]": "[tornado]Eh♥?[/tornado]",
            "[tornado]えぁ♥[/tornado]": "[tornado]Eah♥[/tornado]",
            "[tornado]あ♥[/tornado]": "[tornado]Ah♥[/tornado]",
            "[tornado]え♥[/tornado]": "[tornado]Eh♥[/tornado]",
            "[tornado]えぁ〜♥?[/tornado]": "[tornado]Eah~♥?[/tornado]",
            "\u64cd\u4f5c": "Controls",
            "\u64cd\u4f5c1": "Ctrl 1",
            "\u64cd\u4f5c2": "Ctrl 2",
            "\u30d2\u30f3\u30c8": "Hint",
            "\n\t\u30fb\u982c\u3092\u89e6\u308b:\u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u982c\u3092\u5f15\u3063\u5f35\u308b:\u30c9\u30e9\u30c3\u30b0\n"
            "\t\u30fb\u982d\u3092\u64ab\u3067\u308b:\u30af\u30ea\u30c3\u30af\n\t": (
                "\n\tCheeks: click\n\tPull cheeks: drag\n\tPat head: click\n\t"
            ),
            "\u307b\u3063\u307a\u305f\u309210\u56de\u63c9\u3080\u3068\u6b21\u306e\u30b7\u30ca\u30ea\u30aa\u3078": (
                "Rub cheeks 10 times to continue"
            ),
            "\n\t\u30fb\u5507\u3092\u89e6\u308b: \u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u53e3\u306b\u6307\u3092\u5165\u308c\u308b:\u30c9\u30e9\u30c3\u30b0\n"
            "\t\u30fb\u982c\u3092\u89e6\u308b:\u982c\u3092\u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u982c\u3092\u5f15\u3063\u5f35\u308b:\u982c\u3092\u4e0b\u306b\u30c9\u30e9\u30c3\u30b0\n"
            "\t\u30fb\u982d\u3092\u64ab\u3067\u308b:\u982d\u3092\u30af\u30ea\u30c3\u30af\n\t": (
                "\n\tLips: click\n\tPut finger in mouth: drag\n"
                "\tCheeks: click cheeks\n\tPull cheeks: drag cheeks down\n"
                "\tPat head: click head\n\t"
            ),
            "\u6307\u3092\u5165\u308c\u308b\u3068\u6b21\u306e\u30b7\u30ca\u30ea\u30aa\u3078": "Insert finger to continue",
            "\n\t\u30fb\u5507\uff1f\u3092\u89e6\u308b: \u6307\u3092\u5965\u307e\u3067\u5165\u308c\u3066\u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u53e3\u306b\u6307\u3092\u5165\u308c\u308b:\u30c9\u30e9\u30c3\u30b0\n"
            "\t\u30fb\u982c\u3092\u89e6\u308b:\u982c\u3092\u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u982c\u3092\u5f15\u3063\u5f35\u308b:\u982c\u3092\u4e0b\u306b\u30c9\u30e9\u30c3\u30b0\n"
            "\t\u30fb\u982d\u3092\u64ab\u3067\u308b:\u982d\u3092\u30af\u30ea\u30c3\u30af\n\t": (
                "\n\tLips?: insert finger fully, then click\n"
                "\tPut finger in mouth: drag\n\tCheeks: click cheeks\n"
                "\tPull cheeks: drag cheeks down\n\tPat head: click head\n\t"
            ),
            "10\u56de\u5507?\u3092\u89e6\u308b\u3068\u6b21\u306e\u30b7\u30ca\u30ea\u30aa\u3078": (
                "Touch lips? 10 times to continue"
            ),
            "\n\t\u30fb\u524d\u6b6f\u3092\u89e6\u308b:\u30af\u30ea\u30c3\u30af (\u524d\u6b6f\u304c\u898b\u3048\u3066\u3044\u308b\u3068\u304d\u3060\u3051)\n"
            "\t\u30fb\u820c\u3092\u89e6\u308b: \u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u6307\u3092\u5165\u308c\u308b: \u53e3\u306e\u5de6\u53f3\u3092\u30af\u30ea\u30c3\u30af\u3057\u3066\u30c9\u30e9\u30c3\u30b0\n"
            "\t\u30fb\u820c\u3092\u5f15\u3063\u5f35\u308b: \u53e3\u3092\u5e83\u3052\u305f\u72b6\u614b\u3067\u820c\u5148\u3092\u30af\u30ea\u30c3\u30af\u3057\u3066\u30c9\u30e9\u30c3\u30b0\n\t": (
                "\n\tFront teeth: click when visible\n\tTongue: click\n"
                "\tInsert finger: click mouth sides and drag\n"
                "\tPull tongue: open mouth, click tongue tip and drag\n\t"
            ),
            "\n\t\u30fb\u982c\u3092\u89e6\u308b:\u982c\u3092\u30af\u30ea\u30c3\u30af\n"
            "\t\u30fb\u982c\u3092\u5f15\u3063\u5f35\u308b:\u982c\u3092\u4e0b\u306b\u30c9\u30e9\u30c3\u30b0\n"
            "\t\u30fb\u982d\u3092\u64ab\u3067\u308b:\u982d\u3092\u30af\u30ea\u30c3\u30af\n\t": (
                "\n\tCheeks: click cheeks\n"
                "\tPull cheeks: drag cheeks down\n"
                "\tPat head: click head\n\t"
            ),
            "\n\t10\u56de\u524d\u6b6f\u3092\u89e6\u308b\u3068\u7d42\u4e86\n"
            "\t\u524d\u6b6f\u306f\u53e3\u306b\u6307\u3092\u5165\u308c\u3066\u3044\u305f\u308a\u3059\u308b\u3068\u89e6\u308c\u306a\u3044\u306e\u3067\u3001\u982d\u3092\u64ab\u3067\u305f\u308a\u982c\u3092\u89e6\u3063\u305f\u308a\u3057\u3066\u9732\u51fa\u3055\u305b\u3066\u304f\u3060\u3055\u3044\u3002\n\t": (
                "\n\tTouch front teeth 10 times to finish.\n"
                "\tIf fingers block them, pat head or touch cheeks to reveal them.\n\t"
            ),
            "\u307b\u3063\u307a\u89e6\u3089\u305b\u3066\u304f\u3060\u3055\u3044!!!": "Let me touch your cheeks!!!",
            "\u307b\u3063\u307a\u3063\u3066\u2665 \u666e\u901a\u3058\u3083\u3093\u2665!!!!": (
                "Cheeks are just normal!!!!"
            ),
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_minuki/ticket_minuki.gdc",),
        replacements={
            "[wave]きゃ〜♥[/wave]": "[wave]Kyaa~♥[/wave]",
            "そんなふうにやるんだ〜♥": "So that's how~♥",
            "なんかおっきくなってきた〜?": "Getting bigger~?",
            "くんくん…": "Sniff sniff...",
            "へんなにおい〜♥": "Weird smell~♥",
            "くちゃ くちゃい♥": "So stinky...♥",
            "でる?♥ でる?♥": "Coming?♥ Coming?♥",
            "みるだけでいいの〜?": "Just watching~?",
            "なんか我慢してますか~?": "Holding back~?",
            "\uff81\uff9d\uff81\uff9d\u3060\u3055\u305b\u3066\u304f\u3060\u3055\u3044!": (
                "Please let me take it out!"
            ),
            "\u3061\u3093\u3061\u3093\u3092\u51fa\u3059": "Take it out",
            "なんかあついな〜♥": "Getting hot~♥",
            "ちら〜♥": "Peek~♥!",
        },
    ),
    PatchSpec(
        files=("assets/osawari/ticket_minuki_hanyou/ticket_minuki_hanyou.gdc",),
        replacements={
            "もっとおっきくしろ〜♥": "Get bigger~♥",
            "くちゃ♥ くちゃ〜い♥": "Stinky♥ So stinky~♥",
            "すごいおと〜♥": "What a sound~♥",
            "でる?♥ でる?♥": "Coming?♥ Coming?♥",
            "これほんとにミヌキ〜♥?": "Is this really peeking~♥?",
            "なにしてる〜♥": "What are you doing~♥?",
            "なんか〜あたってるような〜♥？": "Feels like it's touching~♥?",
            "あちゅ♥": "H-hot~♥!",
            "あっ♥": "Ahhh~♥",
            "ああ♥": "Aahh~♥",
            "めっちゃぎゅーしてくる〜♥": "You're squeezing so much~♥",
            "でる〜?♥ でるよね〜♥": "Coming~?♥ You are~♥",
            "だせ〜♥": "Come now~♥",
            "ああ♥♥♥": "Aah♥♥♥",
            "なんか〜音がちがう〜♥？": "That sound is different~♥?",
            "おなじだろ~♥ あ♥": "It's the same~♥ Ah♥",
            "はやっ♥はやっ♥": "So fast♥ So fast♥",
            "へっ♥": "Eh♥",
            "しゅご〜♥": "Amazing~♥",
            "あちゅ♥あっちゅい♥": "Hot♥ So hot♥",
            "だせ♥だしぇ♥": "Come♥ Come on♥",
            "え〜♥??": "Huh~♥??",
        },
    ),
    PatchSpec(
        files=("assets/osawari/goal/goal.gdc",),
        replacements={
            "\u306f\u3063\u2026 \u306f\u3063\u2026": "Haah... Haah...",
            "\u3082\u3063\u3068\uf004": "More\uf004",
            "\u306f\u3063\u2026 \u306f\u3063\u2026 \u306f\u3063\u2026": "Haah... Haah... Haah...",
            "\u305d\u3054\u3063\uf004 ": "There\uf004 ",
            "\u3082\u3063\u3068\u3053\u3057\u3075\u3063\u3066\uf004 \u3075\u3063\u3066\uf004": "Move your hips\uf004 More\uf004",
            "\u3078\u3063\uf004\u3078\u3063\uf004": "Heh\uf004Heh\uf004",
            "\u3042\u3063\uf004 \u3042\u3063\uf004": "Ah\uf004 Ah\uf004",
            "\u3042\u301c\uf004\n\u306a\u3093\u304b\u3067\u3063\u304b\u301c\uf004": "Ahh\uf004\nIt's huge\uf004",
            "\u306a\u3093\u304b\u301c\u3079\u3061\u3083\u3079\u3061\u3083\u301c\uf004": "It's so wet\uf004",
            "\u305d\u3054\u3063\uf004 \u304a\u3050\u304e\u3082\u3062\uf004": "There\uf004 so deep\uf004",
            "\u3082\u3063\u3068\uf004 \u304c\u3093\u3070\u308c\uf004": "More\uf004 keep going\uf004",
            "\u306f\u3063\u2026 \u3078\u3063\uf004 \u3078\u3063\uf004\n\u3060\u3058\u3067\u3063\uf004": "Haah... heh\uf004 heh\uf004\nCome on\uf004",
            "\u3042\u3063\uf004 \u3078\u3063\uf004": "Ah\uf004 heh\uf004",
            "\u3042\u301c\uf004\n\u307e\u305f\u304a\u3063\u304d\u304f\u306a\u3063\u305f\uf004": "Ahh\uf004\nIt got bigger\uf004",
            "\u3075\u308c\u3063\uf004 \u3075\u308c\u3063\uf004": "Move\uf004 move\uf004",
            "\u304e\u3082\u3063\uf004 \u304a\u3050\uf004 \n\u304e\u3082\u3062\u3063\u2026": "Feels\uf004 deep\uf004 \nSo good...",
            "\u305d\u3054\u3063\uf004 \u3078\u3063\uf004": "There\uf004 heh\uf004",
            "\u3082\u3063\u3068\u3053\u3057\u3075\u308c\uf004 \u3075\u308c\u3063\uf004": "Move your hips\uf004 more\uf004",
            "\u306a\u304c \u3044\u304e\u3063\u2026 \u3050\uf004": "So big... ngh\uf004",
            "\u3078\u3063\uf004 \u3060\u305b\u3063\uf004\n \u3044\u3063\u3071\u3044\u3060\u305b\u3063\uf004": "Heh\uf004 let it out\uf004\n all of it\uf004",
            "\u51fa\u305b\u3063\uf004 \u51fa\u305b\u3063\uf004": "Come\uf004 Come\uf004",
            "\u51fa\u305b\u3063\uf004 \u51fa\u305b\u3063\uf004 \u3055\u3044\u3054\u3063\uf004": "Come\uf004 Come\uf004 Last\uf004",
            "\u3061\u3085\u3043\uf004 \u3053\u3047\u3061\u3085\u3044\uf004": "Chu\uf004 kiss me\uf004",
            "\u3047\uf004 \u3041\u3048\u3063\uf004 \u3061\u3085\u304d\uf004": "Eh\uf004 ah\uf004 love\uf004",
            "\u3047\u3063\uf004\u3047\u3042\uf004 ": "Eh\uf004Ah\uf004 ",
            "\u3061\u3085\u304d\uf004 \u3061\u3085\u304d\u3063\uf004": "Love\uf004 love\uf004",
            "\u3060\u3061\u3047\u3063\uf004 \u3060\u3061\u3047\u3063\uf004": "Do it\uf004 do it\uf004",
            "\u3047\u3042!?": "Eh!?",
            "\u3063\u306b\u3083\uf004": "Nya\uf004",
            "\u3061\u3001\u3061\u3050\u3073\u3059\u304d\u2026": "N-nipples...",
            "\u3042\u3063\uf004 \u3061\u304f\u3073\uf004": "Ah\uf004 nipples\uf004",
            "\u3062\u3050\u3001\u3061\u3050\u3073\u3057\u3085\u304d\u2026": "Ngh, love nipples...",
            "\u3061\u3050\u3073\u3063\uf004 \u3059\u304d\u3063\uf004": "Nipples\uf004 love\uf004",
            "\u3062\u3050\u3001\u3061\u3050\u3073\u3086\u308b\u3058\u3066\u2026": "Ngh, forgive me...",
            "\u3062\u3050\u3073\u3044\u30b0\uf004\uf004": "Nip climax\uf004\uf004",
            "[shake]\u3041\u3042\u309b\uf004\uf004\uf004\uf004[/shake]": "[shake]Aaah\uf004\uf004\uf004\uf004[/shake]",
            "\u3062\u3050\u3073\u3044\u304e\u3085\uf004\uf004": "Nip squeeze\uf004\uf004",
            "[shake]\u3044\u3050\uf004\uf004\uf004[/shake]": "[shake]Ngh\uf004\uf004\uf004[/shake]",
            "[shake]\u30a3\u3050\uf004\uf004\uf004\uf004\uf004\uf004\uf004[/shake]": "[shake]Ngh\uf004\uf004\uf004\uf004\uf004\uf004\uf004[/shake]",
            "[shake]\u2026\u3050\u3063 \u3085\u308b\u3058\u3067\uf004\uf004\uf004\uf004\uf004\uf004[/shake]": (
                "[shake]Ngh... forgive me\uf004\uf004\uf004\uf004\uf004\uf004[/shake]"
            ),
            "[shake]\u3050\uf004\uf004\uf004\uf004[/shake]": "[shake]Ngh\uf004\uf004\uf004\uf004[/shake]",
            "\u64cd\u4f5c": "Controls",
            "\u30d2\u30f3\u30c8": "Hint",
            "\u30fb\u3061\u3093\u3061\u3093\u3092\u633f\u5165\u3059\u308b:\u3061\u3093\u3061\u3093\u3092\u4e0a\u306b\u30c9\u30e9\u30c3\u30b0": (
                "Insert: drag yourself up"
            ),
            "\u30fb\u3061\u3093\u3061\u3093\u3092\u633f\u308c\u3088\u3046!": "Try inserting!",
            "\u30fb\u3061\u3093\u3061\u3093\u3092\u52d5\u304b\u3059:\u3061\u3093\u3061\u3093\u3092\u30af\u30ea\u30c3\u30af\n"
            "\u30fb\u4e73\u9996\u3092\u3064\u307e\u3080:\u4e73\u9996\u3092\u30af\u30ea\u30c3\u30af": (
                "Move: click yourself\nPinch nipples: click nipples"
            ),
            "\u30fb\u9650\u754c\u307e\u3067\u5c04\u7cbe\u3057\u3088\u3046!!": "Keep going to the limit!!",
            "\u30fb\u30ad\u30b9\u3092\u3057\u306a\u304c\u3089\u3061\u3093\u3061\u3093\u3067\u7a81\u304f:\u820c\u3092\u30af\u30ea\u30c3\u30af": (
                "Thrust while kissing: click tongue"
            ),
        },
    ),
    PatchSpec(
        files=("assets/osawari/sleep_day/config.gdc",),
        replacements={
            "\u521d\u7d1a": "Easy",
            "\u4e2d\u7d1a": "Normal",
            "\u4e0a\u7d1a": "Hard",
            "\u64cd\u4f5c": "Controls",
            "\n\t\t\u30fb\u982d\u3092\u64ab\u3067\u308b\n"
            "\t\t\u30fb\u4e0a\u7740\u3092\u8131\u304c\u3059(\u7d10:\u30af\u30ea\u30c3\u30af \u8131\u8863:\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u30d1\u30f3\u30c4\u3092\u898b\u308b(\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u3075\u3068\u3082\u3082\u898b\u629c\u304d\u2665\n"
            "\t\t": (
                "\n\t\t- Pat head\n"
                "\t\t- Remove jacket: click strings, drag clothes\n"
                "\t\t- View panties: drag\n"
                "\t\t- Thigh peeking\n"
                "\t\t"
            ),
            "\n\t\t\u30fb\u80f8\u3081\u304f\u308a\n"
            "\t\t\u30fb\u3061\u3085\u30fc\n"
            "\t\t\u30fb\u307e\u3093\u3077\u306b\n"
            "\t\t\u30fb\u9854\u898b\u629c\u304d(\u3061\u3093\u304b\u304e)\u2665\n"
            "\t\t": (
                "\n\t\t- Lift top\n"
                "\t\t- Kiss\n"
                "\t\t- Touch lower body\n"
                "\t\t- Face peeking\n"
                "\t\t"
            ),
            "\n\t\t\u30fb\u5168\u90e8\u8131\u304c\u3059\n"
            "\t\t\u30fb\u4e73\u9996\u3092\u3064\u307e\u3080\n"
            "\t\t\u30fb\u4e73\u9996\u898b\u629c\u304d\u2665\n"
            "\t\t": (
                "\n\t\t- Undress fully\n"
                "\t\t- Touch nipples\n"
                "\t\t- Nipple peeking\n"
                "\t\t"
            ),
            "\n\t\t\u5bfe\u8c61\u90e8\u4f4d\u3092\u30af\u30ea\u30c3\u30af\u3001\u3082\u3057\u304f\u306f\u30c9\u30e9\u30c3\u30b0\u3067\u64cd\u4f5c\u3057\u307e\u3059\u3002\n"
            "\t\t\u3061\u3093\u3061\u3093: \u30c9\u30e9\u30c3\u30b0\u3057\u3066\u3001\u5bfe\u8c61\u90e8\u4f4d(\u2665)\u306b\u30a2\u30b5\u30a4\u30f3\u3067\u304d\u307e\u3059\u3002\u30a2\u30b5\u30a4\u30f3\u72b6\u614b\u306e\u3061\u3093\u3061\u3093\u3092\u30af\u30ea\u30c3\u30af\u3067\u64cd\u4f5c\u3067\u304d\u307e\u3059\n"
            "\t\t": (
                "\n\t\tClick or drag target areas to interact.\n"
                "\t\tDrag yourself onto a target marked with a heart, then click to act.\n"
                "\t\t"
            ),
        },
    ),
    PatchSpec(
        files=("assets/osawari/sleep_night_on_back/config.gdc",),
        replacements={
            "\u521d\u7d1a": "Easy",
            "\u4e2d\u7d1a": "Normal",
            "\u4e0a\u7d1a": "Hard",
            "\u64cd\u4f5c": "Controls",
            "\n\t\t\u30fb\u982d\u3092\u64ab\u3067\u308b\n"
            "\t\t\u30fb\u5e03\u56e3\u3092\u305a\u3089\u3059\n"
            "\t\t\u30fb\u670d\u3092\u305a\u3089\u3059(\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u3061\u3085\n"
            "\t\t\u30fb\u9854\u898b\u629c\u304d\u2665\n"
            "\t\t\u30fb\u3061\u3093\u304b\u304e\u898b\u629c\u304d\u2665\n"
            "\t\t": (
                "\n\t\t- Pat head\n"
                "\t\t- Move blanket\n"
                "\t\t- Shift clothes: drag\n"
                "\t\t- Kiss\n"
                "\t\t- Face peeking\n"
                "\t\t- Close-up peeking\n"
                "\t\t"
            ),
            "\n\t\t\u30fb\u4e0b\u7740(\u80f8/\u30d1\u30f3\u30c4)\u3092\u305a\u3089\u3059(\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u4e73\u9996\u3059\u308a\u3059\u308a(\u30af\u30ea\u30c3\u30af)\n"
            "\t\t\u30fb\u4e73\u9996\u304e\u3085(\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u4e73\u9996\u898b\u629c\u304d\u2665\n"
            "\t\t\u30fb\u30af\u30ea\u3044\u3058\u3081\n"
            "\t\t": (
                "\n\t\t- Shift underwear: drag\n"
                "\t\t- Rub nipples: click\n"
                "\t\t- Pinch nipples: drag\n"
                "\t\t- Nipple peeking\n"
                "\t\t- Tease lower body\n"
                "\t\t"
            ),
            "\n\t\t\u30fb\u670d\u3092\u8131\u304c\u3059(\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u30c7\u30a3\u30fc\u30d7\u30ad\u30b9(\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u811a\u3092\u958b\u304f(\u30d1\u30f3\u30c4\u3092\u8131\u304c\u3057\u3066\u811a\u3092\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u307e\u3093\u3077\u306b(\u30af\u30ea\u30c3\u30af)\n"
            "\t\t\u30fb\u307e\u3093\u6307\u5165\u308c(\u30c9\u30e9\u30c3\u30b0)\n"
            "\t\t\u30fb\u304a\u306a\u304b\u898b\u629c\u304d\u2665\n"
            "\t\t\u30fb\u3048\u3063\u3061\u2665\n"
            "\t\t": (
                "\n\t\t- Remove clothes: drag\n"
                "\t\t- Deep kiss: drag\n"
                "\t\t- Spread legs: remove panties, drag legs\n"
                "\t\t- Touch lower body: click\n"
                "\t\t- Insert fingers: drag\n"
                "\t\t- Belly peeking\n"
                "\t\t- Intimacy\n"
                "\t\t"
            ),
            "\n\t\t\u5bfe\u8c61\u90e8\u4f4d\u3092\u30af\u30ea\u30c3\u30af\u3001\u3082\u3057\u304f\u306f\u30c9\u30e9\u30c3\u30b0\u3067\u64cd\u4f5c\u3057\u307e\u3059\u3002\n"
            "\t\t\u3061\u3093\u3061\u3093: \u30c9\u30e9\u30c3\u30b0\u3057\u3066\u3001\u5bfe\u8c61\u90e8\u4f4d(\u2665)\u306b\u30a2\u30b5\u30a4\u30f3\u3067\u304d\u307e\u3059\u3002\u30a2\u30b5\u30a4\u30f3\u72b6\u614b\u306e\u3061\u3093\u3061\u3093\u3092\u30af\u30ea\u30c3\u30af\u3067\u64cd\u4f5c\u3067\u304d\u307e\u3059\n"
            "\t\t": (
                "\n\t\tClick or drag target areas to interact.\n"
                "\t\tDrag yourself onto a target marked with a heart, then click to act.\n"
                "\t\t"
            ),
        },
    ),
    PatchSpec(
        files=("presentation/common/osawari/novel/base_novel_content.gdc",),
        replacements={
            "\u3084\u3081\u308b (Debug)": "Quit (Debug)",
            "\u2026\uff1f?.\u3000 ": "...??.  ",
        },
    ),
    PatchSpec(
        files=("presentation/common/scenario/dialogue_panel.gdc",),
        replacements={
            "\u81ea\u5206": "Me",
        },
    ),
    PatchSpec(
        files=("presentation/ingame/views/home/battle/result_panel.gdc",),
        replacements={
            "\u52dd\u5229!": "Win!",
            "\u6557\u5317...": "Lost...",
            "\u4f55\u3082\u7372\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f...": (
                "No rewards gained..."
            ),
        },
    ),
    PatchSpec(
        files=("presentation/ingame/views/home/home_view.gdc",),
        replacements={
            "\u591c\u3001\u3078\u3084\u306b\u884c\u3063\u3066\n"
            "\u3068\u3063\u3066\u304a\u304d\u306e\u5c0f\u74f6\u3092\u4f7f\u304a\u3046!!": (
                "Night: use vial in room!!"
            ),
            "\u591c\u3001\u3078\u3084\u306b\u884c\u3063\u3066\u30ab\u30ae\u3092\u8fd4\u305d\u3046!!": (
                "Night: return the key!!"
            ),
            "\u591c\u3001\u3078\u3084\u306b\u884c\u3063\u3066\u898b\u629c\u304d\u3055\u305b\u3066\u3082\u3089\u304a\u3046!!": (
                "Night: ask to peek!!"
            ),
            "\u591c\u3001\u3078\u3084\u306b\u884c\u3053\u3046!!": "Go to room tonight!!",
        },
    ),
    PatchSpec(
        files=("presentation/ingame/views/home/kintama_panel.gdc",),
        replacements={
            "%d\u500b": "%d pc",
        },
    ),
    PatchSpec(
        files=("presentation/ingame/views/home/shop/shop_display_test.gdc",),
        replacements={
            "\u30a2\u30a4\u30c6\u30e0\u304c\u3042\u308a\u307e\u305b\u3093": "No items.",
            "[b]\u30d2\u30f3\u30c8[/b]\\n%s\\n\\n[b]\u8aac\u660e[/b]\\n%s": (
                "[b]Hint[/b]\\n%s\\n\\n[b]Info[/b]\\n%s"
            ),
        },
    ),
    PatchSpec(
        files=("presentation/ingame/views/home/user_action_hint_panel.gdc",),
        replacements={
            "\u5c31\u5bdd\u3057\u3066\u7fcc\u65e5\u306e\u671d\u3092\u8fce\u3048\u307e\u3059": (
                "Sleep until morning"
            ),
            "\u30af\u30a8\u30b9\u30c8\u9078\u629e\u753b\u9762\u3092\u958b\u304d\u307e\u3059": (
                "Open quest select"
            ),
            "\u7279\u306b\u4f55\u3082\u305b\u305a\u3001\u6642\u9593\u3092\u9032\u3081\u307e\u3059": (
                "Pass time"
            ),
            "\u9053\u5177\u5c4b\u3055\u3093\u306e\u3072\u307f\u3064\u3092\u95b2\u89a7\u3057\u307e\u3059": (
                "View secrets"
            ),
            "\u9053\u5177\u5c4b\u3055\u3093\u306e\u304a\u3046\u3061\u3092\u8a2a\u306d\u307e\u3059\u2026": (
                "Visit her home..."
            ),
            "\u9053\u5177\u5c4b\u3055\u3093\u304b\u3089\u30a2\u30a4\u30c6\u30e0\u3092\u8cfc\u5165\u3057\u307e\u3059": (
                "Buy items from the shopkeeper"
            ),
            "\u9053\u5177\u5c4b\u3055\u3093\u306b\u30e2\u30f3\u30b9\u30bf\u30fc\u306e\u7d20\u6750\u3092\u58f2\u5374\u3057\u307e\u3059": (
                "Sell monster materials"
            ),
            "\u2026\u2026\uff1f": "...",
            "1F\u306b\u623b\u308a\u307e\u3059": "Back to 1F",
        },
    ),
)


def align4(value: int) -> int:
    return (value + 3) & ~3


def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def build_patch_map() -> dict[str, dict[str, str]]:
    patch_map: dict[str, dict[str, str]] = {}
    for spec in PATCH_SPECS:
        for file_name in spec.files:
            patch_map.setdefault(normalize_rel(file_name), {}).update(spec.replacements)
    return patch_map


def decompress_gdc(data: bytes) -> bytes:
    if data[:4] != GDSC_MAGIC:
        raise ValueError("not a GDSC file")
    if data[12:16] != ZSTD_MAGIC:
        raise ValueError("GDSC payload is not zstd-compressed")
    expected_size = struct.unpack_from("<I", data, 8)[0]
    payload = zstd.ZstdDecompressor().decompress(data[12:])
    if len(payload) != expected_size:
        raise ValueError(f"unexpected decompressed size: {len(payload)} != {expected_size}")
    return payload


def compress_gdc(original: bytes, payload: bytes) -> bytes:
    header = bytearray(original[:12])
    struct.pack_into("<I", header, 8, len(payload))
    compressed = zstd.ZstdCompressor(level=3, write_content_size=True).compress(payload)
    return bytes(header) + compressed


def is_serialized_string_at(data: bytes, text_offset: int, byte_length: int) -> bool:
    if text_offset < 8:
        return False
    declared_length = struct.unpack_from("<I", data, text_offset - 4)[0]
    if declared_length != byte_length:
        return False

    raw_type = struct.unpack_from("<I", data, text_offset - 8)[0]
    base_type = raw_type & 0xFFFF
    return base_type in {4, 21}


def patch_serialized_strings(payload: bytes, replacements: dict[str, str]) -> tuple[bytes, list[dict[str, object]]]:
    patched = bytearray(payload)
    changes: list[dict[str, object]] = []

    for source, replacement in replacements.items():
        source_bytes = source.encode("utf-8")
        replacement_bytes = replacement.encode("utf-8")
        capacity = align4(len(source_bytes))
        if align4(len(replacement_bytes)) > capacity:
            raise ValueError(f"replacement does not fit in-place: {source!r} -> {replacement!r}")

        offset = 0
        while True:
            found = patched.find(source_bytes, offset)
            if found < 0:
                break
            offset = found + 1
            if not is_serialized_string_at(patched, found, len(source_bytes)):
                continue

            if align4(len(replacement_bytes)) == capacity:
                declared_length = len(replacement_bytes)
                serialized = replacement_bytes + (b"\x00" * (capacity - len(replacement_bytes)))
            elif len(replacement_bytes) <= len(source_bytes):
                declared_length = len(source_bytes)
                serialized = replacement_bytes + (b" " * (len(source_bytes) - len(replacement_bytes)))
                serialized += b"\x00" * (capacity - len(serialized))
            else:
                raise ValueError(f"replacement cannot be padded in-place: {source!r} -> {replacement!r}")

            struct.pack_into("<I", patched, found - 4, declared_length)
            patched[found : found + capacity] = serialized
            changes.append(
                {
                    "from": source,
                    "to": replacement,
                    "offset": found,
                    "declared_length": declared_length,
                    "capacity": capacity,
                }
            )
            offset = found + capacity

    return bytes(patched), changes


def patch_gdc_file(source_path: Path, output_path: Path, replacements: dict[str, str]) -> list[dict[str, object]]:
    original = source_path.read_bytes()
    payload = decompress_gdc(original)
    patched_payload, changes = patch_serialized_strings(payload, replacements)
    if not changes:
        return []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(compress_gdc(original, patched_payload))
    return changes


def patch_tree(source_root: Path, output_root: Path) -> dict[str, object]:
    patch_map = build_patch_map()
    files: list[dict[str, object]] = []
    replacement_count = 0

    for rel_file, replacements in sorted(patch_map.items()):
        source_path = source_root / Path(rel_file)
        if not source_path.exists():
            raise FileNotFoundError(f"Missing source GDC: {source_path}")
        output_path = output_root / Path(rel_file)
        changes = patch_gdc_file(source_path, output_path, replacements)
        if changes:
            files.append({"file": rel_file, "changes": changes})
            replacement_count += len(changes)

    return {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "files_changed": len(files),
        "replacements": replacement_count,
        "files": files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patch visible Japanese constants inside .gdc bytecode.")
    parser.add_argument("--source-root", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = patch_tree(args.source_root, args.output_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("GDC files changed:", report["files_changed"])
    print("GDC replacements:", report["replacements"])
    print("Report:", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
