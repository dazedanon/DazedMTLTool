# Building and running BakinTL

    set BAKIN_DATA=<game>\data          # holds common.dll, SharpKmyCore.dll

    csc -target:exe -platform:x64 -out:BakinTL\BakinTL.exe ^
        -r:%BAKIN_DATA%\common.dll -r:%BAKIN_DATA%\SharpKmyCore.dll ^
        -r:%BAKIN_DATA%\SBControl.dll -r:System.Drawing.dll -r:System.Windows.Forms.dll ^
        BakinTL\Program.cs

    csc -target:library -out:BakinTLHook\BakinTranslationHook.dll BakinTLHook\Hook.cs

x64 is required: `common.dll` is AnyCPU but pulls in the x64 mixed-mode
`SharpKmyCore.dll`. The engine assemblies are bound at runtime from
`BAKIN_DATA` rather than copied, so the tool is not tied to one game's build.

## Pipeline

    python tools\rbpack.py <game>\data\data.rbpack pack.zip   # unpack the container
    <unzip pack.zip into pack\>                                # still scrambled
    <descramble each entry with tools\scramble.descramble>     # -> proj\

    BakinTL roundtrip proj                       # GATE: must be 138/138 identical
    BakinTL layout    proj layout.tsv            # geometry AND position, see below
    BakinTL effectparams proj effectparams.tsv   # nested rom text a flat table misses
    BakinTL audit     proj audit.tsv             # coverage of the built-in table
    BakinTL export    proj work                  # units.jsonl + scripts.jsonl
    <translate: work\units.jsonl -> translated.jsonl {key, en}>
    BakinTL inject    proj translated.jsonl out  # writes a full project

    python tools\build_patch.py proj out dist BakinTLHook\BakinTranslationHook.dll
    python tools\build_patch.py config <game>\data\bakinplayer.exe.config
    <copy dist\data\* into <game>\data\>

## Assets

    python tools\scan_resources.py <game>\data\data.rbpack respaths.txt 64
    BakinRes sizes   <game>\data\data.rbpack respaths.txt ressizes.tsv
    BakinRes extract <game>\data\data.rbpack respaths.txt imgout
    BakinTL  resources proj resources.tsv     # guid, type, name, path

To replace an image: edit it, set that resource's path with a
`R:<guid>:path` unit pointing at `.
es	l\<name>.png`, and ship the new
image scrambled under `data	ranslation\`. The pack is never rebuilt.

## What `layout` and `effectparams` are for

`layout` dumps far more than `size.X`, because `size.X` alone cannot answer
"why does this look wrong":

* `posX/posY`, `origin`, `posType` - a widget with `useClipping = 0` COLLIDES
  rather than clipping, so its real budget is the distance to its neighbour and
  there is no way to compute that without positions. `origin` also decides
  vertical alignment, not just horizontal.
* `parent` and `layoutType` - `ParseAllItems()` flattens the tree, and a flat
  list cannot say what a label is drawn ON. Rebuilt here by matching object
  identity, so it stays correct if the walk order ever changes.
* `subW`/`subH`/`window` - `MenuSubContainer.CreateWindow` OVERWRITES a sub
  item's own `size` with the parent's `subItemsBase*`, so the row's `size` is
  NOT the plate. Read the plate off the container that defines it.
* `usage`/`nodeType` - several usages carry two `UserResource` nodes competing
  with the `SystemResource` one. You cannot reason about a screen without
  knowing which node is live, and a node's NAME does not tell you.

`effectparams` exists because **a Condition stores its battle messages TWICE**:
the flat `messageForAlly` family, and again inside
`EffectParamSettings.EffectParamList[]` on an element exposing `Message` and
`ChangeParam`. **The engine reads the nested copy.** A flat field table cannot
reach it, so those strings are never units, and the usual "re-extract the
injected build and look for residual Japanese" check cannot see them either -
it inherits the same blind spot and reports clean.

**This game has 16 of them** (32 rows: `Message` and `ChangeParam` hold the same
string, so write both). Run it and check whether your patch translated them:

    BakinTL effectparams proj effectparams.tsv

Fill them by SOURCE MATCH against the already translated flat field rather than
translating twice - that also guarantees the two copies cannot drift. `inject`
accepts a dotted write key for this:

    R:<guid>:EffectParamSettings.EffectParamList[3].ChangeParam

`SetField` also now writes `posX`/`posY`/`scaleX`/`scaleY`. `pos` and `scale`
are XNA `Vector2` STRUCTS, so the boxed copy has to be written back or the
assignment is silently lost; a `scale` of 0 is refused because it erases the
text.

Before trusting a translated build, run the **no-op**: turn `units.jsonl` into
`{key, en: src}` and inject it. Every one of the 138 files must come back byte
identical. Anything else means the injector is corrupting data, not translating it.
