export type RunDecisionFact = {
  label: string;
  value: string;
  evidence: string;
};

export const RUN_DECISION_FACTS: readonly RunDecisionFact[] = [
  { label: "Diagnosis", value: "No run selected", evidence: "No diagnosis artifact has been created for the current view." },
  { label: "Candidates", value: "No candidates", evidence: "No deterministic candidate set is associated with the current view." },
  { label: "AI ranking", value: "Not requested", evidence: "No structured ranking response is associated with the current view." },
  { label: "Evaluation", value: "Not started", evidence: "No sandbox evaluation records are associated with the current view." },
  { label: "Statistical verdict", value: "No decision", evidence: "No paired trial comparison is associated with the current view." },
  { label: "Safety verdict", value: "No decision", evidence: "No deterministic admission decision is associated with the current view." },
  { label: "Approval", value: "Not requested", evidence: "No approval request or bound evidence hash is associated with the current view." },
  { label: "Deployment", value: "Not started", evidence: "No production deployment transition is associated with the current view." },
  { label: "Post-deployment result", value: "Not applicable", evidence: "No deployment means no monitoring outcome is available." },
  { label: "Rollback status", value: "Not applicable", evidence: "No deployment means no rollback state is available." },
];
