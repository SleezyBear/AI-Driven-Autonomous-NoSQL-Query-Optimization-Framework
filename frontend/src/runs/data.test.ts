import { describe, expect, it } from "vitest";
import { RUN_DECISION_FACTS } from "./data";

describe("run dashboard data", () => {
  it("contains every required audit field", () => {
    expect(RUN_DECISION_FACTS.map((fact) => fact.label)).toEqual([
      "Diagnosis",
      "Candidates",
      "AI ranking",
      "Evaluation",
      "Statistical verdict",
      "Safety verdict",
      "Approval",
      "Deployment",
      "Post-deployment result",
      "Rollback status",
    ]);
  });
});
