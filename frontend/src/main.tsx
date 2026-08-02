import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "./router";
import App from "./App";

// Pixel Art Design System (restored)
import "./pixel-theme.css";
import "./pixel-effects.css";

// Clean Layout inspired by prototype
import "./runs-page-clean.css";

// Original styles
import "./styles.css";
import "./workspace.css";
import "./agent-ui.css";
import "./pixel-agents.css";
import "./final-ui.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode><RouterProvider><App /></RouterProvider></StrictMode>,
);
