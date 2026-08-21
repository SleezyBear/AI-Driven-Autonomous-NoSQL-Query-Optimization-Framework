import { describe, expect, it } from "vitest";
import { EXPERT_EVIDENCE } from "./data";

describe("expert evidence", () => {
  it("exposes every required read-only evidence category", () => {
    expect(EXPERT_EVIDENCE.map((item) => item.label)).toEqual([
      "Normalized telemetry",
      "Query hashes",
      "Environment fingerprints",
      "Candidate JSON",
      "LLM input",
      "LLM output",
      "Retrieved memories",
      "Trial measurements",
      "Confidence intervals",
      "Per-metric verdicts",
      "Ledger state",
      "Rollback preconditions",
    ]);
  });

  it("does not retain secret-bearing values in the rendered evidence data", () => {
    const rendered = JSON.stringify(EXPERT_EVIDENCE).toLowerCase();
    for (const forbidden of ["password", "credential", "access_token", "mongodb://"]) {
      expect(rendered).not.toContain(forbidden);
    }
  });
});
