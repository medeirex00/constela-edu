/**
 * Fronteira de erro do Quest (app da CRIANÇA). Captura QUALQUER erro lançado
 * SINCRONAMENTE durante o render / ciclo de vida da árvore React — exceção
 * inesperada de um componente, falha ao carregar um chunk lazy (ex.: a cena 3D
 * `Cena3D` via React.lazy num Wi-Fi ruim), erro de dados de tela — e o troca por
 * uma tela amigável e NARRADA, em vez de uma tela branca sem saída.
 *
 * LIMITE ARQUITETURAL (importante): um Error Boundary do React só pega erros de
 * RENDER. NÃO pega eventos assíncronos como a PERDA DE CONTEXTO WebGL do 3D
 * (`webglcontextlost`) — esse caso é tratado onde nasce, na `Cena3D` (listeners
 * no canvas do R3F), não aqui.
 *
 * Decisões:
 * - "Reiniciar" faz um reload COMPLETO da página (não um reset de estado que
 *   re-renderizaria e re-lançaria): recomeça do zero. Por ser disparado pela
 *   criança (clique), NÃO gera laço infinito de render.
 * - Componente de CLASSE — a API de Error Boundary do React só existe em classe.
 */
import { Component, type ReactNode } from "react";

import { narrar, tocar } from "../audio/audio";
import { TelaReiniciar } from "./TelaReiniciar";

interface Props {
  children: ReactNode;
}
interface Estado {
  erro: boolean;
}

const FALA = "Ops! A nave precisa reiniciar. Toque no botão azul para voltar a brincar!";

export class LimiteErro extends Component<Props, Estado> {
  state: Estado = { erro: false };

  static getDerivedStateFromError(): Estado {
    return { erro: true };
  }

  componentDidCatch(erro: Error, info: unknown) {
    // Registra para diagnóstico (console; ponto de plugue p/ telemetria futura).
    console.error("[Quest] erro de renderização capturado pela fronteira:", erro, info);
    // Fala com a criança não-leitora. O áudio é independente do 3D; se ele
    // mesmo tiver quebrado, ignora — a tela visual já cobre.
    try {
      tocar("erro");
      narrar(FALA);
    } catch {
      /* áudio indisponível — a tela amigável basta */
    }
  }

  reiniciar = () => window.location.reload();

  render() {
    if (this.state.erro) return <TelaReiniciar onReiniciar={this.reiniciar} />;
    return this.props.children;
  }
}
