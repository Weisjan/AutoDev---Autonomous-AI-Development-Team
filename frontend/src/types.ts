export type Project = {
  id: string;
  name: string;
  path: string;
  branch: string;
  dirty: boolean;
  error?: string;
};
export type Attempt = {
  agent_id: string;
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  commit?: string;
  error?: string;
  error_kind?: string;
  execution?: ModelExecution;
};
export type Check = {
  passed: boolean;
  skipped: boolean;
  stdout: string;
  stderr: string;
  command: string[];
  exit_code: number | null;
  timed_out: boolean;
  failure_kind?: string;
  reason?: string;
};
export type DevTask = {
  task: {
    id: string;
    description: string;
    owned_files: string[];
    acceptance_criteria: string[];
  };
  status: string;
  branch: string;
  worktree: string;
  attempts: Attempt[];
};
export type Report = {
  report_version?: number;
  model_policy?: ResolvedModelPolicy;
  error_kind?: string;
  mode?: "project";
  specification?: ProjectSpecification;
  milestones?: {
    id: string;
    status: string;
    started_at: string;
    finished_at: string;
    commit?: string;
  }[];
  checkpoint_history?: {
    number: number;
    at: string;
    label: string;
    commit: string;
  }[];
  checkpoint_safe?: boolean;
  validated_tasks?: string[];
  active_milestone?: string;
  run_id: string;
  succeeded: boolean;
  integration_status: string;
  stopped_reason: string;
  source_branch: string;
  integration_branch: string;
  integration_commit?: string;
  base_commit: string;
  duration_seconds: number;
  tasks: DevTask[];
  rounds: {
    number: number;
    milestone_id?: string;
    correction_attempt?: number;
    checks?: { pytest: Check; ruff: Check; environment?: Check };
  }[];
  review?: {
    approved: boolean;
    summary: string;
    findings: {
      severity: string;
      message: string;
      file_path?: string;
      line?: number;
    }[];
  };
  planner_execution?: Attempt;
  reviewer_execution?: Attempt;
  plan?: { summary: string };
};
export type Run = {
  model_policy?: ResolvedModelPolicy;
  id: string;
  run_id: string;
  repository_id: string;
  instructions: string;
  status: string;
  stage: string;
  started_at: string;
  finished_at: string;
  report?: Report;
  error?: string;
  events?: { stage: string; at: string; task_id?: string; error?: string }[];
};
export type Start = {
  model_policy?: ModelPolicy | null;
  mode?: "task" | "project";
  repository_id: string;
  instructions: string;
  concurrency: number;
  max_tasks: number;
  max_corrections: number;
  max_model_calls: number;
  workflow_timeout_seconds: number;
  example: boolean;
};
export type Settings = {
  model_options?: ModelOptions;
  provider: string;
  authentication: string;
  sandbox: string;
  max_concurrency: number;
  max_corrections: number;
  max_tasks: number;
  docker_image: string;
  merging: string;
  cancellation: string;
};

export type ModelRole = "architect" | "developer" | "reviewer";
export type ModelPreset = "fast" | "balanced" | "maximum_quality";
export type ReasoningEffort = "low" | "medium" | "high" | "xhigh";
export type RoleSettings = {
  model: string | null;
  reasoning_effort: ReasoningEffort | null;
  model_source: string;
  effort_source: string;
};
export type ModelPolicy = {
  preset: ModelPreset;
  overrides?: Partial<
    Record<ModelRole, { model?: string; reasoning_effort?: ReasoningEffort }>
  >;
};
export type ResolvedModelPolicy = Record<ModelRole, RoleSettings> & {
  kind: "resolved";
  version: number;
  preset: ModelPreset | null;
  preset_revision: number;
};
export type ModelExecution = {
  role: ModelRole;
  requested: RoleSettings;
  observed_model: null;
  observed_reasoning_effort: null;
  observation_status: "unavailable";
  status: string;
  error_kind?: string;
};
export type ModelOptions = {
  default_dashboard_preset: ModelPreset;
  presets: Record<ModelPreset, ResolvedModelPolicy>;
  models: string[];
  reasoning_efforts: ReasoningEffort[];
  availability: string;
  runtime_observations: string;
};

export type ProjectSpecification = {
  title: string;
  summary: string;
  technology_stack: string[];
  repository_structure: string[];
  components: { id: string; responsibility: string; files: string[] }[];
  interfaces: { source: string; target: string; contract: string }[];
  tasks: {
    id: string;
    description: string;
    owned_files: string[];
    depends_on: string[];
    test_paths: string[];
    acceptance_criteria: string[];
  }[];
  milestones: {
    id: string;
    description: string;
    task_ids: string[];
    acceptance_criteria: string[];
    test_paths: string[];
  }[];
  acceptance_criteria: string[];
  testing_requirements: string[];
  risks: string[];
  assumptions: string[];
};
