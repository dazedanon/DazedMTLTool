import { useEffect, useRef, useState } from "react";
import {
  Download,
  FolderOpen,
  Play,
  RefreshCw,
  Search,
  Square,
} from "lucide-react";
import { api } from "./bridge";
import type { ManualInspection, ManualJob, ManualState } from "./types";

function Estimate({ value }: { value: Record<string, unknown> }) {
  const numbers: [string, string][] = [
    ["requests", "Requests"],
    ["request_count", "Requests"],
    ["input_tokens", "Input tokens"],
    ["output_tokens", "Estimated output tokens"],
  ];
  const costs: [string, string][] = [
    ["live_cost", "Live estimate"],
    ["estimated_cost", "Estimated cost"],
    ["batch_cost", "Batch estimate"],
    ["batch_nocache_cost", "Batch without cache"],
  ];
  return (
    <dl className="estimate-grid">
      {[...numbers, ...costs]
        .filter(([key]) => typeof value[key] === "number")
        .map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {costs.some(([name]) => name === key)
                ? `$${Number(value[key]).toFixed(5)}`
                : Number(value[key]).toLocaleString()}
            </dd>
          </div>
        ))}
    </dl>
  );
}

export function ManualWorkspace({
  requested,
  visible,
  active,
  onChange,
  report,
}: {
  requested?: { source: string; context: string; engine: string; key: number };
  visible: boolean;
  active: boolean;
  onChange: () => void;
  report: (error: unknown) => void;
}) {
  const [state, setState] = useState<ManualState | null>(null);
  const [source, setSource] = useState("");
  const [contextSource, setContextSource] = useState("");
  const [engine, setEngine] = useState("RPG Maker MV/MZ");
  const [mode, setMode] = useState("estimate");
  const [inventory, setInventory] = useState<ManualInspection | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState("");
  const [fullLog, setFullLog] = useState("");
  const [output, setOutput] = useState("");
  const [model, setModel] = useState("");
  const lastStatus = useRef("");
  const job = state?.jobs.find((item) => item.id === chosen) || state?.jobs[0];
  const rows =
    inventory?.files.filter((file) =>
      file.name.toLowerCase().includes(query.toLowerCase()),
    ) || [];
  const displayed = rows.slice(0, 500);
  const selectedSet = new Set(selected);
  const running = !!state?.active;
  const pending = job?.approval;
  useEffect(() => {
    if (!requested) return;
    setSource(requested.source);
    setContextSource(requested.context);
    setEngine(requested.engine);
    setMode("estimate");
    api
      .manualInspect({ source: requested.source, engine: requested.engine })
      .then((result) => {
        setInventory(result);
        setSelected(result.files.map((file) => file.name));
      })
      .catch(report);
  }, [requested?.key]);
  useEffect(() => {
    if (!visible) return;
    refresh().catch(report);
    api
      .settingsGet()
      .then((value) => setModel(String(value.values.model)))
      .catch(report);
  }, [visible]);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => refresh().catch(report), 200);
    return () => clearInterval(timer);
  }, [running]);
  useEffect(() => {
    setFullLog("");
    setOutput("");
  }, [job?.id]);
  async function refresh() {
    const value = await api.manualState();
    const status = `${value.active || ""}:${value.jobs[0]?.status || ""}`;
    setState(value);
    if (value.active) setChosen(value.active);
    if (lastStatus.current !== status) {
      lastStatus.current = status;
      onChange();
    }
  }
  async function run(label: string, task: () => Promise<void>) {
    setBusy(label);
    try {
      await task();
      await refresh();
    } catch (error) {
      report(error);
    } finally {
      setBusy("");
    }
  }
  async function start() {
    if (!inventory) return;
    await run("Starting", async () => {
      const value = await api.manualStart({
        source: inventory.source,
        engine: inventory.engine,
        revision: inventory.revision,
        files: selected,
        mode,
        context_source: contextSource,
      });
      setChosen(value.id);
      setFullLog("");
      setOutput("");
      onChange();
    });
  }
  function invalidate() {
    setInventory(null);
    setSelected([]);
  }
  function chooseJob(value: ManualJob) {
    setChosen(value.id);
  }
  return (
    <section className="manual-workspace">
      <div className="page-heading">
        <div>
          <p className="eyebrow">MANUAL TRANSLATION</p>
          <h1>Use any supported engine.</h1>
          <p>
            Choose prepared input files, estimate the cost, and follow each run
            in its own workspace.
          </p>
        </div>
      </div>
      <section className="settings-card">
        <fieldset
          className="settings-controls"
          disabled={!!busy || active || running}
        >
          <div className="manual-form">
            <label>
              Translation engine
              <select
                aria-label="Manual translation engine"
                value={engine}
                onChange={(event) => {
                  setEngine(event.target.value);
                  invalidate();
                }}
              >
                {state?.engines.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name} · {item.extensions.join(", ")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Input folder
              <div className="path-input">
                <input
                  aria-label="Manual input folder"
                  value={source}
                  onChange={(event) => {
                    setSource(event.target.value);
                    invalidate();
                  }}
                  placeholder="Folder containing prepared translation files"
                />
                <button
                  aria-label="Choose manual input folder"
                  onClick={async () => {
                    const folder = await api.chooseFolder();
                    if (folder) {
                      setSource(folder);
                      invalidate();
                    }
                  }}
                >
                  <FolderOpen size={17} />
                </button>
              </div>
            </label>
            <label>
              Game context folder (optional)
              <div className="path-input">
                <input
                  aria-label="Manual game context folder"
                  value={contextSource}
                  onChange={(event) => setContextSource(event.target.value)}
                  placeholder="Copy this game's glossary, skills, and speaker settings"
                />
                <button
                  aria-label="Choose manual context folder"
                  onClick={async () => {
                    const folder = await api.chooseFolder();
                    if (folder) setContextSource(folder);
                  }}
                >
                  <FolderOpen size={17} />
                </button>
              </div>
            </label>
            <div className="actions">
              <button
                className="secondary"
                disabled={!source.trim()}
                onClick={() =>
                  run("Reading input files", async () => {
                    const result = await api.manualInspect({ source, engine });
                    setInventory(result);
                    setSelected(result.files.map((file) => file.name));
                  })
                }
              >
                <RefreshCw size={16} />
                Read input files
              </button>
              <span className="muted">
                {model && `Configured model: ${model}`}
              </span>
            </div>
          </div>
        </fieldset>
      </section>
      {inventory && (
        <section className="manual-files settings-card">
          <div className="selection-toolbar">
            <label className="search">
              <Search size={16} />
              <input
                aria-label="Search manual files"
                placeholder="Find a file…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <button
              disabled={active || running}
              onClick={() =>
                setSelected([
                  ...new Set([...selected, ...rows.map((file) => file.name)]),
                ])
              }
            >
              Select visible
            </button>
            <button
              disabled={active || running}
              onClick={() => setSelected([])}
            >
              Clear selection
            </button>
            <span className="muted">
              {selected.length} of {inventory.files.length} selected
            </span>
          </div>
          <div className="manual-file-list">
            {displayed.map((file) => (
              <label key={file.name}>
                <input
                  type="checkbox"
                  aria-label={`Translate ${file.name}`}
                  disabled={active || running}
                  checked={selectedSet.has(file.name)}
                  onChange={(event) =>
                    setSelected(
                      event.target.checked
                        ? [...selected, file.name]
                        : selected.filter((name) => name !== file.name),
                    )
                  }
                />
                <span>{file.name}</span>
                <small>{(file.bytes / 1024).toFixed(1)} KB</small>
              </label>
            ))}
          </div>
          {rows.length > 500 && (
            <p className="muted">
              Showing 500 of {rows.length} matching files. Filter to narrow the
              list; Select visible includes all matches.
            </p>
          )}
          <div className="manual-run-controls">
            <label>
              Run mode
              <select
                aria-label="Manual run mode"
                value={mode}
                disabled={active || running || !!busy}
                onChange={(event) => setMode(event.target.value)}
              >
                <option value="estimate">Estimate cost</option>
                <option value="translate" disabled={!state?.allow_providers}>
                  Translate
                </option>
                <option value="batch" disabled={!state?.allow_providers}>
                  Batch API
                </option>
                <option
                  value="speakers"
                  disabled={
                    !state?.allow_providers || engine !== "RPG Maker MV/MZ"
                  }
                >
                  Collect and translate speakers
                </option>
                <option value="offline">Offline engine check</option>
              </select>
            </label>
            <button
              className="primary"
              disabled={active || running || !!busy || !selected.length}
              onClick={start}
            >
              <Play size={16} />
              {mode === "estimate"
                ? "Estimate selected files"
                : mode === "offline"
                  ? "Run offline engine check"
                  : "Start selected run"}
            </button>
          </div>
          <p className="footnote">
            Input files stay unchanged. A run freezes its files, settings, and
            instructions.{" "}
            {mode === "estimate"
              ? "Estimation makes no provider requests and writes no translated files."
              : mode === "offline"
                ? "Offline output is synthetic text for checking the engine."
                : "Unresolved speakers and batch submission each require their own approval."}
          </p>
        </section>
      )}
      {!state?.allow_providers && (
        <p className="footnote">
          This migration build currently enables local estimates and offline
          checks. Full provider execution is available through the separate
          production-provider launch option.
        </p>
      )}
      {busy && <p role="status">{busy}…</p>}
      {!!state?.jobs.length && (
        <div className="manual-history-layout">
          <aside className="manual-history" aria-label="Manual run history">
            <h2>Run history</h2>
            {state.jobs.map((item) => (
              <button
                key={item.id}
                aria-pressed={job?.id === item.id}
                onClick={() => chooseJob(item)}
              >
                <strong>{item.engine}</strong>
                <span>
                  {item.mode} · {item.status}
                </span>
                <small>
                  {new Date(item.created).toLocaleString()} ·{" "}
                  {item.files.length} files
                </small>
              </button>
            ))}
          </aside>
          {job && (
            <section className="manual-run-detail">
              <div className="manual-run-heading">
                <div>
                  <p className="eyebrow">
                    {job.mode.toUpperCase()} · {job.model}
                  </p>
                  <h2>{job.engine}</h2>
                  <p className="manual-status" role="status">
                    {job.status}
                  </p>
                </div>
                <div className="actions">
                  {state.active === job.id ? (
                    <button
                      disabled={!!busy}
                      onClick={() =>
                        run("Stopping", async () => {
                          await api.manualStop(job.id);
                          onChange();
                        })
                      }
                    >
                      <Square size={15} />
                      Stop run
                    </button>
                  ) : ["failed", "stopped", "interrupted", "canceled"].includes(
                      job.status,
                    ) ? (
                    <button
                      disabled={active || running || !!busy}
                      onClick={() =>
                        run("Resuming", async () => {
                          await api.manualResume(job.id);
                          onChange();
                        })
                      }
                    >
                      <Play size={15} />
                      Resume run
                    </button>
                  ) : null}
                </div>
              </div>
              <p className="run-message">{job.message}</p>
              {job.progress && (
                <p className="muted">
                  {job.progress.current} / {job.progress.total} files ·{" "}
                  {job.progress.file}
                </p>
              )}
              {job.item_progress && state.active === job.id && (
                <progress
                  aria-label="Current file progress"
                  max={job.item_progress.total || 1}
                  value={job.item_progress.current}
                />
              )}
              {pending && (
                <div
                  className="manual-approval"
                  role="dialog"
                  aria-label={
                    pending.kind === "batch"
                      ? "Review batch submission"
                      : "Review speaker translation"
                  }
                >
                  <h2>
                    {pending.kind === "batch"
                      ? "Review batch submission"
                      : "Review speaker translation"}
                  </h2>
                  <Estimate value={pending.detail || {}} />
                  {pending.kind === "speakers" && (
                    <div className="speaker-preview">
                      {Array.isArray(pending.detail.speakers) &&
                        pending.detail.speakers.map((speaker, index) => (
                          <span key={index}>{String(speaker)}</span>
                        ))}
                    </div>
                  )}
                  <p>
                    {pending.kind === "batch"
                      ? "Submit this collected request set to the configured provider?"
                      : "Translate these unresolved names before the file run continues?"}
                  </p>
                  <div className="actions">
                    <button
                      className="primary"
                      disabled={!!busy}
                      onClick={() =>
                        run("Approving", async () => {
                          await api.manualAnswer({
                            job_id: job.id,
                            token: pending.token,
                            approved: true,
                          });
                        })
                      }
                    >
                      {pending.kind === "batch"
                        ? "Submit batch"
                        : "Translate speakers"}
                    </button>
                    <button
                      disabled={!!busy}
                      onClick={() =>
                        run("Canceling", async () => {
                          await api.manualAnswer({
                            job_id: job.id,
                            token: pending.token,
                            approved: false,
                          });
                        })
                      }
                    >
                      Cancel this step
                    </button>
                  </div>
                </div>
              )}
              {job.estimate && <Estimate value={job.estimate} />}
              {Object.entries(job.errors).map(([file, message]) => (
                <p className="banner error" key={file}>
                  {file}: {message}
                </p>
              ))}
              {Object.entries(job.mismatches).map(([file, message]) => (
                <p className="banner" key={file}>
                  {file}: {message}
                </p>
              ))}
              <details className="manual-log">
                <summary>Run log</summary>
                <pre>
                  {fullLog ||
                    job.log.join("\n") ||
                    "Waiting for engine output…"}
                </pre>
                <button
                  onClick={() =>
                    run("Loading log", async () =>
                      setFullLog(await api.manualLog(job.id)),
                    )
                  }
                >
                  Load detailed log
                </button>
              </details>
              {job.status === "complete" &&
                !!Object.keys(job.outputs).length && (
                  <div className="actions">
                    <button
                      className="primary"
                      disabled={active || running || !!busy}
                      onClick={() =>
                        run("Exporting", async () => {
                          const result = await api.manualExport(job.id);
                          setOutput(result.path);
                        })
                      }
                    >
                      <Download size={16} />
                      Export translated files
                    </button>
                    <span className="muted">
                      {Object.keys(job.outputs).length} output files ·{" "}
                      {Object.keys(job.mismatches).length} files with validation
                      warnings
                    </span>
                  </div>
                )}
              {output && (
                <div className="manual-export">
                  <p className="output-path">{output}</p>
                  <button onClick={() => api.openExport(output).catch(report)}>
                    <FolderOpen size={16} />
                    Open output folder
                  </button>
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </section>
  );
}
