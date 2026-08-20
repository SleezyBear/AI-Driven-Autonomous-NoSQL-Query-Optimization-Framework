import { useState, type ReactNode } from "react";
import { ClipboardCheck, FileSearch, ShieldCheck, Waypoints, ChevronDown, ChevronUp } from "lucide-react";
import { RUN_DECISION_FACTS } from "./data";

export default function RunDashboard() {
  const [expertMode, setExpertMode] = useState(false);

  return (
    <main className="mx-auto max-w-6xl p-6 sm:p-10">
      <header className="flex flex-col justify-between gap-5 border-b border-slate-200 pb-6 sm:flex-row sm:items-start">
        <div>
          <p className="text-sm font-medium text-blue-700">Run dashboard</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Optimization decision audit</h1>
          <p className="mt-2 text-slate-600">A complete, evidence-led view of each optimization decision.</p>
        </div>
        <button
          aria-pressed={expertMode}
          className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium shadow-sm hover:bg-slate-50"
          onClick={() => setExpertMode((current) => !current)}
          type="button"
        >
          {expertMode ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          Expert Mode {expertMode ? "on" : "off"}
        </button>
      </header>

      <section aria-label="Run summary" className="mt-6 grid gap-4 md:grid-cols-3">
        <Summary icon={<FileSearch className="text-blue-600" />} label="Selected run" value="None" />
        <Summary icon={<ClipboardCheck className="text-violet-600" />} label="Decision state" value="Awaiting a run" />
        <Summary icon={<ShieldCheck className="text-emerald-600" />} label="Auditability" value="Evidence-led" />
      </section>

      <section aria-label="Optimization decision trail" className="mt-8">
        <div className="mb-4 flex items-center gap-2 text-sm font-medium text-slate-600"><Waypoints size={16} /> Full decision trail</div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          {RUN_DECISION_FACTS.map((fact) => (
            <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm" key={fact.label}>
              <h2 className="text-sm font-medium text-slate-500">{fact.label}</h2>
              <p className="mt-2 text-lg font-semibold text-slate-900">{fact.value}</p>
              {expertMode && <p className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-600">Evidence: {fact.evidence}</p>}
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function Summary({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {icon}
      <div><p className="text-sm text-slate-500">{label}</p><p className="font-semibold">{value}</p></div>
    </div>
  );
}
