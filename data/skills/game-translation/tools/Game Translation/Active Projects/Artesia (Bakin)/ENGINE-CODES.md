# Bakin text control codes - engine reference

Target: `執聖官アルテシアVer1.06\data\bakinengine.dll` + `common.dll`.
Bakin build **r64268** (`revision.txt`, committed 2024-07-31), ROM version 74 (`Yukar.Common.Catalog.sRomVersion = 74`).

Decompiled with `dnSpy.Console.exe` (`C:\Users\sw\Desktop\Tools\.NET\dnspy\dnSpy.Console.exe`), C# and IL views.
Every claim below marked **VERIFIED** was read out of the decompiled C# and cross checked against the raw IL of the method named.
Claims marked **INFERRED** are reasoning about consequences, not things read directly.
Codes stated as absent were searched for by name in both assemblies' full decompilation and in the raw string heaps.

Usage counts come from `census.tsv` in this project directory (155,298 attribute rows dumped from the game's ROM).
The census escapes real control characters, so counts were taken after a single left to right decode of `\\` `\n` `\r` `\t`, which keeps a genuine `\`+`n` in the data distinct from a genuine LF.

---

## 1. The pipeline

Message text reaches the screen through exactly two parsing passes, in this order.

**Pass 1 - `Yukar.Engine.GameMain.replaceForFormat(string, Guid)`** (`GameMain.cs:1558`).
A regex substitution pass that resolves variables and a few globals into plain text.
It runs before anything else sees the string.

**Pass 2 - `Yukar.Engine.MessageReader.MessageEntry.separateByCommands(float, Color)`** (metadata token `0x060014BF`).
A hand written character scanner that turns the substituted string into a `List<MessageParts>` carrying styling, timing, line index, ruby and nameplate state.
This is the only place the single letter escapes are recognised.

Entry points that run both passes:

- `MessageReader.ReadMessage` (message boxes and dialogue balloons) via `LayoutStateMessage.PushMessage` and `LayoutStateDialogue`.
- `LayoutStateTelop.InitializeCallback` (telops) calls `replaceForFormat` then `separateByCommands` directly, then `wordWrap`, but **not** `splitByLines`, so telops are never paginated.

`Yukar.Common.Rom.GameContentParser.keyWords` (541 regex literals, 376 distinct base names, `GameContentParser.cs:249`) is a **different, non overlapping** system.
It substitutes menu and HUD placeholders such as `\partyname[0]`, `\currentitemnum`, `\innprice`, `\nameplate`, `\message` into *layout node* text.
The message body itself never passes through it. `EventContentGetter` handles `ContentType.MESSAGE` by handing the already parsed `MessageEntry` to the renderer (`result.MessageEntry = this.gameContent.MessageEntry`), and the body is drawn by `MessageEntry.drawStringWithCommands`, never by the `GameContentParser` text path.
I confirmed `savevar` appears in neither the keyWords table nor anywhere in either assembly.

---

## 2. Pass 1 codes - `GameMain.replaceForFormat`

The whole method, verbatim:

```csharp
public string replaceForFormat(string str, Guid sender)
{
    this.recentSender = sender;
    return Regex.Replace(Regex.Replace(Regex.Replace(
        str.Replace("\\\\", "\t"),
        "\\\\([vhs$#H]|Variable|\\$L)\\[([^\\[]*?)\\](?!\\[)", new MatchEvaluator(this.variableEvaluator)),
        "\\\\(\\$)\\[(.*?)\\]\\[(.*?)\\]",                     new MatchEvaluator(this.arrayVariableEvaluator)),
        "\\\\(map|time|money)",                                 new MatchEvaluator(this.specialTextsEvaluator))
        .Replace("\t", "\\\\");
}
```

After C# string unescaping the three regexes are:

1. `\\([vhs$#H]|Variable|\$L)\[([^\[]*?)\](?!\[)`
2. `\\(\$)\[(.*?)\]\[(.*?)\]`
3. `\\(map|time|money)`

| code | argument | argument is | uses in this build | notes |
|---|---|---|---|---|
| `\\` | none | n/a | 0 | Escaped literal backslash. Handled by the tab shuttle, see 2.1. Survives pass 1 as `\\` and is collapsed to one `\` by pass 2. |
| `\$[name]` | yes, `[^\[]*` | **KEY** - string variable name | 7 in Script, 111 in LayoutProperties, 25 in NSkill formulas | `data.system.GetStrVariable(name, Guid.Empty, false)`. Never translate the bracket. |
| `\$L[name]` | yes | **KEY** - local string variable name | 0 | `GetStrVariable(name, this.recentSender)`, scoped to the event that sent the message. |
| `\$[name][index]` | two, both `.*?` | **KEY** name, **KEY** integer index | 0 | Pass 2 of the regex chain. `GetStrFromArray(name, index)`. Only reachable because regex 1 has the `(?!\[)` lookahead. |
| `\#[name]` | yes | **KEY** - numeric variable name | 2 in Script | `GetVariable(name).ToString("0.##")`. |
| `\v[N]` | yes | **KEY** - integer slot index | 0 | Numeric variable by ordinal via `varDefs.getVariableEntry(Guid.Empty, VarType.DOUBLE, N)`. |
| `\Variable[N]` | yes | **KEY** - integer slot index | 0 | Falls through to the identical code path as `\v`. Verified in the hash switch of `variableEvaluator`: `"Variable"` and `"v"` both reach the DOUBLE branch. |
| `\s[N]` | yes | **KEY** - integer slot index | 0 | String variable by ordinal, `VarType.STRING`. |
| `\h[N]` | yes | **KEY** - integer party index | 0 | `data.party.getHeroName(catalog.getFilteredItemList(typeof(Cast))[N].guId)`. |
| `\H[castname]` | yes | **KEY** - database `Cast` name | 0 | `catalog.getItemFromName(name, typeof(Cast))`. Looks up the *database record name*, not display text. Returns `""` if not found. Do not translate unless you also rename the Cast rom item. |
| `\map` | none | n/a | 0 | Current map name, or the literal `"Map Name"` if no map is loaded. |
| `\time` | none | n/a | 0 | `data.system.GetPlayTime()`. |
| `\money` | none | n/a | 0 | `data.party.GetMoney().ToString()`. |

Anything the evaluators do not recognise returns `""`, so a malformed key silently deletes the whole code.

### 2.1 How `\\` is handled - the tab shuttle

`replaceForFormat` protects escaped backslashes by swapping them out of the regex domain and back:

```csharp
str.Replace("\\\\", "\t")   //  \\  ->  U+0009
    ... three Regex.Replace passes ...
   .Replace("\t", "\\\\")   //  U+0009 -> \\
```

Consequences, all **VERIFIED** from that code:

- `\\$[x]` is *not* variable substituted. It leaves pass 1 as `\\$[x]`, and pass 2 turns `\\` into one literal `\`, so the player sees `\$[x]`. This is the correct way to show a literal code.
- **The round trip is not injective.** Any genuine TAB character already present in the message becomes `\\` on the way out, which pass 2 then renders as a single visible `\`.
  The census shows 1,596 real TAB characters across text rows, so this is not hypothetical.
  A translation pipeline must never let a literal TAB into a message string.
- The swap is unconditional and non greedy in the usual sense. `\\\` (three backslashes) becomes TAB + `\`, and the trailing `\` is then eligible for regex 1.

---

## 3. Pass 2 codes - `MessageReader.MessageEntry.separateByCommands`

### 3.1 The dispatch structure

The outer loop reads one character at a time. Order of tests, taken from the IL at `0x000CD7FD` onward:

```
IL_0087: ldc.i4.s 13   // '\r'  -> skipped entirely, escape flag NOT cleared
IL_0090: ldc.i4.s 10   // '\n'  -> hard line break, escape flag NOT cleared
IL_00A2: ldc.i4.s 92   // '\'   -> if flag clear: flush part, set flag
                       //          if flag set:   clear flag, append one '\' as text
IL_00FA: ldloc.0       // flag? -> no: append char as text
                       //          yes: escape body below
```

Escape body, in order:

```csharp
string substr = this.text.Substring(i);
string text = MessageReader.MessageEntry.commands.FirstOrDefault<string>((string x) => substr.StartsWith(x));
if (text != null) { /* multi letter command */ }
else              { /* single letter switch */ }
```

with

```csharp
private static readonly string[] commands = new string[] { "blink", "blspd", "blrate", "lipspd", "lip", "NP" };
```

**Multi letter commands are tested first, in array order.** The single letter switch is only reached when none of the six matched.

The bracket argument reader is a closure shared by both branches:

```csharp
Func<string[]> func = delegate
{
    if (this.text.Length <= i + 1 || this.text[i + 1] != '[') return new string[0];
    int num4 = this.text.IndexOf(']', i);
    if (num4 < 0) return new string[0];
    string[] array3 = this.text.Substring(i + 2, num4 - i - 2).Split(new char[] { ',' });
    i = num4;
    return array3;
};
```

Four properties of this reader matter for translation:

- The argument ends at the **first** `]` at or after the code letter. A `]` inside the argument truncates it.
- The argument is **split on commas**, always. Codes that read only `array[0]` therefore silently discard everything after the first comma.
- If the next character is not `[`, it returns an empty array and does **not** advance `i`.
- **It is invoked unconditionally for every single letter escape, before the character is even examined.** IL `IL_02AE: callvirt Func<string[]>::Invoke()` precedes the first comparison at `IL_02B7`. So a code that has no use for an argument still consumes and discards one. See trap 6.9.

The full single letter set, read off the IL comparisons (`0x000CDA2F` to `0x000CDAAC`), is exactly
`33 '!'`, `60 '<'`, `62 '>'`, `94 '^'`, `98 'b'`, `99 'c'`, `105 'i'`, `110 'n'`, `114 'r'`, `117 'u'`, `119 'w'`, `122 'z'`.
There are no others.

### 3.2 Code table

| code | argument | argument is | uses in this build | notes |
|---|---|---|---|---|
| `\\` | none | n/a | 0 | Renders one literal `\`. Costs one character of typewriter time. VERIFIED: IL `0x000CD821` sets flag false and branches to the plain text append at `IL_06B4`. |
| `\n` | none | n/a | 403 total, all in `Event.templateInfo` (editor help) and 32 in layout item lists | Hard line break. Increments `currentSett.line`. Not used inside any script message in this game, which uses real CRLF instead (106,302 CRLF pairs in `Script.commands[].attrList[].value`). |
| `\b` | none | n/a | 0 | Toggles `MessageParts.bold`. Stateful, not a wrapper. |
| `\i` | none | n/a | 0 in messages (18 layout hits are `\innpriceG`, a GameContentParser keyword) | Toggles `MessageParts.italic`. |
| `\u` | none | n/a | 0 | Toggles `MessageParts.underline`. Drawn as a 2 px filled rect in `drawStringWithCommands`. |
| `\!` | none | n/a | 0 | Wait for the DECIDE key mid message. Sets `MessageParts.wait = true`, adds 60 frames. |
| `\^` | none | n/a | 0 | Sets `noWait` on the part, which makes `MessageReader.Update` dequeue without waiting for input at the end. |
| `\<` | none | n/a | 0 | Restore default message speed (`currentSett.speed = defaultSpeed`). |
| `\>` | none | n/a | 0 | Instant reveal from here on (`currentSett.speed = 0f`). |
| `\c[RRGGBB]` | yes | **KEY** - 6 hex digits | 0 | `byte.TryParse(arg.Substring(0,2)/(2,2)/(4,2), NumberStyles.HexNumber)`. If the argument is missing **or shorter than 6 characters**, the colour resets to the default and `useChangedColor = false`. So `\c[]` and bare `\c` are the "reset colour" form. |
| `\w[seconds]` | yes | **KEY** - float, invariant culture | 0 | `endTime += (int)(value * 60f)`. Bare `\w` with no bracket adds a fixed 15 frames. |
| `\z[percent]` | yes | **KEY** - integer percent | **23** (`\z[200]`) | `int.TryParse` into `MessageParts.size`. Bare `\z` resets size to 100. |
| `\r[ruby]` | yes, 1 arg | **DISPLAY TEXT** - the ruby gloss | **4** (`\r[・]`) | One argument form. The **next character after `]` is consumed as the base text** (`messageParts6.text = this.text[i].ToString()`). The base character stays in the string and must remain immediately after the closing bracket. |
| `\r[base,ruby]` | yes, 2 args | **BOTH DISPLAY TEXT** | 0 | Two argument form. `parts.text = array2[0]`, `parts.ruby = array2[1]`. Both are rendered and both must be translated. A comma inside either half breaks the code. |
| `\NP[name]` | yes | **DISPLAY TEXT** - nameplate label | 0 | Position defaults to `Left` (enum 0), because no `C`/`L`/`R` follows. |
| `\NPL[name]` | yes | **DISPLAY TEXT** - nameplate label | **71,519** - the dominant code in this game | Left nameplate. |
| `\NPC[name]` | yes | **DISPLAY TEXT** - nameplate label | 0 | Centre nameplate. |
| `\NPR[name]` | yes | **DISPLAY TEXT** - nameplate label | 0 | Right nameplate. |
| `\blink[n]` | yes, **required** | **KEY** - float | 0 | Recognised and consumed by the lexer, queued as a command part, but **no consumer exists** in this build. The dialogue waiter in `ScriptRunner` only handles `blspd`, `blrate` and `lipspd`. Parsed and dropped. |
| `\blspd[n]` | yes, **required** | **KEY** - float | 0 | `SpriteManager.SetBlinkInterval` / `FaceView.SetBlinkInterval`. |
| `\blrate[n]` | yes, **required** | **KEY** - float | 0 | `SetBlinkRate`. |
| `\lip[n]` | yes, **required** | **KEY** - float | 0 | Same as `\blink`: parsed, queued, no consumer. |
| `\lipspd[n]` | yes, **required** | **KEY** - float | 0 | `SetLipSpeed`. |
| `\X` (anything else) | none, but see 6.9 | n/a | 0 | Unknown escapes are **preserved literally**. IL `0x000CDDF9`: `ldstr "\\"` then `String::Concat(text, "\\", c.ToString())`, and `endTime += speed * 2f`. So `\q` displays as the two characters `\q`. Safe on its own, but `\q[...]` still loses the bracket, see 6.9. |

### 3.3 Nameplate positions

`Yukar.Engine.MessageReader+MessageEntry+MessageParts+NamePlatePositions`:

```csharp
public enum NamePlatePositions { Left, Center, Right, Amount }   // 0, 1, 2, 3
```

`Amount` is a count sentinel, not a position.

The literal recognition, verbatim from the decompilation:

```csharp
if (text == "NP")
{
    char c2 = ' ';
    if (this.text.Length > i) c2 = this.text[i + 1];
    if (c2 != 'C') {
        if (c2 != 'L') {
            if (c2 == 'R') { messageParts2.namePlatePosition = NamePlatePositions.Right;  num2 = i + 1; i = num2; }
        } else          { messageParts2.namePlatePosition = NamePlatePositions.Left;   num2 = i + 1; i = num2; }
    } else              { messageParts2.namePlatePosition = NamePlatePositions.Center; num2 = i + 1; i = num2; }
    string[] array = func();
    messageParts2.namePlateString = array[0];
    messageParts2.useNamePlate = messageParts2.namePlateString.Length > 0;
    this.currentSett.namePlateString = messageParts2.namePlateString;
}
```

So the exact literals are `\NP[`, `\NPL[`, `\NPC[`, `\NPR[`.
The suffix letters are **case sensitive uppercase only**. `\npl[...]` would match neither `"NP"` (the `commands` entry is `"NP"`) nor any single letter code, and would render as the literal text `\npl[...]`.

`useNamePlate` is false when the argument is empty, so `\NPL[]` hides the plate.
The stored string is consumed by `EventContentGetter` under `ContentType.NAMEPLATE` and returned raw to the renderer, so it is display text with no further processing.
`LayoutStateMessage`/`LayoutStateDialogue` then show exactly one of the three plate slots:

```csharp
for (int i = 0; i < 3; i++)
    if (messageParts.useNamePlate && i == (int)messageParts.namePlatePosition)
        base.LayoutDrawer.ShowRenderNamePlate(i, this.renderObjectIndex);
    else
        base.LayoutDrawer.HideRenderNamePlate(i, this.renderObjectIndex);
```

---

## 4. Codes that do NOT exist in this build

Searched by name across the complete decompilation of both assemblies and the raw string heaps. None found.

| looked for | result |
|---|---|
| `\savevar[..]` | **Not present.** Not in `MessageReader`, not in `replaceForFormat`, not among the 541 `GameContentParser.keyWords`, no `savevar` string in either DLL. |
| `\f[..]` (font select) | **Not present** as a message escape. `f` is not one of the twelve single letter codes. Fonts are selected per layout node via `TextDrawer`/`Font`, not inline. |
| `\R` | **Not present.** Uppercase `R` only has meaning as the third character of `\NPR`. A bare `\R` renders as the literal text `\R`. |
| `\+` / `\-` | **Not present.** Neither `43` nor `45` appears in the escape comparison chain. They render literally. |
| `\s` as a message escape | **Not a message code.** `\s[N]` exists but only in pass 1, as a string variable ordinal lookup. There is no `\s` in `separateByCommands`. |
| `\i` as an icon code | **No.** `i` is the italic toggle. |

A separate, unrelated escape dialect exists in `Yukar.Engine.InputStringLayoutWindow.LoadCharacter` for the *name entry keyboard layout resource*: `\\` literal, `\c` cancel key, `\d` delete key, `\e` end key, `\s` space key, `\t` character set toggle.
That string never reaches `MessageReader`. Mention it only so a pipeline does not mistake a keyboard layout asset for message text.

---

## 5. `ReadMessage`, word wrap and the line cap

```csharp
public int ReadMessage(string messageString, TextDrawer textDrawer, int width, float textScale, int maxLineNum, Guid sender)
{
    string text = this.gameMain.replaceForFormat(messageString, sender);
    MessageReader.MessageEntry messageEntry = this.wordWrap(text, this.gameMain, textDrawer, width, textScale);
    messageEntry.id = this.messageCount;
    this.messageEntries = messageEntry.splitByLines(maxLineNum);
    this.messageCount += this.messageEntries.Length;
    foreach (MessageReader.MessageEntry messageEntry2 in this.messageEntries)
        this.messageQueue.Enqueue(messageEntry2);
    ...
    return this.messageCount - 1;
}
```

**Does it word wrap with real font measurement?** Yes. **VERIFIED.**
`MessageEntry.wordWrap` calls `measureStringSingleLine`, which calls `textDrawer.MeasureString(text)`, which resolves to

```csharp
public Vector2 MeasureString(Font font, string text)
{
    if (string.IsNullOrEmpty(text)) return Vector2.Zero;
    SharpKmyMath.Vector2 vector = font.measureString(Encoding.UTF8.GetBytes(text));
    return new Vector2(vector.x, vector.y);
}
```

That is a native glyph metrics call into `SharpKmyGfx`, not a character count. Per part `size` scaling is applied on top.

**Which parameter carries the box width?** `int width`, in pixels, taken at the call site from the layout text node:

```csharp
// LayoutStateMessage.PushMessage, line 183
int num = (int)textDrawerObject.MenuItem.size.X;
float item = textDrawerObject.GetTextScale().Item2;
base.SelectProperty.MessageID = this.messageReader.ReadMessage(
    base.SelectProperty.MessageString, textDrawer, num, item,
    base.LayoutDrawer.maxLineNum(), base.SelectProperty.MessageSender);
```

`LayoutStateDialogue.cs:341` is identical.

**What caps the line count?** `maxLineNum`, from `LayoutDrawer.maxLineNum`:

```csharp
public Func<int> maxLineNum = () => 3;                       // LayoutDrawer.cs:2175  (default)
this.maxLineNum = () => menuSettings.maxLineNum;             // LayoutDrawer.cs:103
this.maxLineNum = () => layoutNode.MenuSettings.maxLineNum;  // LayoutDrawer.cs:136
```

**Clipped or paginated?** **Paginated. VERIFIED.**
`MessageEntry.splitByLines(int lineCount)` walks the parts, does `messageParts2.line %= lineCount`, and every time the line index wraps back to 0 it closes the current `MessageEntry` and starts a new one that inherits the style state.
Each resulting entry is enqueued separately, so overflow becomes an extra page that requires another key press. Nothing is discarded.

Note the corollary: an English translation that is 40 percent longer than the Japanese does not get truncated, it silently grows extra message pages.
That changes pacing and can desynchronise anything the script does after the message.

**Wrap point selection.** `MessageEntry.wordWrap` and the static `MessageReader.SplitStringInnerWidth` both use:

```csharp
private bool isWord(char p)
{
    return (p >= 'a' && p <= 'z') || (p >= 'A' && p <= 'Z') || (p >= 'À' && p <= 'ߺ')
        || (p >= '0' && p <= '9')
        || p == ',' || p == '.' || p == '\'' || p == '"'
        || p == '(' || p == '<' || p == ')' || p == '>'
        || p == '[' || p == '{' || p == ']' || p == '}';
}
private bool isNotGoodForPrefix(char p) { return p == '、' || p == '。'; }
```

The `À`..`ߺ` range is U+00C0 to U+07FA, so Latin 1 accented letters, Greek, Cyrillic, Hebrew and Arabic count as word characters. CJK does not, which is why Japanese wraps anywhere and English wraps on spaces.
A single word wider than the box is force split by the `if (x > width) num2 = num;` fallback rather than overflowing.

Note that a space is **not** a word character, so a bracket argument containing a space, for example `\NPL[Sister Agatha]`, is a legal wrap point as far as the static `MessageReader.SplitStringInnerWidth` is concerned.
Message bodies never reach that routine, because `MessageEntry.wordWrap` operates on already lexed parts where the codes are gone. Its three live callers are:

- `SpecialTextRenderer.cs:650` on `renderContent.DrawText`, which is post `GameContentParser` substituted text.
- `TextRenderer.cs:73` on `this.text = base.MenuItem.text` (`TextRenderer.cs:172`), which is the **raw** layout item string. Layout item text in this game does contain `\$[...]` codes (111 occurrences), so a long layout label with a spaced variable name could in principle be wrapped mid code. Not observed in this build's data, flagged as a risk if layout labels are lengthened during translation.
- `ScriptRunner.cs:5949` inside `limitTextForTelop`, which is dead code, see below.

`ScriptRunner.limitTextForTelop` would apply `SplitStringInnerWidth` to a raw telop string and then splice `\n` into it at every wrap point, which would be destructive for coded text.
It is **dead code in this build** - defined at `ScriptRunner.cs:5946`, with no caller anywhere in either assembly.

---

## 6. Traps

### 6.1 Is there an RPG Maker style greedy `[A-Za-z]+` escape lexer? **No, with one bounded exception.**

The single letter path is a plain character comparison chain. It consumes exactly one character after the backslash and then only looks for `[` at the very next position. The IL is unambiguous:

```
IL_02B7: ldc.i4.s 99   // 'c'
IL_02BD: ldc.i4.s 62   // '>'
IL_02C3: ldc.i4.s 33   // '!'
IL_02CC: ldc.i4.s 60   // '<'
IL_02D5: ldc.i4.s 62   // '>'
IL_02E3: ldc.i4.s 94   // '^'
IL_02EC: ldc.i4.s 98   // 'b'
IL_02F2: ldc.i4.s 99   // 'c'
IL_0300: ldc.i4.s 114  // 'r'
IL_0306: ldc.i4.s 105  // 'i'
IL_030C: ldc.i4.s 110  // 'n'
IL_0315: ldc.i4.s 114  // 'r'
IL_0323: ldc.i4.s 117  // 'u'
IL_0329: ldc.i4.s 119  // 'w'
IL_0332: ldc.i4.s 122  // 'z'
```

So `\cRed velvet` does **not** swallow `Red`. It resets the colour to default (empty argument, `array2.Length == 0`) and then emits `Red velvet` as ordinary text.
The RPG Maker `\GWhat` failure mode does not exist here for the single letter codes.

**The bounded exception is the six entry `commands` prefix match**, and it is a real hazard:

```csharp
string substr = this.text.Substring(i);
string text = MessageReader.MessageEntry.commands.FirstOrDefault<string>((string x) => substr.StartsWith(x));
```

```
IL_0007: callvirt instance bool [mscorlib]System.String::StartsWith(string)
```

This is a bare prefix test with no requirement that a `[` follow, and it runs **before** the single letter switch.
The practical collision is `\b` followed by a word starting with `link`:

- `\blinked`, `\blinks`, `\blinking` all match the command `"blink"`, not the bold toggle.
- Then, because the next character is `e`/`s`/`i` rather than `[`, `func()` returns `new string[0]`, and the very next instruction is an unguarded element load:

```
IL_0258: ldc.i4.0
IL_0259: ldelem.ref          // func()[0]  on a zero length array
IL_025A: ldc.i4    511       // NumberStyles.Any
IL_025F: call      CultureInfo::get_InvariantCulture()
IL_026B: call      bool Single::TryParse(string, NumberStyles, IFormatProvider, float32&)
```

The `NP` branch has the identical unguarded load at `IL_0221`.
So `\blinks` does not merely misrender, it throws `IndexOutOfRangeException` inside message parsing. **VERIFIED at IL level. INFERRED** that this surfaces as a crash or a caught exception depending on the caller, since I did not run it.

The other five prefixes (`blspd`, `blrate`, `lipspd`, `lip`, `NP`) are not reachable from a legitimate control code plus English word, because `\l` and `\N` are not codes on their own, so nothing would put them there. Only `\b` is a live single letter code whose letter starts a command name.

Rule for the pipeline: **never allow `\b` to be immediately followed by `link`, `lspd` or `lrate`.**
The safe rewrite is to move the `\b` or insert a zero width space, or simply re-order so the bold toggle does not abut those letters.

Secondary note, **INFERRED**: `StartsWith(string)` is the culture sensitive overload, which under .NET Framework ignores zero weight characters. A soft hyphen or zero width joiner sitting between the backslash and `blink` would still match. Do not rely on invisible characters as a separator.

### 6.2 A stray backslash at end of line eats the first character of the next line

The CR and LF tests run **before** the escape flag is consulted, and neither clears the flag:

```
IL_0087: ldc.i4.s 13 ; beq IL_06E4   // CR: continue, flag untouched
IL_0090: ldc.i4.s 10 ; bne IL_00A0   // LF: newline action, then continue, flag untouched
```

So for the input `abc\` + CRLF + `next`, the trailing `\` sets the flag, CR is skipped, LF breaks the line with the flag still set, and `n` on the next line is then parsed as the `\n` newline code. The visible result is a doubled line break and a missing letter.
A lone trailing `\` at the very end of the whole string is silently dropped.
**VERIFIED** from the IL branch order.

### 6.3 Commas inside bracket arguments are destructive

`func()` always does `.Split(new char[] { ',' })`, and the consumers read fixed indices.

- `\NPL[Smith, Jr.]` gives `array[0] == "Smith"`. The rest is discarded. The nameplate reads `Smith`.
- `\r[base,ruby]` is the two argument form by design, so `\r[the Duke, of Arms]` becomes base `the Duke` with ruby ` of Arms`.
- `\c[FF0000,x]` still works, because only `array[0]` is read and it is 6 characters.

Japanese never triggers this because Japanese uses `、` and `，`, which are not U+002C. English translations of names and rubies routinely contain ASCII commas.
**This is the single most likely way an English string silently loses text in this engine.**

### 6.4 A `]` inside a bracket argument truncates it

`int num4 = this.text.IndexOf(']', i);` takes the first closing bracket. `\NPL[Guard [B]]` gives `Guard [B` and leaves a stray `]` in the body.

### 6.5 TAB characters become a visible backslash

See 2.1. Any TAB surviving into a message string is rewritten to `\\` by `replaceForFormat` and rendered as `\` by `separateByCommands`. Strip TABs at export and at import.

### 6.6 `\$[name]` immediately followed by `[` changes meaning

Regex 1 carries `(?!\[)`. If a translation writes `\$[HeroName][sic]`, regex 1 declines it, regex 2 accepts it as an array variable access with index `int.TryParse("sic") -> 0`, and the output is `GetStrFromArray("HeroName", 0)`.
Do not place a `[` immediately after a `\$[...]` code.

### 6.7 `\map`, `\time` and `\money` have no terminator

Regex 3 is `\\(map|time|money)` with no word boundary and no bracket. `\mapping` substitutes the map name and leaves `ping`.
Unused in this game, but if a translator introduces a literal `\map` prefix it will fire. Escape it as `\\map`.

### 6.8 Bare `\c` and short colour arguments silently reset colour

`if (array2.Length == 0 || array2[0].Length < 6)` resets to the default colour rather than erroring. A truncated hex value such as `\c[F00]` looks like a red tag but produces default white.

### 6.9 Any single letter code eats a following `[...]`, even codes that take no argument

The bracket reader runs before the code letter is inspected:

```
IL_02AD: ldloc.3
IL_02AE: callvirt instance !0 class [mscorlib]System.Func`1<string[]>::Invoke()   // func()
IL_02B3: stloc.s  V_13
IL_02B5: ldloc.s  V_4                                                            // c
IL_02B7: ldc.i4.s 99                                                             // first comparison
```

`func()` advances `i` to the closing `]` whenever the next character is `[`, regardless of which code follows.
The codes that never read `array2` are `!`, `<`, `>`, `^`, `b`, `i`, `n`, `u`, and the unknown code fallback.
For all of those, a following bracket group is **consumed and silently deleted**.

- `\b[whispering]` toggles bold and deletes `[whispering]` from the output.
- `\NPL[Alice]\b[aside] Hello` prints `Alice` on the plate then ` Hello`, with `[aside]` gone.
- `\n[1]` breaks the line and deletes `[1]`.
- `\q[hello]` prints `\q` and deletes `[hello]`.

Japanese rarely puts an ASCII `[` immediately after a style toggle. English stage directions, footnote markers and bracketed glosses do exactly that.
**VERIFIED at IL level.**

---

## 7. Masking recommendation

Apply in this exact order and mask each match as an opaque token before sending text to a translator.
Group 1 is the part a translator may edit. Everything else is opaque.

```python
PATTERNS = [
    # 1. literal backslash first, so it cannot be re-lexed
    (r'\\\\',                                   'OPAQUE'),

    # 2. multi letter commands, before the single letter switch
    (r'\\NP[LCR]?\[([^\]]*)\]',                 'TRANSLATE_ARG'),   # nameplate label
    (r'\\(?:blink|blspd|blrate|lipspd|lip)\[[^\]]*\]', 'OPAQUE'),

    # 3. pass 1 variable codes (KEY arguments, never translate)
    (r'\\\$\[[^\[\]]*\]\[[^\]]*\]',             'OPAQUE'),          # array form first
    (r'\\(?:\$L|\$|\#|Variable|v|s|h|H)\[[^\[\]]*\]', 'OPAQUE'),
    (r'\\(?:map|time|money)',                   'OPAQUE'),

    # 4. ruby - BOTH halves are display text
    (r'\\r\[([^,\]]*),([^\]]*)\]',              'TRANSLATE_BOTH'),
    (r'\\r\[([^\]]*)\](.)',                     'TRANSLATE_ARG_AND_KEEP_BASE_CHAR'),

    # 5. single letter codes with KEY arguments
    (r'\\[cwz]\[[^\]]*\]',                      'OPAQUE'),

    # 6. bare single letter codes
    (r'\\[nbiu!^<>]',                           'OPAQUE'),
    (r'\\[cwz](?!\[)',                          'OPAQUE'),          # reset forms
]
```

Do **not** widen rule 6 to `\\[nbiu!^<>](\[[^\]]*\])?`. The engine does swallow that bracket (6.9), but masking it as opaque would hide a silent text loss instead of surfacing it. Treat it as a validation error.

Validation rules to enforce on the translated side:

1. Reject any `\b` immediately followed by `link`, `lspd` or `lrate`. (6.1)
2. Reject any `,` inside a `\NP*[...]` argument, and inside either half of a `\r[...]`. (6.3)
3. Reject any `]` inside a bracket argument. (6.4)
4. Reject any TAB anywhere in the string. (6.5)
5. Reject a `\` that is the last character of the string or immediately followed by CR or LF. (6.2)
6. Reject a `[` immediately following a `\$[...]` code. (6.6)
7. Reject `\c[...]` whose argument is not exactly 6 hex digits, unless it is deliberately empty. (6.8)
8. Reject a `[` immediately following any of `\n \b \i \u \! \^ \< \>` or an unrecognised escape, because the bracket group is deleted. (6.9)
9. Warn when the translated line count would exceed `maxLineNum` (3 by default here), because it silently adds a page. (Section 5)

---

## 8. What this game actually uses

Counts over the 123,385 non path text rows of `census.tsv`, split into script/event message text and layout text.

| code | script/event | layout |
|---|---|---|
| `\NPL[...]` | **71,519** | 0 |
| `\z[...]` | **23** | 0 |
| `\$[...]` | 7 | 111 (plus 25 in `NSkill` damage formulas) |
| `\r[...]` | **4** | 0 |
| `\#[...]` | **2** | 0 |
| `\n` | 0 | 32 (menu option lists) |
| everything else in section 3.2 | 0 | 0 |

Newlines in message bodies are real CRLF, not `\n`. 106,302 CRLF pairs in `Script.commands[].attrList[].value`.

The 19 `\c` and 18 `\i` hits in layout rows are `GameContentParser` keywords (`\currentitemnum`, `\innpriceG` and friends), not the colour or italic message codes.

Real examples pulled from the ROM:

```
\NPL[アルテシア]ふーっ♡　ふー……っ♡<CRLF>だ、ダメ……っ♡　判断、力がぁ……んぁっ♡
\NPL[アルテシア]（見たところ痴話喧嘩……\r[・]カ\r[・]モね！<CRLF>　この私を侮辱したことを後悔させてあげる……！）
\NPL[アナウンス]\z[200]<CRLF>　　　スタート！！！！
\NPL[アルテシア]…………\$[おっぱい回数]回ぐらい<CRLF>
X : \#[プレイヤーの位置座標X]
```

Practical consequence for this project: the masking surface is small.
`\NPL[...]` with a **translatable** argument dominates, `\z`, `\r`, `\$` and `\#` are rare, and everything else is theoretical.
The `\r[・]カ` pattern above is the emphasis dot idiom, one ruby dot per base character. In English it has no natural equivalent and should probably become italics (`\i`) or be dropped, since `\r`'s one argument form binds to exactly one following character.
