# An introduction to Yu-ris

[Yu-ris](https://yu-ris.net) is a free game engine developed by
[Firstia](https://firstia.com), mainly used to make visual novels.

This document is going to give a brief but deep dive into the inner workings of this engine.

## Main concepts

- The YST language

The engine runs its own programming language
(which I will call by its file extension `YST` as it has no official name),
compiled to binary `YBN` files, which are then packed into a `YPF` archive.
In the YST language, besides conventional programming language features like
variables, expressions, control structures, there are also commands for game
features: text, image, sound, video, keyboard and mouse input etc.

- The E-ris library

Using the YST language, the Yu-ris author developed a library called `E-ris` for
making visual novels. Visual novel makers writes scenario text and uses macros
offered by E-ris for choices, screen effects etc. And E-ris does the rest:
drawing the screen, handle save/load, backlog, settings screen etc.

- Special versions

The Yu-ris author have created some custom versions for commercial games.
Also, some fan-translation teams had made changes to the engine in the process
of translation.

### The YST language

This part describes the syntax and semantics of the YST language.

#### Syntax

Generally, one line contains one statement, or many statements separated by
semicolons (`;`). There are several kinds of statements:

```
// There are C++ style comments
/* and C style comments */

// Command
// - regular command
CG[ID=BG Z=3 FILE="ABC.bmp"]
// - control structures use command form too
IF[@A==1]
  // Do something
ELSE[]
  // Or do something
IFEND[]

// Text
// - basic
素早い狐はのろまな犬を飛び越える
// - variable as text
_["素早い狐はのろまな犬を飛び越える"]

// Label
// - simple forms
#LABELNAME
#"LABELNAME"
#=LABELNAME
#="LABELNAME"
// - command form
LABEL[#=LABELNAME]

// Assignment
// - basic
@A = 1
// - with operator
@A += 1
// - command form
LET[@A+=1]
```

A command can have zero or more arguments, separated with spaces.  
All arguments are keyword arguments and there are no positional arguments.  
Some arguments are mandatory and some are optional.

Arguments can have an assignment operator, like `+=`, `-=`.

String values can be 'single quoted' or "double quoted", and they can be written
without quotes if they don't contain spaces.

Indentation is not significant.

There are also macros, but it's better to understand variables and commands
first. After that, I will describe the macro system.

#### Variables

There are 3 data types:

```
INT[@A=1]   // 64-bit signed integer, like C int64_t
FLT[@B=1.0] // 64-bit floating point number, like C double
STR[$C="S"] // variable length string, like Python str
```

Variable names is always prefixed with a character indicating their types:

- `@` for two number types
- `$` for string type

Variables can also be arrays. Array indices are 0-based.  
Their dimensions are written in parentheses `(1,2)`, separated with comma (`,`).

```
INT[@D(6,7)]
@D(4,2) = 1
```

To refer to the array itself, use empty parentheses `()`.

```
// define an array with size 5
INT[@ARR(5)]
// this command means increasing its size by 3, to 8
VARACT[SET=@ARR() SIZE+=3]
```

There are 5 kinds of variable:

```
// global (prefix G_), visible to all scripts
// global variables are only definable in files named global.yst
G_INT[@G=123]

// static (prefix S_), visible to the script defining them
S_INT[@S=456]

// folder (prefix F_), visible to a folder and its subfolders
// folder variables are only definable in files named global_f.yst
F_INT[@F=789]

// local (no prefix)
// used in functions, saved across function calls
INT[@L=12345]

// system, defined by the engine, for various purposes
// they all have an underscore prefix in their names
@L = @_KEY_SPACE
```

In newer versions, global also has two additional kinds:

```
// Also only definable in files named global.yst
G_INT2[@G2=123]
G_INT3[@G3=456]
```

#### Control Structures

`IF` and `LOOP` can be nested up to 64 levels.  
`GOSUB` recursion depth is also at most 64 levels.

##### IF/ELSE/IFEND, IFBREAK, IFCONTINUE

Do things conditionally

**Basic**

```
IF[condition1]
  // do something
  IF[condition11]
    // do something
  ELSE[]
    // or do something
  IFEND[]
ELSE[condition2]
  // do something
ELSE[condition3]
  // do something
IFEND[]
```

**Continue and Break**

- `IFCONTINUE` jumps to the beginning of the `IF`, re-evaluating the condition.
- `IFBREAK` jumps to the `IFEND`.

They can take an argument `LV=x` to refer to the outer `IF`s.  
The innermost level is `1`.

##### LOOP/LOOPEND, LOOPBREAK, LOOPCONTINUE

Repeat for some times

```
// repeat 5 times
// the LOOPCONTINUE jumps to here
LOOP[SET=5]
  // infinite loop
  LOOP[]
    LOOPBREAK[LV=2]
  LOOPEND[]
  LOOPCONTINUE[]
LOOPEND[]
// the LOOPBREAK jumps to here
```

In a loop, use system variable `@_LC` to refer to the loop counter (1~N)
of the current innermost loop.

##### GO

Jump to a label

```
GO[#=LABELNAME]
#LABELNAME // GO jumps to here, can be in another file
```

##### GOSUB/RETURN

Call a label as a function

```
GOSUB[#=LABELNAME PINT=1 PSTR2="StringArg" PFLT3=42.0]
INT[@Ret1=@_RINT(1)]
FLT[@Ret2=@_RFLT(2)]
STR[$Ret3=@_RSTR(3)]

#LABELNAME
INT[@Arg1=@_PINT(1)]
STR[$Arg2=$_PSTR(2)]
FLT[@Arg3=@_PFLT(3)]
RETURN[RINT=@Arg1+1 RFLT2=@Arg3+2.0 RSTR3=$Arg2+"?"]
```

Different types of values are counted together,
using `PINT` and `PFLT` together is wrong and will become a compile error.

#### Commands

There are many commands controlling various aspects of a game, for example:

- `CG`, `CGACT`, `CGINFO`, `CGEND`: image layers
- `MOVIE`, `MOVIEINFO`, `MOVIEEND`: play video
- `SOUND`, `SOUNDINFO`, `SOUNDEND`: play sound
- `WINDOW`, `WINDOWINFO`, `WINDOWEND`: game windows
- `TASK`, `TASKINFO`, `TASKEND`: multitasking

For a full list, please read the
[official manual](https://yu-ris.net/manual/yu-ris/index.html).  
It's written in formal Japanese and can be machine translated.

#### Expressions

- Arithmetic
  - `+`: addition, also string concatenation
  - `-`: subtraction, or unary negation
  - `*`: multiplication
  - `/`: division
  - `%`: modulo
- Binary
  - `&`: and
  - `|`: or
  - `^`: xor
- Logic
  - `&&`: and
  - `||`: or
  - `!`: not
- Comparison
  - `<`: less than
  - `>`: greater than
  - `<=`: less than or equal
  - `>=`: greater than or equal
  - `==`: equal
  - `!=`: unequal
- Conversion
  - `$(VALUE)`: integer to string
  - `@(VALUE)`: string to integer
  - `$@VAR`: (old version) integer to string
  - `@$VAR`: (old version) string to integer
- Special
  - `&VAR`: (undocumented) take variable number,
    get value using system variable `@_INT(x)`, `@_FLT(x)`, `$_STR(x)`

#### Macros

Macros are defined in files named `macro.yst` using the command `MACRO`.

| Parameter              | Meanining                                      |
| ---------------------- | ---------------------------------------------- |
| `NAME`,`NAME2`~`NAME8` | Macro name(s). A macro can have multiple names |
| `STR`                  | Template string, replaces the invocation       |
| `DEF`, `DEF2`~`DEF10`  | Default value for arguments if omitted         |

System (compiler) variables useful for coding macros:

| Name                  | Meaning                                |
| --------------------- | -------------------------------------- |
| `$_M`, `$_M2`~`$_M10` | Macro argument values                  |
| `@_SERIAL_GNO`        | An increasing unique number            |
| `$_SERIAL_GNO2`       | An increasing unique number, as string |

The two serial numbers are increased with command `PREP`
argument `SERIAL_GNO=1` or `SERIAL_GNO=2`.

Example:

```
// in macro.yst
MACRO[NAME="HELLO" STR="PREP[SERIAL_GNO=2];LABEL[#='lbl.'+$_SERIAL_GNO2]"]
MACRO[NAME="WORLD" STR="$_M=$_M2" DEF2="42"]

\HELLO       // defines a label named "lbl.XXXX" here (XXXX is a number)
\WORLD($X,Y) // expands to $X=Y
\WORLD($X,)  // expands to $X=42
```

#### System Startup and Project Settings

The game starts running at a label named `SYSTEM_START`.
It's usually in the file `system_start.yst`.

In the project's `data/config/projectconfig.txt`, the user
sets a few options like window title, window size.

### The E-ris Library

The E-ris library is distributed in source code form, located at official SDKs'
`システム/data/script/ERIS`.

Visual novel makers write their scripts in `data/script/userscript`, using
macros offered by E-ris.  
Also, they modify the files in `data/script/userdefine` to do customizations
like UI, Font.

E-ris is very complex and uses many undocumented feature of Yu-ris, thus hard
to understand.  
I will only describe its interaction with the users' scenario scripts.

#### The interaction between E-ris and scenario scripts

First, `#SYSTEM_START` jumps into E-ris.
Then, E-ris starts a task running the user's `SCENARIO_START.txt`.  
Each time the script wants to do some thing, like displaying a dialog line,
show a multiple choices, or play some screen effects, it sets some parameters
and gives control to E-ris. And E-ris does the real job.

In fact, every text line is converted to a `WORD` command, and at the ends of
every line, a `RETURNCODE` command is inserted.  
The text is stored into system variable `$_TEXT`, to be read by E-ris.
And `RETURNCODE` is the command giving up control.  
For other things, the E-ris macros set relevant global variables and use `WAIT`
command to give up control.

For save and loading, the `TASK` command can also get and set other tasks'
executing position.  
E-ris saves and load relevant variables, as well as this position of the
scenario task.  
All scenario variables is also managed by E-ris.

### Special Versions

#### Commercial

For commercial titles, the author has made many custom versions.
They differ from the public versions mainly in several points:

- Version numbers

Sometimes they use special version numbers, not reflecting which public versions
they are based on.  
For example, [Unionism Quartet](https://vndb.org/v15288) has 554 in its YBN
files, but it's file formats resemble those of public version before 481.  
And [Fraternite](https://vndb.org/v14895) uses 490, but uses public pre-481
formats.

- Encryption Key

YSTB YBN files are XOR encrypted with a key (explained later).  
In those games, this key is different from the one used in public versions.

- New Commands

Sometimes, the author adds special commands to implement certain features of
that game.  
There is one command often named `PRODUCT`.

- Special E-ris Features

Some game uses a CG image as font, instead of operating system drawing.

- Encoding

For some multi-language games, the engine is changed to use UTF-8 encoding.

- Different Field Meanings

In YSTB YBN files, a `gosub_npar` field has different meaning than the public
version. See [below](#new-format).

#### Fan-Translated

- `WORD` Encoding

In some translated games, the engine is modified to use a different encoding for
displaying text.  
For example, some Chinese fan-translated games uses GBK for dialog text
(`WORD` command), keeping JIS(CP-932) for all other strings.

## File Formats

The assets of Yu-ris Engine games are just the common ones (bmp, png, ogg etc.).

The game has an archive format YPF and several different formats of YBN files:

- `YSCM` (ysc.ybn) command definitions
- `YSCF` (yscfg.ybn) engine configurations
- `YSER` (yse.ybn) error messages
- `YSTD` (yst.ybn) global counts
- `YSLB` (ysl.ybn) label list
- `YSVR` (ysv.ybn) variable list
- `YSTL` (yst_list.ybn) script list
- `YSTB` (ystXXXXX.ybn) compiled script

Also there is one important file in the official SDK

- `YSCD` (YSCom.ycd) compiler's command definitions

Types

- `uXX`, `iXX`: unsigned and signed integers, always little-endian
- `sz`: a null-terminated string

[Notes.txt]: https://github.com/arcusmaximus/VNTranslationTools/blob/main/VNTextPatch.Shared/Scripts/Yuris/Notes.txt

Many are adapted from [Notes.txt]

### YPF Archive

```
u8  magic[4] == 'YPF\0'
u32 version
u32 file_count
u32 header_size
u8  padding[16]

Entry[file_count]
    u32 name_hash
    u8  name_size       // encrypted, see below
    u8  name[name_size] // encrypted, see below, default encoding CP932
    u8  file_type   // related to file extension
    u8  compression // 0 - none, 1 - deflate
    u32 size_uncompressed
    u32 data_size
    uXX data_offset // relative to file beginning, byte count depending on version
    u32 data_hash
```

- Header Size  
  the size of entries and (maybe) header itself.
  - In versions `< 300`, `header_size` doesnt't include the header itself.
  - In versions `>=300`, `header_size` includes the header.

- Encryption of Name Size
  - To decrypt, `name_size` is first XOR'd with 0xFF and then mapped with an array
  - To encrypt, do the reverse of this

```python
M = bytearray(range(256)) # name_size map array, do some swaps
for a, b in ((3, 72), (17, 25), (46, 50),
        (6, 53), (9, 11), (12, 16), (13, 19), (21, 27),
        (28, 30), (32, 35), (38, 41), (44, 47)):
    M[a], M[b] = M[b], M[a]
def decrypt_name_size(v: int):
  return M[v ^ 0xff]
def encrypt_name_size(v: int):
  return M[v] ^ 0xff
```

- Encryption of Name Bytes
  - Each byte of name is XOR'd with a certain value, default is 0xFF
  - XOR encryption and decryption is symmetric

```python
def en_de_crypt_name(s: bytes, v: int = 0xFF):
  return bytes(b ^ v for b in s)
```

- Hashing of Name and Data
  - `name`: hash decrypted name
  - `data`: hash unprocessed (not decompressed) data
  - The two may use different hashes, and hash methods differ across versions

- Integer Size of Data Offset
  - 32-bit in older versions
  - 64-bit in newer versions

**Summary of Changes between Versions**

- Since 0.200
  - `header_size` doesn't include header itself
  - name hash and data hash are both Adler32
  - `data_offset` is 32-bit

- Since 0.265
  - name hash becomes CRC32

- Since 0.300 (approximately)
  - `header_size` now includes the header itself

- Since 0.477
  - name hash and data hash both become 32-bit Murmurhash2
  - `data_offset` is now 64-bit

**Sample Code**

Requirement: `pip install murmurhash2`  
Only handles public versions, with options to override format differences

```python
from os import path, makedirs
from murmurhash2 import murmurhash2
from typing import BinaryIO, Callable
from zlib import decompress, crc32, adler32

M = bytearray(range(256))

for a, b in ((3, 72), (17, 25), (46, 50),
             (6, 53), (9, 11), (12, 16), (13, 19), (21, 27),
             (28, 30), (32, 35), (38, 41), (44, 47)):
    M[a], M[b] = M[b], M[a]


def mmh2(b: bytes):
    return murmurhash2(b, 0)


def parse_ypf(
    f: BinaryIO,
    name_size_map: bytes = M,
    name_xor_byte: int = 0xff,
    name_encoding: str = 'cp932',
    force_data_offset_bytes: int | None = None,
    force_header_size_include: bool | None = None,
    force_hash_name: Callable[[bytes], int] | None = None,
    force_hash_data: Callable[[bytes], int] | None = None
):
    # Header
    assert f.read(4) == b'YPF\0'
    version = int.from_bytes(f.read(4), 'little')
    file_count = int.from_bytes(f.read(4), 'little')
    header_size = int.from_bytes(f.read(4), 'little')
    assert version >= 200 and not any(f.read(16))
    print(f'YPF version={version} '
          f'file_count={file_count} '
          f'header_size={header_size}')
    # Version Differences
    data_offset_bytes = 4
    header_size_include = False
    hash_name = hash_data = adler32
    if version >= 265:
        hash_name = crc32
    if version >= 300:
        header_size_include = True
    if version >= 477:
        data_offset_bytes = 8
        hash_name = hash_data = mmh2
    if force_data_offset_bytes is not None:
      data_offset_bytes = force_data_offset_bytes
    if force_header_size_include is not None:
      header_size_include = force_header_size_include
    hash_name = force_hash_name or hash_name
    hash_data = force_hash_data or hash_data
    # Read Entries
    files: list[tuple[str, bytes]] = []
    for i in range(file_count):
        name_hash = int.from_bytes(f.read(4), 'little')
        name_size = name_size_map[f.read(1)[0] ^ 0xFF]
        name_bytes = f.read(name_size)
        name_bytes = bytes(b ^ name_xor_byte for b in name_bytes)
        assert hash_name(name_bytes) == name_hash
        name = name_bytes.decode(name_encoding)
        file_kind, compression = f.read(2)
        size_uncompressed = int.from_bytes(f.read(4), 'little')
        data_size = int.from_bytes(f.read(4), 'little')
        data_offset = int.from_bytes(f.read(data_offset_bytes), 'little')
        data_hash = int.from_bytes(f.read(4), 'little')
        print(f'[{i}] {name} kind={file_kind} '
              f'compression={compression} size={size_uncompressed} '
              f'data_size={data_size} data_offset=0x{data_offset:x} '
              f'data_hash=0x{data_hash:x}')
        save_pos = fp.tell()
        fp.seek(data_offset)
        data = fp.read(data_size)
        assert hash_data(data) == data_hash
        match compression:
            case 0: pass
            case 1: data = decompress(data)
            case c: raise ValueError(f'unknown compression {c}')
        fp.seek(save_pos)
        files.append((name, data))
    # Check Header Size
    if header_size_include:
        assert fp.tell() == header_size
    else:
        assert fp.tell() == header_size+32
    return files


with open('path/to/file.ypf', 'rb') as fp:
    files = parse_ypf(fp)


OUT_DIR = 'folder/to/extract'
for filename, data in files:
    fullpath = path.join(OUT_DIR, *filename.split('\\'))
    makedirs(path.dirname(fullpath), exist_ok=True)
    with open(fullpath, 'wb') as fp:
        fp.write(data)
```

### `YSCM` (ysc.ybn) command definitions

```
u8  magic[4] == 'YSCM'
u32 version
u32 cmd_count
u32 padding == 0
Command[cmd_count]
  sz  cmd_name
  u8  param_count
  Parameter[param_count]
    sz param_name
    u8 unknown
    u8 unknown
sz error_msg[37]
u8 unknown[256]
```

### `YSCF` (yscfg.ybn) engine configurations

Compiled from `projectconfig.txt`

```
u8  magic[4] == 'YSCF'
u32 version
u32 padding == 0
u32 compile
u32 screenWidth
u32 screenHeight
u32 enable
u8  imageTypeSlots[8]
u8  soundTypeSlots[4]
u32 thread
u32 debugMode
u32 sound
u32 windowResize
u32 windowFrame
u32 filePriorityDev
u32 filePriorityDebug
u32 filePriorityRelease
u32 padding = 0
u16 captionLength
u8  caption[captionLength]
```

### `YSER` (yse.ybn) error messages

```
u8  magic[4] == 'YSER'
u32 version
u32 err_count
u32 padding == 0
Err[err_count]
  u32 id
  sz  msg
```

### `YSTD` (yst.ybn) global counts

The total count of variables and texts (`RETURNCODE` commands) in all scripts.

```
u8  magic[4] == 'YSTD'
u32 version
u32 var_count
u32 txt_count
```

### `YSLB` (ysl.ybn) label list

A list of all labels from all scripts

```
u8  magic[4] == 'YSLB'
u32 version
u32 lbl_count
u32 idx_begin[256] // for label lookup, see below
Lbl[lbl_count]
  u8  name_size
  u8  name[name_size]
  u32 name_hash     // Uses the same hash as in YPF
  u32 code_position // see below
  u16 script_id     // An index into YSTL's script file list
  u8  if_level      // IF nesting level
  u8  loop_level    // LOOP nesting level
```

**idx_begin array**

All labels are sorted by their hashes.  
`idx_begin[i]` is the index of the first label with `name_hash >= (i << 24)`.  
Label lookup process is like:

```python
def find_label(name: bytes):
  name_hash = hash_name(name)
  first_idx = idx_begin[name_hash >> 24]
  for i in range(first_idx, lbl_count):
    if labels[i].name == name:
      return i
  raise ValueError('label not found')
```

**code_position**

In versions `< 300`, it's an offset into YSTB's command section.
In versions `>=300`, it's an index into YSTB's command array.

### `YSVR` (ysv.ybn) variable list

List of all non-local variables,
including their types, dimensions and initial values.

```
u8  magic[4] == 'YSVR'
u32 version
u16 var_count // this is only the size of Var array, not that in YSTD
Var[var_count]
  byte scope         // 1: Global, 2: Static, 3: Folder
  if version >= 481: // only present since 481, as G_xxx2/3 are added
    byte scope_ex    // 0: System, 1: Normal, 2: G_XXX2, 3: G_XXX3
  u16 script_id
  u16 var_id         // can be non-continuous, bec. local variables are skipped
  u8  type           // 0: System, Non-Existent; 1: INT, 2: FLT, 3: STR
  u8  dim_count
  u32 dim_sizes[dim_count]
  switch (type) {
    case 0:
      // NONE;
    case 1:
      i64 value;
    case 2:
      f64 value;
    case 3:
      u16 expr_size;
      u8 expr[expr_size]; // An expression whose result is a string, see YSTB.
  }
```

**Which variables are present**

- System variables take variable index 0-999, and they are all present.  
  Their `var_id`s are indices into `YSCD`'s SystemVar array.
  Non-existent system variables have type `0`, other kinds never have type `0`.
- Global, Static and Folder variables.
- Local variables are assigned a variable index, but is not present here,
  so their var_id is skipped.

### `YSTL` (yst_list.ybn) script list

```
u8  magic[4] == 'YSTL'
u32 version
u32 scr_count
Script[scr_count]
  u32 index
  u32 path_size
  u8  path[path_size] // original path of the source code resulting this YBN
  FILETIME modTime    // windows.h FILETIME structure
  i32 var_count       // count of variables defined in this script; see below
  u32 lbl_count       // count of labels defined in this script
  if version >= 477
    u32 txt_count     // count of `RETURNCODE` commands in this script
```

[FILETIME](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ns-minwinbase-filetime)

A negative `var_count` means there is no YBN file corresponding to it. Reasons:

- This is a `global.yst` file.
- This script is empty and is skipped by the compiler.

### `YSTB` (ystXXXXX.ybn) compiled script

There are two main versions of YSTB:

- Old version (`< 300`): commands and their arguments are in one section
- New version (`>= 300`): commands and arguments are splitted into two arrays

They both have an expressions section to store argument values of commands.

#### Encryption

Also, YSTB uses a simple XOR encryption for its sections.  
Each section is encrypted independently.

```python
# Assume that xor_key is given as big-endian
# That: 0x01020304, the first byte is 0x01
def en_de_crypt(section_data: bytes, xor_key: int):
  key_bytes = xor_key.to_bytes(length=4, byteorder='big')
  return bytes(b ^ key_bytes[i % 4] for i, b in enumerate(section_data))
```

```python
# Operate in-place using xor_cipher library
from xor_cipher import cyclic_xor_in_place
def en_de_crypt(section_data: bytearray, xor_key: int):
  cyclic_xor_in_place(xor_key.to_bytes(length=4, byteorder='big'))
```

YSTB file is like this

```
- Header
- Section1: bytes
- Section2: bytes
- Section3: bytes
```

And en/decryption is called on each section.

#### Old format

```
u8  magic[4] == 'YSTB'
u32 version < 300
u32 cmds_size
u32 exprs_size
u32 exprs_offset
u8  padding[12] // padding until 32 bytes
u8  command_section[cmds_size]
// Here: file position == exprs_offset
u8  expressions_section[exprs_size]
// - FILE END -

OldCommand[] // read until all command_section is consumed
  u8  cmd_id // index into YSCM/YSCD's command array
  u8  arg_count
  u32 line_number // line number of this command in original source code
  OldArgument[arg_count]
    u16 arg_id    // index into YSCM/YSCD's argument array
    u8  type      // value type (0: see below; 1: INT, 2: FLT, 3: STR)
    u8  assign_op // 0-8: =, +=, -=, *=, /=, %=, &=, |=, ^=
    if cmd_id != RETURNCODE:
      // offset and size into expressions_section
      u32 expr_size
      u32 expr_offset
```

#### New format

```
u8  magic[4] == 'YSTB'
u32 version >= 300
u32 cmd_count
u32 cmds_size == cmd_count * 4 //  4 bytes each command
u32 args_size % 12 == 0        // 12 bytes each argument
u32 exprs_size
u32 line_numbers_size == cmd_count * 4 // One number for each command
u32 padding // padding until 32 bytes
NewCommand[cmd_count]
  u8  cmd_id
  u8  arg_count
  u16 gosub_npar // argument count of GOSUB/RETURN commands
NewArgument[arg_count]
  u16 arg_id
  u8  type
  u8  assign_op
  // offset and size into expressions_section
  u32 expr_size
  u32 expr_offset
u8  expressions_section[exprs_size]
u32 line_numbers[cmd_count]
```

##### **gosub_npar**

In some commercial versions, `gosub_npar` is calculated in another way.

```python
# Input is like: ['PINT', 'PINTx', 'PFLTx', 'PSTRx']
def calculate_npar_public(argument_list):
  return len(argument_list)

def calculate_npar_alternate(argument_list: list[str]):
  n_int = 0
  n_str = 0
  n_flt = 0
  for arg in argument_list:
    if 'INT' in arg:
      k = arg.rpartition('INT')[2] # Get the 'x' part
      n_int = max(n_int, int(k) if k.isnumeric() else 1)
    if 'STR' in arg:
      k = arg.rpartition('STR')[2] # Get the 'x' part
      n_str = max(n_str, int(k) if k.isnumeric() else 1)
    if 'FLT' in arg:
      k = arg.rpartition('FLT')[2] # Get the 'x' part
      n_flt = max(n_flt, int(k) if k.isnumeric() else 1)
  # ff[2]_sssss[5]_iiiiii[6]_fff[3]
  return ((n_flt & 0b11) << 14) + (n_str << 9) + (n_int << 3) + (n_flt >> 2)
```

**How to know if a game uses a custom NPAR**

Go to the folder with the decompiled script and find a `GOSUB` in the dump files.  
For example, `data/script/eris/es_button.yst.dump`:

```
[215] off=860 lno=318 npar=16 44:GOSUB
- [0] # RArg(id=0, typ=<Typ.Str: 3>, aop=<AOp.EQL: 0>, siz=22, off=5057, dat=['"es.BT.GROUP.CHECK"'])
- [1] PINT RArg(id=1, typ=<Typ.Int: 1>, aop=<AOp.EQL: 0>, siz=6, off=5079, dat=[(<IOpV.VAR: 840>, <Tyq.NUM: 64>, 1413)])
- [2] PINT2 RArg(id=2, typ=<Typ.Int: 1>, aop=<AOp.EQL: 0>, siz=6, off=5085, dat=[(<IOpV.VAR: 840>, <Tyq.NUM: 64>, 1412)])
```

We see `npar=16`, but there are only two arguments `PINT`, `PINT2`.  
This means the game uses a special scheme for the `npar` field.


**Guessing the XOR key using line numbers**

The first few line numbers are often very small (`<256` or even `<16`),
so their high bytes are zero. And we know that `0 XOR v == v`.  
Thus there is high chance that the first few bytes of line number array
contains the first 3 bytes of the XOR key.

```
Original : A 0 0 0 B 0 0 0 (little endian integers)
XOR key  : P Q R S P Q R S (cyclic XOR)
Encrypted: ? Q R S ? Q R S
```

One method is that we only enumerate the lowest 1 byte or even only 4
bits. That's only 256 or 16 cases, very inexpensive to do.  
For each value, we use it to decrypt the line number array,
and see whether it's increasing.

```python
def guess_xor_key(line_numbers: list[int]):
  assert (line_numbers[0] >> 8) == (line_numbers[1] >> 8)
  for k in range(256):
    k += line_numbers[0] >> 8 << 8 # replace the lowest byte of line_numbers[0]
    try_decrypt = [v ^ k for v in line_numbers]
    for i in range(1, len(try_decrypt)):
      if try_decrypt[i-1] > try_decrypt[i]: # not increasing
        break
    else: # passed the increasing check
      # calculated in little endian
      return k.to_bytes(length=4, byteorder='little')
```

The other method is that we find the YBN file for
`data/script/ERIS/es_button.yst`.
Its first line number is often `9`, and XOR'ing it's first line number with `9`
is the key.

```python
def guess_xor_key_es_button(line_numbers: list[int]):
  return (line_numbers[0] ^ 9).to_bytes(length=4, byteorder='little')
```

Another method, which can prove to be faster, it is if you happen to get the message:

```python
AssertionError
lineno guess key: 0x3e,0xdf,0xa8,0x95,0x3d,0xdf,0xa8,0x95,0x3c,0xdf,0xa8,0x95,0x3b,0xdf,0xa8,0x95
data\script\eris\es_button.yst
```
If that is the case, the first thing to do is getting the first 4 bytes of the array, resulting in the value of **0x85984F1B**. So, **the idea would be to change the byte *5* in 0x85 to any number in between 0 and 4** (since it is 5 in this case) and try out all of the possible combinations. In this case, the possible keys to try out would be 0x8**4**984F1B, 0x8**3**984F1B, 0x8**2**984F1B, 0x8**1**984F1B, 0x8**0**984F1B.

#### Argument ID and Values

For most arguments, the meaning of `arg_id`, `expr_size` and `expr_offset` is as
written above.

However, for a few special commands, `arg_id` is useless, and `expr_` has
special meanings.  
(Below, expr is an expression if not mentioned).

- IF/ELSE/LOOP
  - The first argument is the condition or loop count
  - The second and the third argument's `expr_size` and `expr_offset` does not
    refer to a range in expressions_section, but
    - `expr_size` is the code position of `ELSE` or `LOOPEND`.
    - `expr_offset` is the expr offset of that `ELSE` or `LOOPEND`.
- Those defining and assigning variables (`G_xxx`, `LET`)
- WORD: The data in expressions_section is not an expression, but raw string
- RETURNCODE: `expr_size` is a value returned
- `_` (`WORD` but taking a variable as the word).

#### Expression

(Copied from [Notes.txt])

```
=====================================
Expression VM
=====================================
Apart from the scenario VM, YU-RIS has a tiny stack-based expression VM.
Each instruction consists of an opcode byte followed by a 16-bit argument length.

21 00 00           notequal
25 00 00           mod
26 00 00           logand
29 01 00 00        performvarindexation (uses all the stack values since the last "preparevarindexation" instruction as indexes)
2A 00 00           mul
2B 00 00           add
2C 00 00           nop (array index separator)
2D 00 00           sub
2F 00 00           div
3D 00 00           equal
3C 00 00           less
3E 00 00           greater
41 00 00           binand
42 01 00 XX        pushint8
46 08 00 XX{8}     pushdouble
48 03 00 TT XX XX  pushscalarvar
49 04 00 XX{4}     pushint32
4C 08 00 XX{8}     pushint64
4D XX XX 22 ... 22 pushstring (quoted string with support for \\, \n and \t escape codes, but not \" or \')
4F 00 00           binor
52 00 00           changesign
53 00 00           le
56 03 00 TT XX XX  preparevarindexation
57 02 00 XX XX     pushint16
5A 00 00           ge
5E 00 00           binxor
69 00 00           tonumber
73 00 00           tostring
76 03 00 TT XX XX  pusharrayvar (used to specify @ARRAY() in e.g. VARINFO in SEARCH mode)
7C 00 00           logor
```

**Values of TT**

- 0x24 (`$`): string variable
- 0x40 (`@`): number variable
- 0x23:
  - v `< 300`: integer to string
  - v `>=300`: take variable number of string variables
- 0x60:
  - v `< 300`: string to integer
  - v `>=300`: take variable number of number variables

**Unary Binary And**

In one rare case in E-ris, this is generated from `&0`,
which I guess means a NULL variable reference.

**Unary Comparison Not Equal**

Occured in one game, written as `IF[!='']`.  
I suspect this is a bug of the official compiler.

### `YSCD` (YSCom.ycd) compiler's command definitions

(Adapted from [Notes.txt])

```
u8  magic[4] == 'YSCD'
u32 version
u32 cmd_count
u32 padding == 0

Command[count]
  sz name
  u8 arg_count
  Argument[arg_count]
    sz name
    u8 unknown[4]

u32 sysvar_count
u32 padding == 0
SystemVar[sysvar_count]
    sz  name
    u8  type
    u8  dim_count
    u32 dim_sizes[dim_count]

u32 errmsg_count
u32 padding == 0
sz  errmsg[errmsg_count]
sz  errors[37] // seems to be the same as in YSCM
u32 some_num
u32 padding == 0
u8  unknown[some_num*some_num]
u8  unknown[0x800]
```

System variable names can be recovered using this file.
