# Repository audit

Last reviewed: 2026-08-02

## Git references

Two local topic branches were fully contained by `main` and were removed:

- `dazed/evals` at `48bed75` (45 commits behind, 0 unique commits)
- `dazed/wolfdawn` at `4e2479c` (217 commits behind, 0 unique commits)

The local `main-backup` and `main-backup-github` branches were retained. They
each diverge from `main` by more than one thousand commits and are not safe
cleanup candidates. Their matching remote backup references were also left
unchanged.

All seven stashes were retained. Every stash contains a non-empty patch; the
newest includes the evaluation feature stack and older entries include RPG
Maker, module, launcher, and vocabulary work. Stash age or an unhelpful message
is not evidence that the content can be discarded.

Remote branches were not deleted. Remote cleanup needs an explicit host-level
retention decision because `OldTLMethod`, `gemini`, `main-filtered`, and the
backup branches contain unique history.

## Large Git objects

The checkout's `.git` directory was about 255 MiB at audit time:

- ordinary Git objects: about 106 MiB
- Git LFS object cache: about 146 MiB

The LFS object is the former 153 MB `util/ace/RPGMakerDecrypter.exe`. It remains
reachable from `main-backup`, `main-backup-github`, and their remote-tracking
counterparts. Removing those refs or manually deleting the LFS object would
discard recoverable history, so neither was done. The `git-lfs` client was not
installed in the audit environment; use an installed client and its dry-run
prune workflow only after deciding whether those backup refs still need the
binary.

## Follow-up rules

Before deleting a branch, require `git rev-list --count main..<branch>` to be
zero and inspect its merge relationship. Before dropping a stash, inspect its
file list and patch and confirm the work exists elsewhere. Never use age alone
as the deletion criterion.
