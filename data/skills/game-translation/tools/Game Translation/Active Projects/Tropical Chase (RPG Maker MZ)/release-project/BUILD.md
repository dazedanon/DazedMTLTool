# Tropical Chase release project

Public project: C:/Users/sw/Desktop/Projects/tropical-chase-en
Patch version: 1.0.1. The repository contains 69 runtime files and three small repository files.

The scripts here preserve the packaging work and checks. Copy them into
translation_tooling/project_release in an isolated game workspace before running.
They expect the established source snapshots, image backups, final QA report,
release payload and clean_game layout. They do not contain the game or its saves.

assemble.py creates a fresh player-only staging tree from the verified payload.
create_project.py creates a new local repository; it refuses an existing destination.
It copies the repository-local identity from musi-dream-en. Adapt the Projects
paths for another machine; no global Git settings or network operations are used.
verify_project.py prepare checks a real Git clone, builds the player ZIP,
and tests original restoration, copy-over installation and repeat installation.
cold_smoke.ps1 launches only the isolated clean_game executable, captures its
title window without a startup hook, and closes that QA copy.
verify_project.py finish checks restoration from the test backup and reapplies
the English checkout. The fixed paths and 716-file census are game-specific.

verification.json records the actual result and archive hash. All 69 runtime
files match the previously tested 1.0.1 payload. This was a packaging retest,
not a new complete playthrough. The archive in the public project is ignored by
Git and is ready to attach as a release asset.
