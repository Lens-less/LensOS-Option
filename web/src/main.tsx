import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";

import { DecisionDeskApp } from "./decisionDesk/DecisionDeskApp";
import "./decisionDesk/decisionDesk.css";
import "./base.css";

const LegacyApp = lazy(() => import("./legacyEntry"));

const root = document.getElementById("root");

if (!root) {
  throw new Error("evidence console root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <Suspense fallback={<p role="status">正在打开研究界面…</p>}>
      {new Set(["legacy", "evidence", "workbench", "signal", "series", "demo"]).has(new URLSearchParams(window.location.search).get("view") ?? "") ? <LegacyApp /> : <DecisionDeskApp />}
    </Suspense>
  </StrictMode>,
);
