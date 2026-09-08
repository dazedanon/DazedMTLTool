# Wolf move-route + operand RE — confidence-raising pass

Goal: promote every `med`/`low` confidence route/command name in
`wolf-dawn/crates/wolf-decompiler/data/commands.json` to `high` by RE'ing the
authoritative behavior from Game.exe (port 13337) and GamePro.exe (13338).

## Editor.exe — DEAD END
Editor.exe (every version) does NOT store the 動作指定 menu labels as plaintext
Shift-JIS (only embedded sample-data hits + SJIS false positives). Names must come
from runtime behavior, matched to the documented Wolf move-route command set.

## Move-route executor (Game.exe) = sub_4CC7D0 (per-frame state machine)
Stored route id == switch case. Char struct = `a1`. Known offsets:
- +64 opacity (confirmed), +72 move-speed level (confirmed, mirrored to +70 when ver>=306),
  +79 through/noclip (confirmed via collision skip), +108 wait counter (confirmed),
  +162 direction-fix (confirmed, blocks turns), +168 step px 1/2 (confirmed), +184 height (confirmed).
- UNKNOWN (the med/low items): +86 (id29), +90 (id30), +88 (id31), +161 (id32/33),
  +160 (id34/35), +163 (id40/41), and the +70 anim frame.

## med/low route ids to resolve
22,23 (rel-90 turns) · 24,25 (random turns) · 26,27 (toward/away hero) · 28 (assign) ·
29,30,31 (+86/+90/+88 setters) · 32,33,34,35 (anim toggles +161/+160) · 40,41 (+163) ·
53,54 (sub_4C15C0 move-to-target) · 55 (graphic) · 59,60,61 (GamePro pathfind sub_9DD270).

## med main commands: 104, 242 (ChipGet), 252, 140 (Sound — verify).
