import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";

// Fontes self-host (bundle) — não dependem do Google CDN: funcionam offline,
// no desktop Tauri e em redes filtradas, e não vazam o IP dos alunos (LGPD).
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
// Poppins é a fonte da interface inteira na identidade v2 (títulos, números e corpo).
// O navegador só baixa um arquivo .woff2 quando a página usa aquele peso.
import "@fontsource/poppins/400.css";
import "@fontsource/poppins/500.css";
import "@fontsource/poppins/600.css";
import "@fontsource/poppins/700.css";

import App from "./App";
import { LimiteErro } from "./components/LimiteErro";
import { PwaAviso } from "./components/PwaAviso";
import { AppProvider } from "./context/AppContext";
import { recuperarDeChunkObsoleto } from "./lib/atualizacao";
import { iniciarAtualizacaoPwa } from "./lib/pwaAtualizacao";
import "./index.css";

// Service worker (PWA): torna o app instalável no celular e no computador, com o
// app shell disponível offline. A versão nova é baixada em segundo plano e ESPERA:
// o aviso "Atualizar agora" (PwaAviso) decide a troca — nada recarrega sozinho com
// alguém editando. Telão/vitrine e a abertura do app (antes de qualquer toque)
// trocam direto. Regras: lib/pwaAtualizacao.ts e docs/operacao/PWA-ATUALIZACAO.md.
iniciarAtualizacaoPwa(registerSW);

// Deploy novo + shell antigo em cache = chunk lazy (ex.: o Dashboard) some e o
// import dinâmico falha. O Vite emite `vite:preloadError`; aqui limpamos o
// cache do PWA e recarregamos para o build novo, em vez de deixar a tela em
// branco/no LimiteErro para todos os perfis.
window.addEventListener("vite:preloadError", (evento: Event) => {
  evento.preventDefault();
  recuperarDeChunkObsoleto();
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LimiteErro>
      <BrowserRouter>
        <AppProvider>
          <App />
        </AppProvider>
      </BrowserRouter>
    </LimiteErro>
    <PwaAviso />
  </StrictMode>,
);
