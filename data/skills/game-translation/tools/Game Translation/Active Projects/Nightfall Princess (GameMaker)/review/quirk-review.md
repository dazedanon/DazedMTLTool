# Independent review synthesis

Date: 2026-09-05. Source archive SHA-256:
`2c22ad3c7dd540f4e870c195935a206eeafc58665c458673c88c3acb9a5ab611`.

Three fresh workers (`quirks_a`, `quirks_b`, `quirks_c`) ran concurrently with no
forked conversation. All received the same frozen `STARTING_PACKET.md`, worked
read-only, did not delegate, and could not consult new drafts or one another's
reports. All three returned before this synthesis. The starting orientation was
not evidence. No translator service or game runtime was used.

The coordinator independently recounted the union of Japanese anchors against
all 630 candidates and re-read their definitions and consumers. Exact membership
and source locations are in `anchor-counts.json`. Counts there include technical
needles and held records, so they are not claims of unique visible lines.
Agreement measures convergence, not correctness. This is a targeted review.

Paths below are in `source/gml/`; script shorthand expands to
`gml_GlobalScript_<name>.gml` and object shorthand to `gml_Object_<name>.gml`.

| ID | Finding | Independent reports | Coordinator decision |
|---|---|---|---|
| F1 | Four `攻撃ごとに#回` frequency reversals | A, C: 2/3 | Confirmed, narrowly actionable text correction |
| F2 | `遠謀` / `カウント` / `キル数` have distinct dimensions | A, B, C: 3/3 | Confirmed terminology/meaning policy |
| F3 | `最大感度` and `感度回復` have beneficial stat directions | A, B, C: 3/3 | Confirmed stat-specific policy |
| F4 | `貫通ダメージ` retains damage past the first target | A, C: 2/3 | Confirmed; C also distinguishes `破甲` stacks |
| F5 | `ポイントの魔法ダメージを生成` denotes damage, not currency | B: 1/3 | Confirmed by multiple equipment effects and consumers |
| T1 | Visible terms are also help lookup predicates | A, B, C: 3/3 | Confirmed technical dependency, not a voice defect |
| T2 | `#` can insert a target phrase, not only a number | A, B: 2/3 | Confirmed rank assembly requirement |
| C1 | Third-person scene narration | A, B: 2/3 | Verified clean; preserve point of view |
| C2 | Duplicate names can represent distinct IDs | B: 1/3 | Verified clean; keep record identities |
| C3 | Checked `#回の追加攻撃ごとに` equipment counters | C: 1/3 | Verified clean positive controls for F1 |
| C4 | Display formulas are prose; checked Seed/Pillar formulas agree | A, B: 2/3 family | Verified clean within checked scope |
| C5 | `引爆` in Holy Mark contexts means detonation | B, C: 2/3; A backlog | Confirmed lexical meaning, no systemic source defect |

## Evidence and bounds

**F1.** `scr_text_skill:230,233,236,242` are skills 75, 76, 77, 79;
catalog IDs `CODE:16:549`, `CODE:16:552`, `CODE:16:555`, `CODE:16:561`.
`scr_att_3:42-83` increments counters and emits one effect at thresholds
12/level, 30/level, 32/level, 10/level. `obj_att_3_Collision_obj_enemy_f:26-29`
calls this on a qualifying first hit; the additional attack collision also calls
it. `obj_god_Step_0:164-178` separately increases projectile count. Role 3's
ordinary pool contains 58-80 (`scr_talent_skill:9-12`) and its descriptions are
drawn by `obj_talent_Draw_0:147-149`. Release enables progression
(`obj_lording_Create_0:11`, `obj_end_Step_0:116-127`, `obj_role_2_Step_0:33-39`).
This is static release reachability, not a playtest. Equipment 56/57's correctly
directed counters (`scr_text_equip:173,176`, `obj_att_ex_3_Create_0:11,20`) are exceptions.

**F2.** Independent examples at `scr_text_skill:11,14,26,29,41,59`; explicit
definitions at `scr_text_talent_down:10,14,34`. `scr_strategy:3-11` converts uses
per battle to an interval, `scr_strategy_2:3` converts seconds to frames, and
`scr_strategy_3:3-8` adjusts kill thresholds. Common and role skill pools feed
the live talent display. Equipment countdown acceleration is related timing,
not a new trigger class; generic CD labels are not all this system.

**F3.** `scr_name_talent:13,25` pair with `scr_text_talent:13,25`;
HP's explicit callback is `scr_text_talent:22`. Talent upgrades increase the
threshold and recovery (`obj_talent_Step_0:133,149`); recovery subtracts pleasure
(`obj_god_Step_0:357-363`). The threshold sequence resets pleasure and costs HP
(`obj_ui_Step_0:141-146,196-203`). Normal talent display is the release consumer.
Narrative sensation vocabulary is outside this stat rule.

**F4.** `scr_text_skill:65,92`, `scr_text_equip:41`, `scr_role_clear:17`, and
`obj_att_1_Step_0:10-38` establish the 0.5 base retention on non-nearest targets.
`scr_text_talent_down:42` explicitly defines per-stack increased damage taken;
`obj_sow_Collision_obj_enemy_f:4-7` applies it. The first and second role pools
expose these mechanics. Skill names containing 貫通 are not sufficient evidence
of the same implementation; skills 29 and 50 share a name but differ in effect.

**F5.** `scr_text_equip:122,125,131` use the points/generated wording.
`scr_break:8-10` and `obj_enemy_f_Step_0:184-188` add magic damage to hits.
The merchant generates equipment IDs 1-77 and ranks 1-3 (`obj_npc_Create_0:39-54`),
which can be bought (`obj_shop_Step_0:89`). This is ordinary damage prose;
object-creation uses of 生成 remain distinct. No inference about author identity
or native language follows from unusual Japanese phrasing.

**T1/T2.** Seventeen `string_pos` predicates in `scr_text_talent_down` inspect
the actual displayed description (`obj_talent_Draw_0:147-149`,
`obj_equip_Draw_0:89-113`, `obj_shop_Draw_0:167`). The prepared exact needle map
must accompany translated descriptions. `scr_text_equip:950` substitutes all
`#` occurrences; equipment 28 repeats the marker. Equipment 46's three target
values at `:379,616,853` agree with `scr_skill_z:60-75`. Supply that entire family
as context. One helper, 跳弾, has no discovered producer and stays held.

**Verified clean.** C1 has independent scene anchors at `scr_text_h:89,92,95`;
the enemy-contact/caption path is `obj_enemy_f_Step_0:124-129`,
`obj_ui_Step_0:154,174`, `obj_ui_Draw_0:218`. Merchant records are actual speech.
C2 pairs equipment 2/39 (`scr_name_equip:10,121`) and skills 29/50
(`scr_name_skill:91,154`) with their distinct descriptions. C4's visible formulas
are passed to drawing, not evaluated; Seed's 1.5 coefficient and Pillar's 0.2
five-hit baseline match their collision consumers. C5's Holy Mark detonation is
created at enemy death (`obj_enemy_f_Step_0:116-118`). This does not resolve its
separate coefficient mismatch.

## Isolated issues and backlog

- **Ricochet producer missing: 3/3.** All workers found only the helper's own
  needle/definition. Do not count its absence as a confirmed release defect.
- **Holy Mark coefficient: 1/3 (B).** Help says 0.5 but
  `obj_scar_Collision_obj_enemy_f:4` uses 0.75. Coordinator rechecked both.
  Isolated numeric discrepancy; held, not generalized into automatic corrections.
- **Signed HP decrease: 1/3 (C), also found in coordinator inspection.**
  `obj_hall_Step_0:115` inserts a negative modifier into a decrease sentence;
  `scr_enemy_difficulty:10` returns -5. `assembly_notes.md` gives a text-only
  signed presentation, without changing game arithmetic.
- **属性 means stats in skill 11: 1/3 (C).** Its consumer at
  `obj_talent_Step_0:173-194` increases nine ordinary stats; glossary note accepted.
- **Fourth merchant record and English word wrapping:** found by coordinator,
  not included in worker agreement ratios. See `OPEN_ITEMS.md`.

