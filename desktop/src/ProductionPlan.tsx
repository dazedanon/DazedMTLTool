import { useEffect, useRef, useState } from "react";
import { ArrowRight, Play, Search, Settings2, X } from "lucide-react";
import { api } from "./bridge";
import type { EngineSettings, Job, NativePreview, Project } from "./types";
import { hasUnsavedContext } from "./drafts";

const defaults: EngineSettings = {
  width: 60,
  faceWidth: 50,
  listWidth: 100,
  noteWidth: 75,
  batchsize: 8,
  FIRSTLINESPEAKERS: false,
  INLINE401SPEAKERS: false,
  FACENAME101: false,
  AUTONAMEPOPUP101: false,
  CODE408: false,
};
const plans = new Map<
  string,
  {
    phase: string;
    query: string;
    selected: string[];
    settings: EngineSettings;
    limit: number;
  }
>();
const speakerOptions = [
  ["INLINE401SPEAKERS", "Names appear inside dialogue"],
  ["FIRSTLINESPEAKERS", "The first dialogue line is a speaker name"],
  ["FACENAME101", "Use the configured face-name mapping"],
  ["AUTONAMEPOPUP101", "Use AutoNamePopup speaker information"],
  ["CODE408", "Include displayed comments from supported plugins"],
] as const;

export function ProductionPlan({
  project,
  mode,
  active,
  onStarted,
  report,
}: {
  project: Project;
  mode: string;
  active: boolean;
  onStarted: (job: Job) => void;
  report: (error: unknown) => void;
}) {
  const savedPlan = plans.get(project.id);
  const [phase, setPhase] = useState(savedPlan?.phase || "standard");
  const [query, setQuery] = useState(savedPlan?.query || "");
  const [selected, setSelected] = useState<string[]>(savedPlan?.selected || []);
  const [settings, setSettings] = useState<EngineSettings>(
    savedPlan?.settings || project.settings || defaults,
  );
  const [limit, setLimit] = useState(savedPlan?.limit || 10);
  const [preview, setPreview] = useState<NativePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const anchor = useRef<number | null>(null);
  const eligible = project.files.filter(
    (file) => file.phase && (phase === "standard" || file.phase === phase),
  );
  const visible = eligible.filter((file) =>
    file.name.toLowerCase().includes(query.toLowerCase()),
  );
  const contextDirty = hasUnsavedContext(project.id);
  useEffect(() => {
    plans.set(project.id, { phase, query, selected, settings, limit });
  }, [project.id, phase, query, selected, settings, limit]);
  useEffect(() => setPreview(null), [mode, selected, settings, limit, phase]);
  function selection() {
    return {
      project_id: project.id,
      files: selected,
      phase,
      mode,
      settings,
      request_limit: limit,
    };
  }
  async function prepare() {
    setBusy(true);
    try {
      setPreview(await api.nativePreview(selection()));
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    setBusy(true);
    try {
      const job = await api.startNative(selection());
      setPreview(null);
      onStarted(job);
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  function choose(index: number, checked: boolean, shift: boolean) {
    const indices =
      shift && anchor.current !== null
        ? [Math.min(anchor.current, index), Math.max(anchor.current, index)]
        : [index, index];
    const names = visible
      .slice(indices[0], indices[1] + 1)
      .map((file) => file.name);
    setSelected((previous) =>
      checked
        ? [...new Set([...previous, ...names])]
        : previous.filter((name) => !names.includes(name)),
    );
    anchor.current = index;
  }
  return (
    <div className="production-plan">
      <div className="file-plan-toolbar">
        <label>
          Text scope
          <select
            aria-label="File translation scope"
            value={phase}
            onChange={(event) => {
              setPhase(event.target.value);
              setSelected([]);
              anchor.current = null;
            }}
          >
            <option value="standard">Database + dialogue</option>
            <option value="database">Database text</option>
            <option value="dialogue">Dialogue & choices</option>
          </select>
        </label>
        <span className="muted">
          Existing RPG Maker rules handle names, context, wrapping, and original
          text.
        </span>
      </div>
      <div className="selection-toolbar">
        <label className="search">
          <Search size={16} />
          <input
            aria-label="Find game files"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              anchor.current = null;
            }}
            placeholder="Find a map or database file"
          />
        </label>
        <button
          className="quiet"
          onClick={() =>
            setSelected((previous) => [
              ...new Set([...previous, ...visible.map((file) => file.name)]),
            ])
          }
        >
          Select visible
        </button>
        <button
          className="quiet"
          disabled={!selected.length}
          onClick={() => setSelected([])}
        >
          Clear files
        </button>
      </div>
      <div className="selection-summary">
        <span>
          {selected.length} file{selected.length === 1 ? "" : "s"} selected
        </span>
        <span>{visible.length} visible · Shift-click selects a range</span>
      </div>
      <div className="text-list file-list" role="group" aria-label="Game files">
        {visible.map((file, index) => (
          <label
            className={`text-row ${selected.includes(file.name) ? "selected" : ""}`}
            key={file.name}
          >
            <input
              type="checkbox"
              aria-label={`Translate ${file.name}`}
              checked={selected.includes(file.name)}
              onChange={(e) =>
                choose(
                  index,
                  e.target.checked,
                  Boolean((e.nativeEvent as MouseEvent).shiftKey),
                )
              }
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
                  e.preventDefault();
                  setSelected((previous) => [
                    ...new Set([...previous, ...visible.map((f) => f.name)]),
                  ]);
                }
              }}
            />
            <div>
              <span className="source-text">{file.name}</span>
              <small>
                {project.working_files?.[file.name]
                  ? "Reviewed working copy"
                  : "Original snapshot"}
              </small>
            </div>
            <span className="category-label">
              {file.phase === "database" ? "Database" : "Dialogue"}
            </span>
          </label>
        ))}
        {!visible.length && (
          <p className="empty-inline">
            No supported files match this selection.
          </p>
        )}
      </div>
      <details className="engine-settings">
        <summary>
          <Settings2 size={15} />
          Text layout & speaker settings{" "}
          <span>
            {settings.width} / {settings.faceWidth} character dialogue widths
          </span>
        </summary>
        <div className="width-grid">
          {(
            [
              ["width", "Dialogue"],
              ["faceWidth", "With a face"],
              ["listWidth", "Lists & help"],
              ["noteWidth", "Notes"],
              ["batchsize", "Entries per request"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                aria-label={label}
                type="number"
                min={1}
                max={key === "batchsize" ? 8 : 500}
                value={settings[key]}
                onChange={(e) =>
                  setSettings({ ...settings, [key]: Number(e.target.value) })
                }
              />
            </label>
          ))}
        </div>
        <div className="speaker-options">
          {speakerOptions.map(([key, label]) => (
            <label className="check" key={key}>
              <input
                type="checkbox"
                checked={settings[key]}
                onChange={(e) =>
                  setSettings({ ...settings, [key]: e.target.checked })
                }
              />
              {label}
            </label>
          ))}
        </div>
        <p className="footnote">
          Settings are saved with this workspace and frozen for each run.
          Scripts and variable translation remain outside this scope.
        </p>
      </details>
      {mode === "live" && (
        <div className="request-allowance">
          <label>
            New API requests before pausing
            <input
              type="number"
              aria-label="API request allowance"
              min={1}
              max={25}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            />
          </label>
          <span>
            At most ${(limit * 0.02).toFixed(2)} reserved per attempt · $5
            cumulative cap
          </span>
        </div>
      )}
      <div className="selection-actions">
        <span className="muted">
          {contextDirty
            ? "Save the pending project guidance edits before starting."
            : "Reviewed working files carry forward automatically."}
        </span>
        <button
          className="primary"
          disabled={!selected.length || busy || active || contextDirty}
          onClick={prepare}
        >
          Preview file translation
          <ArrowRight size={16} />
        </button>
      </div>
      {preview && (
        <div className="run-preview">
          <div className="section-heading">
            <h2>Review file translation</h2>
            <button
              className="icon-button"
              aria-label="Close file run preview"
              onClick={() => setPreview(null)}
            >
              <X size={17} />
            </button>
          </div>
          <dl>
            <dt>Scope</dt>
            <dd>
              {preview.files} files ·{" "}
              {preview.phase === "standard"
                ? "database and dialogue"
                : preview.phase}
            </dd>
            <dt>Method</dt>
            <dd>{preview.model}</dd>
            <dt>Budget reservation</dt>
            <dd>
              ${preview.maximum_reserved_usd.toFixed(2)} maximum for this
              attempt
            </dd>
            <dt>Project context</dt>
            <dd>
              Glossary, game instructions, shared translation rules, and saved
              line widths
            </dd>
            {preview.dependencies.length > 0 && (
              <>
                <dt>Required preparation</dt>
                <dd>
                  {preview.dependencies.join(", ")} is included to preserve
                  runtime actor-name references.
                </dd>
              </>
            )}
            <dt>Destination</dt>
            <dd>{preview.destination}</dd>
          </dl>
          <details>
            <summary>Files in this run</summary>
            <p className="scope-filenames">{preview.filenames.join(", ")}</p>
          </details>
          <div className="actions">
            <span className="muted">
              {mode === "offline"
                ? "Produces clearly labeled test text with no API calls."
                : "Stops safely when the request allowance is reached."}
            </span>
            <button
              className="primary"
              disabled={busy || active}
              onClick={start}
            >
              <Play size={15} />
              Start file translation
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
