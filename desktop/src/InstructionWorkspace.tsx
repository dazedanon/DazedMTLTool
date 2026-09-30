import { useEffect, useRef, useState } from "react";
import { Save, Upload } from "lucide-react";
import { api } from "./bridge";
import { saveBeforeClose } from "./lifecycle";
import type { InstructionDraft, SharedInstruction } from "./types";

export default function InstructionWorkspace() {
  const [catalog, setCatalog] = useState<
    Awaited<ReturnType<typeof api.instructionCatalog>>
  >([]);
  const [document, setDocument] = useState<SharedInstruction | null>(null);
  const [draft, setDraft] = useState<InstructionDraft | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const latest = useRef<InstructionDraft | null>(null);
  const dirtyRef = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const pending = useRef(Promise.resolve<unknown>(undefined));
  const report = (error: unknown) =>
    setError(error instanceof Error ? error.message : String(error));
  const dirty = !!(draft && document && draft.text !== document.text);
  function accept(value: SharedInstruction, recover = false) {
    const next = {
      name: value.name,
      revision: recover && value.draft ? value.draft.revision : value.revision,
      text: recover && value.draft ? value.draft.text : value.text,
    };
    setDocument(value);
    setDraft(next);
    latest.current = next;
    dirtyRef.current = next.text !== value.text;
  }
  async function flush() {
    clearTimeout(timer.current);
    await pending.current;
    if (latest.current && dirtyRef.current)
      await api.instructionDraft(latest.current);
  }
  useEffect(() => saveBeforeClose(flush), []);
  useEffect(() => {
    api.instructionCatalog().then(setCatalog).catch(report);
    api
      .instructionGet("skills/system.md")
      .then((value) => accept(value, true))
      .catch(report);
  }, []);
  function edit(text: string, revision = draft?.revision) {
    if (!document || !revision) return;
    const next = { name: document.name, revision, text };
    setDraft(next);
    latest.current = next;
    dirtyRef.current = true;
    setStatus("");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      pending.current = pending.current
        .catch(() => {})
        .then(() => api.instructionDraft(next));
      pending.current.catch(report);
    }, 350);
  }
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await fn();
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="instruction-workspace">
      <div className="page-heading">
        <div>
          <p className="eyebrow">SHARED INSTRUCTIONS</p>
          <h1>Shape your translation instructions.</h1>
          <p>
            Customize prompts for this desktop profile. New runs use saved
            instructions; existing runs retain their snapshots.
          </p>
        </div>
      </div>
      {error && (
        <p className="banner error" role="alert">
          {error}
        </p>
      )}
      <div className="library-layout">
        <nav className="library-list" aria-label="Shared instruction files">
          <label>
            Find instructions
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              type="search"
            />
          </label>
          {catalog
            .filter((item) =>
              `${item.title} ${item.name}`
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((item) => (
              <button
                key={item.name}
                disabled={busy}
                aria-current={document?.name === item.name ? "page" : undefined}
                onClick={() =>
                  action(async () => {
                    await flush();
                    accept(await api.instructionGet(item.name), true);
                  })
                }
              >
                {item.title}
                <small>
                  {item.customized ? "Customized" : "Bundled default"}
                </small>
              </button>
            ))}
        </nav>
        {document && draft ? (
          <fieldset className="instruction-editor" disabled={busy}>
            <div className="section-heading">
              <h2>
                {catalog.find((item) => item.name === document.name)?.title}
              </h2>
              <span className="tag">
                {document.customized ? "Profile override" : "Bundled default"}
              </span>
            </div>
            <p className="muted">{document.name}</p>
            <p className="muted">
              Keep template placeholders and section markers. Game-specific
              instructions belong in the selected game’s context.
            </p>
            {document.bundled_changed && (
              <p className="banner">
                The application includes an updated default for this file. Your
                customization is retained. Compare the bundled default before
                saving.
              </p>
            )}
            {draft.revision !== document.revision && (
              <p className="banner error">
                This recovered draft is based on older instructions. Copy any
                edits you need, then reload the saved file before saving.
              </p>
            )}
            <label className="instruction-text-label">
              Instruction text
              <textarea
                aria-label="Instruction text"
                spellCheck={false}
                value={draft.text}
                onChange={(e) => edit(e.target.value)}
              />
            </label>
            <div className="actions">
              <button
                className="primary"
                disabled={!dirty || draft.revision !== document.revision}
                onClick={() =>
                  action(async () => {
                    await flush();
                    accept(await api.instructionSave(draft));
                    setCatalog(await api.instructionCatalog());
                    setStatus(
                      "Saved. New runs and copied prompts use these instructions.",
                    );
                  })
                }
              >
                <Save size={15} />
                Save instructions
              </button>
              <button
                className="secondary"
                onClick={() =>
                  action(async () => {
                    const source =
                      await api.chooseConfigurationFile("instruction");
                    if (source) {
                      const imported = await api.instructionImport(
                        document.name,
                        source,
                      );
                      edit(imported.text);
                      setStatus(
                        "Imported into this draft. Review and save to apply.",
                      );
                    }
                  })
                }
              >
                <Upload size={15} />
                Import this file
              </button>
              <button
                onClick={() =>
                  action(async () => {
                    await flush();
                    const current = await api.instructionGet(document.name);
                    accept(current);
                    await api.instructionDraft({
                      name: current.name,
                      revision: current.revision,
                      text: current.text,
                    });
                    setStatus("Saved instructions reloaded.");
                  })
                }
              >
                Reload saved file
              </button>
              <button
                onClick={() => {
                  edit(document.default, document.revision);
                  setStatus(
                    "Bundled default loaded into the draft. Save to apply.",
                  );
                }}
              >
                Use bundled default
              </button>
            </div>
            <p className="muted" role="status">
              {busy
                ? "Working…"
                : status ||
                  (dirty
                    ? "Draft saved automatically · save to apply"
                    : "Up to date")}
            </p>
            <details>
              <summary>Compare bundled default</summary>
              <pre>{document.default}</pre>
            </details>
          </fieldset>
        ) : (
          <p className="muted">Loading instructions…</p>
        )}
      </div>
    </section>
  );
}
