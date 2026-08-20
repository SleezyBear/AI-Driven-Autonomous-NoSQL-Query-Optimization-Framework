import { describe, expect, it } from "vitest";
import { TARGET_FACTS } from "./data";

describe("target dashboard data", () => {
  it("contains every required target field", () => {
    expect(TARGET_FACTS.map((fact) => fact.label)).toEqual([
      "Health",
      "Version",
      "Topology",
      "Capabilities",
      "Telemetry source",
      "Namespace allowlist",
      "Deployment mode",
      "Evaluation target",
      "Autonomy eligibility",
    ]);
  });
});
