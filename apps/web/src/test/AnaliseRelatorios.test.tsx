/**
 * Os ARQUIVOS da rede (`pages/analise/RelatoriosRede`: os montadores dos CSV e o cartão), hoje
 * na tela Relatórios e exportações (`/rede/relatorios`): o boletim (PDF) sai pela mesma
 * `apiDownload` do Painel da Rede (`/redes/{id}/boletim`); os CSV saem por `lib/csvRanking` com
 * as mesmas respostas das telas — ausência e proteção escritas ("sem dado", "protegido"),
 * nunca 0; enquanto a leitura não chega, o botão fica desabilitado. O CSV do Diagnóstico
 * (área avançada) usa o mesmo montador, conferido aqui direto.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/csvRanking", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/csvRanking")>();
  return { ...original, baixarCsv: vi.fn() };
});

import { baixarCsv, conteudoCsv } from "../lib/csvRanking";
import { tabelaCsvDiagnostico } from "../pages/analise/RelatoriosRede";
import RelatoriosRedePagina from "../pages/rede/secretaria/RelatoriosRedePagina";
import {
  catalogo, chamadas, consulta, diagnostico, plataformasRede, renderTela, semearSecretaria,
} from "./SecretariaFixtures";
import { ApiError, apiDownload, responder, screen, userEvent, waitFor, within } from "./utils";

const ROTA = "/rede/relatorios";

const tabelaBaixada = (i = 0) => vi.mocked(baixarCsv).mock.calls[i][0];

async function exportar(nome: RegExp) {
  const botao = await screen.findByRole("button", { name: nome });
  await waitFor(() => expect(botao).toBeEnabled());
  await userEvent.click(botao);
  return tabelaBaixada();
}

beforeEach(() => vi.mocked(baixarCsv).mockClear());

describe("Arquivos da rede — boletim", () => {
  it("o boletim sai pela rota de sempre (/redes/{id}/boletim), pela apiDownload", async () => {
    semearSecretaria();
    renderTela(ROTA, <RelatoriosRedePagina />);
    await userEvent.click(await screen.findByRole("button", { name: /Baixar boletim \(PDF\)/ }));
    expect(apiDownload).toHaveBeenCalledWith("/redes/1/boletim");
  });

  it("a falha do boletim aparece no cartão dele", async () => {
    semearSecretaria();
    vi.mocked(apiDownload).mockRejectedValueOnce(new ApiError(500, "FALHA-BOLETIM"));
    renderTela(ROTA, <RelatoriosRedePagina />);
    await userEvent.click(await screen.findByRole("button", { name: /Baixar boletim \(PDF\)/ }));
    expect(await within(screen.getByTestId("relatorio-boletim")).findByText("FALHA-BOLETIM")).toBeInTheDocument();
  });

  it("enquanto as leituras não chegam, os CSV ficam desabilitados (sem arquivo pela metade); o boletim não espera", async () => {
    responder("GET", "/redes/1/analise/indicadores", catalogo());
    responder("GET", "/redes/1/analise/diagnostico", () => new Promise(() => {}));
    responder("GET", "/redes/1/analise/plataformas", () => new Promise(() => {}));
    renderTela(ROTA, <RelatoriosRedePagina />);
    expect(await screen.findByRole("button", { name: /Exportar avaliações \(CSV\)/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Exportar plataformas \(CSV\)/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Exportar sinais \(CSV\)/ })).toBeDisabled();
    expect(screen.getByTestId("relatorio-acompanhamento-quando")).toHaveTextContent("carregando");
    expect(screen.getByRole("button", { name: /Baixar boletim \(PDF\)/ })).toBeEnabled();
  });
});

describe("Arquivos da rede — planilhas", () => {
  it("Avaliações por escola (CSV): uma linha por escola e série oficial, com o rótulo do que é calculado", async () => {
    semearSecretaria();
    renderTela(ROTA, <RelatoriosRedePagina />);
    const t = await exportar(/Exportar avaliações \(CSV\)/);
    expect(t.nomeArquivo).toMatch(/^avaliacoes-por-escola_\d{4}-\d{2}-\d{2}\.csv$/);
    expect(t.cabecalho).toContain("Posição contra a rede (calculado pelo Constela)");
    expect(t.cabecalho).toContain("Situação da meta (oficial)");
    const col = (linha: unknown[], nome: string) => linha[t.cabecalho.indexOf(nome)];
    // Alfa (2 séries), Beta (2), Delta (1), Gama (sem número: uma linha que diz o porquê).
    expect(t.linhas.map((l) => l[0])).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Beta",
      "EMEF Sintética Delta", "EMEI Sintética Gama",
    ]);
    const sarespAlfa = t.linhas[0];
    expect(col(sarespAlfa, "Indicador")).toBe("SARESP");
    expect(col(sarespAlfa, "Resultado (oficial)")).toBe("219,6");
    expect(col(sarespAlfa, "Diferença escola − rede (calculado pelo Constela)")).toBe(7.2);
    expect(col(sarespAlfa, "Posição contra a rede (calculado pelo Constela)")).toBe("acima da rede");
    expect(col(sarespAlfa, "Tendência (calculado pelo Constela)")).toBe("subiu");
    const ieeAlfa = t.linhas[1];
    expect(col(ieeAlfa, "Situação da meta (oficial)")).toBe("não atingiu a meta");
    expect(col(ieeAlfa, "Por que não há posição")).toContain("o IEE só existe por escola");
    expect(col(t.linhas[3], "Média instável (poucos alunos fizeram a prova)")).toBe("sim");
    expect(t.linhas[5]).toContain("sem código INEP no cadastro");
    // As edições como TEXTO (número sairia "2.025" no arquivo: o decimal 2,025 fora do Excel pt-BR).
    expect(col(sarespAlfa, "Edição")).toBe("2025");
    expect(col(sarespAlfa, "Edição anterior")).toBe("2024");
    // O arquivo de verdade: ";" e a diferença negativa como número pt-BR (sem apóstrofo).
    const arquivo = conteudoCsv(t);
    expect(arquivo).toContain(";-14,4;");
    expect(arquivo).toContain(";2025;219,6;");
    expect(arquivo).toContain(";2024;214,0;");
    expect(arquivo).not.toMatch(/2\.02[345]/);
    // A planilha sai do fluxo principal: os motivos do servidor em língua simples, sem a sigla técnica.
    expect(arquivo).not.toMatch(/\bTPS\b|coorte|\bk\s*=/i);
  });

  it("Avaliações por escola (CSV): o IEE calculado com médias de TPS = 0 não sai como um 'não' seco", async () => {
    semearSecretaria();
    const padrao = diagnostico();
    responder("GET", "/redes/1/analise/diagnostico", diagnostico({
      // O backend: IEE com TPS = 0 vem `instavel: false` (o número oficial vale) e `tps_zero: true`.
      escolas: padrao.escolas.map((e) => (e.id !== 2 ? e : {
        ...e, oficiais: e.oficiais.map((o) => (o.indicador !== "iee" ? o : { ...o, instavel: false, tps_zero: true })),
      })),
    }));
    renderTela(ROTA, <RelatoriosRedePagina />);
    const t = await exportar(/Exportar avaliações \(CSV\)/);
    const col = (linha: unknown[], nome: string) => linha[t.cabecalho.indexOf(nome)];
    const [sarespAlfa, ieeAlfa] = t.linhas;
    expect(col(ieeAlfa, "Indicador")).toBe("IEE");
    expect(col(ieeAlfa, "Média instável (poucos alunos fizeram a prova)")).toBe("não (IEE calculado com médias instáveis)");
    expect(col(sarespAlfa, "Média instável (poucos alunos fizeram a prova)")).toBe("não");
    expect(col(t.linhas[3], "Média instável (poucos alunos fizeram a prova)")).toBe("sim");
  });

  it("Elefante e Matific por escola (CSV): protegido e sem dado escritos, nunca 0", async () => {
    semearSecretaria();
    renderTela(ROTA, <RelatoriosRedePagina />);
    const t = await exportar(/Exportar plataformas \(CSV\)/);
    expect(t.nomeArquivo).toMatch(/^plataformas-por-escola_\d{4}-\d{2}-\d{2}\.csv$/);
    expect(t.linhas.map((l) => l[0])).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEI Sintética Gama",
    ]);
    const col = (linha: unknown[], nome: string) => linha[t.cabecalho.indexOf(nome)];
    const [alfa, beta, delta, gama] = t.linhas;
    expect(gama.slice(1).every((c) => c === "protegido")).toBe(true);
    expect(col(alfa, "Matific — participação (%)")).toBe("sem dado");
    expect(col(delta, "Matific — desempenho (0–5)")).toBe("protegido");
    expect(col(delta, "Elefante — acerto nas questões (%)")).toBe("sem dado");
    expect(col(beta, "Elefante — participação (%)")).toBe(85);
    expect(col(beta, "Elefante — coleta")).toBe("coleta parcial (até 20/09/2026)");
    expect(t.linhas.flat().some((c) => c === 0)).toBe(false);
  });

  it("Elefante e Matific por escola (CSV): rede só com o Matific não tem colunas do Elefante", async () => {
    semearSecretaria();
    responder("GET", "/redes/1/analise/plataformas", plataformasRede({ modulos: { elefante: false, matific: true } }));
    renderTela(ROTA, <RelatoriosRedePagina />);
    const t = await exportar(/Exportar plataformas \(CSV\)/);
    expect(t.cabecalho.some((c) => String(c).startsWith("Elefante"))).toBe(false);
    expect(t.cabecalho).toContain("Matific — participação (%)");
  });

  it("Elefante e Matific por escola (CSV) de UMA série: a leitura leva a série e o nome do arquivo a diz", async () => {
    semearSecretaria();
    renderTela(`${ROTA}?serie=2`, <RelatoriosRedePagina />);
    const t = await exportar(/Exportar plataformas \(CSV\)/);
    expect(t.nomeArquivo).toMatch(/^plataformas-por-escola-2o-ano_\d{4}-\d{2}-\d{2}\.csv$/);
    expect(chamadas("/redes/1/analise/plataformas").every((c) => consulta(c).get("serie") === "2")).toBe(true);
  });

  it("Escolas em acompanhamento (CSV): os sinais de cada escola, com onde, tipo, natureza e referência", async () => {
    semearSecretaria();
    renderTela(ROTA, <RelatoriosRedePagina />);
    const t = await exportar(/Exportar sinais \(CSV\)/);
    expect(t.nomeArquivo).toMatch(/^escolas-em-acompanhamento_/);
    const participacaoBeta = t.linhas.find((l) => l[0] === "EMEF Sintética Beta" && l[2] === "Elefante e Matific")!;
    // O número é da plataforma; o "abaixo da rede", critério do Constela: as duas naturezas.
    expect(participacaoBeta.slice(3, 5)).toEqual(["atenção", "Plataforma + Calculado pelo Constela"]);
    expect(participacaoBeta[5]).toBe("Elefante: participação de 40% — abaixo da rede (68,3%).");
    // O sinal favorável também vai (a tela só lista os de atenção).
    expect(t.linhas.some((l) => l[0] === "EMEF Sintética Alfa" && l[3] === "favorável")).toBe(true);
    // Sem nível nem categoria exploratória.
    expect(t.cabecalho.join(" ")).not.toMatch(/Acompanhamento \(hipótese|categoria/i);
  });

  it("Diagnóstico (CSV, área avançada): o mesmo montador, uma linha por escola em ordem alfabética", () => {
    const t = tabelaCsvDiagnostico(diagnostico(), new Date(2026, 9, 20));
    expect(t.nomeArquivo).toBe("diagnostico-pedagogico-exploratorio_2026-10-20.csv");
    expect(t.linhas.map((l) => l[0])).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEI Sintética Gama",
    ]);
    expect(t.cabecalho).toContain("Acompanhamento (hipótese exploratória)");
  });
});
