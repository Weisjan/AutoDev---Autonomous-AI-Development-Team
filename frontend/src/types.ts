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
