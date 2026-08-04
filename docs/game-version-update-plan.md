# Git Version Update Workflow

## Contract

Version Update transports official game releases through Git. It never performs
an engine-aware or semantic merge. Tracked UTF-8 text is normalized to LF line endings, except Windows
CRLF-sensitive scripts such as `.bat`, `.cmd`, and `.reg`.
Valid UTF-8 JSON is reformatted for stable textual diffs, using DazedTL's
existing four-space JSON representation.
RPG Maker `plugins.js` wrappers are formatted with the same JavaScript formatter
as Prepare so plugin configuration does not collapse into a whole-file conflict.

- `original` contains official release trees with deterministic JSON formatting.
- A repository-configured translated branch contains the working translation.
  Existing repositories keep their current branch name (for example `main`);
  repositories created by DazedTL default to `main`.
- Every official release is one reviewed commit with a `DazedTL-Version` trailer.
- The official release commit is cherry-picked into the configured translated branch.
- A conflicting file uses the new official copy and is reported for translation
  review.
- An interrupted cherry-pick can be continued official-first or aborted.
- A mandatory preview lists file changes, translation overlaps, normalized JSON,
  ignored paths, and formatting warnings before refs or working files change.
- The preview identifies official patch files already present verbatim on
  `translation`. If every patch file is already present, approval creates an
  explicitly labeled version-marker commit and does not claim game content
  changed. Any other unexpectedly empty cherry-pick is aborted as an error.
- Preview counts distinguish the official release delta (`original` to
  `original`) from the files that would actually change on `translation`.

## First-time reconciliation

Both engine workflows expose version tracking as the first task in Prepare, and
the Version Update page retains the same setup path. The GUI inspects the
selected translated game immediately. If `original` is
missing, the user supplies the matching clean original folder and its version.
The tool writes the original Git tree directly into repository objects and
records the current translated tree separately, so bootstrap never swaps or
replaces translated content. Both baseline trees receive the same deterministic
JSON formatting and LF line endings, and the translated working files are
normalized to match their recorded branch. This prevents formatting-only or
EOL-only whole-file diffs immediately after initialization.

Before either baseline is committed, bootstrap installs the bundled GameUpdate
`.gitignore`. Existing project rules are retained after the bundled rules, so
their later matches keep final precedence. The same combined policy is stored in
both branches. All imported paths are then evaluated through Git's own `check-ignore` behavior,
including nested `.gitignore` files, `.git/info/exclude`, and configured global
ignore rules. Ignored files stay on disk and are omitted from both branches.

This supports a new repository, an existing translation repository, and a game
stored below a repository subdirectory. Symbolic links are rejected because an
exact, portable tree cannot safely infer their intended target.

Legacy repositories are reconciled in place. A checked-out translated branch
such as `main` is registered by name when `original` already exists;
complete branch pairs that predate `DazedTL-Version` trailers receive no-content
metadata commits. If both expected branches already exist on another checked-out
branch, Prepare offers to switch to the registered translated branch.
The selection is stored as the repository-local Git setting
`dazedtl.translationBranch`. Prepare asks for confirmation before adopting an
existing branch and can change the registration later without deleting either
branch.

## Updating

The user supplies a clean new official folder and version. A preview creates the
proposed Git tree without moving either branch. Valid JSON is parsed and emitted
with `indent=4` and `ensure_ascii=False`. Other tracked UTF-8 text is normalized
to LF line endings, except Windows CRLF-sensitive scripts such as `.bat`, `.cmd`,
and `.reg`. The supplied official folder itself is never modified.
Invalid or non-UTF-8 JSON stays byte-for-byte unchanged and produces a visible
warning. Recognized RPG Maker `plugins.js` files are formatted identically to
Prepare. If a supported structured file cannot be safely formatted, it stays
unchanged and produces a warning. If the folder changes after preview, approval
is rejected and a new preview is required.

After approval, the proposed tree becomes the new `original` commit and is
cherry-picked onto the configured translated branch. Non-conflicting translations
remain. Conflicts prefer the new official release (hunk-level when a 3-way merge
is possible; otherwise the official file), including official deletions, and every
affected path is shown in the GUI Activity card.

The working tree must be clean before bootstrap or update. This keeps rollback
equivalent to `git cherry-pick --abort` and prevents unrelated user changes from
being folded into an update.
