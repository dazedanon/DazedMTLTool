import { useEffect, useRef, useState } from "react";
import { api } from "./bridge";
import { saveBeforeClose } from "./lifecycle";
import type { VersionRecord, VersionState, VersionValues } from "./types";

const actions: Record<string, { label: string; detail: string }> = {
  bootstrap: {
    label: "Create version baselines",
    detail:
      "Record the clean original and current translation in local Git branches. Existing translation files are preserved; normal workflow mode formats supported text files.",
  },
  register: {
    label: "Register current branch",
    detail:
      "Use the current branch as the translation branch for future official updates.",
  },
  metadata: {
    label: "Record version labels",
    detail:
      "Add missing baseline version labels with commits that preserve the existing file trees.",
  },
  checkout: {
    label: "Switch to translation branch",
    detail: "Check out this repository’s registered translation branch.",
  },
  apply: {
    label: "Apply reviewed update",
    detail:
      "Apply the reviewed official changes to the translation. Official files win conflicts; affected translations may need updating. Ignored runtime assets are synchronized using the reviewed manifest.",
  },
  registered: {
    label: "Apply registered original",
    detail:
      "Apply the original version already registered in Git and finish any pending asset synchronization.",
  },
  continue: {
    label: "Continue with official files",
    detail:
      "Resolve pending conflicts using the official files and finish the update.",
  },
  abort: {
    label: "Abort pending cherry-pick",
    detail:
      "Restore the translation to its state before the pending cherry-pick. The new official baseline remains registered for a later retry.",
  },
};

export function VersionWorkspace({
  visible,
  requested,
}: {
  visible: boolean;
  requested?: { source: string; key: number };
}) {
  const [state, setState] = useState<VersionState | null>(null);
  const [source, setSource] = useState("");
  const [values, setValues] = useState<VersionValues | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const pending = useRef({
    record: null as VersionRecord | null,
    values: null as VersionValues | null,
    version: 0,
    saved: 0,
  });
  const queue = useRef(Promise.resolve());
  const copyJob = useRef("");
  const generation = useRef(0);
  const report = (e: unknown) =>
    setError(e instanceof Error ? e.message : String(e));
  function flush() {
    const work = queue.current
      .catch(() => {})
      .then(async () => {
        const p = pending.current;
        while (p.record && p.values && p.saved !== p.version) {
          const version = p.version;
          p.record = await api.versionSave({
            project_id: p.record.id,
            revision: p.record.revision,
            values: p.values,
          });
          p.saved = version;
        }
      });
    queue.current = work;
    return work;
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  function adopt(next: VersionState) {
    setState(next);
    setSource(next.project?.source || "");
    setValues(next.project?.values || null);
    setConfirmation("");
    pending.current = {
      record: next.project,
      values: next.project?.values || null,
      version: 0,
      saved: 0,
    };
  }
  async function refresh() {
    const ticket = generation.current;
    const next = await api.versionState(pending.current.record?.id);
    if (ticket === generation.current) setState(next);
  }
  async function action(name: string) {
    await flush();
    const record = pending.current.record!;
    const job = await api.versionAction({
      project_id: record.id,
      revision: record.revision,
      action: name,
      preview_job: state?.preview?.job_id,
    });
    if (name === "post_update") copyJob.current = job.id;
    setConfirmation("");
    await refresh();
  }
  async function open(folder: string, preserve = false) {
    await flush();
    generation.current++;
    const next = await api.versionOpen(folder, preserve);
    adopt(next);
    const record = next.project!;
    await api.versionAction({
      project_id: record.id,
      revision: record.revision,
      action: "status",
    });
    await refresh();
  }
  useEffect(() => {
    const ticket = ++generation.current;
    if (requested) run(() => open(requested.source, true));
    else
      api
        .versionState()
        .then((next) => {
          if (ticket === generation.current) adopt(next);
        })
        .catch(report);
  }, [requested?.key]);
  useEffect(() => saveBeforeClose(flush), []);
  useEffect(() => {
    const timer = setTimeout(() => flush().catch(report), 400);
    return () => clearTimeout(timer);
  }, [values]);
  useEffect(() => {
    if (!visible || !state?.active) return;
    const timer = setInterval(() => refresh().catch(report), 200);
    return () => clearInterval(timer);
  }, [visible, state?.active]);
  useEffect(() => {
    const job = state?.jobs.find((j) => j.id === copyJob.current);
    if (!job || job.status === "running") return;
    copyJob.current = "";
    if (job.status === "complete" && typeof job.result?.prompt === "string")
      api
        .copyText(job.result.prompt)
        .then(() => setNotice("Post-update translation handoff copied."))
        .catch(report);
    else setError(job.message);
  }, [state?.jobs]);
  function update(change: Partial<VersionValues>) {
    const next = { ...pending.current.values!, ...change };
    pending.current.values = next;
    pending.current.version++;
    setValues(next);
    setConfirmation("");
    setState((s) => (s ? { ...s, preview: null } : s));
  }
  const status = state?.status;
  const project = state?.project;
  const disabled = busy || !!state?.active;
  const preview = state?.preview;
  function folderField(
    key: "original" | "official" | "baseline",
    label: string,
  ) {
    return (
      <label>
        {label}
        <div className="actions">
          <input
            aria-label={label}
            value={values![key]}
            onChange={(e) => update({ [key]: e.target.value })}
          />
          <button
            disabled={disabled}
            onClick={() =>
              run(async () => {
                const path = await api.chooseFolder();
                if (path) update({ [key]: path });
              })
            }
          >
            Browse {key === "official" ? "update" : key}
          </button>
        </div>
      </label>
    );
  }
  const canCopy =
    status?.applied_update_version &&
    !status.pending_cherry_pick &&
    !status.asset_sync_pending &&
    status.current_branch === status.translation_branch;
  return (
    <section className="len-workspace version-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Local version tracking</span>
          <h1>Git version updates</h1>
          <p>
            Compare an official release with the saved Japanese baseline, then
            apply its changes to your translation.
          </p>
        </div>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      <div className="workflow-card">
        <h2>Translation folder</h2>
        <div className="actions">
          <input
            aria-label="Version game folder"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
          <button
            disabled={disabled}
            onClick={() =>
              run(async () => {
                const path = await api.chooseFolder();
                if (path) await open(path);
              })
            }
          >
            Browse game
          </button>
          <button
            disabled={disabled || !source.trim()}
            onClick={() => run(() => open(source))}
          >
            Inspect game
          </button>
        </div>
        {!!state?.projects.length && (
          <label>
            Recent projects
            <select
              value={project?.source || ""}
              disabled={disabled}
              onChange={(e) => run(() => open(e.target.value))}
            >
              <option value="" disabled>
                Select a game
              </option>
              {state.projects.map((p) => (
                <option key={p.id} value={p.source}>
                  {p.source}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {project && values && (
        <>
          <div className="workflow-card">
            <div className="actions">
              <h2>Repository status</h2>
              <button
                disabled={disabled}
                onClick={() => run(() => action("status"))}
              >
                Rescan repository
              </button>
            </div>
            {status ? (
              <>
                <dl className="version-status">
                  <dt>Repository</dt>
                  <dd>{status.repo_root || "Not initialized"}</dd>
                  <dt>Current branch</dt>
                  <dd>{status.current_branch || "None"}</dd>
                  <dt>Translation branch</dt>
                  <dd>{status.translation_branch || "Not registered"}</dd>
                  <dt>Original version</dt>
                  <dd>{status.original_version || "Not recorded"}</dd>
                  <dt>Translation version</dt>
                  <dd>{status.translation_version || "Not recorded"}</dd>
                  <dt>Working tree</dt>
                  <dd>
                    {status.worktree_clean ? "Clean" : "Uncommitted changes"}
                  </dd>
                  <dt>Runtime assets</dt>
                  <dd>
                    {status.asset_sync_pending
                      ? "Synchronization pending"
                      : status.asset_manifest_available
                        ? "Baseline available"
                        : "Baseline not recorded"}
                  </dd>
                </dl>
                {!status.git_available && (
                  <p role="alert">
                    Install Git and make it available on PATH to use version
                    tracking.
                  </p>
                )}
                {status.repo_root && !status.worktree_clean && (
                  <p className="warning-banner">
                    Review and commit current translation changes before
                    previewing an official update.
                  </p>
                )}
                <div className="actions">
                  {status.translation_exists &&
                    status.current_branch !== status.translation_branch && (
                      <button
                        disabled={disabled}
                        onClick={() => setConfirmation("checkout")}
                      >
                        Switch to translation branch
                      </button>
                    )}
                  {status.original_exists &&
                    status.translation_exists &&
                    (status.asset_sync_pending ||
                      status.original_version !==
                        status.translation_version) && (
                      <button
                        disabled={disabled}
                        onClick={() => setConfirmation("registered")}
                      >
                        Apply registered original
                      </button>
                    )}
                </div>
              </>
            ) : (
              <p>Inspecting repository…</p>
            )}
          </div>
          {(!status?.original_exists ||
            !status.translation_exists ||
            !status.original_version ||
            !status.translation_version) && (
            <div className="workflow-card">
              <h2>Set up version tracking</h2>
              <fieldset disabled={disabled}>
                {!status?.original_exists && (
                  <>
                    {folderField("original", "Matching clean original folder")}
                    <label>
                      <input
                        type="checkbox"
                        checked={values.untranslated}
                        onChange={(e) =>
                          update({ untranslated: e.target.checked })
                        }
                      />
                      The selected game is still untranslated; use it as the
                      original when no separate folder is selected.
                    </label>
                  </>
                )}
                <label>
                  Current game version
                  <input
                    aria-label="Current game version"
                    value={values.original_version}
                    onChange={(e) =>
                      update({ original_version: e.target.value })
                    }
                    placeholder="1.00"
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={values.preserve_game_files}
                    onChange={(e) =>
                      update({ preserve_game_files: e.target.checked })
                    }
                  />
                  Preserve native game bytes and local Len work
                </label>
              </fieldset>
              <p className="muted">
                Len projects automatically preserve native bytes. Version
                tracking creates local commits; it does not create remotes or
                publish the game.
              </p>
              <button
                disabled={disabled}
                onClick={() =>
                  setConfirmation(
                    !status?.original_exists
                      ? "bootstrap"
                      : !status.translation_exists
                        ? "register"
                        : "metadata",
                  )
                }
              >
                {!status?.original_exists
                  ? "Create version baselines"
                  : !status.translation_exists
                    ? "Register current branch"
                    : "Record version labels"}
              </button>
            </div>
          )}
          {status?.original_exists && status.translation_exists && (
            <div className="workflow-card">
              <h2>Official update</h2>
              <fieldset disabled={disabled}>
                {folderField("official", "New official game or patch folder")}
                <label>
                  New official version
                  <input
                    aria-label="New official version"
                    value={values.version}
                    onChange={(e) => update({ version: e.target.value })}
                    placeholder="1.01"
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={values.patch_overlay}
                    onChange={(e) =>
                      update({ patch_overlay: e.target.checked })
                    }
                  />
                  Copy-over patch: preserve files omitted from this folder
                </label>
                {(!status.asset_manifest_available ||
                  status.asset_baseline_repair_needed ||
                  values.baseline) && (
                  <>
                    {folderField(
                      "baseline",
                      "Previous clean official folder (optional)",
                    )}
                    <p className="muted">
                      Use the previous release for an exact asset comparison.
                      Leave blank to use the current game’s existing runtime
                      assets as the starting baseline.
                    </p>
                  </>
                )}
              </fieldset>
              <button
                disabled={disabled || !status.ready}
                onClick={() => run(() => action("preview"))}
              >
                Preview official update
              </button>
            </div>
          )}
          {preview && (
            <div className="workflow-card">
              <h2>Review version {preview.version}</h2>
              <p>
                {preview.patch_overlay ? "Copy-over patch" : "Full release"} ·{" "}
                {preview.added_paths.length} added ·{" "}
                {preview.modified_paths.length} modified ·{" "}
                {preview.deleted_paths.length} deleted ·{" "}
                {preview.overlapping_paths.length} overlap translated files
              </p>
              <p className="muted">
                {preview.content_change_expected
                  ? "Review text, image and runtime asset changes before applying."
                  : "These changes are already present. Applying records the version."}
              </p>
              <div className="version-table">
                <table>
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>Change</th>
                      <th>Lines + / −</th>
                      <th>Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.file_changes.map((row) => (
                      <tr key={row.path}>
                        <td>{row.path}</td>
                        <td>
                          {row.change}
                          {row.translation_changed ? " · translated" : ""}
                        </td>
                        <td>
                          {row.added_lines ?? "—"} / {row.deleted_lines ?? "—"}
                        </td>
                        <td>{row.result}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {preview.image_changes.length > 0 && (
                <details open>
                  <summary>
                    Image changes ({preview.image_changes.length})
                  </summary>
                  {preview.image_changes.map((row) => (
                    <p
                      key={row.path}
                      className={row.warning ? "warning-banner" : ""}
                    >
                      {row.path} · {row.change} ·{" "}
                      {row.tracked ? "Git tracked" : "Runtime asset"} ·{" "}
                      {row.result}
                    </p>
                  ))}
                </details>
              )}
              {preview.external_changes.length > 0 && (
                <details>
                  <summary>
                    Runtime asset changes ({preview.external_changes.length})
                  </summary>
                  {preview.external_changes.map((row) => (
                    <p key={row.path}>
                      {row.path} · {row.category} · {row.change} · {row.result}
                    </p>
                  ))}
                </details>
              )}
              {(
                [
                  "overlapping_paths",
                  "already_present_paths",
                  "formatted_json_paths",
                  "json_warnings",
                  "ignored_paths",
                  "preserved_translation_asset_paths",
                ] as const
              ).map(
                (key) =>
                  preview[key].length > 0 && (
                    <details key={key}>
                      <summary>
                        {key.replaceAll("_", " ")} ({preview[key].length})
                      </summary>
                      <pre>{preview[key].join("\n")}</pre>
                    </details>
                  ),
              )}
              <button
                className="primary"
                disabled={disabled || !status?.ready}
                onClick={() => setConfirmation("apply")}
              >
                Apply reviewed update
              </button>
            </div>
          )}
          {status?.pending_cherry_pick && (
            <div className="workflow-card">
              <h2>Recover pending update</h2>
              <pre>
                {status.conflicts.join("\n") ||
                  "Cherry-pick pending without unresolved paths."}
              </pre>
              <div className="actions">
                <button
                  disabled={disabled}
                  onClick={() => setConfirmation("continue")}
                >
                  Continue with official files
                </button>
                <button
                  disabled={disabled}
                  onClick={() => setConfirmation("abort")}
                >
                  Abort pending cherry-pick
                </button>
              </div>
            </div>
          )}
          {canCopy && (
            <div className="workflow-card">
              <h2>Translate the applied update</h2>
              <p>
                Version {status.applied_update_version} is applied. Copy the
                existing game-specific skill to translate and verify its
                changes.
              </p>
              <button
                disabled={disabled}
                onClick={() => run(() => action("post_update"))}
              >
                Copy post-update handoff
              </button>
            </div>
          )}
          {confirmation && (
            <div
              className="workflow-confirm"
              role="dialog"
              aria-label="Confirm Git action"
            >
              <h2>{actions[confirmation].label}</h2>
              <p>{actions[confirmation].detail}</p>
              <p>
                <strong>{project.source}</strong>
              </p>
              {confirmation === "apply" && (
                <p>
                  Official: {values.official} · Version {values.version}
                </p>
              )}
              {confirmation === "bootstrap" && (
                <p>
                  Original: {values.original || project.source} · Version{" "}
                  {values.original_version}
                </p>
              )}
              <div className="actions">
                <button disabled={disabled} onClick={() => setConfirmation("")}>
                  Cancel
                </button>
                <button
                  className="primary"
                  disabled={disabled}
                  onClick={() => run(() => action(confirmation))}
                >
                  Confirm Git action
                </button>
              </div>
            </div>
          )}
          {!!state.jobs.length && (
            <div className="workflow-card">
              <h2>Activity</h2>
              {state.jobs.slice(0, 8).map((job) => (
                <details
                  key={job.id}
                  open={job.id === state.active || job.status === "failed"}
                >
                  <summary>
                    {job.label} · {job.status}
                  </summary>
                  <p>{job.message}</p>
                  <pre>{job.log.join("\n")}</pre>
                  {job.result?.result ? (
                    <pre>{JSON.stringify(job.result.result, null, 2)}</pre>
                  ) : null}
                </details>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
