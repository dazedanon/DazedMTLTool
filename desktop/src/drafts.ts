import { useCallback, useEffect, useSyncExternalStore } from "react";
import { api } from "./bridge";
import type { EditorDrafts } from "./types";

type DraftState = EditorDrafts & {
  ready: boolean;
  pending: boolean;
  error: string;
};
type Store = {
  value: DraftState;
  listeners: Set<() => void>;
  loaded?: Promise<void>;
  timer?: ReturnType<typeof setTimeout>;
  saving: Promise<void>;
};
const empty: DraftState = {
  version: 1,
  revision: 0,
  context: {},
  review: {},
  ready: false,
  pending: false,
  error: "",
};
const stores = new Map<string, Store>();
function store(projectId: string) {
  let current = stores.get(projectId);
  if (!current) {
    current = {
      value: { ...empty },
      listeners: new Set(),
      saving: Promise.resolve(),
    };
    stores.set(projectId, current);
  }
  return current;
}
function publish(current: Store, value: DraftState) {
  current.value = value;
  for (const listener of current.listeners) listener();
}
function releaseSavedStore(projectId: string, current: Store) {
  if (
    current.value.ready &&
    !current.value.pending &&
    !current.listeners.size &&
    stores.get(projectId) === current
  ) {
    stores.delete(projectId);
  }
}
function load(projectId: string) {
  const current = store(projectId);
  if (!projectId || current.loaded) return;
  current.loaded = api
    .getDrafts(projectId)
    .then((value) => {
      publish(current, { ...value, ready: true, pending: false, error: "" });
      releaseSavedStore(projectId, current);
    })
    .catch((error) => {
      publish(current, { ...current.value, error: String(error) });
    });
}
export function useEditorDrafts(projectId: string) {
  const current = store(projectId);
  useEffect(() => load(projectId), [projectId]);
  return useSyncExternalStore(
    useCallback(
      (listener: () => void) => {
        current.listeners.add(listener);
        return () => {
          current.listeners.delete(listener);
          releaseSavedStore(projectId, current);
        };
      },
      [current, projectId],
    ),
    () => current.value,
  );
}
export function hasUnsavedContext(projectId: string) {
  const value = store(projectId).value;
  return !value.ready || Object.keys(value.context).length > 0;
}
export function setEditorDraft(
  projectId: string,
  scope: "context" | "review",
  key: string,
  text?: string,
) {
  const current = store(projectId);
  if (!current.value.ready)
    throw new Error("Wait for saved editor drafts to load first.");
  const values = { ...current.value[scope] };
  if (text === undefined) delete values[key];
  else values[key] = text;
  publish(current, {
    ...current.value,
    [scope]: values,
    pending: true,
    error: "",
  });
  clearTimeout(current.timer);
  current.timer = setTimeout(() => {
    flushEditorDrafts(projectId).catch(() => {});
  }, 300);
}
export function flushEditorDrafts(projectId: string): Promise<void> {
  const current = store(projectId);
  clearTimeout(current.timer);
  current.saving = current.saving
    .catch(() => {})
    .then(async () => {
      while (current.value.pending) {
        const snapshot = current.value;
        try {
          const response = await api.saveDrafts({
            project_id: projectId,
            revision: snapshot.revision,
            context: snapshot.context,
            review: snapshot.review,
          });
          const unchanged =
            snapshot.context === current.value.context &&
            snapshot.review === current.value.review;
          publish(current, {
            ...current.value,
            revision: response.revision,
            pending: !unchanged,
            error: "",
          });
        } catch (error) {
          publish(current, { ...current.value, error: String(error) });
          throw error;
        }
      }
      releaseSavedStore(projectId, current);
    });
  return current.saving;
}
export async function flushAllEditorDrafts() {
  await Promise.all([...stores.keys()].filter(Boolean).map(flushEditorDrafts));
}
