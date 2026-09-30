import { useEffect, useState } from "react";
import { api } from "./bridge";
import { flushEditorDrafts, setEditorDraft, useEditorDrafts } from "./drafts";

const labels: Record<string, string> = {
  "glossary.txt": "Glossary",
  "skills/game.md": "Game instructions",
  "skills/quirks.md": "Voice & quirks",
};
export function ContextEditor({
  projectId,
  report,
}: {
  projectId: string;
  report: (error: unknown) => void;
}) {
  const [documents, setDocuments] = useState<Record<string, string>>({});
  const editor = useEditorDrafts(projectId);
  const drafts = editor.context;
  const [selected, setSelected] = useState("glossary.txt");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    let active = true;
    api
      .context(projectId)
      .then((value) => {
        if (active) {
          setDocuments(value.documents);
          setSelected("glossary.txt");
        }
      })
      .catch(report);
    return () => {
      active = false;
    };
  }, [projectId]);
  function choose(name: string) {
    setSelected(name);
    setSaved(false);
  }
  function edit(text: string) {
    setEditorDraft(
      projectId,
      "context",
      selected,
      text === documents[selected] ? undefined : text,
    );
    setSaved(false);
  }
  async function save() {
    setBusy(true);
    try {
      const value = await api.saveContext({
        project_id: projectId,
        name: selected,
        text: drafts[selected] ?? documents[selected] ?? "",
      });
      setDocuments(value.documents);
      setEditorDraft(projectId, "context", selected);
      await flushEditorDrafts(projectId);
      setSaved(true);
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="context-workspace">
      <div
        className="context-files"
        role="group"
        aria-label="Project context documents"
      >
        {Object.keys(documents).map((name) => (
          <button
            key={name}
            disabled={busy}
            aria-pressed={selected === name}
            onClick={() => choose(name)}
          >
            {labels[name] || name.replace("skills/", "").replace(".md", "")}
            {drafts[name] !== undefined ? " · unsaved" : ""}
          </button>
        ))}
      </div>
      <div className="guidance">
        <label htmlFor="project-context">
          <h2>{labels[selected] || selected}</h2>
        </label>
        <p>
          Edits stay in this isolated project. Existing runs keep the context
          they started with.
        </p>
        <textarea
          id="project-context"
          aria-label="Project context text"
          value={drafts[selected] ?? documents[selected] ?? ""}
          disabled={busy || !editor.ready}
          onChange={(e) => edit(e.target.value)}
        />
        <div className="actions">
          <span className="muted" role="status">
            {saved
              ? "Saved to this project."
              : editor.pending
                ? "Saving recovery draft…"
                : Object.keys(drafts).length
                  ? "Recovery draft saved. Save context to use these edits in new runs."
                  : "Save context to use edits in new runs."}
          </span>
          <button
            className="primary"
            disabled={busy || !Object.keys(documents).length}
            onClick={save}
          >
            Save context
          </button>
        </div>
      </div>
    </div>
  );
}
