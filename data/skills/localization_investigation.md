# DazedTL — Localization Investigation

You are investigating a Japanese game for systemic localization decisions and maintaining its
localization guidance. Work in the game repository and treat Japanese source text as authoritative.
Use existing English only as evidence when a translation is already present.

This standalone skill reruns the same hypothesis-led editorial phase used inside Project Setup.
Use it when new questions arise after setup, when translated English already exists, or when one
family needs deeper follow-up without repeating speaker, layout, and game-frame analysis.

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

## Investigation method

1. Start with the concrete candidate hypotheses collected by the baseline setup phase or supplied
   by the user. In standalone use, perform a brief corpus-wide survey only when no candidates exist.
2. Search for high-yield signals across the whole game, including:
   - recurring jokes, callbacks, catchphrases, coined words, and speech suffixes;
   - repeated scene structures whose Japanese wording varies, such as observation → coinage →
     deadpan repetition;
   - proper names, titles, locations, or common nouns with competing translations;
   - suspicious romanization or untranslated common nouns;
   - the same Japanese translated several ways, or repeated English that erases distinct Japanese;
   - English lines that are locally intelligible but disconnected from adjacent setup or callbacks.
3. Rank concrete hypotheses by likely impact and evidentiary strength. Discard generic categories
   such as “there may be puns” unless actual source anchors or scene patterns support them.
4. Research each supported hypothesis globally with repository search and small scripts as needed.
   Search all maps, common events, and relevant databases rather than only early files. Inspect the
   complete local scene around every candidate. Deduplicate exact copies for analysis, but report
   the total number of occurrences and files/maps affected.
5. Expand a family by its shared semantic, comic, or structural mechanism—not merely one repeated
   token. After finding a new variant, search again for its anchors and structural siblings until
   no new supported members appear.
6. Confirm a recurring family only when at least two independent examples or an explicit callback
   establish it. For each confirmed family, determine:
   - the Japanese mechanism and distinctive source anchors;
   - every supported member and meaningful exception;
   - one recognizable English mechanism or canonical term;
   - whether the rule belongs in Translation quirks, the Glossary, or a bounded correction list.
7. When the project is untranslated, emphasize preventive guidance. When English already exists,
   additionally identify inconsistent members and propose translation corrections, but do not
   apply those corrections. Still apply the confirmed guidance-file updates defined below.

<!-- /investigation-phase -->

## Output

Return these sections in order:

### 1. Executive result

Summarize only the strongest confirmed families and the highest-value unresolved lead.

### 2. Confirmed families

For each family report priority, source mechanism, Japanese anchors, occurrence and file/map counts,
representative locators, current-English assessment when applicable, and the recommended English
strategy. Separate genuine exceptions from missed family members.

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
recounted, and any inaccessible or intentionally excluded material.
