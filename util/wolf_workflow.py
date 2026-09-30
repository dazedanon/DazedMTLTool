"""Shared WOLF workflow operations, independent of a user-interface toolkit."""
from __future__ import annotations
import json
import shutil
from pathlib import Path
from util.wolfdawn import originals as wolf_originals
from util.project_scanner import (detect_wolf_layout, find_wolf_text_archives, wolf_has_maps,
    wolf_maps_dir, wolf_nested_data_dir, wolf_repair_nested_data_dir, wolf_unpack_out_dir)

MANIFEST_NAME = "manifest.json"
NAMES_JSON = "names.json"
WORK_DIR_NAME = "wolf_json"
PHASE_NAMES_KINDS = {"names"}
PHASE_DB_KINDS = {"db"}
PHASE_MAPS_EVENTS_KINDS = {"map", "common", "gamedat", "txt", "txt-dir"}


class WolfWorkflowCore:
    def _tool_root(self) -> Path:
        return Path(self._workspace_root)

    def _work_dir(self) -> Path:
        return Path(self._game_root) / WORK_DIR_NAME


    def _manifest_path(self) -> Path:
        return self._work_dir() / MANIFEST_NAME


    def _read_manifest(self) -> dict | None:
        mp = self._manifest_path()
        if not mp.is_file():
            return None
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            return None


    def _manifest_kinds(self) -> dict:
        """Return ``{json_filename: kind}`` from the manifest (used to pick which
        files a translation phase should translate)."""
        out: dict[str, str] = {}
        manifest = self._read_manifest()
        if manifest:
            for entry in manifest.get("entries", []):
                name, kind = entry.get("json"), entry.get("kind")
                if name and kind:
                    out[name] = kind
        return out


    def _originals_dir(self) -> Path:
        return self._work_dir() / "originals"


    def _orig_base_for(self, entry: dict, data_dir: Path) -> Path:
        """Pristine-snapshot path mirroring an entry's base under originals/."""
        base = Path(entry["base"])
        try:
            rel = base.relative_to(data_dir)
        except ValueError:
            rel = Path(base.name)
        return self._originals_dir() / rel


    def _snapshot_db_dat_sibling(
        self, entry: dict, data_dir: Path, log=None
    ) -> None:
        """Snapshot the ``.dat`` sibling for a database ``.project`` entry.

        WolfDawn ``strings-inject`` on ``kind == "db"`` needs both files in the
        ``--base`` directory. The manifest only lists the ``.project`` path.
        """
        from util.wolfdawn import db_dat_sibling

        if entry.get("kind") != "db":
            return
        proj_orig = self._orig_base_for(entry, data_dir)
        dat_orig = db_dat_sibling(proj_orig)
        if dat_orig.exists():
            return
        dat_live = db_dat_sibling(Path(entry["base"]))
        if not dat_live.is_file():
            return
        try:
            dat_orig.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dat_live, dat_orig)
        except Exception as exc:
            if log:
                log(f"  ⚠ could not snapshot {dat_orig.name}: {exc}")


    def _ensure_db_dat_snapshots(
        self, entries: list[dict], data_dir: Path, log=None
    ) -> None:
        """Backfill missing database ``.dat`` files in originals/."""
        for entry in entries:
            self._snapshot_db_dat_sibling(entry, data_dir, log)


    def _snapshot_originals(self, entries: list[dict], data_dir: Path, log) -> None:
        """Copy the pristine base binaries into originals/ (only when missing, so a
        good snapshot is never clobbered by a later extract of injected data)."""
        for entry in entries:
            if entry.get("kind") == "names":
                continue
            src = Path(entry["base"])
            dst = self._orig_base_for(entry, data_dir)
            if dst.exists():
                self._snapshot_db_dat_sibling(entry, data_dir, log)
                continue
            try:
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            except Exception as exc:
                log(f"  ⚠ could not snapshot original {src.name}: {exc}")
                continue
            self._snapshot_db_dat_sibling(entry, data_dir, log)


    def _ensure_originals(self, manifest: dict, log, progress=None, *, quiet: bool = False) -> None:
        """Make sure a pristine snapshot exists; if entries are missing it and the
        game still has its .wolf archives (packaging renames them to .wolf.bak),
        rebuild the snapshot by unpacking those archives into originals/."""
        emit = (lambda _msg: None) if quiet else log

        data_dir = Path(manifest["data_dir"])
        entries = manifest.get("entries", [])
        missing = [
            e for e in entries
            if e.get("kind") != "names" and not self._orig_base_for(e, data_dir).exists()
        ]
        if not missing:
            return

        root = Path(manifest.get("root") or self._game_root)
        rebuilt = wolf_originals.rebuild_originals_from_archives(
            root,
            self._originals_dir(),
            force=False,
            log_fn=None if quiet else log,
            progress_fn=progress,
        )
        if not rebuilt:
            emit(
                "  ⚠ No pristine originals and no usable .wolf archive baseline. "
                "Extract from an untranslated copy of the game in Step 1."
            )
            return
        self._ensure_db_dat_snapshots(entries, data_dir, None if quiet else log)


    def _restore_live_from_originals(
        self, entries: list[dict], data_dir: Path, log, *, quiet: bool = False
    ) -> None:
        """Copy pristine originals onto live Data/ binaries before names-inject.

        ``names-inject`` rewrites every DB pair, CommonEvent.dat, and every map.
        Resetting from ``wolf_json/originals/`` first keeps them on one baseline.
        """
        from util.wolfdawn import db_dat_sibling

        emit = (lambda _msg: None) if quiet else log
        restored = 0
        for entry in entries:
            if entry.get("kind") == "names":
                continue
            orig = self._orig_base_for(entry, data_dir)
            live = Path(entry["base"])
            if not orig.exists():
                emit(f"  ⚠ no pristine original for {entry['json']} — live file left as-is")
                continue
            try:
                if orig.is_dir():
                    if live.exists():
                        shutil.rmtree(live)
                    shutil.copytree(orig, live)
                else:
                    live.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(orig, live)
                    if entry.get("kind") == "db":
                        dat_orig = db_dat_sibling(orig)
                        dat_live = db_dat_sibling(live)
                        if dat_orig.is_file():
                            shutil.copy2(dat_orig, dat_live)
                restored += 1
            except Exception as exc:
                emit(f"  ⚠ could not restore {live.name} from originals: {exc}")
        if restored and not quiet:
            log(
                f"Restored {restored} live binary file(s) from {WORK_DIR_NAME}/originals/."
            )


    def _ensure_text_archives_unpacked(self, data_dir: Path, log, progress=None) -> bool:
        """Unpack BasicData/MapData archives when their binaries are not loose yet."""
        from util import wolfdawn

        archives = find_wolf_text_archives(self._game_root, data_dir)
        pending: list[Path] = []
        basic = data_dir / "BasicData"
        if "BasicData" in archives and not (basic / "CommonEvent.dat").is_file():
            pending.append(archives["BasicData"])
        if "MapData" in archives and not wolf_has_maps(data_dir):
            pending.append(archives["MapData"])
        if not pending:
            return True

        ok = True
        total = len(pending)
        for idx, arc in enumerate(pending):
            if progress:
                progress(idx, total, f"Unpacking {arc.name} ({idx + 1}/{total}) …")
            log(f"Unpacking {arc.name} …")

            def scoped_progress(current, _total, label, base=idx, archive=arc):
                if not progress:
                    return
                step = min(current, 1)
                detail = label or archive.name
                progress(base + step, total, detail)

            res = wolfdawn.unpack_all(
                [str(arc)],
                str(data_dir),
                log_fn=log,
                progress_fn=scoped_progress if progress else None,
                progress_total=1,
            )
            if not res.ok:
                log(f"  ⚠ unpack failed (exit {res.returncode})")
                ok = False
            elif progress:
                progress(idx + 1, total, f"Unpacked {arc.name}")
        return ok


    def _translated_path(self, json_name: str) -> Path | None:
        """Absolute path to ``translated/<json_name>`` when it exists."""
        p = self._tool_root() / "translated" / json_name
        return p if p.is_file() else None


    def _translated_or_source(self, json_name: str) -> Path | None:
        """Prefer translated/<name>; fall back to files/<name>."""
        root = self._tool_root()
        for sub in ("translated", "files"):
            p = root / sub / json_name
            if p.is_file():
                return p
        return None


    def _injectable_filenames(self, source_dir: Path | None = None) -> list[str]:
        """JSON files in *source_dir* (default translated/) the manifest can inject."""
        from util.wolfdawn import inject as wolf_inject

        manifest = self._read_manifest()
        if not manifest:
            return []
        root = source_dir if source_dir is not None else self._tool_root() / "translated"
        return wolf_inject.list_injectable(root, manifest.get("entries", []))


    def _sync_translated_json_to_wolf_json(
        self, json_name: str, game_json_dir: Path
    ) -> tuple[bool, str | None]:
        """Copy one translated/ (or files/) JSON into the game's wolf_json/ folder."""
        src = self._translated_or_source(json_name)
        if src is None:
            return False, "no translated copy"
        dest = game_json_dir / json_name
        try:
            if src.resolve() == dest.resolve():
                return True, None
        except Exception:
            pass
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return True, None
        except Exception as exc:
            return False, str(exc)


    def _sync_json_to_dir(
        self, json_name: str, source_dir: Path, dest_dir: Path
    ) -> tuple[bool, str | None]:
        """Copy one JSON from *source_dir* into *dest_dir* (e.g. files/ or translated/)."""
        src = source_dir / json_name
        if not src.is_file():
            return False, "source missing"
        dest = dest_dir / json_name
        try:
            if src.resolve() == dest.resolve():
                return True, None
        except Exception:
            pass
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return True, None
        except Exception as exc:
            return False, str(exc)


    def unpack_task(self, root, archives, log, progress=None):
        from collections import defaultdict

        from util import wolfdawn

        groups: dict[Path, list[Path]] = defaultdict(list)
        for arc in archives:
            groups[wolf_unpack_out_dir(root, arc)].append(arc)

        total = len(archives)
        done = 0
        for target, group in groups.items():
            log(f"Unpacking {len(group)} archive(s) into {target} …")
            res = wolfdawn.unpack_all(
                [str(a) for a in group],
                str(target),
                log_fn=log,
                progress_fn=(
                    (lambda c, _t, label, base=done: progress(base + min(c, 1), total, label))
                    if progress
                    else None
                ),
                progress_total=len(group),
            )
            done += len(group)
            if progress:
                progress(done, total, f"Unpacked {len(group)} archive(s)")
            if not res.ok:
                return False, f"unpack-all exited {res.returncode}"
        nested = wolf_nested_data_dir(root)
        if nested is not None and not wolf_repair_nested_data_dir(root):
            return False, f"Could not safely repair nested WOLF data at {nested}."
        return True, "Unpacked archives into Data/."


    def extract_task(self, data_dir, work_dir, game_root, supplement_maps, log, progress=None):
        from util import wolfdawn

        if not self._ensure_text_archives_unpacked(Path(data_dir), log, progress):
            return False, "Could not unpack text archives (see log)."

        layout = detect_wolf_layout(self._game_root)
        self._layout = layout
        basic = Path(layout["basic_data"]) if layout.get("basic_data") else Path(data_dir)
        maps_dir = wolf_maps_dir(data_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        originals_dir = self._originals_dir()

        # If the project has an archive baseline, materialize it before
        # extraction. A full re-extract refreshes an existing snapshot from
        # the archive so previously injected live Data cannot become source.
        archive_baseline = wolf_originals.find_data_archives(
            Path(game_root), Path(data_dir)
        )
        refresh_existing = (
            not supplement_maps
            and bool(archive_baseline)
            and any(work_dir.glob("*.json"))
        )
        if not originals_dir.is_dir() or refresh_existing:
            wolf_originals.rebuild_originals_from_archives(
                Path(game_root),
                originals_dir,
                force=refresh_existing,
                log_fn=log,
                progress_fn=progress,
            )

        existing_manifest = self._read_manifest() if supplement_maps else None
        existing_entries = list(existing_manifest.get("entries", [])) if existing_manifest else []
        existing_json = {e["json"] for e in existing_entries if e.get("json")}

        manifest_entries: list[dict] = (
            existing_entries.copy() if supplement_maps else []
        )

        def _extract_one(base: Path, out_name: str, kind: str):
            if supplement_maps and out_name in existing_json:
                return
            out = work_dir / out_name
            source_base = wolf_originals.preferred_extract_path(
                base, Path(data_dir), originals_dir
            )
            source_note = (
                " from pristine originals" if source_base != base else ""
            )
            log(f"Extracting {base.name}{source_note} …")
            res = wolfdawn.strings_extract(
                str(source_base), str(out), log_fn=log
            )
            if res.ok and out.is_file():
                manifest_entries.append({"json": out_name, "base": str(base), "kind": kind})
            else:
                log(f"  ⚠ skipped {base.name} (exit {res.returncode})")

        if not supplement_maps:
            ce = basic / "CommonEvent.dat"
            if ce.is_file():
                _extract_one(ce, "CommonEvent.dat.json", "common")
            for stem in ("DataBase", "CDataBase", "SysDatabase"):
                proj = basic / f"{stem}.project"
                if proj.is_file():
                    _extract_one(proj, f"{stem}.project.json", "db")
                    if stem == "CDataBase":
                        from util.wolfdawn import cdb_context

                        source_proj = wolf_originals.preferred_extract_path(
                            proj, Path(data_dir), originals_dir
                        )
                        log("Indexing CDB lookup values for translation context …")
                        if not cdb_context.write_sidecar(
                            source_proj,
                            work_dir / cdb_context.SIDECAR_NAME,
                            log_fn=log,
                        ):
                            log("  ⚠ CDB context index could not be created")
            gd = basic / "Game.dat"
            if gd.is_file():
                _extract_one(gd, "Game.dat.json", "gamedat")

        for mps in sorted(maps_dir.glob("*.mps")):
            _extract_one(mps, f"{mps.name}.json", "map")

        if not supplement_maps:
            evtext = Path(data_dir) / "Evtext"
            if evtext.is_dir() and any(evtext.glob("*.txt")):
                out = work_dir / "Evtext.json"
                source_evtext = wolf_originals.preferred_extract_path(
                    evtext, Path(data_dir), originals_dir
                )
                log("Extracting Evtext/ …")
                res = wolfdawn.strings_extract(
                    str(source_evtext), str(out), log_fn=log
                )
                if res.ok and out.is_file():
                    manifest_entries.append({"json": "Evtext.json", "base": str(evtext), "kind": "txt-dir"})

            log("Extracting name list …")
            names_out = work_dir / NAMES_JSON
            names_base = (
                originals_dir
                if any(
                    (originals_dir / name).exists()
                    for name in ("BasicData", "MapData")
                )
                else Path(data_dir)
            )
            res = wolfdawn.names_extract(
                str(names_base), str(names_out), log_fn=log
            )
            if res.ok and names_out.is_file():
                manifest_entries.append({"json": NAMES_JSON, "base": str(data_dir), "kind": "names"})
        elif any(e.get("kind") == "map" for e in manifest_entries):
            log("Refreshing name list (maps were added) …")
            names_out = work_dir / NAMES_JSON
            names_base = (
                originals_dir
                if any(
                    (originals_dir / name).exists()
                    for name in ("BasicData", "MapData")
                )
                else Path(data_dir)
            )
            res = wolfdawn.names_extract(
                str(names_base), str(names_out), log_fn=log
            )
            if res.ok and names_out.is_file():
                manifest_entries = [
                    e for e in manifest_entries if e.get("json") != NAMES_JSON
                ]
                manifest_entries.append({"json": NAMES_JSON, "base": str(data_dir), "kind": "names"})

        new_entries = [
            e for e in manifest_entries
            if supplement_maps and e.get("json") not in existing_json
        ] if supplement_maps else manifest_entries

        if not manifest_entries:
            return False, "Nothing was extracted. Check the Data/ folder layout."
        if supplement_maps and not new_entries:
            return True, f"No new map files to extract in {WORK_DIR_NAME}/."

        manifest = {
            "root": game_root,
            "data_dir": str(data_dir),
            "entries": manifest_entries,
        }
        (work_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        snapshot_entries = new_entries if supplement_maps else manifest_entries
        self._snapshot_originals(snapshot_entries, Path(data_dir), log)
        map_count = sum(1 for e in manifest_entries if e.get("kind") == "map")
        if supplement_maps:
            added = sum(1 for e in new_entries if e.get("kind") == "map")
            return True, (
                f"Added {added} map file(s) ({map_count} total in {WORK_DIR_NAME}/). "
                "Import the checked files from Step 1."
            )
        return True, (
            f"Extracted {len(manifest_entries)} document(s) into {WORK_DIR_NAME}/ "
            f"({map_count} map(s)). Import the checked files from Step 1."
        )


    def inject_task(self, manifest, selected, en_punct, game_json_dir, files_dir, translated_dir, inject_dir, sync_to_wolf_json, sync_to_files, sync_to_translated, inject_state, log, progress=None):
        from util.wolfdawn import inject as wolf_inject

        entries = manifest["entries"]
        data_dir_path = Path(manifest["data_dir"])
        game_root = Path(manifest.get("root") or self._game_root)
        originals_dir = game_root / WORK_DIR_NAME / "originals"

        self._ensure_originals(manifest, log, progress, quiet=True)

        log(f"Inject source: {inject_dir}")
        # allow_code_drift=False: inject still auto-passes it for \\f shrink.
        report = wolf_inject.inject_selected(
            sorted(selected),
            manifest_entries=entries,
            data_dir=data_dir_path,
            originals_dir=originals_dir,
            translated_dir=inject_dir,
            game_root=game_root,
            allow_code_drift=False,
            en_punct=en_punct,
            log_fn=log,
        )

        if sync_to_wolf_json and game_json_dir is not None:
            for json_name in sorted(selected):
                ok, err = self._sync_translated_json_to_wolf_json(
                    json_name, game_json_dir
                )
                if not ok:
                    report.sync_failures.append(
                        (json_name, err or "unknown error")
                    )
                    log(f"  ✗ sync {json_name}: {err}")

        for label, enabled, dest in (
            ("files/", sync_to_files, files_dir),
            ("translated/", sync_to_translated, translated_dir),
        ):
            if not enabled:
                continue
            synced = 0
            for json_name in sorted(selected):
                ok, err = self._sync_json_to_dir(
                    json_name, inject_dir, dest
                )
                if not ok:
                    report.sync_failures.append(
                        (json_name, f"{label}: {err or 'unknown error'}")
                    )
                    log(f"  ✗ sync {label}{json_name}: {err}")
                else:
                    synced += 1
            if synced:
                log(f"Synced {synced} file(s) → {label}")

        dialog = wolf_inject.format_report_dialog(report)
        status = wolf_inject.format_report_status(report)
        inject_state["dialog"] = dialog
        inject_state["report"] = report
        inject_state["selected"] = set(selected)
        return report.ok, status


    def precheck_task(self, manifest, selected, en_punct, state, log, progress=None):
        from util import wolfdawn
        from util.wolfdawn import inject_precheck as wolf_pre
        from util.wolfdawn import names as wolf_names

        translated = self._tool_root() / "translated"
        name_notes: list[str] = []

        # Name hygiene first (same work the old Step 7 buttons did).
        if (translated / "names.json").is_file():
            report_names = wolf_names.reconcile_translated_dir(
                translated, dry_run=False
            )
            reconcile_msg = wolf_names.format_reconcile_summary(report_names)
            log(reconcile_msg)
            detail_limit = 6
            for change in report_names.changes[:detail_limit]:
                log(
                    f"  {change.json_file}: {change.source!r} "
                    f"{change.old_text!r} → {change.new_text!r} ({change.reason})"
                )
            if len(report_names.changes) > detail_limit:
                log(
                    f"  … {len(report_names.changes) - detail_limit} more name "
                    "change(s); see translated/names.json for details."
                )
            name_notes.append(reconcile_msg)
        else:
            log("Name reconcile skipped (no translated/names.json).")

        json_files = []
        for entry in manifest["entries"]:
            p = self._translated_or_source(entry["json"])
            if p:
                json_files.append(str(p))
        if json_files:
            # The CLI can print thousands of individual references. Keep the
            # activity panel useful and show only a short failure excerpt.
            check = wolfdawn.names_check(json_files, log_fn=None)
            if check.returncode == 0:
                name_notes.append("Name usage is consistent across files.")
            else:
                note = "names-check reported inconsistencies."
                name_notes.append(note)
                log(f"⚠ {note}")
                details = [
                    line.strip()
                    for line in (check.stderr or check.stdout or "").splitlines()
                    if line.strip()
                ]
                for line in details[:6]:
                    log(f"  {line}")
                if len(details) > 6:
                    log(f"  … {len(details) - 6} more detail line(s) hidden.")
        else:
            name_notes.append("names-check skipped (no JSON found).")

        entries = manifest["entries"]
        data_dir_path = Path(manifest["data_dir"])
        game_root = Path(manifest.get("root") or self._game_root)
        originals_dir = game_root / WORK_DIR_NAME / "originals"
        self._ensure_originals(manifest, log, progress, quiet=True)
        # Font-size drift from wrap/names-wrap is auto-allowed inside precheck.
        report = wolf_pre.precheck_selected(
            sorted(selected),
            manifest_entries=entries,
            data_dir=data_dir_path,
            originals_dir=originals_dir,
            translated_dir=translated,
            allow_code_drift=False,
            en_punct=en_punct,
            log_fn=log,
        )
        state["report"] = report
        state["name_notes"] = name_notes
        summary = wolf_pre.format_precheck_summary(report)
        if name_notes:
            summary = " · ".join(name_notes) + "\n" + summary
        return True, summary


    def layout_restore_task(self, paths, log, progress=None):
        from util import wolfdawn

        log(f"layout-restore: {len(paths)} file(s)…")
        res = wolfdawn.layout_restore(paths, log_fn=log)
        for line in (res.stdout or "").splitlines():
            if line.strip():
                log(line)
        fixed = wolfdawn.parse_layout_restore_counts(res.stdout, res.stderr)
        if not res.ok:
            err = (res.stderr or res.stdout or "").strip() or f"exit {res.returncode}"
            return False, f"layout-restore failed: {err}"
        n = fixed if fixed is not None else 0
        return True, f"layout-restore fixed {n} line(s) across {len(paths)} file(s)."


    def loose_task(self, archives, log, progress=None):
        renamed = 0
        for arc in archives:
            bak = arc.with_suffix(arc.suffix + ".bak")
            if bak.exists():
                log(f"  {bak.name} already exists — leaving {arc.name} in place")
                continue
            arc.rename(bak)
            log(f"  {arc.name} → {bak.name}")
            renamed += 1
        return True, f"Backed up {renamed} archive(s); the game now runs from the loose Data/ folder."


    def repack_task(self, data_dir, output, like, log, progress=None):
        from util import wolfdawn

        log(f"Repacking {data_dir} → {output} …")
        res = wolfdawn.pack(str(data_dir), str(output), like=str(like) if like else None, log_fn=log)
        if not res.ok:
            return False, f"pack exited {res.returncode}"
        return True, f"Wrote {output.name}."


    def saves_task(self, save_path, game_dat, log, progress=None):
        from util import wolfdawn

        if not game_dat or not game_dat.is_file():
            return False, "Game.dat not found — extract/unpack the game first."
        translations = self._tool_root() / "translated"
        tl_arg = [str(translations)] if translations.is_dir() else None
        log(f"Updating saves in {save_path} …")
        res = wolfdawn.save_update(
            save_path, game=str(game_dat), translations=tl_arg, log_fn=log,
        )
        if not res.ok:
            return False, f"save-update exited {res.returncode}"
        return True, "Saves updated (originals backed up)."


class WolfWorkflow(WolfWorkflowCore):
    def __init__(self, game_root, workspace_root):
        self._game_root = str(game_root)
        self._workspace_root = Path(workspace_root)
