# AutoNamePopup speaker and runtime names

Enable **Use AutoNamePopup's face + index mapping** in the RPG Maker workflow's
speaker settings, or **AutoNamePopup** in Configuration → RPG Maker MV/MZ.
The persisted setting is `AUTONAMEPOPUP101`, off by default.

Use it for games whose enabled `AutoNamePopup` plugin declares `nameKeys` in
`js/plugins.js` (or `www/js/plugins.js` for a packaged MV game). Select the game
in the workflow first. For a manual files-only workflow, supply a copy of the
registry at `files/plugins.js` along with `files/Actors.json`.

Keep generic **Face → Speaker** / `FACENAME101` disabled for shared sheets such
as `Actor1`. AutoNamePopup mode takes precedence if both settings are enabled.
The mapping uses the exact filename and index, including the plugin's declared
facial-expression ranges. Unknown pairs receive no inferred speaker. Explicit
name-window text still takes precedence. This reads the static `nameKeys`
declarations; runtime `setNameKeys` commands and automatic actor-face discovery
are not simulated.

Run **Collect names** after enabling the option and review the glossary. Source
actor names come from `files/Actors.json`, preferring preserved `_original.name`,
and follow the existing speaker/glossary translation path. This keeps speaker
context consistent between Batch Collect and Consume, even when translated
actor defaults exist. Dialogue gets temporary context such as `[Riri]: …`;
code-101 portrait fields and the plugin registry stay unchanged.

AutoNamePopup mode translates Change Actor Name (320) defaults only for actors
referenced by these mappings, even if the generic code-320 option is enabled.
Actor IDs and existing `_original` fields are preserved. Input Name (303) is
untouched, so players can still choose custom names.

Runtime actor and variable references (`\N[3]`, `\n[003]`, `\V[007]`) remain opaque
protected controls. The translator never substitutes a temporary default name
for them in this mode. Shared validation restores their original spelling and
also checks portrait/plugin controls such as `\F1`, `\F2`, and `\AA`. A response
that drops or damages required controls is rejected and the source text is
retained.

The parser follows the author's [AutoNamePopup documentation and source](https://awaya3ji.seesaa.net/article/483412423.html).
