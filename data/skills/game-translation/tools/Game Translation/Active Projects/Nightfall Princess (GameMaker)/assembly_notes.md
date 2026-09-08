# Runtime assembly contracts

These are small lexical/formatting examples for preparation, not a translated
catalog or applied game patch. `catalog.prepared.json` retains all source strings,
null translations, original IDs and per-occurrence token maps.

## Quest reward

`obj_hall_Alarm_0` assembles a prefix, the gold amount, then a suffix.
A compatible English shape is `Quest complete! Received ` + amount + ` G.`.
Both fragments stay nonempty, the prefix owns the space before the number, and
the suffix owns the space before the existing currency symbol. Test 1 and a
large multi-digit amount after translation. Output only the requested fragment,
never the stand-in amount or the complete sentence for both IDs.

## Enemy modifiers

`obj_hall_Step_0:111` inserts `abs(tmp_st)` for an HP increase; line 115 inserts
the already negative `tmp_st` for a decrease. Text fragments can use:

- Positive HP branch: `Enemy HP: +` + positive number + `%`.
- Negative HP branch: `Enemy HP: ` + signed negative number + `%`.
- Speed increase branch at line 121: `Enemy speed: +` + number + `%`.

The positive and negative HP prefixes share their Japanese source but have
different instruction-site IDs and different required English. Keep them separate.
Do not produce “decreases by -5%,” remove the runtime minus, or silently alter
the game's arithmetic. All six target fragments can remain nonempty. The game's
existing newline follows the suffix. `technical_overrides.json` separately plans
the enemy-name list's `、` separator as `, `.

## Equipment placeholders

There are 77 equipment templates and 80 skill templates containing `#`, for
157 strings and 158 marker occurrences. Equipment 28 repeats the same substituted
value in two positions; preserve both sentinel occurrences. Other text values
are left unmasked except for actual runtime markers and line breaks.

Equipment 46 (`世界樹の葉`) is special: its `#` is a target noun phrase. The full
source template and all three insert strings form `equipment:46:target`.
Rank 1 affects the nearest enemy in front; rank 2 affects the nearest enemy on
each side; rank 3 affects all enemies. The template owns spaces on both sides
of the sentinel. Put the same assembly context in the template and phrase batches;
their field instructions remain distinct. Check each restored full sentence.

## Merchant and scene tracks

Supply all four merchant source records as ordered context, with the last one
explicitly marked held/undisplayed. The first three are requested outputs; the
fourth is not. The third source record ends in a comma although the fourth does
not display. Give the visible third line a natural stopping point without adding
the fourth line's information. Do not “fix” the dialogue event during preparation.

Scene captions are independent alternatives. Each prepared unit records its
focus character, scene ID, base/climax phase, known alias IDs and paired phase
ID when present. Paired/alias context is useful; adjacent table rows are not a
conversation. Never deduplicate or concatenate independent narrated scenes.

