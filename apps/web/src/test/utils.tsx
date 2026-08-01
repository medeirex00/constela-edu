/**
 * Utilitários compartilhados dos testes de tela.
 *
 * `renderComApp` monta o componente REAL dentro do `AppProvider` REAL e de um
 * MemoryRouter, já autenticado por padrão (token + escola em memória, com
 * `/auth/me` e `/escolas` respondidos pelo mock). Assim cada teste exercita o
 * fluxo de verdade — contexto, hooks, navegação — e só precisa declarar os
 * endpoints específicos da sua tela.
 */
import { type ReactElement, type ReactNode, useEffect } from "react";

import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppProvider, useApp } from "../context/AppContext";
import type { Dashboard, Escola, RankingItem, Turma, Usuario } from "../lib/types";
import { guardarToken, responder } from "../lib/__mocks__/api";

// Reexporta o Testing Library + userEvent para um import único nos testes.
export * from "@testing-library/react";
export { userEvent };
export * from "../lib/__mocks__/api";

// --- Fábricas de dados (com overrides) ---------------------------------------

export function escolaFake(over: Partial<Escola> = {}): Escola {
  return {
    id: 1,
    nome: "Escola Modelo Constela",
    cidade: "Caraguatatuba",
    estado: "SP",
    logotipo_url: null,
    ano_letivo_ativo: 2026,
    status: "ativa",
    ...over,
  };
}

export function usuarioFake(over: Partial<Usuario> = {}): Usuario {
  return {
    id: 1,
    nome: "Coordenadora Ana",
    email: "ana@escola.com",
    username: "ana",
    cargo: "coordenador",
    is_global: false,
    escola_id: 1,
    status: "ativo",
    ...over,
  };
}

export function rankingItemFake(over: Partial<RankingItem> = {}): RankingItem {
  return {
    posicao: 1,
    aluno_id: 10,
    nome: "Ana Beatriz Souza",
    turma: "3º Ano A",
    ano_escolar: "3º Ano",
    nota_matific: 80,
    nota_elefante: 90,
    nota_geral: 85,
    ...over,
  };
}

export function turmaFake(over: Partial<Turma> = {}): Turma {
  const total_alunos = over.total_alunos ?? 3;
  return {
    id: 1,
    nome: "3º Ano A",
    ano_escolar: "3º Ano",
    ano_letivo: 2026,
    professor_id: null,
    turno: "manhã",
    capacidade_maxima: 30,
    observacoes: null,
    status: "ativa",
    professor_nome: null,
    total_alunos,
    // Por padrão espelha o total_alunos; sobrescreva para simular alunos
    // arquivados / de outro ano (matrículas cruas > alunos ativos).
    total_matriculas: over.total_matriculas ?? total_alunos,
    ...over,
  };
}

export function dashboardFake(over: Partial<Dashboard> = {}): Dashboard {
  return {
    escola: escolaFake(),
    total_alunos: 42,
    total_turmas: 3,
    total_professores: 5,
    total_atividades: 128,
    total_livros: 64,
    tempo_leitura_min: 900,
    media_geral: 78.5,
    top10: [
      rankingItemFake(),
      rankingItemFake({ posicao: 2, aluno_id: 11, nome: "João Pedro Barbosa", nota_geral: 82 }),
    ],
    ...over,
  };
}

// --- Render ------------------------------------------------------------------

export interface OpcoesRender {
  /** Rota inicial do MemoryRouter. Padrão "/". */
  rota?: string;
  /** Se false, não injeta sessão (para testar Login e telas públicas). */
  autenticado?: boolean;
  /** Usuário logado (quando autenticado). */
  usuario?: Usuario;
  /** Escolas da sessão (quando autenticado). A 1ª vira a escola atual. */
  escolas?: Escola[];
  /** Fixa a escola do CONTEXTO após a sessão abrir. Útil para a Secretaria, que
   *  entra em "Toda a Rede" (escolaId nulo): ao testar uma tela por-escola dela,
   *  selecione explicitamente a escola. */
  escolaSelecionada?: number;
}

/** Aplica uma escola ao contexto assim que a sessão termina de abrir (o usuário
 *  já está carregado). Só para testes que precisam de uma escola específica. */
function AplicarEscola({ id, children }: { id: number; children: ReactNode }) {
  const { usuario, selecionarEscola } = useApp();
  useEffect(() => {
    if (usuario) selecionarEscola(id);
  }, [usuario, id, selecionarEscola]);
  return <>{children}</>;
}

/** Injeta token + escola e responde /auth/me e /escolas (sessão pronta). */
export function autenticar(usuario: Usuario = usuarioFake(), escolas: Escola[] = [escolaFake()]): void {
  guardarToken("token-de-teste");
  if (escolas[0]) localStorage.setItem("sgpe_escola", String(escolas[0].id));
  responder("GET", "/auth/me", usuario);
  responder("GET", "/escolas", escolas);
}

function Provedores({ children, rota }: { children: ReactNode; rota: string }) {
  return (
    <MemoryRouter initialEntries={[rota]}>
      <AppProvider>{children}</AppProvider>
    </MemoryRouter>
  );
}

/** Renderiza `ui` com AppProvider + Router. Autenticado por padrão. */
export function renderComApp(ui: ReactElement, opcoes: OpcoesRender = {}) {
  const { rota = "/", autenticado = true, usuario, escolas, escolaSelecionada } = opcoes;
  if (autenticado) autenticar(usuario ?? usuarioFake(), escolas ?? [escolaFake()]);
  const conteudo = escolaSelecionada != null
    ? <AplicarEscola id={escolaSelecionada}>{ui}</AplicarEscola>
    : ui;
  return render(<Provedores rota={rota}>{conteudo}</Provedores>);
}
