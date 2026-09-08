#!/usr/bin/env python3
import argparse
import concurrent.futures
import csv
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = "mistral-large-latest"

SYSTEM_PROMPT = """You are labeling extracted player-visible text from an Unreal Engine Japanese game for translation.

Task:
- Classify each TARGET row by text_type, speaker, speaker_gender, addressee, confidence, and a short reason.
- Use the surrounding CONTEXT rows and the asset path/order to infer dialogue flow.
- Do not translate, rewrite, censor, or moralize the text.
- Return JSON only.

Known speaker/context hints:
- Ive: female protagonist. Defiant/direct style; often uses あたし, アンタ/あんた, 誰よ, 何よ, はぁ？, ふざけ, 帰して, 出してよ, 絶対, 止まらない.
- Mary: female. Often calm/resigned; often addresses Ive by name or says メアリーよ, あなた, 出口はない, ここにいる, 覚えておくわ, 気をつけて.
- GameMaster: controller/observer. Often polite or instructive; uses イヴさん/イブ, 貴方/あなた, 試練, ゲーム, 観察, 見届け, 拒否権, ください/下さい, お待ちしています.
- Mob: rough unnamed male/objectifying speech; often uses お前, 咥えろ, 射精, オラ, こいつ, 名器.
- Zirai/Main/Mine: female voice-line character when asset paths mention VoiceLine/Zirai.
- Narration: descriptive prose, internal narration, scene narration, or lines without a speaking character.
- UI: menus, buttons, prompts, labels, stats, item names, settings, technical headings.
- Unknown: use only when the row is likely spoken but speaker cannot be inferred from text/context.

Important inference rules:
- If a line addresses a person by name, the speaker is usually someone else, not that named person.
- Explicit prefixes such as イヴ「...」 or メアリー「...」 identify the speaker.
- Adjacent dialogue rows in the same asset often alternate speakers; use the whole batch.
- A keyword can be quoted by another speaker. Example: Ive can say 観察？ while objecting to the GameMaster.
- For split segments with the same raw_offset and segment_count > 1, keep the same speaker/type as the neighboring segment unless context strongly says otherwise.
- UI rows can still have Japanese prose; if it is a message shown by the game interface rather than a character speaking, classify it as ui/system/note as appropriate.

Allowed text_type values:
- dialogue
- narration
- ui
- choice
- system
- note
- metadata
- garbage
- unknown

Allowed speaker_gender values:
- female
- male
- unknown
- none

Output format:
{
  "rows": [
    {
      "id": "exact target id",
      "text_type": "dialogue|narration|ui|choice|system|note|metadata|garbage|unknown",
      "speaker": "Ive|Mary|GameMaster|Mob|Zirai|Narration|UI|Unknown|...",
      "speaker_gender": "female|male|unknown|none",
      "addressee": "short name or empty string",
      "confidence": 0.0,
      "reason": "brief explanation, max 18 words"
    }
  ]
}

Return exactly one object with a rows array. Include exactly one result for each TARGET row id and no results for CONTEXT-only rows."""


def read_context_rows(path):
    rows = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        filtered = (line for line in f if not line.startswith("#"))
        reader = csv.DictReader(filtered, delimiter="\t")
        for index, row in enumerate(reader):
            row["_input_index"] = index
            rows.append(row)
    return rows


def load_done_ids(output_path, overwrite):
    if overwrite or not Path(output_path).exists():
        return set()
    with Path(output_path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return {row["id"] for row in reader if row.get("id")}


def output_header():
    return [
        "id",
        "bucket",
        "json_file",
        "raw_offset",
        "segment_index",
        "segment_count",
        "text_type",
        "speaker",
        "speaker_gender",
        "addressee",
        "confidence",
        "reason",
        "text",
    ]


def open_output(path, overwrite):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = overwrite or not path.exists() or path.stat().st_size == 0
    mode = "w" if overwrite else "a"
    f = path.open(mode, encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(f, fieldnames=output_header(), delimiter="\t", lineterminator="\n")
    if write_header:
        writer.writeheader()
        f.flush()
    return f, writer


def parse_int(value, fallback=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def group_by_asset(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row["json_file"], []).append(row)
    for asset_rows in groups.values():
        asset_rows.sort(key=lambda r: (
            r.get("json_file", ""),
            r.get("raw_offset", ""),
            parse_int(r.get("segment_index"), 0),
            parse_int(r.get("_input_index"), 0),
        ))
    return groups


def make_batches(rows, done_ids, batch_size, context_before, context_after, dialogue_only, limit):
    groups = group_by_asset(rows)
    emitted = 0
    for asset, asset_rows in sorted(groups.items()):
        targets = [
            row for row in asset_rows
            if row["id"] not in done_ids and (not dialogue_only or row.get("bucket") == "dialogue")
        ]
        if limit is not None:
            targets = targets[:max(0, limit - emitted)]
        if not targets:
            continue

        positions = {row["id"]: idx for idx, row in enumerate(asset_rows)}
        for start in range(0, len(targets), batch_size):
            chunk = targets[start:start + batch_size]
            if not chunk:
                continue
            target_ids = {row["id"] for row in chunk}
            first_pos = min(positions[row["id"]] for row in chunk)
            last_pos = max(positions[row["id"]] for row in chunk)
            context_rows = asset_rows[max(0, first_pos - context_before):last_pos + context_after + 1]
            yield {
                "asset": asset,
                "target_ids": target_ids,
                "target_rows": chunk,
                "context_rows": context_rows,
            }
            emitted += len(chunk)
            if limit is not None and emitted >= limit:
                return


def compact_row(row, target_ids):
    segment_index = row.get("segment_index") or "0"
    segment_count = row.get("segment_count") or "1"
    return {
        "id": row["id"],
        "target": row["id"] in target_ids,
        "bucket": row.get("bucket", ""),
        "offset": row.get("raw_offset", ""),
        "segment": f"{segment_index}/{segment_count}",
        "text": row.get("text", ""),
    }


def build_user_prompt(batch):
    payload = {
        "asset": batch["asset"],
        "target_ids": [row["id"] for row in batch["target_rows"]],
        "rows": [compact_row(row, batch["target_ids"]) for row in batch["context_rows"]],
    }
    return (
        "Classify only rows where target=true. Use target=false rows only as context.\n"
        "Return JSON with one rows item per target id.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


class RateLimiter:
    def __init__(self, rpm):
        self.min_interval = 60.0 / max(1, rpm)
        self.last_request = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            elapsed = time.monotonic() - self.last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_request = time.monotonic()


def read_response_error(error):
    try:
        return error.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_message_content(data):
    content = data["choices"][0]["message"].get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif "text" in item:
                    parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def call_mistral(endpoint, api_key, model, user_prompt, max_tokens, timeout, rate_limiter, retries):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    last_error = None
    for attempt in range(retries + 1):
        try:
            rate_limiter.wait()
            req = urllib.request.Request(endpoint, data=encoded, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = extract_message_content(data)
            parsed = json.loads(content)
            if "rows" not in parsed or not isinstance(parsed["rows"], list):
                raise ValueError("Response JSON did not contain a rows array")
            return parsed, data
        except urllib.error.HTTPError as error:
            details = read_response_error(error)
            last_error = f"HTTP {error.code}: {details}"
            if error.code == 429:
                retry_after = error.headers.get("Retry-After")
                if retry_after:
                    sleep_for = float(retry_after)
                else:
                    sleep_for = min(90, (2 ** attempt) + random.random())
                time.sleep(sleep_for)
                continue
            if 500 <= error.code < 600 and attempt < retries:
                time.sleep(min(60, (2 ** attempt) + random.random()))
                continue
            raise RuntimeError(last_error) from error
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            last_error = str(error)
            if attempt < retries:
                time.sleep(min(60, (2 ** attempt) + random.random()))
                continue
            raise RuntimeError(last_error) from error
    raise RuntimeError(last_error or "Mistral request failed")


def normalize_label(value, allowed, fallback):
    value = (value or "").strip()
    return value if value in allowed else fallback


def normalize_result(item):
    text_types = {"dialogue", "narration", "ui", "choice", "system", "note", "metadata", "garbage", "unknown"}
    genders = {"female", "male", "unknown", "none"}
    try:
        confidence = float(item.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "id": str(item.get("id", "")).strip(),
        "text_type": normalize_label(item.get("text_type"), text_types, "unknown"),
        "speaker": str(item.get("speaker") or "Unknown").strip() or "Unknown",
        "speaker_gender": normalize_label(item.get("speaker_gender"), genders, "unknown"),
        "addressee": str(item.get("addressee") or "").strip(),
        "confidence": f"{confidence:.2f}",
        "reason": str(item.get("reason") or "").replace("\t", " ").replace("\n", " ").strip()[:240],
    }


def write_batch_results(writer, output_file, batch, parsed):
    by_id = {row["id"]: row for row in batch["target_rows"]}
    seen = set()
    for raw_item in parsed["rows"]:
        item = normalize_result(raw_item)
        row_id = item["id"]
        if row_id not in by_id or row_id in seen:
            continue
        source_row = by_id[row_id]
        writer.writerow({
            "id": row_id,
            "bucket": source_row.get("bucket", ""),
            "json_file": source_row.get("json_file", ""),
            "raw_offset": source_row.get("raw_offset", ""),
            "segment_index": source_row.get("segment_index", ""),
            "segment_count": source_row.get("segment_count", ""),
            "text_type": item["text_type"],
            "speaker": item["speaker"],
            "speaker_gender": item["speaker_gender"],
            "addressee": item["addressee"],
            "confidence": item["confidence"],
            "reason": item["reason"],
            "text": source_row.get("text", ""),
        })
        seen.add(row_id)
    missing = [row_id for row_id in by_id if row_id not in seen]
    for row_id in missing:
        source_row = by_id[row_id]
        writer.writerow({
            "id": row_id,
            "bucket": source_row.get("bucket", ""),
            "json_file": source_row.get("json_file", ""),
            "raw_offset": source_row.get("raw_offset", ""),
            "segment_index": source_row.get("segment_index", ""),
            "segment_count": source_row.get("segment_count", ""),
            "text_type": "unknown",
            "speaker": "Unknown",
            "speaker_gender": "unknown",
            "addressee": "",
            "confidence": "0.00",
            "reason": "missing from model response",
            "text": source_row.get("text", ""),
        })
    output_file.flush()
    return len(seen), len(missing)


def append_raw_log(path, batch, parsed, raw_response):
    if not path:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "asset": batch["asset"],
        "target_ids": list(batch["target_ids"]),
        "parsed": parsed,
        "usage": raw_response.get("usage", {}),
        "model": raw_response.get("model"),
    }
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def label_batch(batch, prompt, args, api_key, rate_limiter):
    parsed, raw_response = call_mistral(
        args.endpoint,
        api_key,
        args.model,
        prompt,
        args.max_tokens,
        args.timeout,
        rate_limiter,
        args.retries,
    )
    return batch, parsed, raw_response


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Use Mistral chat completions to classify extracted game text context.")
    parser.add_argument("--input", default=".translation_tooling/work/all_text_context.tsv")
    parser.add_argument("--output", default=".translation_tooling/work/mistral_text_labels.tsv")
    parser.add_argument("--raw-log", default=".translation_tooling/work/mistral_text_labels.raw.jsonl")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--api-key-env", default="MISTRAL_API_KEY")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--context-before", type=int, default=6)
    parser.add_argument("--context-after", type=int, default=6)
    parser.add_argument("--rpm", type=int, default=55, help="Requests per minute cap. Keep <= 60 for this project.")
    parser.add_argument("--concurrency", type=int, default=6, help="Maximum in-flight Mistral requests.")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dialogue-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print the first request prompt without calling Mistral.")
    args = parser.parse_args()

    if args.rpm > 60:
        raise SystemExit("--rpm must be <= 60 for this project limit")

    rows = read_context_rows(args.input)
    done_ids = load_done_ids(args.output, args.overwrite)
    batches = make_batches(
        rows,
        done_ids,
        max(1, args.batch_size),
        max(0, args.context_before),
        max(0, args.context_after),
        args.dialogue_only,
        args.limit,
    )

    first_batch = next(batches, None)
    if first_batch is None:
        print("Nothing to label.")
        return

    first_prompt = build_user_prompt(first_batch)
    if args.dry_run:
        print("=== SYSTEM PROMPT ===")
        print(SYSTEM_PROMPT)
        print("\n=== USER PROMPT ===")
        print(first_prompt)
        return

    api_key = args.api_key or os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Missing API key. Set {args.api_key_env} or pass --api-key.")

    output_file, writer = open_output(args.output, args.overwrite)
    rate_limiter = RateLimiter(args.rpm)
    total_seen = 0
    total_missing = 0
    submitted = 0
    completed = 0

    try:
        max_workers = max(1, args.concurrency)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending = {}

            def submit(batch, prompt=None):
                nonlocal submitted
                submitted += 1
                request_prompt = prompt if prompt is not None else build_user_prompt(batch)
                print(
                    f"submit batch {submitted}: {batch['asset']} targets={len(batch['target_rows'])}",
                    flush=True,
                )
                future = executor.submit(label_batch, batch, request_prompt, args, api_key, rate_limiter)
                pending[future] = submitted

            submit(first_batch, first_prompt)
            while len(pending) < max_workers:
                try:
                    submit(next(batches))
                except StopIteration:
                    break

            while pending:
                done, _ = concurrent.futures.wait(
                    pending,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    batch_number = pending.pop(future)
                    completed += 1
                    try:
                        batch, parsed, raw_response = future.result()
                    except Exception as error:
                        print(f"batch {batch_number} failed after retries: {error}", file=sys.stderr, flush=True)
                        continue
                    seen, missing = write_batch_results(writer, output_file, batch, parsed)
                    append_raw_log(args.raw_log, batch, parsed, raw_response)
                    total_seen += seen
                    total_missing += missing
                    print(
                        f"complete batch {batch_number}: wrote={seen} missing={missing} "
                        f"completed={completed} in_flight={len(pending)}",
                        flush=True,
                    )
                    try:
                        submit(next(batches))
                    except StopIteration:
                        pass
    finally:
        output_file.close()

    print(f"done. wrote={total_seen} missing={total_missing} output={args.output}")


if __name__ == "__main__":
    main()
