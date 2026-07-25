import React from "react";
import ReactDOM from "react-dom/client";
import { SidePanelApp } from "./SidePanelApp";
import "../styles/sidepanel.css";

const container = document.getElementById("root");

if (!container) {
  throw new Error("sidepanel root container is missing");
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <SidePanelApp />
  </React.StrictMode>,
);
