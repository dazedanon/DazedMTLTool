import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  Check,
  ChevronDown,
  FolderOpen,
  House,
  Images,
  Languages,
  NotebookPen,
  GitBranch,
  Files,
  Package,
  Play,
  Search,
  Settings2,
  ShieldCheck,
  Square,
  Terminal,
  X,
} from "lucide-react";
import type { Job, Preview, ReviewPage, Snapshot, TextRecord } from "./types";
import "./style.css";
import { api } from "./bridge";
import { ProductionPlan } from "./ProductionPlan";
import { ContextEditor } from "./ContextEditor";
import { flushEditorDrafts, setEditorDraft, useEditorDrafts } from "./drafts";
import { cancelClose, prepareToClose } from "./lifecycle";

const InstructionWorkspace = lazy(() => import("./InstructionWorkspace"));
const GuideWorkspace = lazy(() => import("./GuideWorkspace"));
const UpdateWorkspace = lazy(() => import("./UpdateWorkspace"));
const AssetWorkspace = lazy(() => import("./AssetWorkspace"));
const BatchWorkspace = lazy(() => import("./BatchWorkspace"));
const EvaluationWorkspace = lazy(() => import("./EvaluationWorkspace"));
const GuidedWorkspace = lazy(() =>
  import("./GuidedWorkspace").then((module) => ({
    default: module.GuidedWorkspace,
  })),
);
const SettingsWorkspace = lazy(() =>
  import("./SettingsWorkspace").then((module) => ({
    default: module.SettingsWorkspace,
  })),
);

const ManualWorkspace = lazy(() =>
  import("./ManualWorkspace").then((module) => ({
    default: module.ManualWorkspace,
  })),
);

const LenWorkspace = lazy(() =>
  import("./LenWorkspace").then((module) => ({ default: module.LenWorkspace })),
);

const VersionWorkspace = lazy(() =>
  import("./VersionWorkspace").then((module) => ({
    default: module.VersionWorkspace,
  })),
);

const navigation = [
  { id: "overview", label: "Overview", icon: House },
  { id: "workflow", label: "Guided workflow", icon: ArrowRight },
  { id: "translate", label: "Translate", icon: Languages },
  { id: "len", label: "Len’s Method", icon: NotebookPen },
  { id: "version", label: "Git version updates", icon: GitBranch },
  { id: "manual", label: "Manual engines", icon: Files },
  { id: "batches", label: "Batch history", icon: Files },
  { id: "evaluation", label: "Evaluation", icon: ShieldCheck },
  { id: "instructions", label: "Shared instructions", icon: NotebookPen },
  { id: "guide", label: "Guide", icon: Files },
  { id: "images", label: "Images", icon: Images },
  { id: "review", label: "Review & test", icon: ShieldCheck },
  { id: "release", label: "Release", icon: Package },
];
const money = (value: number) =>
  `$${value.toFixed(value > 0 && value < 0.01 ? 5 : 2)}`;

const progressLabel = (job: Job) =>
  job.image
    ? `${job.status === "complete" ? 1 : 0}/1 image`
    : job.native
      ? `${job.native.completed_files.length}/${job.native.files.length} files`
      : `${Object.keys(job.results).length}/${job.records.length} entries`;
const jobLabel = (job: Job) =>
  job.image
    ? `Image preview · ${job.image.name}`
    : job.native
      ? `${job.mode === "offline" ? "Offline file test" : "RPG Maker translation"} · ${job.native.phase}`
      : job.mode === "offline"
        ? "Offline text sample"
        : "Luna text sample";

function App() {
  const [state, setState] = useState<Snapshot | null>(null);
  const [page, setPage] = useState("overview");
  const isProjectPage = ["overview", "translate", "review", "release"].includes(
    page,
  );
  const pageLabel =
    navigation.find((item) => item.id === page)?.label ||
    (page === "updates" ? "Updates & rollback" : "Settings");
  const [instructionsVisited, setInstructionsVisited] = useState(false);
  const [guideVisited, setGuideVisited] = useState(false);
  useEffect(() => {
    if (page === "instructions") setInstructionsVisited(true);
    if (page === "guide") setGuideVisited(true);
  }, [page]);
  const [settingsVisited, setSettingsVisited] = useState(false);
  const [imagesVisited, setImagesVisited] = useState(false);
  const [assetRequested, setAssetRequested] = useState<{
    source: string;
    key: number;
  }>();
  const [manualRequested, setManualRequested] = useState<{
    source: string;
    context: string;
    engine: string;
    key: number;
  }>();
  const [manualVisited, setManualVisited] = useState(false);
  const [batchesVisited, setBatchesVisited] = useState(false);
  const [evaluationVisited, setEvaluationVisited] = useState(false);
  const [lenVisited, setLenVisited] = useState(false);
  const [versionSource, setVersionSource] = useState<{
    source: string;
    key: number;
  }>();
  const [versionVisited, setVersionVisited] = useState(false);
  useEffect(() => {
    if (page === "version") setVersionVisited(true);
  }, [page]);
  useEffect(() => {
    if (page === "len") setLenVisited(true);
  }, [page]);
  const [workflowVisited, setWorkflowVisited] = useState(false);
  useEffect(() => {
    if (page === "workflow") setWorkflowVisited(true);
  }, [page]);
  useEffect(() => {
    if (page === "manual") setManualVisited(true);
    if (page === "batches") setBatchesVisited(true);
    if (page === "evaluation") setEvaluationVisited(true);
    if (page === "images") setImagesVisited(true);
  }, [page]);
  useEffect(() => {
    if (page === "settings") setSettingsVisited(true);
  }, [page]);
  const [tab, setTab] = useState("files");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [source, setSource] = useState("");
  const [original, setOriginal] = useState(true);
  const [importing, setImporting] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [mode, setMode] = useState("offline");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [reviewData, setReviewData] = useState<ReviewPage | null>(null);
  const [reviewOffset, setReviewOffset] = useState(0);
  const [reviewQuery, setReviewQuery] = useState("");
  const [pendingOnly, setPendingOnly] = useState(false);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [runId, setRunId] = useState("");
  const [reviewId, setReviewId] = useState("");
  const [exportPath, setExportPath] = useState("");
  const [engineLog, setEngineLog] = useState("");
  const [imageFocus, setImageFocus] = useState<
    { id: string; key: number } | undefined
  >();
  const projectId = useRef("");
  const generation = useRef(0);
  const readySent = useRef(false);
  const mainPane = useRef<HTMLElement | null>(null);
  const project = state?.project;
  const editorDrafts = useEditorDrafts(project?.id || "");
  const [serviceStopped, setServiceStopped] = useState("");
  useEffect(() => api?.onBeforeClose(prepareToClose, cancelClose), []);
  useEffect(() => {
    if (state?.preferences)
      api.setScale(state.preferences.font_scale).catch(report);
  }, [state?.preferences?.font_scale]);
  useEffect(() => api?.onServiceStopped(setServiceStopped), []);
  const job =
    state?.jobs.find((item) => item.id === runId && !item.image) ||
    state?.jobs.find((item) => !item.image);
  const statusJob = state?.jobs[0];
  const reviewed = job?.native
    ? job.native.stats.reviewed
    : job
      ? Object.values(job.results).filter((r) => r.reviewed).length
      : 0;
  const completed = job?.native
    ? job.native.stats.total
    : job
      ? Object.keys(job.results).length
      : 0;
  const resultTotal = job?.native
    ? job.native.stats.total
    : job?.records.length || 0;
  const displayRecords = job?.native
    ? reviewData?.job_id === job.id
      ? reviewData.records
      : []
    : job?.records || [];
  const displayResults = job?.native
    ? reviewData?.job_id === job.id
      ? reviewData.results
      : {}
    : job?.results || {};
  const reviewRecord = displayRecords.find((r) => r.id === reviewId);
  const draft =
    reviewRecord && job
      ? (editorDrafts.review[job.id + ":" + reviewRecord.id] ??
        displayResults[reviewRecord.id]?.text ??
        "")
      : "";
  const hasUnsavedReview = job
    ? Object.keys(editorDrafts.review).some((key) =>
        key.startsWith(job.id + ":"),
      )
    : false;
  useEffect(() => {
    mainPane.current?.scrollTo(0, 0);
  }, [page, project?.id]);
  function report(value: unknown) {
    setError(value instanceof Error ? value.message : String(value));
  }
  async function run<T>(
    label: string,
    action: () => Promise<T>,
  ): Promise<T | undefined> {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      return await action();
    } catch (e) {
      report(e);
    } finally {
      setBusy("");
    }
  }
  async function refresh() {
    const ticket = generation.current;
    const value = await api.state({
      project_id: projectId.current || undefined,
      query,
      category,
    });
    if (ticket === generation.current) {
      setState(value);
      if (!projectId.current && value.project) {
        projectId.current = value.project.id;
      }
    }
  }
  useEffect(() => {
    if (!api) {
      setError(
        "Open this build in the desktop application to connect the Python service.",
      );
      return;
    }
    refresh().catch(report);
    if (!state?.active_job) return;
    const timer = setInterval(() => refresh().catch(report), 400);
    return () => clearInterval(timer);
  }, [query, category, state?.active_job]);
  useEffect(() => {
    if (state && (!project || editorDrafts.ready) && !readySent.current) {
      readySent.current = true;
      api.ready().catch(() => {});
    }
  }, [!!state, editorDrafts.ready]);
  useEffect(() => {
    setReviewOffset(0);
    setReviewQuery("");
    setPendingOnly(false);
    setReviewData(null);
  }, [job?.id]);
  useEffect(() => {
    if (!job?.native || page !== "review") return;
    let current = true;
    api
      .reviewPage({
        job_id: job.id,
        offset: reviewOffset,
        query: reviewQuery,
        pending: pendingOnly,
      })
      .then((value) => {
        if (current) setReviewData(value);
      })
      .catch(report);
    return () => {
      current = false;
    };
  }, [
    job?.id,
    job?.native?.stats.total,
    job?.native?.stats.reviewed,
    page,
    reviewOffset,
    reviewQuery,
    pendingOnly,
  ]);
  useEffect(() => {
    if (!job) return;
    const identity = displayRecords.some((r) => r.id === reviewId)
      ? reviewId
      : displayRecords.find((r) => displayResults[r.id])?.id || "";
    setReviewId(identity);
  }, [job?.id, completed, reviewData]);
  async function switchProject(identity: string) {
    generation.current++;
    projectId.current = identity;
    setSelected([]);
    setPreview(null);
    setExportPath("");
    setRunId("");
    setQuery("");
    setCategory("all");
    const value = await run("Opening project", () =>
      api.state({ project_id: identity }),
    );
    if (value) {
      setState(value);
      setPage("overview");
    }
  }
  async function importProject() {
    const value = await run("Taking a read-only source snapshot", () =>
      api.importProject({ source, original }),
    );
    if (value?.project) {
      generation.current++;
      projectId.current = value.project.id;
      setState(value);
      setSelected([]);
      setRunId("");
      setExportPath("");
      setImporting(false);
      setQuery("");
      setCategory("all");
      setPage("translate");
      setPreview(null);
    }
  }
  function selection() {
    return { project_id: project!.id, record_ids: selected, mode };
  }
  function chooseRecord(record: TextRecord) {
    setReviewId(record.id);
  }
  async function approve() {
    if (!job || !reviewRecord) return;
    const result = await run("Saving review", () =>
      api.review({ job_id: job.id, record_id: reviewRecord.id, text: draft }),
    );
    if (result && project) {
      setEditorDraft(project.id, "review", job.id + ":" + reviewRecord.id);
      await flushEditorDrafts(project.id).catch(report);
    }
    await refresh();
  }
  async function build() {
    if (!job) return;
    const value = await run("Building data test copy", () =>
      api.export(job.id),
    );
    if (value) {
      setExportPath(value.path);
      setNotice(
        `${value.files} data file(s) written to a new isolated folder.`,
      );
      await refresh();
    }
  }
  const title = (eyebrow: string, heading: string, description: string) => (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{heading}</h1>
        <p>{description}</p>
      </div>
    </div>
  );
  const importForm = (
    <div className="import-panel">
      <div className="section-heading">
        <h2>Open a game</h2>
        {project && (
          <button
            className="icon-button"
            aria-label="Close game chooser"
            onClick={() => setImporting(false)}
          >
            <X size={18} />
          </button>
        )}
      </div>
      <p>
        Open an RPG Maker MV/MZ snapshot for isolated translation and review.
        Use Guided workflow, Len’s Method or Manual engines for their game and
        engine tools.
      </p>
      <label className="field-label" htmlFor="source">
        Game folder
      </label>
      <div className="folder-row">
        <input
          id="source"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="Path to an RPG Maker MV/MZ game"
        />
        <button
          onClick={() =>
            run("Choosing game", async () => {
              const chosen = await api.chooseFolder();
              if (chosen) setSource(chosen);
            })
          }
        >
          <FolderOpen size={16} />
          Choose…
        </button>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={original}
          onChange={(e) => setOriginal(e.target.checked)}
        />
        Read the original Git branch
      </label>
      <p className="muted">
        The branch stays untouched. Uncheck to snapshot the current game data.
      </p>
      <button
        className="primary"
        disabled={!source.trim() || !!busy}
        onClick={importProject}
      >
        Open isolated workspace
        <ArrowRight size={16} />
      </button>
    </div>
  );
  function overview() {
    return (
      <>
        {title(
          "PROJECT OVERVIEW",
          project!.name,
          "Your source, context, and translation work in one place.",
        )}
        <div className="next-task">
          <div className="round-icon">
            <Languages size={24} />
          </div>
          <div>
            <h2>
              {job
                ? job.status === "complete"
                  ? "Your sample is ready to review"
                  : "Continue your translation sample"
                : "Start with a small translation sample"}
            </h2>
            <p>
              {job
                ? `${progressLabel(job)} saved · ${reviewed} changes reviewed`
                : "Choose up to 12 text entries and compare the new workflow."}
            </p>
          </div>
          <button
            className="primary"
            onClick={() =>
              setPage(job?.status === "complete" ? "review" : "translate")
            }
          >
            {job?.status === "complete" ? "Review results" : "Select text"}
            <ArrowRight size={16} />
          </button>
        </div>
        <div className="project-facts">
          <div>
            <span>Engine</span>
            <strong>{project!.engine}</strong>
          </div>
          <div>
            <span>Source data</span>
            <strong>
              {project!.files.length} files ·{" "}
              {project!.total_records.toLocaleString()} supported entries
            </strong>
          </div>
          <div>
            <span>Baseline</span>
            <strong>
              {project!.revision === "working files"
                ? "Snapshot of current files"
                : `Original branch · ${project!.revision.slice(0, 10)}`}
            </strong>
          </div>
          <div>
            <span>Game guidance</span>
            <strong>
              {project!.has_guidance
                ? "Saved with this workspace"
                : "Ready to add"}
            </strong>
          </div>
        </div>
        <div className="section-heading spaced">
          <h2>About this workspace</h2>
        </div>
        <p className="muted">
          File translation uses the existing RPG Maker engine for database text,
          dialogue, choices, supported notes, glossary, and wrapping. Guided
          workflow provides advanced phases, WOLF/Ace tools, playtesting and
          public release packaging. Manual engines and Batch history manage
          configured-provider runs and saved batches.
        </p>
      </>
    );
  }
  function translate() {
    return (
      <>
        {title(
          "TRANSLATION WORKSPACE",
          "Translate with context.",
          "Select the text, inspect the run, and follow results without changing screens.",
        )}
        <div className="translation-toolbar">
          <label>
            Run method
            <select
              aria-label="Run method"
              value={mode}
              disabled={!!state?.active_job}
              onChange={(e) => {
                setMode(e.target.value);
                setPreview(null);
              }}
            >
              <option value="offline">Offline workflow test · $0</option>
              <option value="live" disabled={!state?.allow_live}>
                OpenAI Luna · live API
              </option>
            </select>
          </label>
          <div className="method-detail">
            {mode === "offline" ? (
              <>
                <span className="status-pill">No API calls</span>
                <span>Outputs are labeled test text.</span>
              </>
            ) : (
              <>
                <span className="status-pill">gpt-6-luna</span>
                <span>US$5 maximum across test runs.</span>
              </>
            )}
          </div>
        </div>
        <div className="tabs">
          {[
            ["files", "File workflow"],
            ["selection", "Text sample"],
            ["guidance", "Project guidance"],
          ].map(([id, name]) => (
            <button
              key={id}
              aria-pressed={tab === id}
              onClick={() => {
                setTab(id);
                setPreview(null);
              }}
            >
              {name}
            </button>
          ))}
        </div>
        {tab === "files" ? (
          <ProductionPlan
            key={project!.id}
            project={project!}
            mode={mode}
            active={!!state?.active_job}
            report={report}
            onStarted={(started) => {
              setRunId(started.id);
              setExportPath("");
              setJobsOpen(true);
              refresh().catch(report);
            }}
          />
        ) : tab === "guidance" ? (
          <ContextEditor projectId={project!.id} report={report} />
        ) : (
          <>
            <div className="selection-toolbar">
              <label className="search">
                <Search size={16} />
                <input
                  aria-label="Find text or file"
                  placeholder="Find text or a filename"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <select
                aria-label="Text category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="all">All supported text</option>
                <option value="database">Database</option>
                <option value="dialogue">Dialogue & choices</option>
              </select>
              <button
                className="quiet"
                disabled={!selected.length}
                onClick={() => {
                  setSelected([]);
                  setPreview(null);
                }}
              >
                Clear selection
              </button>
            </div>
            <div className="selection-summary">
              <span>{selected.length} of 12 sample entries selected</span>
              <span>
                {project!.matching_records.toLocaleString()} matching · showing
                first {project!.records.length}
              </span>
            </div>
            <div className="text-list">
              {project!.records.map((record) => (
                <label
                  className={`text-row ${selected.includes(record.id) ? "selected" : ""}`}
                  key={record.id}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select ${record.file} ${record.pointer}`}
                    checked={selected.includes(record.id)}
                    disabled={
                      !selected.includes(record.id) && selected.length >= 12
                    }
                    onChange={(e) => {
                      setSelected(
                        e.target.checked
                          ? [...selected, record.id]
                          : selected.filter((id) => id !== record.id),
                      );
                      setPreview(null);
                    }}
                  />
                  <div>
                    <span className="source-text">{record.source}</span>
                    <small>
                      {record.file}
                      <span>·</span>
                      {record.pointer}
                    </small>
                  </div>
                  <span className="category-label">
                    {record.category === "database" ? "Database" : "Dialogue"}
                  </span>
                </label>
              ))}
              {!project!.records.length && (
                <div className="empty-inline">
                  No matching text. Try a different search or category.
                </div>
              )}
            </div>
            <div className="selection-actions">
              <span className="muted">
                The source snapshot stays unchanged.
              </span>
              <button
                className="primary"
                disabled={!selected.length || !!busy || !!state?.active_job}
                onClick={() =>
                  run("Preparing run preview", async () =>
                    setPreview(await api.preview(selection())),
                  )
                }
              >
                Preview run
                <ArrowRight size={16} />
              </button>
            </div>
          </>
        )}
        {preview && (
          <div className="run-preview">
            <div className="section-heading">
              <h2>Review this run</h2>
              <button
                className="icon-button"
                aria-label="Close run preview"
                onClick={() => setPreview(null)}
              >
                <X size={17} />
              </button>
            </div>
            <dl>
              <dt>Scope</dt>
              <dd>
                {preview.entries} entries across {preview.files} files
              </dd>
              <dt>Method</dt>
              <dd>{preview.model}</dd>
              <dt>Budget reservation</dt>
              <dd>{money(preview.maximum_reserved_usd)} maximum reserved</dd>
              <dt>Destination</dt>
              <dd>{preview.destination}</dd>
            </dl>
            <button
              className="primary"
              disabled={!!busy || !!state?.active_job}
              onClick={() =>
                run("Starting sample", async () => {
                  const started = await api.start(selection());
                  setRunId(started.id);
                  setExportPath("");
                  setPreview(null);
                  setJobsOpen(true);
                  await refresh();
                })
              }
            >
              <Play size={15} />
              Start {mode === "offline" ? "offline test" : "Luna sample"}
            </button>
          </div>
        )}
      </>
    );
  }
  function review() {
    return (
      <>
        {title(
          "REVIEW & TEST",
          "Make every line count.",
          "Compare the source, edit the translation, and approve each changed entry.",
        )}
        {!job || !completed ? (
          <div className="empty-inline">
            <ShieldCheck size={28} />
            <h2>
              {job?.native && job.status === "complete"
                ? "No new text changes to review"
                : "No results to review yet"}
            </h2>
            <p>
              {job?.native && job.status === "complete"
                ? "This run reused existing translated text. Its output is available in Release."
                : "Complete a translation run to see its results here."}
            </p>
            <button onClick={() => setPage("translate")}>
              Open translation
            </button>
          </div>
        ) : (
          <>
            {job.native && (
              <div className="selection-toolbar">
                <label className="search">
                  <Search size={16} />
                  <input
                    aria-label="Find review entries"
                    placeholder="Find source, translation, or file"
                    value={reviewQuery}
                    onChange={(e) => {
                      setReviewQuery(e.target.value);
                      setReviewOffset(0);
                    }}
                  />
                </label>
                <label className="check compact">
                  <input
                    type="checkbox"
                    checked={pendingOnly}
                    onChange={(e) => {
                      setPendingOnly(e.target.checked);
                      setReviewOffset(0);
                    }}
                  />
                  Unreviewed only
                </label>
              </div>
            )}
            <div className="review-summary">
              <span>
                {reviewed} of {resultTotal} entries reviewed
              </span>
              <span className="status-pill">
                {job.mode === "offline" ? "Offline test output" : "Luna output"}
              </span>
            </div>
            <div className="review-workspace">
              <div className="review-list">
                {displayRecords
                  .filter((r) => displayResults[r.id])
                  .map((record) => (
                    <button
                      key={record.id}
                      className={reviewId === record.id ? "chosen" : ""}
                      onClick={() => chooseRecord(record)}
                    >
                      <span>
                        {displayResults[record.id].reviewed ? (
                          <Check size={15} />
                        ) : (
                          <span className="pending-dot" />
                        )}
                        {record.source}
                      </span>
                      <small>{record.file}</small>
                    </button>
                  ))}
              </div>
              {reviewRecord && (
                <div className="review-editor">
                  <span className="eyebrow">{reviewRecord.file}</span>
                  <p className="location">{reviewRecord.pointer}</p>
                  <label>
                    Japanese source
                    <div className="source-block" lang="ja">
                      {reviewRecord.source}
                    </div>
                  </label>
                  <label htmlFor="translation-result">
                    English translation
                  </label>
                  <textarea
                    id="translation-result"
                    value={draft}
                    disabled={!!busy || job.status === "running"}
                    onChange={(e) => {
                      setEditorDraft(
                        project!.id,
                        "review",
                        job.id + ":" + reviewRecord.id,
                        e.target.value === displayResults[reviewRecord.id]?.text
                          ? undefined
                          : e.target.value,
                      );
                    }}
                  />
                  <div className="finding-list">
                    {displayResults[reviewRecord.id]?.flags.map((flag) => (
                      <span key={flag}>{flag.replaceAll("-", " ")}</span>
                    ))}
                  </div>
                  <div className="actions">
                    <span className="muted">
                      {editorDrafts.pending
                        ? "Saving recovery draft…"
                        : "Drafts recover after restart. Approve to use this translation."}
                    </span>
                    <button
                      className="primary"
                      disabled={
                        !!busy ||
                        (job.native
                          ? job.status !== "complete"
                          : job.status === "running")
                      }
                      onClick={approve}
                    >
                      Save & approve
                      <Check size={15} />
                    </button>
                  </div>
                </div>
              )}
            </div>
            {job.native && reviewData && (
              <div className="review-pagination">
                <button
                  disabled={reviewOffset === 0}
                  onClick={() =>
                    setReviewOffset(Math.max(0, reviewOffset - 100))
                  }
                >
                  Previous entries
                </button>
                <span>
                  {reviewData.matching ? reviewOffset + 1 : 0}–
                  {Math.min(reviewOffset + 100, reviewData.matching)} of{" "}
                  {reviewData.matching}
                </span>
                <button
                  disabled={reviewOffset + 100 >= reviewData.matching}
                  onClick={() => setReviewOffset(reviewOffset + 100)}
                >
                  Next entries
                </button>
              </div>
            )}
            {!!job.native?.stats.unresolved && (
              <p className="banner error">
                {job.native.stats.unresolved} source mappings require manual
                inspection before export.
              </p>
            )}
            <p className="footnote">
              Mechanical checks support review. In-game playtesting has not been
              performed.
            </p>
          </>
        )}
      </>
    );
  }
  function release() {
    return (
      <>
        {title(
          "DATA TEST COPY",
          "Inspect the result in isolation.",
          "Write reviewed data to a fresh folder before testing it in a disposable game copy.",
        )}
        <div className="release-checks">
          <div>
            <span>Translation run</span>
            <strong>
              {job?.status === "complete"
                ? `${progressLabel(job)} saved`
                : "Complete a run first"}
            </strong>
          </div>
          <div>
            <span>Review</span>
            <strong>
              {job
                ? `${reviewed} of ${resultTotal} changes approved`
                : "No results yet"}
            </strong>
          </div>
          <div>
            <span>Build scope</span>
            <strong>Selected JSON data files</strong>
          </div>
          <div>
            <span>Source protection</span>
            <strong>Original game and snapshot stay unchanged</strong>
          </div>
        </div>
        <p className="muted">
          This creates a data overlay for testing, not a complete playable game
          or a public release. Offline test output keeps its visible marker.
        </p>
        <div className="actions">
          {job?.native && (
            <button
              className="primary"
              disabled={
                !!busy ||
                job.status !== "complete" ||
                reviewed !== resultTotal ||
                !!job.native.stats.unresolved ||
                hasUnsavedReview
              }
              onClick={() =>
                run(
                  "Applying reviewed files to the isolated workspace",
                  async () => {
                    const updated = await api.applyReviewed(job.id);
                    setState(updated);
                    setNotice(
                      "Reviewed files are now the source for subsequent runs in this workspace.",
                    );
                  },
                )
              }
            >
              Use reviewed files in project
              <Check size={16} />
            </button>
          )}
          <button
            disabled={
              !!busy ||
              job?.status !== "complete" ||
              reviewed !== resultTotal ||
              !!job?.native?.stats.unresolved ||
              hasUnsavedReview
            }
            className="primary"
            onClick={build}
          >
            <Package size={16} />
            Build data test copy
          </button>
          {exportPath && (
            <button
              onClick={() =>
                run("Opening test copy", () => api.openExport(exportPath))
              }
            >
              <FolderOpen size={16} />
              Open output folder
            </button>
          )}
        </div>
        {!!job?.applied_to_workspace && (
          <p className="footnote">
            Applied to working revision {job.applied_to_workspace}. The original
            source remains separate.
          </p>
        )}
        {hasUnsavedReview && (
          <p className="banner error">
            Save the pending review edits before exporting or applying these
            files.
          </p>
        )}
        {exportPath && <div className="output-path">{exportPath}</div>}
      </>
    );
  }
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">D</span>Dazed<span>TL</span>
          <em>PREVIEW</em>
        </div>
        {isProjectPage ? (
          <div className="project-switch">
            <label className="sr-only" htmlFor="projects">
              Active project
            </label>
            <select
              id="projects"
              value={project?.id || ""}
              onChange={(e) => switchProject(e.target.value)}
            >
              {!project && <option value="">No project open</option>}
              {state?.projects.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button className="quiet" onClick={() => setImporting(true)}>
              <FolderOpen size={16} />
              Open game
            </button>
          </div>
        ) : (
          <span className="project-switch">{pageLabel}</span>
        )}
        <span className="top-status">
          <span
            className={`connection-dot ${serviceStopped ? "disconnected" : ""}`}
          />
          {serviceStopped
            ? "Python service stopped"
            : state
              ? "Python service connected"
              : "Connecting…"}
        </span>
      </header>
      <div className="app-body">
        <aside className="sidebar">
          <span className="nav-caption">WORKSPACE</span>
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={page === id ? "active" : ""}
              aria-current={page === id ? "page" : undefined}
              onClick={() => setPage(id)}
            >
              <Icon size={18} />
              {label}
              {id === "review" && completed > reviewed && (
                <span className="nav-count">{completed - reviewed}</span>
              )}
            </button>
          ))}
          <div className="sidebar-bottom">
            <button
              className={page === "updates" ? "active" : ""}
              onClick={() => setPage("updates")}
            >
              <Package size={18} />
              Updates & rollback
            </button>
            <button
              className={page === "settings" ? "active" : ""}
              onClick={() => setPage("settings")}
            >
              <Settings2 size={18} />
              Settings
            </button>
            <div className="budget-mini">
              <span>API test budget</span>
              <strong>
                {money(state?.budget.reserved_usd || 0)}{" "}
                <small>/ $5 reserved</small>
              </strong>
              <div className="budget-track">
                <span
                  style={{
                    width: `${(state?.budget.reserved_usd || 0) * 20}%`,
                  }}
                />
              </div>
            </div>
          </div>
        </aside>
        <main className="workspace" ref={mainPane}>
          {(error || editorDrafts.error || serviceStopped) && (
            <div className="banner error" role="alert">
              <span>{error || editorDrafts.error || serviceStopped}</span>
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="banner success" role="status">
              <Check size={16} />
              {notice}
            </div>
          )}
          {busy && (
            <div className="busy-indicator" role="status">
              <span />
              {busy}…
            </div>
          )}
          {(versionVisited || page === "version") && (
            <div hidden={page !== "version"}>
              <Suspense
                fallback={<p className="muted">Opening Git version updates…</p>}
              >
                <VersionWorkspace
                  visible={page === "version"}
                  requested={versionSource}
                />
              </Suspense>
            </div>
          )}
          {(batchesVisited || page === "batches") && (
            <div hidden={page !== "batches"}>
              <Suspense fallback={<p>Opening batch history…</p>}>
                <BatchWorkspace
                  visible={page === "batches"}
                  onNavigate={setPage}
                />
              </Suspense>
            </div>
          )}
          {(evaluationVisited || page === "evaluation") && (
            <div hidden={page !== "evaluation"}>
              <Suspense fallback={<p>Opening evaluation…</p>}>
                <EvaluationWorkspace visible={page === "evaluation"} />
              </Suspense>
            </div>
          )}
          {(lenVisited || page === "len") && (
            <div hidden={page !== "len"}>
              <Suspense
                fallback={<p className="muted">Opening Len’s Method…</p>}
              >
                <LenWorkspace
                  visible={page === "len"}
                  onNavigate={(next, source) => {
                    if (source) setVersionSource({ source, key: Date.now() });
                    setPage(next);
                  }}
                />
              </Suspense>
            </div>
          )}
          {(instructionsVisited || page === "instructions") && (
            <div hidden={page !== "instructions"}>
              <Suspense fallback={<p>Opening shared instructions…</p>}>
                <InstructionWorkspace />
              </Suspense>
            </div>
          )}
          {(guideVisited || page === "guide") && (
            <div hidden={page !== "guide"}>
              <Suspense fallback={<p>Opening the guide…</p>}>
                <GuideWorkspace onNavigate={setPage} />
              </Suspense>
            </div>
          )}
          {page === "updates" && (
            <Suspense fallback={<p>Opening application updates…</p>}>
              <UpdateWorkspace />
            </Suspense>
          )}
          {(settingsVisited || page === "settings") && (
            <div hidden={page !== "settings"}>
              <Suspense fallback={<p className="muted">Opening settings…</p>}>
                <SettingsWorkspace
                  report={report}
                  onApplied={(value) => {
                    api.setScale(Number(value.values.font_scale)).catch(report);
                    refresh().catch(report);
                  }}
                />
              </Suspense>
            </div>
          )}
          {(imagesVisited || page === "images") && (
            <div hidden={page !== "images"}>
              <Suspense
                fallback={<p className="muted">Opening image workspace…</p>}
              >
                <AssetWorkspace
                  visible={page === "images"}
                  requested={assetRequested}
                  sampleProjectId={project?.id}
                  sampleJob={state?.jobs.find((item) => !!item.image)}
                  active={!!state?.active_job}
                  focusImage={imageFocus}
                  onChange={() => {
                    setJobsOpen(false);
                    refresh().catch(report);
                  }}
                  report={report}
                  onTranslate={(source, context) => {
                    setManualRequested({
                      source,
                      context,
                      engine: "Image Text",
                      key: Date.now(),
                    });
                    setPage("manual");
                  }}
                />
              </Suspense>
            </div>
          )}
          {(manualVisited || page === "manual") && (
            <div hidden={page !== "manual"}>
              <Suspense
                fallback={<p className="muted">Opening manual engines…</p>}
              >
                <ManualWorkspace
                  requested={manualRequested}
                  visible={page === "manual"}
                  active={!!state?.active_job}
                  onChange={() => refresh().catch(report)}
                  report={report}
                />
              </Suspense>
            </div>
          )}
          {(workflowVisited || page === "workflow") && (
            <div hidden={page !== "workflow"}>
              <Suspense
                fallback={<p className="muted">Opening guided workflow…</p>}
              >
                <GuidedWorkspace
                  visible={page === "workflow"}
                  active={!!state?.active_job}
                  report={report}
                  onChange={() => refresh().catch(report)}
                  openSettings={() => setPage("settings")}
                  openImages={(source) => {
                    setAssetRequested({ source, key: Date.now() });
                    setPage("images");
                  }}
                />
              </Suspense>
            </div>
          )}
          {page === "settings" ||
          page === "updates" ||
          page === "evaluation" ||
          page === "instructions" ||
          page === "guide" ||
          page === "batches" ||
          page === "manual" ||
          page === "len" ||
          page === "version" ||
          page === "images" ||
          page === "workflow" ? null : importing || !project ? (
            <>
              {title(
                "WELCOME TO YOUR WORKSPACE",
                "One game. One place to work.",
                "A new desktop flow for translation, review, and testing.",
              )}
              {importForm}
            </>
          ) : !editorDrafts.ready ? (
            <p className="muted">Recovering editor drafts…</p>
          ) : page === "overview" ? (
            overview()
          ) : page === "translate" ? (
            translate()
          ) : page === "review" ? (
            review()
          ) : page === "release" ? (
            release()
          ) : null}
        </main>
      </div>
      <footer className="jobbar">
        <button onClick={() => setJobsOpen(!jobsOpen)} aria-expanded={jobsOpen}>
          <Terminal size={16} />
          <strong>
            {state?.active_job
              ? state.active_job_kind === "image"
                ? "Rendering image preview"
                : state.active_job_kind === "workflow"
                  ? "Tool action running"
                  : "Translation running"
              : statusJob && isProjectPage
                ? `${statusJob.status.charAt(0).toUpperCase() + statusJob.status.slice(1)} · ${progressLabel(statusJob)}`
                : "Ready when you are"}
          </strong>
          <span>
            {state?.active_job_project ||
              (isProjectPage
                ? project?.name || "Open a game to begin"
                : pageLabel)}
          </span>
          <ChevronDown size={15} className={jobsOpen ? "flipped" : ""} />
        </button>
        {state?.active_job && (
          <button
            className="quiet"
            onClick={() =>
              run("Stopping after current request", () =>
                api.stop(state.active_job!),
              )
            }
          >
            <Square size={12} />
            Stop
          </button>
        )}
      </footer>
      {jobsOpen && (
        <section className="activity">
          <div className="section-heading">
            <h2>Activity & runs</h2>
            <button
              className="icon-button"
              aria-label="Close activity"
              onClick={() => setJobsOpen(false)}
            >
              <X size={17} />
            </button>
          </div>
          {!state?.jobs.length ? (
            <p className="muted">Runs for the active project appear here.</p>
          ) : (
            state.jobs.map((item) => (
              <div className="job-row" key={item.id}>
                <div>
                  <strong>
                    {jobLabel(item)}
                    <span className={`job-status ${item.status}`}>
                      {item.status}
                    </span>
                  </strong>
                  <p>{item.message}</p>
                  <small>
                    {new Date(item.created).toLocaleString()} ·{" "}
                    {progressLabel(item)} saved
                  </small>
                </div>
                {(item.native
                  ? item.native.stats.total > 0
                  : Object.keys(item.results).length > 0) && (
                  <button
                    onClick={() => {
                      setRunId(item.id);
                      setExportPath("");
                      setPage("review");
                      setJobsOpen(false);
                    }}
                  >
                    Review this run
                  </button>
                )}
                {!item.image &&
                  ["stopped", "failed", "interrupted"].includes(
                    item.status,
                  ) && (
                    <button
                      disabled={!!busy || !!state.active_job}
                      onClick={() =>
                        run("Resuming unfinished entries", async () => {
                          await api.resume(item.id);
                          setRunId(item.id);
                          await refresh();
                        })
                      }
                    >
                      Resume
                    </button>
                  )}
                {item.native && (
                  <button
                    className="quiet"
                    onClick={() =>
                      run("Reading engine activity", async () =>
                        setEngineLog(await api.engineLog(item.id)),
                      )
                    }
                  >
                    Engine log
                  </button>
                )}
                {item.image && (
                  <button
                    onClick={() => {
                      setImageFocus((previous) => ({
                        id: item.image!.id,
                        key: (previous?.key || 0) + 1,
                      }));
                      setPage("images");
                      setJobsOpen(false);
                    }}
                  >
                    Open image
                  </button>
                )}
              </div>
            ))
          )}
        </section>
      )}
      {engineLog && (
        <div className="log-overlay" role="dialog" aria-label="Engine log">
          <div className="section-heading">
            <h2>Engine log · recent activity</h2>
            <button
              className="icon-button"
              aria-label="Close engine log"
              onClick={() => setEngineLog("")}
            >
              <X size={18} />
            </button>
          </div>
          <pre>{engineLog}</pre>
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
