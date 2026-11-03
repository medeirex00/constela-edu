/**
 * RELATÓRIOS E EXPORTAÇÕES (`/rede/relatorios`) — DESENHO2 §2.3.6: dois grupos simples —
 * "Documento para reuniões" (o Boletim em PDF) e "Planilhas (CSV)" (avaliações por escola,
 * Elefante e Matific por escola no período, escolas em acompanhamento e o Ranking da Rede) —,
 * cada item com o que contém, de quando são os números e o botão. O CSV do diagnóstico
 * exploratório não fica aqui (mora na área avançada). (O conteúdo dos arquivos está em
 * AnaliseRelatorios.)
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import RelatoriosRedePagina from "../pages/rede/secretaria/RelatoriosRedePagina";
import {
  admin, antes, caminhosLidos, chamadas, consulta, plataformasRede, renderTela, semCausalidade, semJargao,
  semearSecretaria,
} from "./SecretariaFixtures";
import { responder, screen, userEvent, waitFor, within } from "./utils";

const ROTA = "/rede/relatorios";

describe("Relatórios e exportações — a tela", () => {
  it("dois grupos, na ordem: o documento para reuniões e as planilhas, cada item com o que contém e de quando", async () => {
    semearSecretaria();
    const { container } = renderTela(ROTA, <RelatoriosRedePagina />);
    await waitFor(() => expect(screen.getByTestId("relatorio-acompanhamento-quando")).toHaveTextContent("Gerado em"));
    expect(screen.getByRole("heading", { level: 1, name: "Relatórios e exportações" })).toBeInTheDocument();
    const documento = screen.getByTestId("grupo-documento");
    const planilhas = screen.getByTestId("grupo-planilhas");
    expect(antes(documento, planilhas)).toBe(true);
    expect(within(documento).getAllByRole("heading", { level: 3 }).map((h) => h.textContent?.trim()))
      .toEqual(["Boletim da rede (PDF)"]);
    expect(within(planilhas).getAllByRole("heading", { level: 3 }).map((h) => h.textContent?.trim())).toEqual([
      "Avaliações por escola (CSV)", "Elefante e Matific por escola no período (CSV)", "Escolas em acompanhamento (CSV)",
      "Ranking da Rede",
    ]);
    // O Boletim e o Ranking leem o retrato das plataformas: cada parte com o SEU período (o
    // contador de livros do Elefante é vitalício — não é "o ano letivo" inteiro).
    expect(screen.getByTestId("relatorio-boletim-quando")).toHaveTextContent(
      "De quando: alunos do ano letivo corrente; livros do Elefante acumulados desde o início da conta de cada aluno; "
      + "Matific no ano letivo; calculado na hora do download.");
    expect(screen.getByTestId("relatorio-ranking-quando")).toHaveTextContent(
      "De quando: alunos do ano letivo corrente; livros do Elefante acumulados desde o início da conta de cada aluno; "
      + "Matific no ano letivo.");
    expect(screen.getByTestId("relatorio-boletim")).toHaveTextContent("Não traz as avaliações oficiais");
    expect(screen.getByTestId("relatorio-avaliacoes-quando")).toHaveTextContent("edições de 2023 a 2025");
    expect(screen.getByTestId("relatorio-plataformas-quando")).toHaveTextContent(
      "ano letivo de 2026 (01/01/2026 a 31/12/2026); série: 1º ao 5º ano; última coleta: Elefante 18/10/2026, Matific 19/10/2026");
    expect(screen.getByTestId("relatorio-acompanhamento-quando"))
      .toHaveTextContent("avaliações: a última edição oficial de cada escola (até 2025); plataformas: ano letivo de 2026.");
    // O CSV do diagnóstico exploratório mora na área avançada: aqui, só o caminho até lá.
    expect(container).not.toHaveTextContent(/Exportar diagnóstico/);
    expect(screen.getByRole("link", { name: "Análises avançadas" })).toHaveAttribute("href", "/rede/analise");
    expect(screen.getByRole("link", { name: "fontes e arquivos oficiais" })).toHaveAttribute("href", "/rede/avaliacoes");
    expect(screen.getByRole("link", { name: /Abrir o Ranking da Rede/ })).toHaveAttribute("href", "/rede/ranking");
    semCausalidade(container);
    semJargao(container);
  });

  it("lê o catálogo, o diagnóstico e as plataformas no ANO LETIVO (não o período global)", async () => {
    semearSecretaria();
    renderTela(ROTA, <RelatoriosRedePagina />, { periodo: { preset: "semana" } });
    await screen.findByRole("button", { name: /Exportar sinais \(CSV\)/ });
    await waitFor(() => expect(caminhosLidos().sort()).toEqual([
      "/redes/1/analise/diagnostico", "/redes/1/analise/indicadores", "/redes/1/analise/plataformas",
    ]));
    expect(consulta(chamadas("/redes/1/analise/diagnostico")[0]).get("periodo")).toBe("ano_letivo");
    expect(consulta(chamadas("/redes/1/analise/plataformas")[0]).get("periodo")).toBe("ano_letivo");
  });

  it("o período da planilha das plataformas fica na URL e o 'de quando' acompanha", async () => {
    semearSecretaria();
    responder("GET", "/redes/1/analise/plataformas", (c: string) => (consulta(c).get("periodo") === "bimestre_3"
      ? plataformasRede({ janela: { inicio: "2026-08-03", fim: "2026-10-09", rotulo: "3º bimestre", preset: "bimestre_3" } })
      : plataformasRede()));
    renderTela(ROTA, <RelatoriosRedePagina />);
    const cartao = await screen.findByTestId("relatorio-plataformas");
    await userEvent.selectOptions(within(cartao).getByLabelText("Período"), "bimestre_3");
    await waitFor(() => expect(screen.getByTestId("relatorio-plataformas-quando"))
      .toHaveTextContent("3º bimestre (03/08/2026 a 09/10/2026)"));
    expect(screen.getByTestId("onde")).toHaveTextContent("periodo=bimestre_3");
  });

  it("a série da planilha das plataformas vai para a leitura, a URL e o 'de quando'", async () => {
    semearSecretaria();
    renderTela(ROTA, <RelatoriosRedePagina />);
    const cartao = await screen.findByTestId("relatorio-plataformas");
    expect(within(cartao).getByLabelText("Série")).toHaveValue("");
    await userEvent.selectOptions(within(cartao).getByLabelText("Série"), "2");
    await waitFor(() => expect(chamadas("/redes/1/analise/plataformas").some((c) => consulta(c).get("serie") === "2"))
      .toBe(true));
    expect(screen.getByTestId("onde")).toHaveTextContent("serie=2");
    await waitFor(() => expect(screen.getByTestId("relatorio-plataformas-quando")).toHaveTextContent("; série: 2º ano;"));
  });

  it("admin global numa rede que o Ranking da Rede não abre: o cartão do Ranking diz qual rede ele mostra", async () => {
    semearSecretaria();
    responder("GET", "/redes", [{ id: 2, nome: "Rede Sintética Sul" }, { id: 1, nome: "Rede Sintética Norte" }]);
    renderTela(`${ROTA}?rede=1`, <RelatoriosRedePagina />, { usuario: admin });
    const ranking = await screen.findByTestId("relatorio-ranking");
    expect(within(ranking).getByTestId("aviso-outra-rede"))
      .toHaveTextContent("O Ranking da Rede abre a rede “Rede Sintética Sul”, não a escolhida aqui");
  });

  it("o admin global vê o nome da tela dele para as fontes ('importações e fontes')", async () => {
    semearSecretaria();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }]);
    renderTela(ROTA, <RelatoriosRedePagina />, { usuario: admin });
    expect(await screen.findByRole("link", { name: "importações e fontes" })).toHaveAttribute("href", "/rede/avaliacoes");
    expect(screen.queryByLabelText("Rede analisada")).toBeNull();                 // uma rede só: sem seletor
    expect(screen.getByRole("link", { name: "Análises avançadas" })).toHaveAttribute("href", "/rede/analise?rede=1");
  });

  it("rede só com o Matific: a planilha das plataformas se chama 'Matific' e não promete o Elefante", async () => {
    semearSecretaria();
    const p = plataformasRede();
    responder("GET", "/redes/1/analise/plataformas", plataformasRede({
      modulos: { elefante: false, matific: true }, rede: { ...p.rede, elefante: null },
    }));
    renderTela(ROTA, <RelatoriosRedePagina />);
    const cartao = await screen.findByTestId("relatorio-plataformas");
    await waitFor(() => expect(within(cartao).getByRole("heading", { level: 3 }))
      .toHaveTextContent("Matific por escola no período (CSV)"));
    expect(cartao).not.toHaveTextContent("Elefante");
    expect(cartao).toHaveTextContent("participação, atividades e desempenho do Matific");
  });

  it("rede só com o Matific: o 'de quando' do Boletim e do Ranking não cita os livros do Elefante", async () => {
    semearSecretaria();
    const p = plataformasRede();
    responder("GET", "/redes/1/analise/plataformas", plataformasRede({
      modulos: { elefante: false, matific: true }, rede: { ...p.rede, elefante: null },
    }));
    renderTela(ROTA, <RelatoriosRedePagina />);
    await waitFor(() => expect(screen.getByTestId("relatorio-boletim-quando")).toHaveTextContent(
      "De quando: alunos do ano letivo corrente; Matific no ano letivo; calculado na hora do download."));
    expect(screen.getByTestId("relatorio-ranking-quando"))
      .toHaveTextContent("De quando: alunos do ano letivo corrente; Matific no ano letivo.");
    expect(screen.getByTestId("relatorio-boletim-quando")).not.toHaveTextContent("Elefante");
  });

  it("rede só com o Elefante: o 'de quando' do Boletim e do Ranking diz os livros desde o início, sem o Matific", async () => {
    semearSecretaria();
    const p = plataformasRede();
    responder("GET", "/redes/1/analise/plataformas", plataformasRede({
      modulos: { elefante: true, matific: false }, rede: { ...p.rede, matific: null },
    }));
    renderTela(ROTA, <RelatoriosRedePagina />);
    await waitFor(() => expect(screen.getByTestId("relatorio-boletim-quando")).toHaveTextContent(
      "De quando: alunos do ano letivo corrente; livros do Elefante acumulados desde o início da conta de cada aluno; "
      + "calculado na hora do download."));
    expect(screen.getByTestId("relatorio-ranking-quando")).not.toHaveTextContent("Matific");
  });
});
