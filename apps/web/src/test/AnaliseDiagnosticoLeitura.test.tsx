/**
 * A leitura PESADA do Diagnóstico exploratório (a aba padrão das Análises avançadas): o
 * diagnóstico mede as plataformas da rede inteira — 60 s de tempo limite, SEM nova tentativa
 * automática (o servidor não cancela o cálculo quando a tela desiste: repetir somaria outro
 * cálculo inteiro) e cache curto (trocar de aba e voltar não refaz a medição).
 *
 * (A evolução por bimestre, a outra leitura pesada, mora hoje na tela Elefante e Matific.)
 *
 * Números e nomes INVENTADOS (D13).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// O useApi DE VERDADE, só observado: as opções que cada leitura passa a ele.
vi.mock("../hooks/useApi", async (importOriginal) => {
  const original = await importOriginal<typeof import("../hooks/useApi")>();
  return { ...original, useApi: vi.fn(original.useApi) };
});

import { limparCacheApi, useApi } from "../hooks/useApi";
import AnaliseEducacional from "../pages/analise/AnaliseEducacional";
import type { RespostaRelacao } from "../pages/analise/tipos";
import { baseRede, diagnostico, secretaria } from "./AnaliseFixturesDiagnostico";
import { api, renderComApp, responder, responderErro, screen, userEvent } from "./utils";

const DIAGNOSTICO = "/redes/1/analise/diagnostico";

const RELACAO: RespostaRelacao = {
  calculavel: false, motivos: ["periodo_sem_sobreposicao"], textos: ["Anos diferentes (texto sintético)."],
  criterios: { metodo: "Spearman", n_minimo: 8, k_minimo_alunos: 5, exige_mesmo_ano_letivo: true,
               exige_mesma_serie: true, so_oficial: true, mesma_escala: true },
  indicador: null, metrica: null, pares: [], n: 0, coeficiente: null, ic95: null, metodologia: "Sintética.",
};

const chamadas = (caminho: string) =>
  api.mock.calls.map(([c]) => String(c)).filter((c) => c.split("?")[0] === caminho);
const opcoesDe = (caminho: string) => vi.mocked(useApi).mock.calls
  .filter(([fonte]) => typeof fonte === "string" && fonte.split("?")[0] === caminho)
  .map(([, opcoes]) => opcoes);

beforeEach(() => {
  vi.mocked(useApi).mockClear();
  limparCacheApi();
});

describe("Diagnóstico exploratório — a leitura pesada", () => {
  it("60 s de tempo limite (não os 15 s padrão), sem nova tentativa automática e com cache curto", async () => {
    responder("GET", "/redes/1/analise/indicadores", baseRede());
    responder("GET", DIAGNOSTICO, diagnostico());
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    await screen.findByTestId("tabela-diagnostico");
    const opcoes = opcoesDe(DIAGNOSTICO);
    expect(opcoes.length).toBeGreaterThan(0);
    for (const op of opcoes) {
      expect(op).toMatchObject({ timeoutMs: 60_000, tentativas: 0 });
      expect(op?.cacheMs).toBeGreaterThan(0);
    }
  });

  it("falha transitória (503): uma leitura só — o erro aparece, sem repetir o cálculo sozinho", async () => {
    responder("GET", "/redes/1/analise/indicadores", baseRede());
    responderErro("GET", DIAGNOSTICO, 503, "FALHA-DIAG");
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    expect(await screen.findByText("Não foi possível carregar o diagnóstico: FALHA-DIAG")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 400));      // a nova tentativa do padrão viria em 300 ms
    expect(chamadas(DIAGNOSTICO)).toHaveLength(1);
  });

  it("trocar de aba e voltar não refaz o diagnóstico (a mesma URL, guardada)", async () => {
    responder("GET", "/redes/1/analise/indicadores", baseRede());
    responder("GET", DIAGNOSTICO, diagnostico());
    responder("GET", "/redes/1/analise/relacao", RELACAO);
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    await screen.findByTestId("tabela-diagnostico");
    await userEvent.click(screen.getByRole("tab", { name: "Relação com as plataformas" }));
    await screen.findByTestId("relacao-nao-calculavel");
    await userEvent.click(screen.getByRole("tab", { name: "Diagnóstico exploratório" }));
    await screen.findByTestId("tabela-diagnostico");
    expect(chamadas(DIAGNOSTICO)).toHaveLength(1);
  });
});
