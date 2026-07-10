import { Component, type ErrorInfo, type ReactNode } from "react";

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
  }

  render(): ReactNode {
    if (!this.state.erro) return this.props.children;
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
          fontFamily: "Inter, system-ui, sans-serif",
          color: "#1B2A4A",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700 }}>Algo deu errado</h1>
        <p style={{ maxWidth: "28rem", color: "#475569" }}>
          Tivemos um problema ao mostrar esta tela. Recarregue e tente de novo —
          seus dados estão salvos.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{
            marginTop: "0.5rem",
            padding: "0.6rem 1.25rem",
            borderRadius: "0.5rem",
            border: "none",
            background: "#1B2A4A",
            color: "#fff",
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
