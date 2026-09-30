import { useEffect, useState } from "react";
import { api } from "./bridge";
import type { ApplicationUpdateState } from "./types";

export default function UpdateWorkspace() {
  const [state, setState] = useState<ApplicationUpdateState | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function refresh() {
    setState(await api.updates("state"));
  }
  useEffect(() => {
    refresh().catch((error) => setError(String(error)));
  }, []);
  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await action();
      await refresh();
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy("");
    }
  }
  const selection = state?.application;
  if (state?.source) {
    const source = state.source;
    return (
      <section className="update-workspace">
        <div className="page-heading">
          <div>
            <span className="eyebrow">APPLICATION</span>
            <h1>Updates & rollback</h1>
            <p>
              Update DazedTL while keeping your settings, credentials and saved
              work.
            </p>
          </div>
        </div>
        {error && (
          <div className="banner error" role="alert">
            {error}
          </div>
        )}
        {(notice || source.message) && (
          <div className="banner" role="status">
            {notice || source.message}
          </div>
        )}
        {busy && <p role="status">{busy}…</p>}
        <div className="panel">
          <h2>Installed application</h2>
          <strong>Build {source.current.slice(0, 12) || "local"}</strong>
          <details>
            <summary>Installation details</summary>
            <p className="path-text muted">{source.root}</p>
          </details>
          <div className="button-row">
            <button
              disabled={!!busy}
              onClick={() =>
                run("Checking for updates", () => api.updates("check"))
              }
            >
              Check for updates
            </button>
            <button
              disabled={!!busy}
              onClick={() => run("Refreshing update state", refresh)}
            >
              Refresh
            </button>
          </div>
        </div>
        {source.available && (
          <div className="panel">
            <h2>Available update · {source.available.sha.slice(0, 12)}</h2>
            <p>
              Downloaded from {source.available.mirror}. Runtime changes are
              prepared before you restart.
            </p>
            <button
              disabled={!!busy}
              onClick={() =>
                run("Downloading and preparing the update", () =>
                  api.updates("download"),
                )
              }
            >
              Download update
            </button>
          </div>
        )}
        {source.staged && (
          <div className="panel">
            <h2>Ready to install · {source.staged.sha.slice(0, 12)}</h2>
            <p>
              Open drafts are saved before restarting. The previous application
              remains available for rollback.
            </p>
            <button
              className="primary"
              disabled={!!busy}
              onClick={() =>
                run("Saving drafts and restarting", () =>
                  api.updates("activate", {
                    id: source.staged!.sha,
                    revision: source.revision,
                  }),
                )
              }
            >
              Install and restart
            </button>
          </div>
        )}
        <div className="panel">
          <h2>Previous application</h2>
          {source.previous ? (
            <>
              <p>
                Build{" "}
                {source.previous.sha.slice(0, 12) || "previous local build"}.
                Your saved work stays in the current profile.
              </p>
              <button
                disabled={!!busy}
                onClick={() =>
                  run("Saving drafts and rolling back", () =>
                    api.updates("rollback", {
                      id: source.previous!.sha,
                      revision: source.revision,
                    }),
                  )
                }
              >
                Roll back and restart
              </button>
            </>
          ) : (
            <p className="muted">
              A previous build becomes available after the first update.
            </p>
          )}
        </div>
      </section>
    );
  }
  return (
    <section className="update-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">APPLICATION</span>
          <h1>Updates & rollback</h1>
          <p>
            Install a complete desktop release. Settings, credentials, shared
            instructions and saved work stay in your desktop profile.
          </p>
        </div>
      </div>
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}
      {state?.error && <div className="banner error">{state.error}</div>}
      {(notice || selection?.message) && (
        <div className="banner" role="status">
          {notice || selection?.message}
        </div>
      )}
      {busy && <p role="status">{busy}…</p>}
      <div className="panel">
        <h2>Installed application</h2>
        {selection ? (
          <>
            <strong>
              Version {selection.current.version} ·{" "}
              {selection.current.id.slice(0, 12)}
            </strong>
            <p className="muted path-text">{selection.current.root}</p>
            {!selection.current.signed && (
              <p className="muted">
                This is an unsigned build. Package checks verify file integrity.
              </p>
            )}
          </>
        ) : (
          <p>
            {state?.packaged
              ? "Application update metadata is unavailable."
              : "Source checkout. Build and launch a desktop package to install updates or roll back."}
          </p>
        )}
        <div className="button-row">
          <button
            disabled={!!busy}
            onClick={() =>
              run("Checking desktop releases", async () => {
                const release = await api.updates("check");
                setNotice(
                  release
                    ? `Desktop release ${release.tag} is available.`
                    : "No compatible desktop release has been published.",
                );
              })
            }
          >
            Check for updates
          </button>
          <button
            disabled={!!busy || !selection}
            onClick={() =>
              run("Verifying and staging the selected package", () =>
                api.updates("import"),
              )
            }
          >
            Import extracted package
          </button>
          <button
            disabled={!!busy}
            onClick={() => run("Refreshing update state", refresh)}
          >
            Refresh
          </button>
        </div>
      </div>
      {state?.release && (
        <div className="panel">
          <h2>Available release · {state.release.tag}</h2>
          <p>
            {state.release.name} ·{" "}
            {(state.release.bytes / 1024 ** 2).toFixed(0)} MB
          </p>
          <button
            disabled={!!busy || !selection}
            onClick={() =>
              run("Downloading and verifying the release", () =>
                api.updates("download"),
              )
            }
          >
            Download and stage
          </button>
        </div>
      )}
      {selection && (
        <>
          {selection.staged
            .filter((item) => item.id !== selection.active.id)
            .map((item) => (
              <div className="panel" key={item.id}>
                <h2>
                  Staged · {item.version} · {item.id.slice(0, 12)}
                </h2>
                <p>
                  The current build will remain available for rollback. Open
                  editor drafts are saved before restarting.
                </p>
                <button
                  className="primary"
                  disabled={!!busy || !!selection.pending}
                  onClick={() =>
                    run("Saving drafts and restarting", () =>
                      api.updates("activate", {
                        id: item.id,
                        revision: selection.revision,
                      }),
                    )
                  }
                >
                  Activate and restart
                </button>
              </div>
            ))}
          <div className="panel">
            <h2>Previous application</h2>
            {selection.previous ? (
              <>
                <p>
                  Version {selection.previous.version} ·{" "}
                  {selection.previous.id.slice(0, 12)}
                </p>
                <p>
                  Rollback changes the application build. Your saved work
                  remains in the current profile.
                </p>
                <button
                  disabled={!!busy || !!selection.pending}
                  onClick={() =>
                    run("Saving drafts and rolling back", () =>
                      api.updates("rollback", {
                        id: selection.previous!.id,
                        revision: selection.revision,
                      }),
                    )
                  }
                >
                  Roll back and restart
                </button>
              </>
            ) : (
              <p className="muted">
                A previous build becomes available after the first update.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
