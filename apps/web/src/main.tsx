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
// trocam direto. A exceção é o socorro abaixo, quando a tela pedida já não existe.
// Regras: lib/pwaAtualizacao.ts e docs/operacao/PWA-ATUALIZACAO.md.
iniciarAtualizacaoPwa(registerSW);

// Deploy novo + página na versão antiga sem os arquivos dela no cache (outra aba
// aplicou a versão nova, ou a página veio da rede) = o chunk lazy de uma tela ainda
// não aberta (ex.: o Dashboard) sumiu do servidor e o import dinâmico falha. O Vite
// emite `vite:preloadError`; aqui recarregamos da rede, uma vez por sessão, para o
// build novo, em vez de deixar a tela em branco/no LimiteErro para todos os perfis.
// Sem apagar o cache do PWA: as outras abas abertas ainda dependem dele.
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
