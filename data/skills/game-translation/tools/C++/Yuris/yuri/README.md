# Yuri

A decompiler and compiler for the Yu-Ris engine, with parallelism.

Tested on many versions, including public and commercial.

## Requirements

1. Python 3.13.x (not 3.12 nor 3.14)
2. `pip install murmurhash2 xor_cipher deflate`

## Usage

There is no exact given path, since each game is different, but everything can be done through the main.py file. It is important to read the technical breakdown of the engine, since it explains some crucial information for the decompilation/compilation process (for example, the process of obtaining the XOR decryption keys for YSTB files).

- [Technical breakdown of the engine](yuri.md)

### Examples

- [Fraternite and Fraternite HD](guides/fraternite.md)
- [Unionism Quartet](guides/unionism-quartet.md)

### Miscellanous tools

- **patch_text.py**: this tool is mostly intended to streamline the translation process, since they are used to extract(ext) and edit(pat) text in .yuri files (dialog lines only).
  Both their arguments are (.yuri directory, text directory).

- **gbk.py**: this is also intended for translations, specifically Chinese ones. The idea is to patch the main Yu-RIS executable of a game, so that all text in the game is encoded in GBK instead of Shift-JIS.
  Obviously, in order to make the game work properly, the custom compiler needs to be told that the output encoding of the ysbin.ypf file will be in GBK.
  Modified from: https://github.com/jyxjyx1234/YURIS_TOOLS/blob/main/GBK.py
