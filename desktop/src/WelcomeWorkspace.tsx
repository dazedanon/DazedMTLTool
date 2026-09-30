import type { ReactNode } from "react";
import type { Snapshot } from "./types";
import { api } from "./bridge";
import {
  ArrowRight,
  Files,
  NotebookPen,
  Route,
  BookOpen,
  Settings2,
} from "lucide-react";

const routes = [
  {
    page: "workflow",
    title: "Guided workflow",
    detail:
      "Take a game from preparation to translation, review and release with a clear next step at every stage.",
    engines: "RPG Maker MV / MZ / Ace · WOLF RPG",
    icon: Route,
    action: "Start guided workflow",
  },
  {
    page: "len",
    title: "Len’s Method",
    detail:
      "Work with your AI assistant using a game-specific handoff, shared guidance and saved progress.",
    engines: "Assistant-led game translation",
    icon: NotebookPen,
    action: "Open Len’s Method",
  },
  {
    page: "manual",
    title: "Other engines & files",
    detail:
      "Choose an engine or file format, inspect the input, then estimate or translate with your configured provider.",
    engines: "19 engines and file handlers",
    icon: Files,
    action: "Open manual engines",
  },
];

export function WelcomeWorkspace({
  onNavigate,
  children,
  legacy,
  onRecent,
  report,
}: {
  onNavigate: (page: string) => void;
  children: ReactNode;
  legacy?: Snapshot["legacy"];
  onRecent: (page: string, source: string) => void;
  report: (error: unknown) => void;
}) {
  return (
    <section className="welcome-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR TRANSLATION WORKSPACE</span>
          <h1>Choose how you want to translate.</h1>
          <p>
            Start a full game workflow, work with an AI assistant, or translate
            individual files. Each workspace keeps its own saved work.
          </p>
        </div>
      </div>
      {legacy && (
        <details
          className="settings-card upgrade-notice"
          open={legacy.warnings.length > 0}
        >
          <summary>Your previous installation is available</summary>
          <p>
            {legacy.settings_imported
              ? "Your preferences were imported. "
              : "Your existing desktop preferences were kept. "}
            {legacy.credentials_imported} saved credentials and{" "}
            {legacy.evaluations_imported} evaluations were recovered. Original
            inputs, outputs and logs remain in the previous folder.
          </p>
          {legacy.warnings.map((warning, index) => (
            <p className="banner" key={index}>
              {warning}
            </p>
          ))}
          <div className="actions">
            {legacy.batch_history_linked && (
              <button onClick={() => onNavigate("batches")}>
                Open recovered batches
              </button>
            )}
            {legacy.evaluations_imported > 0 && (
              <button onClick={() => onNavigate("evaluation")}>
                Open evaluations
              </button>
            )}
            <button onClick={() => api.openExport(legacy.report).catch(report)}>
              View upgrade report
            </button>
          </div>
          {legacy.recent.map((item) => (
            <div className="legacy-game" key={item.source}>
              <div>
                <strong>{item.name}</strong>
                <p className="muted">{item.source}</p>
              </div>
              <button onClick={() => onRecent(item.page, item.source)}>
                {item.page === "manual" ? "Copy input folder" : "Open game"}
              </button>
            </div>
          ))}
        </details>
      )}
      <div className="start-routes">
        {routes.map(
          ({ page, title, detail, engines, icon: Icon, action }, index) => (
            <section
              className={`start-route ${index === 0 ? "recommended" : ""}`}
              key={page}
            >
              <div className="start-route-heading">
                <Icon size={22} aria-hidden="true" />
                {index === 0 && (
                  <span className="status-pill">
                    Start here for a full game
                  </span>
                )}
              </div>
              <h2>{title}</h2>
              <p>{detail}</p>
              <small>{engines}</small>
              <button
                className={index === 0 ? "primary" : "secondary"}
                onClick={() => onNavigate(page)}
              >
                {action}
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            </section>
          ),
        )}
      </div>
      <div className="welcome-setup">
        <div>
          <strong>New to DazedTL?</strong>
          <p>
            Configure a provider for API translation, or read the guide to
            choose your workflow.
          </p>
        </div>
        <button onClick={() => onNavigate("settings")}>
          <Settings2 size={16} />
          Open settings
        </button>
        <button onClick={() => onNavigate("guide")}>
          <BookOpen size={16} />
          Read the guide
        </button>
      </div>
      <div className="section-heading spaced">
        <h2>Isolated review workspace</h2>
        <span className="muted">RPG Maker MV / MZ</span>
      </div>
      <p className="workspace-intro">
        Try a translation sample or review an imported snapshot without writing
        into your game. Translate, Review & test, and Release share this
        snapshot.
      </p>
      {children}
    </section>
  );
}
