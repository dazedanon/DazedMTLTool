# Yume Yoshiwara — Claude Batch preparation kit

Prepared for **夢吉原のあやかし妓楼 v1.041ex**, Electron 7.1.2 / Node 12.8.1,
TyranoScript v5, 1280×720. The original ASAR and saves have not been changed.
No translation batch or other paid API request has been submitted.

## Extracted material

- **13,948 text units / 18,702 occurrences / 386,042 source characters.**
- **10,418 dialogue units**, retained separately by source location and speaker.
- UI and other repeated labels are deduplicated. There are 1,298 unique choices,
  275 positioned labels, 1,529 code literals, 78 notices, 57 name labels, 77 JS
  strings, 29 ruby readings, 61 punctuation units, one title, and 125 state-value
  display copies.
- 603 included scenario/plugin files. The archive contains 607 KS files total;
  plugin samples/unloaded files are kept in the snapshot but omitted from requests.
- All non-dependency text files and eight font files are snapshotted in `source/`.
- **4,537 original image/artwork files**, 1,775,964,044 bytes, are available in
  `images_for_review/` beside this README in the durable project, and in the
  game's `images_for_review/` folder. Open `index.html` to filter by filename and
  open full-size originals. `manifest.csv` is available for manual review notes.
  No images were translated, redrawn, OCRed, or uploaded. Audio was not duplicated.

## Cost and turnaround

Using **claude-sonnet-5, adaptive thinking, low effort, 5-minute cache**:

| Scenario | Estimated USD |
| --- | ---: |
| Optimistic cache reuse | 2.35 |
| Assumed 40% cache hits | 3.09 |
| Every request misses cache | 3.59 |
| Equivalent batch with no caching | 3.32 |
| Planning allowance including uncertainty and retries | 6.51 |

Plan **$3–$4 for the first text pass, approximately $7 with margin**. This is an
offline proxy over 358 prepared requests, about 2.04M input tokens before caching
and 256K output tokens. Output and thinking usage are estimates. Resolve the six
remaining minor-name readings, lock the glossary, and rerun `dryrun` before text
submission. A one-request names batch is approximately one cent.

Allow roughly **1–4 hours per submitted batch** based on the local reference runs.
This is a planning range, not an SLA. Anthropic allows processing up to 24 hours
and requests can expire. A names phase and text phase are sequential; English
layout, display-map integration, saves, and gameplay QA take additional work.

Prices checked 2026-09-06 against the official
[pricing page](https://platform.claude.com/docs/en/about-claude/pricing) and
[Batch documentation](https://platform.claude.com/docs/en/build-with-claude/batch-processing):
$1/M input and $5/M output for Sonnet 5 Batch, with the same 50% discount on cache
tokens. Five-minute writes cost 1.25× input; hits cost 0.1× input.

## Commands

Run from this project directory. Python 3 is required. The Anthropic package is
only imported for network commands; extraction, dry run, and tests are offline.

```powershell
python -X utf8 tl.py dryrun
python -X utf8 tl.py validate
python -X utf8 scripts/test_tooling.py
python -X utf8 tl.py inject --identity --output qa/identity
python -X utf8 tl.py prepare --phase names
```

`prepare` returns an immutable run ID and a manifest to inspect. To run it later,
set `ANTHROPIC_API_KEY` in your environment, then use the returned ID:

```powershell
python -X utf8 tl.py submit RUN_ID
python -X utf8 tl.py status RUN_ID
python -X utf8 tl.py fetch RUN_ID
python -X utf8 tl.py lock-names
python -X utf8 tl.py dryrun
python -X utf8 tl.py prepare --phase text
```

The API key was absent from the current session. It is never written into this
project. A credential fingerprint and endpoint bind saved jobs to the submitting
environment. There is no automatic live/full-price fallback. The existing SDK
was available locally; new environments can install `requirements.txt`.

The names phase writes validated translations to the store; `lock-names` copies
them into the roster while rejecting conflicts with already locked spellings.
Six source names remain unresolved: 静芳, 香蛾屋の主人, 香蛾屋の遊女, 陶, 黒蛇, 玉菊.
Meron's spelling follows the game's `meron` registration, not an assumed kanji
reading. Review name results before locking and before preparing dialogue.

For local corrections, `import` accepts a JSON object keyed by catalog unit ID:

```powershell
python -X utf8 tl.py import reviewed-corrections.json --overwrite
python -X utf8 tl.py validate --complete
```

Failed/truncated/refused replies are retained in each run's report and are not
imported. After fetching, a new `prepare` selects only missing units. Submission
is protected by a nonblocking filesystem lock, immutable manifests, overlap
checks and a checkpoint before each network POST. If the POST outcome is unknown,
the saved `pending` marker prevents a duplicate charge. Reconcile the custom IDs
in Claude's batch list before changing that state. An abandoned `operation.lock`
may be removed only after confirming the recorded process is no longer running.

## Verification and limits

- 12 offline tests pass, including actual import validation, out-of-order batch
  fetch, usage aggregation, and a lost submission response that blocks resubmit.
- Identity injection of **519 text-bearing files** is byte-exact. Source spans,
  overlap, UTF-8/CP932 encoding and mixed line separators are checked.
- The shipped parser processed all 607 KS files / 202,853 elements. Whitespace
  probes confirm quoted ASCII spaces disappear, NBSP survives, and `_ ` preserves
  a leading continuation space. Source duplicate-label warnings are recorded in
  `reports/parser_probe.json`; they are original, not a translation regression.
- Every extracted image path and byte length matches its ASAR entry. This is
  extraction verification, not an image-content or native-decoding review.
- Production translation coverage is **0%**, intentionally. `validate --complete`
  must fail until translations exist. `validate` checks preparation integrity.
- No in-game English build, save test, layout pass, or paid API smoke test has
  been performed. The batch transport is tested with fake responses, not a claim
  of live account/model access.

## Findings that the eventual patch must preserve

1. **State and display are coupled.** Japanese names, ranks, traits and conditions
   appear in comparisons/assignments 12,414 times. Those values remain unchanged.
   The catalog supplies 125 separate `display_value` units; 3,748 dynamic KAG
   display sites are inventoried. A renderer-only mapping is still required before
   release. `other_check.js` also compares rendered trait labels, so both compared
   displays must use the same canonical translations.
2. **Old parser spacing.** `render_site` applies NBSP only in KAG attributes,
   including nested JS literals; standalone JS and iscript retain ordinary spaces.
   Full message continuation and word-insert fitting require final output checks.
3. **Saves.** Preserve package identity, projectID, character IDs, labels, control
   structure and parsed indices. The game's executable-adjacent save is untouched.
   Cached display data and the state map need a separate save/load test.
4. **Original typo.** `data/scenario/status_char1.ks:156` has an unterminated
   `elsif` tag. It is excluded, recorded and preserved; it is not prose.
5. **Disabled editor UIs.** `title.ks:121` uses `onlypartset=true`, and line 125
   uses `manager=false`. Their disabled manager interfaces and selectors are not
   translation targets. The active plugin behavior remains included.
6. **Shipping is a later stage.** English deployment is deliberately unavailable
   in this preparation kit. The span renderer exists for validated staging and
   identity proof; runtime display mapping, font/box fitting, actual translated
   parser invariants and installation/save testing must be implemented before a
   playable patch. No image-replacement path has been built.

## Reuse and preservation

The lexer, masking, source-site records and extraction base were copied from
`Tools/Game Translation/Reference Pipelines/TyranoScript (AjinSyoujyo)` and adapted
for this game. `scripts/project.py` owns game-specific classifications;
`scripts/claude_batch.py` owns API manifests and validated results. Source hashes
are checked on consumers; changing the source snapshot invalidates prepared runs.
Reports contain private source excerpts. This is a development project, not a
player distribution. Preserve this directory before deleting the game.
