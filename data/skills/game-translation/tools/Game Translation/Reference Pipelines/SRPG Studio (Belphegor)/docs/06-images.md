# Translating images (loose Graphics .srk)

Text is not the only thing the Japanese build bakes in: chapter-title cards, class/skill/status panels, growth banners, the save-screen logo and dozens of caption images carry burned-in Japanese. SRPG Studio stores every image as an encrypted `.srk` blob. In a full-loose translation you never edit those blobs by hand and you never push them through `data.dts` — you produce translated PNGs, re-encrypt the changed ones into loose `.srk` files, and drop them into the game's `..\Graphics\` tree, which the engine loads in preference to the archive copy.

This section covers the whole image path: how the engine resolves a loose `.srk`, the typesetting scripts under `tools/imagetools/`, the mask/clean helpers, and exactly how a translated PNG becomes a loose `.srk` the engine picks up.

## Why images are loose, not in data.dts

This is the single most important gotcha, and it has bitten before (the prologue title card shipped, but stayed Japanese in game).

Translated images do **not** travel inside `data.dts`. The engine resolves Graphics with a loose-file-first resolver. From the reverse-engineering notes (`engine-resource-loading.md`): the Graphics resolver `sub_464BF0` builds a loose path with `sub_464F00` (extensions `png/jpg/bmp/mas`, and in practice `.srk`) and takes the loose branch whenever `dword_4E1BB4 || *(dword_4E1E0C+68)!=1 || *(dword_4E1E0C+244)` — the "externalize Graphics" project flag. The Belphegor build ships **3153 loose `.srk`** under `..\Graphics\` (verified: `Graphics\battleback`, `charchip`, `face`, `eventstill`, `mapchip`, ... each full of `NNNN.srk`). Those loose files override the archive, so the translated set must be deployed there.

Where this trips people up is the packer. `SRPG_Unpacker.exe extracted -o data_EN.dts --repack-srk` does re-encrypt your translated PNGs, but it does **not** put them in the dts. In `SRPG_Unpacker.cpp`, the `--repack-srk` path calls:

```cpp
CopyAndEncryptOpenData(inFolder, outFile.parent_path(), j);   // line 337
```

and inside `CopyAndEncryptOpenData` (line 177) it reads each decoded PNG, `Crypt::EncryptData(data)`, and writes it to `outFolder / encName` — i.e. **next to the output dts**, in a sibling `Graphics\` tree, not inside the archive. So deploying only `data_EN.dts -> ..\data.dts` leaves the Japanese images on screen; you must additionally sync the changed `.srk` into `..\Graphics\`.

Two consequences worth internalizing:

- **Encryption is deterministic.** An unchanged PNG re-encrypts to byte-identical `.srk`, so only the `.srk` that actually changed differ from the Japanese set (52 of them in the Belphegor build, out of 58 translated PNGs). You only copy those, and they persist across text-only rebuilds.
- **`res_mapping.json` is the name map.** The decoded PNG name and the encrypted `.srk` name are different; `extracted/res_mapping.json` maps one to the other, e.g.

  ```json
  "Graphics\\battleback\\ビーチ.png": "Graphics\\battleback\\0000.srk",
  ```

  This is also how you find which loose `.srk` a translated PNG lands on (e.g. `title00.png` prologue card -> `eventstill/0154.srk`; `og_セーブ画面.png` -> `mapchip/0020.srk`). `--repack-srk` reads this file (it warns "cannot repack .srk files" and bails if `res_mapping.json` is missing), so it must sit in the unpacked `inFolder`.

## The toolchain at a glance

The image pipeline lives in `FullLooseKit/tools/imagetools/`:

| File | Role |
|---|---|
| `mask_tool.py` | Interactive brush painter -> `<name>_mask.png` marking JP text to erase |
| `place_logo.py` | Composites the English logo onto cleaned backgrounds (title/save screens) |
| `typeset_title.py` | 27 chapter-title cards onto one erased parchment plate |
| `typeset_class.py` | Class-select screens: EN skill descriptions onto erased starfield BGs |
| `typeset_skill.py` | 610x80 transparent skill-description overlays |
| `typeset_status.py` | Shared 600x200 monster-status template (erase JP + draw EN) |
| `typeset_growth.py` | 6 growth-rate banners onto one erased sword plate |
| `typeset_meter.py` | 2 breeding/prenatal stat meters (300x360, transparent) |
| `typeset_misc.py` | One-offs: co-op tooltip + title-screen footnote |
| `inject_images.py` | Overlays finished PNGs onto `extracted/Graphics/**` by basename, ready for repack |

All scripts use Pillow (`PIL`), some add `numpy` for pixel-level erasing. The fonts are pulled from `C:/Windows/Fonts` (`arialbd.ttf`, `ariblk.ttf` Arial Black, `georgia.ttf`, `arial.ttf`) — note these are the *typesetting* fonts for burned-in image text and are unrelated to the game's runtime UI font (`assets/font/M+ 2m.ttf`, which ships loose in `Fonts/`).

## Step 1 — clean (erase the Japanese)

A translated image needs the JP glyphs gone first. There are two strategies in the kit, and the typesetters lean on both:

**Manual masking with `mask_tool.py`.** Run it on a source PNG:

```
python tools/imagetools/mask_tool.py "C:/path/to/image.png"
```

It opens a Tk canvas: left-drag paints white (mark for cleanup), right-drag erases the mark, mouse-wheel or `[`/`]` resizes the brush, `s` saves. The mask is written full-resolution next to the image as `<name>_mask.png` (white = clean this). The on-screen image is downscaled to fit `MAXW,MAXH = 1500,820` but painting is mapped back to true coordinates, so the saved mask is always at native resolution. This produces the input to whatever inpainting/clean step you use to make the blank "plate" backgrounds the typesetters then draw onto.

**Programmatic erasing in the typesetters.** Most `typeset_*.py` don't need a mask because the JP text sits on a flat-color field they can just paint over. The patterns:

- *Rectangle fill over a known box.* `typeset_status.py` erases fixed boxes with the panel's own colors (`d.rectangle([115,24,284,60], fill=TEAL)`), carefully stopping short of beveled borders (comments like `# stop before green box left border (x287-292)`).
- *Color-keyed erase via numpy.* The same script clears only the white glyphs inside the green "Move" box while preserving the tan/black bevel: `sub[sub[:,:,1].astype(int)>86]=GBOXFILL` (olive g=77, white text g~245). `typeset_meter.py` similarly zeroes only the title and label bands (`a[0:50,0:156]=0`) to keep the frame and axis numbers.
- *Patch from a clean region.* `typeset_misc.py`'s footnote copies a blank parchment band from higher in the same image over the JP footnote (`patch=im.crop((690,300,1245,405)); im.paste(patch,(690,590))`) — cheaper than masking when matching texture exists nearby.
- *Pre-erased shared plates.* `typeset_title.py`, `typeset_growth.py`, and `typeset_class.py` draw onto a single hand-cleaned background reused for every variant: `title_plate.png`, `growth_plate.png`, and the `cclean`/`cer_*` starfields. Clean the plate once (with `mask_tool.py` + inpainting), then the script stamps all 27 / 6 / 9 variants on copies of it.

## Step 2 — typeset the English

Every typesetter follows the same shape: open a background, draw text with PIL `ImageDraw`/`ImageFont`, save the finished PNG to an output dir. Two recurring techniques are worth calling out because they encode the visual style of the original art:

**Auto-fit and wrap so text never overflows the slot.** A shrink loop reduces point size until the line fits, e.g. in `typeset_status.py`:

```python
def fit(d,text,maxw,start=19,floor=12):
    s=start
    while s>floor and d.textlength(text,font=F(s))>maxw: s-=1
    return F(s)
```

`typeset_title.py` does the same for chapter names (`fit(...,760,start=48,floor=26)`), `typeset_class.py` drops a one-line skill to a wrapped two-line layout when it exceeds `MAXW=660`, and `typeset_skill.py`/`typeset_growth.py` shrink the whole multi-line block until both width and stacked height fit.

**Match the original glyph styling.** The scripts reproduce fill + outline + accent colors and synthetic effects rather than plain black text:
- `typeset_skill.py` and `typeset_growth.py` render each line to its own RGBA, then apply a synthetic-italic shear (`SHEAR=0.18`) via `Image.AFFINE`, with a yellow fill / navy stroke and a red leading `+` to mimic the game's skill captions.
- `typeset_status.py` mirrors the panel palette exactly (TEAL bg, white labels, GREEN stat deltas, ORANGE skill names) and re-fills the red attack box.
- `typeset_meter.py` samples the original label colors and stacks letters vertically (white fill + colored glow) to match the meter art.
- `typeset_title.py` uses Georgia with manual letter-tracking (`draw_tracked`) for the small-caps "CHAPTER N" line.

`place_logo.py` is the compositing variant: it LANCZOS-scales `logo_en.png` to a target width and `alpha_composite`s it onto already-cleaned backgrounds at fixed centers (the opening title and the three save-screen plates).

Run a typesetter directly; each iterates its built-in job list (and most accept an optional filter arg to render a single image):

```
python tools/imagetools/typeset_title.py        # all 27 cards
python tools/imagetools/typeset_status.py        # all 6 monsters
python tools/imagetools/typeset_skill.py 体術2   # just one, by filename substring
```

**Gotcha — hard-coded absolute paths.** Unlike the text pipeline, these scripts contain literal `C:/Users/sw/Desktop/Games/Belphegor/tooling/...` paths for their source (`ImagesToTranslate`, `cclean`, plates) and output (`tooling/translated`) directories. On another machine you must edit the `SRC`/`OUT`/`PLATE`/`BG` constants at the top of each file, or recreate that `tooling/` layout. They are project artifacts, not general CLI tools.

**Gotcha — keep dimensions identical.** The engine expects each slot's original pixel size. Translated PNGs that differ in dimensions from the slot they replace can render wrong; `inject_images.py` flags this for you (next step).

## Step 3 — inject finished PNGs into the unpacked tree

`inject_images.py` is the bridge from your finished PNGs to a repack. It indexes every decoded PNG under `extracted/Graphics/**` by basename and overlays each translated PNG onto its single match:

```
translatedimages/<name>.png  ->  extracted/Graphics/**/<name>.png   (matched by basename)
```

Run it from the script's own directory (it resolves `SRC = ./translatedimages` and `GFX = ./extracted/Graphics` relative to the file):

```
python tools/imagetools/inject_images.py --dry-run   # report matches + size mismatches
python tools/imagetools/inject_images.py             # actually copy over the slots
```

What it guards against:
- **Ambiguous / missing basenames.** If a name matches zero or >1 decoded PNGs it prints `SKIP ... (ambiguous / no match)` and copies nothing — so you immediately see names that won't land. (This is why the translated PNGs must be named after the *decoded* PNG, e.g. `クラス選択画面アーチナイト.png`, not the encrypted `NNNN.srk`.)
- **Dimension mismatches.** It reads PNG headers and tags `⚠ size (w,h)->(w,h)` whenever your image differs from the original slot.

Note the directory split: the typesetters write to `tooling/translated`, but `inject_images.py` reads from `tooling/translatedimages` (the memory note's "58 files" set). Stage your finished, correctly-named PNGs into `translatedimages/` (next to `inject_images.py`) before injecting. After injection the script reminds you of the repack command.

## Step 4 — repack to loose .srk and deploy

With the translated PNGs sitting in `extracted/Graphics/**`, re-encrypt:

```
tools/SRPG_Unpacker/SRPG_Unpacker.exe extracted -o data_EN.dts --repack-srk
```

As established above, this writes the encrypted `.srk` into a `Graphics\` tree **next to `data_EN.dts`** (via `CopyAndEncryptOpenData` -> `outFile.parent_path()`), using `extracted/res_mapping.json` for the PNG->`.srk` name mapping. It does *not* embed them in the dts. (If you ran `SRPG_Unpacker -c` originally to extract, the decoded originals are always regenerable, so injecting over them is safe.)

Then deploy the image half — in the full-loose path this is the **only** image step (there is no `translation.bin`, and `data.dts` stays the original Japanese):

1. Sync the changed `.srk` into the game's loose Graphics: copy each differing `tooling/Graphics/*.srk -> ..\Graphics\<category>\NNNN.srk`.

Because encryption is deterministic, a fast way to find what to copy is a binary diff of the freshly-repacked `Graphics\` against the Japanese loose set — only the translated slots differ (52 in the Belphegor build). Those, and only those, need to overwrite the loose `.srk` next to `game.exe`.

**Gotcha — a missing loose Graphics file can force-quit the engine.** The Graphics resolver has no `.srk`/container fallback in its loose branch: if it takes the loose path and the file is absent, `sub_464DF0 -> sub_473840` shows a "…が存在しません" dialog and `ExitProcess(0)` when the `ResourceErrorNotify` flag is set. The build ships a 17-byte game.exe patch (offset `0x38d86`, "Patch 1") forcing that flag to 0 so a transient read failure continues instead of quitting. The practical takeaway for the image step: never delete or half-replace a loose `.srk` — replace in place with a same-name, same-dimension file, and keep the full loose Graphics set intact.

## Quick checklist for one new translated image

1. `mask_tool.py` the source -> clean/inpaint a plate (or reuse a shared plate).
2. Add an entry to the matching `typeset_*.py` job list (text + geometry) and run it; output lands in `tooling/translated`.
3. Copy/rename the result into `tooling/translatedimages` using the **decoded PNG basename**.
4. `inject_images.py --dry-run` to confirm a unique match and no size warning, then run for real.
5. `SRPG_Unpacker.exe extracted -o data_EN.dts --repack-srk`.
6. Copy the changed `tooling/Graphics/*.srk` into `..\Graphics\` (use `res_mapping.json` to confirm the `NNNN.srk` target), and deploy the dts/text half as usual.
