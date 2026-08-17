# DazedTL — Localization Investigation

You are investigating a Japanese game for systemic localization decisions and maintaining its
localization guidance. Work in the game repository and treat Japanese source text as authoritative.
Use existing English only as evidence when a translation is already present.

This standalone skill reruns the same hypothesis-led editorial phase used inside Project Setup.
Use it when new questions arise after setup, when translated English already exists, or when one
family needs deeper follow-up without repeating speaker, layout, and game-frame analysis.

## Establish request context

Before beginning a standalone run, resolve the game root and RPG Maker version from the open
project, then derive a short game synopsis yourself (roughly 2–5 sentences covering the premise,
setting, main cast or roles, and tone). Do not ask the user to write it.

Start with `.dazedtl/skills/game.md`, the title in `System.json`, the main `Actors.json` records,
`MapInfos.json`, and a bounded sample of opening or early-map and common-event story text. When web
access is available, use a matching official DLsite product page as a shortcut or cross-check for
the creator's high-level premise. Verify that page by Japanese title, developer/circle, and product
ID when available, and retain its URL in the starting packet. If the page is inaccessible or cannot
be matched confidently, use game-local evidence only; do not block the investigation or guess.
Treat the resulting synopsis as orientation for search terms and candidate hypotheses, not as
evidence, and do not expand this step into a full plot reconstruction.

## RPG Maker corpus map

Use this known layout before doing any open-ended discovery:

- For MV/MZ, locate JSON under `<game>/data/` or `<game>/www/data/`. For VX Ace, use DazedTL's
  normalized `<game>/ace_json/` output (or legacy `<game>/JSON/`) rather than reverse-engineering
  `Data/*.rvdata2` when normalized JSON is available.
- Prefer the current translated or exported JSON tree that retains DazedTL `_original` values.
  In database records, `_original` usually mirrors the translated fields; in event command lists,
  a command-level `_original` preserves the Japanese source for the translated parameter. Compare
  the live sibling value with `_original`, and never modify or remove the source field.
- Read the small databases first: `Actors.json`, `Classes.json`, `Enemies.json`, `Skills.json`,
  `Items.json`, `Weapons.json`, `Armors.json`, `States.json`, and `System.json`. Use `MapInfos.json`
  to resolve map IDs and names.
- Search the full event corpus in `MapNNN.json`, `CommonEvents.json`, and `Troops.json`. Map events
  are normally under `events -> pages -> list`; common events have their own `list`, and troop
  pages have `pages -> list`. Commands use `code` plus `parameters`: code `101` establishes a
  message window/name, `401` carries its dialogue lines, `102` carries choices, and `405` carries
  scrolling text. Inspect complete local command-list context around a hit rather than treating an
  isolated parameter as a scene.
- Consult `.dazedtl/glossary.txt`, `.dazedtl/skills/quirks.md`, and `.dazedtl/skills/game.md` before
  proposing a family. Check `js/plugins.js` and the enabled source under `js/plugins/` only when a
  concrete candidate depends on custom commands, terminology, or runtime data; do not inventory
  every plugin speculatively. For Ace script-dependent candidates, inspect the extracted Ruby under
  `ace_json/scripts/` only as needed.

<!-- investigation-phase -->

## Phase 2 — Global localization investigation

Discover systemic localization families that ordinary per-line review misses. Turn confirmed
families into preventive guidance before translation or bounded correction work afterward.

## Boundaries

- Do not edit runtime game data or translated text as part of investigation.
- Follow the containing workflow's explicit guidance-file write contract.
- Do not certify the game as fully reviewed or clean.
- Read the current `.dazedtl/glossary.txt`, `.dazedtl/skills/quirks.md`, and
  `.dazedtl/skills/game.md` when present.
- Never modify or remove `_original` source fields.
- Do not promote a one-off joke or ambiguous coincidence into a global rule.
- Keep runtime, formatting, and exhaustive per-line checks in the normal QA workflow.

## Three-pass discovery

1. Freeze one starting packet containing the game paths, engine/version, applicable corpus map,
   short source-derived synopsis with its game-local and optional DLsite provenance, unchanged
   guidance, user-supplied hypotheses, and any raw Phase 1 candidates. Label the synopsis and
   starting guidance as orientation rather than corpus evidence. Do not add conclusions from the
   coordinator.
2. Launch exactly three fresh subagents concurrently with no forked conversation context; set
   `fork_turns="none"` when that control is available. Never show a worker either of the other
   reports.
3. Give all three workers the same self-contained packet and the Investigation method below. Tell
   each worker not to delegate, edit files, or write a report into the shared repository; it must
   inspect the corpus read-only and return its compact evidence report only to the coordinator.
   When a prompt explicitly designates you as one of these already-launched workers, do not run or
   repeat Three-pass discovery: perform the Investigation method exactly once and return your own
   report.
4. Keep the guidance files unchanged and do not synthesize or begin coordinator verification until
   all three reports are returned. If three isolated subagents cannot run concurrently, report the
   blocker rather than presenting serialized or repeated work as the requested parallel passes.
5. After all three passes, merge families by shared mechanism and anchors. Treat duplicate
   discoveries as convergence evidence, not waste; retain unique discoveries for equal verification.
   Independently recount and inspect the union of proposed anchors, members, exceptions, and
   corrections against the corpus. Treat starting guidance as hypotheses, not evidence; after the
   blind passes, audit anchored quirks and game-specific glossary keys that have competing current
   English renderings. For placeholder templates, inspect every distinct resolved value and relevant
   context; do not force one English frame merely because the Japanese template is identical. Split
   the policy or retain a backlog item when one frame is not natural for every member. Classify a
   correction as actionable only when its text is player-visible and release-reachable; keep hidden
   scaffolding, test content, and uncertain reachability in the backlog. If a canonical choice is a
   corpus minority, cite the primary in-game label,
   self-identification, or explicit user instruction that outweighs frequency; generated guidance
   alone is not proof. Only the coordinator may confirm families and apply guidance.

## Investigation method

1. Start with the concrete candidate hypotheses collected by the baseline setup phase or supplied
   by the user. In standalone use, perform a brief corpus-wide survey only when no candidates exist.
2. Search for high-yield signals across the whole game, including:
   - recurring jokes, callbacks, catchphrases, coined words, and speech suffixes;
   - repeated scene structures whose Japanese wording varies, such as observation → coinage →
     deadpan repetition;
   - proper names whose reading may depend on character lore, naming-family morphology, mythology,
     titles, affiliations, motifs, or wordplay—not only kana-to-Latin phonetics;
   - suspicious romanization or untranslated common nouns;
   - the same Japanese translated several ways, or repeated English that erases distinct Japanese;
   - English lines that are locally intelligible but disconnected from adjacent setup or callbacks.
3. Rank concrete hypotheses by likely impact and evidentiary strength. Discard generic categories
   such as “there may be puns” unless actual source anchors or scene patterns support them.
4. Research each supported hypothesis globally with repository search and small scripts as needed.
   Search all maps, common events, and relevant databases rather than only early files. Inspect the
   complete local scene around every candidate. Deduplicate exact copies for analysis, but report
   the total number of occurrences and files/maps affected.
<!-- character-name-evidence -->
5. For each suspicious character name, enumerate competing spellings and build a compact evidence
   matrix. Evaluate evidence in this order, while recording contradictions and source quality:
   1. trustworthy creator or in-game Latin spelling;
   2. corpus structure and demonstrated naming-family morphology;
   3. attested lexical or proper-name candidates in plausible source languages;
   4. independent lore convergence, including explicit wordplay or callbacks;
   5. kana phonetics and the exact mismatch for each candidate; then
   6. a conservative naturalized fallback, clearly labeled editorial when ambiguity remains.

   Compare which candidates each item actually distinguishes. Repeated nameplates, database fields,
   and self-introductions establish identity or segmentation, not Latin orthography. Treat related
   lines from one role, motif, institution, or scene premise as one evidence class. Do not validate
   a spelling merely because every occurrence inherited the same provisional glossary guess.

   Research credible dictionaries and naming references rather than stopping at transliteration.
   Record meaning, pronunciation, morphology, and exact kana mismatch; compare cognates across
   plausible languages. An attested word whose meaning fits independent source anchors can outweigh
   a minor transcription irregularity. The irregularity remains contrary evidence, not a veto, and
   an otherwise unexplained mechanical spelling does not win solely by following kana more closely.

   Decide every component of a multi-part name independently. A common-noun reading supported only
   by one matching trait, dictionary existence, phonetic fit, or a language inferred from another
   component is weak; default to the conservative naturalized reading. Keep the common-noun reading
   eligible, however, and promote it when multiple independent naming signals converge—for example
   an unusually exact semantic callback plus demonstrated language or morphology, explicit
   wordplay, creator evidence, or parallel names. An attested proper name is a useful conservative
   candidate, not an automatic winner. Matching two dictionary words to two character traits does
   not by itself establish a compound naming pattern.

   Prefer the reading that explains the most independent, discriminating evidence with the fewest
   unsupported assumptions. Naturalize foreign or invented names for the player-facing language
   rather than preserving every kana mora mechanically. When the evidence remains close, retain a
   conservative reading and put the alternatives and exact missing evidence in the research backlog.
<!-- /character-name-evidence -->
6. Expand a family by its shared semantic, comic, or structural mechanism—not merely one repeated
   token. After finding a new variant, search again for its anchors and structural siblings until
   no new supported members appear.
7. Confirm a recurring family only when at least two independent examples or an explicit callback
   establish it. For each confirmed family, determine:
   - the Japanese mechanism and distinctive source anchors;
   - every supported member and meaningful exception;
   - one recognizable English mechanism or canonical term;
   - whether the rule belongs in Translation quirks, the Glossary, or a bounded correction list.
   For a confirmed faux name or other name-based joke, audit the final English Glossary target
   against that mechanism. When a natural, evidence-supported adaptation is possible, the target
   itself must carry the recognizable joke; do not merely transliterate the name and leave the
   wordplay only in its description. Retain a transliteration only when adaptation would distort
   the character's identity or tone, or no supportable English mechanism exists, and record that
   reason in the research backlog.
8. When the project is untranslated, emphasize preventive guidance. When English already exists,
   additionally identify inconsistent members and propose translation corrections, but do not
   apply those corrections. Return proposed guidance to the coordinator; it applies confirmed
   guidance-file updates only after synthesizing all three reports.

<!-- /investigation-phase -->

## Output

Return these sections in order:

### 1. Executive result

Separate confirmed actionable defects, verified-clean families, and the highest-value unresolved
leads. Never count a verified-clean family as an inconsistency, defect, or correction family.

### 2. Confirmed families

For each family report priority, source mechanism, Japanese anchors, occurrence and file/map counts,
representative locators, current-English assessment when applicable, and the recommended English
strategy. Include discovery agreement such as `1/3` or `3/3`; agreement raises confidence but does
not replace corpus verification. State total family scope and actionable correction count
separately, and make the executive total sum actionable targets only. For a placeholder-wide policy,
state that every distinct resolved value was checked and list any exception classes; IDs alone are
not evidence. Label its outcome `Actionable` or `Verified clean`, and separate genuine exceptions
from missed family members.

### 3. Translation quirks updates applied

Directly apply confirmed `ADD`, `REPLACE`, or `REMOVE` changes to
`.dazedtl/skills/quirks.md`; do not wait for approval and do not return a replacement block for the
user to paste. Preserve unrelated and user-authored guidance. Every humor, callback, catchphrase,
or wordplay rule must include distinctive Japanese source anchors so later QA can gather the family
deterministically. Report the exact bullets changed and verify the saved file by rereading it.

### 4. Glossary updates applied

Directly apply confirmed `ADD`, `REPLACE`, or `REMOVE` changes to the game-specific section of
`.dazedtl/glossary.txt`; do not wait for approval and do not return a replacement block for the user
to paste. Preserve unrelated entries and preserve the auto-appended base separator and everything
below it byte-for-byte. Include only confirmed canonical names, titles, locations, and world terms.
Do not put joke-family strategy or per-character prose style here. Report the exact Japanese entry
keys changed and verify the saved file by rereading it.

### 5. Correction families

When translated English exists, list each actionable family with all supported affected locators,
the shared correction policy, and any item that needs bespoke wording. Do not pretend one proposed
blend can be copied mechanically across different jokes.

### 6. Research backlog

List plausible but unconfirmed hypotheses with their evidence, confidence, and the exact next
search or context needed. If none remain, say so. This is a research backlog, not a QA clearance.

### 7. Coverage

State which file classes and map ranges were searched, occurrence totals that were independently
recounted, whether all three isolated passes completed, and any inaccessible or intentionally
excluded material.
