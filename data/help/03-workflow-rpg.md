# Workflow: RPG Maker

Open **Workflow** and select **RPG Maker** in the engine selector.
Use each step's **?** button for short in-context help.
This page is the overview.

The workflow uses a step rail on the left and keeps one task page visible at a time. At narrower
window sizes the rail collapses to step numbers so the task area stays usable. Use **Back** and
**Continue** at the bottom, or select a step directly in the rail.

Every page is organized as numbered tasks rather than one large control surface. Work through
the numbered cards in order; wide layouts place closely related cards side by side, while narrow
layouts stack them without changing their meaning or state.

Related buttons share a consistent size and alignment. Primary blue actions advance or apply work;
neutral actions inspect, copy, reload, or configure; red-outline actions remove existing data or
installed tools. Form fields and checkbox groups use stable columns so values remain easy to scan.

Routine output is collected behind the **Activity** button instead of permanently taking page
space. The badge shows unread entries; open the panel for details or to clear the display. Errors
remain indicated after the panel is closed so they are not easy to miss.

## Steps at a glance

| Step | What it does |
|------|----------------|
| **0 Project** | Detect MV/MZ/Ace, list JSON, import into `files/` |
| **1 Pre-process** | Optional `dazedformat`, format `plugins.js` (MV/MZ), copy `gameupdate/` |
| **2 Setup** | Speaker flags, Parse Speakers, Project Setup → vocab / quirks / game skill |
| **3 TL Phase 1** | Phase 0 DB → Phase 1 dialogue → Phase 1b code 111 cache |
| **4 TL Phase 2** | Risky codes (122, plugins, etc.) after you audit |
| **5 Export** | MV/MZ: `plugins.js` helpers. Ace: Ruby `.rb` scripts. Then export / pack |
| **6 Rewrap** | Reflow exported game data by category, selected files/maps, and event codes |
| **7 Images** | Check image setup, then decrypt → AI translate → review → patch (MV/MZ) |
| **8 Playtest** | TL Inspector / Forge (MV/MZ; hidden for Ace) |

## Example: first RPG Maker run

1. Step 0 - select the game root that contains `www/` (MV) or `data/` (MZ).
2. Import core DB + one small map (for example `Map001.json`) before importing everything.
3. Step 2 - Parse Speakers, then run Project Setup in Cursor on the game folder.
4. Step 3 - run Phase 0, skim `translated/` and `log/`, then Phase 1 on the small map.
5. Play in-game. If it looks good, import the rest of the maps and continue.

## Speaker flags (Step 2)

Step 2 is split into preparing working files, building speaker/project context, and reviewing the
saved guidance. Enable only the speaker detection methods the game uses:

- **INLINE401** - name stuck to dialogue on the same line
- **FIRSTLINE** - first dialogue line is the speaker name
- **FACENAME** - last resort from face filenames

Project Setup's `speakers` block recommends ENABLE / SKIP with evidence.

## Phase tips

- Keep **vocab.txt** focused - huge glossaries raise cost and can hurt quality.
- Use **Batch** mode with **Claude Sonnet 4.6** for large map / CommonEvents runs (Anthropic Message Batches, ~50% off).
- On **Mistral** (free), stay on **Normal** mode - Batch is Claude-only.
- Use **Normal** mode when you want live iteration on a handful of files.
- Phase 2 can break games if you translate logic keys - audit with the Plugin Prompt first.
- Phase 2's long plugin/script and pattern lists are under **Advanced code controls**. Collapsing
  that section never changes its checked options.

## Rewrap exported game data (Step 6)

Export translations in Step 5 first. Rewrap then edits the JSON in the game data folder detected
by Step 0 when the English is correct but its line breaks need to change. It does not call the
model and never changes `_original`.

The page follows four stages: choose files, set wrapping rules, scan/review/apply, then finish QA
and package the game. At wide window sizes file selection and wrapping rules appear side by side.
Event codes and non-401 row protection are under **Advanced event handling**, and scan results
remain collapsed until a scan begins.

- Select Dialogue, Dialogue + Face, List/Help, Notes, or any combination.
- Select individual maps/database files, all maps/events, all DB files, or everything.
- Keep event codes at `401,405` for standard messages, or explicitly include other recognized
  display-code fields.
- Scan before applying. Row protection applies by default to rewrapped fields other than code 401,
  including scrolling text, list/help, notes, and supported plugin fields; it can be disabled.
- Code-401 dialogue, including face dialogue, is never blocked by the row limit because it can
  continue into another message window.
- Dialogue wrapping never adds, removes, or repurposes code-401 commands. It inserts `\n` inside
  each existing code-401 text value while preserving that command's other data and `_original`.
- Run final QA after applying approved changes, then create the public release ZIP from this step.

## Images (Step 7, MV/MZ)

Step 7 keeps the engine-aware Image Manager on the separate **Images** page, selects the RPG Maker
workflow through auto-detection, and verifies that you are ready to use it:

- Step 0 points to the actual game root containing `img/` or `www/img/`.
- Encrypted projects have a valid key in `System.json`.
- `<game>/vocab.txt` exists for the copied AI skill.
- Editable PNGs are under `.dazedtl/images/<game-relative>/img/...`.
- No PNGs were accidentally placed beside that expected `img/` tree.

Click **Open Images**, decrypt the images you want to translate, then click **Copy skill** in the
Image Manager and paste it into Codex, Cursor, Copilot, or a similar coding agent. Review the
resulting PNGs before using **Patch selected** or **Patch all**.

Do not edit the runtime images directly. The Image Manager maintains editable copies and patches
the reviewed results back into the game.

## Ace note (Ruby scripts, not plugins.js)

Ace has no `plugins.js`. UI / menu strings often live in **Ruby scripts** packed inside `Data/Scripts.rvdata2`.

1. **Unpack** - Step 0 runs **RV2JSON `-c`**, which writes `ace_json/` (JSON data + `ace_json/scripts/*.rb`).
2. **Edit like plugins.js** - In Step 5 the **Plugins** row becomes **Scripts**. Copy vocab → game, copy the Ace scripts prompt, open `ace_json/scripts/` in Cursor/VS Code, and translate only player-visible string literals (same safety rules as plugins.js: never keys, method names, or logic comparisons).
3. **Pack** - Click **Export Active** or **Export ALL**. The tool writes translated JSON into `ace_json/`, then runs **RV2JSON `-u`**, which packs `ace_json/` (including the edited `.rb` scripts) back into `Data/*.rvdata2` (including `Scripts.rvdata2`).

Dialogue/DB files still go through the normal translate pipeline; script UI text is an IDE pass on the `.rb` files, then Export packs them.
