export type TargetFact = {
  label: string;
  value: string;
  detail: string;
};

export const TARGET_FACTS: readonly TargetFact[] = [
  { label: "Health", value: "Healthy", detail: "Local monitored MongoDB is reachable." },
  { label: "Version", value: "MongoDB 8.x", detail: "Capability discovery records the exact server and FCV values." },
  { label: "Topology", value: "Replica set", detail: "Replica set name: rs-monitored." },
  { label: "Capabilities", value: "Discovered", detail: "Read-only capability snapshot; query settings and query stats are checked." },
  { label: "Telemetry source", value: "Capability selected", detail: "Preference order: query stats, diagnostic log, profiler, current operations." },
  { label: "Namespace allowlist", value: "Not configured", detail: "No namespaces are eligible until an allowlist is configured." },
  { label: "Deployment mode", value: "Approval controlled", detail: "Production changes retain configured human approval boundaries." },
  { label: "Evaluation target", value: "mongo-evaluation", detail: "Separate local evaluation MongoDB replica set." },
  { label: "Autonomy eligibility", value: "Safety constrained", detail: "Only admitted, typed, reversible actions can become eligible." },
];
