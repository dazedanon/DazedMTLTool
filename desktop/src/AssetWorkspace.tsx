import { useEffect, useRef, useState } from "react";
import { api } from "./bridge";
import ImageWorkspace, { flushImageProject } from "./ImageWorkspace";
import type { AssetState, Job } from "./types";

type Resource = {
  key: string;
  label: string;
  detail: string;
  size: string;
  installed: boolean;
  default: boolean;
};
export default function AssetWorkspace({
  visible,
  requested,
  sampleProjectId,
  sampleJob,
  active,
  focusImage,
  onChange,
  onTranslate,
  report,
}: {
  visible: boolean;
  requested?: { source: string; key: number };
  sampleProjectId?: string;
  sampleJob?: Job;
  active: boolean;
  focusImage?: { id: string; key: number };
  onChange: () => void;
  onTranslate: (source: string, context: string) => void;
  report: (e: unknown) => void;
}) {
  const [state, setState] = useState<AssetState | null>(null);
  const [galleryVisible, setGalleryVisible] = useState(!sampleProjectId);
  const [editorVisible, setEditorVisible] = useState(false);
  const [source, setSource] = useState("");
  const [engine, setEngine] = useState("auto");
  const [imageRoot, setImageRoot] = useState("");
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("all");
  const [folder, setFolder] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [thumbs, setThumbs] = useState<
    Record<string, { url?: string; error?: string }>
  >({});
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [ocrEngine, setOcrEngine] = useState("rapidocr");
  const [translatedPath, setTranslatedPath] = useState("");
  const [editor, setEditor] = useState<{ id: string; key: number } | null>(
    null,
  );
  const [resources, setResources] = useState<Resource[]>([]);
  const [resourceKeys, setResourceKeys] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);
  const seenJob = useRef("");
  const opening = useRef(0);
  const lastThumbnails = useRef("");
  const confirmPanel = useRef<HTMLDivElement>(null);
  const currentId = useRef("");
  const filters = useRef({ query, stage, folder, page });
  filters.current = { query, stage, folder, page };
  const disabled = busy || active || !!state?.running;
  const project = state?.project;
  const job = state?.jobs[0];
  async function refresh() {
    const next = await api.assetState({
      project_id: currentId.current,
      ...filters.current,
    });
    setState(next);
    currentId.current = next.project?.id || "";
    if (!source && next.project) setSource(next.project.source);
    const latest = next.jobs[0];
    if (
      latest &&
      latest.status !== "running" &&
      latest.id !== seenJob.current
    ) {
      seenJob.current = latest.id;
      onChange();
      if (latest.status === "complete") {
        const ids = latest.result?.images as string[] | undefined;
        if (ids?.length) {
          setEditor({ id: ids[0], key: Date.now() });
          setEditorVisible(true);
        }
        if (latest.result?.resources) {
          const values = latest.result.resources as Resource[];
          setResources(values);
          setResourceKeys(
            values.filter((r) => r.default && !r.installed).map((r) => r.key),
          );
        }
      }
    }
    const key = JSON.stringify([
      next.project?.id,
      next.assets.map((a) => a.id),
      latest?.id,
      latest?.status,
    ]);
    if (next.project && !next.running && key !== lastThumbnails.current) {
      lastThumbnails.current = key;
      const values = await api.assetThumbnails({
        project_id: next.project.id,
        ids: next.assets.map((a) => a.id),
      });
      if (lastThumbnails.current === key) setThumbs(values);
    }
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function open(path = source) {
    setGalleryVisible(true);
    setEditorVisible(false);
    const next = await api.assetOpen({
      source: path,
      engine,
      image_root: imageRoot,
    });
    currentId.current = next.project!.id;
    setState(next);
    setSource(path);
    setSelected([]);
    setEditor(null);
    setPage(0);
    await start("scan", []);
  }
  async function start(action: string, ids = selected) {
    if (!currentId.current) return;
    await flushImageProject(currentId.current);
    seenJob.current = "";
    await api.assetAction({
      project_id: currentId.current,
      action,
      ids,
      options: { engine: ocrEngine, path: translatedPath, keys: resourceKeys },
    });
    setConfirmation("");
    onChange();
    await refresh();
  }
  useEffect(() => {
    if (visible) refresh().catch(report);
  }, [visible, query, stage, folder, page]);
  useEffect(() => {
    if (!visible || !state?.running) return;
    const timer = setInterval(() => refresh().catch(report), 400);
    return () => clearInterval(timer);
  }, [visible, state?.running]);
  useEffect(() => {
    if (requested && requested.key !== opening.current) {
      opening.current = requested.key;
      run(() => open(requested.source));
    }
  }, [requested?.key]);
  useEffect(() => {
    if (confirmation)
      confirmPanel.current?.scrollIntoView({
        block: "center",
        behavior: "smooth",
      });
  }, [confirmation]);
  const notices: Record<string, string> = {
    patch: `Write the selected editable PNGs into ${project?.source}. Existing runtime images are backed up once; changed source files stop the batch. With nothing selected, all editable images are included.`,
    delete:
      "Delete the selected editable copies. Runtime game images remain available; saved text jobs are retained until the editor is synchronized.",
    migrate:
      "Move DazedTL_Images into .dazedtl/images. Conflicting files are kept in .dazedtl/legacy_image_conflicts.",
    ocr: `${ocrEngine === "lens" ? "Upload the selected original image pixels to Google Lens for OCR." : "Run local RapidOCR; its models must be installed."} This replaces the selected images’ existing text regions and translations. With nothing selected, all editable images are included.`,
    restore:
      "Restore the selected editable images from their stored untranslated originals. With nothing selected, all editable images are included.",
    install: `Download and install ${resourceKeys.length} selected image tool(s). Downloads may be large; installed tools are shared by image projects.`,
  };
  const translation = state?.jobs.find(
    (j) => j.status === "complete" && j.result?.translation_source,
  )?.result?.translation_source as string | undefined;
  const prompt = state?.jobs.find(
    (j) => j.status === "complete" && j.result?.prompt,
  )?.result?.prompt as string | undefined;
  return (
    <div
      className={`asset-shell ${editorVisible && editor ? "editor-open" : !galleryVisible && sampleProjectId && !project ? "individual-open" : ""}`}
    >
      <div className="actions asset-view-tabs">
        <button
          onClick={() => {
            setGalleryVisible(true);
            setEditorVisible(false);
          }}
        >
          Game image gallery
        </button>
        {editor && (
          <button onClick={() => setEditorVisible(true)}>Text editor</button>
        )}
        {!project && sampleProjectId && (
          <button onClick={() => setGalleryVisible(false)}>
            Individual images
          </button>
        )}
        {editorVisible && editor && (
          <>
            <button
              disabled={disabled}
              onClick={() => run(() => start("exchange"))}
            >
              Prepare translation
            </button>
            {translation && (
              <button onClick={() => onTranslate(translation, project!.source)}>
                Open Image Text translation
              </button>
            )}
          </>
        )}
      </div>
      <div className="page-heading">
        <div>
          <span className="eyebrow">IMAGES</span>
          <h1>Localize game images.</h1>
          <p>
            Prepare editable copies, review text, and publish approved artwork
            back to the game.
          </p>
        </div>
      </div>
      <section className="panel asset-project-picker">
        <div className="form-grid">
          <label>
            Game folder
            <div className="path-input">
              <input
                aria-label="Image game folder"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              />
              <button
                disabled={disabled}
                aria-label="Choose image game folder"
                onClick={() =>
                  run(async () => {
                    const p = await api.chooseFolder();
                    if (p) setSource(p);
                  })
                }
              >
                Browse…
              </button>
            </div>
          </label>
          <label>
            Image profile
            <select
              aria-label="Image engine profile"
              value={engine}
              onChange={(e) => setEngine(e.target.value)}
            >
              <option value="auto">Detect automatically</option>
              <option value="rpgmaker_mvmz">RPG Maker MV/MZ</option>
              <option value="generic">Generic / loose PNGs</option>
            </select>
          </label>
          {engine === "generic" && (
            <label>
              Image folder inside the game
              <input
                aria-label="Loose image folder"
                value={imageRoot}
                onChange={(e) => setImageRoot(e.target.value)}
                placeholder="Defaults to the whole game"
              />
            </label>
          )}
        </div>
        <div className="actions">
          <button
            disabled={disabled || !source.trim()}
            onClick={() => run(() => open())}
          >
            Open game images
          </button>
          {!!state?.projects.length && (
            <select
              aria-label="Recent image projects"
              value={project?.id || ""}
              disabled={disabled}
              onChange={(e) =>
                run(async () => {
                  const p = state.projects.find(
                    (p) => p.id === e.target.value,
                  )!;
                  setEngine(p.engine);
                  setImageRoot(p.image_root);
                  const next = await api.assetOpen({
                    source: p.source,
                    engine: p.engine,
                    image_root: p.image_root,
                  });
                  currentId.current = p.id;
                  setState(next);
                  setSource(p.source);
                  setEditor(null);
                  setSelected([]);
                  await refresh();
                })
              }
            >
              {state.projects.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.source}
                </option>
              ))}
            </select>
          )}
        </div>
        {project && (
          <p className="muted">
            {project.detection} · Editable workspace: {state?.paths.editable}
          </p>
        )}
      </section>
      {project && (
        <>
          <section className="panel">
            <div className="actions">
              <button
                disabled={disabled}
                onClick={() => run(() => start("scan", []))}
              >
                Rescan images
              </button>
              <button
                disabled={disabled}
                onClick={() => run(() => start("editable"))}
              >
                Make {selected.length ? "selected" : "all"} editable
              </button>
              <button
                disabled={disabled}
                onClick={() => run(() => start("edit"))}
              >
                Edit image text
              </button>
              <button
                disabled={disabled}
                onClick={() => setConfirmation("patch")}
              >
                Prepare for game
              </button>
              <button
                disabled={disabled || !selected.length}
                onClick={() => setConfirmation("delete")}
              >
                Delete editable copies
              </button>
              {state?.legacy && (
                <button
                  disabled={disabled}
                  onClick={() => setConfirmation("migrate")}
                >
                  Migrate old workspace
                </button>
              )}
              <button
                onClick={() =>
                  api.openExport(state!.paths.editable).catch(report)
                }
              >
                Open editable folder
              </button>
            </div>
            <div className="form-grid asset-filters">
              <label>
                Filter images
                <input
                  aria-label="Filter game images"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(0);
                  }}
                />
              </label>
              <label>
                Folder
                <select
                  value={folder}
                  onChange={(e) => {
                    setFolder(e.target.value);
                    setPage(0);
                  }}
                >
                  <option value="">All folders</option>
                  {state?.folders.map((f) => (
                    <option key={f}>{f}</option>
                  ))}
                </select>
              </label>
              <label>
                Stage
                <select
                  value={stage}
                  onChange={(e) => {
                    setStage(e.target.value);
                    setPage(0);
                  }}
                >
                  <option value="all">All images</option>
                  <option value="editable">Editable copies</option>
                  <option value="runtime">Runtime only</option>
                </select>
              </label>
            </div>
            <div className="actions">
              <button
                onClick={() =>
                  setSelected(
                    Array.from(
                      new Set([...selected, ...state!.assets.map((a) => a.id)]),
                    ),
                  )
                }
              >
                Select this page
              </button>
              <button onClick={() => setSelected([])}>Clear selection</button>
              <span>
                {selected.length} selected · {state?.count} matching /{" "}
                {state?.total} total
              </span>
            </div>
            <div className="asset-gallery">
              {state?.assets.map((a) => (
                <label
                  className={`asset-tile ${selected.includes(a.id) ? "selected" : ""}`}
                  key={a.id}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select image ${a.relative}`}
                    checked={selected.includes(a.id)}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [...selected, a.id]
                          : selected.filter((id) => id !== a.id),
                      )
                    }
                  />
                  {thumbs[a.id]?.url ? (
                    <img alt="" src={thumbs[a.id].url} />
                  ) : (
                    <span className="muted">
                      {thumbs[a.id]?.error || "Loading preview…"}
                    </span>
                  )}
                  <strong>{a.relative}</strong>
                  <span>
                    {a.editable ? "Editable" : "Runtime"}
                    {a.encrypted ? " · Encrypted" : ""}
                  </span>
                </label>
              ))}
            </div>
            <div className="actions">
              <button
                disabled={!state?.page}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous page
              </button>
              <span>
                Page {(state?.page || 0) + 1} / {state?.pages}
              </span>
              <button
                disabled={!state || state.page + 1 >= state.pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next page
              </button>
            </div>
          </section>
          <section className="panel">
            <h2>Read, review, translate</h2>
            <p>
              Actions use the selected images, or all editable images when the
              selection is empty. Review OCR text and boxes before confirming
              them.
            </p>
            <div className="actions">
              <select
                aria-label="Image OCR engine"
                value={ocrEngine}
                onChange={(e) => setOcrEngine(e.target.value)}
              >
                <option value="rapidocr">RapidOCR — local</option>
                <option value="lens">Google Lens — uploads images</option>
              </select>
              <button
                disabled={disabled}
                onClick={() => setConfirmation("ocr")}
              >
                Read text with OCR
              </button>
              <button
                disabled={disabled}
                onClick={() => run(() => start("confirm"))}
              >
                Confirm reviewed text
              </button>
              <button
                disabled={disabled}
                onClick={() => run(() => start("unconfirm"))}
              >
                Mark for review
              </button>
              <button
                disabled={disabled}
                onClick={() => run(() => start("exchange"))}
              >
                Prepare translation
              </button>
              {translation && (
                <button
                  onClick={() => onTranslate(translation, project.source)}
                >
                  Open Image Text translation
                </button>
              )}
              <button
                disabled={disabled}
                onClick={() => setConfirmation("restore")}
              >
                Restore original editable images
              </button>
            </div>
            {!!state?.translations.length && (
              <label>
                Completed image translations
                <select
                  aria-label="Completed image translations"
                  value={translatedPath}
                  onChange={(e) => setTranslatedPath(e.target.value)}
                >
                  <option value="">Choose a completed run</option>
                  {state.translations.map((j) => (
                    <option key={j.id} value={j.path}>
                      {j.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Translated image_text.json
              <input
                aria-label="Translated image exchange"
                value={translatedPath}
                onChange={(e) => setTranslatedPath(e.target.value)}
                placeholder="Path from the completed translation output"
              />
            </label>
            <div className="actions">
              <button
                disabled={disabled || !translatedPath}
                onClick={() => run(() => start("collect"))}
              >
                Collect translations
              </button>
              <button
                disabled={disabled}
                onClick={() => run(() => start("skill"))}
              >
                Prepare image translation handoff
              </button>
              {prompt && (
                <button
                  onClick={() =>
                    run(async () => {
                      await api.copyText(prompt);
                      setCopied(true);
                    })
                  }
                >
                  {copied ? "Handoff copied" : "Copy image handoff"}
                </button>
              )}
            </div>
          </section>
          <details className="panel">
            <summary>OCR, reconstruction tools, and fonts</summary>
            <button
              disabled={disabled}
              onClick={() => run(() => start("resources", []))}
            >
              Inspect installed image tools
            </button>
            {resources.map((r) => (
              <label className="check" key={r.key}>
                <input
                  type="checkbox"
                  checked={resourceKeys.includes(r.key)}
                  onChange={(e) =>
                    setResourceKeys(
                      e.target.checked
                        ? [...resourceKeys, r.key]
                        : resourceKeys.filter((k) => k !== r.key),
                    )
                  }
                />
                <span>
                  <strong>{r.label}</strong> ·{" "}
                  {r.installed ? "Installed" : r.size}
                  <small>{r.detail}</small>
                </span>
              </label>
            ))}
            {!!resources.length && (
              <button
                disabled={disabled || !resourceKeys.length}
                onClick={() => setConfirmation("install")}
              >
                Install selected tools
              </button>
            )}
          </details>
          {confirmation && (
            <section
              ref={confirmPanel}
              className="confirmation panel"
              role="alert"
            >
              <h2>Review image action</h2>
              <p>{notices[confirmation]}</p>
              <p>
                {selected.length
                  ? `${selected.length} selected image(s)`
                  : "All applicable images"}{" "}
                · {project.source}
              </p>
              <div className="actions">
                <button
                  disabled={disabled}
                  onClick={() => run(() => start(confirmation))}
                >
                  Confirm image action
                </button>
                <button onClick={() => setConfirmation("")}>Cancel</button>
              </div>
            </section>
          )}
          {job && (
            <section className="panel">
              <div className="section-heading">
                <h2>{job.label}</h2>
                <span className="asset-job-status">{job.status}</span>
              </div>
              <p role="status">{job.message}</p>
              {state?.active && (
                <button
                  onClick={() =>
                    api.workflowStop(state.active).then(refresh).catch(report)
                  }
                >
                  Stop image action
                </button>
              )}
              <details>
                <summary>Activity log</summary>
                <pre className="activity-log">{job.log.join("\n")}</pre>
              </details>
            </section>
          )}
          {editor && (
            <div hidden={!editorVisible}>
              <ImageWorkspace
                key={project.id}
                projectId={project.id}
                active={disabled}
                imageJob={state?.image_job}
                onStarted={() => {
                  onChange();
                  refresh().catch(report);
                }}
                report={report}
                focusImage={editor}
                fonts={
                  (state?.jobs.find((j) => j.result?.fonts)?.result?.fonts ||
                    []) as { path: string; name: string }[]
                }
              />
            </div>
          )}
        </>
      )}
      {!project && sampleProjectId && (
        <div hidden={galleryVisible}>
          <ImageWorkspace
            key={sampleProjectId}
            projectId={sampleProjectId}
            active={active}
            imageJob={sampleJob}
            onStarted={onChange}
            report={report}
            focusImage={focusImage}
          />
        </div>
      )}
    </div>
  );
}
