import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FolderOpen,
  Play,
  Square,
} from "lucide-react";
import { api } from "./bridge";
import { saveBeforeClose } from "./lifecycle";
import { InputField } from "./SettingsWorkspace";
import { WolfStages, wolfStages, wolfHelp } from "./WolfStages";
import { FileScope } from "./FileScope";
import type {
  GuidanceDocuments,
  GuidedProject,
  SettingValue,
  WorkflowDraft,
  WorkflowPreview,
  WorkflowState,
} from "./types";

const rpgStages = [
  "Project",
  "Prepare",
  "Setup",
  "Translation phase 1",
  "Translation phase 2",
  "Export",
  "Rewrap",
  "Translation QA",
  "Images",
  "Playtest",
];
const rpgHelp = [
  "Select the actual game root, then choose the JSON files to import. Ace archives require explicit decryption and conversion. Changing the selection replaces only this guided project's imported files.",
  "Format game data, format plugins.js, install GameUpdate, then set up Git version tracking. Git needs a matching original baseline and the current release label.",
  "Collect speaker names, inspect the game using the setup skill, and save its glossary, quirks and game instructions before translation.",
  "Translate the database first, then dialogue and choices. Build the variable cache before Phase 2. Sync completed translations into the next phase when continuing the same game.",
  "Use the advanced-text audit to identify visible variable, script and plugin text. Enable the relevant codes and handlers; save inclusive variable IDs and ranges.",
  "Audit plugin or Ruby text, then export the selected or all translated files into the detected game data folder. Ace also requires packing its JSON back into native data.",
  "Load or measure the game's four line widths. Preview deterministic rewrap on the selected game-data files, then apply the same settings. Original source fields remain protected.",
  "Review localization guidance, choose the full-game release gate or a targeted focus, and prepare the existing receipt-based QA task. A completed pass can rebuild its final report without repeating review.",
  "Open the image workspace for the selected game. Engine extraction and patching are tracked separately from manual image editing.",
  "Configure playtest hotkeys and editor in Settings, install or update the shared plugins, copy the walkthrough skill, then build a sanitized public-release ZIP.",
];
const speakerKeys = new Set([
  "NAMES",
  "FIRSTLINESPEAKERS",
  "INLINE401SPEAKERS",
  "FACENAME101",
  "AUTONAMEPOPUP101",
  "SPEAKERS408",
]);
const widthLabels: Record<string, string> = {
  width: "Dialogue width",
  faceWidth: "Face dialogue width",
  listWidth: "List / help width",
  noteWidth: "Note width",
};
const databaseNames = new Set([
  "Actors.json",
  "Armors.json",
  "Classes.json",
  "Enemies.json",
  "Items.json",
  "MapInfos.json",
  "Skills.json",
  "States.json",
  "System.json",
  "Weapons.json",
]);

export function GuidedWorkspace({
  visible,
  active,
  report,
  onChange,
  openSettings,
  openImages,
}: {
  visible: boolean;
  active: boolean;
  report: (value: unknown) => void;
  onChange: () => void;
  openSettings: () => void;
  openImages: (source: string) => void;
}) {
  const [state, setState] = useState<WorkflowState | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState<WorkflowPreview | null>(null);
  const [nextStage, setNextStage] = useState<number | null>(null);
  const [documents, setDocuments] = useState<GuidanceDocuments>({});
  const [draft, setDraft] = useState<WorkflowDraft>({});
  const draftRef = useRef({ id: "", value: {} as WorkflowDraft, dirty: false });
  const draftTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const saving = useRef(Promise.resolve());
  const loadedId = useRef("");
  const [sync, setSync] = useState(true);
  const [version, setVersion] = useState("");
  const [original, setOriginal] = useState("");
  const [untranslated, setUntranslated] = useState(false);
  const [rewrapFiles, setRewrapFiles] = useState<string[]>([]);
  const [rewrapCategories, setRewrapCategories] = useState([
    "dialogue",
    "face_dialogue",
    "list",
    "notes",
  ]);
  const [codes, setCodes] = useState("401,405");
  const [maxRows, setMaxRows] = useState(4);
  const [protectRows, setProtectRows] = useState(true);
  const [overLimit, setOverLimit] = useState(false);
  const [focus, setFocus] = useState("release");
  const [output, setOutput] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);
  const [referenceTitle, setReferenceTitle] = useState("");
  const [referenceOriginal, setReferenceOriginal] = useState("");
  const [referenceTranslated, setReferenceTranslated] = useState("");
  const [customSkill, setCustomSkill] = useState("");
  const [clearedAt, setClearedAt] = useState("");
  const project = state?.project;
  const isWolf = project?.engine === "WOLF";
  const stages = isWolf ? wolfStages : rpgStages;
  const help = isWolf ? wolfHelp : rpgHelp;
  const step = project?.step || 0;
  useEffect(() => {
    if (visible) document.querySelector("main.workspace")?.scrollTo(0, 0);
  }, [project?.id, step]);
  const disabled = !!busy || !!state?.active || active;
  const widths = draft.widths || project?.widths || {};
  const options = draft.engine_options || project?.engine_options || {};
  const latest = state?.jobs[0];
  const manual = state?.manual_job;

  async function flushDraft() {
    clearTimeout(draftTimer.current);
    const current = draftRef.current;
    if (!current.id || !current.dirty) return saving.current;
    const value = structuredClone(current.value),
      id = current.id;
    const task = saving.current
      .catch(() => {})
      .then(async () => {
        await api.workflowDraft(id, value);
        if (
          draftRef.current.id === id &&
          JSON.stringify(draftRef.current.value) === JSON.stringify(value)
        )
          draftRef.current.dirty = false;
      });
    saving.current = task;
    return task;
  }
  function editDraft(value: WorkflowDraft) {
    setDraft(value);
    draftRef.current = { id: project!.id, value, dirty: true };
    clearTimeout(draftTimer.current);
    draftTimer.current = setTimeout(() => flushDraft().catch(report), 400);
  }
  useEffect(() => saveBeforeClose(flushDraft), []);
  async function accept(value: WorkflowState) {
    stateRef.current = value;
    setState(value);
    if (value.project && loadedId.current !== value.project.id) {
      loadedId.current = value.project.id;
      setSource(value.project.source);
      setDraft(value.draft);
      draftRef.current = {
        id: value.project.id,
        value: value.draft,
        dirty: false,
      };
      setDocuments(await api.workflowDocuments(value.project.id));
      setRewrapFiles(value.project.files.map((item) => item.name));
    }
  }
  async function refresh() {
    await accept(await api.workflowState());
  }
  useEffect(() => {
    refresh().catch(report);
  }, []);
  useEffect(() => {
    if (!visible && !state?.active) return;
    if (!state?.active) {
      if (visible) refresh().catch(report);
      return;
    }
    const timer = setInterval(() => {
      refresh().then(onChange).catch(report);
    }, 200);
    return () => clearInterval(timer);
  }, [visible, state?.active]);
  async function run(label: string, action: () => Promise<void>) {
    setBusy(label);
    setNotice("");
    try {
      await action();
    } catch (error) {
      report(error);
    } finally {
      setBusy("");
      onChange();
    }
  }
  async function update(values: Record<string, unknown>) {
    const current = stateRef.current!.project!;
    setState({
      ...stateRef.current!,
      project: { ...current, ...values } as GuidedProject,
    });
    try {
      const value = await api.workflowUpdate({
        project_id: current.id,
        revision: current.revision,
        values,
      });
      stateRef.current = value;
      await accept(value);
    } catch (error) {
      await refresh();
      throw error;
    }
  }
  async function commitControls() {
    if (draftRef.current.value.engine_options) {
      await update({ engine_options: draftRef.current.value.engine_options });
      const next = { ...draftRef.current.value };
      delete next.engine_options;
      editDraft(next);
      await flushDraft();
    }
  }
  async function action(
    name: string,
    parameters: Record<string, unknown> = {},
  ) {
    const preview = await api.workflowPreview({
      project_id: project!.id,
      action: name,
      options: parameters,
    });
    if (preview.confirmation) setPending(preview);
    else {
      await api.workflowExecute(preview.token);
      await refresh();
    }
  }
  async function execute() {
    await api.workflowExecute(pending!.token);
    setPending(null);
    await refresh();
  }
  useEffect(() => {
    if (
      !pending &&
      nextStage !== null &&
      latest?.action === "import" &&
      latest.status === "complete" &&
      !state?.active
    ) {
      const next = nextStage;
      setNextStage(null);
      run("Opening stage", () => update({ step: next }));
    } else if (
      nextStage !== null &&
      latest?.action === "import" &&
      ["failed", "interrupted", "stopped"].includes(latest.status)
    )
      setNextStage(null);
  }, [latest?.id, latest?.status, state?.active, pending]);
  async function navigate(target: number, complete = false) {
    await commitControls();
    if (
      step === 0 &&
      target !== 0 &&
      JSON.stringify([...project!.selected].sort()) !==
        JSON.stringify([...project!.imported].sort())
    ) {
      setNextStage(target);
      await action("import", { files: project!.selected });
      return;
    }
    await update({
      step: target,
      ...(complete ? { done: [...new Set([...project!.done, step])] } : {}),
    });
  }
  const actionButton = (
    name: string,
    label: string,
    parameters: Record<string, unknown> = {},
    primary = false,
  ) => (
    <button
      className={primary ? "primary" : "secondary"}
      disabled={disabled}
      onClick={() => run(label, () => action(name, parameters))}
    >
      {label}
    </button>
  );
  const skillButton = (name: string, label: string) => (
    <button
      className="secondary"
      disabled={!!busy}
      onClick={() =>
        run(label, async () => {
          await api.copyText(await api.workflowSkill(project!.id, name));
          setNotice("Skill copied.");
        })
      }
    >
      {label}
    </button>
  );
  const phaseButton = (phase: string, label: string) => (
    <button
      className="primary"
      disabled={
        disabled ||
        (!state?.allow_providers &&
          (phase === "speakers" ||
            ["translate", "batch"].includes(project?.mode || "")))
      }
      onClick={() =>
        run(label, async () => {
          await commitControls();
          await api.workflowPhase({ project_id: project!.id, phase, sync });
          await refresh();
        })
      }
    >
      <Play size={14} />
      {label}
    </button>
  );
  const fields = (filter: (key: string) => boolean) => (
    <fieldset className="settings-grid" disabled={disabled}>
      {state?.engine_schema
        .filter((field) => filter(field.key))
        .map((field) => (
          <InputField
            key={field.key}
            prefix="workflow"
            field={field}
            value={options[field.key] ?? field.default}
            onChange={(value) =>
              editDraft({
                ...draft,
                engine_options: { ...options, [field.key]: value },
              })
            }
          />
        ))}
    </fieldset>
  );
  const selection = (
    names: string[],
    selected: string[],
    setSelected: (value: string[]) => void,
  ) => (
    <FileScope
      key={`${project?.id}-${step}`}
      names={names}
      selected={selected}
      onChange={setSelected}
      query={query}
      disabled={disabled}
    />
  );
  const rewrapOptions = {
    files: rewrapFiles,
    widths,
    categories: rewrapCategories,
    codes,
    max_rows: maxRows,
    protect_rows: protectRows,
    over_limit: overLimit,
  };
  const lastHandoff = state?.jobs.find(
    (job) => typeof job.result?.handoff === "string",
  );
  return (
    <div className="guided-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">GUIDED WORKFLOW</span>
          <h1>{isWolf ? "WOLF RPG" : "RPG Maker"}</h1>
          <p className="muted">
            Prepare, translate, review and release your game.
          </p>
        </div>
        <button className="secondary" onClick={() => setHelpOpen(!helpOpen)}>
          Stage help
        </button>
      </div>
      <div className="workflow-project toolbar">
        <label className="grow">
          Game root
          <input
            aria-label="Guided game root"
            value={source}
            disabled={disabled}
            onChange={(event) => setSource(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter")
                run("Detecting game", async () => {
                  await flushDraft();
                  await accept(await api.workflowOpen(source));
                });
            }}
          />
        </label>
        <button
          className="secondary"
          disabled={disabled}
          onClick={() =>
            run("Choosing game", async () => {
              const selected = await api.chooseFolder();
              if (selected) {
                await flushDraft();
                await accept(await api.workflowOpen(selected));
              }
            })
          }
        >
          <FolderOpen size={15} />
          Browse
        </button>
        <button
          className="primary"
          disabled={disabled || !source}
          onClick={() =>
            run("Detecting game", async () => {
              await flushDraft();
              await accept(await api.workflowOpen(source));
            })
          }
        >
          Detect game
        </button>
      </div>
      {!!state?.projects.length && (
        <label className="setting-field">
          Recent guided projects
          <select
            aria-label="Recent guided projects"
            disabled={disabled}
            value={project?.source || ""}
            onChange={(event) =>
              run("Opening game", async () => {
                await flushDraft();
                await accept(await api.workflowOpen(event.target.value));
              })
            }
          >
            {state.projects.map((item) => (
              <option key={item.id} value={item.source}>
                {item.source}
              </option>
            ))}
          </select>
        </label>
      )}
      {notice && (
        <p role="status" className="success-note">
          {notice}
        </p>
      )}
      {busy && (
        <p role="status" className="muted">
          {busy}…
        </p>
      )}
      {project && (
        <>
          <nav className="workflow-stages" aria-label="Guided stages">
            {stages
              .slice(0, project.engine === "ACE" ? 8 : 10)
              .map((label, index) => (
                <button
                  key={label}
                  className={step === index ? "active" : ""}
                  disabled={disabled}
                  onClick={() => run("Opening stage", () => navigate(index))}
                >
                  <span>
                    {project.done.includes(index) ? (
                      <Check size={14} />
                    ) : (
                      index + 1
                    )}
                  </span>
                  {label}
                </button>
              ))}
          </nav>
          {helpOpen && <aside className="workflow-help">{help[step]}</aside>}
          <section className="panel workflow-stage">
            <div className="panel-heading">
              <h2>{stages[step]}</h2>
              <span className="badge">
                {project.engine} · {step + 1}/
                {project.engine === "ACE" ? 8 : 10}
              </span>
            </div>
            {isWolf && (
              <WolfStages
                project={project}
                jobs={state?.jobs || []}
                draft={draft.wolf || {}}
                edit={(wolf) => editDraft({ ...draft, wolf })}
                disabled={disabled}
                action={actionButton}
                phase={phaseButton}
                skill={skillButton}
                update={(values) =>
                  run("Saving WOLF settings", () => update(values))
                }
              />
            )}
            {step === 0 && (
              <>
                <p className="muted">{project.data}</p>
                {project.engine === "ACE" && (
                  <div className="toolbar">
                    {actionButton("ace_decrypt", "Run Ace decrypter")}
                    {actionButton("ace_extract", "Convert Ace data to JSON")}
                    {actionButton("ace_pack", "Pack Ace JSON")}
                  </div>
                )}
                <div className="toolbar">
                  <input
                    aria-label="Filter workflow files"
                    placeholder="Filter files"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                  {["All", "Clear", "Database"].map((mode) => (
                    <button
                      key={mode}
                      className="secondary"
                      disabled={disabled}
                      onClick={() =>
                        run("Updating selection", () =>
                          update({
                            selected:
                              mode === "Clear"
                                ? []
                                : project.files
                                    .filter(
                                      (file) =>
                                        mode === "All" ||
                                        file.category === "core",
                                    )
                                    .map((file) => file.name),
                          }),
                        )
                      }
                    >
                      {mode}
                    </button>
                  ))}
                </div>
                {selection(
                  project.files.map((file) => file.name),
                  project.selected,
                  (value) =>
                    run("Updating selection", () =>
                      update({ selected: value }),
                    ),
                )}
                <div className="toolbar">
                  {actionButton(
                    "import",
                    `Import ${project.selected.length} selected files`,
                    { files: project.selected },
                    true,
                  )}
                  <span className="muted">
                    {project.imported.length} files currently imported
                  </span>
                </div>
              </>
            )}
            {step === 1 && (
              <>
                <p className="muted">
                  Run the file preparation tasks before recording the original
                  Git baseline.
                </p>
                <div className="workflow-task">
                  <h3>1. Format game data</h3>
                  {actionButton("format_data", "Format game data")}
                </div>
                {!isWolf && (
                  <div className="workflow-task">
                    <h3>2. Format plugins.js</h3>
                    <p className="muted">
                      {project.plugins || "Not applicable to Ace"}
                    </p>
                    {project.plugins &&
                      actionButton("format_plugins", "Format plugins.js")}
                  </div>
                )}
                <div className="workflow-task">
                  <h3>3. Install GameUpdate</h3>
                  {actionButton("gameupdate", "Install GameUpdate")}
                </div>
                <div className="workflow-task">
                  <h3>4. Set up Git version tracking</h3>
                  <div className="settings-grid">
                    <label className="setting-field">
                      Current game version
                      <input
                        value={version}
                        onChange={(event) => setVersion(event.target.value)}
                        placeholder="1.00"
                      />
                    </label>
                    <label className="setting-field">
                      Matching original game
                      <input
                        value={original}
                        onChange={(event) => setOriginal(event.target.value)}
                      />
                    </label>
                  </div>
                  <label className="setting-toggle">
                    <input
                      type="checkbox"
                      checked={untranslated}
                      onChange={(event) =>
                        setUntranslated(event.target.checked)
                      }
                    />
                    This selected game is still untranslated; use it as the
                    original baseline.
                  </label>
                  <div className="toolbar">
                    {actionButton("git_status", "Inspect Git")}
                    {actionButton("git_setup", "Set up version tracking", {
                      version,
                      original,
                      untranslated,
                    })}
                  </div>
                </div>
              </>
            )}
            {step === 2 && (
              <>
                {!isWolf && <h3>Speaker detection</h3>}
                {!isWolf && fields((key) => speakerKeys.has(key))}
                <div className="toolbar">
                  {!isWolf && phaseButton("speakers", "Collect names")}
                  {skillButton("setup", "Copy setup skill")}
                </div>
                {!isWolf && (
                  <details className="workflow-task">
                    <summary>Reference translations</summary>
                    <p className="muted">
                      References provide exact source matches for Setup and QA.
                      Reference games remain unchanged.
                    </p>
                    {state?.references.map((reference) => (
                      <div className="toolbar" key={reference.id}>
                        <strong>{reference.title}</strong>
                        <span className="muted">
                          {reference.mode} · {reference.translated_data}
                        </span>
                        {actionButton("reference_remove", "Remove reference", {
                          id: reference.id,
                        })}
                      </div>
                    ))}
                    <div className="settings-grid">
                      <label className="setting-field">
                        Reference title
                        <input
                          value={referenceTitle}
                          onChange={(event) =>
                            setReferenceTitle(event.target.value)
                          }
                        />
                      </label>
                      <label className="setting-field">
                        Translated reference game or data folder
                        <input
                          value={referenceTranslated}
                          onChange={(event) =>
                            setReferenceTranslated(event.target.value)
                          }
                        />
                      </label>
                      <label className="setting-field">
                        Japanese reference game (for pairs)
                        <input
                          value={referenceOriginal}
                          onChange={(event) =>
                            setReferenceOriginal(event.target.value)
                          }
                        />
                      </label>
                    </div>
                    <div className="toolbar">
                      {actionButton(
                        "reference_add",
                        "Add DazedTL translation",
                        {
                          title: referenceTitle,
                          translated: referenceTranslated,
                        },
                      )}
                      {actionButton(
                        "reference_pair",
                        "Add Japanese / English pair",
                        {
                          title: referenceTitle,
                          original: referenceOriginal,
                          translated: referenceTranslated,
                        },
                      )}
                      {actionButton("reference_build", "Build exact matches")}
                    </div>
                  </details>
                )}
                {Object.entries({
                  glossary: "Glossary",
                  quirks: "Translation quirks",
                  game: "Game skill",
                  ...Object.fromEntries(
                    Object.keys(documents)
                      .filter((name) => name.startsWith("custom:"))
                      .map((name) => [name, name.slice(7)]),
                  ),
                }).map(([name, label]) => (
                  <div className="workflow-document" key={name}>
                    <label htmlFor={`workflow-${name}`}>{label}</label>
                    <textarea
                      id={`workflow-${name}`}
                      value={
                        draft.documents?.[name]?.text ??
                        documents[name]?.text ??
                        ""
                      }
                      onChange={(event) =>
                        editDraft({
                          ...draft,
                          documents: {
                            ...draft.documents,
                            [name]: {
                              text: event.target.value,
                              revision:
                                draft.documents?.[name]?.revision ||
                                documents[name]?.revision ||
                                "",
                            },
                          },
                        })
                      }
                    />
                    <div className="toolbar">
                      <button
                        className="primary"
                        disabled={disabled || !draft.documents?.[name]}
                        onClick={() =>
                          run(`Saving ${label}`, async () => {
                            const value = draft.documents![name];
                            setDocuments(
                              await api.workflowDocumentSave({
                                project_id: project.id,
                                name,
                                text: value.text,
                                revision: value.revision,
                              }),
                            );
                            const next = {
                              ...draft,
                              documents: { ...draft.documents },
                            };
                            delete next.documents![name];
                            editDraft(next);
                            await flushDraft();
                          })
                        }
                      >
                        Save {label.toLowerCase()}
                      </button>
                      {draft.documents?.[name] && (
                        <button
                          className="secondary"
                          onClick={() =>
                            run("Discarding saved draft", async () => {
                              const next = {
                                ...draft,
                                documents: { ...draft.documents },
                              };
                              delete next.documents![name];
                              editDraft(next);
                              await flushDraft();
                              setDocuments(
                                await api.workflowDocuments(project.id),
                              );
                            })
                          }
                        >
                          Discard draft and reload
                        </button>
                      )}
                      <button
                        className="secondary"
                        disabled={!!draft.documents?.[name]}
                        onClick={() =>
                          run(`Reloading ${label}`, async () =>
                            setDocuments(
                              await api.workflowDocuments(project.id),
                            ),
                          )
                        }
                      >
                        Reload
                      </button>
                      <span className="muted">
                        {draft.documents?.[name]
                          ? "Draft saved separately until you press Save"
                          : documents[name]?.path}
                      </span>
                    </div>
                  </div>
                ))}
                <div className="toolbar">
                  <label className="setting-field">
                    Custom skill name
                    <input
                      value={customSkill}
                      onChange={(event) => setCustomSkill(event.target.value)}
                      placeholder="dialogue-style"
                    />
                  </label>
                  <button
                    className="secondary"
                    disabled={disabled || !customSkill.trim()}
                    onClick={() =>
                      run("Adding custom skill", async () => {
                        setDocuments(
                          await api.workflowDocumentSave({
                            project_id: project.id,
                            name: "custom:" + customSkill.trim(),
                            text: "",
                            revision: "",
                          }),
                        );
                        setCustomSkill("");
                      })
                    }
                  >
                    Add custom skill
                  </button>
                </div>
              </>
            )}
            {(step === 3 || step === 4 || (isWolf && step === 5)) && (
              <>
                <div className="toolbar">
                  <label>
                    Translation mode
                    <select
                      aria-label="Workflow translation mode"
                      value={project.mode}
                      disabled={disabled}
                      onChange={(event) =>
                        run("Saving mode", () =>
                          update({ mode: event.target.value }),
                        )
                      }
                    >
                      <option value="translate">Normal</option>
                      <option value="batch">Batch</option>
                      <option value="estimate">Local estimate</option>
                      <option value="offline">Offline test</option>
                    </select>
                  </label>
                  <label className="setting-toggle">
                    <input
                      type="checkbox"
                      checked={sync}
                      onChange={(event) => setSync(event.target.checked)}
                    />
                    Sync completed translations before this phase
                  </label>
                </div>
                {!state?.allow_providers && (
                  <p className="muted">
                    Provider execution is disabled in this migration build.
                    Local estimates and offline tests are available.
                  </p>
                )}
              </>
            )}
            {((isWolf && step === 5) ||
              (!isWolf && (step === 3 || step === 6))) && (
              <>
                <div className="settings-grid">
                  {Object.entries(widthLabels).map(([key, label]) => (
                    <label className="setting-field" key={key}>
                      {label}
                      <input
                        type="number"
                        min="20"
                        max="300"
                        value={widths[key] || ""}
                        onChange={(event) =>
                          editDraft({
                            ...draft,
                            widths: {
                              ...widths,
                              [key]: Number(event.target.value),
                            },
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
                <div className="toolbar">
                  <button
                    className="secondary"
                    disabled={disabled}
                    onClick={() =>
                      run("Saving widths", async () => {
                        await update({ widths });
                        const next = { ...draft };
                        delete next.widths;
                        editDraft(next);
                        await flushDraft();
                      })
                    }
                  >
                    Save line widths
                  </button>
                  <button
                    className="secondary"
                    disabled={!!draft.widths}
                    onClick={() =>
                      run("Loading widths", async () => {
                        await accept(await api.workflowOpen(project.source));
                      })
                    }
                  >
                    Load saved widths
                  </button>
                  {skillButton("wrap", "Copy width analysis skill")}
                </div>
              </>
            )}
            {!isWolf && step === 3 && (
              <>
                <label className="setting-toggle">
                  <input
                    type="checkbox"
                    checked={project.phase1_comments}
                    disabled={disabled}
                    onChange={(event) =>
                      run("Saving comment scope", () =>
                        update({ phase1_comments: event.target.checked }),
                      )
                    }
                  />
                  Translate supported comment continuations (code 408)
                </label>
                <div className="workflow-phase-actions">
                  {phaseButton("database", "Translate database")}
                  {phaseButton("dialogue", "Translate dialogue")}
                  {phaseButton("variables", "Build variable cache")}
                </div>
              </>
            )}
            {!isWolf && step === 4 && (
              <>
                <div className="toolbar">
                  {skillButton("advanced", "Copy advanced-text audit")}
                </div>
                {fields((key) =>
                  [
                    "CODE122",
                    "CODE122_VAR_RANGES",
                    "CODE355655",
                    "CODE357",
                    "CODE657",
                    "CODE356",
                    "CODE320",
                    "CODE324",
                    "CODE325",
                    "CODE108",
                  ].includes(key),
                )}
                <details>
                  <summary>Plugin and script handlers</summary>
                  {fields((key) => key.startsWith("ENABLED_"))}
                </details>
                <div className="toolbar">
                  <button
                    className="secondary"
                    disabled={disabled || !draft.engine_options}
                    onClick={() =>
                      run("Saving advanced settings", commitControls)
                    }
                  >
                    Save advanced settings
                  </button>
                  {phaseButton("advanced", "Translate selected text")}
                </div>
              </>
            )}
            {!isWolf && step === 5 && (
              <>
                <div className="toolbar">
                  {skillButton(
                    "plugins",
                    project.engine === "ACE"
                      ? "Copy Ruby translation skill"
                      : "Copy plugin translation skill",
                  )}
                </div>
                <p className="muted">
                  Export writes completed translations to {project.data}.
                </p>
                <div className="toolbar">
                  {actionButton("export_selected", "Export selected files")}
                  {actionButton("export_all", "Export all translated files")}
                  {project.engine === "ACE" &&
                    actionButton("ace_pack", "Pack translated Ace data")}
                </div>
              </>
            )}
            {!isWolf && step === 6 && (
              <>
                <div className="toolbar">
                  <input
                    aria-label="Filter rewrap files"
                    placeholder="Filter files"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                  {["All", "Clear", "Events", "Database"].map((mode) => (
                    <button
                      className="secondary"
                      key={mode}
                      onClick={() =>
                        setRewrapFiles(
                          project.files
                            .filter(
                              (file) =>
                                mode === "All" ||
                                (mode === "Events" &&
                                  (/^Map\d+\.json$/.test(file.name) ||
                                    [
                                      "CommonEvents.json",
                                      "Troops.json",
                                    ].includes(file.name))) ||
                                (mode === "Database" &&
                                  databaseNames.has(file.name)),
                            )
                            .map((file) => file.name),
                        )
                      }
                    >
                      {mode}
                    </button>
                  ))}
                </div>
                {selection(
                  project.files.map((file) => file.name),
                  rewrapFiles,
                  setRewrapFiles,
                )}
                <div className="toolbar">
                  {["dialogue", "face_dialogue", "list", "notes"].map(
                    (category) => (
                      <label className="setting-toggle" key={category}>
                        <input
                          type="checkbox"
                          checked={rewrapCategories.includes(category)}
                          onChange={(event) =>
                            setRewrapCategories(
                              event.target.checked
                                ? [...rewrapCategories, category]
                                : rewrapCategories.filter(
                                    (item) => item !== category,
                                  ),
                            )
                          }
                        />
                        {category.replaceAll("_", " ")}
                      </label>
                    ),
                  )}
                </div>
                <div className="settings-grid">
                  <label className="setting-field">
                    Event codes
                    <input
                      value={codes}
                      onChange={(event) => setCodes(event.target.value)}
                    />
                  </label>
                  <label className="setting-field">
                    Protected row limit
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={maxRows}
                      onChange={(event) =>
                        setMaxRows(Number(event.target.value))
                      }
                    />
                  </label>
                </div>
                <label className="setting-toggle">
                  <input
                    type="checkbox"
                    checked={protectRows}
                    onChange={(event) => setProtectRows(event.target.checked)}
                  />
                  Skip protected row overflow
                </label>
                <label className="setting-toggle">
                  <input
                    type="checkbox"
                    checked={overLimit}
                    onChange={(event) => setOverLimit(event.target.checked)}
                  />
                  Only rewrap text over its line-width limit
                </label>
                <div className="toolbar">
                  {actionButton(
                    "rewrap_preview",
                    "Preview rewrap",
                    rewrapOptions,
                  )}
                  {actionButton("rewrap_apply", "Apply rewrap", rewrapOptions)}
                  {skillButton("qa", "Copy final QA skill")}
                </div>
              </>
            )}
            {!isWolf && step === 7 && (
              <>
                <div className="toolbar">
                  {skillButton("investigation", "Copy investigation skill")}
                  <button
                    className="secondary"
                    disabled={
                      !!draft.documents &&
                      Object.keys(draft.documents).length > 0
                    }
                    onClick={() =>
                      run("Reviewing guidance", async () => {
                        setDocuments(await api.workflowDocuments(project.id));
                        await update({ step: 2 });
                      })
                    }
                  >
                    Reload and review guidance
                  </button>
                </div>
                <label className="setting-field">
                  QA pass
                  <select
                    value={focus}
                    onChange={(event) => setFocus(event.target.value)}
                  >
                    <option value="release">
                      Full game — coverage & release gate
                    </option>
                    <option value="database">Targeted — database files</option>
                    <option value="risky-codes">
                      Targeted — risky event codes
                    </option>
                    <option value="dialogue">
                      Targeted — dialogue, lore & wordplay
                    </option>
                  </select>
                </label>
                <div className="toolbar">
                  {actionButton("qa_status", "Refresh QA status", { focus })}
                  {actionButton(
                    "qa_prepare",
                    "Prepare / resume QA",
                    { focus },
                    true,
                  )}
                  {actionButton("qa_rebuild", "Create final rebuild handoff", {
                    focus,
                  })}
                </div>
                {lastHandoff && (
                  <button
                    className="secondary"
                    onClick={() =>
                      run("Copying handoff", async () => {
                        await api.copyText(String(lastHandoff.result!.handoff));
                        setNotice("QA handoff copied.");
                      })
                    }
                  >
                    Copy prepared QA handoff
                  </button>
                )}
              </>
            )}
            {!isWolf && step === 8 && (
              <>
                <p className="muted">
                  Open the selected game's image workspace to edit, render and
                  review images.
                </p>
                {actionButton("images_status", "Refresh readiness")}
                <button
                  className="primary"
                  disabled={disabled}
                  onClick={() => openImages(project.source)}
                >
                  Open Image Manager
                </button>
              </>
            )}
            {!isWolf && step === 9 && (
              <>
                <div className="toolbar">
                  <button className="secondary" onClick={openSettings}>
                    Hotkeys, scale and editor settings
                  </button>
                  {actionButton("editors", "Find editors")}
                  {actionButton("playtest_apply", "Apply settings to game")}
                </div>
                <div className="toolbar">
                  {actionButton("inspector_install", "Install TL Inspector")}
                  {actionButton("inspector_remove", "Remove TL Inspector")}
                  {actionButton("forge_install", "Install Forge")}
                  {actionButton("forge_remove", "Remove Forge")}
                  {actionButton("playtest_install", "Install both plugins")}
                  {actionButton("playtest_status", "Refresh plugin status")}
                  {skillButton("walkthrough", "Copy walkthrough skill")}
                </div>
              </>
            )}
            {(step === 9 || (step === 7 && project.engine === "ACE")) && (
              <div className="workflow-task">
                <h3>Public release</h3>
                <label className="setting-field">
                  Release ZIP destination
                  <input
                    value={output}
                    onChange={(event) => setOutput(event.target.value)}
                    placeholder="Choose a path outside the game folder"
                  />
                </label>
                {actionButton(
                  "release",
                  "Build public release ZIP",
                  { output },
                  true,
                )}
              </div>
            )}
            <div className="workflow-next">
              <button
                className="secondary"
                disabled={disabled || step === 0}
                onClick={() =>
                  run("Opening previous stage", () => navigate(step - 1))
                }
              >
                <ArrowLeft size={15} />
                Back
              </button>
              <button
                className="primary"
                disabled={
                  disabled || step === (project.engine === "ACE" ? 7 : 9)
                }
                onClick={() =>
                  run("Continuing workflow", () => navigate(step + 1, true))
                }
              >
                Continue
                <ArrowRight size={15} />
              </button>
            </div>
          </section>
          {manual && (
            <section className="panel workflow-run">
              <div className="panel-heading">
                <h2>Translation run</h2>
                <span className="badge">{manual.status}</span>
              </div>
              <p>{manual.message}</p>
              {manual.progress && (
                <progress
                  max={manual.progress.total || 1}
                  value={manual.progress.current}
                />
              )}
              {manual.estimate && (
                <details>
                  <summary>Estimate details</summary>
                  <pre>{JSON.stringify(manual.estimate, null, 2)}</pre>
                </details>
              )}
              {manual.approval && (
                <div className="workflow-help">
                  <h3>
                    {manual.approval.kind === "batch"
                      ? "Submit this provider batch?"
                      : "Translate the collected speaker names?"}
                  </h3>
                  <pre>{JSON.stringify(manual.approval.detail, null, 2)}</pre>
                  <div className="toolbar">
                    {[false, true].map((approved) => (
                      <button
                        className={approved ? "primary" : "secondary"}
                        key={String(approved)}
                        onClick={() =>
                          run("Answering run", async () => {
                            await api.manualAnswer({
                              job_id: manual.id,
                              token: manual.approval!.token,
                              approved,
                            });
                            await refresh();
                          })
                        }
                      >
                        {approved ? "Approve" : "Cancel"}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {["running", "waiting"].includes(manual.status) ? (
                <button
                  className="secondary"
                  onClick={() =>
                    run("Stopping translation", async () => {
                      await api.manualStop(manual.id);
                      await refresh();
                    })
                  }
                >
                  <Square size={14} />
                  Stop translation
                </button>
              ) : (
                ["failed", "stopped", "interrupted", "canceled"].includes(
                  manual.status,
                ) && (
                  <button
                    className="secondary"
                    disabled={disabled}
                    onClick={() =>
                      run("Resuming translation", async () => {
                        await api.manualResume(manual.id);
                        await refresh();
                      })
                    }
                  >
                    Resume translation
                  </button>
                )
              )}
              {project.collection_error && (
                <p role="alert">{project.collection_error}</p>
              )}
            </section>
          )}
          <section className="panel workflow-console">
            <div className="panel-heading">
              <h2>Activity</h2>
              <div className="toolbar">
                {state?.active && latest?.status === "running" && (
                  <button
                    className="secondary"
                    onClick={() =>
                      run("Stopping action", async () => {
                        await api.workflowStop(latest.id);
                        await refresh();
                      })
                    }
                  >
                    <Square size={14} />
                    Stop action
                  </button>
                )}
                <button
                  className="secondary"
                  onClick={() => setClearedAt(new Date().toISOString())}
                >
                  Clear activity
                </button>
              </div>
            </div>
            {state?.jobs
              .filter((job) => job.created > clearedAt)
              .slice(0, 8)
              .map((job) => (
                <div className="workflow-activity" key={job.id}>
                  <strong>
                    {job.label} · {job.status}
                  </strong>
                  <p>{job.message}</p>
                  <details open={job.id === latest?.id}>
                    <summary>Details</summary>
                    <pre>{job.log.join("\n")}</pre>
                    {job.result && (
                      <pre>
                        {JSON.stringify(
                          Object.fromEntries(
                            Object.entries(job.result).filter(
                              ([key]) => key !== "handoff",
                            ),
                          ),
                          null,
                          2,
                        )}
                      </pre>
                    )}
                  </details>
                </div>
              ))}
            {manual && manual.created > clearedAt && (
              <pre>{manual.log.join("\n")}</pre>
            )}
          </section>
        </>
      )}
      {pending && (
        <div className="modal-backdrop">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Confirm guided action"
            className="modal"
          >
            <h2>{pending.label}</h2>
            <p>This action writes to:</p>
            <code>{pending.destination}</code>
            {pending.overwrite && (
              <p>The existing release ZIP will be replaced.</p>
            )}
            {pending.files > 0 && <p>{pending.files} selected files</p>}
            <p className="muted">
              Check the destination before continuing. Changed inputs invalidate
              this preview.
            </p>
            <div className="toolbar">
              <button
                className="secondary"
                autoFocus
                onClick={() => {
                  setPending(null);
                  setNextStage(null);
                }}
              >
                Cancel
              </button>
              <button
                className="primary"
                disabled={!!busy}
                onClick={() => run(pending.label, execute)}
              >
                Run action
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
