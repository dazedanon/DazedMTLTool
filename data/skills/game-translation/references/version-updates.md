# Version updates: carrying a translation onto the next release

The game ships v1.03.
You are holding 40,000 translated lines against v1.02, hand-fixed wrap points, a locked glossary, and edited PNGs.
Re-translating is unaffordable and throws away every manual fix.
Carrying it forward by hand is worse, because the lines that changed are exactly the ones you cannot spot by eye.

**Reference implementation:** `DAZEDTL_ROOT/util/version_update/git_workflow.py`

**DazedTL Len projects:** begin with `references/project-lifecycle.md` and the live
`scripts/len_translation.py git-status` / `git-setup` commands. Newly created Len
baselines preserve native game bytes and the reviewed project ignore policy.
`dazedtl.preserveGameFiles` and the `DazedTL-Preserve-Game-Files` commit trailer carry
that choice into later shared updates. The normalization advice below applies to
projects whose engine and established baseline use normalized text; do not apply it
over a native-byte baseline or force the RPG Maker file allowlist onto another engine.
(3,014 lines) drives the flow, `gui/version_update_tab.py` (1,326 lines) is the operator
view, `gameupdate/` holds the in-game notice (`TranslationUpdateCheck.js`,
`patch-config.txt`), and `data/skills/post_update_translation.md` is the reusable prompt
for scoping a post-update pass by diff. Wolf does the same job in one command:
`wolf translations-merge --old old/ --new new/ -o result/`.

**Both naive approaches fail, and they fail silently.**

`diff -r old/ new/` reports every file as 100% changed.
RPG Maker writes `Map001.json` and `CommonEvents.json` as one gigantic single line, so a one-word official fix is a whole-file rewrite.
Extractor dumps come out in whatever order the walker visited, so a re-run reorders entries that did not change.
A Windows checkout flips LF to CRLF and every line differs on both sides.
The result is one giant conflict, and "resolve" degenerates into picking a whole file, which means losing either the update or the translation.

**Matching by array index breaks the moment anything is inserted.**
Insert one `401` at the top of a page and every command index below it shifts by one.
Insert one `.ks` line and every parsed element index after it shifts.
Nothing errors.
The translation just lands on the wrong lines, from the insertion point to the end of the file, and you find out from a player screenshot.

The whole discipline below exists to turn a version bump into **a per-string merge over a stable key**.

---

## 0. Pick the path before you touch anything

| You have | Path | Identity mechanism |
|---|---|---|
| A committed, unmodified copy of the **old official release** | **3-way merge** (preferred) | none needed - git's merge base does it |
| Only the new Japanese and your English | **Translation memory keyed on source text** | key table in §2 |

**Path A is strictly better and costs nothing to guarantee: commit the clean original before you translate a single line.**
With a merge base, git applies the official delta `originalV1 -> originalV2` as a patch onto the translation, and every untouched translated line survives with no key matching at all.
Without it you are reduced to diffing new Japanese against your English, which reports every translated line as a conflict.

Path B is the fallback for a project you inherited, or for engines where you only ever see extractor output.
Both paths require §1 first.

---

## 1. Normalize before you diff

**Canonically pretty-print every tracked JSON before the first commit, or a version bump is a whole-file conflict.**

```python
json.dumps(document, indent=4, ensure_ascii=False, allow_nan=False)
```

`indent=4` puts each object member and each array element - each event-command `parameters` string - on its own line, so a changed dialogue line becomes a one-line hunk that merges independently of its neighbours.
Then normalize to LF.
Apply this **on disk before `git init`** and before the baseline commits, and again to **every incoming official tree**, so the first diff is never a whole-file reformat.

Safety rails, all of them required:

- A duplicate object key or a `NaN`/`Infinity` constant **raises and leaves the file byte-identical** with a visible warning, rather than silently rewriting it.
- Files that are not valid UTF-8 are skipped. Treat any NUL byte or decode error as "not text".
- Sparse arrays keep their `null` holes, because the round trip is a real parse and not a text transform.

RPG Maker `plugins.js` gets the same treatment with jsbeautifier at `indent_size=2, max_preserve_newlines=2, end_with_newline=True`, gated on the file actually containing `var $plugins =`.
That gate is what lets an official plugin-parameter bump merge cleanly against a translator-added plugin entry.

### Line endings: four defenses, all mandatory on Windows

Skip any one and 100% of files conflict on the next update.

1. **Force every tracked UTF-8 text file to LF**, with an explicit exemption list for `.bat`, `.cmd`, `.reg`, which are CRLF-sensitive when executed. This is a *repository* rule and it fights the engine rule. Where a parser demands CRLF (older KiriKiri, TyranoScript projects that mix CRLF and LF within one project - see `references/engine-tyranoscript.md`), exempt that extension too.
2. **Read files as bytes and decode manually.** `Path.read_text()` uses universal newlines and hides CRLF, so already-normalized files look unchanged while CRLF blobs stay in git forever.
3. **Write git subprocess stdin as raw UTF-8 bytes, never text mode.** Windows text-mode pipes translate LF to CRLF, which corrupts `hash-object --stdin` blobs and embeds a trailing CR into the path names fed to `update-index --index-info`.
4. **Re-apply `core.autocrlf=false` and `core.eol=lf` at every entry point** - bootstrap, register, preview, apply, continue, abort - not once at init. Local config is not carried by clone or push, so a collaborator with global `autocrlf=true` checks out CRLF and rewrites every file.

Write blobs with `git hash-object -w --no-filters` so no clean/smudge filter can touch game bytes.

---

## 2. Identity: what survives re-ordering

**Never key on a position.** Array index, command index, line number, byte offset, and dump order are all invalidated by an insertion anywhere above them.

**Key on the normalized source string, with the container path as tiebreaker.**
Normalize for the key only: strip trailing whitespace, LF-only, NFC.
Do **not** strip control codes - `\C[1]`, `[r]`, `%s`, `\n[1]` are part of the string's identity and of its translation.

Prefer an authored key when the engine has one.
An authored key is written by the game's own author and survives reordering, retranslation and reflow. A derived key does not.

| Engine | Authored key, if any | Coordinate that survives an official edit | Coordinate that does NOT |
|---|---|---|---|
| RPG Maker MV/MZ | none for events | file + event id + page index | command index within the page |
| RPG Maker VX Ace | none for events | same, via RV2JSON | command index |
| Wolf RPG | none | common-event id, CDB type/entry id | command index |
| TyranoScript | `*label` names | scenario filename + nearest preceding label | parsed element index, line number |
| KiriKiri `.ks` | `*label` names | same | line number |
| SRPG Studio | object id in the JS data | the id | array position |
| Unreal `.locres` | **namespace + key** | the key, always | anything else |
| Unity I2Loc / CSV tables | **term / key column** | the key, always | row order |
| Unity Mono/IL2CPP hardcoded | none | asset path + field path | list index |

For the keyless engines the composite key is:

```
sha256(f"{container_path}\x00{event_id}\x00{code}\x00{source_text}")
```

with a **fallback to `sha256(source_text)` alone at lower confidence** when the container moved.
The two-tier lookup is what lets a scene that was relocated from `Map012` to `CommonEvents` keep its translation.

**Duplicate source strings need context in the key or they cross-contaminate.**
`はい`, `いいえ`, `……` and single-word menu items occur hundreds of times and are legitimately translated differently by context.
If the exact key misses and the text-only key hits **more than one distinct translation**, do not auto-carry. Flag it.

---

## 3. Classify every unit before spending a token

Produce the counts first.
An update that turns out to be 1 changed line and 4 new ones does not need a pipeline run.

| Class | Test | Action |
|---|---|---|
| **unchanged** | key hit, source bytes identical | carry the translation verbatim, cost zero |
| **moved** | key hit via fallback, source identical, container differs | carry, no action, log the move |
| **markup-only** | source differs, but identical after masking control codes | **re-apply the new markup to the existing translation, do not re-translate** |
| **changed** | source differs after masking | re-translate, and pass the old source + old translation as context so the editor sees a diff, not a blank |
| **fuzzy** | no key hit, best `difflib.SequenceMatcher(None, a, b).ratio() >= 0.85` on the masked strings | present the near match as a suggestion, require a human or a second-pass LLM confirm |
| **new** | no key hit, no match above threshold | full translation pass |
| **removed** | old key with no new counterpart | drop from the shipped patch, **keep the entry in the memory file** - cut content comes back in the next release |

Rules that matter more than the table:

- **Mask control codes before comparing, then compare masked.** A line whose only change is `\C[6]` -> `\C[2]` is markup-only. Re-translating it burns money and risks a glossary drift on a line nobody changed.
- **Never delete a translation memory entry.** Removal is a shipping decision, not a memory decision.
- **A fuzzy match is a suggestion, never an auto-carry.** Silently carrying an 0.85 match is how an official bugfix to a number or a name gets reverted by your own patch.

---

## 4. Merge

**Resolve conflicts hunk-by-hunk with official-wins, never file-by-file.**
"Take theirs for the whole file" discards every unrelated translated line in a conflicted map.

For each path from `git diff --name-only --diff-filter=U -z`, read `git ls-files -u -z -- <path>` and split each record on TAB then on spaces to get `(mode, oid, stage)`, building `{1: base, 2: ours/translated, 3: theirs/official}`.

| Stage state | Meaning | Action |
|---|---|---|
| stage 3 missing | official release deleted the file | `git rm -f -- <path>` even though the translation modified it |
| all three present | real content conflict | `git merge-file --object-id --theirs <ours-oid> <base-oid> <official-oid>` |
| binary, or add/add | no textual base | `git checkout --theirs -- <path>` then `git add` |

`merge-file --object-id` works purely on object IDs with no worktree files.
It merges non-overlapping hunks and resolves only the genuinely overlapping ones in favour of the official side, leaving **no conflict markers behind**.
Install the merged blob with `update-index --add --cacheinfo <official-mode>,<merged-oid>,<path>` - take the **official** file mode, not yours - then `checkout-index --force` to write it to disk.

If `merge-file` fails and stderr does not mention `binary`, **raise** rather than guessing.
Re-query conflicts afterwards and raise if any remain.
Run the continuation with `GIT_EDITOR=true`.

The payoff is exactly this: official text wins at the conflicting line, a translated line nine rows away survives untouched, and the new official feature line lands.

### Preview: predict per file what the merge will destroy, before any ref moves

Dry-run the same `merge-file --object-id --theirs` that apply will run, and classify each changed path from the `(base, translated, official)` blob triple **in this order**:

1. Translation never touched the path -> `New file` / `File removed` / `Official changes applied`. Not a loss.
2. Official deleted it while the translation changed it -> `whole_file_replaced`, `Translated file removed`.
3. Official added a path the translation also added, or the translation deleted it -> `Translated file replaced by official file`.
4. Translated blob == base blob -> nothing to lose.
5. Translated blob == official blob -> `Official content already present, file metadata updated`.
6. Otherwise run the merge. **If the merged blob equals the official blob exactly, the whole translation was swallowed** -> `Entire translated file replaced by official content`, `whole_file_replaced`. Else `Merged with translation edits`.

A non-zero return or non-hex output from step 6 means binary. Report a full replacement.

Alongside it compute:

- `overlapping_paths` = official-changed INTERSECT translation-changed
- `already_present` = proposed blob identical to translated blob
- per-file added/deleted line counts from `git diff --numstat --no-renames -z`, where `-` means binary
- a separate list flagging every tracked translated **image** about to be replaced or removed (`references/image-translation.md` work is expensive and invisible in a line count)

Without this gate you discover "these four files lost their translation entirely" by playing the game.

---

## 5. Git practice

### The three-branch model

One repo, whose worktree **is** the live translated game.
Branch `original` holds nothing but clean official release trees, one commit per release.
The translated branch is whatever the project already uses (`main`, or a legacy `translation`), recorded in repo-local git config so no tool ever guesses or renames it.

An update is four steps:

```
1. build a tree from the new official folder, using the previous `original` commit as base
2. commit-tree it, parent = previous original commit,
   subject = "patch: update original game files to <ver>"
3. update-ref refs/heads/original <new>   # pass the OLD value as the compare-and-swap arg
4. git cherry-pick <new original commit>  # onto the checked-out translated branch
```

Preconditions, checked before any ref moves: translated branch checked out, no cherry-pick in progress, worktree clean.
Rollback is exactly `git cherry-pick --abort`.

**This layer must know nothing about any engine.**
It never parses or reconstructs a game file, so it works identically for RPG Maker JSON, `.ks` scripts and Wolf dumps.

### Plumbing hygiene: never check anything out

The worktree is the translator's live game. A stray checkout overwrites their work with the baseline.

- `mkstemp` a name, close and **unlink** it, pass `{"GIT_INDEX_FILE": name}` so git creates it fresh and the real index is never disturbed.
- Batch all unmodified files through **one** `git hash-object -w --no-filters --stdin-paths` call with a generous timeout, and assert the returned hash count equals the input count. Only reformatted files go through individual `--stdin` calls.
- Populate the index with a single `update-index --index-info` feed of `<mode> <oid>\t<path>` lines. Express deletions as `0 0000000000000000000000000000000000000000\t<path>`.
- Mode from `S_IXUSR|S_IXGRP|S_IXOTH` -> `100755`, else `100644`.
- Commit with `git -c user.name=... -c user.email=...@invalid commit-tree` so no repo or global identity is required and the author is never the user.
- **Reject symlinks outright** in any game tree, and reject paths containing CR, LF or TAB.
- Parse `git worktree list --porcelain` and refuse to update if `refs/heads/original` is checked out in another worktree.
- Re-validate every conflict path git hands back as relative, `..`-free, and inside the game prefix before using it.

**To register an existing translation as a branch without writing to it:** write both branches into objects, point the refs at them, run `git read-tree <translation commit>` (index only, no checkout), then demand `git status --porcelain=v1 -z` come back empty. List up to 8 offending paths otherwise.

### The already-present case

**Handle "the official patch is already in the translation" explicitly, because git aborts an empty cherry-pick and leaves the branches wedged mid-pick.**

Before cherry-picking, compute the official delta paths with `git diff --name-status --no-renames` between `original^` and `original`.
For each, compare the raw `git ls-tree -z <commit> -- <path>` **whole record** (mode, oid and path must all match) between the new original commit and the translation commit.

If **every** changed path is already byte-identical on the translation branch - the translator hand-applied the update, or the release only touched files you already carry - skip the cherry-pick and create a marker commit reusing the translation's existing tree:

```
commit-tree <existing tree> -p <translation commit>
subject: "translation: record already-present original game version <ver>"
```

installed with a compare-and-swap `update-ref`, and reported as no content change.

Treat any **other** empty cherry-pick as an error: match `empty` in git's combined stdout+stderr, run `cherry-pick --abort`, report that no version marker was created, and warn separately if the abort itself failed.
Stamping a version you did not verify as present is how you ship a patch labeled v1.03 that is actually v1.02.

### Version identity lives in a commit trailer

Every release commit carries a `<Tool>-Version: <ver>` trailer.
Recover it by scanning the last 100 commit messages of a ref with `--format=%B%x00`, splitting on NUL, and returning the first `^<Tool>-Version:\s*(.+?)$` match.

Fallbacks for repos predating the trailer, in order:

```
tags pointing at the commit, filtered by
  (?i)(version|ver\.?|v|update(d)? (original )?game files to)[\s:._-]*(\d+(\.\d+)+)
  taking the lexicographically last
then the same regex against the commit subject
```

**Mark applied updates with a `patch:` subject prefix.**
To answer "which official update has actually been applied and still needs localizing", scan only for commits whose first line case-foldedly starts with `patch:` and return that commit's trailer.
That deliberately excludes baseline, registration and already-present marker commits, so a localization pass is never run against a registration commit that changed nothing.
Hand the translation agent that commit, its parent, and its changed-file list as the exact scope. That is the whole "what is new and still Japanese" question, answered as a one-commit diff instead of a full re-scan.

### Keep your own tooling out of the official tree

**A clean official game folder contains none of your tooling, so snapshotting it as the new baseline shows every one of your files as a deletion, and the merge removes them from the shipped translation.**

Maintain an explicit tool-owned path set and preserve it on **every** official tree you build - preview, apply, and previous-official baseline validation alike.

- Match a case-folded **first path component** against tool directories: `.agents`, `.codex`, your tool's dot-dir, image-work dirs, `dictionaries`, `docs`, `gameupdate`, `prompts`, `skills`.
- Match a single-component name against root files: `.gitattributes`, `.gitignore`, the updater `.bat`/`.sh`, `patch-config.txt`, `patch-config.example.txt`, `readme.md`, bundled tool exes and their licenses.
- Diff the tool-owned subset of the proposed official tree against the base ref through a temporary index, and rewrite any difference back to the base version, or delete it with a zero-oid line if it did not exist in the base.
- Append your tool's metadata dir to `.git/info/exclude` so removed legacy updater state cannot re-enter the branches.
- Keep local-only artifacts out of the asset manifest entirely: saves, logs, caches, `previous_patch_sha.txt`, `Save*`, `wolf_json/originals/`, `.md`/`.rst` docs.
- Install the bundled ignore policy **without discarding project rules**: strip complete `# BEGIN/END <tool> settings` blocks before comparison so an equivalent block is not relocated every run, recognize and replace the previous bundled template rather than preserving it as a user rule, and re-append anything left under a `# Existing project rules` header.

### Binaries: gitignored, but still versioned

Committing every PNG and OGG makes the patch repo hundreds of MB and unusable as a public download.
Plain-ignoring them means an official art or audio update never reaches the player's install.

- Ship a **deny-by-default** `.gitignore`: `*.*`, then whitelist the text extensions you actually merge - `.json`, `.js`, `.txt`, `.csv`, `.rb`, `.rvdata2`, `.ks`, `.tjs`, `.ain`, `.yaml`, plus named WOLF `.dat` files.
- Track the ignored files in a manifest of `{path: {sha256, size, mode}}` stored **outside** the repo content, under `<git-common-dir>/`, keyed by a hash of the game prefix so several games in one repo do not collide.
- **Decide what is ignored by asking git, never by reimplementing the matcher.** Pipe NUL-separated virtual paths to `git check-ignore --no-index -z --stdin` and accept exit codes 0 and 1 only, so nested `.gitignore` files, `.git/info/exclude` and the user's global excludes all apply.
- Validate the manifest strictly on load - `sha256` matches `[0-9a-f]{64}`, mode is `100644` or `100755`, path is relative with no `..` and no CR/LF/TAB - and treat a bad manifest as a hard error.
- Make the sync transactional: copy each file to a staging dir, re-hash it there and abort if the source changed mid-run, back up each destination, `os.replace` one at a time, and on any failure restore backups in reverse order and report which rollbacks also failed.

**The commit and the file copy cannot be one atomic operation.**
Write a `pending-assets.json` plan - source folder, version, original commit, manifest digest, overlay flag - *before* the ref moves, and clear it only after the copy succeeds.
On resume, re-derive the manifest from the source folder and refuse if the digest changed.
Without the pending plan, a crash between commit and copy leaves a repo that claims v1.03 with v1.02 art.

### Copy-over patches are overlays, not releases

**Many doujin releases ship an "extract over your game and overwrite" folder, not a full release. Treat it as an overlay or you delete most of the game.**

In overlay mode, build the tree **without** first staging a deletion for every existing index entry under the game prefix.
Only supplied paths are written, so files the patch omits survive from the previous `original` commit.
Documented limitation: **a copy-over patch can never express a deletion.**

Merge the asset manifest the same way rather than replacing it:

```python
proposed = dict(baseline); proposed.update(supplied)
```

Guard the classic mis-drop where the operator selects `<game>/www` but the patch archive's own root already contains `www/`, which otherwise creates `www/www/data/...` inside the tracked tree and propagates into the merge and the shipped ZIP.
For each supplied file, test whether `<parent-of-selection>/<rel>` exists in the original tree (direct match) against `<selection>/<rel>` (intended match).
Refuse if **either** the selection's own folder name appears as a first path component of a supplied file, **or** there are at least 3 direct matches and `direct >= 4 * intended`.
Name a concrete example path and the folder that should have been selected in the error text.

---

## 6. Shipping the update to players

**Use the patch repo's commit SHA as the installed-version marker.**
It is content-exact, needs no version file inside the game, and cannot be faked by a partial copy.
Store one line in `gameupdate/previous_patch_sha.txt`.

The updater flow:

1. Resolve the branch head SHA via the forge API. Equal to the stored SHA -> no-op exit code.
2. Download the archive **at that exact SHA**, not at branch head, so a push mid-download cannot produce a mixed install.
3. Validate before use: reject 0 bytes, reject a missing `PK` magic. On failure, sniff the first 6 KB and report whether the body was an HTML error page or a forge JSON `message`.
4. Extract to a temp stage, require **exactly one root folder** in the archive, then copy **file by file** into the game root rather than moving the folder, so bundled tool binaries never leak into a game root that does not need them.
5. **Never delete anything.** A copy-over patch must not be able to remove a file.
6. Write the SHA back only after a successful extract.

Install a native `SetConsoleCtrlHandler` for `CTRL_CLOSE`/`LOGOFF`/`SHUTDOWN` that deletes the partial ZIP if the player closes the console mid-download.

Abstract the host behind a `forge=` key with aliases (`gitlab`/`gl`/`gitgud`, `github`/`gh`, `forgejo`/`gitea`/`fj`/`codeberg`) plus per-forge default hosts, defaulting legacy username/repo/branch configs to your original host.

**The release builder must refuse to stamp the SHA** unless all four hold:

- the game folder is on the configured branch
- `git status --porcelain --untracked-files=all` is empty
- an upstream is configured whose name matches the branch
- `@{upstream}` resolves to the same SHA as `HEAD`, meaning the commit is actually pushed

**Strip any existing `previous_patch_sha.txt` from the ZIP before writing your own**, or every fresh install thinks it is already up to date and refuses to patch.

### What the player has to be told

- **The game version the patch targets**, stated in the release text, because a player on v1.02 applying a v1.03 patch gets a mismatched merge and blames the translation.
- **Whether saves survive.** A new official version moves indices on its own, independently of your edits. Re-run the save-migration proof against the new version before release - see `references/save-compatibility.md`.
- **What is still untranslated.** New content ships Japanese if the update landed after your translation pass. Say so, or it reads as a broken patch.

---

## 7. Symptom table

| Symptom | Cause | Fix |
|---|---|---|
| Every file conflicts on update | JSON on one line, or CRLF, or both | §1 - canonical print + LF, applied to **both** baselines before the first commit |
| Whole file lost its translation after merge | file-level "take theirs" | §4 - hunk merge on object IDs |
| Translation lands on wrong lines from some point onward | keyed on index | §2 - key on source text, never position |
| Update applied but nothing changed, git errors | empty cherry-pick | §5 - already-present detection and marker commit |
| Your tooling vanished from the shipped patch | official tree snapshot showed it as deleted | §5 - tool-owned path preservation |
| Repo claims v1.03 but art is v1.02 | crash between commit and asset copy | §5 - `pending-assets.json` written before the ref moves |
| Most of the game deleted after applying a patch archive | overlay treated as a full release | §5 - overlay mode, no bulk deletion staging |
| `www/www/data/...` appears in the tree | wrong folder selected for a copy-over patch | §5 - direct-vs-intended match heuristic |
| Fresh install refuses to patch | `previous_patch_sha.txt` shipped inside the ZIP | §6 - strip it before writing |
| Collaborator's commit rewrites every file | their global `core.autocrlf=true` | §1 defense 4 - re-apply local config at every entry point |
