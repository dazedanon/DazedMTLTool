import { useEffect, useRef, useState } from "react";
import { Check, KeyRound, RefreshCw, Save, Upload } from "lucide-react";
import { api } from "./bridge";
import type {
  ApplicationSettings,
  ModelCatalogState,
  SettingField,
  SettingsDraft,
  SettingValue,
} from "./types";
import { saveBeforeClose } from "./lifecycle";

export function InputField({
  field,
  value,
  onChange,
  prefix = "setting",
}: {
  field: SettingField;
  value: SettingValue;
  onChange: (value: SettingValue) => void;
  prefix?: string;
}) {
  const id = `${prefix}-${field.key}`;
  if (field.type === "boolean")
    return (
      <label className="setting-toggle">
        <input
          id={id}
          type="checkbox"
          checked={!!value}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>
          {field.label}
          {field.help && <small>{field.help}</small>}
        </span>
      </label>
    );
  if (field.type === "choices")
    return (
      <fieldset className="setting-choices">
        <legend>{field.label}</legend>
        {field.choices?.map((choice) => (
          <label key={choice}>
            <input
              type="checkbox"
              checked={Array.isArray(value) && value.includes(choice)}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...(Array.isArray(value) ? value : []), choice]
                    : (Array.isArray(value) ? value : []).filter(
                        (item) => item !== choice,
                      ),
                )
              }
            />
            {choice}
          </label>
        ))}
      </fieldset>
    );
  const offset = field.display_offset || 0;
  const display = typeof value === "number" ? value + offset : String(value);
  return (
    <label className="setting-field" htmlFor={id}>
      <span>{field.label}</span>
      {field.type === "select" ? (
        <select
          id={id}
          value={String(value)}
          onChange={(event) => onChange(event.target.value)}
        >
          {field.choices?.map((choice) => (
            <option key={choice} value={choice}>
              {choice === "\t" ? "Tab" : choice}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          list={
            field.key === "model"
              ? "available-models"
              : field.key === "api"
                ? "api-endpoints"
                : undefined
          }
          type={
            field.type === "integer" || field.type === "number"
              ? "number"
              : "text"
          }
          min={field.min === undefined ? undefined : field.min + offset}
          max={field.max === undefined ? undefined : field.max + offset}
          step={field.type === "integer" ? 1 : "any"}
          value={display}
          onChange={(event) =>
            onChange(
              field.type === "integer" || field.type === "number"
                ? event.target.value === ""
                  ? ""
                  : Number(event.target.value) - offset
                : event.target.value,
            )
          }
        />
      )}{" "}
      {field.help && <small>{field.help}</small>}
    </label>
  );
}

export function SettingsWorkspace({
  report,
  onApplied,
}: {
  report: (error: unknown) => void;
  onApplied: (value: ApplicationSettings) => void;
}) {
  const [settings, setSettings] = useState<ApplicationSettings | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [section, setSection] = useState("general");
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [catalog, setCatalog] = useState<ModelCatalogState>({
    status: "idle",
    models: [],
    error: "",
  });
  const [keyForm, setKeyForm] = useState({
    name: "",
    secret: "",
    endpoint: "",
    keyless: false,
  });
  const [editingKey, setEditingKey] = useState(false);
  const [deleting, setDeleting] = useState("");
  const latest = useRef<SettingsDraft | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const saving = useRef<Promise<unknown>>(Promise.resolve());
  const secret = useRef("");
  secret.current = keyForm.secret;
  function accept(value: ApplicationSettings, recover = false) {
    setSettings(value);
    const saved = {
      revision: value.revision,
      values: value.values,
      engines: value.engines,
    };
    const recovered = recover && value.draft ? value.draft : saved;
    setDraft(recovered);
    latest.current = recovered;
    dirtyRef.current = !!(recover && value.draft);
    setDirty(dirtyRef.current);
    onApplied(value);
  }
  useEffect(() => {
    api
      .settingsGet()
      .then((value) => accept(value, true))
      .catch(report);
  }, []);
  async function flush() {
    clearTimeout(timer.current);
    await saving.current;
    const value = latest.current;
    if (value && dirtyRef.current) await api.settingsDraft(value);
  }
  useEffect(
    () =>
      saveBeforeClose(async () => {
        await flush();
        if (secret.current)
          throw new Error(
            "A credential has been entered but not saved. Save it in Settings before closing.",
          );
      }),
    [],
  );
  function edit(next: SettingsDraft) {
    setDraft(next);
    latest.current = next;
    dirtyRef.current = true;
    setDirty(true);
    setStatus("");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      saving.current = saving.current
        .catch(() => {})
        .then(() => api.settingsDraft(latest.current!));
      saving.current.catch(report);
    }, 400);
  }
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setStatus("");
    try {
      await fn();
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!draft) return;
    await action(async () => {
      await flush();
      accept(await api.settingsSave(draft));
      setStatus("Settings saved. New runs will use these values.");
    });
  }
  useEffect(() => {
    if (catalog.status !== "loading") return;
    const interval = setInterval(
      () => api.settingsModels().then(setCatalog).catch(report),
      500,
    );
    return () => clearInterval(interval);
  }, [catalog.status]);
  if (!settings || !draft) return <p className="muted">Loading settings…</p>;
  const schema =
    section === "general"
      ? settings.fields
      : settings.engine_schemas[section]?.fields || [];
  const values =
    section === "general" ? draft.values : draft.engines[section] || {};
  const groups = [
    ...new Set(
      schema.map(
        (item) =>
          item.group || settings.engine_schemas[section]?.label || "Options",
      ),
    ),
  ];
  return (
    <section className="application-settings">
      <fieldset className="settings-controls" disabled={busy}>
        <div className="page-heading">
          <div>
            <p className="eyebrow">APPLICATION SETTINGS</p>
            <h1>Set up your translation tools.</h1>
            <p>Save providers, formatting, and engine options for new runs.</p>
          </div>
        </div>
        <div className="settings-actions">
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              action(async () => {
                const source = await api.chooseFolder();
                if (!source) return;
                await flush();
                accept(
                  await api.settingsImport({
                    source,
                    revision: settings.revision,
                  }),
                );
                setStatus(
                  "Existing settings and credentials imported. The original installation is unchanged.",
                );
              })
            }
          >
            <Upload size={16} />
            Import existing installation
          </button>
          <button
            className="secondary"
            onClick={() =>
              action(async () => {
                const source = await api.chooseConfigurationFile("settings");
                if (!source) return;
                const imported = await api.settingsTransfer("import", source);
                edit({
                  ...imported,
                  engines: { ...settings.engines, ...imported.engines },
                });
                setStatus(
                  "Settings file imported as a draft. Credentials are excluded; review and save to apply.",
                );
              })
            }
          >
            Import settings file
          </button>
          <button
            className="secondary"
            disabled={dirty}
            onClick={() =>
              action(async () => {
                const result = await api.settingsTransfer("export");
                await api.openExport(result.path);
                setStatus("Saved settings exported without credentials.");
              })
            }
          >
            Export saved settings
          </button>
          <button className="primary" disabled={busy || !dirty} onClick={save}>
            <Save size={16} />
            Save settings
          </button>
          <span className="muted" role="status">
            {busy
              ? "Saving…"
              : status ||
                (dirty
                  ? "Draft saved automatically · changes are not active yet"
                  : "Up to date")}
          </span>
        </div>
        {draft.revision !== settings.revision && (
          <div className="banner error">
            This recovered draft is based on older settings.{" "}
            <button
              onClick={() =>
                action(async () => {
                  const current = await api.settingsGet();
                  accept(current);
                  await api.settingsDraft({
                    revision: current.revision,
                    values: current.values,
                    engines: current.engines,
                  });
                })
              }
            >
              Reload saved settings
            </button>
          </div>
        )}
        <div className="tabs" role="group" aria-label="Settings sections">
          <button
            aria-pressed={section === "general"}
            onClick={() => setSection("general")}
          >
            General
          </button>
          {Object.entries(settings.engine_schemas).map(([key, value]) => (
            <button
              key={key}
              aria-pressed={section === key}
              onClick={() => setSection(key)}
            >
              {value.label}
            </button>
          ))}
        </div>
        {settings.presets[section] && (
          <section className="settings-card">
            <h2>CSV presets</h2>
            <div className="actions">
              {Object.entries(settings.presets[section]).map(
                ([name, preset]) => (
                  <button
                    key={name}
                    onClick={() => {
                      edit({
                        ...draft,
                        engines: {
                          ...draft.engines,
                          [section]: { ...values, ...preset },
                        },
                      });
                      setStatus(
                        `${name} loaded into this draft. Save settings to apply.`,
                      );
                    }}
                  >
                    {name}
                  </button>
                ),
              )}
            </div>
          </section>
        )}
        {section === "general" && (
          <section className="settings-card">
            <h2>
              <KeyRound size={18} />
              API credentials
            </h2>
            <p className="muted">
              Keys are stored in this desktop profile. Leave the secret blank
              when editing to retain the saved key.
            </p>
            <div className="credential-list">
              {settings.keys.map((key) => (
                <div className="credential-row" key={key.name}>
                  <button
                    className={
                      settings.active_key === key.name
                        ? "selected-key"
                        : "secondary"
                    }
                    disabled={busy}
                    onClick={() =>
                      action(async () => {
                        const value = await api.settingsKey({
                          action: "select",
                          name: key.name,
                        });
                        setSettings(value);
                        setStatus(`Selected ${key.name}.`);
                      })
                    }
                  >
                    {settings.active_key === key.name && <Check size={15} />}{" "}
                    {key.name}
                    <small>
                      {key.keyless ? "No API key required" : "Secret saved"}
                    </small>
                  </button>
                  <span className="muted">
                    {key.endpoint || "Uses the configured endpoint"}
                  </span>
                  <button
                    disabled={busy}
                    onClick={() => {
                      setEditingKey(true);
                      setKeyForm({
                        name: key.name,
                        secret: "",
                        endpoint: key.endpoint,
                        keyless: key.keyless,
                      });
                    }}
                  >
                    Edit
                  </button>
                  <button disabled={busy} onClick={() => setDeleting(key.name)}>
                    Remove
                  </button>
                </div>
              ))}
            </div>
            {deleting && (
              <div className="credential-delete">
                Remove “{deleting}” from this profile?
                <button
                  onClick={() =>
                    action(async () => {
                      setSettings(
                        await api.settingsKey({
                          action: "delete",
                          name: deleting,
                        }),
                      );
                      setDeleting("");
                    })
                  }
                >
                  Remove credential
                </button>
                <button onClick={() => setDeleting("")}>Keep credential</button>
              </div>
            )}
            {editingKey ? (
              <form
                className="credential-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  action(async () => {
                    setSettings(
                      await api.settingsKey({ action: "save", ...keyForm }),
                    );
                    setKeyForm({
                      name: "",
                      secret: "",
                      endpoint: "",
                      keyless: false,
                    });
                    setEditingKey(false);
                    setStatus("Credential saved.");
                  });
                }}
              >
                <label>
                  Credential name
                  <input
                    aria-label="Credential name"
                    value={keyForm.name}
                    required
                    onChange={(event) =>
                      setKeyForm({ ...keyForm, name: event.target.value })
                    }
                  />
                </label>
                <label>
                  API secret
                  <input
                    aria-label="API secret"
                    type="password"
                    autoComplete="new-password"
                    disabled={keyForm.keyless}
                    value={keyForm.secret}
                    onChange={(event) =>
                      setKeyForm({ ...keyForm, secret: event.target.value })
                    }
                  />
                </label>
                <label>
                  Endpoint for this credential
                  <input
                    aria-label="Credential endpoint"
                    list="api-endpoints"
                    value={keyForm.endpoint}
                    onChange={(event) =>
                      setKeyForm({ ...keyForm, endpoint: event.target.value })
                    }
                  />
                </label>
                <label className="setting-toggle">
                  <input
                    type="checkbox"
                    checked={keyForm.keyless}
                    onChange={(event) =>
                      setKeyForm({
                        ...keyForm,
                        keyless: event.target.checked,
                        secret: event.target.checked ? "" : keyForm.secret,
                      })
                    }
                  />
                  Local endpoint without an API key
                </label>
                <div className="actions">
                  <button type="submit" className="primary" disabled={busy}>
                    Save credential
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setKeyForm({
                        name: "",
                        secret: "",
                        endpoint: "",
                        keyless: false,
                      });
                      setEditingKey(false);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <button
                className="secondary"
                onClick={() => {
                  setKeyForm({
                    name: "",
                    secret: "",
                    endpoint: "",
                    keyless: false,
                  });
                  setEditingKey(true);
                }}
              >
                Add credential
              </button>
            )}
          </section>
        )}
        <datalist id="api-endpoints">
          {settings.endpoints.map(([name, url]) => (
            <option key={name} value={url}>
              {name}
            </option>
          ))}
        </datalist>
        <datalist id="available-models">
          {(catalog.models.length ? catalog.models : settings.models).map(
            (model) => (
              <option key={model} value={model} />
            ),
          )}
        </datalist>
        {groups.map((group) => (
          <section className="settings-card" key={group}>
            <h2>{group}</h2>
            <div className="settings-grid">
              {schema
                .filter(
                  (item) =>
                    (item.group ||
                      settings.engine_schemas[section]?.label ||
                      "Options") === group,
                )
                .map((item) => (
                  <InputField
                    key={item.key}
                    field={item}
                    value={values[item.key] ?? item.default}
                    onChange={(value) =>
                      edit(
                        section === "general"
                          ? {
                              ...draft,
                              values: { ...draft.values, [item.key]: value },
                            }
                          : {
                              ...draft,
                              engines: {
                                ...draft.engines,
                                [section]: { ...values, [item.key]: value },
                              },
                            },
                      )
                    }
                  />
                ))}
            </div>
            {group === "Provider" && (
              <div className="actions">
                <button
                  className="secondary"
                  disabled={
                    busy ||
                    dirty ||
                    catalog.status === "loading" ||
                    !settings.active_key
                  }
                  onClick={() =>
                    action(async () =>
                      setCatalog(await api.settingsModels(true)),
                    )
                  }
                >
                  <RefreshCw size={15} />
                  Refresh available models
                </button>
                <span className="muted" role="status">
                  {catalog.status === "loading"
                    ? "Fetching model list…"
                    : catalog.error ||
                      (catalog.models.length
                        ? `${catalog.models.length} models available`
                        : "Save provider settings before refreshing.")}
                </span>
              </div>
            )}
          </section>
        ))}
        <div className="actions">
          <button
            className="secondary"
            disabled={busy}
            onClick={() => {
              const defaults = Object.fromEntries(
                schema.map((item) => [item.key, item.default]),
              );
              edit(
                section === "general"
                  ? { ...draft, values: defaults }
                  : {
                      ...draft,
                      engines: { ...draft.engines, [section]: defaults },
                    },
              );
            }}
          >
            Reset this section
          </button>
          <button
            className="secondary"
            onClick={() => {
              edit({
                ...draft,
                values: Object.fromEntries(
                  settings.fields.map((item) => [item.key, item.default]),
                ),
                engines: Object.fromEntries(
                  Object.entries(settings.engine_schemas).map(
                    ([key, schema]) => [
                      key,
                      Object.fromEntries(
                        schema.fields.map((item) => [item.key, item.default]),
                      ),
                    ],
                  ),
                ),
              });
              setStatus(
                "Default preferences and engine options loaded into the draft. Save to apply.",
              );
            }}
          >
            Reset all preferences
          </button>
          <button className="primary" disabled={busy || !dirty} onClick={save}>
            Save settings
          </button>
        </div>
      </fieldset>
    </section>
  );
}
