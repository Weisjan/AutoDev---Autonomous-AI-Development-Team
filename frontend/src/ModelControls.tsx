import type {
  ModelOptions,
  ModelPolicy,
  ModelPreset,
  ModelRole,
  ReasoningEffort,
} from "./types";

const roles: [ModelRole, string][] = [
  ["architect", "Architect"],
  ["developer", "Developers"],
  ["reviewer", "Reviewer"],
];
export const presetLabel = (preset: ModelPreset | null) =>
  ({
    fast: "Fast",
    balanced: "Balanced",
    maximum_quality: "Maximum Quality",
  })[preset || "balanced"];

export default function ModelControls({
  value,
  options,
  changed,
}: {
  value: ModelPolicy;
  options?: ModelOptions;
  changed: (value: ModelPolicy) => void;
}) {
  const update = (
    role: ModelRole,
    field: "model" | "reasoning_effort",
    selected: string,
  ) => {
    const overrides = { ...value.overrides };
    const settings = { ...overrides[role] };
    if (selected) Object.assign(settings, { [field]: selected });
    else delete settings[field];
    if (Object.keys(settings).length) overrides[role] = settings;
    else delete overrides[role];
    changed({ ...value, overrides });
  };
  return (
    <fieldset className="model-controls">
      <legend>Role-based model settings</legend>
      <label>
        Model preset
        <select
          value={value.preset}
          onChange={(e) => changed({ preset: e.target.value as ModelPreset })}
        >
          {(["fast", "balanced", "maximum_quality"] as const).map((name) => (
            <option key={name} value={name}>
              {presetLabel(name)}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">
        Requested settings · account access unverified. Presets do not change
        workflow limits.
      </p>
      <table className="model-table">
        <thead>
          <tr>
            <th>Role</th>
            <th>Requested model</th>
            <th>Reasoning</th>
          </tr>
        </thead>
        <tbody>
          {roles.map(([role, label]) => {
            const settings = value.overrides?.[role];
            const base = options?.presets[value.preset][role];
            return (
              <tr key={role}>
                <th>{label}</th>
                <td>{settings?.model || base?.model || "Loading options…"}</td>
                <td>
                  {settings?.reasoning_effort || base?.reasoning_effort || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <details>
        <summary>
          Customize roles
          {Object.keys(value.overrides || {}).length
            ? " · overrides applied"
            : ""}
        </summary>
        <p className="field-hint">
          Changing the preset clears role overrides. Runtime observations are
          unavailable from the current Codex exec transport.
        </p>
        {roles.map(([role, label]) => (
          <div className="form-grid" key={role}>
            <label>
              {label} model
              <select
                aria-label={`${label} model`}
                value={value.overrides?.[role]?.model || ""}
                disabled={!options}
                onChange={(e) => update(role, "model", e.target.value)}
              >
                <option value="">Use preset model</option>
                {options?.models.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {label} reasoning
              <select
                aria-label={`${label} reasoning`}
                value={value.overrides?.[role]?.reasoning_effort || ""}
                disabled={!options}
                onChange={(e) =>
                  update(
                    role,
                    "reasoning_effort",
                    e.target.value as ReasoningEffort,
                  )
                }
              >
                <option value="">Use preset reasoning</option>
                {options?.reasoning_efforts.map((effort) => (
                  <option key={effort} value={effort}>
                    {effort === "xhigh" ? "Extra high (xhigh)" : effort}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ))}
      </details>
    </fieldset>
  );
}
