# RPG Maker RGSSAD / RGSS2A / RGSS3A

Archive tooling for RPG Maker **XP** (`.rgssad`), **VX** (`.rgss2a`) and
**VX Ace** (`.rgss3a`).

| file | what it is |
|---|---|
| `rgssad.py` | reader/extractor for v1 and v3, written from the format. `--list`, `-o`, `-v`, path-traversal guarded |
| `install-template.ps1` | a PLAYER-facing installer for a VX Ace patch: unpacks the archive, copies the patch over it, moves the archive aside. `-Uninstall` reverses it |
| `install-template.bat` | double-click wrapper (`-ExecutionPolicy Bypass` for that process only) |

## The thing to know before shipping any VX Ace patch

**RGSS3 reads the ARCHIVE before it reads a loose file.** With `Game.rgss3a`
present, `Data\*.rvdata2` is served out of the archive and an identically-named
loose file beside it is ignored. A patch dropped in next to the archive does
nothing at all, and does it silently - the game starts in Japanese with a fully
translated `Data\` sitting right there.

Audio is loose in a stock VX Ace game and is NOT in the archive, which is the
proof that RGSS falls back to the filesystem for anything the archive does not
contain. So the archive must be emptied and taken out of the loop:

```
1. extract Game.rgss3a into the game folder   -> Data\ and Graphics\
2. copy the patch over the extracted Data\
3. MOVE Game.rgss3a out of the folder         <- not optional
```

`install-template.ps1` is that, for a player who has neither Python nor an
extractor. Copy it next to a `Patch\Data\` folder, adjust the game name in the
banner, ship the two files with the patch.

The unpacking inside it is a small C# class compiled at run time with
`Add-Type`, because the archive is ~95 MB of XOR-ed bytes and a PowerShell byte
loop takes minutes where compiled code takes seconds. Verified against
`rgssad.py`: all 467 graphics extracted by the PowerShell installer are
byte-identical to the Python extractor's output, and `-Uninstall` restores an
archive byte-identical to the original.

## Format, for when something does not parse

```
header      "RGSSAD\0" + version byte (1 = XP/VX, 3 = VX Ace)

v1/v2       entries follow immediately, XOR-ed with a running key that starts
            at 0xDEADCAFE and advances key = key*7+3 after every 4-byte field
            and after every name byte.
            entry: u32 name_len, name bytes (one key step each), u32 size,
                   then size bytes encrypted with the key reached at that point

v3          u32 seed, then key = seed*9+3 for the whole entry table.
            entry: u32 offset, u32 size, u32 data_key, u32 name_len, name
                   bytes XOR-ed with the key's 4 LE bytes cycled.
            offset == 0 ends the table. Payload is XOR-ed with data_key,
            advancing k = k*7+3 after each 4-byte block.
```

The v3 entry table is a flat list with absolute offsets, so a partial archive
is legal and a repack is possible - but repacking redistributes the game's own
art, which is a licensing question rather than a technical one. The installer
approach keeps the player's own archive as the source of those bytes.
