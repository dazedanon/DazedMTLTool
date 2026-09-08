# Player Git project

`C:/Users/sw/Desktop/Projects/musi-dream-en` contains the player patch,
following Nightfall Princess's minimal repository convention. The initial
commit is `f88a0e6d1e98791b8a7cf3e492d07dc9db50b7f0` on `master`.

The 60 tracked files are 50 verified runtime replacements, four installer
scripts and their manifest, a short player README, install/restore CMD wrappers,
and two Git metadata files. `* -text` preserves the exact reviewed bytes,
including existing CRLF and source whitespace. The generated Git allowlist
excludes original game files, saves, rebuild tools, and private QA materials.
The excluded video-listing image remains absent from the payload.

Players copy `English_Patch` and both CMD files beside `musi_dream.exe`, run
`Install_English.cmd` once, then launch the game normally. The archive installer
is required for this Electron build's archive-first loader; Ajin Shoujo's
loose-folder precedence does not apply. `Restore_Japanese.cmd` restores the
verified original backup. No separate interpreter, download, or API is needed.

`Musi_Dream_DropIn.zip` was assembled from the committed Git blobs and contains
the 58 player files, excluding Git metadata. `reports/DROPIN_PROJECT.json`
records its identity and the repository location. No remote was configured and
nothing was published online.

`scripts/build_dropin_project.py` rebuilds a candidate tree from the validated
release in this durable Tools project. Its default output is `dropin_stage/`;
`--output` selects another review directory. It verifies release evidence and
all payload hashes, and refuses unexpected files instead of deleting them.
Review and test the candidate before deliberately updating the player repo.

`reports/dropin_qa.json` records the packaging retest: a clean game copy exported
from the staged Git tree installed the exact prior release archive, recognized
a repeat installation, launched with English title art and scene text, and
restored the exact original. The previous nine-scene gameplay, layout, image
and save evidence applies because all 50 runtime replacements are byte-identical.
The temporary fixture was separate from the user's game and saves.
