/**
 * Tela amigável "algo deu errado — tentar de novo", para a CRIANÇA. É
 * compartilhada por:
 *   - LimiteErro (fronteira de erro de RENDER da árvore React); e
 *   - Cena3D (aviso de PERDA DE CONTEXTO WebGL, que é um evento assíncrono e
 *     NÃO um erro de render — por isso é tratado lá, não pela fronteira).
 *
 * Sem 3D e com estilos INLINE: renderiza mesmo que o motor 3D ou uma folha de
 * estilo tenham falhado. Acessível (role="alert" + aria-live, foco no botão,
 * alvo de toque grande, alto contraste). Texto pt-BR (o app não usa i18n).
 */
import type { CSSProperties } from "react";

interface Props {
  onReiniciar: () => void;
  titulo?: string;
  detalhe?: string;
}

export function TelaReiniciar({
  onReiniciar,
  titulo = "Ops! A nave precisa reiniciar.",
  detalhe = "Não se preocupe — é só tocar no botão para voltar a brincar.",
}: Props) {
  return (
    <div role="alert" aria-live="assertive" style={estilos.tela}>
      <div style={estilos.painel}>
        <div aria-hidden="true" style={estilos.emoji}>🚀</div>
        <p style={estilos.titulo}>{titulo}</p>
        <p style={estilos.texto}>{detalhe}</p>
        <button autoFocus onClick={onReiniciar} style={estilos.botao}>
          Tentar de novo
        </button>
      </div>
    </div>
  );
}

const estilos: Record<string, CSSProperties> = {
  tela: {
    position: "fixed",
    inset: 0,
    display: "grid",
    placeItems: "center",
    padding: "24px",
    background: "radial-gradient(circle at 50% 30%, #1b2a5b 0%, #0b1020 70%)",
    color: "#ffffff",
    fontFamily: "'Baloo 2', 'Nunito', system-ui, sans-serif",
    zIndex: 9999,
  },
  painel: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    textAlign: "center",
    gap: "16px",
    maxWidth: "min(90vw, 420px)",
  },
  emoji: { fontSize: "64px", lineHeight: 1 },
  titulo: { fontSize: "26px", fontWeight: 800, margin: 0 },
  texto: { fontSize: "18px", fontWeight: 600, color: "#c7d2fe", margin: 0 },
  botao: {
    marginTop: "8px",
    minHeight: "56px",
    padding: "14px 32px",
    fontSize: "20px",
    fontWeight: 800,
    color: "#0b1020",
    background: "#38bdf8",
    border: "none",
    borderRadius: "16px",
    boxShadow: "0 6px 0 #0284c7",
    cursor: "pointer",
    touchAction: "manipulation",
  },
};
