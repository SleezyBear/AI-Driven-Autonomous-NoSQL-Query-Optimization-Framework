import { describe, expect, it } from "vitest";
import { runOutcome } from "./LiveRuns";
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

  it("renders deployment success as a human outcome", () => {
    expect(runOutcome({
      run_id: "run-1",
      target_id: "target-1",
      status: "COMPLETED",
      deployment_mode: "APPROVAL_CONTROLLED",
      primary_metric_key: "p99_latency_ms",
      completion_reason: "DEPLOYMENT_SUCCEEDED",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:01Z",
    })).toBe("Deployment completed successfully.");
  });
});
