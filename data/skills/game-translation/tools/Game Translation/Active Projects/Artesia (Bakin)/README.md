# 執聖官アルテシア Ver1.06 - Bakin

Second Bakin title in the corpus.
Adapted from `Reference Pipelines\Bakin (Miyutsure)\`.
Bakin build **r64268** (2024-07-31), against the reference game's r73294 - two
container details differ and both were re-measured rather than carried across.

Game folder: `C:\Users\sw\Desktop\Games\執聖官アルテシアVer1.06`
(a working copy - nothing here may depend on it).

## What differs from the reference pipeline

**1. The rbpack header has no `hasLabel` bool.**
This build writes the splash label string straight after the discarded int64, so
the reference reader mis-parsed `0x0a` (the label's 7-bit length prefix) as the
bool and then read `'L'` as the length. `tools\rbpack.py` now tries both layouts
and lets the DRM MD5 decide which one was right.

    version 1 | label "Loading..." | drm_num 9672193 (salt 2525)
    zip_len 62,817,974 | body_offset 56 | res_offset 62,818,022

**2. The resource index stores paths relative to `res\`, and the roots are not
the reference game's.**
Entries read `character\3D\effekseer\...`, `texture\...`, `WesternPack\...` -
never `res\...` - so the reference's root-anchored regex harvested nothing
usable. `BakinRes probe` confirms the engine serves `res\window\...` and not
`window\...`, so `tools\index_walk.py` prepends the component.

Rather than pattern-match, the index is now **walked structurally**: it is a
contiguous run of `[path][17-byte record]` entries beginning at `res_offset + 5`,
and the next path starts exactly 17 bytes after the last byte of the current
one. That stride makes the walk self-checking - a wrong extension guess
desynchronises on the next entry and the walk stops - and it terminated cleanly
on entry 4,405 at `window\default_selectable.png`, after which the region turns
to high-entropy asset data.

`.efk` is a prefix of `.efkmat`, so the terminator has to be the **longest**
extension matching at the earliest position, not the first one found.

Scrambles are unchanged: **M = 7** on the rbpack body, **M = 13** on the resource
region, `dataVersion` 1.

## Verified

    index walk           4,405 entries
    BakinRes sizes       4,405 served, 0 missing, 2.24 GB
    BakinRes extract     3,403 images, 0 missing, 1,973 MB
    magic check          2,569 PNG / 826 BMP / 8 HDR all valid after descramble

The 826 BMPs include **7 files the game ships with a `.png` name over BMP
bytes** - `res\texture\sb_obj_indoor001_OldKitchen_normal.png` and the six
`sb_obj_indoor002_IronPot01{a,c}_{albedo,mask,normal}.png`. That is the game's
own mislabelling, not an extraction fault, so `flatten_png.py` dispatches on
magic rather than extension.

    .png 2,576   920.3 MB        .fbx 772    97.2 MB
    .bmp   819 1,136.6 MB        .ogg 128    73.0 MB
    .hdr     8    12.5 MB        .efk* 102    1.1 MB

## Run it

    set BAKIN_DATA=c:\Users\sw\Desktop\Games\執聖官アルテシアVer1.06\data

    csc -nologo -target:exe -platform:x64 -out:BakinRes\BakinRes.exe ^
        -r:%BAKIN_DATA%\common.dll -r:%BAKIN_DATA%\SharpKmyCore.dll ^
        BakinRes\Program.cs

    python tools\index_walk.py %BAKIN_DATA%\data.rbpack respaths.txt 32
    BakinRes\BakinRes.exe sizes   %BAKIN_DATA%\data.rbpack respaths.txt ressizes.tsv
    BakinRes\BakinRes.exe extract %BAKIN_DATA%\data.rbpack respaths_img.txt <game>\imgout
    python tools\flatten_png.py <game>\imgout <game>\imgpng

`respaths_img.txt` is `respaths.txt` filtered to `.png .bmp .hdr`. Extracting the
full list adds the FBX/OGG/EFK, another 171 MB.

## The text half

**`PIPELINE.md` is the main document.** This file covers assets only. The text
pipeline is built, gated and canaried: round trip 328/329, no-op inject
**329/329 byte-identical** over 90,195 units, 41/41 offline checks, and a canary
patch proven in-game. The localization-coverage audit the reference pipeline
calls for does not apply - this engine build has no localization feature at all,
so the field whitelist comes from two censuses instead.

## Assets still to do

The 3,395 images in `imgpng/` have not been triaged for baked-in Japanese.
Bakin injects a replaced image by repointing `ResourceItem.path` at a path the
pack does not contain and shipping the new file scrambled under
`data/translation/` - `data.rbpack` is never rebuilt.
