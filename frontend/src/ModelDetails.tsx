import type { ModelExecution, RoleSettings } from "./types";

export default function ModelDetails({
  requested,
  execution,
}: {
  requested?: RoleSettings;
  execution?: ModelExecution;
}) {
  const settings = execution?.requested || requested;
  return (
    <dl className="model-details">
      <div>
        <dt>Requested model</dt>
        <dd>
          {settings
            ? settings.model || "Codex default (unverified)"
            : "Not recorded"}
        </dd>
      </div>
      <div>
        <dt>Requested reasoning</dt>
        <dd>
          {settings
            ? settings.reasoning_effort || "Codex default (unverified)"
            : "Not recorded"}
        </dd>
      </div>
      {settings && (
        <div>
          <dt>Configuration source</dt>
          <dd>
            Model: {settings.model_source} · reasoning: {settings.effort_source}
          </dd>
        </div>
      )}
      <div>
        <dt>Runtime model / reasoning</dt>
        <dd>Unavailable · not reported reliably by Codex exec</dd>
      </div>
      {execution && (
        <div>
          <dt>Model request</dt>
          <dd>
            {execution.status}
            {execution.error_kind ? ` · ${execution.error_kind}` : ""}
          </dd>
        </div>
      )}
    </dl>
  );
}
