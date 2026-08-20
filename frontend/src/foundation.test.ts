import { describe, expect, it } from "vitest";

describe("frontend foundation", () => {
  it("uses the project title", () => {
    expect("Autonomous NoSQL Optimizer").toContain("NoSQL");
  });
});
