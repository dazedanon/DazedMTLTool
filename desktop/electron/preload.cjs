const { contextBridge, ipcRenderer } = require("electron");
const call = (method, params) =>
  ipcRenderer.invoke("workspace:call", method, params);
contextBridge.exposeInMainWorld("workspace", {
  copyText: (text) => ipcRenderer.invoke("workspace:copy-text", text),
  setScale: (value) => ipcRenderer.invoke("workspace:scale", value),
  ready: () => ipcRenderer.invoke("workspace:ready"),
  runtime: () => ipcRenderer.invoke("workspace:runtime"),
  updates: (action, options = {}) => ipcRenderer.invoke("workspace:updates", action, options),
  onBeforeClose: (handler, cancelled) => {
    const listener = async (_event, token) => {
      let error = "";
      try {
        await handler();
      } catch (value) {
        error = String(value).slice(0, 1000);
      }
      ipcRenderer.send("workspace:close-ready", { token, error });
    };
    ipcRenderer.on("workspace:before-close", listener);
    const cancelListener = () => cancelled();
    ipcRenderer.on("workspace:close-cancelled", cancelListener);
    return () => {
      ipcRenderer.removeListener("workspace:before-close", listener);
      ipcRenderer.removeListener("workspace:close-cancelled", cancelListener);
    };
  },
  onServiceStopped: (handler) => {
    const listener = (_event, message) => handler(message);
    ipcRenderer.on("workspace:service-stopped", listener);
    return () =>
      ipcRenderer.removeListener("workspace:service-stopped", listener);
  },
  getDrafts: (project_id) => call("get_drafts", { project_id }),
  saveDrafts: (params) => call("save_drafts", params),
  state: (params) => call("state", params),
  importProject: (params) => call("import_project", params),
  saveGuidance: (params) => call("save_guidance", params),
  preview: (params) => call("preview", params),
  start: (params) => call("start", params),
  stop: (job_id) => call("stop", { job_id }),
  resume: (job_id) => call("resume", { job_id }),
  review: (params) => call("review", params),
  export: (job_id) => call("export", { job_id }),
  context: (project_id) => call("context", { project_id }),
  saveContext: (params) => call("save_context", params),
  nativePreview: (params) => call("native_preview", params),
  startNative: (params) => call("start_native", params),
  reviewPage: (params) => call("review_page", params),
  applyReviewed: (job_id) => call("apply_reviewed", { job_id }),
  engineLog: (job_id) => call("engine_log", { job_id }),
  assetState: (params = {}) => call("asset_state", params),
  assetOpen: (params) => call("asset_open", params),
  assetThumbnails: (params) => call("asset_thumbnails", params),
  assetAction: (params) => call("asset_action", params),
  imageList: (project_id) => call("image_list", { project_id }),
  imageImport: (params) => call("image_import", params),
  imageGet: (params) => call("image_get", params),
  imageSave: (params) => call("image_save", params),
  imageRender: (params) => call("image_render", params),
  imageReview: (params) => call("image_review", params),
  imageApprove: (params) => call("image_approve", params),
  imageExport: (params) => call("image_export", params),
  manualState: () => call("manual_state"),
  batchState: () => call("batch_state"),
  evaluationState: (params = {}) => call("evaluation_state", params),
  evaluationAction: (params) => call("evaluation_action", params),
  evaluationDraft: (values) => call("evaluation_draft", { values }),
  evaluationReasoning: (candidate) =>
    call("evaluation_reasoning", { candidate }),
  chooseEvaluationFile: (kind) =>
    ipcRenderer.invoke("workspace:evaluation-file", kind),
  batchRegister: (source) => call("batch_register", { source }),
  batchAction: (params) => call("batch_action", params),
  batchResume: (operation_id) => call("batch_resume", { operation_id }),
  manualInspect: (params) => call("manual_inspect", params),
  manualStart: (params) => call("manual_start", params),
  manualResume: (job_id) => call("manual_resume", { job_id }),
  manualAnswer: (params) => call("manual_answer", params),
  manualStop: (job_id) => call("manual_stop", { job_id }),
  manualLog: (job_id) => call("manual_log", { job_id }),
  manualExport: (job_id) => call("manual_export", { job_id }),
  versionState: (project_id = "") => call("version_state", { project_id }),
  versionOpen: (source, preserve = false) =>
    call("version_open", { source, preserve }),
  versionSave: (params) => call("version_save", params),
  versionAction: (params) => call("version_action", params),
  lenState: (project_id = "") => call("len_state", { project_id }),
  lenOpen: (source) => call("len_open", { source }),
  lenSave: (params) => call("len_save", params),
  lenAction: (params) => call("len_action", params),
  lenDocuments: (project_id) => call("len_documents", { project_id }),
  lenDocumentSave: (params) => call("len_document_save", params),
  instructionCatalog: () => call("instruction_catalog"),
  instructionGet: (name) => call("instruction_get", { name }),
  instructionSave: (params) => call("instruction_save", params),
  instructionDraft: (params) => call("instruction_draft", params),
  instructionImport: (name, source) =>
    call("instruction_import", { name, source }),
  guideCatalog: () => call("guide_catalog"),
  guidePage: (identity) => call("guide_page", { identity }),
  guideLink: (url) => ipcRenderer.invoke("workspace:guide-link", url),
  chooseConfigurationFile: (kind) =>
    ipcRenderer.invoke("workspace:configuration-file", kind),
  settingsTransfer: (action, source = "") =>
    call("settings_transfer", { action, source }),
  settingsGet: () => call("settings_get"),
  workflowState: (project_id = "") => call("workflow_state", { project_id }),
  workflowOpen: (source) => call("workflow_open", { source }),
  workflowUpdate: (params) => call("workflow_update", params),
  workflowPreview: (params) => call("workflow_preview", params),
  workflowExecute: (token) => call("workflow_execute", { token }),
  workflowStop: (job_id) => call("workflow_stop", { job_id }),
  workflowDocuments: (project_id) => call("workflow_documents", { project_id }),
  workflowDocumentSave: (params) => call("workflow_document_save", params),
  workflowSkill: (project_id, name) =>
    call("workflow_skill", { project_id, name }),
  workflowPhase: (params) => call("workflow_phase", params),
  workflowDraft: (project_id, draft) =>
    call("workflow_draft", { project_id, draft }),
  settingsSave: (params) => call("settings_save", params),
  settingsDraft: (params) => call("settings_draft", params),
  settingsKey: (params) => call("settings_key", params),
  settingsImport: (params) => call("settings_import", params),
  settingsModels: (refresh = false) => call("settings_models", { refresh }),
  chooseFolder: () => ipcRenderer.invoke("workspace:choose"),
  chooseImage: () => ipcRenderer.invoke("workspace:image"),
  openExport: (target) => ipcRenderer.invoke("workspace:open-export", target),
});
