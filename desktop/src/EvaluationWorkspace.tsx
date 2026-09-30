import React, { useEffect, useRef, useState, useId } from "react";
import { api } from "./bridge";
import { saveBeforeClose } from "./lifecycle";
import { Modal } from "./Modal";
import type {
  EvaluationCandidate,
  EvaluationDraft,
  EvaluationState,
} from "./types";

const blank: EvaluationCandidate = {
  provider: "openai",
  endpoint: "",
  model: "",
  label: "",
  key_name: "",
  execution: "batch",
  reasoning_effort: "auto",
  max_output_tokens: 4096,
};
const empty: EvaluationDraft = {
  source: "",
  candidates: [],
  settings: {
    target_segments: 360,
    stability_samples: 12,
    repetitions: 3,
    batch_size: 10,
    budget_usd: 10,
  },
  content_selection: {
    preset: "balanced",
    sources: [],
    map_files: [],
    include_code_heavy: true,
  },
};
const title = (key: string) => key.replaceAll("_", " ");
const dollars = (n?: number) =>
  n == null ? "Unavailable" : `$${n.toFixed(n < 0.01 ? 5 : 2)}`;
function anonymous(value: unknown, labels: Record<string, string>): unknown {
  if (Array.isArray(value)) return value.map((v) => anonymous(v, labels));
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [
        labels[k] || k,
        anonymous(v, labels),
      ]),
    );
  return typeof value === "string" ? labels[value] || value : value;
}
function Detail({ value }: { value: unknown }) {
  if (value == null) return <span className="muted">Not available</span>;
  if (Array.isArray(value))
    return (
      <div className="evaluation-details">
        {value.length
          ? value.map((v, i) => (
              <div key={i}>
                <Detail value={v} />
              </div>
            ))
          : "None"}
      </div>
    );
  if (typeof value === "object")
    return (
      <dl className="evaluation-metrics">
        {Object.entries(value).map(([k, v]) => (
          <React.Fragment key={k}>
            <dt>{title(k)}</dt>
            <dd>
              <Detail value={v} />
            </dd>
          </React.Fragment>
        ))}
      </dl>
    );
  return (
    <span>
      {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
    </span>
  );
}
function Candidate({
  row,
  keys,
  change,
  remove,
  disabled,
  models,
  discover,
}: {
  row: EvaluationCandidate;
  keys: EvaluationState["credentials"];
  change: (row: EvaluationCandidate) => void;
  remove: () => void;
  disabled: boolean;
  models: string[];
  discover?: () => void;
}) {
  const modelList = useId();
  const [reasoning, setReasoning] = useState<{
    levels: string[];
    default: string;
  }>({ levels: [], default: "provider_default" });
  useEffect(() => {
    let live = true;
    api
      .evaluationReasoning(row)
      .then((v) => {
        if (live) setReasoning(v);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [row.provider, row.model]);
  return (
    <fieldset className="evaluation-candidate" disabled={disabled}>
      <legend>{row.label || row.model || "Comparison model"}</legend>
      <div className="form-grid">
        <label>
          Saved credential
          <select
            aria-label="Evaluation credential"
            value={row.key_name}
            onChange={(e) => {
              const key = keys.find((k) => k.name === e.target.value);
              change({
                ...row,
                key_name: e.target.value,
                endpoint: key?.endpoint || "",
              });
            }}
          >
            <option value="">Choose a saved credential</option>
            {keys.map((k) => (
              <option key={k.name}>{k.name}</option>
            ))}
          </select>
        </label>
        <label>
          Provider protocol
          <select
            value={row.provider}
            onChange={(e) =>
              change({
                ...row,
                provider: e.target.value,
                reasoning_effort: "auto",
              })
            }
          >
            {["openai", "anthropic", "gemini"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Model
          <input
            aria-label="Evaluation model"
            list={modelList}
            value={row.model}
            onChange={(e) =>
              change({
                ...row,
                model: e.target.value,
                reasoning_effort: "auto",
              })
            }
          />
          <datalist id={modelList}>
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <button disabled={!discover || !row.key_name} onClick={discover}>
            Refresh available models
          </button>
        </label>
        <label>
          Display label
          <input
            value={row.label}
            onChange={(e) => change({ ...row, label: e.target.value })}
          />
        </label>
        <label>
          Execution
          <select
            value={row.execution}
            onChange={(e) => change({ ...row, execution: e.target.value })}
          >
            <option value="batch">Batch — asynchronous</option>
            <option value="live">Live — keep app open</option>
          </select>
        </label>
        <label>
          Reasoning
          <select
            value={row.reasoning_effort}
            onChange={(e) =>
              change({ ...row, reasoning_effort: e.target.value })
            }
          >
            <option value="auto">Auto ({title(reasoning.default)})</option>
            {reasoning.levels.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Maximum output tokens
          <input
            type="number"
            min={1}
            max={128000}
            value={row.max_output_tokens}
            onChange={(e) =>
              change({ ...row, max_output_tokens: Number(e.target.value) })
            }
          />
        </label>
      </div>
      <div className="evaluation-row">
        <small className="output-path">
          {row.endpoint || "Save an API URL with the credential in Settings."}
        </small>
        <button onClick={remove}>Remove model</button>
      </div>
    </fieldset>
  );
}

export default function EvaluationWorkspace({ visible }: { visible: boolean }) {
  const [state, setState] = useState<EvaluationState | null>(null);
  const [runId, setRunId] = useState("");
  const [draft, setDraft] = useState<EvaluationDraft>(empty);
  const [tab, setTab] = useState("setup");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [blind, setBlind] = useState(true);
  const [compareModels, setCompareModels] = useState<string[]>([]);
  const [autoCollect, setAutoCollect] = useState(false);
  const [historyQuery, setHistoryQuery] = useState("");
  const [legacy, setLegacy] = useState("");
  const [archive, setArchive] = useState("");
  const [reviewPath, setReviewPath] = useState("");
  const [calibration, setCalibration] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [reviewerKind, setReviewerKind] = useState("human");
  const [mode, setMode] = useState("paired");
  const [stage, setStage] = useState("screening");
  const [newCampaign, setNewCampaign] = useState(false);
  const [policy, setPolicy] = useState("");
  const [challenge, setChallenge] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState("");
  const loaded = useRef(false);
  const initializing = useRef(false);
  const currentDraft = useRef(draft);
  currentDraft.current = draft;
  const report = (e: unknown) =>
    setError(e instanceof Error ? e.message : String(e));
  async function refresh() {
    setState(
      await api.evaluationState({
        run_id: runId,
        query,
        selection: filter,
        page,
        review_mode: mode,
      }),
    );
  }
  async function action(
    name: string,
    options: Record<string, unknown> = {},
    previewJob = "",
    identity = runId,
  ) {
    setBusy(true);
    setError("");
    setConfirm("");
    try {
      const job = await api.evaluationAction({
        action: name,
        run_id: identity,
        options,
        preview_job: previewJob,
      });
      setPending(job.id);
      await refresh();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (visible) refresh().catch(report);
  }, [visible, runId, query, filter, page, mode]);
  useEffect(() => {
    if (!state || loaded.current) return;
    if (state.defaults) {
      loaded.current = true;
      setDraft({
        ...empty,
        ...state.draft,
        candidates:
          state.draft?.candidates ||
          state.defaults.map((row) => ({ ...blank, ...row })),
      });
      setPolicy(JSON.stringify(state.policy, null, 2));
    } else if (!state.active && !initializing.current) {
      initializing.current = true;
      action("catalog", {}, "", "");
    }
  }, [state]);
  useEffect(() => {
    if (!loaded.current) return;
    const timer = setTimeout(
      () => api.evaluationDraft(draft).catch(report),
      350,
    );
    return () => clearTimeout(timer);
  }, [draft]);
  useEffect(
    () =>
      saveBeforeClose(async () => {
        if (loaded.current) await api.evaluationDraft(currentDraft.current);
      }),
    [],
  );
  useEffect(() => {
    if (!visible || !state?.active) return;
    const timer = setInterval(() => refresh().catch(report), 500);
    return () => clearInterval(timer);
  }, [visible, state?.active, runId, query, filter, page]);
  useEffect(() => {
    if (!pending) return;
    const job = state?.jobs.find((j) => j.id === pending);
    if (!job || job.status === "running") return;
    setPending("");
    if (job.status !== "complete") {
      setError(job.message);
      return;
    }
    if (job.result?.run_id && job.result.run_id !== runId) {
      setRunId(job.result.run_id);
      setPage(0);
    }
    if (
      [
        "prepare",
        "archive_import",
        "legacy_import",
        "open",
        "submit",
        "refresh",
      ].includes(job.action)
    )
      setTab("results");
    if (job.action === "skill" && job.result?.text)
      api.copyText(job.result.text).catch(report);
    if (job.action === "scan" && job.result?.source)
      setDraft((value) => ({ ...value, source: job.result!.source! }));
    if (job.action === "review_export") {
      setNewCampaign(false);
      setChallenge("");
    }
  }, [state, pending]);
  useEffect(() => {
    if (!state?.view) return;
    setChosen(
      state.view.choices.filter((c) => c.selected_by_default).map((c) => c.id),
    );
  }, [
    state?.view?.run_id,
    state?.view?.choices.map((c) => c.id + c.valid_primary).join(","),
  ]);
  useEffect(() => {
    if (!state?.view) return;
    setPolicy(
      JSON.stringify(
        state.view.state.paired_review?.policy || state.policy,
        null,
        2,
      ),
    );
    setNewCampaign(false);
    setAutoCollect(false);
    setCompareModels(state.view.state.candidates.map((c) => c.id!));
  }, [state?.view?.run_id]);
  useEffect(() => {
    if (
      !visible ||
      !autoCollect ||
      !state?.allow_providers ||
      state.active ||
      !state.view ||
      state.view.state.credential_binding_required ||
      !["submitted", "partially_submitted"].includes(state.view.state.status)
    )
      return;
    const timer = setTimeout(() => action("refresh"), 60000);
    return () => clearTimeout(timer);
  }, [
    visible,
    autoCollect,
    state?.allow_providers,
    state?.active,
    state?.view?.state.status,
    runId,
  ]);
  const view = state?.view;
  const displayedCandidates =
    view?.state.candidates.filter((c) => compareModels.includes(c.id!)) || [];
  const disabled = busy || !!state?.active;
  const scan = state?.jobs.find(
    (j) =>
      j.action === "scan" &&
      j.status === "complete" &&
      j.result?.source === draft.source &&
      JSON.stringify(j.result.selection) ===
        JSON.stringify(draft.content_selection),
  )?.result;
  const estimate = state?.jobs.find(
    (j) =>
      j.action === "estimate" &&
      j.status === "complete" &&
      j.result?.run_id === runId &&
      j.result.revision === view?.revision,
  );
  const preview = state?.jobs.find(
    (j) =>
      j.action === "review_preview" &&
      j.status === "complete" &&
      j.result?.run_id === runId &&
      j.result.revision === view?.revision,
  );
  const reviewOptions = () => ({
    mode,
    stage,
    candidate_ids:
      mode === "paired" &&
      view?.state.paired_review &&
      !newCampaign &&
      stage !== "confirmation"
        ? undefined
        : chosen,
    policy:
      mode === "paired" && (!view?.state.paired_review || newCampaign)
        ? JSON.parse(policy)
        : undefined,
    new_campaign: newCampaign,
    challenge_samples: challenge
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  });
  const fileField = (
    label: string,
    value: string,
    change: (s: string) => void,
    kind: "archive" | "review" | "calibration",
  ) => (
    <label>
      {label}
      <div className="evaluation-row">
        <input value={value} onChange={(e) => change(e.target.value)} />
        <button
          disabled={disabled}
          onClick={() =>
            api
              .chooseEvaluationFile(kind)
              .then((v) => {
                if (v) change(v);
              })
              .catch(report)
          }
        >
          Browse
        </button>
      </div>
    </label>
  );
  return (
    <section className="evaluation-shell">
      <div className="page-heading">
        <div>
          <p className="eyebrow">TRANSLATION EVALUATION</p>
          <h1>Compare translations on the same text.</h1>
          <p className="muted">
            Prepare a shared sample, inspect costs, then review anonymous
            outputs. Quality judgments and delivery reliability remain separate.
          </p>
        </div>
        <button
          disabled={disabled}
          onClick={() => action("catalog", {}, "", "")}
        >
          Reload saved runs
        </button>
      </div>
      {error && (
        <div role="alert" className="error-banner">
          {error}
        </div>
      )}
      {!!state?.runs?.length && (
        <div className="evaluation-history card">
          <label>
            Find saved runs
            <input
              value={historyQuery}
              onChange={(e) => setHistoryQuery(e.target.value)}
              placeholder="Game, model, status or run ID"
            />
          </label>
          <label>
            Saved evaluation
            <select
              aria-label="Saved evaluation"
              value={runId}
              disabled={disabled}
              onChange={(e) => {
                setRunId(e.target.value);
                setPage(0);
                action("open", {}, "", e.target.value);
              }}
            >
              <option value="">Choose a run</option>
              {state?.runs
                ?.filter((r) =>
                  `${r.run_id} ${r.models.join(" ")} ${r.source_name} ${r.status}`
                    .toLowerCase()
                    .includes(historyQuery.toLowerCase()),
                )
                .map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.created_at} · {r.source_name} · {r.status} ·{" "}
                    {r.models.join(" / ")}
                  </option>
                ))}
            </select>
          </label>
        </div>
      )}
      <div className="tabs" role="tablist" aria-label="Evaluation sections">
        {["setup", "results", "review", "compare", "archives", "activity"].map(
          (v) => (
            <button
              key={v}
              role="tab"
              id={`evaluation-tab-${v}`}
              aria-controls={`evaluation-panel-${v}`}
              aria-selected={tab === v}
              tabIndex={tab === v ? 0 : -1}
              onKeyDown={(event) => {
                const tabs = [
                  "setup",
                  "results",
                  "review",
                  "compare",
                  "archives",
                  "activity",
                ];
                const index = tabs.indexOf(v);
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % tabs.length
                    : event.key === "ArrowLeft"
                      ? (index + tabs.length - 1) % tabs.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? tabs.length - 1
                          : -1;
                if (next >= 0) {
                  event.preventDefault();
                  setTab(tabs[next]);
                  document
                    .getElementById(`evaluation-tab-${tabs[next]}`)
                    ?.focus();
                }
              }}
              onClick={() => setTab(v)}
            >
              {v.charAt(0).toUpperCase() + v.slice(1)}
            </button>
          ),
        )}
      </div>
      <div
        role="tabpanel"
        id={`evaluation-panel-${tab}`}
        aria-labelledby={`evaluation-tab-${tab}`}
      >
        {tab === "setup" && (
          <div className="card">
            <fieldset disabled={disabled || !loaded.current}>
              <legend>Prepare a benchmark</legend>
              <label>
                Evaluation game folder
                <div className="evaluation-row">
                  <input
                    aria-label="Evaluation game folder"
                    value={draft.source}
                    onChange={(e) =>
                      setDraft({ ...draft, source: e.target.value })
                    }
                  />
                  <button
                    onClick={() =>
                      api
                        .chooseFolder()
                        .then((source) => {
                          if (source) setDraft({ ...draft, source });
                        })
                        .catch(report)
                    }
                  >
                    Browse game
                  </button>
                </div>
              </label>
              <div className="form-grid">
                <label>
                  Content preset
                  <select
                    value={draft.content_selection.preset}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        content_selection: {
                          ...draft.content_selection,
                          preset: e.target.value,
                        },
                      })
                    }
                  >
                    {["balanced", "events", "database", "custom"].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </label>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={draft.content_selection.include_code_heavy}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        content_selection: {
                          ...draft.content_selection,
                          include_code_heavy: e.target.checked,
                        },
                      })
                    }
                  />
                  Include code-heavy lines
                </label>
              </div>
              {draft.content_selection.preset === "custom" &&
                state?.content_groups?.map(([id, label, sources]) => (
                  <fieldset key={id}>
                    <legend>{label}</legend>
                    <div className="evaluation-checks">
                      {sources.map(([key, name]) => (
                        <label key={key}>
                          <input
                            type="checkbox"
                            checked={draft.content_selection.sources.includes(
                              key,
                            )}
                            onChange={(e) =>
                              setDraft({
                                ...draft,
                                content_selection: {
                                  ...draft.content_selection,
                                  sources: e.target.checked
                                    ? [...draft.content_selection.sources, key]
                                    : draft.content_selection.sources.filter(
                                        (s) => s !== key,
                                      ),
                                },
                              })
                            }
                          />
                          {name}{" "}
                          {scan?.inventory &&
                            `(${scan.inventory.source_counts[key] || 0})`}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                ))}
              <label>
                Map files (comma separated; blank includes all)
                <input
                  value={draft.content_selection.map_files.join(", ")}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      content_selection: {
                        ...draft.content_selection,
                        map_files: e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      },
                    })
                  }
                />
              </label>
              <button
                onClick={() =>
                  action(
                    "scan",
                    {
                      source: draft.source,
                      content_selection: draft.content_selection,
                    },
                    "",
                    "",
                  )
                }
              >
                Inspect eligible content
              </button>
              {scan && (
                <p role="status">
                  {scan.selected} selected eligible lines;{" "}
                  {scan.inventory?.eligible_segments} across the game.{" "}
                  {scan.selected! >= 60 && (
                    <button
                      onClick={() =>
                        setDraft({
                          ...draft,
                          settings: {
                            ...draft.settings,
                            target_segments: Math.min(scan.selected!, 5000),
                          },
                        })
                      }
                    >
                      Use {Math.min(scan.selected!, 5000)} lines
                    </button>
                  )}
                </p>
              )}
              {scan?.inventory && (
                <details>
                  <summary>Content inventory and map counts</summary>
                  <Detail value={scan.inventory} />
                </details>
              )}
              <div className="form-grid">
                <label>
                  Test template
                  <select
                    defaultValue="custom"
                    onChange={(e) => {
                      const template = {
                        quick: [120, 3],
                        standard: [360, 12],
                        thorough: [600, 18],
                      }[e.target.value as "quick" | "standard" | "thorough"];
                      if (template)
                        setDraft({
                          ...draft,
                          settings: {
                            ...draft.settings,
                            target_segments: template[0],
                            stability_samples: template[1],
                            batch_size: 10,
                            repetitions: 3,
                          },
                        });
                      e.target.value = "custom";
                    }}
                  >
                    <option value="custom">Custom / saved settings</option>
                    <option value="quick">Quick · 120 lines</option>
                    <option value="standard">Standard · 360 lines</option>
                    <option value="thorough">Thorough · 600 lines</option>
                  </select>
                </label>
                {(
                  [
                    ["target_segments", "Target lines", 60, 5000, 1],
                    ["batch_size", "Lines per sample", 1, 2147483647, 1],
                    ["stability_samples", "Repeated samples", 0, 500, 1],
                    ["repetitions", "Runs per repeated sample", 1, 10, 1],
                    ["budget_usd", "Hard budget per model ($)", 1, 100, 0.01],
                  ] as const
                ).map(([key, label, min, max, step]) => (
                  <label key={key}>
                    {label}
                    <input
                      type="number"
                      min={min}
                      max={max}
                      step={step}
                      value={draft.settings[key]}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          settings: {
                            ...draft.settings,
                            [key]: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              {draft.candidates.map((row, i) => (
                <Candidate
                  key={i}
                  row={row}
                  keys={state?.credentials || []}
                  models={
                    state?.jobs.find(
                      (j) =>
                        j.action === "models" &&
                        j.status === "complete" &&
                        j.result?.model_source?.key_name === row.key_name &&
                        j.result.model_source.endpoint === row.endpoint &&
                        j.result.model_source.provider === row.provider,
                    )?.result?.models ||
                    state?.model_suggestions ||
                    []
                  }
                  discover={
                    state?.allow_providers
                      ? () => action("models", { candidate: row }, "", "")
                      : undefined
                  }
                  disabled={disabled}
                  change={(next) =>
                    setDraft({
                      ...draft,
                      candidates: draft.candidates.map((v, j) =>
                        j === i ? next : v,
                      ),
                    })
                  }
                  remove={() =>
                    setDraft({
                      ...draft,
                      candidates: draft.candidates.filter((_, j) => j !== i),
                    })
                  }
                />
              ))}
              <div className="evaluation-row">
                <button
                  onClick={() =>
                    setDraft({
                      ...draft,
                      candidates: [...draft.candidates, { ...blank }],
                    })
                  }
                >
                  Add comparison model
                </button>
                <button
                  className="primary"
                  disabled={!scan || draft.candidates.length < 2}
                  onClick={() =>
                    action(
                      "prepare",
                      { ...draft, source_hash: scan?.source_hash },
                      "",
                      "",
                    )
                  }
                >
                  Prepare evaluation locally
                </button>
              </div>
              <p className="muted">
                Preparation freezes the source and instructions in the manifest.
                It replaces older unsubmitted preparations; active runs and
                completed archives remain in history.
              </p>
            </fieldset>
          </div>
        )}
        {tab === "results" && (
          <div className="card">
            {!view ? (
              <p>Select or prepare an evaluation.</p>
            ) : (
              <>
                <div className="evaluation-row">
                  <h2>{view.run_id}</h2>
                  <span className="status-pill">{view.state.status}</span>
                  <button
                    onClick={() => api.openExport(view.path).catch(report)}
                  >
                    Open run folder
                  </button>
                </div>
                <p>
                  {view.requests} requests per model · Hard budget{" "}
                  {dollars(view.state.budget_usd_per_model)} per model.
                </p>
                <div className="evaluation-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Model</th>
                        <th>Mode / status</th>
                        <th>Reasoning / output cap</th>
                        <th>Text estimate</th>
                        <th>Theoretical ceiling</th>
                      </tr>
                    </thead>
                    <tbody>
                      {view.state.candidates.map((c) => (
                        <tr key={c.id}>
                          <th>
                            {c.label || c.model}
                            <small>{c.model}</small>
                          </th>
                          <td>
                            {c.execution}
                            <small>{c.status}</small>
                          </td>
                          <td>
                            {title(
                              c.effective_reasoning_effort ||
                                "provider_default",
                            )}
                            <small>{c.max_output_tokens} tokens</small>
                          </td>
                          <td>
                            {dollars(c.estimate?.cost_usd)}
                            {c.estimate?.reasoning_tokens_unestimated && (
                              <small>+ unestimated reasoning</small>
                            )}
                          </td>
                          <td>{dollars(c.estimate?.maximum_cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {view.state.credential_binding_required && (
                  <fieldset disabled={disabled}>
                    <legend>Reconnect imported candidates</legend>
                    <p>
                      Select each original account saved for the displayed exact
                      API URL.
                    </p>
                    {view.state.candidates
                      .filter(
                        (c) =>
                          !["completed", "failed"].includes(c.status || ""),
                      )
                      .map((c) => (
                        <label key={c.id}>
                          {c.label || c.model} · {c.endpoint}
                          <select
                            value={bindings[c.id!] || ""}
                            onChange={(e) =>
                              setBindings({
                                ...bindings,
                                [c.id!]: e.target.value,
                              })
                            }
                          >
                            <option value="">Choose original credential</option>
                            {state?.credentials
                              .filter(
                                (k) =>
                                  k.endpoint.replace(/\/$/, "") ===
                                  c.endpoint.replace(/\/$/, ""),
                              )
                              .map((k) => (
                                <option key={k.name}>{k.name}</option>
                              ))}
                          </select>
                        </label>
                      ))}
                    <button onClick={() => action("bind", { bindings })}>
                      Save credential bindings locally
                    </button>
                  </fieldset>
                )}
                <div className="evaluation-row">
                  <button
                    disabled={
                      disabled ||
                      !["prepared", "partially_submitted"].includes(
                        view.state.status,
                      ) ||
                      !!view.state.credential_binding_required
                    }
                    onClick={() => action("estimate")}
                  >
                    Review costs before submission
                  </button>
                  <button
                    disabled={
                      disabled ||
                      !state?.allow_providers ||
                      ![
                        "submitted",
                        "partially_submitted",
                        "imported_paused",
                      ].includes(view.state.status) ||
                      !!view.state.credential_binding_required
                    }
                    onClick={() => setConfirm("refresh")}
                  >
                    Collect provider results
                  </button>
                </div>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={autoCollect}
                    disabled={!state?.allow_providers}
                    onChange={(e) => setAutoCollect(e.target.checked)}
                  />
                  Collect active provider batches every 60 seconds while this
                  page is open
                </label>
                {!state?.allow_providers && (
                  <p className="muted">
                    Provider requests are disabled in this session. Local
                    preparation, archives and reviews are available.
                  </p>
                )}
                {estimate?.result?.approval && (
                  <div className="evaluation-approval">
                    <h3>Submission review</h3>
                    <p>
                      This sends paid requests for{" "}
                      {estimate.result.approval.requests} manifest executions
                      per model. Batch jobs run asynchronously; Live jobs
                      require the app to stay open and resume from their saved
                      checkpoints. Live ceilings include automatic retries.
                      Current prices are checked again before submission against
                      the saved hard budget.
                    </p>
                    <p>
                      Hard budget: {dollars(estimate.result.approval.budget)}{" "}
                      per model.
                    </p>
                    <ul>
                      {estimate.result.approval.candidates
                        .filter((c) =>
                          ["prepared", "running_live"].includes(c.status || ""),
                        )
                        .map((c) => (
                          <li key={c.id}>
                            <strong>{c.label || c.model}</strong> ·{" "}
                            {c.execution} · {dollars(c.estimate?.cost_usd)} text
                            estimate
                            {c.estimate?.reasoning_tokens_unestimated
                              ? " + reasoning"
                              : ""}{" "}
                            · {dollars(c.estimate?.maximum_cost_usd)}{" "}
                            theoretical ceiling
                            <br />
                            <small>
                              {c.key_name} · {c.endpoint}
                            </small>
                          </li>
                        ))}
                    </ul>
                    <button
                      className="primary"
                      disabled={disabled || !state?.allow_providers}
                      onClick={() => action("submit", {}, estimate.id)}
                    >
                      Approve and run evaluation
                    </button>
                  </div>
                )}
                <details>
                  <summary>Sampling and frozen instructions</summary>
                  <Detail value={view.state.corpus_summary} />
                  <Detail value={view.context} />
                </details>
                {view.state.candidates.map((c) => (
                  <details key={c.id}>
                    <summary>
                      {c.label || c.model}: reliability, cost and stability
                    </summary>
                    <Detail value={c.summary} />
                  </details>
                ))}
                {view.paired_summary && (
                  <>
                    <h3>Paired review findings</h3>
                    <pre className="evaluation-summary">
                      {view.paired_summary}
                    </pre>
                    <details>
                      <summary>
                        Quality intervals, calibration and decision evidence
                      </summary>
                      <Detail value={view.paired_report} />
                    </details>
                  </>
                )}
                {view.state.human_review && (
                  <details>
                    <summary>
                      Legacy ranking results and reviewer agreement
                    </summary>
                    <Detail value={view.state.human_review} />
                  </details>
                )}
              </>
            )}
          </div>
        )}
        {tab === "review" && (
          <div className="card">
            {!view ? (
              <p>Select a completed evaluation.</p>
            ) : (
              <fieldset disabled={disabled}>
                <legend>Blind review</legend>
                <p>
                  CSV exports omit model identities and previous verdicts.
                  Import the completed CSV to validate its frozen inputs and
                  calculate results.
                </p>
                <div className="form-grid">
                  <label>
                    Review format
                    <select
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                    >
                      <option value="paired">
                        Paired assessment and preference
                      </option>
                      <option value="ranking">Legacy all-model ranking</option>
                    </select>
                  </label>
                  <label>
                    Review stage
                    <select
                      value={stage}
                      onChange={(e) => setStage(e.target.value)}
                    >
                      {(mode === "paired"
                        ? [
                            "screening",
                            "confirmation",
                            "challenge",
                            "judge_check",
                            "order_swap",
                            "adjudication",
                            "calibration",
                          ]
                        : ["screening", "judge_check"]
                      ).map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="evaluation-checks">
                  {view.choices.map((c) => (
                    <label key={c.id}>
                      <input
                        type="checkbox"
                        checked={chosen.includes(c.id)}
                        disabled={!c.available}
                        onChange={(e) =>
                          setChosen(
                            e.target.checked
                              ? [...chosen, c.id]
                              : chosen.filter((id) => id !== c.id),
                          )
                        }
                      />
                      {c.label} · {c.valid_primary} usable lines{" "}
                      {c.reason && `(${c.reason})`}
                    </label>
                  ))}
                </div>
                {mode === "paired" && (
                  <>
                    <label className="check-row">
                      <input
                        type="checkbox"
                        checked={newCampaign}
                        onChange={(e) => {
                          setNewCampaign(e.target.checked);
                          if (e.target.checked) setStage("screening");
                        }}
                      />
                      Start a new campaign (retains prior results)
                    </label>
                    <details>
                      <summary>
                        Review policy and source-selected challenges
                      </summary>
                      <p>
                        Policy changes apply to a new screening campaign. Rates
                        use 0–1; pilot thresholds require calibration.
                      </p>
                      <textarea
                        aria-label="Paired review policy"
                        rows={16}
                        value={policy}
                        onChange={(e) => {
                          setPolicy(e.target.value);
                          setNewCampaign(true);
                          setStage("screening");
                        }}
                      />
                      <label>
                        Challenge sample IDs, comma separated
                        <input
                          value={challenge}
                          onChange={(e) => setChallenge(e.target.value)}
                        />
                      </label>
                    </details>
                  </>
                )}
                <button
                  onClick={() => {
                    try {
                      action("review_preview", reviewOptions());
                    } catch (e) {
                      report(e);
                    }
                  }}
                >
                  Preview blind review coverage
                </button>
                {preview?.result?.preview && (
                  <div className="evaluation-approval">
                    <Detail value={preview.result.preview} />
                    <p>
                      Export uses the options recorded in this preview. Preview
                      again after changing the format, candidates or stage.
                    </p>
                    <button
                      onClick={() => action("review_export", {}, preview.id)}
                    >
                      Export previewed review
                    </button>
                  </div>
                )}
                <button onClick={() => action("skill")}>
                  Copy review instructions
                </button>
                {state?.jobs
                  .filter(
                    (j) =>
                      j.action === "review_export" &&
                      j.status === "complete" &&
                      j.result?.run_id === runId,
                  )
                  .slice(0, 3)
                  .map((j) => (
                    <p key={j.id}>
                      <button
                        onClick={() =>
                          api.openExport(j.result!.path!).catch(report)
                        }
                      >
                        Open exported review
                      </button>{" "}
                      <span className="output-path">{j.result!.path}</span>
                    </p>
                  ))}
                <hr />
                {fileField("Reviewed CSV", reviewPath, setReviewPath, "review")}
                <div className="form-grid">
                  <label>
                    Reviewer name
                    <input
                      value={reviewer}
                      onChange={(e) => setReviewer(e.target.value)}
                    />
                  </label>
                  <label>
                    Reviewer kind
                    <select
                      value={reviewerKind}
                      onChange={(e) => setReviewerKind(e.target.value)}
                    >
                      {["human", "ai", "unspecified"].map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <button
                  disabled={!reviewPath}
                  onClick={() =>
                    action("review_import", {
                      path: reviewPath,
                      reviewer,
                      reviewer_kind: reviewerKind,
                    })
                  }
                >
                  Import reviewed CSV
                </button>
                {fileField(
                  "Human-authored calibration JSON",
                  calibration,
                  setCalibration,
                  "calibration",
                )}
                <button
                  disabled={!calibration}
                  onClick={() => action("calibration", { path: calibration })}
                >
                  Load calibration
                </button>
              </fieldset>
            )}
          </div>
        )}
        {tab === "compare" && (
          <div className="card">
            {!view ? (
              <p>Select an evaluation to read its outputs.</p>
            ) : (
              <>
                <div className="form-grid">
                  <label>
                    Find samples
                    <input
                      value={query}
                      onChange={(e) => {
                        setQuery(e.target.value);
                        setPage(0);
                      }}
                      placeholder="Source, translation, scene or evidence"
                    />
                  </label>
                  <label>
                    Sample filter
                    <select
                      value={filter}
                      onChange={(e) => {
                        setFilter(e.target.value);
                        setPage(0);
                      }}
                    >
                      {[
                        "available",
                        "all",
                        "reviewed",
                        "ties",
                        "notes",
                        "problems",
                        "unreviewed",
                        "follow_up",
                        "disputed",
                      ].map((v) => (
                        <option key={v} value={v}>
                          {title(v)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={blind}
                      onChange={(e) => setBlind(e.target.checked)}
                    />
                    Hide model identities
                  </label>
                </div>
                <div className="evaluation-checks">
                  {view.state.candidates.map((c, i) => (
                    <label key={c.id}>
                      <input
                        type="checkbox"
                        checked={compareModels.includes(c.id!)}
                        disabled={
                          compareModels.length === 1 &&
                          compareModels.includes(c.id!)
                        }
                        onChange={(e) =>
                          setCompareModels(
                            e.target.checked
                              ? [...compareModels, c.id!]
                              : compareModels.filter((id) => id !== c.id),
                          )
                        }
                      />
                      {blind ? `Model ${i + 1}` : c.label || c.model}
                    </label>
                  ))}
                </div>
                <p>{view.total} matching samples</p>
                {view.samples.map((sample) => (
                  <article className="evaluation-sample" key={sample.id}>
                    <h3>
                      {sample.id} · {title(sample.stratum)}
                    </h3>
                    <p className="muted">
                      {sample.scene_id}
                      {sample.human_follow_up && " · Human follow-up requested"}
                    </p>
                    <details>
                      <summary>Source context</summary>
                      <Detail value={sample.context} />
                    </details>
                    {sample.paired_holdout_locked ? (
                      <p>
                        Confirmation outputs remain hidden until the campaign
                        selects confirmation candidates.
                      </p>
                    ) : (
                      <div className="evaluation-table">
                        <table>
                          <thead>
                            <tr>
                              <th>Japanese source</th>
                              {displayedCandidates.map((c) => (
                                <th key={c.id}>
                                  {blind
                                    ? sample.blind_labels[c.id!] ||
                                      `Candidate ${String.fromCharCode(65 + view.state.candidates.findIndex((v) => v.id === c.id))}`
                                    : c.label || c.model}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {sample.lines.map((line) => (
                              <tr key={line.segment_id}>
                                <td lang="ja">{line.source}</td>
                                {displayedCandidates.map((c) => {
                                  const output = line.outputs[c.id!];
                                  return (
                                    <td
                                      key={c.id}
                                      className={
                                        !output?.valid
                                          ? "evaluation-invalid"
                                          : ""
                                      }
                                    >
                                      {output?.translation || "Missing output"}
                                      {output?.issues.map((v, i) => (
                                        <small key={i}>{v}</small>
                                      ))}
                                      {output?.warnings.map((v, i) => (
                                        <small key={i}>{v}</small>
                                      ))}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    {!sample.paired_holdout_locked && (
                      <details>
                        <summary>
                          Review verdicts and supporting evidence
                        </summary>
                        <Detail
                          value={
                            blind
                              ? anonymous(
                                  sample.paired_review || sample.review,
                                  Object.fromEntries(
                                    view.state.candidates.map((c, i) => [
                                      c.id!,
                                      sample.blind_labels[c.id!] ||
                                        `Candidate ${String.fromCharCode(65 + i)}`,
                                    ]),
                                  ),
                                )
                              : sample.paired_review || sample.review
                          }
                        />
                      </details>
                    )}
                  </article>
                ))}
                <div className="evaluation-row">
                  <button
                    disabled={!view.page}
                    onClick={() => setPage(view.page - 1)}
                  >
                    Previous samples
                  </button>
                  <span>Page {view.page + 1}</span>
                  <button
                    disabled={(view.page + 1) * 8 >= view.total}
                    onClick={() => setPage(view.page + 1)}
                  >
                    Next samples
                  </button>
                </div>
              </>
            )}
          </div>
        )}
        {tab === "archives" && (
          <div className="card">
            <fieldset disabled={disabled}>
              <legend>Move or recover an evaluation</legend>
              <p>
                Exports include frozen context, results and review history.
                Active imports remain paused and require deliberate credential
                binding before reconnecting.
              </p>
              <button
                disabled={!runId}
                onClick={() => action("archive_export")}
              >
                Export selected evaluation archive
              </button>
              {fileField("Evaluation archive", archive, setArchive, "archive")}
              <button
                disabled={!archive}
                onClick={() =>
                  action("archive_import", { path: archive }, "", "")
                }
              >
                Import evaluation archive
              </button>
              <label>
                Legacy evaluation run folder
                <div className="evaluation-row">
                  <input
                    value={legacy}
                    onChange={(e) => setLegacy(e.target.value)}
                  />
                  <button
                    onClick={() =>
                      api
                        .chooseFolder()
                        .then((v) => {
                          if (v) setLegacy(v);
                        })
                        .catch(report)
                    }
                  >
                    Browse legacy run
                  </button>
                </div>
              </label>
              <button
                disabled={!legacy}
                onClick={() =>
                  action("legacy_import", { path: legacy }, "", "")
                }
              >
                Import legacy evaluation
              </button>
            </fieldset>
            {Object.entries(state?.paths || {})
              .filter(([id]) => id !== "run")
              .map(([id, path]) => (
                <p key={id}>
                  <button onClick={() => api.openExport(path).catch(report)}>
                    Open export
                  </button>{" "}
                  <span className="output-path">{path}</span>
                </p>
              ))}
          </div>
        )}
        {tab === "activity" && (
          <div className="card">
            {state?.jobs.map((job) => (
              <details key={job.id} open={job.status === "running"}>
                <summary>
                  {job.label} · {job.status} · {job.created}
                </summary>
                <p>{job.message}</p>
                <pre>{job.log.join("\n")}</pre>
                {job.status === "running" && (
                  <button
                    onClick={() =>
                      api.workflowStop(job.id).then(refresh).catch(report)
                    }
                  >
                    Stop at safe boundary
                  </button>
                )}
              </details>
            ))}
          </div>
        )}
      </div>
      {state?.active && (
        <div className="evaluation-running" role="status">
          {state.jobs.find((j) => j.id === state.active)?.message ||
            "Another action is running."}
          <button onClick={() => setTab("activity")}>View activity</button>
        </div>
      )}
      {confirm && (
        <Modal
          label="Reconnect and collect this evaluation?"
          onDismiss={() => setConfirm("")}
          dismissible={!disabled}
        >
          <h2>Reconnect and collect this evaluation?</h2>
          <p>
            This contacts the saved provider endpoints using each candidate’s
            original credential. Imported jobs will be unpaused for collection.
          </p>
          <div className="evaluation-row">
            <button
              autoFocus
              disabled={disabled}
              onClick={() => setConfirm("")}
            >
              Cancel
            </button>
            <button className="primary" onClick={() => action("refresh")}>
              Collect results
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
