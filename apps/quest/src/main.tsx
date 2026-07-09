import React from "react";
import ReactDOM from "react-dom/client";

// Fontes auto-hospedadas (PWA offline — nada de CDN externa). SÓ o subset
// latin: os entrypoints completos arrastam devanagari/cirílico/vietnamita
// para o precache (~1,2MB a mais atravessando o Wi-Fi da escola à toa).
import "@fontsource/baloo-2/latin-600.css";
import "@fontsource/baloo-2/latin-700.css";
import "@fontsource/baloo-2/latin-800.css";
import "@fontsource/nunito/latin-600.css";
import "@fontsource/nunito/latin-700.css";
import "@fontsource/nunito/latin-800.css";
import "@fontsource/nunito/latin-900.css";

import "./design/tokens.css";
import "./design/base.css";

import { App } from "./app/App";
import { iniciarAudio } from "./audio/audio";

iniciarAudio();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
