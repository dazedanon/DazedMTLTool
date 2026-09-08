# natuiso tooling

Two reusable tools:
- `dxa_unpack.py` — DXArchive v8 extractor (below).
- `find_text_images.py` — find images containing text of a given Unicode script
  (Japanese by default, vertical included) and collect them into a folder.

## find_text_images.py

Generic, nothing hard-coded: input paths, output folder, OCR backend, target
scripts, thresholds, extensions and the collect action are all CLI options. The
"Japanese" filter is just the default set of Unicode ranges, so the same tool finds
Korean/Cyrillic/Latin/etc. The OCR engine is a pluggable adapter (EasyOCR or
Tesseract).

```sh
# Japanese (default), copy hits into ./jp_text_images keeping folder structure:
python find_text_images.py natuiso_extracted pix_extracted -o jp_text_images --manifest hits.csv

# Korean instead, require >=3 matching chars, just list (don't copy):
python find_text_images.py imgs -o out --scripts korean --min-chars 3 --action list

# Higher precision on horizontal text only:
python find_text_images.py imgs -o out --min-conf 0.4 --no-vertical
```

```sh
# Skip folders, and run on the GPU (RTX 3090):
python find_text_images.py natuiso_extracted -o jp_text_images --exclude bg cg --gpu
```

Key options: `--backend {auto,easyocr,tesseract}`, `--langs`, `--scripts`
(groups `japanese/chinese/korean`, or named ranges `hiragana,katakana,kanji,
hangul,cyrillic,latin,...`), `--min-chars`, `--min-conf`, `--max-dim`,
`--rotations`, `--action {copy,move,symlink,list,none}`, `--flatten`,
`--manifest file.csv|.json`, `--gpu`, `--exclude PAT...`, `--include PAT...`.

`--exclude` / `--include` match a directory name (`bg`), a path prefix (`cg/sub`)
or a glob (`'cg/*'`, `'*_thumb.png'`) against each image's relative path; excluded
directories are pruned from the walk (not just filtered), so they cost nothing.

**GPU:** pass `--gpu` to use CUDA. EasyOCR's default pip install pulls a CPU-only
torch; for an NVIDIA card install a CUDA build, e.g.
`pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126`.
The script prints a warning (and falls back to CPU) if `--gpu` is set but CUDA isn't available.

Detection counts characters whose codepoints fall in the target script ranges, so
**vertical Japanese is caught even though EasyOCR transcribes it at very low
confidence** — which is why `--min-conf` defaults to 0 and precision comes from
`--min-chars`. Backend install: `pip install easyocr` (used here), or
`pip install pytesseract` plus `tesseract.exe` with `jpn` + `jpn_vert` data.

---

## script_tl.py — translation extract / inject

Extracts the VN's translatable text into **LLM-friendly per-file JSON** (one `.json`
per script, **scenes separated by `label`** so contexts never bleed) and re-injects
translations back into the UTF-8 scripts with a **byte-exact round-trip guarantee**.

```sh
# 1) extract  (scenes split by label; embeds a character glossary per file)
python script_tl.py extract natuiso_extracted/scripts -o tl_json

# 2) translate the "translation" field of each segment in tl_json/*.json (LLM)
#    (re-running extract with --merge keeps translations already filled in)

# 3) inject back into copies of the scripts
python script_tl.py inject tl_json --scripts natuiso_extracted/scripts -o scripts_en

# sanity: confirm the parser reproduces every script byte-for-byte
python script_tl.py verify natuiso_extracted/scripts
```

Each JSON segment carries context for quality: `type` (dialogue / monologue / narration),
`speaker` + `speaker_en`, `voice` id, the source text, an empty `translation`, and a
`note`. `meta` holds game info, translation instructions, and the **glossary of just the
characters in that file** (name, romaji, role, speech style). Scenes list their speakers.

Useful flags: `extract --split {label,file,none}`, `extract --merge` (don't clobber
existing translations), `extract --glossary _glossary.json` (use your edited glossary),
`inject --fallback {original,empty,mark}` (what to emit for untranslated lines),
`inject --translate-names` (also rewrite `＠speaker` to the English name — **off by
default**; may affect voice/nameplate matching, test in-game first), and
`glossary -o tl_json` to (re)write the starter glossary.

Validated: 43/43 scripts round-trip byte-identical; inject with no translations
reproduces the originals exactly; multi-line dialogue and name rewriting work.
Note: on-screen text baked into PNGs (title, dialogs, eyecatch, `parts/文字`) is **not**
in scripts — handle those via image editing (see `find_text_images.py` output).

## tl_translate.py — batch translation with Claude Sonnet 4.6

Translates the `tl_json/` from `script_tl.py extract` using the Anthropic **Message
Batches** API (50% cheaper), then writes the results back into the `translation`
fields. Requests use a compact, scene-grouped format with short per-chunk indices
(mapped back to segment ids locally), a shared **prompt-cached** instruction block, and
the per-file character glossary — so long ids are never sent or returned.

```sh
export ANTHROPIC_API_KEY=sk-ant-...                      # required for live calls
python tl_translate.py dryrun   tl_json --show-sample     # cost/token preview, no key
python tl_translate.py run      tl_json --max-segments 100 # submit + poll + fetch + validate
python tl_translate.py validate tl_json                   # completeness/quality checks
# then:
python script_tl.py inject tl_json --scripts natuiso_extracted/scripts -o scripts_en
```

Sub-commands: `dryrun` (offline estimate + sample prompt), `submit` (create batch, save
`_batch_state.json`), `status`, `fetch` (download + write back; resumable), `run`
(submit+poll+fetch+validate), `validate`, and `selftest` (offline build→fake→apply→validate).
Flags: `--model` (default `claude-sonnet-4-6`), `--max-segments` (per-request chunk size),
`run --poll` (seconds). The validator flags: untranslated, identical-to-source, residual
Japanese, and suspiciously-short translations.

Measured on this game (tiktoken o200k_base proxy): ~220K input + ~150–220K output tokens →
**≈ $1.5–2.0 per pass with batching** (≈$3–4 non-batch). Confirm Sonnet 4.6 pricing; add
~15% for tokenizer差. selftest applies 3843/3843 segments with 0 errors.

## img_translate.py — replace baked-in text in images

Spec-driven, reusable text-on-image replacement that matches the original style
using the game's own English font (`natuiso_extracted/system/fonts/fonts.en_us.otf`).

```sh
python img_translate.py detect img.png -o spec.json     # OCR -> region spec (fill in "en")
python img_translate.py render spec.json -o out_dir     # erase + re-render + side-by-side preview
```

Each region: `box`, `jp`, `en`, an `erase` method (`rowbg` = per-row background sampling,
ideal for gradient/solid panels; `solid`; `inpaint`; `clear` for transparent layers),
plus `font`/`color`/`align`/`size` (auto by default). Validated on `dialog_load.png`
("ロードしますか？" → "Load this game?", see `_img_demo/`).

**Scope:** good for flat UI text (the 6 `dialog_*`, `waring`, `info`, `nameplate`,
`staffroll`). NOT for hand-designed logo typography over art (`アイキャッチ/IC*`,
`title*`) or angled SFX (`文字/PB*`) — those need manual design.

### translate_images.py — project driver (natuiso UI)

Renders the English UI images for THIS game into `images_en/` (+ `images_en/_previews/`)
using the engine above; translations/layout live in the driver.

```sh
python translate_images.py        # -> images_en/  (12 images)
```

Covers: 6 confirmation dialogs, the age/disclaimer warning screen, the autosave info
bar (translucent), the sample nameplate, and 3 staff-roll credit samples. `sample.png`
is skipped (a dev layout mock, not a shipping asset). nameplate + staff-roll are stylized
dev samples, so their font match is approximate; everything else matches the game style
using `fonts.en_us.otf`.

---

# natuiso DXArchive unpacker

`夏とプールとイソギンチャク` (PIX GAME STUDIO) ships its assets in **DxLib DXArchive v8**
containers (`natuiso.bin`, `pix.bin`). This folder contains a standalone Python unpacker
reverse-engineered from `natuiso.exe`.

## Usage

```sh
python dxa_unpack.py pix.bin              # -> pix_extracted/
python dxa_unpack.py natuiso.bin          # -> natuiso_extracted/  (~1.3 GB, 5493 files)
python dxa_unpack.py pix.bin --list       # list contents only
python dxa_unpack.py <arc> -o <dir>       # custom output dir
python dxa_unpack.py <arc> --key <str>    # override key string
```

Requires Python 3 (numpy optional, used to speed up the XOR step).

## Format (DXArchive v8, recovered from natuiso.exe)

Header magic `DX`, version 8. Per encoded blob the pipeline is:

```
on-disk bytes ──KeyConv(XOR)──▶ ──Huffman_Decode──▶ ──LZ Decode──▶ original
```

Key facts pulled out of the binary (IDA functions in brackets):

| Item | Value |
|------|-------|
| Hash | standard CRC32, poly `0xEDB88320` `[sub_755920]` |
| Key (7 bytes) | `LE32(CRC32(even-index chars)) ++ LE24(CRC32(odd-index chars))` `[sub_752EE0 / KeyCreate]` |
| KeyConv | `data[i] ^= key[(position + i) % 7]` `[sub_752C70 / KeyConv]` |
| **Game key string** | `"_ppiixxeell_"` — set via `SetDXArchiveKeyString` `[sub_44BAC0 → sub_751F50]` |
| Table | global key, **position 0**, Huffman then LZ `[sub_753350]` |
| File key string | `"_ppiixxeell_"` + UPPERCASE filename + parent dir names (child→parent, root excluded) `[CreateKeyFileString / sub_750AE0]` |
| File KeyConv position | `DataSize` (uncompressed size) `[sub_7521B0 / sub_754140]` |
| Large-file Huffman | only head + tail (`HuffmanEncodeKB`×1024 = 10 KiB each) are Huffman-compressed; middle stored raw `[sub_754140]` |
| MIN_COMPRESS | 4 |
| Name table entry | `u16 PackNum; u16 Parity; char Upper[PackNum*4]; char RealName[]` (CP932) |

Header layout (64 bytes, always plaintext):

| off | size | field |
|-----|------|-------|
| 0x00 | u16 | `Head` = 0x5844 (`"DX"`) |
| 0x02 | u16 | `Version` = 8 |
| 0x04 | u32 | `HeadSize` (decompressed table size) |
| 0x08 | u64 | `DataStartAddress` |
| 0x10 | u64 | `FileNameTableStartAddress` (file offset of compressed table block) |
| 0x18 | u64 | `FileTableStartAddress` (relative to table block) |
| 0x20 | u64 | `DirectoryTableStartAddress` (relative to table block) |
| 0x28 | u32 | `CodePage` (932) |
| 0x2C | u8  | `Flags` (bit0 = no-key, bit1 = table uncompressed) |
| 0x30 | u8  | `HuffmanEncodeKB` (10) |

`FILEHEAD` = 72 bytes (9×u64): NameAddr, Attributes, Create/Access/Write times,
DataAddr, DataSize, PressDataSize (`0xFFFF…` = no LZ), HuffPressDataSize (`0xFFFF…` = no Huffman).
`DIRINFO` = 32 bytes (4×u64): DirAddr, ParentDirAddr (`0xFFFF…` = root), FileHeadNum, FileHeadAddr.

Verified against ground truth: extracted XML (`<?xml`), PNG (`\x89PNG…IEND`),
OGG (`OggS`), WAV (`RIFF…WAVE`) and TTF (`\x00\x01\x00\x00`) all decode with exact sizes.
