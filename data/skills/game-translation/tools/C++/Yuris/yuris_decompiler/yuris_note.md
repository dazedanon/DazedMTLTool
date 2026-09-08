# Yu-Ris Note

Not mentioned here are the same as [Notes.txt](https://github.com/arcusmaximus/VNTranslationTools/blob/main/VNTextPatch.Shared/Scripts/Yuris/Notes.txt)

## YSL.ybn (Labels)

```
u32 magic == 'YSLB'
u32 version
u32 n_labels
u32 hash_to_index[256] // Index of the first label with hash.MSB == i;
Label [n_labels]
  u8   name_size
  char name_bytes[name_size]
  u32  name_hash  // Adler32 or Murmurhash2 as in YPF
  u32   pc          // offset in 2xx, index in 3xx
  u16  i_script
  u8   if_level   // IF nesting level
  u8   loop_level // LOOP nesting level
```

## YSTxxxxx.ybn (Script)

V200

In V200, commands for Global, Static vars are in both YSTB and YSVR
In V300, only Static and Folder vars are in both, Globals are only in YSVR
Locals are always in YSTB, not in YSVR

```
u32 magic == 'YSTB'
u32 version // 200-300
u32 cmds_size
u32 expr_size
u32 expr_offset == 32+cmds_size
u32 pads[4] == [0,0,0,0] // 32 bytes header
----
u8  cmds_data[cmds_size] // XOR'd with ystb key
u8  expr_data[expr_size] // XOR'd with ystb key

Cmd[]
  u8  code // as index in ysc.ybn or YSCom.ybn
  u8  n_args
  u16 line_no
  Arg args[n_args]
    u16 kw_id       // as index in ysc.ybn or YSCom.ybn's Cmd.Args
    u8  type        // low 2 bits: 1:INT 2:FLT 3:STR; see below for 0
    u8  assignment  // 0-8: '=', '+=', '-=',  '*=',  '/=',  '%=',  '&=',  '|=',  '^='
    u32 expr_size    // in expr_data
    u32 expr_offset // in expr_data
// For special commands, don't lookup kw_id in ysc.ybn or YSCom.ybn
// LET, INT, G_INT and other variable definitions
// WORD  : type is 0, and expr_data is a raw string (not instruction)
// V290  : for RETURNCODE: only expr_size is present, therefore its Arg is 6 bytes
// Others: for RETURNCODE: no expr_size and expr_offset, Arg is only 4 bytes
// for RETURNCODE: expr_size is not a data size, I haven't figured out its meaning
// for IF, ELSE(else if), LOOP: the 2nd and onwards arguments: (plain ELSE has no argument)
// - expr_size is a branch target (see Label)
// - expr_offset equals to their branch target's first arg data offset
//   - if no target, equals to the current position of expr_data (increasing)
// - IF/ELSE(= else if): elif, ifend; LOOP: loopend
// Sometimes for var def commands's second arg (LVal), type doesn't match, idk why
```

V300

```
u32 magic == 'YSTB'
u32 version // 300-500
u32 n_cmds
u32 cmds_size == n_cmds * 4
u32 args_size // % 12 == 0
u32 expr_size
u32 lnos_size == n_cmds * 4 // Line Numbers
u32 pad == 0 // 32 bytes header
----
u8  cmds_data[cmds_size] // XOR'd with ystb key
u8  args_data[args_size] // XOR'd with ystb key
u8  expr_data[expr_size] // XOR'd with ystb key
u8  lnos_data[lnos_size] // XOR'd with ystb key

Cmd[]:
  u8  code
  u8  n_args // sequentially read N Args from args_data
  u16 n_para // value count (PINT, RINTs) for GOSUB and RETURN; for others 0
Arg[]:
  u16 kw_id
  u8  type
  u8  assignment
  u32 expr_size   // unlike V200, always present, WORD is still raw string
  u32 expr_offset // unlike V200, always present, WORD is still raw string
  // for special commands, see V200
```

## YSV.ybn (Variables)

My terminology: compiler var == internal var == system var

```
Var
  u8  scope // 1:Global, 2:Static, 3:Folder
  u8  g_ext // since V481, see below
  u16 i_script
  u16 i_var // increasing, no entry for local vars
  u8  type  // 1:INT 2:FLT 3:STR 0:see below
  u8  n_dim
  u32 dims[n_dim] // Array dimensions
  if type == 0: None
  if type == 1: i64 init_val
  if type == 2: f64 init_val
  if type == 3: u32 size; u8 expr[size]; // using the YSTB expression vm code
// i_var 0 to 999 (inclusive) is for compiler variables
// there will be initial values due to file format requirement
// a type of 0 means the compiler does not exist, never 0 for real vars
```
