# Nightfall Princess - cross-cutting translation guidance

This is source-derived guidance, not a characterization inferred from the genre.
Canonical spellings belong to `glossary.json`; per-character register belongs to
its name records. Verification, convergence and exceptions are documented in
`review/quirk-review.md`. This is a targeted preparation review, not a full-game review.

## Narrator and address

- Captions such as `高貴な王女は` and `フラヴィアは` describe the heroine externally.
  The focus character is not a speaker. Preserve subjects, agency and scene phase;
  do not add first-person speech or heroine verbal tics. The merchant's `私は`
  introduction is a separate dialogue track. No recurring joke, dialect or
  catchphrase family was verified in this pass; do not manufacture one.
- Use natural fantasy English. Japanese honorifics are not retained as suffixes.
  Preserve rank when meaningful; use the bible's direct-address rule for `王女様`.
  No source evidence supports faux-archaic speech for a goddess or baby talk for a fairy.

## Mechanical prose

- `遠謀#`, `カウント#`, and `キル数#` are different trigger systems: activations per
  battle, a time interval in seconds, and a kill threshold. Their numbers have
  different directions of improvement. Keep the glossary labels distinct and
  preserve units. Ordinary cooldowns are a separate system.
- `最大感度` is a tolerable pleasure ceiling, while `感度回復` reduces accumulated
  pleasure. A larger value is beneficial for both. `体力` is the separate HP
  reserve lost at the threshold. Do not apply this stat interpretation to every
  narrative use of sensitivity or sensation.
- `貫通ダメージ` is the damage retained on targets beyond the nearest target;
  `破甲` is a stackable increase to damage received. Do not describe both as armor
  penetration. Render `層` as stacks where it counts that status. Do not infer a
  universal multiplicative/additive percentage policy for all other effects.
- The recurring `ポイントの魔法ダメージを生成` wording means dealing an amount of
  magic damage, not generating a points currency. Prefer normal English effect
  verbs. `生成` can still mean creating a projectile in other contexts. `引爆`
  means detonation in the checked Holy Mark contexts, not a separate invented system.
- Four explicitly marked skill units reverse their source frequency:
  `攻撃ごとに#回` must describe **one effect every # qualifying attack hits**.
  The relevant normal/additional attack callbacks count; the separate projectile
  increase remains. Apply only the per-unit `verified_correction`. Equipment
  `#回の追加攻撃ごとに` examples already express the correct direction and must not
  be inverted. No other numeric corrections are implied.

## Assembly and formatting

- Keep all protected sentinels in order. A `#` substitution can contain a number
  or an entire target phrase. Equipment 46 has three target ranks; check the
  assembled sentence for each. Formula text such as `[攻撃*0.5]` is displayed
  prose: translate the stat word while preserving its mathematics. Explanatory
  `X` in help is literal notation, not a runtime token.
- Follow the per-unit exact helper keywords. Their capitalization controls help
  lookup. Do not introduce unrelated canonical keywords accidentally in other
  equipment/skill descriptions. Technical lookup edits are a separate planned step.
- A fragment's spaces belong to the complete expression. Do not duplicate the
  number, write two independent sentences around it, or drop a nonempty fragment.
  The negative HP modifier uses a signed value; follow `assembly_notes.md`.
- Use ASCII punctuation supported by the embedded fonts: straight quotes and
  apostrophes, a hyphen, `...`, and `%`. Preserve protected explicit line breaks.
  This is punctuation style, not permission to remove information to fit an
  arbitrary character count. Runtime word wrapping remains a later layout task.

