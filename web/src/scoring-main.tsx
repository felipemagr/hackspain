import "@fontsource-variable/geist";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { loadRates } from "./lib/currency";
import "./app.css";

loadRates(new URL(/* @vite-ignore */ "../data/fx.json", import.meta.url).href);

createRoot(document.getElementById("root")!).render(
  <StrictMode><ErrorBoundary><App localScoring /></ErrorBoundary></StrictMode>,
);
