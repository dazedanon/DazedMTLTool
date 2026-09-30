import { useEffect, useRef, useState } from "react";
import { api } from "./bridge";
import { saveBeforeClose } from "./lifecycle";
import type {
  GuidanceDocuments,
  LenRecord,
  LenState,
  LenValues,
} from "./types";

export function LenWorkspace({
  visible,
  onNavigate,
}: {
  visible: boolean;
  onNavigate: (page: string, source?: string) => void;
}) {
  const [state, setState] = useState<LenState | null>(null);
  const [source, setSource] = useState("");
  const [values, setValues] = useState<LenValues | null>(null);
  const [drafts, setDrafts] = useState<GuidanceDocuments>({});
  const [documents, setDocuments] = useState<GuidanceDocuments | null>(null);
  const [documentName, setDocumentName] = useState("glossary");
  const [customName, setCustomName] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [reference, setReference] = useState({
    title: "",
    original: "",
    translated: "",
  });
  const [pair, setPair] = useState(false);
  const pending = useRef({
    record: null as LenRecord | null,
    values: null as LenValues | null,
    drafts: {} as GuidanceDocuments,
    version: 0,
    saved: 0,
  });
  const queue = useRef(Promise.resolve());
  const copyJob = useRef("");
  const report = (e: unknown) =>
    setError(e instanceof Error ? e.message : String(e));
  function flush() {
    const work = queue.current
      .catch(() => {})
      .then(async () => {
        const p = pending.current;
        while (p.record && p.values && p.saved !== p.version) {
          const version = p.version;
          const saved = await api.lenSave({
            project_id: p.record.id,
            revision: p.record.revision,
            values: p.values,
            drafts: p.drafts,
          });
          p.record = saved;
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
  function adopt(next: LenState) {
    setState(next);
    setSource(next.project?.source || "");
    setValues(next.project?.values || null);
    setDrafts(next.project?.documents || {});
    setDocuments(null);
    pending.current = {
      record: next.project,
      values: next.project?.values || null,
      drafts: next.project?.documents || {},
      version: 0,
      saved: 0,
    };
  }
  async function refresh() {
    setState(await api.lenState(pending.current.record?.id));
  }
  useEffect(() => {
    api.lenState().then(adopt).catch(report);
    return saveBeforeClose(flush);
  }, []);
  useEffect(() => {
    if (!visible) return;
    const timer = setInterval(
      () => refresh().catch(report),
      state?.active ? 200 : 3000,
    );
    return () => clearInterval(timer);
  }, [visible, state?.active]);
  useEffect(() => {
    const timer = setTimeout(() => flush().catch(report), 400);
    return () => clearTimeout(timer);
  }, [values, drafts]);
  useEffect(() => {
    const job = state?.jobs.find((j) => j.id === copyJob.current);
    if (!job || job.status === "running") return;
    copyJob.current = "";
    if (job.status === "complete" && typeof job.result?.handoff === "string") {
      api
        .copyText(job.result.handoff)
        .then(() =>
          setNotice(
            "Handoff copied. Paste it into your coding assistant; its progress will appear here.",
          ),
        )
        .catch(report);
    } else setError(job.message);
  }, [state?.jobs]);
  function update(change: Partial<LenValues>) {
    const next = { ...pending.current.values!, ...change };
    pending.current.values = next;
    pending.current.version++;
    setValues(next);
  }
  function edit(name: string, text: string, revision: string) {
    const next = { ...pending.current.drafts, [name]: { text, revision } };
    pending.current.drafts = next;
    pending.current.version++;
    setDrafts(next);
  }
  async function open(folder: string) {
    await flush();
    adopt(await api.lenOpen(folder));
  }
  async function action(name: string, options: Record<string, unknown> = {}) {
    await flush();
    const record = pending.current.record!;
    const job = await api.lenAction({
      project_id: record.id,
      revision: record.revision,
      action: name,
      options,
    });
    if (name === "prepare") copyJob.current = job.id;
    await refresh();
  }
  const project = state?.project;
  const disabled = busy || !!state?.active;
  const handoffJob = state?.jobs.find(
    (j) =>
      j.action === "prepare" &&
      j.status === "complete" &&
      j.result?.handoff &&
      values &&
      Object.entries(values).every(
        ([key, value]) =>
          (j.result?.values as Record<string, unknown>)?.[key] === value,
      ),
  );
  const selectedDoc = drafts[documentName] || documents?.[documentName];
  return (
    <section className="len-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Agent workflow</span>
          <h1>Len’s Method</h1>
          <p>
            Prepare a complete translation handoff and follow the agent’s saved
            progress.
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
        <h2>Game folder</h2>
        <div className="actions">
          <input
            aria-label="Len game folder"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="Choose any supported game folder"
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
            Open game
          </button>
        </div>
        {!!state?.projects.length && (
          <label>
            Recent projects
            <select
              aria-label="Recent Len projects"
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
            <h2>Translation scope</h2>
            <fieldset disabled={disabled}>
              <label>
                Translation mode
                <select
                  value={values.mode}
                  onChange={(e) =>
                    update({ mode: e.target.value as LenValues["mode"] })
                  }
                >
                  <option value="local">Agent Translation</option>
                  <option value="api">API Batch Translation</option>
                </select>
              </label>
              <p className="muted">
                {values.mode === "local"
                  ? "Use your coding assistant’s existing access. The handoff does not authorize translation API calls or hosted image generation."
                  : "The agent prepares a complete request plan, quotes it using your saved API settings, and asks for any missing spending authorization before submitting a batch."}
              </p>
              <div className="len-options">
                <label>
                  <input
                    type="checkbox"
                    checked={values.include_images}
                    onChange={(e) =>
                      update({ include_images: e.target.checked })
                    }
                  />
                  Translate images containing Japanese text
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={values.include_glossary_base}
                    onChange={(e) =>
                      update({ include_glossary_base: e.target.checked })
                    }
                  />
                  Include DazedTL’s base glossary
                </label>
                <label>
                  <input
                    type="checkbox"
                    disabled={!state.forge_supported}
                    checked={values.install_forge}
                    onChange={(e) =>
                      update({ install_forge: e.target.checked })
                    }
                  />
                  Install Forge for MV/MZ
                </label>
              </div>
              <label>
                Additional project instructions
                <textarea
                  aria-label="Len project instructions"
                  value={values.instructions}
                  onChange={(e) => update({ instructions: e.target.value })}
                  placeholder="Scope, terminology, or delivery requirements"
                />
              </label>
            </fieldset>
            <div className="actions">
              <button
                className="primary"
                disabled={disabled}
                onClick={() => run(() => action("prepare"))}
              >
                Prepare & copy handoff
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await flush();
                    setDocuments(await api.lenDocuments(project.id));
                  })
                }
              >
                Review shared guidance
              </button>
              <button
                disabled={disabled}
                onClick={() =>
                  run(async () => {
                    await flush();
                    onNavigate("version", project.source);
                  })
                }
              >
                Git version updates
              </button>
              {values.mode === "api" && (
                <>
                  <button onClick={() => onNavigate("settings")}>
                    API settings
                  </button>
                  <button onClick={() => onNavigate("batches")}>
                    Batch history
                  </button>
                </>
              )}
            </div>
            <p className="muted">
              Options save automatically. Preparing creates or refreshes the
              game’s local Len workspace and handoff.
            </p>
          </div>
          {documents && (
            <div className="workflow-card">
              <h2>Shared game guidance</h2>
              <label>
                Document
                <select
                  value={documentName}
                  onChange={(e) => setDocumentName(e.target.value)}
                >
                  {[
                    ...new Set([
                      ...Object.keys(documents),
                      ...Object.keys(drafts),
                    ]),
                  ].map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="actions">
                <input
                  aria-label="Custom Len skill name"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  placeholder="Custom skill name"
                />
                <button
                  disabled={!customName.trim() || busy}
                  onClick={() => {
                    const name = "custom:" + customName.trim();
                    edit(name, "", "");
                    setDocumentName(name);
                    setCustomName("");
                  }}
                >
                  Add custom skill
                </button>
              </div>
              <textarea
                aria-label="Len guidance text"
                value={selectedDoc?.text || ""}
                onChange={(e) =>
                  edit(
                    documentName,
                    e.target.value,
                    selectedDoc?.revision || "",
                  )
                }
              />
              <div className="actions">
                <button
                  disabled={disabled || !drafts[documentName]}
                  onClick={() =>
                    run(async () => {
                      await flush();
                      const doc = pending.current.drafts[documentName];
                      setDocuments(
                        await api.lenDocumentSave({
                          project_id: project.id,
                          name: documentName,
                          ...doc,
                        }),
                      );
                      const next = { ...pending.current.drafts };
                      delete next[documentName];
                      pending.current.drafts = next;
                      pending.current.version++;
                      setDrafts(next);
                      await flush();
                    })
                  }
                >
                  Save guidance to game
                </button>
                <span className="muted">
                  Recovery drafts stay in this desktop profile until saved to
                  the game.
                </span>
              </div>
            </div>
          )}
          <details className="workflow-card">
            <summary>Reference translations</summary>
            <p>
              Register embedded DazedTL translations or a matching Japanese /
              English pair.
            </p>
            {state.references?.map((r) => (
              <div className="actions" key={r.id}>
                <span>
                  {r.title} · {r.mode}
                </span>
                <button
                  disabled={disabled}
                  onClick={() =>
                    run(() => action("reference_remove", { id: r.id }))
                  }
                >
                  Remove {r.title}
                </button>
              </div>
            ))}
            <label>
              Reference title
              <input
                value={reference.title}
                onChange={(e) =>
                  setReference({ ...reference, title: e.target.value })
                }
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={pair}
                onChange={(e) => setPair(e.target.checked)}
              />
              Use a Japanese / English pair
            </label>
            {(pair ? ["original", "translated"] : ["translated"]).map((key) => (
              <label key={key}>
                {key === "original" ? "Japanese folder" : "English folder"}
                <div className="actions">
                  <input
                    value={reference[key as "original" | "translated"]}
                    onChange={(e) =>
                      setReference({ ...reference, [key]: e.target.value })
                    }
                  />
                  <button
                    onClick={() =>
                      run(async () => {
                        const path = await api.chooseFolder();
                        if (path) setReference({ ...reference, [key]: path });
                      })
                    }
                  >
                    Browse
                  </button>
                </div>
              </label>
            ))}
            <div className="actions">
              <button
                disabled={disabled}
                onClick={() =>
                  run(() =>
                    action(
                      pair ? "reference_pair" : "reference_add",
                      reference,
                    ),
                  )
                }
              >
                Add reference
              </button>
              <button
                disabled={disabled}
                onClick={() => run(() => action("reference_build"))}
              >
                Build reference matches
              </button>
            </div>
          </details>
          <div className="workflow-card">
            <div className="actions">
              <h2>Translation progress</h2>
              <button disabled={busy} onClick={() => run(refresh)}>
                Refresh progress
              </button>
            </div>
            {state.progress?.warnings?.map((w) => (
              <div className="warning-banner" role="alert" key={w}>
                {w}
              </div>
            ))}
            <p>
              {state.progress?.updated_at
                ? `Updated ${new Date(state.progress.updated_at).toLocaleString()}`
                : "Waiting for the first progress update."}
            </p>
            <div className="len-metrics">
              {Object.entries(state.metrics || {}).map(([key, metric]) => (
                <div key={key}>
                  <h3>
                    {key === "reviewed"
                      ? "Reviewed text"
                      : key === "images"
                        ? "Images"
                        : "Translated text"}
                  </h3>
                  <progress max="100" value={metric.value} />
                  <p>{metric.label}</p>
                  <small>{metric.counts}</small>
                </div>
              ))}
            </div>
            <p>{state.estimate}</p>
            <div className="len-phases">
              {Object.entries(state.phases || {}).map(([key, phase]) => (
                <span key={key}>
                  {phase.label}: {phase.status}
                </span>
              ))}
            </div>
            {state.progress?.blocker && (
              <p role="alert">Blocker: {state.progress.blocker}</p>
            )}
            {state.progress?.next_action && (
              <p>Next: {state.progress.next_action}</p>
            )}
            {state.status && (
              <details>
                <summary>Agent status report</summary>
                <pre>{state.status}</pre>
              </details>
            )}
          </div>
          {handoffJob && (
            <details className="workflow-card">
              <summary>Prepared handoff</summary>
              <pre>{String(handoffJob.result!.handoff)}</pre>
              <button
                onClick={() =>
                  run(async () => {
                    await api.copyText(String(handoffJob.result!.handoff));
                    setNotice("Handoff copied.");
                  })
                }
              >
                Copy handoff again
              </button>
            </details>
          )}
          <div className="actions">
            {Object.entries(state.paths).map(([name, path]) => (
              <button
                key={name}
                onClick={() =>
                  run(async () => {
                    const error = await api.openExport(path);
                    if (error) throw new Error(error);
                  })
                }
              >
                Open{" "}
                {name === "skill"
                  ? "Len skill"
                  : name === "game"
                    ? "game folder"
                    : "Len workspace"}
              </button>
            ))}
          </div>
          {!!state.jobs.length && (
            <div className="workflow-card">
              <h2>Activity</h2>
              {state.jobs.slice(0, 5).map((job) => (
                <details key={job.id} open={job.id === state.active}>
                  <summary>
                    {job.label} · {job.status}
                  </summary>
                  <p>{job.message}</p>
                  <pre>{job.log.join("\n")}</pre>
                  {job.status === "running" && (
                    <button
                      onClick={() =>
                        run(async () => {
                          await api.workflowStop(job.id);
                          await refresh();
                        })
                      }
                    >
                      Stop action
                    </button>
                  )}
                </details>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
