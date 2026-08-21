export type ExpertEvidence = {
  label: string;
  value: string;
  detail: string;
};

export const EXPERT_EVIDENCE: readonly ExpertEvidence[] = [
  { label: "Normalized telemetry", value: "No telemetry window selected", detail: "Only normalized operation evidence is eligible for display." },
  { label: "Query hashes", value: "No query shapes observed", detail: "Literal predicate values are never retained in this view." },
  { label: "Environment fingerprints", value: "No evaluation selected", detail: "Environment fingerprints are attached to benchmark evidence when a run exists." },
  { label: "Candidate JSON", value: "No candidates generated", detail: "Only typed candidate actions can appear here." },
  { label: "LLM input", value: "No AI request recorded", detail: "The captured, privacy-sanitized input is shown only for a selected run." },
  { label: "LLM output", value: "No AI response recorded", detail: "Structured AI output is shown only for a selected run." },
  { label: "Retrieved memories", value: "No memories retrieved", detail: "Retrieved experience may reprioritize candidates but cannot create actions." },
  { label: "Trial measurements", value: "No sandbox trial recorded", detail: "Paired baseline and candidate measurements appear after a sandbox evaluation." },
  { label: "Confidence intervals", value: "Not available", detail: "Intervals require a completed paired statistical evaluation." },
  { label: "Per-metric verdicts", value: "No admission verdict", detail: "Protected metric decisions are shown for the selected evaluation only." },
  { label: "Ledger state", value: "No ledger entry selected", detail: "Append-only ledger state is read-only in Expert Mode." },
  { label: "Rollback preconditions", value: "Not applicable", detail: "Ownership and current-state checks are shown only for a rollback candidate." },
];
