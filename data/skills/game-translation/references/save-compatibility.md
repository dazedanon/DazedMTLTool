# Saves must survive your patch updates

A translation patch ships more than once. Version 1.1 fixes the labels that
clipped, 1.2 rewraps the lines that orphaned, 1.3 corrects a name. If each
release destroys the saves of everyone already playing, the patch is worse than
useless - and this breaks **silently**, months after you stop testing, in a way
no validator, selftest or byte-identity proof will ever show you.

Ask one question before the first public release: **what does a save record
about where the player is, and does my patch change it?**

---

Related: `text-fitting.md`, because a layout pass that adds or drops a line break is
the usual thing that moves the index described below, and `version-updates.md`, which
faces the same identity problem across game versions rather than across patches.

**Working implementations to copy from**, all under `tools/Game Translation/Reference Pipelines/`:

| Engine | What exists | Where |
|---|---|---|
| TyranoScript | `patch_src/save_compat.js` (the migration shim: stamps new saves with `(line, ordinal, kind)` and re-derives the resume index on load, wired in by one line added to `index.html`) and `scripts/test_remap.js` (the proof: parses every scenario before and after, remaps all 24k elements, reports exact / same-line / wrong-line) | `TyranoScript (AjinSyoujyo)\` |
| RPG Maker MV/MZ | `translate_save.py` - the string-rewriting kind: MV LZString and MZ zlib codecs, safe-section allowlist, round-trip assert | `RPG Maker MVMZ (BroodGeneral)\` |
| Wolf RPG | `wolf save-update save.sav --game DataEN/BasicData/Game.dat` - standard and GamePro Pro formats | WolfDawn `wolf` CLI (not bundled, see `tools/THIRD-PARTY.md`) |

Those are two different problems sharing one file. TyranoScript's is the **index**
problem (the save points at a position your edits moved). RPG Maker's and Wolf's is
the **stale data** problem (the save carries a copy of strings the build has since
translated). A patch usually has both.

## Read flags can depend on source text even when command indices survive

Treat resume position, cached display text and read-history identity as three
separate checks. Tropical Chase preserved 928 event lists / 21,383 command
positions, yet `SkipAlreadyReadMessage` also keyed read flags from dialogue.
The shipped plugin supports `$gameMessage.SkipAlreadyReadMessage.org_text`;
the translation hook supplies the pristine 401 body at its verified metadata
coordinate before the existing `command101` handler runs, only while the
message is not busy. This preserved old flags without rewriting them. Inspect
the installed plugin's metadata conventions; its map/common-event/troop IDs
are not generic engine IDs. Do not invent a broad save-string replacement.

Cached actor names and display variables used exact `(ID, old value, English)`
rules on `extractSaveContents`, retaining custom names and gameplay state.
Cached interpreter lists remained intact; an already-running event may still
show Japanese until it ends. Record that limit honestly.

Create compatibility fixtures through the **real save UI**, then load them
through the real load scene. Direct `DataManager.saveGame()` omitted
`$gameSystem.onBeforeSave()` in one harness and left BGM state null; its later
load error was a malformed fixture, not a patch defect. Similarly, replacing
game objects while the previous `Scene_Map` still updates can leave event data
out of sync. Leave that scene before a deliberate direct-load fixture. Require
the engine error panel to be empty and frames to advance, not just an IPC reply.
See [MZ native QA](rpgmaker-mz-native-qa.md) for the worked hook and test scope.

## The failure

Most VN and RPG engines do not save "chapter 3, line 40". They save an
**index** - an offset into a parsed array, a command pointer, an event page
number - because that is what the interpreter was holding.

TyranoScript is the clean example. A save carries
`data.current_order_index`, an integer index into the parsed element array of
the current scenario, and the load path resumes with:

```js
this.kag.ftag.nextOrderWithIndex(data.current_order_index,
                                 data.stat.current_scenario, !0, insert, "yes")
```

The parser splits each `.ks` line into elements - one per tag, one per run of
text between tags. So `Hello[r]world[p]` is four elements on one line. **Every
tag your layout pass drops or inserts shifts every index after it.** On the
reference game the rewrap pass alone (22 dropped `[r]`, 44 inserted breaks, 4
removed `[ruby]`) moved 22 of 45 scenarios, and a save taken past the first
edit in an edited file resumed at the wrong element:

```
no remap (what ships today)   exact 63.2%
```

**A third of saves land in the wrong place.** Not corrupted, not crashing -
resuming mid-sentence, replaying a transition, or skipping a `[p]`. The kind of
bug that gets reported as "the patch broke my game" with no reproduction.

---

## The fix: find the coordinate that survives your edits

You cannot make the index stable. You can record the position in terms of
something your patch does not move, and re-derive the index on load.

For a pipeline whose injection is a **span splice** - every translated string
replaces its source in place, every edit stays inside one line - the surviving
coordinate is the **source line number**. That is a property worth protecting
for exactly this reason: it is what makes save migration possible at all.

| Engine | What the save stores | What survives a text patch |
|---|---|---|
| TyranoScript | index into the parsed element array | the source line |
| RPG Maker MV/MZ | map id + event id + page + command index | map/event/page ids |
| Wolf RPG | common-event id + command index | the event id |
| Unity/Utage | scenario label + row | the label |
| KiriKiri | scenario file + label + offset | the label |

Read the load path before assuming which column applies to you. The rule of
thumb: **labels and ids are stable, offsets and indices are not.**

---

## Two tiers, because you cannot stamp a save that already exists

The complete fix is to write a better coordinate into the save. But every save
made before your fix shipped - including every save made by the *unpatched*
game - does not have it. Both paths must work:

**Stamped saves.** Wrap the save routine to record what you actually need. For
TyranoScript that is the line, the element's **ordinal within that line**, and
its kind:

```js
proto.menu.snapSave = function (title, call_back, flag_thumb) {
  var mark = describe(this.kag.ftag);      // {line, ordinal, name}
  var stamp = function () {
    if (self.snap && mark) self.snap.__compat = mark;
    if (typeof call_back === 'function') call_back();
  };
  return snapSave.call(this, title, stamp, flag_thumb);
};
```

The ordinal is what makes it exact rather than approximate - a line whose
element count changed still identifies its third element as the third.

**Legacy saves.** Fall back to whatever the engine already stored. TyranoScript
happens to keep `stat.current_line` alongside the index, so the fallback is
"the element on that line nearest the stored index".

Measured over all 45 scenarios and 24,019 elements of the reference game:

```
no remap (what ships today)    exact 63.2%
legacy save (line only)        exact 85.4%   same line 14.6%   wrong line 0.0%
stamped save (line + ordinal)  exact 99.2%   same line  0.8%   wrong line 0.0%
```

The remaining 0.8% are the lines the layout pass **actually edited** - a
dropped `[r]`, a removed `[ruby]` - where the saved element genuinely no longer
exists. Those land on a neighbouring element of the same line, costing at most
a repeated or skipped display tag. Nothing lands on the wrong line.

**Design for the degradation, not just the happy path.** Never having the right
line is the failure that matters. Being one element off inside the right line is
a cosmetic hiccup. Ranking those two correctly is what makes the fallback tier
worth shipping at all.

---

## The save carries the build's data, not only its position

Fixing the resume index is the obvious half. The save also holds a **copy of
whatever the build put into memory**, and that copy is as stale as the index was.

Two distinct kinds of staleness, and both bite.

### Data tables initialised at new-game and then carried forever

This game fills `f.item`, `f.task` and `f.nemo_task` from `exp.ks` when a game is
*started*, and the save stores the whole of `f`. Translate an item name after
that and every existing save keeps the old string - which is why a finished task
still read 完了したタスク in a save begun before that string was translated. The
scripts were patched correctly. The save simply was not reading them any more.

Nothing in the pipeline can see this. The shipped tree greps clean, the
validator passes, the screen is still Japanese.

**Ship the build's copy of that text and write it back on load.** Generate it
from the same tree you inject, so it can never drift:

```python
OWNED: dict[str, tuple[int, ...]] = {
    "task": (0, 1, 7),        # name, completed-text, briefing
    "nemo_task": (1, 7),      # field 0 is the jump target - see below
    "item": (1,),             # [3] is how many the player holds: state, not text
}
```

Then, on load, three guards decide whether a field may be replaced:

- the table must still have **the same number of rows** as the build's.
- the value being replaced must **already be a string** (never overwrite a
  count with a caption).
- a row the build has nothing for is **left alone**.

**Only ship fields that are purely display text.** A `nemo_task` name is also
its own jump target - `*ネモタスク1` is a real label - so replacing it in an old
save sends that save to a label its own build never had. This is the
"never translate keys" rule arriving somewhere new: the *migration* has to
respect it too, and the field list is the place to enforce it.

Payoff beyond the one bug: every later translation fix to those tables now
reaches existing saves automatically instead of requiring a new game.

### Engine state that is itself a table of indices

`snapSave` clones the whole of `kag.stat`, which includes `map_macro` - and a
macro is registered as `{storage, index}`, an **element index** into the file
that defined it. So the same content patch that moves the resume point also
sends every macro defined below an edit to the wrong tags. Splitting one
`[ptext]` into three inside `macro.ks` moved **668 of 713 macros**. Loading an
older save then has buttons half-building a screen out of the previous macro's
tail.

Here the fix is easier than for the resume point, because the engine parses
`macro.ks` at boot and its live table is already correct. Prefer the live table
over the saved one.

**The general check: grep the save for every field that is an index, an offset,
or a pointer into content, and ask what makes each one still valid.** The resume
position is the one everybody thinks of. It is rarely the only one.

### A plugin that CACHES a value onto a game object at init

The nastiest member of this family, because the source data is patched, the
patched data is correct, and the save still shows Japanese forever.

`EventLabel` sets SIX fields once, in `Game_Event.prototype.initialize`:

```js
this._labelText   = this.findLabelName();            // <LB:...> note tag
this._labelSize   = param.fontSize || 16;            // a PLUGIN PARAMETER
this._labelX      = findMetaValue(ev, 'LB_X') || 0;  // <LB_X:...>
this._labelY      = findMetaValue(ev, 'LB_Y') || 0;
this._labelSwitch = findMetaValue(ev, 'LB_S') || null;
this._labelTail   = findMetaValue(ev, 'LB_T');
```

**Refresh EVERY field the init sets, not the one you were chasing.** Fixing
only `_labelText` looked like a complete fix and was not: a later change to the
plugin's `fontSize` parameter and a new `<LB_X:>` offset were *also* frozen in
the save, so captions kept rendering at the old size and the ones nudged away
from a map edge stayed clipped - while `data/` and `plugins.js` were both
correct and every file-level check passed. A player found it after the "fixed"
build shipped. Enumerate the whole init block and re-derive all of it.

**Note what that implies for a plugin PARAMETER.** `_labelSize` comes from
`plugins.js`, not from the map - so editing a plugin parameter, which feels
like a pure config change with no save implications, silently does not reach
any existing save either.

`Game_Map` - including its `_events` array, and each Game_Event's fields - is
serialised into the save. On load those objects come back with the label the
JAPANESE build gave them, and `initialize()` never runs again. Nine on one real
save, plus one in `_tileEvents`. **No amount of re-translating `data/` reaches
it**, and nothing in the pipeline can detect it, because the pipeline only ever
looks at files.

Find them by decoding a real save and walking it for source-language strings,
grouped by their path:

```
9  .map._events[]._labelText          <- the bug
4  .map._interpreter._list[].parameters[]
1  .map._prevDisplayName
1  .actors._data[]._characterName     <- a FILENAME, leave it
```

That inventory also tells you what NOT to touch. A `_characterName` is a sprite
sheet filename; rewriting it stops the sprite loading.

**Fix it by re-deriving on load, not by editing saves.** A save fixer only helps
the saves you are handed; a few lines in a patch plugin repair every save
forever, including ones made before the patch existed:

```js
const _Scene_Map_onMapLoaded = Scene_Map.prototype.onMapLoaded;
Scene_Map.prototype.onMapLoaded = function() {
    _Scene_Map_onMapLoaded.apply(this, arguments);
    refreshEventLabels();     // re-read meta['LB'] for every event
};
```

`onMapLoaded` fires on a fresh transfer, on a load, and after a map update, so
one hook covers all three. Re-deriving is safe **only** because the note tag is
the source of truth and the tag NAME is untouched by the patch - re-deriving a
field that doubles as a key would send an old save to a target its own build
never had.

Two things to leave alone deliberately, and to say so in the plugin's help:

* `Game_Interpreter._list` - the cached command list of the event that was
  RUNNING at save time. It replays from the cache until that event ends. Editing
  a running interpreter's list risks moving the index it is pointing at, for a
  few lines that self-correct.
* Anything a cache is keyed on.

Prove the fix before shipping it: parse the real save, parse the patched data,
and print the stale value beside what the hook would re-derive, per event. That
is a five-line script and it is the difference between "should work" and
"verified against the file you were given".

### Read the save the way the engine does

The format is often older than it looks. These saves are URL-encoded JSON with
legacy `%uXXXX` escapes, so `decodeURIComponent` throws `URIError: URI malformed`
and the engine's own `unescape` is what works. Match the engine's reader rather
than the modern equivalent.

## Where provenance metadata may live

**Provenance metadata goes in a sibling key on the command, never inside `parameters`.**
RPG Maker's interpreter reads only `code`, `indent` and `parameters` and ignores
unknown sibling keys, so an `_original` key at the top level of the command dict
is safe to carry in the shipped JSON. Appending an element to `parameters`, or
turning that list into a dict, crashes or silently drops the command at runtime.
Worse for this file's purposes: **any change in command count moves the command
index a save is holding.**

Assert per command after a run:

- same `code`, same `indent`
- `len(parameters)` unchanged
- `type(parameters)` unchanged (a list stays a list)
- `json.loads(json.dumps(doc)) == doc`, so no non-JSON value leaked in

Then run the entire extraction a **second** time and assert `rerun == translated`
with zero model calls and zero speaker lookups. That is the assertion that catches
a handler appending a duplicate prefix or shifting an index on the re-run, which is
the exact failure that silently invalidates every existing save.

The same discipline applies to database entries, where the metadata is a dict keyed
by field name, and to `System.json`, where array indices become string keys.

## Verify it against real before/after builds

Do not reason about this. Build the scenarios twice - once as they were, once as
they ship - reimplement the engine's own parser, and ask the remap function
where every element went.

The shipped runtime is usually a JS interpreter when asked, so the test runs the
real code with no dependency to install:

```bash
python tl.py inject --no-rewrap && cp -r translated before
python tl.py inject
ELECTRON_RUN_AS_NODE=1 ./game.exe scripts/test_remap.js before/data/scenario translated/data/scenario
```

This is not ceremony. The first version of the remap reported **134 elements
landing on the wrong line**, all in one file - because that build had a debug
menu that inserts a whole *line*, breaking the "every edit stays within a line"
assumption the design rests on. Rerunning against a release build gave zero.
**The invariant held for what ships and not for what was being tested with**,
which is precisely the thing you cannot find by reading the code.

---

## The harness must not carry its own copy of the code under test

The first version of the remap test opened with an honest comment:

```js
// --- copied verbatim from patch_src/save_compat.js --------------------------
function remap(array_tag, saved, mark) { ... }
```

It *was* verbatim, on the day it was written. Then the shipping implementation
gained a recovery branch and the copy did not, so the harness went on reporting
percentages for logic that no longer ran anywhere. It still passed. It was
measuring a fossil.

Have the test read the file that ships and pull the functions out of it:

```js
const COMPAT = fs.readFileSync(path.join(__dirname, '..', 'patch_src',
                                         'save_compat.js'), 'utf8');
function declaration(opener) {           // brace-match one function out
  const at = COMPAT.indexOf(opener);
  if (at < 0) throw new Error('save_compat.js no longer has: ' + opener);
  let depth = 0;
  for (let j = COMPAT.indexOf('{', at); j < COMPAT.length; j++) {
    if (COMPAT[j] === '{') depth++;
    else if (COMPAT[j] === '}' && --depth === 0) return COMPAT.slice(at, j + 1);
  }
  throw new Error('unbalanced braces in: ' + opener);
}
const [ordinalOf, remap] = new Function(
  [assignment('var DRIFT ='), declaration('function ordinalOf'),
   declaration('function remap'), 'return [ordinalOf, remap];'].join('\n'))();
```

The `throw` on a missing name matters as much as the extraction: rename the
function and the test fails loudly instead of silently testing nothing.

This applies to any shim you inject into a game - a BepInEx hook, a runtime
patch, a loader script. The code that ships is in one language and the harness is
often in another, and a copy is the obvious way to bridge that. It is also the
way a green test stops meaning anything.

## A fallback must be better than the input it replaces

The remap's "give up" branch read:

```js
if (!candidates.length) return saved;      // that line is gone
```

Returning `saved` looks conservative. It is the opposite: `saved` is the stale
index that is *known* to be wrong, which is the entire reason the function was
called. On a real save this resumed one element past `[s]`, landing on the label
after it, so the game played a scene the player was not in - the exact
"your patch broke my save" symptom, arrived at by the code path meant to prevent
it.

The design had assumed line numbers survive. They do survive *injection*, which
is a span splice - but not across builds, where a line can be added or removed
anywhere above. Once that happens the stamp names a line that no longer holds a
tag, and the recorded name and ordinal are the only identity left:

```js
if (mark.name === undefined) return saved;
for (var step = 0; step <= DRIFT; step++) {
  for (var side = 0; side < 2; side++) {
    var at = side ? want - step : want + step;
    if (at < 0 || at >= array_tag.length) continue;
    if (array_tag[at].name === mark.name &&
        (mark.ordinal === undefined || ordinalOf(array_tag, at) === mark.ordinal)) {
      return at - 1;
    }
  }
}
return saved;                              // nowhere near: give up
```

**Bound the search and say why.** `DRIFT = 16` because a patch moves things by
one or two. Anything further is a rewrite, and guessing across a rewrite resumes
in the wrong scene - worse than the honest failure. An unbounded scan would
always find *some* tag with the right name.

Whenever you write `return theStoredValue` in a recovery path, check whether the
stored value is the thing you were called to fix.

## Test against real save files, not only a synthetic corpus

The corpus comparison reported `wrong line 0.0%` and looked healthy. A real save
was broken at the same time.

Find where the engine actually writes saves - not where you assume. This one
keeps them beside the executable as URL-encoded JSON, despite the engine having
localStorage, a `userData` directory, and a compress path:

```
ajin_syoujyo_tyrano_data.sav        %7B%22kind%22%3A%22save%22%2C%22hash%22...
```

Decode them and read what each slot claims:

```
slot 0   base/base.ks  line 247  index 259  __compat {line:247, ordinal:1, name:'s'}
slot 2   base/base.ks  line 246  index 258  __compat None          <- predates the fix
slot 4   base/base.ks  line 246  index 258  __compat {line:246, ordinal:1, name:'s'}
```

Slot 0 is stamped and still wrong - its line moved between builds. **The
presence of the stamp was not the whole story, and only real files showed
that.** A three-line script that replays each real slot through the shipping
remap and asserts where it lands is worth more than the whole corpus run.

## When there is NO real save, build one - and it will still find a bug

The rule above stands: real files beat a corpus. But "no save exists on this
machine" is not a reason to ship a save translator that has never executed.
Build one to the shape the engine writes, from the engine's own source.

RPG Maker VX Ace, out of `DataManager`:

```ruby
Marshal.dump(make_save_header, file)     # document 1: the save-list row
Marshal.dump(make_save_contents, file)   # document 2: :system :timer :message
                                         #   :switches :variables :self_switches
                                         #   :actors :party :troop :map :player
```

Two facts that shape the tooling:

* **A save is TWO concatenated Marshal documents**, each with its own symbol
  and object-link tables. A single-document reader sees the second as trailing
  garbage.
* **`load_header` reads only the first document**, so the save-list draws its
  own copy of the map name before any load happens. No load-time hook can ever
  fix what the list shows - the header has to be rewritten too.

A synthetic save built from that shape found a real defect on its first run:
the baked map was being translated with an EMPTY glossary, so the save's name
plates stayed Japanese while the patched data file said Eris. That is a bug no
amount of reading the code had caught.

## VX Ace bakes more into a save than most engines

Worth knowing before promising "old saves keep working":

* **`Game_Actor` copies `@name` and `@nickname` out of the database at `setup`**
  and never re-reads them, so an existing save shows the Japanese name in every
  menu forever.
* **`Game_Map` stores `@map`, the WHOLE `RPG::Map`** for the map the player is
  standing on - every event, every page, every command - plus a `Game_Event`
  per event. So that map's entire script is inside the save, and the patched
  `Map###.rvdata2` is not consulted again until the player walks somewhere
  else.
* Those `Game_Event`s hold **the same `RPG::Event` instances** as
  `@map.events`, preserved through Marshal's link table. Editing the map's copy
  in place updates the running events too - but only if the translator EDITS
  the object rather than replacing it. Replace it and the stored copy looks
  right while the running event is still Japanese.

The remedy is cheap once the Marshal layer exists: apply the store's units to
the baked `@map` using the same pointers and the same text pipeline as `inject`,
rewrite the actor fields from the glossary, rewrite header strings, keep a
`.bak`. What it must NOT touch is anything that doubles as a key -
`$game_self_switches` keys are `[map_id, event_id, char]` arrays, and switch and
variable VALUES are state, not text.

## Point the comparison at the failure you are guarding against

Running the harness *original Japanese → current English* produced pages of
"stamped miss" rows that were nothing but the text being translated - the tags
match, their contents cannot, by construction.

The failure being guarded against is "the 1.1 patch breaks a save made on 1.0",
so the baseline is **the previous build against the next one**, not the source
game against anything. Point it at the deployed tree versus the freshly injected
one.

And make an empty corpus say so. When no element counts changed, the run printed
every metric as `-`:

```
scenarios compared         45 (0 shifted by the patch)
  stamped save (line+ordinal)  exact -  same line -  wrong line -
```

Nothing was measured, which is genuinely good news here - the patch is
index-safe by construction - but a row of dashes scans as "fine" exactly like a
pass does. Say *no elements moved. Nothing to compare* in words. This is also
why the unit checks matter: they are the part that still runs when the corpus is
empty, which is precisely when the corpus check tells you nothing.

## Hooking the engine safely

Three rules, all of which cost something when broken:

**Patch the prototype before the instance is cloned.** TyranoScript's `kag.init`
does `this.menu = object(tyrano.plugin.kag.menu)` at DOM ready, so a script
placed before `</body>` - after every engine script in `<head>` - patches the
prototype and every live instance inherits it. Deterministic, no polling, no
`setInterval` waiting for an object to appear.

**Find out who else calls the function you are hooking.**
`nextOrderWithIndex` is the save-load resume path *and* the way a macro returns
to its caller. Remapping the second case would break the game outright, since
the recorded line refers somewhere else entirely. The fix is a flag set by
`loadGameData` and consumed by the very next call:

```js
proto.menu.loadGameData = function (data) {
  this.kag.ftag.__resumeMark = mark;        // set
  return loadGameData.apply(this, arguments);
};
proto.ftag.nextOrderWithIndex = function (index, scenario_file) {
  var mark = this.__resumeMark;
  this.__resumeMark = null;                 // consumed - macro returns pass through
  if (!mark) return nextOrderWithIndex.apply(this, arguments);
  ...
```

**Fail open.** Every branch that cannot do better falls back to the stored
index, which is the behaviour without the patch. A save-migration shim may
degrade. It must never be the reason a load fails.

---

## Ship it in the build, not by hand

The migration is part of the patch, so it belongs in `deploy`, not in a
checklist. On a loose-file delivery it costs two ordinary override files - the
script, and the game's own `index.html` with one line added - and the existing
path interception does the rest:

```python
html = html.replace("</body>", SCRIPT_TAG + "\n</body>", 1)
```

Keep the check that the anchor exists (`raise SystemExit` if `</body>` is
missing) rather than silently producing a build with no migration in it.

---

## The cheapest possible proof: constrain the edits, then assert it

The migration shim above is what you need when your edits genuinely move the
coordinate. **The far cheaper option is to constrain the injector so nothing
moves, and then prove that** - no shim, no stamp, no fallback, and old saves keep
working by construction.

For RPG Maker that means: never change the number of commands in an event list.
The usual write-back tombstones the absorbed `401`s of a run and merges the text
into the anchor, which moves every later index. Redistributing the wrapped
English across exactly the commands the run already had costs nothing, because
the engine joins them with `\n` anyway - k wrapped lines across c commands render
`max(k, c)` rows.

Then assert it with a structural walk of source against injected output:

```
same set of files, each parsing
identical structure                 same keys, same array lengths
every event command list            the same LENGTH
every command                       same `code`, same `indent`, same order
every NON-string leaf               byte-identical (ids, switches, numbers, bools)
only STRING leaves differ
```

That is thirty lines, runs in seconds, and on the reference game reported
**9,144 command lists / 40,677 commands / 0 structural differences** with 4,558
string leaves changed. Name the first divergence per list rather than dumping the
list, and say what it means in the failure message - *"command 12 changed
(code, indent) (401,0) -> (101,0) - THIS MOVES EVERY SAVED INDEX AFTER IT"* -
because the number alone does not tell a reader what breaks.

**Gate the release build on it.** A patch that breaks saves is worse than no
patch, and nothing else in a release script would notice. The build aborts on a
failed verify rather than reporting it as a warning next to nine other lines.

This is the proof for *position*. It says nothing about the build's **data**
being baked into the save - actor names, message backlogs, tables the engine
fills in at new-game - which is a separate problem with a separate fix above.

## Checklist

- [ ] Read the engine's **load** path and write down what the save stores.
- [ ] Decide which coordinate survives your edits. If none does, constrain your
      edits until one does.
- [ ] Wrap the save routine to stamp the durable coordinate.
- [ ] Write the fallback for saves that predate the stamp - including saves from
      the unpatched game.
- [ ] Prove it: parse before and after, remap every element, require **0 wrong
      line**. Run it against a **release** build, comparing the **previous patch
      to the next one** - not the source game to anything.
- [ ] Have the harness read the shipping implementation rather than a copy of it,
      and throw if the names it extracts are gone.
- [ ] Replay **real save files off a real install** through it. The corpus run
      read 0.0% wrong line while an actual save was broken.
- [ ] Keep unit checks beside the corpus check - they are what still runs on the
      release where no element moved.
- [ ] Audit every `return storedValue` in a recovery path: the stored value is
      usually the thing you were called to fix.
- [ ] Inventory **every other index the save holds** (macro tables, event
      pointers, quest cursors), not just the resume point.
- [ ] Ship the build's copy of any **data table** the engine fills in at
      new-game, and write back only fields that are pure display text.
- [ ] Wire it into `deploy` so it cannot be forgotten.
- [ ] Fail open everywhere.
