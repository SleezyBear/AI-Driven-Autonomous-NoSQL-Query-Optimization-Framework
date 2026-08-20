export type WorkloadFact = {
  label: string;
  value: string;
  evidence: string;
};

export const WORKLOAD_FACTS: readonly WorkloadFact[] = [
  { label: "Throughput", value: "No observations", evidence: "Normalized operation count: 0 in the current telemetry window." },
  { label: "Read/write split", value: "No operations", evidence: "Normalized read count: 0; normalized write count: 0." },
  { label: "p50 / p95 / p99", value: "Not available", evidence: "Latency percentiles require a non-empty normalized sample." },
  { label: "Query-shape distribution", value: "No shapes observed", evidence: "No literal predicates are retained; the current normalized shape set is empty." },
  { label: "CPU", value: "Not collected", evidence: "No resource observation is attached to the current telemetry window." },
  { label: "Memory", value: "Not collected", evidence: "No resource observation is attached to the current telemetry window." },
  { label: "Disk", value: "Not collected", evidence: "No resource observation is attached to the current telemetry window." },
  { label: "Replication lag", value: "Not collected", evidence: "No replication-lag observation is attached to the current telemetry window." },
];
