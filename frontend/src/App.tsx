import { Link, Route, Routes } from "react-router-dom";

function FoundationPage() {
  return (
    <main className="mx-auto max-w-4xl p-8">
      <h1 className="text-3xl font-semibold">Autonomous NoSQL Optimizer</h1>
      <p className="mt-3 text-slate-600">Frontend foundation is ready for the target dashboard.</p>
      <nav className="mt-6"><Link className="text-blue-700 underline" to="/">Overview</Link></nav>
    </main>
  );
}

export default function App() {
  return <Routes><Route path="*" element={<FoundationPage />} /></Routes>;
}
