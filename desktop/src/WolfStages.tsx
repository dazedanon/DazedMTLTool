import type { ReactNode } from "react";
import type { GuidedProject, OperationJob, WolfDraft } from "./types";
import { FileScope } from "./FileScope";

export const wolfStages = [
  "Project",
  "Prepare",
  "Setup",
  "Names",
  "Database",
  "Maps & events",
  "Check",
  "Apply",
  "Playtest",
  "Fix layout",
];
export const wolfHelp = [
  "Unpack archives, extract text with pristine binary backups, then import the selected JSON. Re-extraction uses the original archive baseline when available.",
  "Format the extracted JSON, install GameUpdate, then record the original Git baseline.",
  "Prepare the game glossary and instructions. Reliable first-line nameplates are always handled; choose whether to trust uncertain first-line names after reviewing the speaker skill.",
  "Translate safe name entries first. Reference-only and verify entries remain protected by the shared WOLF engine.",
  "Discover the database layout. Translate foundation sheets before narrative sheets; select individual sheets or import a reviewed AI profile.",
  "Translate maps, common events, Game.dat and external event text using the game's glossary and speaker settings.",
  "Reconcile names and dry-run every translated file. Copy the repair handoff when the check identifies issues, then check again.",
  "Apply the complete injectable set together using pristine binaries. Choose translated files or the game's wolf_json copy, with optional synchronization back to this workspace.",
  "Back up packed archives to run loose data, or repack Data.wolf. Existing saves can be updated with automatic backups. Build the public ZIP when ready.",
  "Find text as it appears in game, preview wrapping, and apply Manual or Relayout to a row or group. Then apply translations and package again.",
];

type Hit = {
  id: Record<string, string | number>;
  summary: string;
  text: string;
};
type Group = {
  key: string;
  tier: string;
  type_name?: string;
  typeName?: string;
  sheet_name?: string;
};
export function WolfStages({
  project,
  jobs,
  draft,
  edit,
  disabled,
  action,
  phase,
  skill,
  update,
}: {
  project: GuidedProject;
  jobs: OperationJob[];
  draft: WolfDraft;
  edit: (value: WolfDraft) => void;
  disabled: boolean;
  action: (
    name: string,
    label: string,
    options?: Record<string, unknown>,
    primary?: boolean,
  ) => ReactNode;
  phase: (name: string, label: string) => ReactNode;
  skill: (name: string, label: string) => ReactNode;
  update: (value: Partial<GuidedProject>) => void;
}) {
  const step = project.step;
  const discovery = jobs.find(
    (job) =>
      ["wolf_discover", "wolf_profile"].includes(job.action) &&
      job.status === "complete",
  )?.result;
  const groups =
    (discovery?.distribution as { groups?: Group[] })?.groups || [];
  const search = jobs.find(
    (job) => job.action === "wolf_search" && job.status === "complete",
  )?.result;
  const hits = (search?.hits || []) as Hit[];
  const hit = draft.hit;
  const precheck = jobs.find(
    (job) => job.action === "wolf_precheck" && job.result,
  )?.result;
  const preview = jobs.find(
    (job) => job.action === "wolf_wrap_preview" && job.status === "complete",
  )?.result;
  const wrap = {
    hit,
    width: draft.width ?? 50,
    font: draft.font ?? 0,
    max_lines: draft.max_lines ?? 0,
    manual: draft.manual ?? true,
    scope: draft.scope || "row",
  };
  const punctuation = (
    <label className="setting-toggle">
      <input
        type="checkbox"
        checked={draft.en_punct ?? true}
        disabled={disabled}
        onChange={(e) => edit({ ...draft, en_punct: e.target.checked })}
      />
      Use English punctuation during injection
    </label>
  );
  return (
    <>
      {step === 0 && (
        <div className="toolbar">
          {action("wolf_unpack", "Unpack archives")}
          {action("wolf_extract", "Extract text and backups")}
          {action("wolf_maps", "Extract missing maps")}
        </div>
      )}
      {(step === 2 || step === 5) && (
        <div className="workflow-task">
          <label className="setting-toggle">
            <input
              type="checkbox"
              checked={project.wolf.literal_line1_lowconf}
              disabled={disabled}
              onChange={(e) =>
                update({
                  wolf: {
                    ...project.wolf,
                    literal_line1_lowconf: e.target.checked,
                  },
                })
              }
            />
            Treat uncertain first-line names as speakers
          </label>
          <p className="muted">
            Reliable nameplates are handled automatically. Speaker checks run
            before translation.
          </p>
          {skill("wolf_speakers", "Copy WOLF speaker skill")}
        </div>
      )}
      {step === 3 && (
        <>
          <p className="muted">
            Translate safe name entries first to seed the glossary.
          </p>
          <div className="toolbar">
            {action("wolf_names", "Refresh name safety")}
            {phase("names", "Translate safe names")}
          </div>
          {jobs.find((j) => j.action === "wolf_names")?.result && (
            <pre className="engine-log">
              {String(
                jobs.find((j) => j.action === "wolf_names")?.result?.summary ||
                  "",
              )}{" "}
              {"\n"}
              {String(
                jobs.find((j) => j.action === "wolf_names")?.result
                  ?.categories || "",
              )}
            </pre>
          )}
        </>
      )}
      {step === 4 && (
        <>
          <div className="toolbar">
            {action("wolf_discover", "Discover database sheets")}
            {typeof discovery?.prompt === "string" && (
              <button
                className="secondary"
                onClick={() => api.copyText(discovery.prompt as string)}
              >
                Copy database audit
              </button>
            )}
          </div>
          {discovery && (
            <pre className="engine-log">{String(discovery.summary || "")}</pre>
          )}
          {!!groups.length && (
            <>
              <FileScope
                names={groups.map((g) => g.key)}
                selected={project.wolf.db_groups}
                disabled={disabled}
                onChange={(db_groups) =>
                  update({ wolf: { ...project.wolf, db_groups } })
                }
              />
              <p className="muted">
                {groups.map((g) => `${g.key}: ${g.tier}`).join(" · ")}
              </p>
            </>
          )}
          <div className="workflow-phase-actions">
            {phase("foundation", "Translate foundation sheets")}
            {phase("narrative", "Translate narrative sheets")}
            {phase("db_selected", "Translate checked sheets")}
            {phase("database", "Translate all database sheets")}
          </div>
          <details className="workflow-task">
            <summary>Import AI database profile</summary>
            <textarea
              aria-label="WOLF database profile"
              className="code-editor"
              value={draft.profile || ""}
              onChange={(e) => edit({ ...draft, profile: e.target.value })}
            />
            {action("wolf_profile", "Save database profile", {
              profile: draft.profile || "",
            })}
            {discovery?.profile != null && (
              <pre className="engine-log">
                {JSON.stringify(discovery.profile, null, 2)}
              </pre>
            )}
          </details>
        </>
      )}
      {step === 5 && (
        <div className="toolbar">
          {phase("maps", "Translate maps and events")}
        </div>
      )}
      {step === 6 && (
        <>
          {punctuation}
          <p className="muted">
            This check first reconciles names in translated files, then checks
            the complete injection set.
          </p>
          {action(
            "wolf_precheck",
            "Run name and injection checks",
            { en_punct: draft.en_punct ?? true },
            true,
          )}
          {typeof precheck?.prompt === "string" && precheck.prompt && (
            <button
              className="secondary"
              onClick={() => api.copyText(precheck.prompt as string)}
            >
              Copy AI repair handoff
            </button>
          )}
        </>
      )}
      {step === 7 && (
        <>
          {punctuation}
          <p className="muted">
            All injectable files are applied together from pristine originals.
            The activity report lists successes and any failed files.
          </p>
          <label className="setting-toggle">
            <input
              type="checkbox"
              checked={draft.sync ?? true}
              disabled={disabled}
              onChange={(e) => edit({ ...draft, sync: e.target.checked })}
            />
            When applying wolf_json, also sync it to this workspace's files and
            translations
          </label>
          <div className="toolbar">
            {action(
              "wolf_inject",
              "Apply all translations",
              { en_punct: draft.en_punct ?? true },
              true,
            )}
            {action("wolf_inject_game", "Apply from wolf_json", {
              en_punct: draft.en_punct ?? true,
              sync: draft.sync ?? true,
            })}
            {action("wolf_restore", "Restore source whitespace")}
          </div>
        </>
      )}
      {step === 8 && (
        <>
          <div className="toolbar">
            {action("wolf_loose", "Use loose Data folder")}
            {action("wolf_repack", "Repack Data.wolf")}
            {skill("walkthrough", "Copy walkthrough skill")}
          </div>
          <label className="setting-field">
            Existing save folder or .sav file
            <input
              value={draft.save_path || ""}
              onChange={(e) => edit({ ...draft, save_path: e.target.value })}
            />
          </label>
          {action("wolf_saves", "Update existing saves", {
            path: draft.save_path || "",
          })}
          <label className="setting-field">
            Public release ZIP destination
            <input
              value={draft.output || ""}
              onChange={(e) => edit({ ...draft, output: e.target.value })}
            />
          </label>
          {action("release", "Build public release ZIP", {
            output: draft.output || "",
          })}
        </>
      )}
      {step === 9 && (
        <>
          <div className="toolbar">
            <label className="grow">
              Text shown in game
              <input
                aria-label="WOLF text search"
                value={draft.query || ""}
                onChange={(e) => edit({ ...draft, query: e.target.value })}
              />
            </label>
            {action("wolf_search", "Find text", { query: draft.query || "" })}
          </div>
          <div className="wolf-search-results">
            {hits.map((row, i) => (
              <button
                key={i}
                className={
                  JSON.stringify(row.id) === JSON.stringify(hit)
                    ? "active"
                    : "secondary"
                }
                onClick={() => edit({ ...draft, hit: row.id })}
              >
                {row.summary}
              </button>
            ))}
          </div>
          {hit && (
            <>
              <pre className="engine-log">
                {hits.find((h) => JSON.stringify(h.id) === JSON.stringify(hit))
                  ?.text || JSON.stringify(hit)}
              </pre>
              <fieldset disabled={disabled} className="settings-grid">
                <label>
                  Mode
                  <select
                    value={wrap.manual ? "manual" : "relayout"}
                    onChange={(e) =>
                      edit({ ...draft, manual: e.target.value === "manual" })
                    }
                  >
                    <option value="manual">Manual</option>
                    <option value="relayout">Relayout</option>
                  </select>
                </label>
                <label>
                  Scope
                  <select
                    value={wrap.scope}
                    onChange={(e) =>
                      edit({
                        ...draft,
                        scope: e.target.value as "row" | "group",
                      })
                    }
                  >
                    <option value="row">Selected row</option>
                    <option value="group">Group / dialogue format</option>
                  </select>
                </label>
                {(["width", "font", "max_lines"] as const).map((key) => (
                  <label key={key}>
                    {key === "width"
                      ? "Cell width (0 = names auto)"
                      : key === "font"
                        ? "Body font (0 = keep)"
                        : "Maximum lines (0 = keep)"}
                    <input
                      type="number"
                      min="0"
                      max={key === "width" ? 300 : key === "font" ? 200 : 100}
                      value={wrap[key]}
                      onChange={(e) =>
                        edit({ ...draft, [key]: Number(e.target.value) })
                      }
                    />
                  </label>
                ))}
              </fieldset>
              <div className="toolbar">
                {action("wolf_wrap_preview", "Preview WOLF wrap", wrap)}
                {action("wolf_wrap", "Apply WOLF wrap", wrap, true)}
              </div>
              {preview && (
                <pre className="engine-log">
                  {String(preview.wrapped || "")}
                </pre>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
import { api } from "./bridge";
