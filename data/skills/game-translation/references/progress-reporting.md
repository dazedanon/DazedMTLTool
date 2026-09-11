# Compact progress reporting

Use this during every Len task, including preparation, direct/API translation,
resume and QA. The tab reads `.dazedtl/len-method/progress.json` for its compact
panel. Keep explanations and historical evidence in `status.md`. The agent
maintains both; the user should not need another prompt or manual bookkeeping.

After each saved batch or milestone, at least every 10 minutes during active work, and before pausing or handing off, export
current unit records and run:

```bash
python DAZEDTL_ROOT/scripts/len_translation.py progress-update \
  --game-root /path/to/game --input /path/to/report.json
```

`--input -` reads the same JSON from stdin. `progress --game-root /path/to/game`
reads the last snapshot and freshness warnings. These commands make no API calls.
Python adapters can call `util.len_progress.update_progress(project, report)`.

## Report format

Send a complete report each time. Missing metrics become unknown and missing phase
states become pending; the command never guesses from the narrative log. Keep a
report template in the pipeline if needed, updating checkpoints as work advances.

```json
{
  "phase": "translation",
  "phases": {"preparation": "complete", "extraction": "complete"},
  "text": ".dazedtl/len-method/work/text-units.json",
  "images": ".dazedtl/len-method/work/image-units.json",
  "inputs": [".dazedtl/len-method/work/source-manifest.json"],
  "blocker": "",
  "next_action": "Translate the remaining map dialogue."
}
```

- `phase`: `preparation`, `extraction`, `translation`, `injection`, `qa`, `patch`,
  or null when no phase is active. This is the last reported activity, not a claim
  that a process is currently running.
- `phases`: those same keys with `pending`, `active`, `complete`, `blocked`, or
  `out_of_scope`. Several phases can be active when work overlaps; `phase` identifies the current focus and defaults to active.
  Set preparation-only tasks' later phases out of scope. Report QA/playtesting and
  patch checkpoints from actual evidence, never from a translation count.
- `text`, `images`: game-relative paths to saved unit exports below, or null before
  measurement. Omit images when the project's image scope is disabled.
- `inputs`: game-relative source/evidence file paths to watch for changes. Include
  current source manifests/files and any guidance whose changes require review.
  Files must exist inside the game folder. Unit exports and image files are also
  watched automatically.
- `blocker`, `next_action`: one short line each, up to 240 characters. Empty blocker
  means none reported. Put detailed explanations in `status.md`.

## Count saved units, including unfinished ones

Adapt the existing store's exporter rather than maintaining incrementing counters.
Each text/image export uses this envelope:

```json
{
  "complete": false,
  "units": [{"id": "Map001#/events/1/pages/0/list/1", "source": "はい。"}]
}
```

Set `complete` true only when the export contains the entire independently audited
corpus for that metric and scope. Otherwise the panel shows completed units over the discovered denominator with a provisional percentage, explicitly marking full coverage unaudited.
Before any export exists, the denominator and percentage remain unknown. Include every in-scope occurrence, including
untranslated units; successful API responses alone are not a denominator. An audited
empty corpus is `complete: true, units: []`, displayed as zero units.
Identical duplicate IDs count once; conflicting duplicates reject the report.
Use stable occurrence IDs so two speakers saying the same text remain two units.

For **text**, `source` is the exact current source string. Optional `translation`
is the saved, accepted output; null or empty means unfinished. Carry these fields
from the saved translation/review record:

- `translated_from_sha256`: SHA-256 of the exact UTF-8 source used to produce the
  translation. Only matching source/output pairs count as translated.
- `reviewed_sha256`: a review fingerprint covering both source and translation.
  Its definition is `sha256((source_sha256 + ":" + translation_sha256).encode("ascii")).hexdigest()`.
  `util.len_progress.review_fingerprint(source_bytes, translation_bytes)` produces it.

Compute the source fingerprint when saving an accepted translation and the review
fingerprint when its review finishes. **Do not regenerate fingerprints just to
make old output count as current progress.** Source changes invalidate translation
and review; changed translations need another review. Existing stores without
fingerprints need source alignment and review evidence checked before backfilling
them. API failures and pending requests do not count.

For **images**, use the same fields, but `source` and `translation` are game-relative
paths to separate original and translated files. Fingerprints use their exact bytes.
The helper checks files exist; visual review and injection validation still belong
to the pipeline. Keep the original file available after injection. Include all
image assets in scope, not just rendered replacements.

## Freshness, resume and delivery

The helper calculates counts, validates updates, fingerprints listed artifacts and
replaces the snapshot atomically. Re-running it cannot add duplicate completions.
Marking translation complete requires known totals and all scoped text/images
translated. Other phase checkpoints require the corresponding validation, playtest
or packaging evidence and are explicitly reported by the agent.

The UI refreshes while visible. It shows the last update time and warns when tracked
files change/disappear or image scope/project instructions change. These checks
cover listed artifacts and project scope, not unregistered engine files. The UI
uses file timestamps/sizes to keep refresh cheap; the CLI's `progress` read also
always verifies content hashes, including when timestamps and sizes were preserved. Recheck source, outputs and
downstream checkpoints before generating a new report. Do not
retain completed injection/QA/patch checkpoints when changed output invalidates
them. Disabled bars remain the last reported counts.

Prompt refreshes and resume never overwrite `progress.json`. Its artifact paths are
relative to the game.
Keep `progress.json` and `status.md` in `.dazedtl/len-method/`, authored exports under `work/`, and all of them in the separate workspace backup.
These are local working records and must stay ignored on both patch branches. Unknown totals,
out-of-scope work and incomplete playtesting must stay explicit. A 100% text bar
does not mean the game is ready to deliver.

## Active time and estimates

A report may also include these optional fields:

```json
{
  "timing": {"translated": 3600, "reviewed": 1200},
  "estimates": {
    "qa": {"low_minutes": 30, "high_minutes": 60,
           "basis": "Targeted locale/input and two changed window classes; excludes a full playthrough."},
    "patch": {"low_minutes": 10, "high_minutes": 20,
              "basis": "Rebuild, hash audit and clean-copy install/restore with existing tooling."}
  }
}
```

Merge these fields into the complete phase/artifact report; sending only this fragment resets omitted metrics to unknown.
`timing` records cumulative active translation/review seconds for this corpus, not elapsed time since starting the task.
Exclude sleep, provider queue waits, user pauses and unrelated work.
The helper retains up to 20 samples and estimates remaining discovered text after two compatible samples, at least 60 active seconds and positive completed work.
Its 0.7–1.5 multiplier around the measured remaining time is a planning range, not a confidence interval or promised wall-clock finish.
A changed corpus/scope, regressed counts or reset clock discards incompatible throughput history.
Without valid samples it displays the missing estimate explicitly and identifies the next measurement needed.

`estimates` uses phase names from `phases`, with finite nonnegative lower/upper remaining active minutes and a short basis explaining assumptions/exclusions.
Use it for preparation, extraction, images within translation, injection, QA and patch work that text throughput cannot predict.
Update these values as work finishes; zero text remaining does not estimate the unfinished images or QA.
Estimates are paused while blockers or stale-evidence warnings apply, and completed/out-of-scope phases are omitted.
Do not add overlapping phase times into a claimed wall-clock deadline.

At each milestone, also give a short human update: completed/discovered text and review count, whether coverage is audited, image status, current phase, remaining active-work range, next checkpoint and any blocker.
During preparation, report the files/tracks inspected and remaining inventory even before source-unit counts exist.
Before a provider wait, distinguish queued requests from accepted translations and give the next reconciliation point.
Keep long paths, full test matrices and narrative history in `status.md`; the main update should make progress understandable without opening that file.
