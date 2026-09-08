# Musi Dream runtime and layout audit

Read-only audit on 2026-09-05. No game boot, UI, network/API, game source edits,
archive changes, deployment, or save access. Scripts and evidence are confined to
this directory. Electron Node-mode starts emitted the existing Windows crash
registration access-denied diagnostic; interpreter probes completed normally.

Source paths below are relative to the durable project's `source/app`:
`C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Musi Dream (TyranoScript)`.
Minified engine offsets are zero-based JavaScript character offsets within line 1.

## Delivery

**This executable searches `app.asar`, then `app`, then `default_app.asar`.**
A loose `resources/app` folder by itself does not override its original archive.
The Electron 7 reference's reversed precedence is not applicable.

Evidence from this actual 162,125,312-byte executable:

- `process.binding('natives')['electron/js2c/browser_init']`, char 114588:
  `const p=l.getHiddenValue(global,"appSearchPaths")`, followed by ordered
  `for(c of p)` package loading, first success wins. The full bundled source is
  preserved as `electron_js2c_browser_init.js` and the excerpt in `probe_init.txt`.
- Native constructors at VA `0x14036243b`, `0x140362457`, `0x14036246e` load
  `app.asar`, `app`, `default_app.asar` into consecutive stack strings at
  `rsp+0x150`, `rsp+0x168`, `rsp+0x180`, copied into the 0x48-byte vector at
  `rsp+0xb0`. `binary_evidence.json` retains disassembly and referenced bytes.
- The OnlyLoadASAR branch selects that vector unless getter `0x1403c7670`
  returns true. Its getter reads `0x1480eeba7`, whose byte is `0`, compared with
  ASCII `1`. The alternate vector has only `app.asar`. Fuse wire at file offset
  135189376 is version 1, count 7, `1011000`.
- Node-mode ASAR `fs.readFileSync(resources/app.asar/package.json)` succeeded.
  This establishes ASAR filesystem support, not browser protocol interception.

Parent selected a full ASAR rebuild with original backup and entry-by-entry
verification, which avoids bootstrap identity changes. The archive is small
enough for that choice. If a future small shim is desired, it must rename the
original archive or install an active tiny `app.asar` bootstrap, preserve the
original executable-facing app path, and prove its file protocol override in UI.

Original launcher requirements that a repack naturally preserves:

- `main.js:101` enters ready handler. `main.js:127` creates the window with
  `useContentSize:true`, original package dimensions/resizability;
  `nodeIntegration:true`, `contextIsolation:true`, and ASAR `preload.js`.
- `main.js:141` appends ` TyranoErectron` user-agent suffix; `main.js:143` loads
  ASAR index.html. Keep the original package name `tyranogame` and window block.
- `main.js:197` `getAppPath` IPC returns `electron_app.getAppPath()`;
  `main.js:202` `getProcess` returns platform, `__dirname`, execPath and HOME;
  `main.js:213` `doubleCheck` obtains the single-instance lock.
- **The text snapshot omitted `preload.js`.** Read it from the original ASAR.
  Its contextBridge `studio_api` exposes `fs-extra`, built-in fs/shell/path,
  `asar`, `adm-zip`, `csv-parse`, `csv-stringify`, and ipcRenderer. Keep all
  original node_modules. Three package dependencies do not enumerate everything
  the preload actually requires.
- `tyrano/libs.js:1020` `getExePath` strips exactly `\\resources\\app.asar` or
  `\\resources\\app` from getAppPath on Windows. Returning a renamed archive
  path would break that normalization. `libs.js:1085` writes
  `getExePath()+"/"+key+".sav"`. `kag.js` char 9699 builds the anti-tamper key from
  getExePath plus projectID. Config.tjs lines 3,6 keep file saves and `musi_dream`.

## Normal text geometry

Theme `init.ks:25-26` sets outer (60,522), 1160x193; padding left/right 140,
top 55. Earlier `data/scenario/system/message_window.ks:7` leaves bottom 10.

The final content width is **870px**, not the earlier nominal 880:
`kag.layer.js`, `refMessageLayer` char 4002, sets inner left/top=outer+10,
inner width=outer-10 and height=outer-10. `kag.tag.js`, position char 43700,
uses border-box and CSS padding. Thus content starts near (210,587), with
1150-280=870px width and 183-55-10=118px height.

Config.tjs:74-79 sets font 28, line spacing 8, pitch 0, normal weight. Normal
line boxes are 36px, yielding **three complete rows** in 118px. The nameplate
is independent: theme init.ks:29, 360px width, 26px font at (165,525).

`kag.tag.js` `setCurrentSpanStyle` char 17787 computes line height from the
active font size plus line_spacing/defaultLineSpacing. Track each `[font]` and
`[resetfont]`; changing only glyph size does not justify retaining a 36px row
assumption. `autoInsertPageBreak` char 14500 checks existing p height against
0.8 * OUTER height before appending the next text element. It is not a safe
overflow paginator for a single long English unit.

Font chain in Config.tjs:77 begins Quicksand, Yu Gothic variants, other Japanese
system families, sans-serif, Arial. `tyrano/css/font.css:2-12` is wholly commented
out; there is no bundled-face guarantee from it. Actual resolved face and ink
need the parent's renderer calibration. At default no effect, the engine's
buildMessageHTML emits inline char spans, not forced inline-block per letter;
animation or outline modes can alter this. Measure the actual DOM spans.

## Bubbles

`data/scenario/system/builder.ks:214-223` uses **message1**, sets margins
top5/left10/right10/bottom10, then activates fuki. It does not inherit the theme's
140px message0 padding. `chara_define.ks` records these content width/font pairs:

- undress: fixed 300 / 20px (line 4; fix_width overrides max_width200).
- undress_bug: 250 / 24px (line 7).
- undress_face, kosuri_abc, insert_cutin, sanran_tr, sanran_bl_tamago,
  piston_toiki, sanran_39kara, sanran_sukasi: 300 / 28px.
- kosuri_face, insert_face, piston_bed, sanran_face: 200 / 20px.
- kosuri_bug, insert_bug, sanran_ch: 240 / 24px.
- sanran_bl: 300 / 20px; ev_baby: 330 / 28px.

`kag.tag.js` `adjustCharaFukiSize` char 23813 uses content-box, fixed width if
provided else max-width, resets height, measures actual content, then grows outer
width by left/right padding+20 and height by top/bottom padding+20. For this
message1 macro those additions are 40px horizontally and 35px vertically.
It positions relative to the displayed sprite scaled against origin dimensions,
then clamps using screen width/height minus10 and a minimum top/left10. Bubble
height therefore expands; a universal three-row cap would be fabricated. Audit
the resulting bubble height against 700px screen room and compare to the source
layout/subject occlusion. Bubble font overrides in setFukiStyle (char 34980)
modify current_span font-size after inherited line-height was assigned; do not
assume its line-height automatically becomes bubble font-size+8.

## Configuration sample reader

Active `testMessagePlus/gMessageTester.js:69-81` removes comments and ALL spaces,
then splits at `[p]`. Its separate CSS reader at line 52 must stay unchanged.
The sample box is (348,598), **760x62px**, 18px font in style.css:25-30. It inherits
default font family via gMessageTester.js:294-297. No explicit sample line-height
is declared, so actual CSS normal-height rendering must determine row count.

`probe_sample.cjs` executes the shipped plugin, modifies only the sample callback
in VM memory, and demonstrates a scoped candidate:

1. Remove semicolon COMMENT LINES, not semicolons within English sentences.
2. Normalize CRLF, trim each source line, discard empty lines, join with a space.
3. Split `[p]`, trim each page, retain existing trailing-empty-page removal.

The probe proves ASCII word spaces and multiline joins, preserves `[r]` and
`[kidoku]/[endkidoku]` conversion via the real `appendChar` method, and confirms
the CSS property map is byte-value equivalent. `probe_sample.txt` has before/
after evidence. No plugin source was changed by this audit.

## Structural and save checks

`compare_runtime.cjs SOURCE_APP TRANSLATED_APP RUNTIME_FILES_JSON [--overlay] [--parsed-output JSON]`
loads each tree's own KAG parser and Config.tjs in the shipped runtime. Default
mode fails on missing active files; `--overlay` explicitly reads absent output
files from original source. It checks:

- All active parsed element counts, names, line coordinates and label maps.
- Every tag control parameter, with only `glink.text` and unregistered literal
  `chara_ptext.name` permitted to differ. Registered character names remain keys.
- Prose value changes and leading `_ ` spacing are permitted without inserting
  elements or moving lines.
- Every iscript block compiles; Acorn AST structure stays identical except
  literal string values (actual Acorn is obtained from the shipped Node runtime).
- Every changed/new JS file compiles with `vm.Script`.
- projectID, save backend/overwrite setting, space mode and screen dimensions.
- Zero parser warnings in both source and translated active trees.

The unchanged baseline passes **33 scenarios / 5,138 elements / 37 iscript
blocks**. `selftest_compare.cjs` exercises the actual comparator: accepted English
nameplate, glink, `_ ` spacing; rejected inserted break/line shift, changed jump
target, invalid JS and altered script identifier. Seven checks pass. This is a
structural/syntax gate; it cannot prove translation completeness or visual fit.

Parent's raw English overlay subsequently passed this gate: 33 scenarios,
5,138 elements, 426 changed text elements, 37 iscript blocks, 8 changed JS files,
zero issues (`compare_english.json`). Its parsed arrays and labels are preserved
under `parsed_output.json` in `files[relativePath].array_s` / `.map_label`.

`kag.menu.js` `snapSave` char 5225 stores current_order_index-1 plus cloned stat
and layer state. `loadGameData` char 17352 calls nextOrderWithIndex with stored
index/current_scenario. Exact element identity at every index also preserves
macro registrations, calls and stack positions; a remapper is unnecessary if
this gate passes and no structural layout edits are introduced. If adding or
dropping tags later, stop relying on identity and adapt the save compatibility
reference, including legacy and stamped-save remap proofs.

Old saves restore `data.layer` and `data.stat` (kag.menu.js char 12778), so their
already-captured screen text/slot captions may stay Japanese until the next
translated dialogue appears. This is separate from index compatibility. The
only extracted iscript literal is transient `tf.text_sample` in config.ks:80;
the present catalog does not identify persistent Japanese display tables needing
an automatic state migration.

Parent still must run this gate on the final rebuilt content, verify rebuilt
ASAR entries against intended bytes, launch the distribution, open each menu,
exercise normal and bubble text, and save/load a real slot. No live runtime or
rendered layout claim is made here.
