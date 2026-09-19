import "@fontsource-variable/geist";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { loadRates } from "./lib/currency";
import { watchWindowErrors } from "./lib/report";
import "./app.css";

watchWindowErrors();
loadRates();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
