# Reference Translations

Reusing a game you already translated as evidence for the next one. Same circle,
same engine, same series, or just the same stock plugin text - the overlap is
usually larger than it feels, and re-deriving it costs money and introduces drift.

The whole technique is in `DAZEDTL_ROOT/util/reference_games.py`.

The alignment problem here is the same one `version-updates.md` solves across
versions of one game. Read that first if you are carrying a translation forward
rather than borrowing from a different game.

## Multiple prequels named in the starting instructions

The user can supply one corpus folder or several translated-game folders in Len's
**Instructions** field. Handle these as part of setup in the same run. Do not require
the user to fill the reference dialog or manually transfer a glossary first.

1. Read each supplied folder's README, corpus manifest and existing glossary when
   available. Inventory which games, versions, languages and alignment formats it
   contains. Use already-prepared corpora before attempting another extraction.
   Restrict references to the titles the user requested; a shared publisher folder
   is not evidence that every game has the same setting or characters.
2. Search every specified prequel for the current game's names, aliases, locations,
   factions, item/skill names, system terminology and recurring expressions. Search
   Japanese keys in glossary/term indexes as well as their occurrences in the paired
   corpus. Whole-line exact matches alone miss terms inside new dialogue.
3. Check the corresponding Japanese and shipped English in context. Retain the source
   game, file/locator, English variants and relevant counts as evidence. Resolve
   variants using the user's stated priority, the current meaning and curated guidance;
   neither the last loaded game nor the most frequent rendering wins automatically.
   Preserve public/revealed identities and do not import another character's voice
   merely because their name or role resembles a current character.
4. Add the verified recurring decisions to the CURRENT game's `.dazedtl/glossary.txt`.
   Use `.dazedtl/skills/quirks.md` only for evidenced recurring motifs or cross-cutting
   voice rules. This makes inherited terms apply to new sentences through the shared
   context compiler. Preserve existing curated decisions and document justified
   changes. Do not copy entire historical glossaries or plot bibles into the prompt.
5. Keep a concise provenance/conflict report under
   `.dazedtl/len-method/work/prequel-terminology.md`, outside runtime skill overlays.
   Record references checked, inherited decisions, unresolved variants and gaps.
   Lack of an exact old line is not proof that a term is absent from the prequels.
6. Register supported aligned JP/EN data for each reference using the shared helpers
   below. Compile each translation batch through `scripts/len_translation.py context
   --sources ...` to obtain exact-source reference evidence alongside the glossary.
   Validate inherited terminology across translated dialogue, database labels and
   images in scope. Keep every supplied reference folder read-only; adapters, derived
   indexes and decisions belong in the current project's workspace.

### Existing corpus workspaces

A corpus may already provide `terminology.json`, `database/legacy-terms.json`, paired
JSONL/TSV records, and per-game normalized JSON. Inspect the actual schema first:

- A recurring-term index may omit one-off terms. Search occurrence-level database
  inventories and paired text as well. Exclude engine metadata, unchanged Japanese
  and internal labels from English terminology decisions unless the current display
  use independently warrants them.
- Fields such as `common_english` and `variants` are observations, not approved locks.
  Inspect the paired source context before adding a term. These list-of-records indexes
  are not the `names`/`terms` schema accepted by the glossary importer; select and
  convert reviewed entries before importing, or edit the shared glossary directly.
- Generated comparisons against another target game are derived reports. Use the
  actual prequel records for provenance and compare against the current game's source.
- Some normalized corpora keep `*-japanese.json` and `*-english.json` in one mixed
  folder. For the shared paired index, materialize one Japanese directory and one
  English directory under the current workspace, with corresponding files named
  identically. Preserve aligned logical keys and copy only text records. Do not pass
  the mixed folder as both languages or guess alignment by text similarity.
- Paired JSONL records with stable IDs can likewise become two identically named
  JSON objects mapping the same IDs to their Japanese and English strings. Keep a
  separate reference entry per game so disagreements retain their provenance.

## Registering a reference

Two shapes:

- **embedded** - a translated data folder that carries `_original` sidecars, so JP and
  EN both live in one tree.
- **paired** - explicit JP and EN normalized JSON folders.

Use `add_embedded_reference(game_root, title, translated_data)` or
`add_paired_reference(game_root, title, source_data, translated_data)` from the live
`util.reference_games` module. For supported raw RPG Maker or WOLF game-folder pairs,
`add_game_pair_reference` prepares isolated normalized copies under the current project.
Run helpers with the DazedTL application on Python's import path. Register all requested
games separately; do not replace the existing registry with a single last-used reference.

## The hard part: aligning the two sides without array indices

A translated tree can gain or lose commands, so **index-based alignment is wrong from
the start.** Walk the JSON emitting `(logicalPath, string)` pairs instead:

- Iterate dict keys `sorted()` for determinism, and skip `_original`.
- When a list looks like a command list (every element a dict with an int `code`),
  key by **`command-{code}/{ordinal}` where ordinal is a per-code running counter,
  not the array index.** That survives insertions and deletions of *other* codes.
- Join a message run into one record before keying it, using the header-to-follower
  map:
  ```python
  _MESSAGE_FOLLOWERS = {101: 401, 105: 405, 108: 408, 355: 655}
  ```
  Consume the header, then every consecutive follower, join the texts with `\n`, emit
  at path `.../text`, and skip the cursor past them.
- Emit choices individually at `.../choice/{i}`.

Keep a pair only when `source != translation` **and** the source actually matches
`[一-龠々〆〤ぁ-ゔァ-ヴー]`. An identical pair teaches nothing, and a pair whose source
is already Latin is not a translation.

## The index, and disagreement

Aggregate to `source -> [{reference_id, title, translation, occurrences, examples[:3]}]`.

**Keeping a list rather than a single winner is the point.** Two references
disagreeing about the same Japanese line is exactly what you want surfaced, not
silently resolved by whichever loaded last.

Cache-validate the whole index by a registry hash plus per-entry folder fingerprints,
and give every artifact a `content_sha256`. Then intersect the index with the current
game's own source strings so only overlapping lines are surfaced - the rest is noise.

## Feeding it to the model: advisory, not authoritative

For setup/research handoffs, name the count and point at a local evidence file. For
translation batches, consume only the matched evidence from the shared request-context
compiler; do not paste a complete prequel corpus into every provider request. Frame
historical matches explicitly:

> the current game's meaning and glossary remain authoritative. Investigate conflicts
> instead of blindly copying old wording.

A previous translation is evidence about *this* line, not a decision about it. The old
game had a different cast, a different register, and possibly a different mistake. A
reference index that reads as authoritative will happily propagate a wrong term across
every game you own.
