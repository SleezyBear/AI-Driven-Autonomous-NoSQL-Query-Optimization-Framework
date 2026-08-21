import { Eye, LockKeyhole } from "lucide-react";
import type { ReactNode } from "react";
import { EXPERT_EVIDENCE } from "./data";

export default function ExpertDashboard() {
  return (
    <main className="mx-auto max-w-6xl p-6 sm:p-10">
      <header className="border-b border-slate-200 pb-6">
        <p className="text-sm font-medium text-blue-700">Expert Mode</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Read-only evidence</h1>
        <p className="mt-2 max-w-3xl text-slate-600">Inspect normalized evidence behind an optimization decision. This view never exposes secrets and cannot execute actions.</p>
      </header>

      <section aria-label="Expert Mode safeguards" className="mt-6 grid gap-4 md:grid-cols-2">
        <Summary icon={<Eye className="text-blue-600" />} label="Access" value="Read-only evidence" />
        <Summary icon={<LockKeyhole className="text-emerald-600" />} label="Sensitive data" value="Secrets excluded" />
      </section>

      <section aria-label="Expert evidence" className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {EXPERT_EVIDENCE.map((item) => (
          <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm" key={item.label}>
            <h2 className="text-sm font-medium text-slate-500">{item.label}</h2>
            <p className="mt-2 text-lg font-semibold text-slate-900">{item.value}</p>
            <p className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-600">Evidence: {item.detail}</p>
          </article>
        ))}
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
