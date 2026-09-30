import { flushAllEditorDrafts } from "./drafts";

const saveTasks = new Set<() => Promise<void>>();
export function saveBeforeClose(save: () => Promise<void>) {
  saveTasks.add(save);
  return () => {
    saveTasks.delete(save);
  };
}
export async function prepareToClose() {
  document.body.inert = true;
  try {
    await Promise.all([
      flushAllEditorDrafts(),
      ...[...saveTasks].map((save) => save()),
    ]);
  } finally {
    document.body.inert = false;
  }
}

export function cancelClose() {
  document.body.inert = false;
}
