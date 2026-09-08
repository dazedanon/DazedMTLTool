# Forum Post — building the release thread

The last deliverable of a translation is the thread people actually find. It is
built with **`tools/ForumPostGen/forum_post_generator.py`** — a
CustomTkinter GUI that renders an F95-style BBCode post from a flat field set, with
a live preview, a tag picker, per-game profiles and a crash-safe autosave.

```
Run.bat                          # or: .venv\Scripts\python.exe forum_post_generator.py
profiles\_autosave_session.json  # written on EVERY change, restored on launch
profiles\<Game Title>.json       # per-game profiles (Save / Save As)
tags.json                        # the tag vocabulary the picker offers
```

Deps are `customtkinter` + `pillow`; the repo ships a `.venv` that has them. The
system Python does not — `import forum_post_generator` from a bare interpreter dies
on `customtkinter`.

## The fastest path: fill the autosave, then open the GUI

You almost always know more than the user wants to retype. Write
`profiles\_autosave_session.json` directly and the GUI restores it on launch, so
they open the tool to a nearly-finished post and only edit what needs judgement.

### Blank every field first — a new post starts from empty, not from the last game

The autosave is a *live session*: whatever game was open last is still in it. The
tempting shortcut — load it and `.update()` the fields you know — leaks every field
you did not happen to set. The previous game's version, store links, download hosts,
translator notes and credits all survive, and those are precisely the fields nobody
re-reads before posting. A wrong download link on a release thread is worse than a
missing one.

Do it in this order:

```
1. back up the current autosave      profiles/<PreviousGame>_backup.json
2. blank EVERY key                   not just the ones you are about to fill
3. re-apply the tool's own defaults  os=Windows, language=English, censored=No,
                                     download_os_label=Win, ss_size=Thumbnail
4. apply the new game's values
5. sync genre from tags_selected, and validate the tags against tags.json
```

`ForumPostGen/new_post.py` does exactly this:

```python
from new_post import start
start({"title": "...", "developer": "...", ...},
      tags=[...], backup_as="PreviousGameName")
```

It raises on a field name the app does not read and on a tag missing from
`tags.json`, rather than writing a post that silently drops them. Keys it does not
recognise (a newer build added a field) are carried over **emptied**, so the key set
survives without the value.

Afterwards, `new_post.diff_against("profiles/<PreviousGame>_backup.json")` lists
every non-empty value the two posts share. Overlap is not automatically wrong —
`Windows` is `Windows`, `English` is `English` — but each hit is a field to justify
before posting. On a real changeover the only matches should be the tool defaults.

Doing this by hand instead? Then set **all** keys explicitly, including the ones you
want empty. "I set 37 of 37" is a property to verify, not to assume.

Verify before handing it over, using the tool's own renderer rather than eyeballing
the JSON:

```python
sys.path.insert(0, FORUMPOSTGEN)
import forum_post_generator as fpg
print(fpg.build_bbcode(json.load(open(AUTOSAVE, encoding="utf-8")))[:1500])
```

## Field reference

Scalars (all strings):

| Field | Notes |
|---|---|
| `title` | Game name. Also the profile filename and the thread title's first part. |
| `banner_src`, `banner_alt` | Cover image. The user handles these — see **Images**. |
| `thread_updated`, `release_date` | `YYYY-MM-DD`. Both default to today in the GUI. |
| `original_title` | The JP title, e.g. `コイン☆プッシー`. |
| `aliases` | Romaji / alternate spellings people will search for. |
| `developer`, `publisher`, `translator` | Names; links go in the matching `*_links` list. |
| `version` | Patch or game version. Also the thread title's `[...]`. |
| `os` | `Windows` unless you checked otherwise. |
| `censored` | One of `Yes` / `No` / `Yes (Mosaics)` / `Partial`. |
| `language`, `language_note` | Note renders as `Language: English (note)` and accepts BBCode. |
| `voice` | e.g. `Japanese`. Empty means the line is omitted, not "none". |
| `length` | Optional playtime. |
| `vndb_url`, `other_games_url` | Rendered as a bare `Link`. |
| `download_os_label` | The bold label on the download line. Default `Win`. |
| `ss_size` | `Thumbnail` or `Full image` — only affects forum **attachment IDs**. |
| `overview_short` | The centred blurb. The one field worth real writing. |
| `overview_spoiler` | Longer story/detail, collapsed. |
| `installation`, `developer_notes`, `translator_notes` | Each becomes its own `[SPOILER]`. |
| `required_note` | Free line rendered centred under the spoilers. |
| `genre` | **Derived** — see Tags. |
| `_profile` | Internal; leave `None`. |

Lists of rows — each row is a dict with exactly these keys:

| Field | Row shape |
|---|---|
| `developer_links`, `publisher_links`, `translator_links`, `store_links` | `{"label", "url"}` |
| `downloads` | `{"host", "url"}` — host is the mirror name (`PIXELDRAIN`) |
| `extras` | `{"label", "url"}` — e.g. `Patch Only` |
| `screenshots` | `{"src", "alt"}` — `src` is an attachment ID, URL, or local path |
| `tags_selected` | plain list of tag strings |

Rows with an empty `url`/`src` are skipped at render, so leaving a labelled blank
row is a safe way to prompt the user to fill it.

## Output shape

`build_bbcode` emits a fixed order; there is no template to edit:

```
[CENTER] banner + Overview + [SPOILER]overview_spoiler[/SPOILER] [/CENTER]
Thread Updated / Release Date / Original Title / Aliases
Developer / Publisher / Translator      (name followed by its links)
Censored / Version / OS / Language / Voice / Length
VNDB / Store / Other Games
[B]Genre[/B]        [SPOILER] … [/SPOILER]
[B]Installation[/B] [SPOILER] … [/SPOILER]
[B]Developer Notes[/B], [B]Translator Notes[/B]
[CENTER] required_note [/CENTER]
[CENTER][SIZE=6]DOWNLOAD[/SIZE]  Win: links   Extras: links   screenshots [/CENTER]
```

Any field left empty drops its whole line, so an unfinished post degrades cleanly.

**Thread title** is a separate clipboard button, not part of the BBCode:

```
<title> [<version>] [<developer>]
```

## Tags

`tags_selected` is the list; `genre` is the same list joined alphabetically
(case-insensitive) with `, `. The GUI derives `genre` from the chips, so when
writing JSON by hand set **both** and keep them consistent:

```python
tags = sorted(TAGS, key=str.lower)
d["tags_selected"] = tags
d["genre"] = ", ".join(tags)
```

Validate every tag against `tags.json` — an unknown string still renders in the
genre line but has no chip in the picker, so the user cannot toggle it off:

```python
vocab = set(json.load(open("tags.json", encoding="utf-8")))
assert not [t for t in tags if t not in vocab]
```

The picker can add tags to `tags.json` permanently, so only extend it deliberately.

### Pick tags from the corpus, not from impressions

You have just translated every line in the game — that is a far better source than
memory of a few scenes. Grep the finished store for each candidate tag in **both**
languages and read the hits:

```python
PROBES = {"Scat": (r"\bshit|scat\b|feces", r"スカトロ|ス●トロ|うん〇|ウ●コ"), ...}
```

Search the Japanese `raw` as well as the English `tl`: censored spellings (`ス●トロ`,
`催●`) survive into the translation and are often the only unambiguous evidence.

Then tighten anything ambiguous before committing it. Broad probes are noisy in
exactly the ways that produce wrong tags:

- `sh.t` matched *ship*, `raw` matched *raw tits*, `mouth` matched everything.
- `\bdog` matched **Doggy pose** — a position, not bestiality. The real evidence was
  `種付け動物園で…獣●、解禁` (a breeding-zoo segment), which is depicted, not referenced.
- A single viewer comment is not a tag. `爆乳` appeared once, in chat, about a
  character who is not drawn that way — that is not `Big Tits`.

Distinguish **depicted** from **mentioned**, and **who is doing it**: hits for
"jerk-off material" describe the audience, not the heroine masturbating.

Report the borderline calls to the user rather than silently including or excluding
them — they know the forum's tagging norms better than the corpus does.

### Tags you can settle from the build, not the script

- `Voiced` — look for voice cue columns in the script tables and the size of the
  streamed audio. 57 populated `Voice` cells and 8 GB of `.resource` is conclusive.
- `2D Game` / `3D Game` / `3DCG` — the renderer, not the art style of the menus.
- `Male Protagonist` vs `Female Protagonist` — who the script addresses. 67 lines
  addressing the player as `お客様` settles it.
- `Censored` — DLsite JP releases are mosaicked by law, so `Yes (Mosaics)` is the
  right default, but say you assumed it. It is one of the few fields a reader will
  notice is wrong.

## Images

Banner and screenshots are the user's job — leave `banner_src` and `screenshots`
alone unless asked. For reference, `image_bb` branches on the value:

| `src` | Renders as |
|---|---|
| all digits | `[ATTACH]123[/ATTACH]`, or `type="full"` when `ss_size` is `Full image` |
| `http(s)://…` | `[IMG]url[/IMG]` |
| anything else | `[IMG]local\path[/IMG]` — preview only, does not load on the forum |

## Gotchas

- **The autosave is live.** Once the GUI is open it rewrites the file on every
  change. Write your JSON *before* telling the user to launch it.
- **Clear before you fill.** The GUI's own Clear button calls `apply({})`; doing the
  equivalent in JSON means blanking every key, not overwriting the ones you know.
  See the blank-first section — this is the single easiest way to publish a thread
  carrying another game's download links.
- **`cien_url`** is read by `build_bbcode` (it appends a `ci-en` link to Developer)
  but no GUI control writes it. Prefer a `developer_links` row labelled `Ci-en` —
  same output, and visible in the form.
- **`store_url` / `store_label`** are legacy single-store fields still honoured for
  old profiles; new posts use the `store_links` list.
- **Profile filenames are sanitised** from the title (`[^A-Za-z0-9 _.-]` → `_`), so
  a JP title produces a file of underscores. Save under the romanised name.
- **Don't invent URLs or dates.** A store page you have not seen, a release date you
  inferred from a file timestamp — leave them blank with the label in place. A build
  timestamp is the date *that copy* was compiled, which is not the release date;
  if you use it, say so.

## What the translation pipeline already knows

Fill these from work you have done rather than asking:

| Field | Source |
|---|---|
| `original_title`, `developer` | the game's readme / `globalgamemanagers` company+product |
| `version` | build timestamp (label it as such) |
| `voice` | voice columns + streamed audio size |
| `language`, `translator` | your run |
| `installation` | the real install steps for your delivery method |
| `translator_notes` | credits, unit count, how the patch works, that saves are safe |
| `overview_short` | you have read every line of the script — write it from that |
| `tags_selected` | the corpus scan above |
