export interface TextRecord {
  id: string;
  file: string;
  pointer: string;
  source: string;
  category: string;
}
export interface Result {
  text: string;
  flags: string[];
  reviewed: boolean;
}
export interface Job {
  kind?: "sample" | "rpgmaker" | "image";
  image?: {
    id: string;
    name: string;
    revision: number;
    failures?: number;
    stale?: boolean;
  };
  applied_to_workspace?: number;
  native?: {
    phase: string;
    files: string[];
    completed_files: string[];
    requests: number;
    request_limit: number;
    stats: {
      total: number;
      reviewed: number;
      flagged: number;
      unresolved: number;
    };
    progress?: { file: string; current: number; total: number };
  };
  id: string;
  project_id: string;
  created: string;
  updated: string;
  status: string;
  mode: string;
  records: TextRecord[];
  results: Record<string, Result>;
  message: string;
  exports: string[];
}
export interface Project {
  id: string;
  name: string;
  source: string;
  revision: string;
  engine: string;
  files: { name: string; entries: number; phase?: string | null }[];
  settings?: EngineSettings;
  working_files?: Record<string, { sha256: string; job_id: string }>;
  working_revision?: number;
  records: TextRecord[];
  total_records: number;
  matching_records: number;
  guidance: string;
  has_guidance?: boolean;
}
export interface Snapshot {
  legacy?: {
    source: string;
    report: string;
    recent: { source: string; page: string; name: string }[];
    settings_imported: boolean;
    credentials_imported: number;
    evaluations_imported: number;
    batch_history_linked: boolean;
    warnings: string[];
    preserved_folders: string[];
  };
  preferences?: { font_scale: number; translationCompletionAlert: boolean };
  projects: { id: string; name: string; source: string }[];
  project: Project | null;
  jobs: Job[];
  budget: {
    cap_usd: number;
    reserved_usd: number;
    usage_estimate_usd: number;
    requests: number;
    unknown_requests: number;
  };
  allow_live: boolean;
  active_job: string | null;
  active_job_project?: string;
  active_job_kind?: string;
}
export interface Selection {
  project_id: string;
  record_ids: string[];
  mode: string;
}
export interface Preview {
  entries: number;
  files: number;
  mode: string;
  model: string;
  maximum_reserved_usd: number;
  destination: string;
}
export interface EngineSettings {
  width: number;
  faceWidth: number;
  listWidth: number;
  noteWidth: number;
  batchsize: number;
  FIRSTLINESPEAKERS: boolean;
  INLINE401SPEAKERS: boolean;
  FACENAME101: boolean;
  AUTONAMEPOPUP101: boolean;
  CODE408: boolean;
}
export interface NativeSelection {
  project_id: string;
  files: string[];
  phase: string;
  mode: string;
  settings: EngineSettings;
  request_limit: number;
}
export interface NativePreview {
  files: number;
  filenames: string[];
  dependencies: string[];
  working_files: string[];
  phase: string;
  mode: string;
  model: string;
  maximum_reserved_usd: number;
  request_limit: number;
  settings: EngineSettings;
  context_files: string[];
  destination: string;
}
export interface ReviewPage {
  job_id: string;
  records: TextRecord[];
  results: Record<string, Result>;
  total: number;
  reviewed: number;
  flagged: number;
  unresolved: number;
  matching: number;
  offset: number;
}
export interface EditorDrafts {
  version: 1;
  revision: number;
  context: Record<string, string>;
  review: Record<string, string>;
}
export type SettingValue = string | number | boolean | string[];
export interface SettingField {
  key: string;
  label: string;
  group?: string;
  type: string;
  default: SettingValue;
  min?: number;
  max?: number;
  choices?: string[];
  display_offset?: number;
  help?: string;
}
export interface SettingsDraft {
  revision: number;
  values: Record<string, SettingValue>;
  engines: Record<string, Record<string, SettingValue>>;
}
export interface ApplicationSettings extends SettingsDraft {
  presets: Record<string, Record<string, Record<string, SettingValue>>>;
  fields: SettingField[];
  engine_schemas: Record<string, { label: string; fields: SettingField[] }>;
  active_key: string;
  keys: {
    name: string;
    endpoint: string;
    keyless: boolean;
    has_secret: boolean;
  }[];
  endpoints: [string, string][];
  models: string[];
  draft: SettingsDraft | null;
}
export interface ModelCatalogState {
  status: string;
  models: string[];
  error: string;
}
export interface ManualInspection {
  source: string;
  engine: string;
  revision: string;
  files: { name: string; bytes: number; sha256: string }[];
}
export interface ManualJob {
  id: string;
  created: string;
  source: string;
  engine: string;
  mode: string;
  model: string;
  files: string[];
  status: string;
  phase: string;
  message: string;
  completed: string[];
  errors: Record<string, string>;
  mismatches: Record<string, string>;
  approval: null | {
    token: string;
    kind: "batch" | "speakers";
    detail: Record<string, unknown>;
  };
  estimate: Record<string, unknown> | null;
  progress: null | { current: number; total: number; file: string };
  item_progress?: { current: number; total: number; file: string };
  log: string[];
  exports: string[];
  outputs: Record<string, string>;
}
export interface ManualState {
  engines: { name: string; extensions: string[] }[];
  jobs: ManualJob[];
  active: string | null;
  allow_providers: boolean;
}
export interface WorkspaceAPI {
  instructionCatalog(): Promise<
    { name: string; title: string; customized: boolean }[]
  >;
  instructionGet(name: string): Promise<SharedInstruction>;
  instructionSave(params: InstructionDraft): Promise<SharedInstruction>;
  instructionDraft(params: InstructionDraft): Promise<{ saved: boolean }>;
  instructionImport(name: string, source: string): Promise<{ text: string }>;
  guideCatalog(): Promise<
    { type?: string; id?: string; title: string; file?: string }[]
  >;
  guidePage(identity: string): Promise<{
    id: string;
    title: string;
    html: string;
    external_links: string[];
  }>;
  guideLink(url: string): Promise<void>;
  chooseConfigurationFile(
    kind: "settings" | "instruction",
  ): Promise<string | null>;
  settingsTransfer(action: "import", source: string): Promise<SettingsDraft>;
  settingsTransfer(action: "export"): Promise<{ path: string }>;
  evaluationState(params?: {
    run_id?: string;
    query?: string;
    selection?: string;
    page?: number;
    review_mode?: string;
  }): Promise<EvaluationState>;
  evaluationAction(params: {
    action: string;
    run_id?: string;
    options?: Record<string, unknown>;
    preview_job?: string;
  }): Promise<OperationJob>;
  evaluationDraft(values: EvaluationDraft): Promise<{ saved: boolean }>;
  evaluationReasoning(
    candidate: EvaluationCandidate,
  ): Promise<{ levels: string[]; default: string }>;
  chooseEvaluationFile(
    kind: "archive" | "review" | "calibration",
  ): Promise<string | null>;
  batchState(): Promise<BatchState>;
  batchRegister(source: string): Promise<BatchState>;
  batchAction(params: {
    source_id: string;
    batch_id: string;
    action: string;
    key_name?: string;
    engine?: string;
    revision?: string;
    prepared_id?: string;
  }): Promise<OperationJob>;
  batchResume(operation_id: string): Promise<ManualJob>;
  versionState(project_id?: string): Promise<VersionState>;
  versionOpen(source: string, preserve?: boolean): Promise<VersionState>;
  versionSave(params: {
    project_id: string;
    revision: number;
    values: VersionValues;
  }): Promise<VersionRecord>;
  versionAction(params: {
    project_id: string;
    revision: number;
    action: string;
    preview_job?: string;
  }): Promise<OperationJob>;

  copyText(text: string): Promise<void>;
  lenState(project_id?: string): Promise<LenState>;
  lenOpen(source: string): Promise<LenState>;
  lenSave(params: {
    project_id: string;
    revision: number;
    values: LenValues;
    drafts: GuidanceDocuments;
  }): Promise<LenRecord>;
  lenAction(params: {
    project_id: string;
    revision: number;
    action: string;
    options?: Record<string, unknown>;
  }): Promise<OperationJob>;
  lenDocuments(project_id: string): Promise<GuidanceDocuments>;
  lenDocumentSave(params: {
    project_id: string;
    name: string;
    revision: string;
    text: string;
  }): Promise<GuidanceDocuments>;

  workflowState(project_id?: string): Promise<WorkflowState>;
  workflowOpen(source: string): Promise<WorkflowState>;
  workflowUpdate(params: {
    project_id: string;
    revision: number;
    values: Record<string, unknown>;
  }): Promise<WorkflowState>;
  workflowPreview(params: {
    project_id: string;
    action: string;
    options?: Record<string, unknown>;
  }): Promise<WorkflowPreview>;
  workflowExecute(token: string): Promise<OperationJob>;
  workflowStop(id: string): Promise<OperationJob>;
  workflowDocuments(id: string): Promise<GuidanceDocuments>;
  workflowDocumentSave(params: {
    project_id: string;
    name: string;
    text: string;
    revision: string;
  }): Promise<GuidanceDocuments>;
  workflowSkill(id: string, name: string): Promise<string>;
  workflowPhase(params: {
    project_id: string;
    phase: string;
    sync: boolean;
  }): Promise<ManualJob>;
  workflowDraft(id: string, draft: WorkflowDraft): Promise<{ saved: boolean }>;
  manualState(): Promise<ManualState>;
  manualInspect(params: {
    source: string;
    engine: string;
  }): Promise<ManualInspection>;
  manualStart(params: {
    source: string;
    engine: string;
    files: string[];
    revision: string;
    mode: string;
    context_source: string;
  }): Promise<ManualJob>;
  manualResume(id: string): Promise<ManualJob>;
  manualAnswer(params: {
    job_id: string;
    token: string;
    approved: boolean;
  }): Promise<ManualJob>;
  manualStop(id: string): Promise<ManualJob>;
  manualLog(id: string): Promise<string>;
  manualExport(id: string): Promise<{ path: string; files: number }>;
  setScale(value: number): Promise<void>;
  settingsGet(): Promise<ApplicationSettings>;
  settingsSave(params: SettingsDraft): Promise<ApplicationSettings>;
  settingsDraft(params: SettingsDraft): Promise<{ saved: boolean }>;
  settingsKey(params: {
    action: string;
    name: string;
    secret?: string;
    endpoint?: string;
    keyless?: boolean;
  }): Promise<ApplicationSettings>;
  settingsImport(params: {
    source: string;
    revision: number;
  }): Promise<ApplicationSettings>;
  settingsModels(refresh?: boolean): Promise<ModelCatalogState>;
  ready(): Promise<void>;
  updates(action: "state"): Promise<ApplicationUpdateState>;
  updates(action: "check"): Promise<DesktopRelease | null>;
  updates(
    action: "import" | "download",
  ): Promise<DesktopUpdateSelection | null>;
  updates(
    action: "activate" | "rollback",
    options: { id: string; revision: string },
  ): Promise<{ restarting: boolean }>;
  runtime(): Promise<{
    packaged: boolean;
    root: string;
    python: string;
    workspace: string;
  }>;
  onBeforeClose(
    handler: () => Promise<void>,
    cancelled: () => void,
  ): () => void;
  onServiceStopped(handler: (message: string) => void): () => void;
  getDrafts(project_id: string): Promise<EditorDrafts>;
  saveDrafts(params: {
    project_id: string;
    revision: number;
    context: Record<string, string>;
    review: Record<string, string>;
  }): Promise<{ revision: number }>;
  state(params?: {
    project_id?: string;
    query?: string;
    category?: string;
  }): Promise<Snapshot>;
  importProject(params: {
    source: string;
    original: boolean;
  }): Promise<Snapshot>;
  saveGuidance(params: { project_id: string; text: string }): Promise<Snapshot>;
  preview(params: Selection): Promise<Preview>;
  start(params: Selection): Promise<Job>;
  stop(id: string): Promise<Job>;
  resume(id: string): Promise<Job>;
  review(params: {
    job_id: string;
    record_id: string;
    text: string;
  }): Promise<Job>;
  export(id: string): Promise<{ path: string; files: number }>;
  context(
    project_id: string,
  ): Promise<{ documents: Record<string, string>; settings: EngineSettings }>;
  saveContext(params: {
    project_id: string;
    name: string;
    text: string;
  }): Promise<{ documents: Record<string, string>; settings: EngineSettings }>;
  nativePreview(params: NativeSelection): Promise<NativePreview>;
  startNative(params: NativeSelection): Promise<Job>;
  reviewPage(params: {
    job_id: string;
    offset?: number;
    query?: string;
    pending?: boolean;
  }): Promise<ReviewPage>;
  applyReviewed(id: string): Promise<Snapshot>;
  engineLog(id: string): Promise<string>;
  assetState(params?: {
    project_id?: string;
    query?: string;
    stage?: string;
    folder?: string;
    page?: number;
  }): Promise<AssetState>;
  assetOpen(params: {
    source: string;
    engine: string;
    image_root: string;
  }): Promise<AssetState>;
  assetThumbnails(params: {
    project_id: string;
    ids: string[];
  }): Promise<Record<string, { url?: string; error?: string }>>;
  assetAction(params: {
    project_id: string;
    action: string;
    ids?: string[];
    options?: Record<string, unknown>;
  }): Promise<OperationJob>;
  imageList(project_id: string): Promise<ImageSummary[]>;
  imageImport(params: {
    project_id: string;
    name: string;
    data_url: string;
    source_path?: string;
  }): Promise<ImageDocument>;
  imageGet(params: {
    project_id: string;
    image_id: string;
  }): Promise<ImageDocument>;
  imageSave(params: {
    project_id: string;
    image_id: string;
    revision: number;
    blocks: ImageBlock[];
    strokes: ImageStroke[];
  }): Promise<ImageDocument>;
  imageRender(params: { project_id: string; image_id: string }): Promise<Job>;
  imageReview(params: {
    project_id: string;
    image_id: string;
    revision: number;
    confirmed: boolean;
  }): Promise<ImageDocument>;
  imageApprove(params: {
    project_id: string;
    image_id: string;
    revision: number;
  }): Promise<ImageDocument>;
  imageExport(params: {
    project_id: string;
    image_id: string;
  }): Promise<{ path: string; file: string }>;
  chooseFolder(): Promise<string | null>;
  chooseImage(): Promise<{
    name: string;
    url: string;
    source_path?: string;
  } | null>;
  openExport(path: string): Promise<string>;
}

export type DesktopPackage = {
  id: string;
  root: string;
  version: string;
  signed: boolean;
  executable: string;
};
export type DesktopRelease = {
  tag: string;
  name: string;
  url: string;
  sha256: string;
  bytes: number;
};
export type DesktopUpdateSelection = {
  current: DesktopPackage;
  active: DesktopPackage;
  previous: DesktopPackage | null;
  staged: DesktopPackage[];
  pending: { attempted: boolean } | null;
  revision: string;
  message: string;
  busy: boolean;
};
export type ApplicationUpdateState = {
  packaged: boolean;
  error: string;
  application: DesktopUpdateSelection | null;
  release: DesktopRelease | null;
  source?: {
    current: string;
    root: string;
    available: { sha: string; mirror: string } | null;
    staged: { sha: string } | null;
    previous: { sha: string; transaction: string } | null;
    message: string;
    revision: string;
  } | null;
};

export interface EvaluationCandidate {
  id?: string;
  provider: string;
  endpoint: string;
  model: string;
  label: string;
  key_name: string;
  execution: string;
  reasoning_effort: string;
  effective_reasoning_effort?: string;
  max_output_tokens: number;
  status?: string;
  estimate?: {
    cost_usd: number;
    maximum_cost_usd: number;
    reasoning_tokens_unestimated?: boolean;
  };
  summary?: Record<string, unknown>;
}
export interface EvaluationDraft {
  source: string;
  candidates: EvaluationCandidate[];
  settings: {
    target_segments: number;
    stability_samples: number;
    repetitions: number;
    batch_size: number;
    budget_usd: number;
  };
  content_selection: {
    preset: string;
    sources: string[];
    map_files: string[];
    include_code_heavy: boolean;
  };
}
export interface EvaluationSample {
  id: string;
  scene_id: string;
  stratum: string;
  context: unknown;
  has_problems: boolean;
  paired_holdout_locked?: boolean;
  human_follow_up?: boolean;
  blind_labels: Record<string, string>;
  review: unknown;
  paired_review?: unknown;
  lines: {
    segment_id: string;
    source: string;
    outputs: Record<
      string,
      {
        translation: string;
        missing: boolean;
        valid: boolean;
        issues: string[];
        warnings: string[];
      }
    >;
  }[];
}
export interface EvaluationState {
  model_suggestions?: string[];
  defaults?: EvaluationCandidate[];
  content_groups?: [string, string, [string, string][]][];
  policy?: Record<string, unknown>;
  runs?: {
    run_id: string;
    status: string;
    created_at: string;
    source_name: string;
    models: string[];
    selected_segments: number;
    reviewed_samples: number;
  }[];
  draft?: Partial<EvaluationDraft>;
  credentials: { name: string; endpoint: string; keyless: boolean }[];
  active: string | null;
  allow_providers: boolean;
  paths: Record<string, string>;
  jobs: (Omit<OperationJob, "result"> & { result: EvaluationResult | null })[];
  view: null | {
    run_id: string;
    path: string;
    revision: string;
    requests: number;
    state: {
      status: string;
      candidates: EvaluationCandidate[];
      budget_usd_per_model: number;
      corpus_summary: Record<string, unknown>;
      credential_binding_required?: boolean;
      human_review?: Record<string, unknown>;
      paired_review?: Record<string, unknown>;
    };
    choices: {
      id: string;
      label: string;
      available: boolean;
      selected_by_default: boolean;
      valid_primary: number;
      reason: string;
    }[];
    context: Record<string, unknown>;
    paired_report: Record<string, unknown> | null;
    paired_summary: string;
    samples: EvaluationSample[];
    total: number;
    page: number;
  };
}
export interface EvaluationResult {
  models?: string[];
  model_source?: { key_name: string; endpoint: string; provider: string };
  run_id?: string;
  revision?: string;
  message?: string;
  path?: string;
  text?: string;
  selected?: number;
  source?: string;
  source_hash?: string;
  selection?: EvaluationDraft["content_selection"];
  inventory?: {
    source_counts: Record<string, number>;
    map_files: Record<string, number>;
    eligible_segments: number;
  };
  approval?: {
    candidates: EvaluationCandidate[];
    requests: number;
    budget: number;
  };
  preview?: Record<string, unknown>;
  options?: Record<string, unknown>;
}
export type GuidanceDocuments = Record<
  string,
  { text: string; revision: string; path?: string }
>;
export interface WolfDraft {
  profile?: string;
  query?: string;
  save_path?: string;
  output?: string;
  en_punct?: boolean;
  sync?: boolean;
  hit?: Record<string, string | number>;
  width?: number;
  font?: number;
  max_lines?: number;
  manual?: boolean;
  scope?: "row" | "group";
}
export interface WorkflowDraft {
  wolf?: WolfDraft;
  documents?: GuidanceDocuments;
  widths?: Record<string, number>;
  engine_options?: Record<string, SettingValue>;
}
export interface GuidedProject {
  id: string;
  source: string;
  engine: string;
  data: string;
  plugins: string;
  encrypted: string[];
  revision: number;
  step: number;
  done: number[];
  selected: string[];
  imported: string[];
  files: {
    name: string;
    category: string;
    size_kb: number;
    default: boolean;
  }[];
  widths: Record<string, number>;
  engine_options: Record<string, SettingValue>;
  mode: string;
  wolf: { literal_line1_lowconf: boolean; db_groups: string[] };
  phase1_comments: boolean;
  manual_job: string;
  collected: string[];
  collection_error: string;
}
export interface OperationJob {
  id: string;
  created: string;
  project_id: string;
  action: string;
  label: string;
  status: string;
  message: string;
  log: string[];
  result: Record<string, unknown> | null;
}
export interface BatchRow {
  local_queue: boolean | null;
  revision: string;
  id: string;
  source_id: string;
  created_at: string;
  updated_at: string;
  status: string;
  api_status: string;
  provider: string;
  model: string;
  key_name: string;
  endpoint: string;
  request_count: number | null;
  request_counts: Record<string, number> | null;
  file_set: string[] | null;
  cost_estimate: Record<string, number> | null;
  usage: Record<string, number> | null;
  actual_cost: number | null;
  notes: string;
  workflow: string;
  sequential_token_limit: number | null;
  queued_request_count: number | null;
}
export interface BatchState {
  credentials: string[];
  engines: string[];
  sources: {
    plan_root?: string;
    id: string;
    root: string;
    label: string;
    job_id: string;
    engine: string;
  }[];
  rows: BatchRow[];
  errors: { source_id: string; message: string }[];
  jobs: OperationJob[];
  active: string | null;
  allow_providers: boolean;
}
export interface WorkflowState {
  projects: { id: string; source: string; engine: string }[];
  project: GuidedProject | null;
  jobs: OperationJob[];
  active: string | null;
  manual_job: ManualJob | null;
  engine_schema: SettingField[];
  allow_providers: boolean;
  draft: WorkflowDraft;
  references: {
    id: string;
    title: string;
    mode: string;
    translated_data: string;
    source_data: string;
  }[];
}
export interface WorkflowPreview {
  overwrite: boolean;
  token: string;
  label: string;
  destination: string;
  confirmation: boolean;
  files: number;
  options: Record<string, unknown>;
}
export interface ImageSummary {
  id: string;
  name: string;
  width: number;
  height: number;
  revision: number;
  preview_revision: number | null;
  approved_revision: number | null;
}
export interface ImageBlock {
  angle?: number;
  skip?: boolean;
  lines?: {
    text: string;
    box: [number, number, number, number];
    angle?: number;
  }[];
  flags?: string[];
  id: string;
  box: [number, number, number, number];
  source: string;
  target: string;
  style: {
    background: string;
    inpaint_method?: string;
    font?: string;
    scale_x?: number;
    scale_y?: number;
    tracking?: number;
    outline_color?: string;
    outline_width?: number;
    fill_alpha?: number;
    text_color_alpha?: number;
    outline_color_alpha?: number;
    overflow?: boolean;
    locked?: boolean;
    confidence?: number;
    notes?: string[];
    donor?: [number, number, number, number];
    row_colors?: number[][];
    column_colors?: number[][];
    fill: string;
    text_color: string;
    cap_height: number;
    align: string;
    bold: boolean;
    italic: boolean;
  };
}
export interface ImageStroke {
  tool: "paint" | "erase-paint" | "cut";
  points: [number, number][];
  size: number;
  color: string;
}
export interface ImageDocument extends ImageSummary {
  status?: string;
  link?: { root: string; relative: string };
  project_id: string;
  mime: string;
  source_sha256: string;
  blocks: ImageBlock[];
  strokes: ImageStroke[];
  original_url?: string;
  preview_url?: string;
  paint_url?: string;
  cut_url?: string;
  base_url?: string;
  overlay_url?: string;
  notes: { block_id: string; ok: boolean; message: string; tight: boolean }[];
}
declare global {
  interface Window {
    workspace: WorkspaceAPI;
  }
}

export interface LenValues {
  mode: "local" | "api";
  include_images: boolean;
  include_glossary_base: boolean;
  install_forge: boolean;
  instructions: string;
}
export interface LenRecord {
  id: string;
  source: string;
  revision: number;
  values: LenValues;
  documents: GuidanceDocuments;
}
export interface LenState {
  project: LenRecord | null;
  projects: { id: string; source: string }[];
  jobs: OperationJob[];
  active: string | null;
  paths: Record<string, string>;
  forge_supported?: boolean;
  references?: WorkflowState["references"];
  progress?: {
    updated_at: string | null;
    phase: string | null;
    warnings?: string[];
    blocker: string;
    next_action: string;
  };
  metrics?: Record<string, { value: number; label: string; counts: string }>;
  phases?: Record<string, { label: string; status: string }>;
  estimate?: string;
  status?: string;
}

export interface VersionValues {
  original: string;
  original_version: string;
  official: string;
  version: string;
  baseline: string;
  patch_overlay: boolean;
  untranslated: boolean;
  preserve_game_files: boolean;
}
export interface VersionRecord {
  id: string;
  source: string;
  revision: number;
  values: VersionValues;
}
export interface RepositoryStatus {
  selected_root: string;
  repo_root: string | null;
  current_branch: string | null;
  translation_branch: string | null;
  original_exists: boolean;
  translation_exists: boolean;
  original_commit: string | null;
  translation_commit: string | null;
  original_version: string | null;
  translation_version: string | null;
  applied_update_version: string | null;
  ready: boolean;
  worktree_clean: boolean;
  pending_cherry_pick: boolean;
  asset_sync_pending: boolean;
  asset_manifest_available: boolean;
  asset_baseline_repair_needed: boolean;
  git_available: boolean;
  conflicts: string[];
  branches: string[];
}
export interface VersionPreview {
  job_id: string;
  source_root: string;
  version: string;
  patch_overlay: boolean;
  content_change_expected: boolean;
  added_paths: string[];
  modified_paths: string[];
  deleted_paths: string[];
  overlapping_paths: string[];
  already_present_paths: string[];
  formatted_json_paths: string[];
  json_warnings: string[];
  ignored_paths: string[];
  preserved_translation_asset_paths: string[];
  file_changes: {
    path: string;
    change: string;
    added_lines: number | null;
    deleted_lines: number | null;
    translation_changed: boolean;
    result: string;
  }[];
  image_changes: {
    path: string;
    change: string;
    tracked: boolean;
    warning: boolean;
    result: string;
  }[];
  external_changes: {
    path: string;
    change: string;
    category: string;
    already_present: boolean;
    size_bytes: number;
    result: string;
  }[];
}
export interface VersionState {
  project: VersionRecord | null;
  projects: { id: string; source: string }[];
  status: RepositoryStatus | null;
  preview: VersionPreview | null;
  jobs: OperationJob[];
  active: string | null;
}

export interface AssetRecord {
  id: string;
  source: string;
  engine: string;
  image_root: string;
  detection: string;
}
export interface AssetState {
  translations: { id: string; label: string; path: string }[];
  project: AssetRecord | null;
  projects: AssetRecord[];
  assets: {
    id: string;
    relative: string;
    editable: boolean;
    encrypted: boolean;
    runtime: boolean;
  }[];
  folders: string[];
  total: number;
  count: number;
  page: number;
  pages: number;
  jobs: OperationJob[];
  active: string;
  running: boolean;
  legacy: boolean;
  paths: Record<string, string>;
  image_job?: Job;
}

export interface InstructionDraft {
  name: string;
  revision: string;
  text: string;
}
export interface SharedInstruction extends InstructionDraft {
  default: string;
  customized: boolean;
  bundled_changed: boolean;
  path: string;
  draft: { revision: string; text: string } | null;
}
