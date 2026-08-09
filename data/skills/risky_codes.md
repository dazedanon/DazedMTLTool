You are an expert RPGMaker MV/MZ event system analyst.

<task>
Audit several optional event code types and report: (a) which contain player-visible Japanese text that needs translation, and (b) for code 122, exactly which variable ID ranges carry display text versus internal keys.
</task>

--- attach Actors.json, CommonEvents.json, Troops.json, Map*.json, and js/plugins.js here ---

<actor_context>
Read Actors.json in full before auditing event commands. Use it to resolve actor IDs, \N[n] references, and code 320/324/325 targets. If you see an event reference to a major actor whose full character glossary entry is missing or only appears as a placeholder mapping like \N[3] (Keimi), report that Actors.json should be included in the glossary build and that a full # Game Characters entry is needed.
</actor_context>

<audit_1 code="122">
Code 122 — Control Variables — which variable IDs carry display text

A code 122 entry looks like:
  { "code": 122, "parameters": [startVarId, endVarId, 0, 4, "\"some string\""] }
parameters[0] is the variable ID being set; parameters[4] is the string value
(only present when parameters[3] == 4, direct string assignment).

Collect every code 122 where parameters[3] == 4. For each variable ID found:
  1. Is the string also tested in a code 111 $gameVariables comparison?
     → DO NOT TRANSLATE (would break game logic)
  2. Is the string used as an internal ID / plugin key / script argument?
     → DO NOT TRANSLATE
  3. Is the string purely player-visible display text?
     → SAFE TO TRANSLATE

Summarise translatable variable IDs as compact numeric ranges,
e.g. 'Translate IDs: 5, 10-18, 42'. Separately list any DO NOT TRANSLATE IDs
with the reason. This compact string will be pasted directly into the translation tool.
</audit_1>

<audit_2>
Plugin codes with visible text — 357 / 356 / 355-655 / 657 / 320 / 324 / 325 / 108
For each code type below, scan all events and report whether any instance contains Japanese text visible to the player at runtime.

--- Code 357 (MZ Plugin Commands) ---
parameters[0] = plugin header; parameters[3] = data dict.
Look up each unique header in js/plugins.js.
Does any key in parameters[3] hold Japanese text shown on screen?
The module already handles: AdvExtentionllk, VisuMZ_4_ProximityMessages, LL_GalgeChoiceWindow
For other headers with visible text, check the commented-out headerMappings list:
  "LL_InfoPopupWIndow": (["messageText"], None),
  "QuestSystem": (["DetailNote"], None),
  "BalloonInBattle": (["text"], None),
  "MNKR_CommonPopupCoreMZ": (["text"], None),
  "DestinationWindow": (["destination"], None),
  "_TMLogWindowMZ": (["text"], None),
  "TorigoyaMZ_NotifyMessage": (["message"], None),
  "SoR_GabWindow": (["arg1"], None),
  "DarkPlasma_CharacterText": (["text"], None),
  "DTextPicture": (["text"], None),
  "TextPicture": (["text"], None),
  "TRP_SkitMZ": (["name"], None),
  "LogWindow": (["text"], None),
  "BattleLogOutput": (["message"], None),
  "TorigoyaMZ_NotifyMessage_CommandMessage": (["message"], None),
  "NUUN_SaveScreen": (["AnyName"], None),
  "build/ARPG_Core": (["Text", "SkillByName"], None),
Output: EXACT uncomment line, or describe parameters[3] if header is new.

--- Code 356 (MV Plugin Commands) ---
parameters[0] is a space-delimited string, e.g. 'D_TEXT テキスト 24'.
The module already handles: D_TEXT, ShowInfo, PushGab, addLog, DW_*, CommonPopup, AddCustomChoice.
Does any 356 line have Japanese that is shown on screen?
If yes: ENABLE CODE356 and list the command keywords found.
If no:  SKIP CODE356.

--- Code 355/655 (Inline Scripts) ---
Code 355 starts a script block; code 655 continues it.
parameters[0] is the raw JS/script text.
For each block with Japanese in a string passed to a message/popup/log function:
  • The leading keyword/pattern that identifies the block
  • A regex capturing only the display substring, e.g. テキスト-(.+)
  • Whether it is single-line (355 only) or multi-line (355 + 655)
  • The exact entry to add to the patterns dict:
      "<keyword>": (r"<regex>", <True|False>),

--- Code 657 (Picture Text) ---
parameters[0] is a plain string drawn onto a picture.
Does any 657 entry contain Japanese text visible on screen (not a filename)?
If yes: ENABLE CODE657. If no: SKIP CODE657.

--- Codes 320 / 324 / 325 (Actor Name / Nickname / Profile) ---
parameters[1] is the new name/nickname/profile string.
Do any of these codes set Japanese strings visible to the player
(not just internal IDs or filenames)?
If yes: ENABLE the respective code. If no: SKIP.

--- Code 108 (Comment / Notetag) ---
parameters[0] is a comment string used as a plugin notetag.
The module only translates 108 lines that match specific patterns:
  info:, ActiveMessage:, event_text, Menu Name, text_indicator, NW名前指定
Do any 108 entries matching those patterns have Japanese visible to the player?
If yes: ENABLE CODE108 and list the patterns found. If no: SKIP CODE108.
</audit_2>

<output_format>
Reply with these exact sections:

### Code 122 — Variable Translation Ranges
  Translate IDs  : <compact ranges, e.g. 5, 10-18, 42>
  Do NOT translate: <ID — reason>
If none: 'No display-text string assignments found.'

### Code 357 — Plugin Handlers to Enable
  • Already handled  : <header> — no action needed
  • Enable in module : uncomment → "<header>": (["<key>"], None),
  • New entry needed : <header> — parameters[3] structure: <description>
  • No visible text  : <header> — internal only, skip
If none: 'No code 357 visible text found.'

### Code 356 — Enable or Skip
  ENABLE / SKIP — keywords found: <list>

### Code 355/655 — Script Patterns to Add
  • Pattern key : <keyword>
  • Regex       : <capture regex>
  • Multiline   : <true/false>
  • Module line : "<keyword>": (r"<regex>", <True|False>),
If none: 'No translatable 355/655 scripts found.'

### Code 657 — Enable or Skip
  ENABLE / SKIP — <brief reason>

### Codes 320 / 324 / 325 — Enable or Skip
  320: ENABLE / SKIP   324: ENABLE / SKIP   325: ENABLE / SKIP

### Code 108 — Enable or Skip
  ENABLE / SKIP — patterns found: <list>

### GUI Action Summary

After all audit sections above, output this final block to configure the GUI:

ENABLE CODES     : <comma-separated CODE* keys to check, e.g. CODE357, CODE356>
SKIP CODES       : <codes that have no visible text>
357 PLUGINS      : <comma-separated HEADER_MAPPINGS_357 keys to enable>
355/655 PATTERNS : <comma-separated PATTERNS_355655 keys to enable>
122 VARIABLE IDS : <compact ranges, e.g. 5, 10-18, 42>

If a field has nothing to fill in, write NONE.
</output_format>
