# LLM Translation Pipeline (Mistral & Claude)

Two proven drivers are preserved under `tools/Game Translation/Reference Pipelines/`. **Mistral** (`/v1/chat/completions`, free-tier friendly) and **Claude** (Message Batches API, cheapest at scale with prompt caching). Copy the closest one, don't rewrite from scratch. (`RP/` below = `tools/Game Translation/Reference Pipelines/`.)

- Mistral reference impls: `RP/Unreal (FortuneBride)/scripts/mistral_translate.py`, `RP/Unity Mono (NTR Soccer)/scripts/mistral_translate.py`, `RP/Unity Utage (Goblin Sword)/translate_mistral.py`, `RP/Wolf RPG (Pachimon)/translate_mistral.py`.
- Claude batch reference impl: `RP/RPG Maker MVMZ (BroodGeneral)/` (`tl.py`, `batches.py`, `rpgmvtl/`) and `RP/SRPG Studio (Belphegor)/` (`tl.py`, `srpgtl/`).

---

## Claude request shape: the three params that decide the bill

**`output_config.effort` is the single biggest cost lever, and it is not where you expect it.** It lives inside `output_config`, not top-level, and the default is `high` - a model left at the default spends as many thinking tokens as it wants. Translation is direct high-volume work with no reasoning to do:

```python
output_config={"effort": "low"}          # low | medium | high | xhigh | max
thinking={"type": "adaptive"}            # leave thinking ON, lower the effort
```

**Always state the effort next to any cost estimate.** An estimate computed at `low` is wrong by a multiple against the same run at the default, and nothing in the numbers reveals which one you quoted.

Do not reach for `thinking: {"type": "disabled"}` to save tokens.
On Opus 5 it is accepted only at effort `high` or below, and it introduces two failure modes (a tool call written into visible text, `<thinking>` tags leaking into the response).
Adaptive thinking at `effort: "low"` is both cheaper and safer. `thinking: {"type": "enabled", "budget_tokens": N}` is a hard 400 on the whole 5 family and on 4.7/4.8.

**The 5 family rejects sampling params.** `temperature`, `top_p` and `top_k` are removed and return a hard **400** on `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`, `claude-opus-4-8` and `claude-opus-4-7`. They still parse on `claude-opus-4-6` / `claude-sonnet-4-6` and older. Send none of them on any 4.6-or-later model, and **match the family by an explicit id list, not by a numeric range** - the cut is between 4.6 and 4.7, not at a version number you can compare. Same for assistant prefill, which is a 400 across the entire 4.6+ generation. `temperature=0.0` remains correct on OpenAI-shaped and Mistral endpoints.

Batches results **arrive in any order** - key by `custom_id`, never by position. The `fallbacks` parameter is rejected on the Batches API.

## Mistral: measured free-tier limits (2026)

Limits are per-account and **not published** - read them live from response headers. Measured values (per API key):

```
x-ratelimit-limit-req-minute:    50
x-ratelimit-limit-tokens-minute: 25000   (input+output combined)
x-ratelimit-remaining-req-minute / -tokens-minute  <- throttle off these, not a fixed sleep
x-ratelimit-tokens-query-cost:   <cost of that request>
```

Probe any account with a 1-token call and dump `-D -`:
```bash
curl -s -D - -o /dev/null -X POST https://api.mistral.ai/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"mistral-medium-latest","messages":[{"role":"user","content":"OK"}],"max_tokens":5}'
```

**Two keys run in parallel** = one worker pool per key, each with its own limiter, so ~2x throughput on free tier. Model: `mistral-medium-latest` (was `mistral-medium-3-5`) is the workhorse, `mistral-large-latest` for hard scenes, `mistral-small-latest` for cheap UI passes. `temperature` 0.15-0.3 for deterministic translation. Response format `{"type":"json_object"}`.

## Mistral driver anatomy (what to keep)

An `AdaptiveLimiter` that paces off the live headers, not a fixed RPM:
```python
REQ_PER_MIN, TOK_PER_MIN, TOKEN_HEADROOM = 50, 25000, 3000
# acquire(est): block until req_remaining>0 AND tokens_remaining-est>headroom; reset window at 60s
# update(headers): sync tokens_remaining/req_remaining to x-ratelimit-remaining-* after each call
```

**Parse the per-second rate-limit header as a `float`, never `int`.** Mistral's per-model RPS values are commonly fractional (0.08, 0.42, 0.83) and `int()` floors them to 0, which either divides by zero computing `min_interval = 1/req_per_sec` or leaves the limiter wide open and gets the key throttled for the rest of the run. Integer parsing is for count headers only. With no true per-second header, divide `x-ratelimit-limit-requests` (RPM) by 60. Seed conservatively at **0.5 RPS** and let the first response correct upward rather than hand-tuning per model and per account tier. Reserve the next slot atomically under a lock by advancing a shared `next_request_at` by `min_interval`, so bursting threads cannot collectively overrun a per-minute cap, and **cap each sleep at 5s per iteration** so header updates written by other threads are picked up mid-wait. On `remaining-requests <= 0`, push `next_request_at` out a full 60s.

429 / 5xx / network handling (copy verbatim):
```python
if e.code == 429:
    ra = e.headers.get("Retry-After")
    try: delay = float(ra)            # RFC 9110 also allows an HTTP-date - guard it
    except (TypeError, ValueError): delay = min(60, 2**attempt + random.random()*2)
    time.sleep(delay); continue
if 500 <= e.code < 600 and attempt < retries:
    time.sleep(min(45, 2**attempt + random.random())); continue
```

**On a 400/422 that rejects `response_format.type == "json_schema"`, downgrade once to `json_object` and retry immediately** - no sleep, and without consuming the attempt. Many OpenAI-compatible proxies advertise the schema form and reject it.

Resume = atomic state file written after every batch:
```python
def save_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)   # atomic; rerun `run` to continue from wherever it stopped
```

State is keyed by **source JP text** (dedup across ids). A `flagged` map holds validation failures with reason. Commands: `run` / `status` / `merge` (official-EN + LLM results into a final dictionary). Keys come from env `MISTRAL_API_KEYS` (comma-sep) or a git-ignored `tl/mistral_keys.txt` - **never hardcode keys in source that might be shared**.

**The no-op path must still write back.** The state file is the durable record and the unit store is derived from it, so `run` deciding "nothing left to translate" and returning early is a bug the day anything resets the store - a re-extraction, a schema change, a deleted working file. On one run `extract` legitimately rewrote `units.json` with empty `tl` fields, `run` saw a full state file, printed "nothing to translate" and returned, and the next gate reported **0 of 207 translated** with every translation sitting safely in the state file the whole time. Fold state into the store *before* the early return, and say what you did:

```python
if not batches:
    write_back(doc, state)      # <- not after the return
    print(f"nothing to translate - {done}/{len(units)} done, store synced from state")
    return
```

The same shape catches a related class: any command whose fast path skips the step that makes its output consistent.

---

## Prove the pipeline with ONE request before committing to a run

**Ship a `smoke` command that sends exactly one request on a MEDIAN-sized chunk and saves nothing.** For a few cents it exercises credentials, the model id, the sampling and effort params, both cache breakpoints, the JSON parser, the index-to-unit map and the placeholder validator - every part that turns a 700-request run into 700 wasted requests.

**Not the smallest chunk.** Chunking always leaves one-unit requests at the tail, and a one-unit round trip exercises none of what actually breaks: no ordering, no key-count check, no multi-line placeholder set.

Run order before spending: `dryrun --show-sample` (scope, cost, sample prompt, no API call) then `smoke` (one real request) then `selftest` (offline wiring) then the run.

**A self-test must not write to the real store.** A fake-translate round trip that fills every unit's `tl` with `"[EN n]"` and saves turns the store into a finished-looking job: `dryrun` then reports 0 pending, a run translates nothing, and inject ships placeholder text into the game. Copy the store to a tempdir, run there, and **assert the real store is still clean afterwards** as part of the test.

**A test that builds its fixtures from PENDING work silently passes once the work is done.** A request-shape test - one cached prefix, no sampling params, `max_tokens` scaled to the payload, every unit queued exactly once - is the most valuable thing you can run before spending, and it is built by calling the same `build_all()` the run calls. The moment the game is finished, `build_all()` returns **zero** requests, every `all(...)` over an empty list is vacuously true, and the suite reports PASS while checking nothing.

Force `retranslate_all=True` in the test so it always builds the full set, and **fail loudly on an empty build** before any other assertion runs:

```python
if not reqs:
    print("FAIL no requests built at all - nothing below was actually tested")
    sys.exit(1)
```

The same shape catches you anywhere a fixture is derived from remaining work: a retry test with nothing failing, an overflow test with nothing overflowing, a conflict test on a clean corpus.

**And when the run has two phases, it legitimately has two cached prefixes.** The names pass and the text pass are different jobs with different system prompts. A test asserting "exactly one cached prefix" across *all* requests fails correctly-built code. Assert one prefix **per job**, keyed off which id-map the request belongs to - a prefix varying *within* a job is the real defect, because it is never re-read and bills the write multiplier every time.

## Claude Message Batches (best at scale)

Use when the game is large (thousands of lines) and cost matters. `RP/RPG Maker MVMZ (BroodGeneral)/` is the reference. Key mechanics:

- **Model** `claude-sonnet-5` for volume, `claude-opus-5` when the prose matters. Match the model key **longest-first** so `claude-opus-4-8` is not caught by a shorter `claude-opus-4` prefix.
- **Two-phase run**: phase 1 = names only, written into the glossary. Phase 2 = dialogue/data with the filled glossary in the cached roster block. Keeps prose names consistent with name boxes.
- **Submit/poll/fetch** with a `_batch_state.json` (batch id, model, id maps, phase). Ctrl-C safe, resume with `fetch`. `batches.py usage <id>` reports real billed tokens.
- Default ~80 units/request, scene-aligned. Split scenes carry 3 context lines.

### Submission: lock it, split it, checkpoint every split

**Take a NON-BLOCKING cross-process lock around submission and fail loudly rather than queueing** - a second window submitting the same corpus is how you get billed twice for one game. Before any network call, reject a queue containing more than one model or more than one provider, and reject entries that predate the current instruction and source-context schema.

Split by accumulating `len(json.dumps(params).encode("utf-8")) + 128` per request against the provider's byte and count limits, and raise if a **single** request exceeds the max.
**Checkpoint each submitted split to state and to durable history BEFORE attempting the next**, marking the job `partially_submitted` until the last split lands.
On resume, skip cache keys already present in the prior state's `custom_id`s, and reuse the **same** saved API key and endpoint - a batch job belongs to the credential and endpoint that created it.

**Write the fetched results file as an exact snapshot, never a merge with a previous run.** Cache keys carry no model identity, so merging a partially-errored new result set over an old one silently mixes two models' output into one patch and is undetectable afterwards.

### The collect queue: append-only fragments, never one growing file

A collect pass over RPG Maker or Wolf discovers thousands of requests per process.
Rewriting a 10k-entry JSON after every parser call makes filesystem metadata the dominant wall-clock cost, and a partial write loses the whole run.
Buffer into a process-local dict keyed by cache key, flush as one **immutable fragment** named with a nanosecond prefix plus pid, tid and uuid so filenames sort in commit order, and coalesce flushes at 64 entries or 15 seconds, whichever comes first, force-flushing on scope exit **including the exceptional path**.
Merge on read in sorted filename order with `setdefault` so first write wins, skipping `.tmp` leftovers and rejecting symlinks and non-`.json` entries.
**Write the full merged snapshot BEFORE deleting any fragment** - the deliberate tradeoff is that a crash can duplicate a collected request but can never lose one.

**At every paid boundary, read strict: raise on a malformed file rather than returning `{}`.** A corrupt queue that reads as empty is how the same corpus gets submitted and billed twice.

### Consume fails closed - no implicit full-price fallback

**A batch consume pass must fail closed when a result is missing, never fall through to a live call.** A batch run exists to pay 50%. A missing result that silently re-issues at full price, multiplied over thousands of chunks, is an unbounded surprise bill with no signal to the user. Three layers:

1. The retry decorator checks the phase at call time and invokes the **unwrapped** function during consume, so a deterministic consume error is not retried five times.
2. The result lookup raises a distinct `BatchResultUnavailableError` when no fetched result matches the payload-plus-context key, with a message naming the fix (redownload with the collect-time glossary freeze, or re-collect).
3. A belt-and-braces raise of the same error inside the retry loop on the live-call branch, so control reaching a live request while phase is consume is a crash rather than a charge.

Allow a fallback to a legacy context-free cache key ONLY when the stored state's `cache_key_version < 2`.

### Batches can sit queued for hours - have a live driver

`processing=118, succeeded=0` is the queue depth, **not** a completion ratio. A real run showed zero progress for 85 minutes and then finished in ~4 hours. The documented cap is 24h and "most complete within 1 hour" is guidance, not a promise.

**The counters are not a progress bar at all.** A 113-request run sat at `processing=113, succeeded=0` for its entire 93-minute life and then flipped to 113 succeeded in a single step. Meanwhile the **console usage graph was live** and showed the input being consumed within minutes of submission - 652K tokens in, matching the job's computed total to 2%. So:

* Do not tell the user "nothing has been billed yet" because `succeeded` is 0. The work is happening and the tokens are spent.
* If you need to know whether a batch is actually moving, the usage page answers it and `request_counts` does not.
* Never cancel a stalled-*looking* batch to re-run it live without checking usage first - you would pay twice for work already done.

Do not burn turns polling.
Either background a watcher, or cancel and re-run synchronously.
Keep a `live` command that reuses the *same* request builder, parser and apply path as the batch driver - thread pool, exponential backoff honouring `Retry-After`, no retry on 4xx.
It costs 2x but returns in minutes with visible per-request progress, which is worth it for a small remainder or a stalled queue.

### Parsing model JSON: two failure modes worth handling

25 of 118 requests failed to parse on a real run. Both are recoverable from the stored results with **no re-billing** - fix the parser and re-fetch.

1. **Unescaped `"` inside a value.** The JP source used an ASCII double-quote as a dakuten on slurred moans (`あ"っ`), and the model carried it into English (`"...enjoy the show? Aa"♥"`). Repair rule: a `"` only *closes* a value when the next non-space character is `,` or `}` (or `:` for a key). Anything else is literal text - escape it.
2. **Self-correction.** The reply emits a partial object, reconsiders in prose, then emits the real one: `{...}\n\nWait, I need to output all 53...\n\n{...}`. A first-`{`-to-last-`}` span swallows the prose. Extract every *balanced* top-level object and keep the one with the most keys.

Order matters: repair quotes first, because the brace scan depends on correct string boundaries. Recovery on that run: 4,181 to 5,534 applied units. Guard both with unit tests, plus regressions for clean input, properly-escaped quotes, fenced JSON, and `{`/`:` appearing inside text.

**Full repair order before `json.loads`:** strip ``` and ```json fences, unwrap surrounding quotes only when `s[1:2] == "{"` and `s[-2:-1] == "}"`, apply the smart-quote table (below), delete trailing commas with `re.sub(r",(\s*[}\]])", r"\1", s)`, then fix a doubled opening quote with `re.sub(r':\s*\"\"(?=[^\",}\]\s])', r':\"', s)` - the lookahead is what stops that rule destroying a legitimate empty string `:""`.

**Keep a regex extractor for blobs that never parse:**
```python
r'"Line(\d+)"\s*:\s*"{1,2}((?:\\.|[^"\\])*)"'   # tolerates one or two opening quotes
# sort numerically, then json.loads(f'"{v}"') per value to decode escapes
```
That turns a truncated response into a partial-count failure the length check catches, instead of a total loss.
**Harvest `finish_reason` when it is not `"stop"`, and `message.refusal`** (whitespace-collapsed, truncated to 500 chars), and log both whenever content is missing or validation failed.
Telling truncation from a refusal from a genuinely bad translation is the difference between lowering the chunk size and rewriting the prompt.

---

## Prompt caching

### Two cache breakpoints, and what goes in each

**A block earns a `cache_control` breakpoint only if its bytes are byte-identical across requests.** Layout:

| block | content | `cache_control` | why |
|---|---|---|---|
| `system[0]` | rules, game bible, output contract | yes, ttl per driver | frozen for the whole run |
| `system[1]` | **roster**: the full name/term glossary, shipped whole | yes | identical every request, written once and read N-1 times |
| `system[2]` | per-batch matched glossary + SFX lines, emitted only when non-empty | **no** | differs every request |
| `messages` | the units | no | |

Measured on a 48,650-unit game: moving the full glossary out of the per-request tail and into the cached roster block took per-request overhead from **2,453 tokens to 178**, and total dynamic input from **3.12M to 2.15M**.

**Correction to an earlier belief in this file.** The old argument was that a second breakpoint means a mid-run glossary edit "re-writes only the glossary block instead of invalidating the whole prefix". That reasoning is wrong and produced a real regression once the glossary was matched per batch. A block whose bytes change per request is **never re-read at all** and bills the write multiplier (1.25x at 5m, 2x at 1h) on every single request. Uncached churn costs base rate. Cached churn costs 1.25x-2x base rate for nothing.

Keep per-batch matched terms in the **system role** even though they are uncached. Demoting them into the user turn makes the model read approved spellings as suggestions rather than as instructions.

Three mechanics that bite:

- **Minimum cacheable prefix is ~1024 tokens.** A roster shorter than that silently does not cache and returns no error.
- **Max 4 breakpoints per request.**
- **Caching is a prefix match over `tools` then `system` then `messages`.** A varying tool list, an unsorted `json.dumps`, a timestamp or a per-request id anywhere before the breakpoint invalidates everything after it.

Mirror the boundary on other providers: OpenAI `gpt-5.6` takes `prompt_cache_breakpoint: {"mode":"explicit"}` on `block[0]`, and many OpenAI-compatible proxies reject block arrays entirely, so join the blocks with `"\n\n"` into a plain string for those.
Keep glossary and SFX as separate strings internally right up to send time so evaluation can export each one.
Watch for the blunt localization hack `static_system = prompt.replace("English", language)`, which rewrites the word anywhere it appears in the bible.

### Serial cache warm-up before fan-out

**Concurrency and prompt caching fight on the first wave.** Fire N requests at once and all N *write* the cache, none reads it - three concurrent requests produced `cache_read = 0` across all three. Send the **first request alone**, wait for it, then fan out. One extra round trip buys the whole run its cache reads.

Do **not** try to prewarm a live request before an Anthropic batch. The warm did not transfer reliably and nearly every batch request still paid the 2x 1h cache-write rate. Batch fans requests out independently.

### Cache TTL follows the driver

| driver | ttl | why |
|---|---|---|
| batch | `"1h"` | async requests are processed minutes apart and would miss a 5m window entirely |
| live | `"5m"` | requests land seconds apart, and the 5m write multiplier is 1.25x against 1h's 2x |

### On a BATCH, caching can cost more than not caching. Know the break-even.

Because a batch fans out independently, most of its requests write the prefix
instead of reading it, and a write is dearer than an uncached token. The
break-even hit rate `f` is where the blend stops beating plain input:

    (1 - f) * write_multiplier + f * 0.10 < 1.00

        1h TTL, write 2.00x  ->  f > 53%
        5m TTL, write 1.25x  ->  f > 22%

**Measured on a 411-request Sonnet 5 batch** with a byte-stable 8.8k-token
prefix: 2,492,100 cache-write tokens against 1,114,425 reads, a **30.9% hit
rate**. Cache writes were $4.98 of the $8.16 bill, and the caching cost
**$1.49 MORE than sending the same tokens uncached would have**. The estimate,
which assumed one write and 410 reads, said $3.58.

So for a batch: the 5m TTL is the safer default despite the "requests are
minutes apart" reasoning, because 22% is a rate a batch actually reaches while
53% is not. Reserve 1h for a run you have measured. And whatever you choose,
**print the cold-cache number next to the optimistic one** in the estimate -
one write and N-1 reads is the best case, not the expected case.

**Confirmed on a second game.** A 204-request Sonnet 5 batch at the 5m TTL came
back at a **42.2% hit rate** - comfortably over the 22% break-even, and still
nowhere near the 53% a 1h TTL would have needed. 5m is the right default.

**And bill the write column at the TTL you actually used.** A cost function
hardcoding `cw1h` overstates a 5m run by 60% on what is, on a batch, the
*largest* column - cache writes were $1.20 of a $3.15 bill. Pass the TTL into
the cost model, not just into the request.

**A roster that grows changes the estimate under you.** The dry run said
$1.90-2.63 and the bill was $3.15. Input was predictable; what moved was the
cached prefix, from ~4.5k tokens to ~8.1k, because the estimate was computed
BEFORE the names pass filled the roster with 189 characters plus roles and
registers. Re-run the estimate after the glossary is populated, or quote the
prefix size you measured it at.

**And bound the roster, because on a batch it is the thing you pay for over and
over.** A batch fans out independently, so most requests WRITE the cached prefix
rather than read it - which makes the roster's size a per-request cost, not a
one-off. A game whose speaker list came from an engine nameplate code had **465
distinct speakers**; shipping all of them with roles and registers is roughly
18k tokens written on every one of 400 requests.

The fix is a `roster_min` line threshold, and it has to come with the other
half or it is a silent quality regression: **names below the threshold are not
dropped, they move into the per-request matched-terms block**, so a rare speaker
is still constrained on exactly the requests where they appear. That block is
uncached by design (its bytes change per request), stays in the *system* role,
and costs base rate only where it is needed.

Two nuances that show up in the estimate report:

* Print **each distinct cached prefix with its own token count**, not the total
  divided by the count. Two prefixes is correct - the names pass and the text
  pass are different jobs - and averaging them hid that the names prefix was
  155 tokens, well under the ~1024 minimum where caching silently does nothing.
* Chunking that breaks on your own STORE's file boundaries rather than the
  game's costs requests for nothing. Sharding a corpus by owner into 222 docs
  and chunking per doc produced 480 requests averaging 51 units against a
  budget of 80; packing scenes in play order across shards and breaking only on
  the budget gave 400. A scene is still never split, and the user turn emits a
  `# scene:` header whenever it changes, so nothing about coherence is lost.

### Measure the hit rate, every run

Report `cache_read_input_tokens / (cache_read_input_tokens + cache_creation_input_tokens)` at end of run, and warn below the **break-even for the TTL in use** (53% at 1h, 22% at 5m) rather than below 5% - a 31% hit rate is not a broken prefix, it is a batch behaving normally and a TTL chosen wrongly, and only the break-even tells the two apart. Warn separately below ~5% over 20 or more requests, which IS a broken prefix. Near-zero re-read means the prefix is not byte-stable, and the design is doing nothing while still billing the write multiplier. A healthy run looks like the measured **99.2% re-reads** over 118 requests.

### Every distinct chunk size is a separate cached prefix

A schema generated per chunk size (`Line1..LineN`, `required` listing all N) makes the output config differ for every N, so a run with ragged tail chunks pays a full-price cache write for each odd size instead of a 0.10x read.
**Keep chunk sizes uniform** and let only the final chunk be short.
Track sizes already written in a file the worker processes share, so the estimator charges exactly one write per newly-seen size: split each queued request's system blocks at the `cache_control` breakpoint, count each distinct prefix once at 2.0x input and (n-1) times at 0.10x, then halve for the batch discount.

---

## Batching & context strategy (both providers)

- **Dialogue**: group by scene/event-page in play order, ~40-90 lines/request. When a scene is too big, split and **carry 3-6 preceding lines as context marked "do NOT translate"**. Pass the speaker per line so register and pronouns resolve.
- **UI / names / items / skills**: batch ~40-45 per request, globally deduped. Terse headers ("UI widget strings - terse natural UI English, preserve markup exactly").
- **Names**: their own tiny first pass so they lock before anything references them.
- **Output contract**: `{"t":{"<id>":"<en>",...}}` (Mistral) or `{"translations":[{"id","translation","translation_speaker","notes"}]}` (Utage/Claude style). One entry per input id, same order, ids unchanged.
- Give each category its own batch and its own context label: `Quest Name`, `Quest Summary`, `Quest Goal`, `Menu Item`, `Menu Help Text`, `Status Tracker Label`, `Character Stat Name`, `Save Screen Label`. The model writes differently when it knows which widget it is filling.

### Do not make one request per scene

Scene-aligning dialogue is right.
Making each scene its own request is not.
A game with hundreds of two-line scenes produced **510 requests averaging 10 units**, where per-request overhead dwarfed the payload.
Pack scenes in play order up to the unit budget and break only on *file* boundaries: 510 requests became 113, and the estimate fell from $8.99 to $3.81 for identical output.
Carry the previous chunk's last 3 lines as do-not-translate context across the join.

Likewise pool the tiny kinds. A `notice` with 1 unit and a `title` with 1 do not each deserve a request. Batch them into one "mixed" request and tag each line with its widget.

### Output-token sizing and the pre-flight that catches an oversized batch

**Size the completion cap off the payload, not a constant:** `min(ceiling, max(8192, payload_tokens * 2))`. A floor of 8192 because even a short structured request needs room for JSON scaffolding and reasoning tokens. Ceiling is provider-dependent: 16384 official OpenAI and Gemini, 16000 Mistral, 8192 DeepSeek and any unknown OpenAI-compatible route. Detect official OpenAI by `urlparse(endpoint).hostname == "api.openai.com"` and **switch the parameter name with it**: `max_completion_tokens` on official OpenAI, `max_tokens` everywhere else (most local OpenAI-compatible servers implement only the latter).

If instead you pin one fixed cap for all providers, **refuse at prepare time to run a batch whose expected output cannot fit it**. Count tokens over `system + glossary + sfx_reference`, the user payload, and the history for every request before submitting, and raise naming the worst offender:

```
Lines per sample is too high for the fixed 4,096-token response limit.
{request_id} contains {N} lines and is estimated to need about {M} output tokens.
Reduce Lines per sample and prepare the benchmark again.
```

A truncated response fails JSON parsing and the line-count check, so an oversized batch size masquerades as "that model is bad at following the schema" when it is really your request shape.
Do not trust the tokenizer for the cost guard either: apply provider fudge factors of 1.30x for Anthropic against 1.10x elsewhere, an extra 1.10x thinking factor for Gemini, clamp estimated output to `executions * 4096`, and refuse to submit when the likely upper bound exceeds 80% of the per-model budget.

### The output contract: id keys, or `LineN` sorted numerically

**Prefer an id-keyed map, `{"t": {"<id>": "<en>"}}`.** It removes an entire class of misalignment failures at zero cost.

**But the id must be OPAQUE and SHORT, or the model tidies it and the map matches nothing.** Ids that carry structure - `ui:6404:MonoBehaviour.m_text`, `db:1:2:DialogueText`, a file path, a dotted field path - get *truncated at a separator* on the way back. On one run every id of the form `kind:fileID:field` came back as `kind:fileID`, so **every UI batch scored 0 of 8 while the translations themselves were perfect**, the driver logged `got=0` with no error, and three repair rounds re-sent the same batch and got the same nothing. It reads exactly like a refusal or a bad prompt.

Number the items **batch-locally** (`n1`, `n2`, ...), keep a `key -> unit_id` map on the batch, and translate back on receipt:

```python
def keyed(items):
    keymap = {}
    for i, it in enumerate(items, 1):
        it["key"] = f"n{i}"          # what the model sees
        keymap[it["key"]] = it["id"] # what you actually store against
    return items, keymap
...
uid = batch["keymap"].get(rkey, rkey)
```

The real id still belongs in the *store*; it just must not be the wire format. And **treat a batch that resolves zero of its ids as a hard failure, not as "the model returned nothing"** - log the first returned key next to the first sent key, which turns an hour of prompt-doctoring into one line of output.

When the contract keys lines positionally, **emit a keyed object schema, never an array, and rebuild the list in NUMERIC key order**:

```python
{"type":"object",
 "properties":{"Line1":{"type":"string"}, ...},
 "required":["Line1", ..., "LineN"],
 "additionalProperties": False}
# parse: keys matching re.fullmatch(r"Line(\d+)"), sorted by int(m.group(1))
```

Providers serialize those keys **lexically** (`Line1, Line10, Line2, ...`).
A raw dict-order read silently shifts every line from index 9 onward in every batch of 10 or more.
It looks like random mistranslation rather than a plumbing bug and is nearly impossible to spot in review.
Sort on the integer suffix **everywhere** the response is walked, including the debug log renderer, so `Line2` prints before `Line10`. Fall back to `list(d.values())` only when no `LineN` key exists at all.
Accept a bare `{"translations": [...]}` array form too and render it back into `Line1..LineN` for the log.

Treat a structured marker leaking into a *translation* as a hard content failure: `re.search(r"(?:^|[}\]])\s*Line\d+\s*:", trans, re.I)` catches `}Line1:` bleeding into player text, where it renders on screen as a speaker label.

### Never apply positionally - fail closed on any count mismatch

**On a count mismatch, write nothing and leave the whole field in the source language.**

```python
if len(stringList) != len(response[0]):
    MISMATCH.append(filename)
    return []          # zip() then writes NOTHING
```

**Never apply by positional index with a length guard** (`if i < len(translatedList)`, `if i >= len(translatedList): break`). That silently misaligns every line after a merged or dropped response entry, and off-by-one misalignment is the single most damaging failure in bulk game translation: every subsequent line gets someone else's dialogue and the patch looks plausible while being completely wrong. Returning `[]` is loud and recoverable.

Three ways this bites in real drivers:

- **Length is not a success test.** A driver that retries internally per chunk can return a full-length list in which one chunk silently fell back to its source. Record a per-call mismatch flag on the thread context and discard the entire result list when that flag is set **or** when the lengths differ. Applying a partially failed batch misaligns every later entry in the same list and freezes a wrong provenance value that no re-run corrects.
- **Join per-list checks with `and`, never `or`.** A real bug shipped because six per-list quest comparisons were joined with `or`, so one matching length let all six write. Quest summaries landed in quest names - plausible English in the wrong field, caught by no syntax check, surfacing mid-playthrough.
- **Recursive pass-2 designs that consume a queue with `x[0]` then `pop(0)`** require pass 2's field guards to evaluate identically to pass 1's, or the queue desyncs invisibly.

Follow every applied field with an atomic save: write `translated/<name>.tmp` then `os.replace`, so a crash mid-run leaves valid partial output.

### Silent index shift when you filter lines out of a chunk

**If you drop lines from a chunk before sending it: filter, renumber, key the cache on the FILTERED payload, cache the filtered value, and expand only at write time.** Two classes get dropped - lines containing U+FFFD (mojibake, whose presence alone should skip the API call for that chunk) and lines with no source-language match (cleaned and bracket-converted locally).

Record each into its own index map, compute the surviving indices, then **rebuild the protected-placeholder table and renumber the replacement map so key `j` is the NEW position** - a stale map is how placeholders get restored into the wrong line.
Number the payload keys `Line{i+1}` over the filtered list and set the schema's line count to the filtered length so the model never sees a hole.
Re-expansion walks the full-length original list and emits, per index, the corrupted-map value, the no-source-language-map value, the next clean value, or the untranslated source line when the clean values run short.
Run that same expansion on the cache-hit path, and skip the API entirely when every line was filtered.

If the filtered payload and the reinsertion map ever disagree, every line after the first skipped entry is written with the wrong translation: the count matches, the JSON parses, no validator fires, and the patch ships with dialogue attached to the wrong speakers.

---

## Token/cost estimation

```python
def estimate_tokens(text):
    jp = sum(1 for ch in text if "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿")
    return int(jp * 1.1 + (len(text) - jp) * 0.28) + 8
```

**A single tokens-per-character ratio over a mixed prompt is badly wrong.** The old `len(text)*1.1` proxy is right for Japanese and about 4x too heavy for English, so an English rules-and-bible prefix estimated at **11,509 tokens against 4,261 real**. Count the two scripts separately, as above.

`tools/Game Translation/Text QA and Glossary/count_tokens.py` gives real `tiktoken` counts (cl100k + o200k) per script.
For an exact Claude count use `client.messages.count_tokens` (free, no generation) - reserve the char-ratio proxy for bulk pre-flight where a per-request API call is impractical. `tl.py dryrun --show-sample` prints scope, cost and a sample prompt with no API call.
Always dryrun before spending.

### Never quote prices from memory

**Read the live pricing page every time.** A cached table reproduced a neighbouring model's rates and attached an invented promotional expiry, producing correct-looking dollar figures for the wrong reason. Transcribe all five published columns - base input, 5m cache write, 1h cache write, cache hits/refreshes, output - and derive batch rates by halving rather than typing them twice. Cross-check the derived numbers against the published batch table. If any model disagrees, your table is wrong.

**An expiry you recorded is not an expiry that happened.** This section previously carried `claude-sonnet-5` at "$3.00 (intro $2.00 through 2026-08-31)". The scheduled increase was cancelled and **$2.00 / $10.00 is now the standard price** - so every Sonnet 5 estimate quoted from this file after that date would have run 50% high, in the safe-looking direction that nobody re-checks. A dated caveat ages into a wrong number exactly as fast as a wrong number does.

Transcribed from the live page, first-party API, per MTok (**re-read before quoting**):

| model | base input | 5m cache write | 1h cache write | cache hit | output |
|---|---|---|---|---|---|
| `claude-fable-5` | $10.00 | $12.50 | $20.00 | $1.00 | $50.00 |
| `claude-mythos-5` | $10.00 | $12.50 | $20.00 | $1.00 | $50.00 |
| `claude-opus-5` | $5.00 | $6.25 | $10.00 | $0.50 | $25.00 |
| `claude-opus-4-8` / `4-7` / `4-6` / `4-5` | $5.00 | $6.25 | $10.00 | $0.50 | $25.00 |
| `claude-sonnet-5` | $2.00 | $2.50 | $4.00 | $0.20 | $10.00 |
| `claude-sonnet-4-6` / `4-5` | $3.00 | $3.75 | $6.00 | $0.30 | $15.00 |
| `claude-haiku-4-5` | $1.00 | $1.25 | $2.00 | $0.10 | $5.00 |

**Store the multipliers, not just the numbers**, so a model released after your last read is derivable rather than guessed: 5m write = **1.25x** base input, 1h write = **2x**, cache hit = **0.1x**. Batch halves **every** token class - the multipliers "stack with other pricing modifiers, including the Batch API discount" - so cache writes and reads halve too.

Three modifiers that silently move the total and are easy to leave out of an estimate:

- **`inference_geo: "us"` is a 1.1x multiplier on ALL token categories** (input, output, cache writes, cache reads) on 4.6-and-later models. The default `"global"` is standard price. An estimate that ignores a pinned geo is 10% light across the board.
- **Fast mode is $10 / $50 on Opus 5 and Opus 4.8** and stacks with the cache multipliers. It is **not available with the Batch API**, so a fast-mode plan and a batch plan are different plans, not a toggle.
- **Long context is not a surcharge.** 4.6-and-later ship the full 1M window at standard rates - a 900k-token request bills per token exactly like a 9k one, and caching and batch apply across the whole window. Do not budget a long-context premium that no longer exists.

Bedrock and Vertex are partner-operated with separate pricing, and their regional/multi-region endpoints carry a 10% premium over global. Claude Platform on AWS and Microsoft Foundry bill the same first-party rates through Claude Consumption Units at $0.01/CCU.

**The tokenizer changed at 4.7 and the docs and the measurement disagree.** The pricing page says 4.7-and-later models use a newer tokenizer producing "approximately 30% more tokens for the same text" (Sonnet 4.6 and earlier use the previous one). A real 118-request run on a post-4.7 model measured **input estimated 961,930 vs 960,000 actual, x0.998** - the 30% did not appear. Do not inflate an input estimate by 30% on the strength of the doc line, and do not assume it will never appear either: state which tokenizer the model uses, quote the proxy figure, and reconcile against the bill once.

### Four ways to run the job, not two

Estimate `batch+cache`, `batch only`, `live+cache`, `live only`. Live+cache lands at ~2x batch+cache.

Real numbers, real game: **48,650 units / 736 requests / 1,245,326 JP source tokens**, effort `low`, 1h cache, output ratio 1.3.

| model | batch + cache | batch only | live only |
|---|---|---|---|
| Sonnet 5 | **$11.17** | $12.83 | $25.67 |
| Opus 5 | **$27.93** | $32.09 | $64.18 |

The Sonnet 5 row is the original run's figures scaled by exactly 2/3. That is legitimate here and only here: all five of Sonnet 5's columns moved from the $3.00 basis to the $2.00 basis by the *same* factor, so the total scales cleanly. **Rescaling a recorded total is valid only when every column scaled by one factor** - re-run the estimator instead the moment one column moves on its own.

### The output ratio belongs to the output *contract*, not the game

| pipeline | contract | ratio |
|---|---|---|
| CoinPussy, Sonnet 5, 5,680 units | object per unit: id, translation, speaker, notes | **2.36** |
| Ajin Syoujyo, Sonnet 5, 5,056 units | bare `{"t": {id: string}}` map | **1.38** |

Same model, same kind of content, 1.7x apart - the difference is JSON scaffolding, not prose. Carry the ratio for the contract you are using. A bare `{id: string}` contract measures **1.38** in practice, so an estimate at 1.3 runs ~6% light.

### Calibrate against a real run, then trust the measurement

Record the estimate at submit time and compare it to billed usage. Measured on 5,680 units / 118 requests:

```
input   961,930 estimated vs 960,000 actual   x0.998
output  103,383 estimated vs 147,669 actual   x1.43
cache: 99.2% of cached tokens were re-reads   (caching working)
```

**Input is predictable** - the proxy was accurate to 0.2%, *despite* the model using the post-4.7 tokenizer that the pricing docs say yields ~30% more tokens than 4.6-era models. Do not inflate the input estimate on that basis, it did not appear. **Output is where estimates break.** Treat the usual 1.3-1.6 expansion ratios as a floor for chatty content, not a ceiling.

---

## The prompt: what belongs in it

### Failure modes worth a rule in the prompt, and the ones to fix offline

**Decorative kana survive as "style".** Translating eroge moans, the model keeps small kana as slur decoration: `Ogh゛っ♡`, `cock milk゛ぅぅぅっ♡♡♡`. 74 of 5,056 units came back that way. The rule that fixes it has to be explicit that these are *sounds*, not symbols:

> No kana may survive into the output, not even as decoration. っ/ッ is a glottal catch, ぅ ぉ ぇ ぃ ぁ are a vowel dragged out. Render them with Latin letters - a doubled vowel, an -h, a hyphen - and delete the kana. `Ogh゛っ♡` is wrong, `Ogh-♡` is right. The dakuten ゛ may stay, it reads as distortion.

That recovered 68 of 74. **Fix the last handful offline** - stranded small kana are a deterministic transliteration and a third round-trip buys nothing:

```python
SMALL_KANA = {"ぁ":"a","ぃ":"i","ぅ":"u","ぇ":"e","ぉ":"o","ゃ":"ya","ゅ":"yu","ょ":"yo", ...}
# っ/ッ -> "-" after a letter, dropped between decorations.
# Bail out unchanged if any FULL-SIZE kana or kanji is present - that is a real
# miss and must go back to the model, not be papered over.
```

The same applies to fullwidth punctuation (`！？。`): convert it offline, no model call. But leave U+3000 alone - inside a moan it is a pacing gap between gasps, and collapsing it runs the phrases together.

**Word-inserts need a spacing rule.** A sentinel standing for an inserted noun (`\n[1]`, `{0}`, `[name2]`) has no space around it in the Japanese, and the model faithfully keeps none:

> Some sentinels are a **word** inserted at run time. Japanese needs no space around one, so the source has none. **English does.** Put a space either side unless the neighbour is an apostrophe, a hyphen or a decoration mark.

Still enforce it on inject: if you peel leading/trailing sentinels off the unit so the model sees clean text, the insert sitting against that edge is outside the unit and the model never saw it at all.

**Labels that overflow their widget need a second pass, not a longer prompt.** Telling the model up front to "keep UI labels tight" does not bound them. Measure after the run, then re-request just the overflowing ones *with their budget stated* - "now 242px, needs <=126px, about 14 characters". Two passes took 34 overflows to 5, and the last 5 were faster to write by hand ("Advance Time" to "Wait") than to round-trip again.

Also worth a cheap scan: a unit whose "translation" is the literal word `placeholder`.

### Context handed to the model must be the SOURCE, never text you just translated

In a writeback-in-place pipeline the message text is translated and stored before the choice list is extracted, so the obvious next step - passing the now-English `messageText` as context for the choice batch - feeds the model a paraphrase that has already lost the honorific, gender and register cues only the Japanese carries. The drift compounds across every branch in the scene.

Capture the source before the translation call (`sourceQuestion = jaString`) and pass **that** as the batch's context item, marked do-not-translate.
Enforce it structurally: read context from the extraction master, not from the mutable in-memory row the writeback pass has already updated.
Covers RPG Maker 102 and 357 choice lists, VN choice tables, and any two-stage pass where stage one rewrites what stage two reads.

### Speaker identity: inject it, then strip the echo in two stages

If you prefix the source line with `[Speaker]: ` for context, strip the echoed prefix back off or every dialogue line in the shipped patch begins with a literal `[Kurone]: ` that the game already renders in its nameplate.
First remove the well-formed forms `[Speaker]:`, `[Speaker]|`, `[Speaker]：`. **Only if that changed nothing**, fall back to the case where the model echoed the *untranslated* Japanese name, which slips past the first check entirely:

```python
re.sub(r"^[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ]+\s*[\(（:]\s*", "", text)   # 琴音: text  and  琴音(text
re.sub(r"\s*[)）]\s*$", "", text)
```

Translate speaker names once and memoize them into a global names list.
**Retry the name call once if `re.search(r"([a-zA-Z？?])", response)` finds no Latin character**, which means the model echoed Japanese back - commit that to the memo and it is reused for the rest of the run.
Repair the `'S` artifact `.title()` creates on possessives.
That same character class `[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ]` is the module-wide "does this string need translating" gate, and it deliberately includes fullwidth Latin and halfwidth katakana.

### Particle-initial fragments need a dummy subject

**A template fragment that starts with a particle needs a dummy subject prepended before translation and stripped afterwards.** RPG Maker `message1`..`message4` on Skills.json and States.json are action-log fragments the engine concatenates *after* an actor name.

Detect with `msg_text[0] in ['は','を','の','に','が']`, prepend the literal `Taro`, and instruct explicitly: reply with only the gender-neutral English translation of the action log, and for messages starting with Taro always start the sentence with Taro - for example translate `Taroを倒した！` as `Taro was defeated!`. Without a subject the model returns a fragment or invents one, and the engine renders `SlimeDefeated!` or a doubled name ("Slime Slime was defeated!").

**Strip case-INSENSITIVELY, unanchored, allowing the possessive:** `\bTaro(?:['’]s)?\b` with `re.I`, then collapse runs of two or more spaces and trim surrounding spaces, tabs and quotes. Models emit `taro` and `TARO` and frequently move the name into the middle of the sentence. **Run the strip even on messages that never got the prefix** - prompt bleed inserts `Taro` into neighbouring items in the same batch.

Send the whole entry (name, description, all four messages) as one batch with a per-slot map of `(field_type, field_name, needs_dummy, raw_source)` so results remap positionally. The pattern applies to any engine whose battle or status log strings are concatenation templates.

### Retry notes go in the USER message and name the failure mode

**Editing the system prefix on retry busts the prompt cache** and costs a full cache write on every attempt, which on a long run is a large fraction of total spend. Put the correction in the user turn.

**Name the observed failure modes rather than saying "try again"**: translate fully with no source-language characters left, no empty or single-punctuation values, preserve every `__PROTECTED_N__` placeholder exactly and in the same position, emit no long runs of one character. Generic retries do not fix placeholder loss.

`max_retries = 2` for live calls, **`0` for a batch consume pass** where a retry cannot change anything. **Order validation cheapest-first and short-circuit**: length mismatch, then placeholder-count multiset, then control codes checked on the RESTORED text, then the content battery, then non-blocking warnings.

---

## Masking, placeholders and control codes

### Masking is three tiers, not one

An opaque placeholder can destroy the meaning the model needs:

1. **Ruby.** Replace `\r[kanji,kana]` with the base spelling (`ruby.split(",",1)[0]`) and do not restore it, when the target convention is to drop furigana entirely.
2.
**Database inserts.** Resolve a runtime lookup such as `\cdb[type:row:field]` to its real string and emit it as a *marked span*, `__CONTEXT_n_START__<value>__CONTEXT_n_END__`, so the model sees the actor or item name and gets pronouns and articles right.
Then restore the whole span - including whatever the model wrote inside it - to the byte-exact original code.
A masked `\cdb[21:78:0]` tells the model nothing about whether the sentence is about a person or an object, and leaking the resolved value into the output breaks the runtime lookup.
3. **Everything else.** An opaque `__CODE_n__` placeholder, string-replaced back.

Build the lookup table from a **full database dump once**, flattened to `{"type:row:field": value}` and cached as a hidden sidecar next to the extract, since the ordinary strings extract holds only translatable strings and cannot resolve every field. Fall back to the strings extract (`group.type`/`line.row`/`line.field` to `source`) when there is no game root.

**Gate write-back on placeholder integrity: each placeholder must appear exactly once and each context marker pair exactly once, or discard the translation and leave the entry with `text == source`.** That converts the most common model failure, a dropped or duplicated code, from a shipped broken line into a benign untranslated no-op the injector reports. Also skip any response byte-identical to the payload you sent.

### Normalize the SOURCE before it enters the JSON payload

**Map every fancy quote to a single ASCII apostrophe before serializing, and apply the identical table to the reply before parsing.** A JP line carrying U+201C U+201D U+FF02 U+2018 U+2019 U+201B U+02BC U+FF07 is read by the model as an ASCII double quote, and `"スキルを"リセットする` comes back as an empty value plus stray trailing text. It parses, the key count matches, and the content is silently gone. One `str.maketrans` table, **including the double quotes, which become `'` and not `"`**. Run the same table over the response before `json.loads` so the repair is symmetric.

**Scope NFKC to half-width kana spans only:**
```python
re.sub(r"[｡-ﾟ]+", lambda m: unicodedata.normalize("NFKC", m.group(0)), text)
```
Whole-string NFKC flattens the fullwidth Latin and fullwidth digits authors use to align menu columns.

### Control-code validation: multiset plus scope order, never position

Position comparison rejects most good translations because English word order differs. Plain set comparison lets the model drop a duplicate icon or invert a colour scope so the rest of the box renders wrong. Compare `Counter(source_tokens)` against `Counter(live_tokens)`, plus a scope-order check.

| case | verdict |
|---|---|
| `\C[2]Name\C[0] \I[14]` to `\I[14] \C[2]Name\C[0]` | accept - a complete scope moved as a unit |
| `\V[302]` moving with its translated noun phrase | accept |
| `\C[2]Name\C[0]` to `\C[0]\C[2]Name` | reject: `formatting scope order changed` |
| `\I[14]a\I[14]` to `\I[14]a` | reject on count (multiset, not set) |
| `\SHADOW[3]` to `\SHADOW[08]` | reject: parameter token changed |
| invented `\Coming` | reject: added escape |

One regex covering bracket codes, bare singles, internal sentinels and printf forms:
```python
TOKEN = r"\\(?:[A-Za-z]+\[[^\]\r\n]*\]|[{}.!|^><])|__PROTECTED_\d+__|%(?:\d+\$)?[-+#0 ]*(?:\d+|\*)?(?:\.\d+)?[A-Za-z]"
```

**Escape orphan backslashes on restore.** A lone `\` that survives into English can form a *new* control code once Latin letters follow it, so emit `\\`: `\C[1]\ヘレンの体力－100` becomes `\C[1]\\Helen's Stamina -100`. Invert that when re-protecting cached text for reuse.

**A missing SENTINEL is not automatically a missing CODE - but relaxing that
check has a hole.** The model often restores a code itself, writing `%1's
attack!` where the payload said `⟦0⟧の攻撃！`. That is byte-identical to what
the injector would have produced, and 145 of one run's 150 sentinel flags were
exactly that. So make the sentinel comparison a cheap PRE-FILTER and let the
restored-multiset test decide.

The hole: that fallback only covers sentinels whose value is a code the regex
recognises. Anything *else* you masked into a sentinel - a choice-visibility
clause, a plugin condition, a span you protected for position - is invisible to
a code multiset, so the relaxation waves a dropped one straight through. It
re-opened a deleted-gate bug that the strict check had just caught. **Forgive a
missing sentinel only when its stored value is a recognised code; otherwise it
stays a hard failure.**

**A correct code multiset does not mean a correct line.** The check answers
"are the same codes present in the same numbers", and a translation can pass it
while the words around the codes are broken. Shipped in one patch:

```
JP  %1は\c[16]レベル\c[17]%2\c[0]に上がった！     "%1 rose to Level %2!"
EN  %1's \c[16] rose to level \c[17]%2\c[0]!    "Azusa's  rose to level 5!"
```

Every code is present, in order, in the right number - the multiset check is
clean. But the word that lived INSIDE `\c[16]` was moved out and dropped, and a
possessive was invented for a topic marker, so the rendered line has a hole in
it and reads as a bug. Nothing automated catches this. When a string is a
format template with codes in the middle, the reviewable unit is the RENDERED
result with plausible substitutions, not the template - render it and read it.

**Exclude LOCKED units from the failure tally.** Stock-UI seeds, mirrored
values and pre-filled silent beats are `identical` to their source *by design*.
Counting them buried 33 real echoes under 82 intentional ones.

RPG Maker specifics: flag `missing-center-alignment` when a code-`401` source contained `\ac` but not every non-blank output line starts with `^\s*\ac(?=[^A-Za-z]|$)`, and `unsafe-bare-center-code` when `\ac` or `\cl` is followed immediately by a letter, which the engine swallows into the escape.

### Tune a noisy check by ABLATION, not by intuition

A canonicaliser is a pile of rules, each added because it fixed something. Some
of them cost more than they fix, and you cannot tell which by reading them.
Turn each rule off in turn over the finished corpus and count both directions:

```
all rules on          : 274 flags
  digit+scale  off ->  278   (rule fixes   4, causes   0, net -4)   keep
  bare scale   off ->  276   (rule fixes   2, causes   0, net -2)   keep
  counters番位点 off ->  279   (rule fixes   5, causes   0, net -5)   keep
  ordinal      off ->  278   (rule fixes   6, causes   2, net -4)   keep
  kana numerals off->  281   (rule fixes   3, causes   6, net +3)   DROP
```

The kana-numeral rule is the lesson: mapping `ひとり`/`ふたり` to 1/2 fixed 3
units and created 23, because `ふたりきり` is "alone together" and English writes
neither as a digit. Narrowed to the `つ`-series it still netted +3. It is now
off, left in the file **empty and documented with its measurement**, because the
next game may write its counts that way and the number is the thing worth
keeping.

Rules that earned their place on JP→EN, all measured net-negative:

* a DIGIT followed by an English scale word - `15 million` against `１５００万`;
* a BARE scale word - `the top hundred` against `上位１００名`;
* an English ORDINAL suffix - `_NUM_RE` refuses a digit followed by a letter so
  that `Lv5` is not a quantity, which also makes `7th` invisible while `7位` is
  perfectly visible, so every rank read as a dropped number;
* `+` before a digit is a SIGN - `回数＋１` reads as `+1` while `Count+1` reads
  as `1`, and `MAXHP*5%アップ` against `MaxHP +5%` flagged twenty-two skill names.

**Then bucket what is left, because the buckets have different value.** Split
into *invented* (source had none), *dropped* (target has none), *reordered*, and
**conflict** (both sides have numbers and they disagree). A real quantity error
has to land in `conflict`. On this corpus that bucket went to **empty**, which
is what justified reporting the remaining 248 without retrying them - a retry
produces a differently-restructured sentence, not a fixed one.

**Report a check you do not retry, and print the reason next to the count.**
Not a silent mute, and not a global waiver: the count stays visible and the
justification travels with it.

### Classify drift into named failure modes before handing it to a model

**"Control-code mismatch" is not an actionable instruction.** Parse the guard message's token lists out of the text between the literals `source has ` and `, translation has ` (truncate at any trailing advice clause), rewrite Rust-style `\u{3000}` escapes to real characters first because Python's json decoder rejects them, then json-decode both sides. Compute missing and extra as **multiset** differences with `Counter`, so duplicates count and a pure reordering shows as neither and is reported as "order differs". Classify in this order:

1. **Unrepresentable characters** - list the exact chars failing `char.encode("cp932")` with their `U+XXXX` codepoints.
2. **The *source* has an unclosed bracketed code at end of line** (`\\[A-Za-z]+\[[^\]\r\n]*(?=\r?$)`, a shipped `\i[200`). The instruction is to keep the malformed suffix identical, not to "fix" it.
3. The translation repeats a window prefix like `@N` more times than the source.
4. Every changed token fullmatches `\f\[(\d+)\]` - font-only.
5. An extra token beginning with a literal `\n` - the model emitted the two characters instead of a newline.
6. Extras that are all `\"` - added backslashes before quote marks.

**Mark font-only drift REVIEW, not FIX.** Your own text fitting legitimately changes font sizes, and a repair pass told to FIX it will undo the fitting.

Emit a manifest with locator, named problem, deduped and counted missing/extra token lists (first 6, control characters rendered) and per-mode guidance.
Constrain the repair prompt: edit only `text`, never `source`, ids or order, resolve locators structurally, keep the window prefix exactly once at the start, allow adding the obvious closing `]` to a malformed source code only when all normalized codes then match.
**Forbid the cheats by name**, because a model will take them: deleting `source`, copying `source` into `text`, or enabling a global drift-allow flag all make the check pass and ship untranslated or crashing lines.

### Leaked engine syntax in the shipped text

Sentinel-multiset validation compares source to translation and **cannot see a code that survived injection**, which is the most visible failure a patch can ship. Run over the injected output:

```python
r"\\(?:C|I|FS|PX|PY|OW|OC|V|N|P)\s*\[[^\]\r\n]*\]"   # IGNORECASE
```

Know its gap: it covers only bracketed codes, so add bare `\G`, `\.`, `\!`, `\|`, `\>`, `\<`, `\^`, `\$`, MZ's `\{`/`\}`, and your own sentinel form (`⟦0⟧`, `{CTRL1}`).
Two more families are worth running over player prose - internal locators (`Map\d{3,}`, `(?:map|event|common event|switch|variable|troop)\s+(?:ID\s*)?#?\d+`, bare `(x, y)` pairs, `x=12`/`y: 34`) and authoring jargon leaking out of notes into copy (`(victory|success|loss) branch`, `(route|story|objective|progression) state`, `the event (advances|sets|calls|enables)`).

**The transferable half is the scoping.** Strip comments first with `re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)`, and have one scanner that knows which regions are player-facing and which are allowed to contain raw engine syntax. Without that split the technical sections trip every pattern and the check gets turned off.

---

## Re-run safety: keep the source inside the patched file

**Store the Japanese source inside the patched file so a second pass never feeds English back to the model.** Without an in-file source of truth, a game update silently reverts hundreds of finished lines with no diff signal that anything was lost.

Three shapes cover everything:

- A **scalar** `_original` string for single-slot codes, keyed by a table naming the parameter index: `{108:0, 320:1, 324:1, 325:1, 355:0, 356:0, 655:0, 657:0}`.
- A **list** `_original` parallel to `parameters[0]` for code 102 choices.
- A sparse **path-mirrored dict** for structured codes such as 111 and 357, built by walking before and after in parallel and recording only non-empty strings that actually CHANGED, keyed by stringified list index or dict key, then merged non-destructively so an existing value is never overwritten.

In event command lists keep a **command-level** `_original` holding the Japanese for that command's translated parameter.

**Every setter is write-once.** Return early if a scalar `_original` already exists, and for database and system fields additionally refuse to store a value containing no Japanese. Never modify or remove one.

**The load-bearing asymmetry:** decide whether to SKIP a slot from its CURRENT live value, but read the text you SEND to the model from `_original` when present. A re-run then translates from pristine Japanese, and only for slots still holding Japanese.

**Snapshot before pass 1 and apply the originals twice against that same pristine snapshot** - once after pass 1 for handlers that write during collection, once after pass 2. Otherwise a handler that has already written turns its own translation into the preserved "source" and the file is permanently unrecoverable.

Prefer re-reviewing the current translated tree that retains `_original` over a pristine re-extraction: every QA pass then compares live against source in place with no matching dump to hunt down.
On an official update, diff the new data file against its **pre-update translated counterpart** so surviving translations are retained and newly official Japanese is not missed, scoping the pass to the full update diff including wholesale-replaced files.
Locate the update by the recorded patch commit and its parent diff, not by file timestamps, and if the commit or a safe file scope cannot be established, stop without editing.

**Read markers through the `_original`-aware accessor, not the live parameter.** RPG Maker code 408 continues a code-108 comment and most comment blocks are developer notes, so a 408 handler walks backwards past intervening 408 and empty `-1` commands to the owning 108 and requires its text to be in a supported-marker set (`選択肢ヘルプ` is the known one). On a re-run that 108 already reads `Choice Help`, and reading `parameters` orphans every 408 after the first run.

---

## Validation

### Hard failures block injection

1. Empty translation, or identical to source (untranslated).
2. Residual Japanese (hiragana/kanji in output, lone katakana `·`/`ー` separators don't count).
3. Placeholder mismatch (control-code sentinel set changed - count/identity, sometimes order).
4. Byte-span / width overflow for fixed layouts (Unreal, exe patches, narrow boxes).

Soft warnings (review, don't block): possible misgender (female char but he/him), extreme over-expansion (>3-6x), leftover cosmetic kana (っ/ッ) stranded in English, punctuation drift (JP `。！？` to EN `. ! ?`).

### The in-loop retry gate battery

**Run the content battery only on lines whose SOURCE matches the source-language regex, and make every one a hard failure that forces a retry, never a warning.** The recorded regression is exactly that: collapse-to-one-punctuation-mark used to be a warning, so corrupt player text was cached AND written without ever entering the retry path.

```
empty or whitespace-only output
len(trans) <= 1 and len(orig) > 3
len(orig) > 10 and len(trans) <= 2 and not trans.isalnum()
degeneration:     re.search(r"(.)\1{44,}", trans)
runaway length:   len(orig) > 10 and len(trans) > max(len(orig)*8, 120)
absolute cap:     len(trans) > 4000 and len(trans) > len(orig)*3
source-language residue
leaked scaffolding: re.search(r"(?:^|[}\]])\s*Line\d+\s*:", trans, re.I)
```

**Waive both short-output checks when the output contains a bracketed code** (`re.search(r"\\[A-Z]\[", trans)`), since `\N[1]` is a legitimately two-to-five character line. **Strip U+3000 and the CJK quote marks 「」『』〝〞〟 from the residue copy before the language check** - ideographic space is intentional menu padding, and English that keeps the source's stylistic wrappers is not untranslated. When the target is Chinese, add a separate kana-residue check `[ぁ-ゖァ-ヺー\uFF66-\uFF9F]`, because the generic CJK class cannot see that kana survived. Keep a parallel non-blocking warning pass that re-runs only the short and repetition checks and prints after a line has already passed.

### The post-hoc mechanical flag battery

**Emit a fixed, order-stable flag battery per record and let nothing else drive escalation.** Eight flags, in emission order:

| flag | test |
|---|---|
| `empty-live` | `not live.strip()` |
| `unchanged-source` | `source == live` byte-for-byte (silently skipped unit) |
| `source-language-residue` | `[一-龠々〆〤ぁ-ゔァ-ヴー]` anywhere in the live string |
| `runtime-token-mismatch` | `Counter(src_tokens) != Counter(live_tokens)` |
| `missing-center-alignment` | see control-code section |
| `unsafe-bare-center-code` | see control-code section |
| `visible-number-mismatch` | ordered list diff, below |
| `suspicious-length-ratio` | `len(source) >= 8 and len(live) >= 1` and raw ratio `< 0.35` or `> 3.0` |

**Keep length-ratio out of the blocking set and promote the other seven.** JP to EN routinely triples, so forcing review on expansion drowns the queue in good lines and spends the entire review budget on noise. That 0.35/3.0 band still catches truncation and runaway hallucination.

**Reimplement the whole battery once in an independent verifier that never imports the builder** - re-walk the files, rediscover the preserved-source leaves, re-resolve pointers, recompute hashes - and reject the run when the two disagree. A check living only inside the thing it checks certifies its own bugs.

### Visible-number mismatch: CANONICALISE both sides, then compare ordered

**Quantity drift is the most damaging class of fluent-but-wrong MT output.** `三日後` as "in a few days", a quest needing 3 items described as needing 5. Every one is grammatical English that spelling, grammar and placeholder checks wave straight through.

The base is a digit extraction over the code-stripped, NFKC-normalised text:

```python
visible = unicodedata.normalize("NFKC", _RUNTIME_TOKEN_RE.sub("", text))
NUM_RE  = r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z0-9_])"
# flag when source_numbers != live_numbers, guarded by (source_numbers or live_numbers)
```

Stripping tokens first stops `\C[3]` and `\V[12]` contributing phantom digits. NFKC makes a fullwidth `３` equal an ASCII `3`. The lookarounds exempt `3rd`, `HP100` and `Lv5`. Compare **ordered**, so "3 of the 5" becoming "5 of the 3" is caught.

**That base alone is a false-positive machine, and a check that cries wolf gets switched off.** On a 2,866-unit game its first run produced **seven flags, all seven of them correct translations and none of them a real drift**. Every failure was the comparison's:

| source | translation | why the naive check was wrong |
|---|---|---|
| `5000万G` | `50,000,000 G` | CJK myriad grouping - 5000万 **is** 50 million |
| `10000G` | `10,000G` | a thousands separator, plus the trailing currency unit made the two sides parse **asymmetrically** (`10000G` matched nothing, `10,000G` yielded `10`) |
| `100年` | `a hundred years` | English legitimately spells numbers out |
| `2倍` | `Doubles` | and legitimately lexicalises them |

So **canonicalise both sides to one digit form before extracting**, in this order - each step assumes the digits above it are settled:

1. **Kanji numerals, gated on a COUNTER.** `三日後` is the headline case. Convert `[〇零一二三四五六七八九十百千万億兆]` runs only when a counter follows (`日人個回年月時秒匹枚本階度倍円歳割層つ`), because `一番`, `一体`, `一緒` are lexical and converting them invents a number the source does not have.
2. **Thousands separators**, only where the grouping is well formed (`\d{1,3}(?:,\d{3})+`), so a real decimal comma survives.
3. **Arabic + myriad marks**, largest scale first. Must run *after* step 1 or `5000万` has its `万` read as a bare kanji numeral and becomes `500010000`.
4. **Detach the currency unit.** `10000G` is a UNIT, not the `3rd` ordinal the trailing-letter exemption exists for. Use `(?<=\d)\s*G(?![A-Za-z])` - **not** `\b`, because `G受` has no ASCII word boundary and the Japanese side would keep its G while the English side lost it.
5. **English spelled-out numerals and lexicalised multipliers** - `a hundred` to 100, `double`/`twice` to 2.

Four exclusions that each cost one line of code and remove a large noise class:

- **`体` and `分` are not counters.** `一体` is "what on earth", not "one body". `十分` is じゅうぶん "enough", not じゅっぷん "ten minutes" - it flagged `もう十分お持ちのようですね` and `魔力切れには十分注意` on the same run.
- **`何` before a numeral makes it indefinite.** `何百年` is "hundreds of years", not 100 years, so the quantity is not comparable at all.
- **English `once` is an adverb**, not a count. "once my power's back", "at once", "once more", "once attached to" - mapping it to 1 flagged sixteen correct lines.
- **A LEADING English `one` is a pronoun.** "the one I took" is not the number 1. Allow `one` to *continue* a numeral (`twenty one`) and to precede a scale (`one hundred`), never to lead one.

**And then drop the value 1 from both sides entirely.** It is not comparable across Japanese and English: Japanese writes it as a counter (`一匹`, `一人`, `一回`, `一つ`) where English uses an article, a pronoun, or nothing - `ゴブリン一匹に` is "even one goblin", `一人歩き` is "took on a life of its own", `一気に` is "all at once". The exemption is **symmetric**, so a real drift still shows: `1個` rendered "3 items" is `[]` vs `['3']`, and `3個` rendered "one item" is `['3']` vs `[]`. Only 1-rendered-as-1 and 1-rendered-as-nothing stop being distinguishable, and the second is a dropped article rather than a quantity error.

Result on that game: **61 flags down to 5, of which 4 were real** - "those **two** are trying to run off" where the source says only `あいつら`, and "a small cliff **or two**" where it says `ちょっとした崖くらい`. The naive version had buried those four in its own noise.

### A second corpus: the classes that list does not cover

A 14,750-unit VX Ace game ran the canonicaliser above and opened at **246
flags**. It finished at **47**, and every fix was to the CHECK. The classes it
added:

| source | translation | why the check was wrong |
|---|---|---|
| `２回目` / `３０回目` / `３１本目` | "the second time" / "the thirtieth" / "the 31st" | **ordinals** - 170 of the 246 |
| `―――３時間後―――` | `---Three hours later---` | the leading dash of an em-dash run parsed as a **minus sign**: `['3']` vs `['-3']` |
| `エミリオン宿屋` | `Emilion Inn` | a katakana numeral rule matched `ミリオン` **inside the place name** |
| `数千人` | "several thousand" | `数` makes it indefinite, exactly like `何` |
| `地下２階` / `ＴＤ２階層` | "the second basement floor" / "TD Floor 2" | a floor is **notation**, not a quantity |
| `２等市民` | "second-class citizens" | so is a rank |
| `オッズは２倍` | "the odds are 2x" | the trailing-letter guard rejected `2x`, the form English uses for 倍 |
| `四つん這い` / `二度と` / `百発百中` / `人一倍` | "on all fours" / "never again" / "never misses" / "twice as" | fixed phrases that merely contain a numeral |
| `３，４本の触手` | "three or four tentacles" | a comma between digits is a **list**, not a decimal |
| `３日間で１００回…と３００回…` | "more than 100 climaxes ... in three days" | English **reorders clauses** |

Four rules generalise out of that:

1. **CONVERT ordinals on both sides. Do not delete them.** Deletion looks
   symmetrical and is not: English renders a Japanese ordinal as a cardinal
   (`３日目` to "three days in", `３回戦` to "round three") and the reverse, so
   deleting on the Japanese side leaves the English number with nothing to
   match. Strip the ordinal MARKER (`目`, `第`) and let the counter rules
   convert the numeral; map English ordinal words and `\d+(st|nd|rd|th)` to
   their digit. Guard the word list with `(?<!\ba )(?<!more )(?<!single )` -
   "one more second" and "a single second of rest" are time, not the number 2.
   `first` mapping to 1 is harmless because 1 is dropped from both sides
   anyway.
2. **Notation is not quantity - delete those on both sides.** Floors and ranks
   use different tokens in the two languages (`2階` / `B2` / `2F` / "second
   floor"), so no conversion aligns them.
3. **Compare as a MULTISET, and report order separately.** An ordered compare
   flags every re-ordered clause. Keep the ordering signal as a soft
   `number-order` warning that says "check the numbers still belong to the same
   nouns".
4. **Anchor any substring rule to a word boundary in ITS OWN script.** The
   katakana numerals needed `(?<![ァ-ヴーｦ-ﾟ])`; without it one rule written to
   fix two skill names claimed twenty-odd map names contained 1,000,000.

**Expect the count to move sideways before it comes down.** That run went
246 -> 80 -> 95 -> 146 -> 47: every one-sided fix converted a false positive in
one bucket into a false positive in the other. Track the flags **by shape**
(number only in JP / only in EN / both but different) rather than by total, or
you cannot tell progress from churn.

And the payoff is real: among the 47 survivors was `「一泊 10\G です。」`
translated as "One night is \G." - the inn's price silently deleted. That is
exactly the class the check exists for, and the naive version had it buried
under 199 correct lines.

### Every check needs a visible per-unit waiver

**A validator with no escape hatch gets switched off wholesale the first time it is right about the shape and wrong about the case.** The fifth surviving flag above was `ごせんま…………`, the protagonist's cut-off **kana** spelling of 5000万, correctly rendered "F-fifty mill-...". The checker canonicalises arabic and kanji numerals but not kana ones, and one line does not justify a kana numeral parser.

So give the store a per-unit, per-check waiver that **must carry a reason** and that `validate` **reports** rather than silently applies:

```json
"waive": {"number-drift": "ごせんま is her cut-off KANA spelling of 5000万 …"}
```

```
WAIVED checks : 1 (accepted by hand, listed below - a suppression nobody
                   can see is worse than the false positive it hides)
   = Map029:ev29:p0:c70 [number-drift] ごせんま is her cut-off KANA …
```

Per-unit and per-check, never per-check globally: the second is indistinguishable from deleting the check, and it happens by the same reasoning ("this one is a false positive, so the check is broken").

### Two exemptions the residue check needs

**Censor glyphs are not residual Japanese.** Eroge mask obscenities with `〇` (U+3007) or `●` and often name a character `●●●`. `うん〇` to `sh〇t` is a *correct* localization that keeps the mask. Flagging U+3007 sends good lines to a retry that can only reproduce them. Exclude it from the untranslated-JP class, and keep `々`/`〆`, which are real Japanese marks that should not survive. A lone `ー` between Latin syllables is a separator, not residue.

**A single iteration mark trailing a preserved kaomoji is decoration, not Japanese.** ゝゞヽヾ on `(｀・ω・´)ゞ` are pure flourish, so every emoticon-bearing line burns all its retries and falls back to untranslated Japanese - and emoticons are dense in exactly the genres these pipelines target. Gate the exemption on **all four** conditions:

- the SOURCE matches `(?P<open>[（(])(?P<face>[^（）()\r\n\s]{1,32})(?P<close>[）)])(?P<flourish>[ゝゞヽヾ])?`
- the face holds at least 2 characters whose `unicodedata.category(char)[:1]` is `P` or `S`
- the face itself does NOT match the source-language regex
- the whole token including its parentheses appears byte-for-byte in the translation

Only then drop that one flourish character from the **residue copy** used for the check. **Never touch the translation itself, and never exempt iteration marks in general** - a blanket rule ships real untranslated Japanese.

### What validation cannot catch - read the UI labels

Dump every button, choice, notice and tooltip as `JP -> EN` side by side and skim it. A few hundred lines, minutes of reading, and it is the only pass that finds a short verb rendered as the wrong part of speech: `訂正する` ("correct it", i.e. go back and re-enter) came back as **"Correct"**, which reads as agreement and sends the player the opposite way from the button's actual target.

It is English, it is short, it carries no placeholders and no residual Japanese - **every automated check passes it**. Length and placeholder validation only prove the shape is right, never the meaning. Dialogue is too big for this and needs play-testing. UI labels are small, and they are where a wrong word actually misleads.

### What your extractor filtered out is still on screen

Extraction keys on "contains a source-language character". Everything that filter rejects is invisible to every per-unit pass you will ever write - translation, validation, polish, the lot - and some of it is still wrong on screen.

The reference game writes its trailing-off beat as a run of low lines. Attached to a sentence it came through as a unit and got converted to an ellipsis. Alone on its own line it did not:

```
______[p]                 <- no Japanese, never extracted, ships as underscores
翌日____[p]                <- has Japanese, extracted, polished to "The next day..."
```

The same character in the same role, and one of them was structurally unreachable. The author also writes the marker in **ASCII** as well as fullwidth, so a rule matching only `＿` missed half the occurrences.

- **Punctuation and typographic conventions need converting whether or not they arrived attached to Japanese.** Ellipses, dashes, wave dashes, low lines, fullwidth brackets, `！？` runs.
- **Match both widths of everything.** Fullwidth and ASCII forms of the same mark do the same job in the same script.
- **Anything the unit filter cannot see needs a pass that iterates lines, not units.** That pass exists anyway if you are repairing layout.

Cheap check for the whole class: grep the *injected output* for runs of any character your conventions should have converted, and diff the hits against the Japanese. What is identical in both was never a unit.

---

## The local translation cache

**Key on the payload plus only the glossary entries that actually matched that payload, never on the whole glossary.**

```
md5(f"{payload}|{language}")
  + f"|context:{sha256(matched_glossary_subset)}"     # omit entirely when nothing matched
  + f"|request:{sha256(normalized_request_context)}"
```

Key on the full glossary and one typo fix re-bills the entire game. Key on payload alone and a glossary correction never takes effect, so the old spelling persists forever. Omitting the context segment when nothing matched preserves the legacy key, so upgrading the tool does not discard the existing cache.

Store in SQLite behind a cross-process file lock and **fail open on corruption** - rebuild the cache, never block a translation on it.

**A cache miss must claim the work.** Parallel per-file workers on one game routinely hit the same payload (RPG Maker repeats strings constantly), so without a claim you pay N times for the same chunk. On a miss, or on a STALE claim, or on your OWN claim, write

```python
{"__translation_pending__": True, "pid": ..., "thread": ..., "time": ...}
```

and return a miss so this worker does the request. On someone else's fresh claim, poll every **0.25s** until the value lands or the marker ages past a **600s** TTL. **Delete only markers whose pid and thread match this worker**, so a crashed worker never eats another's finished value, and make the read-merge-write save refuse to let a pending marker overwrite a real translation.

**A queue-building (collect) pass must peek, never claim** - an abandoned marker written by a collect pass stalls the consume pass for the full TTL. A consume pass makes no live calls, so buffer its cache mutations in memory and persist once at scope exit. Buffer a whole file's results in a thread-local deferred-write list and flush once.

For a two-pass batch flow, build each collected request **byte-identical** to the live request including the cached system block.

---

## Applying corrections safely

### One correction per target, and re-read before writing

**Key every correction by `(file, live_pointers)` and refuse to apply two different corrections to the same target.** Because identical (source, translation) pairs are clustered, one approved finding fans out to hundreds of file locations, so two findings that each look local collide and produce last-writer-wins corruption with no error at all. Raise on differing corrections for one key, silently skip an exact duplicate, then **repeat the check one level finer at individual `(file, pointer)` granularity after line-splitting**, which catches overlaps the joined-run key cannot see.

Before writing, re-read each live value from disk and require `current == operation["expected"]` exactly, after applying whatever read transform produced it, raising "expected value changed, rebuild QA" otherwise. That is what makes it safe to re-run against a data folder somebody hand-edited in between.

Resolve every target path and reject it when `data_root not in path.parents or not path.is_file() or path.is_symlink()`. Make the record identity `f"{file}#{source_pointer}@{sha256(source)}"` so any change to the Japanese source invalidates every receipt that referenced it rather than silently rebinding to different text.

### Post-apply regression gate

**After writing, rebuild the manifest from disk, re-run the validators, and diff the flags per record identity.** Assert four things:

1. The set of record identities is unchanged.
2. Every surviving identity's `source_sha256` is unchanged.
3. Every applied operation's new live value equals its replacement exactly.
4. `after_flags - before_flags` is empty except for the explicitly non-blocking flags (length-ratio only).

An approved correction can itself introduce a defect - drop a `\C[0]`, strand a kanji, empty a line - and the per-identity flag diff is the only thing that catches it. The identity and source-hash assertions catch the worse case, where an apply mangled the JSON structure or clobbered a stored original, which makes the patch unrepeatable and no longer reversible.

**On failure restore every touched file, not just the offending one**, from the in-memory pre-image, and record that a rollback happened. Stage each write to a `mkstemp` in the *same directory*, `os.fsync` it, **re-parse the temp file as JSON to prove it is valid**, and only then `os.replace`. A malformed render must never reach the game folder even for an instant.

---

## LLM review passes

For scoring a finished translation rather than repairing it, see
`quality-evaluation.md`. For the review-context export, `glossary-and-prompts.md`.

### Repeated lines are re-reviewed per scene when they carry third-person pronouns

**Deduping the *review* pass by exact (source, translation) pair reviews a reused line exactly once, in the wrong scene.** Japanese drops subjects and MT invents them, so 「わかった」 rendered "I'll tell her" is correct in the scene it was translated in and wrong in every other place the engine reuses that string.

Cluster identical pairs as normal, then break the dedup in exactly two narrow cases:

- A cluster appearing in **2 or more distinct scenes** whose *translation* matches `\b(?:he|him|his|himself|she|her|hers|herself|they|them|their|theirs|themselves)\b` case-insensitively: re-emit it in every one of those scenes with reason `repeated-third-person-context`.
- A cluster spoken by **2 or more distinct detected speakers** whose translation matches the broader all-persons set (add I/me/my/you/your): add one representative scene per speaker, chosen deterministically as `min(candidates, key=scene_id)`.

Keep the base pass minimal with a greedy minimum set cover over dialogue clusters, ties broken by scene id, so these two rules are the only intentional duplication. Mark the re-emitted unit as a context expansion and instruct the reviewer to judge it against **this** scene rather than in general.

### Subjective findings must carry a structured `editorial_basis`

**An LLM reviewer's default failure mode is rewriting perfectly good lines into its own preferred register**, producing an endless stream of "improvements" that cost review time and risk regressions.

First normalize free-form reviewer labels onto a small fixed taxonomy by slugifying and intersecting token sets: `{runtime, control, code}` to `runtime`, `{terminology, consistency, glossary, name, title}` to `terminology`, `{meaning, accuracy, context, referent, pronoun, subject, identity, condition, number, modality, action, explicit}` to `meaning`, fallback `other`.

If the normalized category is `fluency`, `voice` or `wordplay`, the finding **must** carry an `editorial_basis` object whose key set is **exactly** `{defect, source_support, not_preference}`, both strings nonempty and `not_preference` true.
If it is any other category, supplying `editorial_basis` at all is an **error** - otherwise it degrades into boilerplate attached to every finding and stops meaning anything.

Two companion rules: a `clean` verdict on an item that carries prior mechanical evidence must supply nonempty rebuttal text, so a later reviewer cannot quietly discard an earlier one's concrete evidence. And a non-actionable review may not carry a severity.

### Export what was actually sent

**Dump the exact matched glossary and SFX blocks that were sent, as separate review files, on every evaluation run.** When a translation comes back wrong you cannot tell whether the glossary was ignored or simply never matched unless you can see the block the model actually received. Keep the two strings separate on the request record (`request["glossary"]`, `request["sfx_reference"]`) all the way from assembly, then walk every request, dedup lines order-preservingly on `rstrip()`, and atomically write `review_system_prompt.txt`, `review_glossary.txt`, `review_sfx_reference.txt`.

**Write an explicit sentinel rather than an empty file** when nothing matched - `(No Japanese SFX reference entries matched the reviewed source text.)` - so a reviewer can tell "feature off or no matches" from "export broken". Record the reference-data identity in the run manifest too (name, repository, revision, upstream path, sha256, license, and whether the feature was enabled), which is what lets you attribute a quality regression to a reference-data update rather than to a model change.

---

## Comparing providers or models fairly

**Freeze one provider-neutral request object and adapt it per API without changing its content.** Store `system`, `glossary`, `sfx_reference`, `history`, `context_kind`, `instructions`, `user`, `schema_line_count`, and hash it as `logical_hash = sha256(logical)`. Assert all logical hashes are unique and every request carries a system prompt, sources and typed context. That hash plus the manifest hash is what proves months later that all candidates saw byte-identical prompts.

**Pin reasoning depth on every provider or you are comparing thinking budgets, not translation ability, and the cost column is meaningless.** Anthropic: `output_config={"effort": "low"}` with adaptive thinking (do not use `thinking={"type":"disabled"}` - see the request-shape section). OpenAI: `reasoning=none`, `temperature=0.0`. Gemini: `reasoning_effort="minimal"`.

Provider quirks worth copying:

- Gemini's OpenAI-compatible batch endpoint needs `temperature` and `extra_body` popped, because the batch file validator rejects a top-level `google` extension.
- OpenAI wants `max_completion_tokens` on `api.openai.com` but `max_tokens` on most local OpenAI-compatible servers, which implement only the latter.
- **Gemini's OpenAI compatibility layer does not expose file upload or result download.** Submit and fetch must go through `google.genai`'s Files API even though the batch itself is OpenAI-shaped: `google_client.files.upload(file=str(path), config=types.UploadFileConfig(display_name=path.name, mime_type="jsonl"))` and `uploaded.name` as the input file id, versus `client.files.create(file=stream, purpose="batch")` and `uploaded.id` for OpenAI. The subsequent `client.batches.create(input_file_id=..., endpoint="/v1/chat/completions", completion_window="24h")` is shared. Wrap the `types` import in `except (ImportError, AttributeError)` with a plain-dict config fallback, delete the temp jsonl in a `finally`, and detect the provider by explicit name **or** by URL substring `generativelanguage.googleapis.com` so a user who only configured a base URL is still routed correctly. (`DAZEDTL_ROOT/util/batch_providers.py:40`, `:205`)

**Never let a comparison run touch the shared translation cache or the active credential file** - a cache hit returns one model's output for another model's request.
