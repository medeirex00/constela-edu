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
 *      não aparecem.
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import TurmaDetalhe from "../pages/TurmaDetalhe";
import {
  api, renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, waitFor, within,
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

function abrir(opcoes: { modulos?: string[] } = {}) {
  responder("GET", `${BASE}/resumo`, RESUMO);
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 5, nome: "3º Ano A" })]);
  responder("GET", `${BASE}/alunos`, ALUNOS);
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: "/turmas/5", usuario: usuarioFake({ cargo: "coordenador", modulos: opcoes.modulos }) },
  );
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
});
