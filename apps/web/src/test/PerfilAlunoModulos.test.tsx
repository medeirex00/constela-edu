/**
 * Ficha do aluno × módulos contratados (SaaS): a aba "Histórico de Leituras" é do
 * Elefante Letrado e só aparece quando a rede tem o módulo de leitura. Com os dois
 * módulos, nada muda. Dados fictícios.
 */
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import PerfilAluno from "../pages/PerfilAluno";
import type { Usuario } from "../lib/types";
import { api, renderComApp, responder, screen, userEvent, usuarioFake, waitFor } from "./utils";

const ALUNO = {
  id: 10, nome: "Ana Beatriz Ficticia", turma: "3º Ano A", ano_escolar: "3º Ano",
  status: "ativo", foto_url: null, numero_chamada: 4,
};

function perfil(comLeitura: boolean) {
  return {
    aluno: ALUNO, posicao: 2,
    nota_matific: 80, nota_elefante: comLeitura ? 70 : null,
    nota_geral: comLeitura ? 75 : 80,
    ficha: { ra: "000111222" },
    calculada_em: null,
    detalhes: {
      modo_normalizacao: "auto",
      matific: { indicadores: [], nota: 80 },
      elefante: comLeitura ? { indicadores: [], questoes: null, nota: 70 } : null,
      geral: { pesos: comLeitura ? { matific: 50, elefante: 50 } : { matific: 100 }, nota: comLeitura ? 75 : 80 },
    },
  };
}

function montar(usuario: Usuario, comLeitura: boolean) {
  responder("GET", "/escolas/1/alunos/10/perfil", perfil(comLeitura));
  responder("GET", "/escolas/1/gamificacao/alunos/10", null);
  responder("GET", /\/escolas\/1\/alunos\/10\/leituras/, {
    periodo: { chave: "tudo", rotulo: "Todo o período", inicio: null, fim: null },
    resumo: { total_livros: 0, pontos: 0, tempo_total_min: 0 },
    itens: [],
  });
  renderComApp(
    <Routes>
      <Route path="/alunos/:id" element={<PerfilAluno />} />
    </Routes>,
    { rota: "/alunos/10", usuario },
  );
}

const chamouLeituras = () =>
  api.mock.calls.some(([c]) => String(c).startsWith("/escolas/1/alunos/10/leituras"));

describe("Perfil do aluno: aba do Elefante só com o módulo de leitura", () => {
  it("sem o módulo de leitura, a aba “Histórico de Leituras” não aparece", async () => {
    montar(usuarioFake({ cargo: "coordenador", modulos: ["matematica"] }), false);

    const lista = await screen.findByRole("tablist", { name: "Seções do perfil do aluno" });
    expect(lista).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Perfil" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Linha do tempo" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Evolução" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Histórico de Leituras" })).toBeNull();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(chamouLeituras()).toBe(false);
  });

  it("com os dois módulos, a aba existe e busca o histórico", async () => {
    montar(usuarioFake({ cargo: "coordenador", modulos: ["leitura", "matematica"] }), true);

    await screen.findByRole("tablist", { name: "Seções do perfil do aluno" });
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    const aba = screen.getByRole("tab", { name: "Histórico de Leituras" });
    await userEvent.click(aba);
    expect(aba).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Histórico de Leituras" })).toBeInTheDocument();
    await waitFor(() => expect(chamouLeituras()).toBe(true));
  });

  it("só com o módulo de leitura, a aba continua", async () => {
    montar(usuarioFake({ cargo: "coordenador", modulos: ["leitura"] }), true);

    await screen.findByRole("tablist", { name: "Seções do perfil do aluno" });
    expect(screen.getByRole("tab", { name: "Histórico de Leituras" })).toBeInTheDocument();
  });
});
