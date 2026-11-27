import { describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import { podeVerDemoCaragua, ROTA_DEMO_CARAGUA } from "../lib/demoCaragua";
import Login from "../pages/Login";
import DemonstracaoCaragua from "../pages/rede/secretaria/DemonstracaoCaragua";
import type { DadosDemoCaragua } from "../pages/rede/secretaria/dadosDemoCaragua";
import { renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

vi.mock("../pages/rede/secretaria/MapaDemoCaragua", () => ({
  default: ({ escolherRegiao, escolherEscola }: {
    escolherRegiao: (id: "norte") => void;
    escolherEscola: (id: string) => void;
  }) => (
    <div>
      <button type="button" onClick={() => escolherRegiao("norte")}>Clicar no mapa da região</button>
      <button type="button" onClick={() => escolherEscola("a")}>Clicar no ponto da escola</button>
    </div>
  ),
}));

const usuarioDemo = usuarioFake({ cargo: "admin", rede_id: 27, escola_id: null, username: " @IFSP2026SEC " });
const dados: DadosDemoCaragua = {
  regioes: [
    { id: "norte", nome: "Norte", contexto: "Cenário fictício do Norte." },
    { id: "centro", nome: "Centro", contexto: "Cenário fictício do Centro." },
  ],
  escolas: [
    { id: "a", regiao: "norte", nome: "Escola Demo Alfa", latitude: -23.54, longitude: -45.34, nota: 40,
      com_dados: 19, matriculados: 20 },
    { id: "b", regiao: "norte", nome: "Escola Demo Beta", latitude: -23.55, longitude: -45.33, nota: null,
      com_dados: 0, matriculados: 30 },
    { id: "c", regiao: "centro", nome: "Escola Demo Gama", latitude: -23.62, longitude: -45.4, nota: 81,
      com_dados: 17, matriculados: 20 },
  ],
  avaliacoes: [
    { escola_id: "a", avaliacao: "SARESP", edicao: 2025, serie: "5º ano", disciplina: "Português", resultado: 193.5 },
    { escola_id: "a", avaliacao: "SARESP", edicao: 2025, serie: "5º ano", disciplina: "Matemática", resultado: 201.3 },
    { escola_id: "a", avaliacao: "SARESP", edicao: 2024, serie: "2º ano", disciplina: "Português", resultado: 177.1 },
    { escola_id: "a", avaliacao: "SAEB", edicao: 2023, serie: "5º ano", disciplina: "Matemática", resultado: 212.1 },
  ],
};

function renderDemo() {
  responder("GET", "/redes/27/demonstracao-caragua", dados);
  return renderComApp(<DemonstracaoCaragua />, { usuario: usuarioDemo, escolas: [] });
}

describe("Demonstração Caraguatatuba", () => {
  it("usa apenas a conta de Secretaria da demonstração, com a normalização do login", () => {
    expect(podeVerDemoCaragua(usuarioDemo)).toBe(true);
    expect(podeVerDemoCaragua(null)).toBe(false);
    expect(podeVerDemoCaragua({ ...usuarioDemo, is_global: true })).toBe(false);
    expect(podeVerDemoCaragua({ ...usuarioDemo, rede_id: null })).toBe(false);
    expect(podeVerDemoCaragua({ ...usuarioDemo, escola_id: 1 })).toBe(false);
    expect(podeVerDemoCaragua({ ...usuarioDemo, username: "secretaria-outro" })).toBe(false);
  });

  it.each<[typeof usuarioDemo, string]>([
    [usuarioDemo, "Mapa da demonstração"],
    [{ ...usuarioDemo, username: "secretaria-outro" }, "Panorama"],
  ])("abre o destino esperado após login (%#)", async (usuario, destino) => {
    renderComApp(
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path={ROTA_DEMO_CARAGUA} element={<h1>Mapa da demonstração</h1>} />
        <Route path="/" element={<h1>Panorama</h1>} />
      </Routes>,
      { rota: "/login", usuario, escolas: [] },
    );
    expect(await screen.findByRole("heading", { name: destino })).toBeVisible();
  });

  it("mostra o resumo da região sem contar nota ausente como zero e compara escolas de regiões diferentes", async () => {
    renderDemo();
    const usuario = userEvent.setup();
    await usuario.click(await screen.findByRole("button", { name: "Clicar no mapa da região" }));
    expect(screen.getByRole("heading", { name: "Norte" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Escolas fictícias (2)" })).toBeVisible();
    expect(screen.getByText("38%")).toBeVisible();
    expect(screen.getByText("19 de 50 alunos com dados")).toBeVisible();
    expect(screen.getByText("Cenário fictício do Norte.")).toBeVisible();
    expect(screen.getByText("40")).toBeVisible();

    await usuario.click(screen.getByRole("button", { name: "Clicar no ponto da escola" }));
    expect(screen.getByRole("heading", { name: "Escola Demo Alfa" })).toBeVisible();
    expect(screen.getByText("95%")).toBeVisible();
    await usuario.click(screen.getByRole("checkbox", { name: "Comparar Escola Demo Alfa" }));
    await usuario.click(screen.getByRole("button", { name: "Centro", exact: true }));
    await usuario.click(screen.getByRole("checkbox", { name: "Comparar Escola Demo Gama" }));

    const comparacao = screen.getByRole("table", { name: "Comparação de escolas fictícias" });
    expect(within(comparacao).getByRole("row", { name: /Escola Demo Alfa/ })).toHaveTextContent("95%");
    expect(within(comparacao).getByRole("row", { name: /Escola Demo Gama/ })).toHaveTextContent("81");
    expect(within(comparacao).queryByRole("row", { name: /Escola Demo Beta/ })).not.toBeInTheDocument();
  });

  it("troca os recortes válidos sem misturar escalas ou exibir resultados de outra edição", async () => {
    renderDemo();
    const usuario = userEvent.setup();
    const saresp = await screen.findByRole("table", { name: "Resultados fictícios de SARESP" });
    expect(within(saresp).getByText("193,5")).toBeVisible();
    await usuario.selectOptions(screen.getByRole("combobox", { name: "Disciplina" }), "Matemática");
    expect(within(saresp).getByText("201,3")).toBeVisible();
    await usuario.selectOptions(screen.getByRole("combobox", { name: "Edição" }), "2024");
    expect(screen.getByRole("combobox", { name: "Série" })).toHaveValue("2º ano");
    expect(within(saresp).getByText("177,1")).toBeVisible();
    await usuario.selectOptions(screen.getByRole("combobox", { name: "Avaliação" }), "SAEB");
    const saeb = screen.getByRole("table", { name: "Resultados fictícios de SAEB" });
    expect(screen.getByRole("combobox", { name: "Edição" })).toHaveValue("2023");
    expect(within(saeb).getByText("212,1")).toBeVisible();
    expect(within(saeb).queryByText("177,1")).not.toBeInTheDocument();
  });
});
