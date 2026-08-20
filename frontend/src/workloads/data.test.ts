import { describe, expect, it } from "vitest";
import { WORKLOAD_FACTS } from "./data";

describe("workload dashboard data", () => {
  it("contains every required workload field", () => {
    expect(WORKLOAD_FACTS.map((fact) => fact.label)).toEqual([
      "Throughput",
      "Read/write split",
      "p50 / p95 / p99",
      "Query-shape distribution",
      "CPU",
      "Memory",
      "Disk",
      "Replication lag",
    ]);
  });
});
