/**
 * Lista de alunos da TURMA — desempenho por matéria (Decisão 1 do dono,
 * 2026-10-12; plano de retirada, itens 2 e 3).
 *
 * Antes: uma coluna "Desempenho" com a nota geral e a posição na ordem única,
 * e a ordenação `ordenar=desempenho` (pela nota geral). Agora:
 *   1. uma coluna por matéria CONTRATADA, com "—" para quem não tem dado da
 *      plataforma (nunca 0,0) — e o 0,0 legítimo (tem dado, não produziu)
 *      continua aparecendo como 0,0;
 *   2. ordenação por "Nota de Leitura" / "Nota de Matemática"
 *      (`desempenho_leitura` / `desempenho_matematica`); a tela não pede mais
 *      a ordem única;
 *   3. a nota geral e a posição legadas — que a API ainda manda por contrato —
 *      não aparecem;
 *   4. as colunas seguem o contrato da ESCOLA aberta (também para o Admin
 *      Global, que tem o catálogo inteiro no /auth/me);
 *   5. `situacao_desempenho` da API: fora da classificação (turma de Fase, aluno
 *      inativo) e sem nota calculada viram "—" com o motivo; sem o campo (API
 *      anterior, que não preenchia as notas por matéria) as colunas não
 *      aparecem — nada de "sem dado" para a turma inteira.
 *
 * O fixture `aluno()` traz `situacao_desempenho: "classificado"` porque é o que
 * a API manda desde que passou a declarar a situação (mudança de contrato, não
 * afrouxamento do teste).
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import TurmaDetalhe from "../pages/TurmaDetalhe";
import type { Escola } from "../lib/types";
import {
  api, escolaComContrato, renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, waitFor,
  within,
} from "./utils";

const BASE = "/escolas/1/turmas/5";

const RESUMO = {
  turma: { id: 5, nome: "3º Ano A", ano_escolar: "3º Ano" },
  total_alunos: 3, media_geral: 61.2, media_matific: 64.5, media_elefante: 36.2,
  indicadores: { livros_unicos: 10, tempo_leitura_min: 100 },
};

/** Aluno da lista como a API manda: os campos por matéria E o legado (nota
 *  geral 85 e 1º na ordem única), que a tela tem de ignorar. */
function aluno(id: number, nome: string, porMateria: Record<string, unknown>) {
  return {
    id, nome, foto_url: null, numero_chamada: id, status: "ativo", turma: "3º Ano A",
    ano_escolar: "3º Ano", created_at: null,
    nota_geral: 85, posicao: 1,
    nota_leitura: null, nota_matematica: null, aferido_leitura: false, aferido_matematica: false,
    posicao_leitura: null, posicao_matematica: null,
    situacao_desempenho: "classificado",
    ...porMateria,
  };
}

const ALUNOS = [
  aluno(1, "Ana Duas Plataformas", {
    nota_leitura: 72.4, aferido_leitura: true, posicao_leitura: 4,
    nota_matematica: 64.5, aferido_matematica: true, posicao_matematica: 2,
  }),
  // Zero LEGÍTIMO em Leitura (tem dado, ainda não produziu) e sem Matific.
  aluno(2, "Bruno Abriu E Nao Leu", { nota_leitura: 0, aferido_leitura: true, posicao_leitura: 9 }),
  aluno(3, "Caio Sem Dado", {}),
];

const ordenarDe = (caminho: string) =>
  new URLSearchParams(caminho.split("?")[1] ?? "").get("ordenar");
const chamadasLista = () =>
  api.mock.calls.map((c) => String(c[0])).filter((p) => p.startsWith(`${BASE}/alunos?`));

function abrir(opcoes: {
  modulos?: string[]; alunos?: unknown[]; global?: boolean; escolas?: Escola[];
} = {}) {
  responder("GET", `${BASE}/resumo`, RESUMO);
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 5, nome: "3º Ano A" })]);
  responder("GET", `${BASE}/alunos`, opcoes.alunos ?? ALUNOS);
  const usuario = opcoes.global
    ? usuarioFake({ cargo: "admin", is_global: true, escola_id: null, modulos: opcoes.modulos })
    : usuarioFake({ cargo: "coordenador", modulos: opcoes.modulos });
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: "/turmas/5", usuario, escolas: opcoes.escolas },
  );
}

/** Títulos (o motivo) das células "—" de notas de uma linha. */
function motivos(nome: string): string[] {
  const tr = screen.getByRole("link", { name: nome }).closest("tr") as HTMLElement;
  return within(tr).queryAllByText("—")
    .filter((c) => c.hasAttribute("title"))
    .map((c) => c.getAttribute("title") ?? "");
}

function linha(nome: string): string[] {
  const link = screen.getByRole("link", { name: nome });
  const tr = link.closest("tr") as HTMLElement;
  return within(tr).getAllByRole("cell").map((c) => (c.textContent ?? "").trim());
}

describe("TurmaDetalhe — desempenho por matéria", () => {
  it("uma coluna por matéria: '—' para quem não tem dado, 0,0 só para o zero legítimo, sem a nota geral", async () => {
    abrir();
    expect(await screen.findByRole("link", { name: "Ana Duas Plataformas" })).toBeInTheDocument();

    expect(screen.getByRole("columnheader", { name: "Leitura" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Matemática" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Desempenho" })).not.toBeInTheDocument();

    expect(linha("Ana Duas Plataformas")).toEqual(expect.arrayContaining(["72,4", "64,5"]));
    expect(linha("Bruno Abriu E Nao Leu")).toEqual(expect.arrayContaining(["0,0", "—"]));
    const caio = linha("Caio Sem Dado");
    expect(caio.filter((c) => c === "—")).toHaveLength(2);
    expect(caio).not.toContain("0,0");

    // O legado que a API ainda manda (nota geral 85, 1º na ordem única) não aparece.
    const tabela = screen.getByRole("table");
    expect(within(tabela).queryByText("85,0")).not.toBeInTheDocument();
    expect(within(tabela).queryByText(/^\d+º$/)).not.toBeInTheDocument();
  });

  it("ordena por Nota de Leitura / Matemática e nunca pede a ordem única", async () => {
    abrir();
    const u = userEvent.setup();
    await screen.findByRole("link", { name: "Ana Duas Plataformas" });

    const seletor = screen.getByLabelText("Ordenar por");
    expect(within(seletor).getByRole("option", { name: "Nota de Leitura" })).toBeInTheDocument();
    expect(within(seletor).getByRole("option", { name: "Nota de Matemática" })).toBeInTheDocument();
    expect(within(seletor).queryByRole("option", { name: "Desempenho" })).not.toBeInTheDocument();

    await u.selectOptions(seletor, "desempenho_leitura");
    await waitFor(() => expect(chamadasLista().some((p) => ordenarDe(p) === "desempenho_leitura")).toBe(true));
    await u.selectOptions(seletor, "desempenho_matematica");
    await waitFor(() => expect(chamadasLista().some((p) => ordenarDe(p) === "desempenho_matematica")).toBe(true));
    expect(chamadasLista().some((p) => ordenarDe(p) === "desempenho")).toBe(false);
  });

  it("rede só com Leitura: sem coluna nem ordenação de Matemática", async () => {
    abrir({ modulos: ["leitura"] });
    expect(await screen.findByRole("link", { name: "Ana Duas Plataformas" })).toBeInTheDocument();

    expect(screen.getByRole("columnheader", { name: "Leitura" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Matemática" })).not.toBeInTheDocument();
    const seletor = screen.getByLabelText("Ordenar por");
    expect(within(seletor).queryByRole("option", { name: "Nota de Matemática" })).not.toBeInTheDocument();
    expect(linha("Ana Duas Plataformas")).not.toContain("64,5");
  });

  it("Admin Global numa escola cuja rede não contratou Matemática: sem coluna nem ordenação de Matemática", async () => {
    // O global tem o catálogo inteiro no /auth/me; a escola, só Leitura. A API
    // da escola não preenche Matemática — a coluna seria "—" para todo mundo.
    abrir({ global: true, modulos: ["leitura", "matematica"], escolas: [escolaComContrato(["leitura"])] });
    expect(await screen.findByRole("link", { name: "Ana Duas Plataformas" })).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.queryByRole("columnheader", { name: "Matemática" })).not.toBeInTheDocument());
    expect(screen.getByRole("columnheader", { name: "Leitura" })).toBeInTheDocument();
    const seletor = screen.getByLabelText("Ordenar por");
    expect(within(seletor).queryByRole("option", { name: "Nota de Matemática" })).not.toBeInTheDocument();
    expect(within(seletor).getByRole("option", { name: "Nota de Leitura" })).toBeInTheDocument();
  });

  it("fora da classificação e sem nota calculada: '—' com o motivo de cada um, sem nota", async () => {
    abrir({
      alunos: [
        ALUNOS[0],
        // Turma de Fase / aluno inativo: a API não manda a nota congelada.
        aluno(4, "Davi Da Fase", { situacao_desempenho: "fora_da_classificacao" }),
        // Na classificação, mas a escola ainda não foi recalculada.
        aluno(5, "Eva Chegou Agora", { situacao_desempenho: "sem_nota" }),
        ALUNOS[2],
      ],
    });
    expect(await screen.findByRole("link", { name: "Davi Da Fase" })).toBeInTheDocument();

    const fora = "Fora da classificação: turma que não concorre ou aluno inativo";
    expect(motivos("Davi Da Fase")).toEqual([fora, fora]);
    expect(motivos("Eva Chegou Agora")).toEqual(["Nota ainda não calculada", "Nota ainda não calculada"]);
    // Na classificação e sem dado da plataforma continua sendo "sem dado".
    expect(motivos("Caio Sem Dado")).toEqual(["Ainda sem dado de Leitura", "Ainda sem dado de Matemática"]);
    expect(linha("Ana Duas Plataformas")).toEqual(expect.arrayContaining(["72,4", "64,5"]));
  });

  it("API anterior (sem situacao_desempenho): as colunas por matéria não aparecem — ninguém vira 'sem dado'", async () => {
    // A API de antes não preenchia as notas por matéria: os campos chegam no
    // default vazio (aferido false, nota null) para TODOS.
    const antigos = ALUNOS.map(({ situacao_desempenho: _situacao, ...resto }) => ({
      ...resto, nota_leitura: null, nota_matematica: null, posicao_leitura: null,
      posicao_matematica: null, aferido_leitura: false, aferido_matematica: false,
    }));
    abrir({ alunos: antigos });
    expect(await screen.findByRole("link", { name: "Ana Duas Plataformas" })).toBeInTheDocument();

    expect(screen.queryByRole("columnheader", { name: "Leitura" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Matemática" })).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Ainda sem dado/)).not.toBeInTheDocument();
    // E a nota geral legada continua fora da tela.
    expect(within(screen.getByRole("table")).queryByText("85,0")).not.toBeInTheDocument();
  });
});
