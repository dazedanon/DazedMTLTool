# Independent text coverage audit

Scope: the 101 files in `reports/runtime_files.json`, plus direct inspection of
`data/system/Config.tjs` and the four manually translated maps. No source files or
store records were changed. Images were not audited.

## Finding requiring a display repair

The backlog exposes internal character IDs, a class invisible to Japanese-only
extraction. `data/scenario/system/chara_define.ks` registers `jname` equal to
`name`. `tyrano/plugins/kag/kag.tag_ext.js:1` (`chara_ptext.start`) writes that
`jname` to the character name element. `tyrano/plugins/kag/kag.tag.js:1`
(`text.showMessage`, followed by `pushTextToBackLog`) then prints it in the
backlog. The theme's `html/backlog.html:12` displays the generated log verbatim.

The nine used technical speaker keys occur in 189 source `#` controls:

| Key | Controls | First source control | Intended display |
|---|---:|---|---|
| undress_bug | 5 | scene2_undress.ks:85 | Giant Katydid |
| kosuri_bug | 25 | scene3_kosuri.ks:38 | Giant Katydid |
| kosuri_face | 6 | scene3_kosuri.ks:127 | Himarii |
| insert_bug | 10 | scene4_insert.ks:25 | Giant Katydid |
| insert_face | 10 | scene4_insert.ks:44 | Himarii |
| sanran_bl | 1 | scene6_sanran.ks:140 | Himarii |
| sanran_face | 54 | scene6_sanran.ks:150 | Himarii |
| sanran_ch | 67 | scene6_sanran.ks:159 | Giant Katydid |
| ev_baby | 11 | scene9_baby.ks:8 | Himarii |

The `sanran_ch` lines were reviewed in full: despite the sprite's name, the
dialogue consistently belongs to the katydid, including scene6:201, 891, and 936.
Recommended repair: map only the rendered backlog name. Preserve the internal
keys and `jname` aliases: assigning the same `jname` to multiple sprites would
collide in `stat.jcharas` and could change speech-bubble anchor lookup. This is
an observed code path, pending confirmation in the running patched game.

## Japanese literal coverage

An independent Esprima tokenizer pass examined all 50 active JS files and found
124 Japanese-bearing string/template tokens. 68 overlap catalog spans. All 56
remaining tokens were reviewed individually, including each occurrence on the
minified engine lines:

- 29 in `tyrano/libs/html2canvas.js:20`: CSS counter numeral alphabets and
  Japanese/Chinese numbering algorithms, not translatable game labels.
- 15 in `tyrano/plugins/kag/kag.tag_three.js:1`: AR startup and 3D debug controls.
  `Config.tjs:12` has `use3D=false`, and the scenarios invoke no `3d_*` tags.
- 5 in `tyrano/plugins/kag/kag.js:1`: one punctuation exclusion list for the
  speech sound system and four event-listener logging template fragments.
- 4 in `tyrano/libs.js:900,919,1422,1479`: direct `console.error` diagnostics.
- 1 each in `kag.tag_audio.js:1`, `kag.tag_system.js:1`, and `kag.tag.js:1`:
  console/debug logging, not player dialogs.

Esprima reports one invalid-regex error partway through the unused AR library
`tyrano/libs/three/etc/ar.js`; a separate whole-file scan found no raw Japanese
or Japanese Unicode escapes. Other active JS tokenization produced no errors.
The detailed token locations, columns, and surrounding code are recorded in
`unextracted_audit.json`; the independent helper is `audit_unextracted.py`.

HTMLParser examined all nine active HTML files. No Japanese attribute values or
visible text nodes were found. Four Japanese-bearing script bodies contain only
source comments; those comments were manually reviewed. Menu and configuration
controls use image resources, so this result is literal-text coverage only.

The independent residual-span sweep of active KS and CSS files left eight lines:
five CSS font-family lines and three explicit `[font face=...]` attributes
(`scene1.ks:56`, `scene6_sanran.ks:1215,1463`). These are valid font names.
Independent Esprima tokenization of every active `[iscript]` block found only
the already-extracted fallback configuration sample at `config.ks:80`.
`Config.tjs` contains no missed display value: its Japanese content is the build
comment and font family names. The main title and project identifier are already
the Latin string `musi_dream`.

No missed Japanese player-facing literal or incorrectly excluded Japanese
technical field was identified in this audit.

## Punctuation, masks, and map completeness

The four manual JSON maps together contain exactly all 509 catalog IDs. No
Japanese remains in their English values. The source token maps contain no
Japanese hidden behind sentinels. The only unextracted punctuation-only bare
display is `scene3_kosuri.ks:293`, `…………`; preserving it unchanged is correct.
Literal Japanese nameplates have catalog coverage; the nine ASCII speaker keys
above are a separate display issue.

These findings assess source coverage and manual maps. They do not establish
rendered fitting, loader behavior, save compatibility, or final-build identity;
the parent task performs those checks against the built game.
