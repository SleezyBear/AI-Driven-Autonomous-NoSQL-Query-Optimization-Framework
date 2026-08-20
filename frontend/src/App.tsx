import { Route, Routes } from "react-router-dom";
import TargetDashboard from "./targets/TargetDashboard";

export default function App() {
  return <Routes><Route path="*" element={<TargetDashboard />} /></Routes>;
}
