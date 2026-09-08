# Len’s game-translation skill for DazedTL

This maintained copy ships as ordinary source files with DazedTL. Open **Len’s Method**,
choose a game and scope, click **Copy starting prompt**, and paste it into your coding
assistant. This prepares the workspace and includes setup in the same starting prompt.
There is no separate skill ZIP to install or refresh.

`SKILL.md` is the playbook; `references/` contains engine and topic guidance, and
`tools/` contains Len’s reusable tools and reference pipelines. `DAZEDTL_ROOT` in the
references means the live application folder three levels above this skill folder.
The frozen DazedTL extract from the supplied package is replaced by that live code.

The project uses the same `.dazedtl/glossary.txt`, `.dazedtl/skills/game.md`,
`.dazedtl/skills/quirks.md`, custom skills and reference registry as Workflow. The
shared context compiler and import bridge are `DAZEDTL_ROOT/scripts/len_translation.py`.
Longer research, pipeline adaptations, stores and QA evidence belong under the
project’s `.dazedtl/len-method` workspace. Copy only the needed tools before adapting
or running scripts that write beside themselves.

Run the self-check from anywhere:

```text
python <skill folder>/scripts/check_tools.py
```

Third-party dependencies are listed in `tools/THIRD-PARTY.md`. DazedTL’s own bundled
utilities are resolved from the live app. Other optional downloads depend on the
selected engine; preparation does not download or execute them.

Imported from the supplied Len TL Tools package on 2026-09-07. The reusable sources,
reference pipelines and code examples are retained. Caches, environment files, the
captured Loccubus game snapshot and the duplicated DazedTL extract are excluded.
References to the removed IL2CPP tool have been removed. The old `build_vocab.py`
now forwards to the current shared glossary importer.

Historical game configuration and provenance files in examples still contain the
original author’s paths. They are examples to adapt, never locations to read. Some
example manifests describe unshipped game artifacts or hash the original pipeline;
re-establish those manifests when adapting a pipeline to a different game.

## What ships

The local `.gitignore` excludes per-run reports, extracted game text, generated lookup
tables, rendered replacement images, compiler scratch, the old Unreal Python package
installation, and Bakin example builds. These are regenerated in the selected game's
workspace. `tools/C++/Unreal/requirements.txt` replaces its copied dependency installation.
The Loccubus baseline, unit/site catalogs and reports are not shipped; its preparation
scripts require a new baseline from the selected game. LoserLife's build wrapper generates
`known_texts.b64` from the new extraction. Bakin examples must be rebuilt from the supplied
source using their build instructions and the selected game's assemblies.

Retained assets include authored prompts/glossaries/configuration examples, provenance and
licenses, small curated before/after QA examples, image-builder masks, the two offline Wolf
executables, the Il2CppDumper embedded DLL resource, Trois TTS sidecars and SRPG patch blobs.
Those binary inputs are intentional tool assets; a blanket `*.dll` / `*.bin` / `*.json`
ignore rule would break or impoverish the shipped examples. Historical measured results
describe the source projects; they are not fresh QA results for a new game.

DazedTL is MIT licensed (see `DAZEDTL_ROOT/LICENSE.md`). Its SFX corpus has separate
`SOURCE.md` and `LICENSE.md` files under `DAZEDTL_ROOT/data/sfx_reference/`.
Il2CppDumper-ManualReg retains its upstream license. The remaining tools retain the
authorship and license material supplied in the original package.
