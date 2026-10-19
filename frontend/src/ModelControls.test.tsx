import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { expect, it } from "vitest";
import ModelControls from "./ModelControls";
import ModelDetails from "./ModelDetails";
import type { ModelOptions, ModelPolicy } from "./types";

const role = {
  model: "gpt-6-astra",
  reasoning_effort: "high" as const,
  model_source: "preset",
  effort_source: "preset",
};
const snapshot = {
  kind: "resolved" as const,
  version: 1,
  preset: "balanced" as const,
  preset_revision: 1,
  architect: role,
  developer: { ...role, model: "gpt-6.1-sol" },
  reviewer: role,
};
const options: ModelOptions = {
  default_dashboard_preset: "balanced",
  presets: {
    fast: { ...snapshot, preset: "fast" },
    balanced: snapshot,
    maximum_quality: { ...snapshot, preset: "maximum_quality" },
  },
  models: ["gpt-6-astra", "gpt-6.1-sol"],
  reasoning_efforts: ["low", "medium", "high", "xhigh"],
  availability: "Account access unverified",
  runtime_observations: "Unavailable",
};

function Form() {
  const [value, change] = useState<ModelPolicy>({ preset: "balanced" });
  return (
    <>
      <ModelControls value={value} options={options} changed={change} />
      <output data-testid="selection">{JSON.stringify(value)}</output>
    </>
  );
}

it("defaults to Balanced, customizes typed role settings and clears overrides on preset change", () => {
  render(<Form />);
  expect(screen.getByLabelText("Model preset")).toHaveValue("balanced");
  fireEvent.click(screen.getByText("Customize roles"));
  fireEvent.change(screen.getByLabelText("Architect reasoning"), {
    target: { value: "xhigh" },
  });
  expect(
    JSON.parse(screen.getByTestId("selection").textContent!).overrides.architect
      .reasoning_effort,
  ).toBe("xhigh");
  expect(screen.getByText(/overrides applied/)).toBeVisible();
  fireEvent.change(screen.getByLabelText("Model preset"), {
    target: { value: "maximum_quality" },
  });
  expect(JSON.parse(screen.getByTestId("selection").textContent!)).toEqual({
    preset: "maximum_quality",
  });
  expect(screen.getByText(/account access unverified/)).toBeVisible();
  expect(screen.getByText(/do not change workflow limits/)).toBeVisible();
});

it("keeps requested settings separate from unavailable runtime observations", () => {
  render(
    <ModelDetails
      requested={role}
      execution={{
        role: "architect",
        requested: role,
        observed_model: null,
        observed_reasoning_effort: null,
        observation_status: "unavailable",
        status: "succeeded",
      }}
    />,
  );
  expect(screen.getByText("gpt-6-astra")).toBeVisible();
  expect(screen.getByText("Requested model")).toBeVisible();
  expect(screen.getByText(/Unavailable · not reported reliably/)).toBeVisible();
  expect(screen.queryByText(/runtime verified/i)).not.toBeInTheDocument();
});

it("does not fabricate settings for historical attempts", () => {
  render(<ModelDetails />);
  expect(screen.getAllByText("Not recorded")).toHaveLength(2);
  expect(screen.getByText(/Unavailable/)).toBeVisible();
});
