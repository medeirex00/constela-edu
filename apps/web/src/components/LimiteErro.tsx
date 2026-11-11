import { Component, type ErrorInfo, type ReactNode } from "react";

import { ehErroDeChunk, recuperarDeChunkObsoleto } from "../lib/atualizacao";
import { recarregarSemServiceWorker } from "../lib/pwaAtualizacao";

interface Props {
  children: ReactNode;
}
interface State {
  erro: boolean;
}

/**
 * Error Boundary do app web. Um erro de renderização em QUALQUER página é
 * contido aqui e vira uma tela de recuperação — em vez de desmontar toda a SPA
 * e deixar "tela branca" sem saída. Estilos inline de propósito: a tela de
 * fallback não depende de CSS que também pode ter falhado.
 */
export class LimiteErro extends Component<Props, State> {
  state: State = { erro: false };

  static getDerivedStateFromError(): State {
    return { erro: true };
  }

  componentDidCatch(erro: Error, info: ErrorInfo): void {
    // Log local no console (o backend não recebe stack do cliente).
    console.error("Erro de renderização capturado:", erro, info.componentStack);
    // Falha ao carregar um chunk lazy (deploy novo: o arquivo da versão antiga
    // sumiu) = recarrega da rede uma vez, já na versão nova, em vez de estampar
    // "Algo deu errado". Sem apagar o cache do PWA, que as outras abas usam.
    if (ehErroDeChunk(erro)) recuperarDeChunkObsoleto();
  }

  render(): ReactNode {
    if (!this.state.erro) return this.props.children;
    // Identidade v2 nos VALORES (fundo lavanda, Poppins, botão violeta), mas tudo
    // continua inline: esta tela não pode depender do CSS que talvez tenha falhado.
    return (
      <div
        role="alert"
        style={{
          minHeight: "100dvh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "0.75rem",
          padding: "2rem",
          textAlign: "center",
          fontFamily: "Poppins, Inter, system-ui, sans-serif",
          background: "#F5F6FB",
          color: "#1A1C38",
        }}
      >
        <span
          aria-hidden
          style={{
            display: "grid",
            placeItems: "center",
            width: "3.5rem",
            height: "3.5rem",
            marginBottom: "0.25rem",
            borderRadius: "9999px",
            background: "#F3F1FE",
            color: "#6C5CE7",
          }}
        >
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </span>
        <h1 style={{ fontSize: "1.625rem", fontWeight: 700, letterSpacing: "-0.01em", margin: 0 }}>
          Algo deu errado
        </h1>
        <p style={{ maxWidth: "28rem", color: "#545876", fontSize: "0.95rem", lineHeight: 1.55, margin: 0 }}>
          Tivemos um problema ao mostrar esta tela. Recarregue e tente de novo —
          seus dados estão salvos.
        </p>
        <button
          type="button"
          onClick={() => void recarregarSemServiceWorker()}
          style={{
            marginTop: "0.75rem",
            padding: "0.7rem 1.4rem",
            borderRadius: "0.75rem",
            border: "none",
            background: "#6C5CE7",
            boxShadow: "0 8px 18px -6px rgba(108, 92, 231, 0.55)",
            color: "#fff",
            fontFamily: "inherit",
            fontSize: "0.9rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Recarregar
        </button>
      </div>
    );
  }
}
