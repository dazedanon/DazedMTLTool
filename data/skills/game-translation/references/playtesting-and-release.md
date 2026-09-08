# Playtesting and Release

The pipeline finishing is not the patch working. This file covers the three things
that happen after `inject` and before a player runs it: proving the translation on
screen, keeping a working copy you can recover from, and building an archive that
does not leak your workspace.

---

## Run a CANARY before a single line is translated

Ship six obviously-English strings - the window title, the game title, two or
three system buttons, one map name - build the patch, install it, launch, and
look. Then uninstall.

The point is to prove the DELIVERY path while the text is still 100% Japanese,
so a failure is unambiguous. Run it after a real translation instead and a
Japanese screen could be the loader hook, the archive scramble, the injector,
the file naming, or the translation itself, and telling those apart costs hours.
Doing it first costs ten minutes and it does not need the API at all.

**Pick canary strings that are visible without playing**, so the check is
mechanical rather than a screenshot you squint at. A window title is ideal:
`Get-Process <player> | Select MainWindowTitle` answers it from a script.

It earns its place on the first run. On a Bakin game the canary changed
`GameSettings.meta.title` and the title bar stayed Japanese - because the window
title comes from `GameSettings.name`, a *different* field holding the *same*
string. Every gate upstream was green (round trip 329/329, no-op inject
329/329), the overlay had demonstrably worked (the temp folder held the injected
roms), and the only thing wrong was one field being the wrong one. Found in one
cycle by a canary; after a full run it would have looked like the entire patch
failed to apply.

Include a **map name** if translated map names rename files on your engine -
that is the one part of delivery with special handling, so it is the one part
worth exercising.

Make `uninstall` restore the game byte-for-byte from a backup the installer
takes, and verify it with a diff. A canary you cannot cleanly revert is a canary
you will hesitate to run.

---

## Playtest after every export, not once at the end

**And if the game runs on this machine, capture the screen instead of squinting
at it.** A screenshot can be measured; a memory of one cannot. See
`text-fitting.md`, "If you CAN launch it, capture the screen and measure it in
PIXELS" - it turns "that looks a bit high" into "the ink centre is 8.9px above
the plate centre in a 48.2px plate", which is the difference between guessing at
a fix and deriving one.

Run the same five items each time. The point is that a defect found after one export
has one obvious cause, and a defect found after twenty has twenty.

1. **Launch the game normally.**
2. **Load a save near the area you just translated**, or start a new game.
3. **Open every menu** and read item, skill, actor and location names. Database text
   renders **only** in menus and never on a map, so a map-only playtest cannot see a
   database pass at all. This is the single most commonly skipped step.
4. **Walk every map you just exported.**
5. **Save once and load it back.** This is the save-compatibility probe. Rewritten
   data can invalidate an existing save when actor or item identities shift - see
   `save-compatibility.md`.

For a follow-up limited to display metadata, such as a window credit, scope
the rerun to the affected path when an artifact comparison proves gameplay
code, non-caption content/resources and save identity are unchanged. Launch the actual
package in a clean game copy and read back the changed caption. Retain the prior
gameplay evidence and identify its build; do not describe this launch as a new
full playthrough. Content or renderer edits still need the affected in-game
checks above.

For a narrowly scoped renderer fix, compare the previous and new payloads,
rerun every affected visual variant plus save/load and sprite lifecycle checks,
and bind the new report to the actual installed/build/archive hashes. Retain
prior route/content evidence only for content proved unchanged and identify
its original build. A prior layout gate shown to be wrong must be explicitly
superseded, not carried forward as passing evidence. Tropical Chase v1.0.1
changed only its runtime plugin; a 112-case painted-panel check replaced the
viewport-only signoff while unchanged text and prior route coverage were named.

Keep coverage claims separate: complete extraction/translation, all-block
native measurement, targeted ending fixtures, and a fresh New Game route are
different evidence. A completed defeat route is not a successful arrest;
reducing enemy HP to test victory callbacks is not a legitimate victory run.
Give exact limits even if every automated check passes.

Package the already-built payload only after verifying its current QA and
source/output identities. Reopening the ZIP must confirm the exact allowlist,
CRC and per-file hashes. Restore/reinstall checks should include unchanged
tracked files and any patch-owned additions, preserving unexpected user edits.
Reference: `RPG Maker MZ (Tropical Chase)/PIPELINE.md`, with the 716-file
restore/reinstall proof and 69-game-file payload scope.

Hunt six defect classes:

- the same name spelled two ways across files
- a line that does not match its scene
- text overflowing its box or covering the screen
- an awkward line break
- residual source language
- an image too crowded after editing

**Fix and re-test ONE defect before making any further change.** Otherwise you cannot
tell which edit caused what.

For each leftover Japanese string: screenshot it, OCR the screenshot, then search the
game folder for that exact string to find the field it came from. Where short or
duplicated strings make that fail, instrument the runtime instead - see
`playtest-instrumentation.md`.

### Four passes that per-export testing structurally cannot do

Add these before release:

- **Play start to finish**, not from old saves. An old save resumes *past* the maps
  whose events you edited.
- **Have a second person play.** They take choice branches (RPG Maker code `102`,
  and the equivalent elsewhere) that you never take.
- **Copy the finished translation onto a clean copy of the game and test that copy.**
  This is the only check that catches a patch which works solely because your working
  folder still holds a file the release does not.
- **Audit the archive** for API keys, private notes and screenshots.

### Every check in the pipeline is PER-UNIT. Budget for the bugs that have no unit

This is the structural reason playtesting cannot be skipped, and it is worth
stating as a category rather than a list. A defect is invisible to automated
checking whenever it is not a property of one translated string:

* **It was never extracted.** A filtered-out line, a blanket denylist entry, a
  text source in a file the extractor does not open. A unit that does not exist
  cannot fail anything, so *every counter reads green*.
* **It is a RELATIONSHIP between two records.** A caption and the widget drawn
  to its right, living in different commands. A lookup key that must equal a
  value chosen in another file.
* **It lives in the SAVE, not in a file.** A display value the engine copied
  into a game object on the pre-patch build.
* **It is in a field the injector writes but no unit owns.** A name plate
  rebuilt from the glossary, a coordinate.

On one game a user's screenshots surfaced **six** such classes after the
pipeline reported 100% translated and zero hard failures. Two cheap passes catch
most of them and neither needs a controller:

1. **Scan the INJECTED output**, not the store - grep for source-language text
   and for anything byte-identical to the source, then explain every hit by the
   code that owns it. That is what found 41 Japanese name plates.
2. **Decode a real save** and walk it for source-language strings grouped by
   path. That is what found the cached map labels.

And when a user reports one, treat it as a *class*, not an instance: ask what
else shares that shape. "Japanese in the opening menu" was one denylist entry;
the same denylist held three more.

### Never sign off a scene from the recollection room

Every CG-heavy Japanese game ships a gallery or replay menu, and the lazy check stops
there: find the replay call, read the text, declare the scene proofread. **The replay
path renders lines out of context**, often with different name and variable
substitutions, sometimes a different variant of the scene entirely, and it tells you
nothing about the in-world trigger that makes the line render in situ.

List the files that implement the viewer up front, then require that availability,
normal acquisition, live trigger and live completion each cite at least one source
**outside** that list and outside the viewer's own data rows. For a combat-triggered
scene that means naming the troop, skill, state and map that produce it, not the
gallery entry that replays it.

Use the gallery only to confirm the CG count and to spot which sets exist. Reach each
scene the player's way to check the text.

---

## Every defect a player reports should leave a CHECK behind

On one patch a human looking at the screen found, in order: dialogue breaking so
a word sat alone on a line; menu labels off-centre; those labels too tall for
their buttons; a tofu box where a heart should be; a duplicated MP cost; and
Japanese battle text. **Every automated check was green for all six.** They were
not near-misses - each sat in a blind spot the checks could not see into:

| what was reported | why nothing caught it |
|---|---|
| orphaned line break | every line fitted its width, and width was all "fits" meant |
| label off-centre | centring lived in a hand-tuned `pos.X`, not in a flag |
| text too tall | the check measured advance WIDTH, never ink HEIGHT |
| tofu glyph | the text was correct - the FONT lacked the codepoint |
| duplicated value | row 3 was already spent, and only width was measured |
| Japanese in battle | the field was unreachable, so it was never a unit |

A wrapping widget has TWO budgets, width and ROW COUNT, and the checks modelled
only the first. That is what made the duplicated MP cost look like someone
else's bug. The author had written the cost INTO the description field behind a
hard newline, so row 3 of 3 was spoken for before a translator touched
anything. English needing three rows pushed the text onto a fourth row, and the
engine drew that fourth row twice. Nothing the author shipped rendered twice.
The spill was ours, and every line of it fitted its width, which is why a
width-only check reports 0 against a panel that visibly repeats a line.

The lesson is not "test more". It is that **a report is a free specification for
a check you are missing**, and the check is usually cheap once the defect has
told you where to look. Each of those six became one: an orphan audit, a
centring-group detector, a glyph-coverage diff against the font's cmap, an
ink-height measurement, a fit measurement against the source, and a generic walk
of the shipped data. Most then found MORE instances than the one reported - the
glyph diff found 226,834, the battle-message walk found 50.

**One of the six found nothing, and it was the one that mattered.** The
row-count audit was written alongside its own fix, and both were written from
the same premise: that the panel was drawn by a single description code. It
reported 0 while the player's screen was unchanged. A check that shares a
premise with its fix cannot falsify that premise, so it does not find more
instances. It CONFIRMS the bug and puts a green number beside it. Point every
new check at the screenshot that reported the defect BEFORE you trust its zero,
and require it to fail there first. A zero you have never seen fail is not
evidence about the artifact.

So when a defect comes in, do three things in order: fix the instance, **sweep
for the class**, and leave behind the check that would have caught it. If you
cannot think of a check, you have not understood the defect yet.

The class is usually wider than the screen showed. One database record is drawn
through several distinct codes - `currentitemdes`, `currentskilldes`,
`selectshopitemdes`, `currentdictionarydes` - so a fix and an audit that cover
one code green-light the other three and ship the identical defect to the
player twice more.

And expect them in waves. Fixing one exposes the next, because a screen the
player could not read is a screen they now look at properly.

## The build step that does not build: stamp provenance, fail loud

**A "green gates, wrong build" report is almost never a bad gate. It is a gate
pointed at the wrong artifact.**

Two incidents on one pipeline, the same shape:

* `patch` PACKAGES the injected tree; it does not produce it. Edit the config,
  run every gate, run `patch` - and the previous inject ships. The gates were
  all green and all irrelevant: they read the translation store and the SOURCE
  layout, and not one of them opens the injected tree.
* `unpack` fills the working tree from the game archive and is never re-run,
  because it is slow and its output already exists. Point the pipeline at a
  newer build of the game and the working tree still describes the old one. Since
  the injector copies untouched source bytes straight through, and the patch is
  an OVERRIDE rather than a merge, the stale files then MASK the author's new
  ones at runtime - silently, in the target language, on a build everything
  called green.

Notice the gates cannot catch either, structurally rather than by oversight. A
no-op gate proves `output == source`. That says nothing about whether the
source still describes the game, and nothing at all about whether the output is
current.

So: **every producer stamps what it built from, every consumer checks, and a
mismatch is FATAL.** Write a small stamp file into each generated tree
recording the identity of its inputs - the archive's size and mtime, a hash of
the config, the newest mtime across the code and the store. Cheap identity, not
content hashes: a 1.7 GB archive hashed on every command is its own reason to
start skipping the check.

Make it an error, never a warning. This class of bug survives precisely because
its symptom is silence, and a warning in a 300-line log is silence with extra
steps. A false positive costs one rebuild; a false negative costs a playtest
round trip and the player's trust in the last thing you told them was fixed.

The tell that you need this: you find yourself saying "did that actually get
rebuilt?" If a human has to remember an ordering, the ordering belongs in code.

**A rename is a DELETE plus an add, and an overlay install only does the add.**
Where the engine names a file after content you translate - Bakin writes a map
to `<map name>_<guid>.rbr` - correcting that name changes the FILENAME. Copying
the new patch over the old one then leaves both files present, and the engine is
entitled to load the stale one. It bites twice: on your own dev install, and on
every player who drops release two over release one.

So an overlay folder whose filenames are derived from translated text must be
CLEARED before it is written, not merged into, and the release notes have to say
so. Check it by counting: the installed folder and the built folder must hold
the same number of files, not merely agree on the ones that exist in both. A
pure hash comparison of the built set against the installed set passes happily
while an orphan sits beside it.

**The same discipline applies one level down: verify the ARTIFACT carries the
change, not that the command reported success.** A declared override can
no-op silently. A resize keyed by widget did nothing on every description
panel, because those widgets draw a bare code, carry no source-language text,
were therefore never extracted as units, and the injector could not name an
owning file for them - so it counted them as skipped and printed that among a
dozen other counts. The config said 0.90, the run said OK, and the shipped tree
said 1.0.

So after any change to declared geometry, read the value back OUT of the built
tree and compare it against what you declared. It is two lines of code and it
is the only step that distinguishes "I configured it" from "it is in the
build". Anything keyed by a widget rather than by a translated string is
especially exposed, because the pipeline's whole addressing scheme is built
around strings that HAVE source text.

## Two-folder discipline, and what to do when the game breaks

**Keep two complete game folders with unambiguous names.** `Game - CLEAN BACKUP`,
never edited. `Game - WORKING`, the only one any tool or editor is ever pointed at.

Classify every action by what it mutates. Extraction and translation write only into
the workspace. **The game is mutated only by export, inject, build and patch.** Each
of those should have a preview or precheck that shows the planned change without
applying it, and the ordering rule is always preview before apply.

**When the game breaks, do not pile on more exports.** Close everything. Leave the
broken working copy in place, because it still holds useful translated files. Make a
**fresh** working copy from the untouched original, and re-add **one small group** of
translations at a time with a playtest after each. Incremental re-add is what
identifies which group broke it. A wholesale restore just reproduces the bug.

**Never delete the translated-output directory.** It holds results already paid for,
and its validity is independent of whether the playable copy works.

Automatic backups and a git repo are supplements. Neither replaces the untouched
whole-game copy.

---

## Per-game state lives inside the game folder, behind an allowlist

In the DazedTL integration, preserve the managed `.dazedtl` guidance rules and the
separate Len work block. `len-method/project.json`, `len-method/status.md` and authored
files allowed by `len-method/work/.gitignore` are versioned too. Generated context,
provider state, caches and raw snapshots remain local. The example below illustrates
the general pattern; do not replace the integration's current blocks with it.

Keep per-game state in a dot-directory inside the game root so it travels with the
project, and track it **partially** on purpose: commit the glossary, the settings file
holding the measured line widths, and the per-game guidance markdown. Ignore local
backups, caches and machine state. The portable translation guidance then travels with
the repo and nothing machine-local does.

Write a marker-delimited block into the game's own `.gitignore`:

```gitignore
# BEGIN portable translation settings
!/.tl/
/.tl/*
!/.tl/glossary.txt
!/.tl/settings.json
!/.tl/skills/
/.tl/skills/*
!/.tl/skills/*.md
# END portable translation settings
```

**The ordering is load-bearing.** Git cannot re-include a file inside an *excluded
directory*, so you must exclude the directory's **contents** (`/.tl/*`) rather than the
directory itself, and only then negate individual paths. The `skills/` subdirectory
needs its own exclude-then-negate pair for the same reason. Everything else -
reference indexes, QA manifests, image workspaces, image backups, cached API state -
stays ignored.

When rewriting that block: preserve its existing position in the file so git does not
churn, refuse to operate if `.gitignore` is a symlink or not a regular file, and write
via mkstemp + fsync + `chmod` back to the original mode + `os.replace`.
(`DAZEDTL_ROOT/util/paths.py:44`.)

**Runtime gotcha for anything that writes config from inside the game.** A packaged
NW.js build serves a `chrome-extension://` URL whose pathname is merely `/index.html`,
so `process.cwd()` is not the game root. Collect candidate roots (page dir,
`nw.App.startPath`, `process.mainModule.filename` dir, `process.execPath` dir,
`process.cwd()`), strip a trailing `www` component, and pick the first that actually
contains `index.html` or `www/index.html`. Keep a path-scoped `localStorage` fallback
for read-only game folders. (`DAZEDTL_ROOT/util/forge/modern_patches.py:96`.)

---

## A requested drop-in project has a smaller payload

Follow the user's existing project conventions when they name a Projects
directory. Assemble only the required replacement files at their original
relative paths, plus a minimal README stating where to copy them, how to back
up originals, how to launch and how to restore. Use an explicit payload allowlist;
keep originals, rebuild scripts, glossaries, image masks, QA fixtures and reports
in a stable tools project outside the game folder. A repository's metadata is not player payload.

Test a clean game copy assembled from the original runtime and the actual
project payload. Compare its file hashes with the release manifest and installed
copy, so a successful development build cannot conceal a stale project copy.
When Git LFS is used, verify the working payload contains the real binary;
a Git pointer is not a usable drop-in file. Use repository-local settings and
the established binary policy without changing global Git configuration.

Window-title credits belong in the field or runtime call that sets the visible
caption. Preserve separate internal project IDs and save-directory names, then
read the exact title from the running process. A title change does not imply a
logo redraw. See [engine-gamemaker.md](engine-gamemaker.md) for the measured case.

The denylist below describes exclusions from a contaminated working tree.
Write the intentionally small player README into the assembled payload after
that filtering; do not accidentally omit it with the development documentation.

## Build the release archive with an explicit denylist

**Assume the working folder is contaminated, and anchor the workspace names to the
ROOT only.** A real game legitimately ships `data/`, docs-shaped folders and `.md`
files deep in its tree, so a blanket recursive denylist strips game content.

**Exclude anywhere in the tree:** the tool's own dot-directory, `.git`, `.hg`, `.svn`,
`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, any directory named
`save`/`saves`/`savedata`/`save_data`, any file starting with `.env`, `.DS_Store`,
`desktop.ini`, `Thumbs.db`, patch scripts and their state files, and any file ending
`.bak`/`.backup`/`.orig`/`.tmp`/`.rpgsave`/`.sav`.

**Exclude at the root only:** `files`, `translated`, `log`, `logs`, `scripts`,
`skills`, `docs`, `test`, `tests`, agent and editor directories (`.agents`, `.claude`,
`.codex`, `.cursor`, `.vscode`, `.idea`, `.github`), `glossary.txt`, `vocab.txt`,
`translation_quirks.txt`, `readme.md`, `todo.md`, `requirements.txt`, `.gitignore`,
`.gitattributes`, `.editorconfig`, and any root file with suffix
`.md`/`.markdown`/`.rst`/`.doc`/`.docx`/`.pdf` or whose name starts with `save`.

Rules for the walker itself:

- **Return a reason string per exclusion** so the operator sees why each file was
  dropped.
- **Never follow symlinks.**
- **Prune directories top-down** so an excluded directory is never descended.
- **Default the output path beside the game root** (`<root>-public.zip`), so a re-run
  never archives the previous archive.

Shipping the working folder directly leaks `.env` and API keys, the whole
request-dump log, personal saves, and the paid translation corpus.

Ship a build that does not log. See SKILL.md step 11 for the loader-console and
disk-log specifics, and verify by running the **distribution** copy and confirming the
log files never appear. Config values are an intention, absent files are the evidence.

### The author's own dump plugins are the specific hazard

A developer build often carries the *author's* script-extraction plugins, still
enabled. This game shipped `DRS_AllDataExtractor` and `SentenceDataExtractor`,
which write **44 text files containing the entire Japanese script** into
`www/data_output/` at every boot. Shipping that means shipping the source script
as loose `.txt` beside your patch, and it regenerates itself after any denylist
sweep that only looks once.

**Disable them, do not delete them.** A plugin file that is missing while
`plugins.js` still registers it throws at boot. Set `status: false` through a
structural `raw_decode` edit so every other entry stays byte-identical, and name
what you disabled in the manifest.

### The release's residual-language check must know the engine's codes

A plain "find source-language text in the output" walk over an RPG Maker patch
reports **1,139** strings, and every one of them is a code-108 comment, a
code-118 label or a code-355 script that the pipeline deliberately never
translates. A number that size reads as a broken patch, so nobody reads the list
- which is exactly how the one real residual goes unnoticed.

Resolve each hit's enclosing command `code` and label it:

```
~ 73x '▼ここに障害物消滅フラグON'   Map006…/list/13/parameters/0
                                  [code 108 - comment (dev note): correctly left alone]
```

The same run then reports **0 player-facing Japanese remaining** and 67 distinct
strings correctly left alone, which is a number a human will actually check.
Reuse the scanner the QA step already has rather than writing a second, simpler
walk in the release script - two implementations of "is this player-facing" drift,
and the release one is the one nobody tests.
