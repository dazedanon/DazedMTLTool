# YU-RIS Decompiler

[the version before rewrite](https://github.com/shimamura-sakura/yuris_decompiler/tree/400654a261cf93629a6271cd164fb7a854badfc7)

[my note on the file formats](yuris_note.md)

A decompiler for the Yu-Ris game engine.  
(It's visual novel part is called E-Ris, which is written in Yu-Ris script itself)  
Now also with a YPF extractor.  
Supports versions from 0.247 to 0.494  
Currently missing YSCFG (yscfg.ybn) format.

Dependency: `pip install murmurhash2` for YPF extracting

# Usage

Currently there are no commandline interface or gui, you need to call it by code.  
See [example.py](example.py) for usage of YPF extractor and YSTB decompiler

# Tested on

## Decompile and Recompile

- official sample of 0.255
- official sample of 0.494
- 夏空あすてりずむ [DLsite RJ367965](https://www.dlsite.com/maniax/work/=/product_id/RJ367965.html) (Yu-Ris 0.488)

The recompiled files are equal to the originals except yst_list.ybn.  
yst_list.ybn differs only in the modification time fields, which do not affect execution.

## Parsing files

- YSCom.ycd: 247-494 (format haven't changed since 247)
- Other files: 247, 255, 290, 292, 450, 461, 466, 479, 480, 481, 488, 494

## Thank You

- file format: [arcusmaximus/VNTranslationTools](https://github.com/arcusmaximus/VNTranslationTools/blob/main/VNTextPatch.Shared/Scripts/Yuris/Notes.txt)
- ysvr >v455: [1F1E33-float32/Tools](https://github.com/1F1E33-float32/Tools/blob/main/VisualNovel/Engine/YuRis/decompiler/ysvr.py#L72)
- some special commands: same as above
