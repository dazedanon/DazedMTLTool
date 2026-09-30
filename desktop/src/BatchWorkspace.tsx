import React, { useEffect, useState } from "react";
import { api } from "./bridge";
import type { BatchState, BatchRow } from "./types";

const actions: Record<string, { label: string; detail: string }> = {
  import: {
    label: "Import legacy inputs",
    detail:
      "Copy the recorded inputs and instructions into an isolated manual run. Unsubmitted queues stay linked to their original folder and submission lock; keep that folder available. Submitted runs copy their recovery files. Select the original engine and keep its inputs unchanged.",
  },
  bind: {
    label: "Record original credential",
    detail:
      "Save this credential name for the selected legacy batch. Choose the account that submitted it. The secret stays in your desktop profile; this action makes no provider request.",
  },
  refresh: {
    label: "Refresh provider status",
    detail: "Retrieve status using this batch’s saved credential and endpoint.",
  },
  cancel: {
    label: "Cancel provider batch",
    detail:
      "Ask the provider to cancel this batch. Work already processed may still be billed. Refresh afterward to check completion.",
  },
  usage: {
    label: "Fetch billed usage",
    detail:
      "Read provider results and calculate usage with the shared pricing configuration.",
  },
  download: {
    label: "Redownload results",
    detail:
      "Download the complete saved batch group into its original run folder. Existing ownership checks prevent mixing results from another run.",
  },
  activate: {
    label: "Prepare recovery",
    detail:
      "Restore the saved group’s active state. This can download completed results. Review the next step before continuing the translation engine.",
  },
};
const rowKey = (row: BatchRow) => row.source_id + "/" + row.id;
export default function BatchWorkspace({
  visible,
  onNavigate,
}: {
  visible: boolean;
  onNavigate: (page: string) => void;
}) {
  const [state, setState] = useState<BatchState | null>(null);
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [legacyPath, setLegacyPath] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [credential, setCredential] = useState("");
  const [engine, setEngine] = useState("RPG Maker MV/MZ");
  const refresh = async () => setState(await api.batchState());
  const report = (e: unknown) =>
    setError(e instanceof Error ? e.message : String(e));
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (visible) refresh().catch(report);
  }, [visible]);
  useEffect(() => {
    if (!visible || !state?.active) return;
    const timer = setInterval(() => refresh().catch(report), 500);
    return () => clearInterval(timer);
  }, [visible, state?.active]);
  const row = state?.rows.find((r) => rowKey(r) === selected);
  const origin = state?.sources.find((s) => s.id === row?.source_id);
  const disabled = busy || !!state?.active;
  const rows =
    state?.rows.filter(
      (r) =>
        (!status || r.status === status) &&
        (!source || r.source_id === source) &&
        `${r.id} ${r.model} ${r.provider} ${r.key_name} ${(r.file_set || []).join(" ")}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    ) || [];
  const prepared = state?.jobs.find(
    (job) =>
      ["activate", "profile"].includes(job.action) &&
      job.status === "complete" &&
      job.result?.batch_id === row?.id &&
      job.project_id === "batch:" + row?.source_id,
  );
  const profile = prepared?.result?.profile_confirmation as {
    config: Record<string, string | number | boolean>;
    enabled_plugins_357: string[];
    enabled_patterns_355655: string[];
  } | null;
  return (
    <section className="len-workspace batch-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Saved provider jobs</span>
          <h1>Batch history</h1>
          <p>
            Track submissions, download results and resume the original
            translation run.
          </p>
        </div>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      {!state?.allow_providers && (
        <p className="notice">
          Provider operations are disabled for this session. Saved history can
          be inspected locally.
        </p>
      )}
      <div className="workflow-card">
        <label>
          Legacy run folder
          <input
            value={legacyPath}
            onChange={(e) => setLegacyPath(e.target.value)}
            placeholder="Original tool or batch run folder"
          />
        </label>
        <div className="actions">
          <button disabled={disabled} onClick={() => run(refresh)}>
            Reload local history
          </button>
          <button
            disabled={disabled}
            onClick={() =>
              run(async () => {
                const path = legacyPath.trim() || (await api.chooseFolder());
                if (path) setState(await api.batchRegister(path));
              })
            }
          >
            Add legacy run folder
          </button>
          <button onClick={() => onNavigate("manual")}>Manual engines</button>
        </div>
        <div className="form-grid">
          <label>
            Search batches
            <input value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <label>
            Run folder
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">All saved runs</option>
              {state?.sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Batch status
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {[...new Set(state?.rows.map((r) => r.status))]
                .sort()
                .map((s) => (
                  <option key={s}>{s}</option>
                ))}
            </select>
          </label>
        </div>
        {state?.errors.map((e) => (
          <p key={e.source_id} role="alert">
            {e.message}
          </p>
        ))}
        <div className="version-table">
          <table>
            <thead>
              <tr>
                <th>Batch</th>
                <th>Provider / model</th>
                <th>Status</th>
                <th>Requests</th>
                <th>Actual cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={rowKey(r)} aria-selected={selected === rowKey(r)}>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => {
                        setSelected(rowKey(r));
                        setConfirmation("");
                      }}
                    >
                      {r.id}
                    </button>
                    <small>{r.created_at}</small>
                  </td>
                  <td>
                    {r.provider} · {r.model}
                    <small>
                      {r.workflow === "evaluation"
                        ? "Evaluation"
                        : "Translation"}
                    </small>
                  </td>
                  <td>
                    {r.status}
                    <small>{r.api_status}</small>
                  </td>
                  <td>{r.request_count ?? "—"}</td>
                  <td>
                    {r.actual_cost == null
                      ? "—"
                      : `$${r.actual_cost.toFixed(5)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <p className="muted">
            No saved batches match these filters. Submitted manual runs appear
            here automatically.
          </p>
        )}
      </div>
      {row && (
        <div className="workflow-card">
          <h2>{row.id}</h2>
          <p>{origin?.root}</p>
          {origin?.plan_root && origin.plan_root !== origin.root && (
            <p className="notice">
              This queue is linked to its original folder. Keep it available;
              both applications share its saved submissions.
            </p>
          )}
          <p>
            Saved credential: {row.key_name || "Not recorded"} · Endpoint:{" "}
            {row.endpoint || "Provider default"}
          </p>
          {row.notes && <p>{row.notes}</p>}
          {!row.key_name && (
            <div className="actions">
              <label>
                Original credential
                <select
                  value={credential}
                  onChange={(e) => setCredential(e.target.value)}
                >
                  <option value="">Select original account</option>
                  {state?.credentials.map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
              </label>
              <button
                disabled={disabled || !credential}
                onClick={() => setConfirmation("bind")}
              >
                Record original credential
              </button>
            </div>
          )}
          <div className="actions">
            {Object.entries(actions)
              .filter(([name]) => !["bind", "import"].includes(name))
              .map(([name, action]) => (
                <button
                  key={name}
                  disabled={
                    disabled ||
                    !state?.allow_providers ||
                    (row.local_queue && name !== "activate") ||
                    (row.workflow === "evaluation" &&
                      ["download", "activate", "usage"].includes(name)) ||
                    (name === "activate" && !origin?.job_id)
                  }
                  onClick={() => setConfirmation(name)}
                >
                  {action.label}
                </button>
              ))}
          </div>
          {row.workflow === "evaluation" && (
            <p className="muted">
              Collect evaluation results through Translation evaluation.
            </p>
          )}
          {!origin?.job_id && (
            <div className="actions">
              <label>
                Original translation engine
                <select
                  value={engine}
                  onChange={(e) => setEngine(e.target.value)}
                >
                  {state?.engines.map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
              </label>
              <button
                disabled={
                  disabled || !row.key_name || row.workflow === "evaluation"
                }
                onClick={() => setConfirmation("import")}
              >
                Import legacy inputs
              </button>
            </div>
          )}
          <details>
            <summary>Files, request counts and cost details</summary>
            <pre>
              {JSON.stringify(
                {
                  files: row.file_set,
                  counts: row.request_counts,
                  estimate: row.cost_estimate,
                  usage: row.usage,
                },
                null,
                2,
              )}
            </pre>
          </details>
          {prepared && (
            <div className="notice">
              <p>{prepared.message}</p>
              {profile && (
                <div>
                  <h3>Confirm original RPG Maker settings</h3>
                  <p>
                    This legacy batch has no saved code profile. Review the
                    settings frozen when its inputs were imported and confirm
                    they match the original collect pass. If they differ,
                    restore the original installation’s settings and import the
                    run again before resuming.
                  </p>
                  <p>
                    Enabled codes:{" "}
                    {Object.entries(profile.config)
                      .filter(
                        ([key, value]) =>
                          key.startsWith("CODE") && value === true,
                      )
                      .map(([key]) => key)
                      .join(", ") || "None"}
                  </p>
                  <details>
                    <summary>
                      All frozen code, plugin and pattern settings
                    </summary>
                    <table>
                      <thead>
                        <tr>
                          <th>Setting</th>
                          <th>Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(profile.config).map(([key, value]) => (
                          <tr key={key}>
                            <td>{key}</td>
                            <td>
                              {typeof value === "boolean"
                                ? value
                                  ? "Enabled"
                                  : "Disabled"
                                : String(value) || "None"}
                            </td>
                          </tr>
                        ))}
                        <tr>
                          <td>Plugins (357)</td>
                          <td>
                            {profile.enabled_plugins_357.join(", ") || "None"}
                          </td>
                        </tr>
                        <tr>
                          <td>Script patterns (355/655)</td>
                          <td>
                            {profile.enabled_patterns_355655.join(", ") ||
                              "None"}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </details>
                  <button
                    disabled={disabled}
                    onClick={() =>
                      run(() =>
                        api.batchAction({
                          source_id: row.source_id,
                          batch_id: row.id,
                          action: "profile",
                          prepared_id: prepared.id,
                        }),
                      )
                    }
                  >
                    Confirm these match the original collect pass
                  </button>
                </div>
              )}
              <p>
                {prepared.result?.state === "partially_submitted"
                  ? "This partial queue will poll its existing batch and may submit remaining chunks, which incur provider charges."
                  : prepared.result?.state === "fetched"
                    ? "Write this batch’s downloaded results with its saved engine and frozen inputs. No new batch will be submitted."
                    : prepared.result?.state === "queued"
                      ? "Review the queued cost in Manual engines before approving its first provider submission. Declining preserves a linked original queue."
                      : "Poll and collect this provider group with its saved engine and frozen inputs."}
              </p>
              <button
                disabled={disabled || !state?.allow_providers || !!profile}
                onClick={() =>
                  run(async () => {
                    await api.batchResume(prepared.id);
                    onNavigate("manual");
                  })
                }
              >
                Resume saved translation
              </button>
            </div>
          )}
        </div>
      )}
      {row && confirmation && (
        <div
          className="workflow-confirm"
          role="dialog"
          aria-label="Confirm batch action"
        >
          <h2>{actions[confirmation].label}</h2>
          <p>{actions[confirmation].detail}</p>
          <p>
            {row.id} · {row.key_name} · {origin?.root}
          </p>
          <div className="actions">
            <button disabled={disabled} onClick={() => setConfirmation("")}>
              Back
            </button>
            <button
              className="primary"
              disabled={disabled}
              onClick={() =>
                run(async () => {
                  await api.batchAction({
                    source_id: row.source_id,
                    batch_id: row.id,
                    action: confirmation,
                    key_name: confirmation === "bind" ? credential : undefined,
                    engine: confirmation === "import" ? engine : undefined,
                    revision: row.revision,
                  });
                  setConfirmation("");
                })
              }
            >
              Confirm batch action
            </button>
          </div>
        </div>
      )}
      {!!state?.jobs.length && (
        <div className="workflow-card">
          <h2>Batch activity</h2>
          {state.jobs.map((job) => (
            <details
              key={job.id}
              open={job.status === "running" || job.status === "failed"}
            >
              <summary>
                {job.label} · {job.status}
              </summary>
              <p>{job.message}</p>
              <pre>{job.log.join("\n")}</pre>
              {job.result && (
                <pre>
                  {JSON.stringify(
                    Object.fromEntries(
                      Object.entries(job.result).filter(
                        ([k]) => !["hashes", "plan_hash"].includes(k),
                      ),
                    ),
                    null,
                    2,
                  )}
                </pre>
              )}
              {job.action === "import" && job.status === "complete" && (
                <button
                  onClick={() => {
                    setSource("");
                    setSelected(
                      `${job.result?.source_id}/${job.result?.batch_id}`,
                    );
                  }}
                >
                  Open imported batch
                </button>
              )}
              {job.status === "running" && (
                <button onClick={() => run(() => api.workflowStop(job.id))}>
                  Stop local operation
                </button>
              )}
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
