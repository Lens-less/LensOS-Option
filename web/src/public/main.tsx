import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { PublicApp } from "./PublicApp";
import "../styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("public research root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <PublicApp />
  </StrictMode>,
);
