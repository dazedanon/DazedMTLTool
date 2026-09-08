# -*- coding: utf-8 -*-
"""Per-image typesetting of the English translations onto the Qwen-cleaned
plates, placed in the rectangles drawn in the mask tool.

Each function builds one image; run `python scripts/typeset_all.py [names...]`.
Terminology follows the user's collages: Blood Points, Tickets, Charms,
Death Deadline, Offering Box, Well, Interest, Restock Button, etc.
"""
import sys
from tlib import Plate, BODY, WHITE, PINK, HOTPINK, RED, GOLD, CYAN, GREEN

ORANGE = (242, 140, 64)
TEAL = (120, 210, 220)


def t02(p):
    # box0 left paragraph, box1 right paragraph
    p.block(p.rect(0),
            ["This room's unique currency.",
             "To escape the room, your goal is",
             "to spin the slots and earn it."],
            color=BODY, highlights={"spin the slots": PINK}, max_size=40)
    p.block(p.rect(1),
            ['Used at the store to buy "Charms"',
             "that help you progress."],
            color=BODY, highlights={'"Charms"': PINK}, max_size=40)


def t01(p):
    # 0 KEYBOARD, 1 Open Settings Screen, 2 Move, 3 Dash, 4 MOUSE, 5 Zoom
    p.block(p.rect(0), ["KEYBOARD"], color=HOTPINK, align="left", max_size=30,
            style="b", tracking=3, valign="center")
    p.block(p.rect(1), ["Open Settings Screen"], color=HOTPINK, align="left", max_size=40)
    # Move + Dash: left-align both at the same x so Dash lines up under Move
    mx = p.rect(2)[0]
    p.block(p.rect(2), ["Move"], color=WHITE, max_size=50, glow=True, align="left")
    db = p.rect(3)
    p.block([mx, db[1], db[2], db[3]], ["Dash"], color=WHITE, max_size=50,
            glow=True, align="left")
    p.block(p.rect(4), ["MOUSE"], color=HOTPINK, align="left", max_size=30,
            style="b", tracking=3)
    p.block(p.rect(5), ["Zoom"], color=WHITE, max_size=50, glow=True)


def _split_v(box, frac):
    x0, y0, x1, y1 = box
    ym = y0 + (y1 - y0) * frac
    return [x0, y0, x1, ym], [x0, ym, x1, y1]


def t11(p):
    # 0 = warning paragraph: headline (red, gold 666) + smaller body
    head, body = _split_v(p.rect(0), 0.42)
    p.block(head, ["From Death Deadline 3 on, 666 can rarely line up."],
            color=RED, highlights={"666": GOLD}, max_size=44, glow=True)
    p.block(body,
            ["If it lines up, the points earned that round are forfeited.",
             "From Death Deadline 7 on, you lose all points you hold.",
             "Deposit frequently to play it safe."],
            color=(212, 150, 150), max_size=30)


def t03(p):
    # 0 caption, 1/3/5 labels Debt/Deposited/Interest, 2/4/6 descriptions, 7 bottom
    p.block(p.rect(0), ['Deposit "Blood Points".'], color=BODY,
            highlights={'"Blood Points"': PINK}, max_size=34)
    # 3 labels: left-align at a common x inside the frames, same font size
    LBLX = 1648
    p.block(p.rect(1), ["Debt"], color=HOTPINK, size=40, align="left", left_x=LBLX)
    p.block(p.rect(2), ["The amount of Blood Points",
                        'required to reach "Remaining', '05 Rounds".'],
            color=BODY, max_size=30, align="left")
    p.block(p.rect(3), ["Deposited"], color=HOTPINK, size=40, align="left", left_x=LBLX)
    p.block(p.rect(4), ["The amount of Blood Points", "currently deposited."],
            color=BODY, max_size=30, align="left")
    p.block(p.rect(5), ["Interest"], color=HOTPINK, size=40, align="left", left_x=LBLX)
    p.block(p.rect(6), ["Can be withdrawn from the",
                        "offering box after every", 'round at the "WELL".'],
            color=BODY, highlights={'"WELL"': PINK}, max_size=30, align="left")
    p.block(p.rect(7),
            ['Interest Rate (%) applies to the "Deposited" amount. If you deposit more than you',
             'need for the slots, the "Interest" you receive at the end of each round increases.'],
            color=BODY, highlights={'"Deposited"': PINK, '"Interest"': PINK,
                                    "Interest Rate (%)": PINK}, max_size=32)


def t04(p):
    # 0 right description, 1 Death Deadline Bonus header, 2 bottom paragraph
    p.block(p.rect(0),
            ['After each round, "Interest" is', "paid out and can be received."],
            color=BODY, highlights={'"Interest"': PINK}, max_size=34, align="left")
    p.block(p.rect(1), ["Death Deadline Bonus"], color=HOTPINK, max_size=44, glow=True)
    p.block(p.rect(2),
            ['While rounds still remain, if you finish depositing the required amount',
             'into the "Offering Box", the "Well" pays out a ticket and Blood Points as a',
             'bonus. The payout changes with the number of "Rounds Remaining".'],
            color=BODY, highlights={'"Offering Box"': PINK, '"Well"': PINK,
                                    '"Rounds Remaining"': PINK}, max_size=32)


def t05(p):
    # 0 instruction1, 1 instruction2, 2 shelf note
    p.block(p.rect(0), ['Pay Tickets to purchase "Charms".'], color=BODY,
            highlights={'"Charms"': PINK}, max_size=36, align="left")
    p.block(p.rect(1),
            ['Press the central "Restock Button" to spend',
             '"Blood Points" and refresh the lineup.'],
            color=BODY, highlights={'"Restock Button"': PINK, '"Blood Points"': PINK},
            max_size=36, align="left")
    p.block(p.rect(2), ['Purchased "Charms" are', 'stored on this "Shelf".'],
            color=BODY, highlights={'"Charms"': PINK, '"Shelf"': PINK},
            max_size=34, align="left")
    # caption under the store photo (not in the mask) - erase JP ストア, write Store
    cap = [420, 1148, 660, 1210]
    p.erase_fill(cap)
    p.block(cap, ["Store"], color=BODY, max_size=30)


def t06(p):
    # 0 left description, 1 Part Marks header, 2 shelf caption
    p.block(p.rect(0),
            ['These are "Part-Specific Charms" worn directly on Konoha\'s body. They bear',
             'the marks below and are kept in a "Part-Specific Shelf", apart from the normal "Shelf".'],
            color=BODY, highlights={'"Part-Specific Charms"': PINK,
                                    '"Part-Specific Shelf"': PINK,
                                    '"Shelf"': PINK}, max_size=36, align="left")
    p.block(p.rect(1), ["Part Marks (8 Types)"], color=HOTPINK, max_size=38, align="left")
    p.block(p.rect(2), ["Part-Specific Shelf"], color=BODY, max_size=30)
    # 8 part-mark labels under each icon (not masked) - erase JP, write pink English
    marks = [
        (358, 1107, "Mouth"), (684, 1107, "Neck"), (1011, 1107, "Legs"), (1337, 1107, "Breasts"),
        (359, 1315, "Vagina"), (680, 1315, "Clit"), (1012, 1315, "Anal"), (1337, 1315, "Full Body"),
    ]
    for cx, cy, en in marks:
        box = [cx - 165, cy - 36, cx + 165, cy + 36]
        p.erase_fill(box, grow=6)
        p.block(box, [en], color=HOTPINK, max_size=34)


def t08(p):
    # 0/1 spin descriptions, 2 cost warning, 3 round paragraph, 4 caption
    PAYX = 1052  # common left x so both "Pay" lines align vertically
    p.block(p.rect(0), ['Pay "Blood Points" to get 1', "Ticket after 7 spins."],
            color=BODY, highlights={'"Blood Points"': PINK}, max_size=40,
            align="left", left_x=PAYX)
    p.block(p.rect(1), ['Pay "Blood Points" to get 2', "Tickets, with 3 spins."],
            color=BODY, highlights={'"Blood Points"': PINK}, max_size=40,
            align="left", left_x=PAYX)
    # red warning box is wide - use 2 longer lines instead of 3 short ones
    p.block(p.rect(2), ["The amount needed to spin the slots grows",
                        "each time you clear a Death Deadline."],
            color=(226, 178, 178), max_size=34, align="left")
    p.block(p.rect(3),
            ['From paying to finishing a spin is 1 Round. It takes 3 Rounds',
             'until the next "Death Deadline", and this repeats.'],
            color=BODY, highlights={'"Death Deadline"': PINK}, max_size=32)
    p.block(p.rect(4), ["Select spin count"], color=BODY, max_size=30)


def t09(p):
    # 0 description, 1 formula, 2/3 table captions, 4 bottom
    CX = 1404  # panel centre (midpoint between the two value tables) - align all 3
    p.block(p.rect(0),
            ['Each of the 7 symbols has a "Symbol Value" and',
             'an "Appearance Rate"; the 11 patterns each have a',
             '"Pattern Value" (the initial value is the "Base Value").',
             'A "Symbol Multiplier" and "Pattern Multiplier" are also set.'],
            color=BODY, highlights={'"Symbol Value"': PINK, '"Appearance Rate"': PINK,
                                    '"Pattern Value"': PINK, '"Base Value"': PINK,
                                    '"Symbol Multiplier"': PINK, '"Pattern Multiplier"': PINK},
            max_size=30, align="center", center_x=CX)
    p.block(p.rect(1),
            ["Symbol Value  ×  Pattern Value  ×",
             "Symbol Multiplier  ×  Pattern Multiplier  =",
             'Earned "Blood Points"'],
            color=BODY, highlights={'"Blood Points"': PINK}, max_size=36, center_x=CX)
    p.block(p.rect(2), ["Symbol Value Table"], color=BODY, max_size=26)
    p.block(p.rect(3), ["Pattern Value Table"], color=BODY, max_size=26)
    p.block(p.rect(4),
            ['You earn when the same symbol lines up in a pattern. The higher the',
             '"Multiplier", the more "Blood Points" you earn.'],
            color=BODY, highlights={'"Multiplier"': PINK, '"Blood Points"': PINK},
            max_size=30, center_x=CX)


def t10(p):
    # 0 main description, 1 left caption (2 lines), 2 center caption
    p.block(p.rect(0),
            ['The "Red Button" in the corner of the chair can be pressed while you',
             'hold a "Charm that activates with the red button". Pressing it spends',
             'all of that charm\'s "Charge" to trigger its effect. Charge recovers',
             'by "1" after each round ends.'],
            color=BODY, highlights={'"Red Button"': HOTPINK, '"Charge"': CYAN},
            max_size=32, align="left")
    head, sub = _split_v(p.rect(1), 0.5)
    p.block(head, ["Red Button"], color=BODY, max_size=30)
    p.block(sub, ["Blinks when pressable"], color=(168, 150, 192), max_size=24)
    p.block(p.rect(2), ["Charm that activates with the red button"],
            color=(168, 150, 192), max_size=24)


def t07(p):
    # 0 desc; 1/3/5 state labels; 2/4/6 sub-captions; 7-12 inline sentence; 13/14 paragraphs
    p.block(p.rect(0),
            ['Some "Charms", when held, have the trait of changing Konoha\'s mental',
             "state. You can tell them apart by the mark shown on their back."],
            color=BODY, highlights={'"Charms"': PINK}, max_size=34)
    p.block(p.rect(1), ["Defiance"], color=ORANGE, max_size=44)
    p.block(p.rect(2), ["Her attitude turns aggressive."], color=TEAL, max_size=30)
    p.block(p.rect(3), ["Emptiness"], color=CYAN, max_size=44)
    p.block(p.rect(4), ["Her reactions grow faint."], color=TEAL, max_size=30)
    p.block(p.rect(5), ["Ahe"], color=HOTPINK, max_size=44)
    p.block(p.rect(6), ["She comes to crave stimulation."], color=TEAL, max_size=30)
    p.block(p.rect(7), ["Mental states:"], color=BODY, max_size=34)
    p.block(p.rect(8), ["Normal"], color=GREEN, max_size=34)
    p.block(p.rect(9), ["Defiance"], color=ORANGE, max_size=34)
    p.block(p.rect(10), ["Emptiness"], color=CYAN, max_size=34)
    p.block(p.rect(11), ["Ahe"], color=HOTPINK, max_size=34)
    p.block(p.rect(12), ["4 types."], color=BODY, max_size=34)
    p.block(p.rect(13),
            ["Equipping a charm with a mental trait changes Konoha's expressions and lines."],
            color=HOTPINK, max_size=34)
    p.block(p.rect(14),
            ["The most numerous mental trait takes priority; if tied, the order is Ahe > Defiance > Emptiness."],
            color=BODY, max_size=30)


def t12(p):
    # 0 Repeat; 1 step1; 5 step2; 4 step3; 2 step4; 3 bottom
    p.block(p.rect(0), ["Repeat"], color=PINK, max_size=26)
    p.block(p.rect(1), ['Buy "Charms" with Tickets to', "raise the money & count you earn"],
            color=BODY, highlights={'"Charms"': PINK}, max_size=30)
    p.block(p.rect(5), ["Spin the slots to get", "money and Tickets"], color=BODY, max_size=30)
    p.block(p.rect(4), ["Deposit in the Offering Box", "to break the Death Deadline"],
            color=BODY, max_size=30)
    p.block(p.rect(2), ["The debt amount rises"], color=BODY, max_size=30)
    p.block(p.rect(3),
            ['The debt rises higher each time you break a Death Deadline.',
             'Use "Charms" and "Typewriters" to master this loop.'],
            color=BODY, highlights={'"Charms"': PINK, '"Typewriters"': PINK}, max_size=32)


def t13(p):
    # 0 desc; 1-6 effect entries (label+desc); 7 caption
    p.block(p.rect(0),
            ['Through charm effects, slot symbols can gain a special "Modifier".',
             "When a pattern containing a Modifier lines up, the effects below apply."],
            color=BODY, highlights={'"Modifier"': PINK}, max_size=32, align="left")
    effects = [
        (2, "Ticket", HOTPINK, "Lets you obtain 1 Ticket."),
        (3, "Gold", GOLD, "Raises a symbol's value by its base value."),
        (4, "Chain", ORANGE, "Raises a matched pattern's value by its base value."),
        (5, "Token", RED, "Grants points equal to half the current interest."),
        (6, "Repeat", HOTPINK, "Repeats the current pattern one more time."),
        (7, "Battery", CYAN, "Restores 1 charge to your red-button charm."),
    ]
    for i, label, col, desc in effects:
        head, sub = _split_v(p.rect(i), 0.46)
        p.block(head, [label], color=col, max_size=30, align="left")
        p.block(sub, [desc], color=BODY, max_size=24, align="left")
    p.block(p.rect(1), ["Example of a pattern containing a Modifier"],
            color=BODY, max_size=26, align="center")


def t14(p):
    # 0 big title, 1 bottom note
    p.block(p.rect(0), ["Thank you for downloading", "the demo version"],
            color=HOTPINK, max_size=96, glow=True, style="i")
    p.block(p.rect(1),
            ["In the demo, you can play up to Death Deadline 3 of the 10 Death Deadlines.",
             "Please enjoy it along with trying out the controls."],
            color=BODY, highlights={"Death Deadline 3": PINK, "10 Death Deadlines": PINK},
            max_size=32)


def t15(p):
    # 0 big title, 1 body, 2/3 version labels, 4/5 Death Deadline, 6 Infinity
    p.block(p.rect(0), ["Thank you for playing", "the demo version."],
            color=HOTPINK, max_size=92, glow=True, style="i")
    p.block(p.rect(1),
            ["Enjoy the story through Death Deadline 10, ecchi with the many Konoha,",
             'multiple endings, plus extras like "Mental State" and "Costume Change".'],
            color=BODY, highlights={'"Mental State"': PINK, '"Costume Change"': PINK},
            max_size=32)
    p.block(p.rect(2), ["<Demo Version>"], color=BODY, max_size=26)
    p.block(p.rect(3), ["<Full Version>"], color=BODY, max_size=26)
    p.block(p.rect(4), ["Death Deadline"], color=BODY, max_size=30)
    p.block(p.rect(5), ["Death Deadline"], color=BODY, max_size=30)
    p.block(p.rect(6), ["Infinity"], color=GOLD, max_size=44)


BUILDERS = {"tutorial_02_currency": t02, "tutorial_01_controls": t01,
            "tutorial_11_six66": t11, "tutorial_03_saisen": t03,
            "tutorial_04_ido": t04, "tutorial_05_store": t05,
            "tutorial_06_part_charm": t06, "tutorial_08_slot_intro": t08,
            "tutorial_09_symbol_pattern": t09, "tutorial_10_red_button": t10,
            "tutorial_07_mental_state": t07, "tutorial_12_game_loop": t12,
            "tutorial_13_modifier": t13, "tutorial_14_start_demo": t14,
            "tutorial_15_finish_demo": t15}


def main():
    names = sys.argv[1:] or list(BUILDERS)
    for n in names:
        if n not in BUILDERS:
            print("no builder:", n); continue
        p = Plate(n)
        BUILDERS[n](p)
        print("saved", p.save())


if __name__ == "__main__":
    main()
