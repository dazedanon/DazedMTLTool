# The patched game.exe — engine patches P1..P8

`game.exe` is the full SRPG Studio engine (not `runtime.rts`), imagebase `0x400000`. In the full-loose build it is binary-patched so that, on top of the **original Japanese `data.dts`**, it loads loose override files: a loose `Project\` JSON tree (translated at parse time), loose `Fonts\`, loose `Script\`/`Plugin\` `.js`, and loose `Graphics\` `.srk`. A translator edits plain files and sees changes on the next launch — no repack, no recompile.

Everything in this section is one script: `FullLooseKit/tools/loosekit/patch_exe.py`, which turns a **stock v1.23** `game.exe` into the shipped build in one verified pass. It needs `probe.bin`, `load_table.bin`, `apply_fontsize.bin`, and `apply_title.bin` next to it. The seven logical patches are P1, P2, P3, P5b, P6, P7, P8 — there is no P4, and P5 (the old `translation.bin` variant) was superseded by P5b (see below).

```
python patch_exe.py game.exe.orig.bak -o game.exe
```

## Build invariants the script enforces

These are the discipline that makes the build reproducible — read them before touching any patch.

- **Stock-exe gate.** The script knows exactly one input. `STOCK_SHA = afd79d5bbfd4d95d0650987b101a203ea8c38e8f671bc2134a144a8ca37213e6`. A mismatch only warns, but **every** patch site is then re-verified by `expect()` against the exact original bytes; any drift aborts with `refusing: <site> at <off> is <got>, expected <want> (not the stock v1.23 exe).` You cannot silently patch the wrong build.
- **Position-independent caves / ASLR discipline.** The exe has `DYNAMIC_BASE` set, so Windows can rebase it (observed: `0x430000`, `0xb90000`). Bytes the script *adds* are **not** in `.reloc`, so any hardcoded absolute (an IAT `call [0x4A92xx]`, a `push offset string`, a `mov eax,[global]`) would land `0x30000+` off → garbage call → the engine boots to the graceful `ゲームの起動に失敗しました` dialog. Every cave therefore computes its own ASLR delta with the PIC idiom `call $+5; pop reg; sub reg,<static-VA-of-the-pop>` (in the hex blobs: `E8 00000000 58 2D <va>` / `5F 81 EF <va>`), then forms every absolute as `[delta+abs]` (`call [delta+IAT]`, `lea eax,[delta+str]`, `mov eax,[delta+global]`). Internal `E8 rel32` calls and PC-relative jumps are fine as-is. This cost a full debug pass to discover; preserve it in any new cave.
- **Two new PE sections.** P3 lives in a new `.mod` section; P5b/P6/P7/P8 live in a new `.mtl` section. `add_section()` appends the header, bumps `NumberOfSections`, grows `SizeOfImage`, and **requires the file to end exactly at the section's raw offset** (`refusing: file ends at <x>, expected <raw>`) — i.e. the stock file size is the anchor (`MOD_RAW = 0x153000`, `.mtl` raw `0x153200`). `.mod` is `0x60000020` (CODE|EXEC|READ). `.mtl` is `0xE0000020` (CODE|EXEC|**READ|WRITE**) because P5b stores `g_table` and the FNV arena pointer into the section itself.

---

## P1 — disable the resource-error force-quit (ResourceErrorNotify)

**Why.** The config loader `sub_439620` reads `ResourceErrorNotify` from `game.ini` and stores a flag at the settings struct `[edi+0Ch]` (`dword_4E1DC8 +12`) computed as `(value == -1 || value == 0)` — so the flag is TRUE (quit) when the ini key is `0` or absent. The resource-error handler `sub_473840` then does `MessageBoxW` + `ExitProcess(0)`. A momentarily-missing loose resource (e.g. a transient AV/disk lock right after install on an effect/CG `.srk`) thus **force-quit the whole game**. A real player hit this on a file that actually existed.

**The fix.** Force the flag to `0` (continue, never quit) regardless of `game.ini`.

- File offset `0x38D86` (VA `0x439986`), 17 bytes.
- Original: `83 f9 ff 75 05 8d 41 02 eb 07 33 c0 85 c9 0f 94 c0` (the cmp/jnz/lea/jmp/xor/test/setz that compute the flag).
- Patched: `33 C0` (`xor eax,eax`) + 15× `90` (nop). The pre-existing `mov [edi+0Ch], eax` at `0x439997` then stores 0.

**Why this approach.** It is ini-independent and touches **no** player settings. Shipping a modified `game.ini` instead would reset keybinds/fullscreen, and the engine exposes no script API to change the flag (plugins can't help). GOTCHA: this is the *least* surprising of the seven and the one most likely to be "optimized away" by someone who doesn't realize a missing CG must be survivable on a real player's machine — keep it.

---

## P2 — loose `Script\`/`Plugin\` replace-loader

**Why.** The published engine loads Script+Plugin from `data.dts` (`sub_446380` → `sub_456090`, the packed branch). It only scans loose `Script\`/`Plugin\` folders when `data.dts` is **absent** (editor mode), and that built-in branch is all-or-nothing and destructive (overwrites the script-collection pointer, MessageBoxes if there's no loose `Script\` folder) — so you cannot just flip the gate. Scripts load via `IActiveScriptParse::ParseScriptText` with `SCRIPTTEXT_ISVISIBLE|ISPERSISTENT` (flag `0x42`), meaning parsing == adding to the global JS namespace and files parsed **last** override earlier ones.

**Hook + cave.** P2 hooks `sub_456090`'s per-script loop at the loose-vs-packed branch.

- Hook at VA `0x456223` (file `0x55623`), the 8-byte `test edx,edx; jz loc_4562B4` (`85 D2 0F 84 89 00 00 00`), replaced with `E9 <rel32 to PERCAVE_VA> 90 90 90`.
- Cave `PERCAVE_VA = 0x4A8620` (file `0xA7A20`), reusing free `.text` padding (the script `expect()`s that padding is all zero before writing).

**Behavior — per-entry REPLACE, not additive.** For each archive entry the cave builds `<gamedir>\Script|Plugin\<name>` (name = `[edi+0xC]`, which **includes subfolders** — the archive stores subfolder-relative paths like `constants\constants-stringtable.js`; Script vs Plugin from `[edi+0x14]`), `GetFileAttributesW`-probes it, and if the loose file exists `jmp loc_4562B4` into the engine's own loose path (`sub_4563F0(path, mode=1)`), loading the loose file **instead** of the archive buffer. If absent, it reproduces `test edx,edx; jz loc_4562B4` and falls through to packed.

**GOTCHA — the wrapper/alias double-execution trap.** It MUST be replace, not additive. ~16–21 of the edited plugins use the alias/wrapper pattern `var a = Obj.m; Obj.m = fn`. If the JP base copy *and* the loose copy both parse, the wrapper double-wraps → gameplay bugs. Replace-mode (loose file runs *instead of* the base entry, not after it) is the only correct semantics. The earlier additive trampoline at `0x456298` was reverted to `8B 8C 24 3C 0A 00 00`.

**GOTCHA — UTF-16LE is mandatory.** Loose `.js` **must** be UTF-16LE with the `FF FE` BOM. `sub_4749B0` reads the loose file and, if it is *not* UTF-16, decodes via the ANSI codepage (CP1252), **not** UTF-8. So a UTF-8 loose file mojibakes every non-ASCII char (`—` `E2 80 94` → `â€"`), and a UTF-8 BOM `EF BB BF` makes `ParseScriptText` throw `property 'ï»¿' is null`. The packed `data.dts` scripts are UTF-16, which is why they're fine. Deploy step: convert each edited `.js` from UTF-8 to UTF-16LE+BOM (`utf-8-sig` decode → `\xff\xfe` + `utf-16-le`) before placing it loose.

**GOTCHA — PIC.** The cave must restore/preserve `ecx`=`wsprintfW` (because `loc_4562B4` does `call ecx`) and `edx`=v4, and it is fully PIC (the `89 e6 e8 00000000 58 2d 30864a00` delta prologue you can see in `PERCAVE`). End-to-end proof: no folder boots clean; a valid loose `Plugin\x.js` boots and runs; a 0-byte plugin makes the engine name its full path in a dialog.

---

## P3 — loose-first `project.dat`

**Why.** The whole database (every dialogue/name/description) is the ProjectSection at the tail of `data.dts`. P3 lets a loose **plaintext** `project.dat` next to the exe override it.

**Hook + cave.** Loaded by `sub_446BD0`.

- Trampoline at `0x446C52` (file `0x46052`), 8 displaced bytes `8B 17 33 C0 83 7B 44 01`, replaced with `E9 <rel32 to 0x557000> 90 90 90`.
- Cave (`CAVE2`) at VA `0x557000` in the new `.mod` section (RVA `0x157000`, file `0x153000`).

**Behavior.** The cave builds `<gamedir>\project.dat`, calls the engine's own whole-file reader `sub_47B120` (`ecx=path, edx=0`), and if present: sets `[edi]=buf`, `[edi+4]=0`, forces the **non-encrypt** parse path (the loose file is already plaintext, so it must skip the RC4 decrypt that the archive path does), and arranges the buffer to be freed after parse. Absent → reproduces the displaced bytes → normal `data.dts` path. KEY insight that makes this work: the decrypted body size equals the plaintext `project.dat` size (RC4 is a stream cipher), so the loose file can be the plaintext DB.

**Status in the live build.** P3 is **dormant** — the shipped build ships no loose `project.dat`, so this path never fires. Text translates live via P5b, and the one non-string field (`fontSize`) applies live via P8, both straight from the `Project\` folder; nothing in the loose translation needs a repacked database. P3 is kept in the exe as a latent capability (drop a plaintext `project.dat` next to `game.exe` and it loads over `data.dts`), but it is not part of the workflow. See [docs/08](08-changing-the-database.md).

---

## P5 / P5b — parse-time database translation from the loose `Project\` tree

This is the heart of the translation. Both variants share one principle: **every** database string flows through one engine function `sub_474100(ecx=cursor, edx=&out)` (~180 callers across the DB parsers). Hook its success return and you translate the data *as it is parsed*, so the in-memory database is fully English with **no display-hook limitations** — wrapping, page composition, name substitution all stay correct because the substitution happens at the data layer, not at draw time.

**Hook + cave (shared).**
- Hook the success return at VA `0x474167` (file `0x73567`), displaced 5 bytes `89 33 5F 5E 5B` (`mov [ebx],esi; pop edi; pop esi; pop ebx` — the resume is dead), replaced with `E9 <rel32 to 0x558008>`.
- The cave (the **probe**, `probe.bin`, 279 bytes) lives at `0x558008` in `.mtl`. `g_table` is the dword at `0x558000` (the section base). The probe, on each parsed blob, FNV-1a hashes it, open-addressing-probes the table, and on a match `HeapAlloc`s an EN buffer, copies it, sets `*out`=EN and returns `en_len`; on a miss it passes the JP through. `g_table == -1` (or empty) ⇒ universal passthrough = the original Japanese from `data.dts`. (Strings are null-terminated and the length **includes** the trailing `0x0000`; a match leaks the original ~1.5 MB JP buffer, harmless.)

**P5 (historical).** The cave loaded a prebuilt `translation.bin` (an FNV open-addressing table: `u32 nb`, `u32 ne`, bucket array, then `[u32 jp_len][jp+null][u32 en_len][en+null]` entries) built by `tooling/build_translation.py` from `translation.json`. This required a rebuild on every edit. The P5 build is `game.exe.transtable` (P1+2+3+5, SHA `edfd2662…`).

**P5b (shipped — the zero-build the TODO wanted).** Same probe, same in-memory FNV layout, but the table is now **built at runtime from the editable `Project\` folder** — so editing a file shows up next launch with no build step and `translation.bin` is deleted. The folder **IS the native SRPG `project.dat` JSON tree** (`items.json`, `Maps\map_000.json`, … — exactly what `SRPG_Unpacker -c` produces) with each translatable string wrapped as `{"jp": "...", "en": "..."}`. Only the loader changed, and the probe's `call load_table` at `0x558036` was repointed.

**The P5b loader = PIC asm stub + compiled-C shellcode.** This is the subtle part:

- **`load_table.c`** (`FullLooseKit/tools/loosekit/load_table.c`) is compiled with `cl /nologo /c /TC /O1 /GS- /Gs1000000 /Zl` (see `build_loader.ps1`, needs VS 2022) to **position-independent shellcode** with **zero relocations**. `_emit.py` extracts the `.text` from the COFF `.obj` and asserts/prints the relocation count — it must be 0, which is *why* the C is allowed to reference no globals and no imports directly. The committed artifact is `load_table.bin` (1561 bytes). `patch_exe.py` embeds the committed `.bin`; you only rebuild if you change the `.c`.
- **Everything the blob touches comes in through an `Imp` struct** the asm stub fills: 12 Win32 function pointers (`HeapAlloc`, `GetProcessHeap`, `HeapFree`, `FindFirstFileW`/`FindNextFileW`/`FindClose`, `CreateFileW`/`ReadFile`/`CloseHandle`/`GetFileSize`, `wsprintfW`, `MultiByteToWideChar`) plus `base_dir`, `g_table`, the format strings `L"%s\\*"` / `L"%s\\%s"`, the search keys `"jp\": \""` / `"en\": \""`, and `rootname = L"Project"`. That indirection is what keeps the compiled `.text` relocation-free and runnable from any ASLR address.
- **The asm stub** (`STUB_VA = 0x558300`, `STUB_LEN = 0xD7`, PIC via `E8 00000000 5F 81 EF <STUB_VA+5>`) loads each of the 12 IAT thunks through the delta (`IAT = [0x4a9230, 0x4a9090, …]`), sets `base_dir = [0x4E1AF4] + 0x8E8` (the game dir), `g_table = delta + 0x558000`, points the five string slots at the embedded strings, then `call`s the blob (`BLOB_VA`, 16-byte aligned after the stub) and on return stores `g_table` back at `0x558000`.
- **The blob** (`load_table` in the `.c`) `HeapAlloc`s an 8 + `NB*4` + 12 MB arena (`NB = 32768`), then walks `<base>\Project` with an **explicit heap dir-stack, not recursion** (so it stays one function — `FindFirstFileW("%s\\*")`, push directories, read each `*.json`). Per file it scans for each `"jp": "..."` then the **following** `"en": "..."`, JSON-unescapes both, `MultiByteToWideChar(CP_UTF8=65001)` → UTF-16, and FNV-inserts with **first-win dedup**. `ne == 0` ⇒ `*g_table = INVALID (-1)` ⇒ passthrough. **Empty `en` is skipped** (`if (!em … continue;`) ⇒ an untranslated string shows the `data.dts` Japanese.

**GOTCHAS for P5b.**
- The `Project\` tree must be the *native* project.dat JSON shape with `{"jp","en"}` wraps; the loader keys on the literal byte sequences `"jp": "` and `"en": "` and on `.json` extensions. `speaker`/`comment`/`fontName` are left as plain strings (speaker names translate through the unit-name entries). Build it with `make_folder.py` — and prefer `make_folder.py --store …`, which runs the text pipeline's `inject` so dialogue gets the same width-fill reflow/page-align/glossary as the data.dts build (no orphan tail-words); plain `--en` carries the raw translator wraps un-reflowed.
- Blank `en` → Japanese is a *feature* (incremental translation), not a bug; don't "fix" it by emitting the JP into `en`.
- `.mtl` must stay **RWX** — the loader writes `g_table` and the arena pointer back into the section.

**Proof.** Boots clean, `ne = 10744`; `ベルフェゴール → Belphegor`, world-map names, and multi-line dialogue all resolve; edit a wrapped `en` → reopen → new value in memory. (Content-keying means 102/10744 JP keys that had inconsistent EN in the old project.dat collapse to one majority-vote EN — more consistent, not a limitation.)

---

## P6 — loose `Fonts\` loader

**Why.** The game text font (M+ 2m) is an **in-memory DirectWrite custom font collection** (d2d1/dwrite, loaded in `sub_43CA10`), not GDI (`CreateFontW` in `sub_438CC0` is only the UI "MS Shell Dlg 2"). `sub_402170` builds `lpMem` (`dword_4E1A24` → an array of `{ptr,len}` per font) and DirectWrite reads glyphs straight from `lpMem[i]`. Fonts *with* embedded bytes (`[node+0x20] != 0`, M+ 2m) store at the embedded branch `loc_40227A`; fonts *without* embedded bytes already get a loose `<base>\Fonts\<name>.<ttf|otf>` path. That asymmetry is exactly why a player's loose font was ignored — M+ 2m is embedded, so it never took the loose path.

**Hook + cave.**
- Hook at VA `0x40227A` (file `0x167A`), displaced 5 bytes `A1 24 1A 4E 00` (`mov eax, lpMem`), replaced with `E9 <rel32 to FONT_VA>`. `FONT_VA = 0x5581B8` (PIC, in `.mtl`).
- The cave builds `<base>\Fonts\<name>.ttf` (base = `[dword_4E1AF4]+0x8E8`, name = `[ebx+0x10]`), calls the engine's own loose reader `sub_441450(path, index = edi>>3)` (`CreateFileW`/`ReadFile`/`HeapAlloc` → `lpMem[index]`, ret 1/0). Ret 1 → loose loaded; ret 0 → reproduce the embedded store `{ecx,esi}`; either way `jmp loc_4024AA`.

**Two GOTCHAS that each cost a debug pass.**
1. **The font NAME is at `node+0x10`, not `+0x0C`.** The originally-inferred `+0xC` is null for embedded fonts → path `\Fonts\.ttf` → silent embedded fallback (no crash, but no swap either — the worst kind of bug).
2. **The stale base-reloc trap.** The original `mov eax, lpMem` operand has a base-reloc (a HIGHLOW entry at **RVA `0x227B`** for the absolute `0x4E1A24`). Our `jmp rel32` *reuses those very bytes*, so the loader would relocate the `rel32` (+ASLR delta) and the jump lands in garbage → the graceful `ゲームの起動に失敗しました。<resource>` dialog (it is **not** a caught AV — the font function is never reached). FIX: `patch_exe.py` calls `kill_reloc(d, 0x227B)`, which walks `.reloc` and turns that one HIGHLOW (`type 3`) entry into type-0 (skip). The P7 title hook does **not** hit this because `mov eax,[eax+0x250]` uses a displacement, not a relocatable absolute.

**Proof.** `lpMem[0].len == 1610624` (loose fixed M+ 2m, TTF signature `00 01 00 00`) vs `1622368` (embedded broken); menu text renders clean. The loose font ships as `FullLooseKit/assets/font/M+ 2m.ttf` into the game's `Fonts\` folder.

---

## P7 — OS window title, live from `Project\titles.json`

**Why.** The main-window factory `sub_438930` (class `game-win`, writes `hWnd` to `0x4E19A8`) loads the caption once from a raw `WCHAR*` at `*(cfg+0x250)` (`cfg = dword_4E1AF4`). The title does **not** flow through `sub_474100`, so P5b can't reach it; only two `SetWindowTextW` sites exist and both are dialogs. So P7 supplies the caption itself — but **reads it from the folder, nothing baked in** (this is the generic, every-SRPG-Studio-game form; the older build hardcoded the EN string in the cave).

**Hook + cave.**
- Hook at VA `0x438967` (file `0x37D67`), the 6-byte `mov eax,[eax+250h]` (`8B 80 50 02 00 00`), replaced with `E8 <rel32 to the P7 stub> 90` — a `call`, since the cave returns the caption `WCHAR*` in `eax` exactly as the displaced instruction would.
- The cave (PIC asm stub + compiled-C blob `apply_title.bin`, in `.mtl`) reads `<base>\Project\titles.json` and resolves `windowTitle`: **`en` if non-empty → else `jp` → else the engine's own caption** `*(cfg+0x250)` (i.e. unpatched, if the file/key is absent). The chosen string is UTF-8→UTF-16'd into a persistent buffer in `.mtl` and returned. The stub preserves the host function's registers via `pushad`, overwrites only the saved `eax` slot (`[esp+0x1C]`) with the result, then `popad; ret` — so the caller sees only `eax` change, just like the original `mov`.

**Proof.** `GetWindowText` returns `windowTitle.en` from the folder; blanking `en` falls back to `jp`; removing `titles.json` falls back to the engine's original caption — all without a rebuild, no crash. `apply_title.c` → `apply_title.bin` via `build_loader.ps1`.

---

## P8 — loose `fontSize` from `Project\fonts.json`

**Why.** `fontSize` is the **only** non-string field the `Project\` tree exposes (everything else is a `{jp,en}` string P5b reaches, including the numbers inside `customParameters` — see [docs/08](08-changing-the-database.md)). A bare number has no Japanese text to key on, so P5b can't swap it. P8 closes that last gap so the whole folder is live: edit a `fontSize`, relaunch, done — no loose `project.dat`, no build step.

**The data.** The ten font slots parse into a FONTDATA linked list off `cfg + 0x1B4` (`cfg = dword_4E1AF4`); each node holds its `id` at `+0x08` and its `fontSize` at `+0x20`. `sub_402170` (the font-system builder, called once from `sub_4390C0` after the project is parsed) reads exactly this list, so its entry is a clean, post-parse override point.

**Hook + cave.**
- Hook at VA `0x40218C` (file `0x158C`), inside `sub_402170`'s prologue: the 6-byte `mov eax,[eax+508h]` (`8B 80 08 05 00 00`), replaced with `E9 <rel32 to STUB8_VA> 90`. That instruction uses `eax+disp` (no absolute operand), so — unlike the P6 hook — there is **no base-reloc to kill**, and `eax` already holds `cfg` there.
- The cave (PIC asm stub + compiled-C blob `apply_fontsize.bin`, both laid in `.mtl` after the P5b strings) reads `<base>\Project\fonts.json` (base = `[dword_4E1AF4]+0x8E8`), scans it for `"id":`/`"fontSize":` pairs into a small table, then walks the FONTDATA list and writes `table[node->id]` into `node->fontSize` (`+0x20`). It preserves all registers (`pushad`/`popad`), runs the displaced `mov eax,[eax+508h]`, and jumps back to `0x402192`. Blank/missing file → the list is left as parsed (the JP sizes). Like P5b's loader, everything it touches comes through an `Imp` struct the stub fills, so the compiled `.text` (`cl /O1 /GS- /Gs1000000 /Zl`, **0 relocations**) is position-independent.

**Proof.** Set `fonts.json` id0 `14→30` and id5 `15→40`, relaunch: the parsed FONTDATA nodes read back `30` and `40` (Frida), and the title menu renders the Default font visibly larger — straight from the folder, no loose `project.dat`. `apply_fontsize.c` → `apply_fontsize.bin` via `build_loader.ps1` (`_emit2.py` verifies 0 relocations).

---

## Reproduction summary

`patch_exe.py game.exe.orig.bak -o game.exe` applies P1, P2, P3, then `add_section(".mod")`, then `add_section(".mtl")` + `build_mtl()`. The `.mtl` section is `0x2000`: `probe.bin` at `0x558008`, the P6 font cave at `0x5581B8`, the P5b asm stub at `0x558300` + `load_table.bin` + the loader strings, then the P8 `apply_fontsize.bin` blob + stub + `fonts.json` path, then the P7 `apply_title.bin` blob + stub + `titles.json` path + a persistent UTF-16 out-buffer (all in the `0x559xxx` half). Then the `.mtl`-related trampolines (P5b db-string hook, P6 font hook + `kill_reloc(0x227B)`, P7 caption hook → the title stub, P8 font-init hook at `0x158C`). Each site is `expect()`-verified against stock bytes; the build is deterministic. The resulting full exe is `game.exe.full` (== the shipped `game.exe`, latest/preferred). It **ships loose at the release-zip root** — the user copies it into the game folder and Windows prompts to replace — **not** via the patcher's `extra_files` channel (the user wanted no settings touched and the patcher shouldn't manage the exe; `game.ini` is never shipped).

**What to ship alongside it:** the original JP `data.dts` + the loose `Project\` folder + loose `Fonts\M+ 2m.ttf` + loose `Script\`/`Plugin\` `.js` (UTF-16LE) + loose `Graphics\*.srk`. **No `translation.bin`** (deleted under P5b).

## Source references (absolute paths)

- `C:\Users\sw\.claude\projects\c--Users-sw-Desktop-Games-Belphegor\memory\exe-patches.md` — primary, the per-patch ground truth (addresses, bytes, gotchas, hashes).
- `C:\Users\sw\.claude\projects\c--Users-sw-Desktop-Games-Belphegor\memory\engine-resource-loading.md` — the loader functions P1/P2/P6 hook (`sub_464BF0`, `sub_456090`, `sub_473840`).
- `C:\Users\sw\Desktop\Games\Belphegor\FullLooseKit\tools\loosekit\patch_exe.py` — the authoritative reproducer (offsets, `STOCK_SHA`, section chars, `kill_reloc`, `build_mtl`).
- `C:\Users\sw\Desktop\Games\Belphegor\FullLooseKit\tools\loosekit\load_table.c` — the P5b runtime folder reader (Imp struct, dir-stack walk, FNV insert, blank-`en` skip).
- `C:\Users\sw\Desktop\Games\Belphegor\FullLooseKit\tools\loosekit\build_loader.ps1` / `_emit.py` — compile flags and the zero-relocation assertion that proves the shellcode is PIC.
- `C:\Users\sw\Desktop\Games\Belphegor\FullLooseKit\tools\loosekit\README.md` — operator-facing build/edit steps.
