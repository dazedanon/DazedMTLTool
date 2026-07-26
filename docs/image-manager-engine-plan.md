# Engine-Agnostic Image Manager Plan

## Goal

Turn the RPG Maker MV/MZ Image Manager into an engine-agnostic Images page while
preserving the existing RPG Maker workflow. Engine profiles own discovery,
decoding, and runtime encoding; the shared manager owns browsing, editable
copies, review, selection, and patch delivery.

## First release

- `Auto-detect` chooses a profile from game-folder markers.
- `RPG Maker MV/MZ` preserves `img/` and `www/img/`, `.rpgmvp` / `.png_`
  decryption, `System.json` keys, and runtime re-encryption.
- `Generic / Loose Images` manages ordinary PNGs below a user-selected folder.
- Unknown and packed engines never silently use an unsafe repacking strategy.

## Storage contract

- Editable images: `.dazedtl/images/<game-relative logical path>`
- Manager metadata: `.dazedtl/image_manager/`
- Runtime backups: `.dazedtl/image_backups/<game-relative runtime path>`
- Transaction staging: `.dazedtl/image_patch_stage/`

The existing RPG Maker workspace layout remains valid. Generic images mirror
their path relative to the game root, for example `assets/ui/menu.png` becomes
`.dazedtl/images/assets/ui/menu.png`.

## Architecture

An image profile exposes:

1. Detection evidence and confidence.
2. Default or user-configurable image roots.
3. Asset scanning and logical IDs.
4. Preview decoding.
5. Creation of editable copies.
6. Runtime-file generation for patching.
7. Capabilities and actionable unsupported-operation errors.
8. A concise context block injected into the shared bitmap-localization skill.

Patch delivery is separate from engine encoding. The initial Git/GameUpdate
backend publishes engine-built files at their game-relative paths and adds exact
`.gitignore` allow-rules, matching existing behavior. The boundary must permit
later apply-only and export-folder backends.

## Safety requirements

- Folder detection and scanning are read-only.
- Legacy migration and duplicate cleanup are explicit actions, not load-time
  side effects.
- Editable copies are never overwritten by a normal make-editable operation.
- All source, editable, backup, and patch targets are checked to remain inside
  their expected roots.
- Symlink escapes, path collisions, corrupt images, missing keys, deleted source
  files, and externally changed runtime files produce visible errors.
- Patch writes use staging, backups, atomic replacement, and rollback where a
  multi-step publish cannot be completed.

## UI contract

- Game folder, engine selector, and detection reason appear together.
- Generic mode exposes an image-folder selector constrained to the game root.
- Action wording follows capability: RPG Maker uses Decrypt for encrypted
  assets; generic assets use Make editable.
- Copy skill injects the active engine name and profile guidance into one shared,
  engine-neutral bitmap-localization workflow.
- The first release keeps the existing All/Editable filters. Baseline metadata
  provides the foundation for later Modified/Conflict filters without making
  every ordinary filter operation hash thousands of images on the UI thread.
- RPG Maker Workflow Step 6 continues to open the shared Images page.

## Delivery phases

1. Add engine-neutral models, profile registry, detection, and Generic scanning.
2. Wrap existing RPG Maker behavior in its profile without changing crypto.
3. Refactor the Images UI to dispatch through the active profile.
4. Remove load-time mutation, add an explicit legacy-workspace migration
   affordance, and move side-by-side cleanup behind explicit edit actions.
5. Introduce baseline hashes and transactional patch preflight.
6. Update Workflow integration, Guide content, and compatibility imports.
7. Cover auto-detection, manual override, Generic nested paths, RPG regressions,
   path safety, conflicts, and UI capability states with tests.

## Definition of done

- Existing RPG Maker image tests continue to pass.
- A folder of loose PNGs can be scanned, copied to the workspace, edited,
  previewed, and patched back with a backup and exact Git allow-rule.
- Auto-detection selects RPG Maker for known MV/MZ layouts and otherwise gives a
  clear Generic fallback.
- Merely opening or refreshing Images does not move, delete, or rewrite files.
- Help text describes the engine selector, workspace, and patch semantics.
