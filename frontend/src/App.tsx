import { Link, Route, Routes } from "react-router-dom";
import ExpertDashboard from "./expert/ExpertDashboard";
import RunDashboard from "./runs/RunDashboard";
import TargetDashboard from "./targets/TargetDashboard";
import WorkloadDashboard from "./workloads/WorkloadDashboard";

export default function App() {
  return (
    <>
      <nav className="border-b border-slate-200 bg-white px-6 py-3 text-sm font-medium">
        <div className="mx-auto flex max-w-6xl gap-5"><Link className="text-slate-700 hover:text-blue-700" to="/targets">Target</Link><Link className="text-slate-700 hover:text-blue-700" to="/workload">Workload</Link><Link className="text-slate-700 hover:text-blue-700" to="/runs">Runs</Link><Link className="text-slate-700 hover:text-blue-700" to="/expert">Expert</Link></div>
      </nav>
      <Routes>
        <Route path="/targets" element={<TargetDashboard />} />
        <Route path="/workload" element={<WorkloadDashboard />} />
        <Route path="/expert" element={<ExpertDashboard />} />
        <Route path="*" element={<RunDashboard />} />
      </Routes>
    </>
  );
}
