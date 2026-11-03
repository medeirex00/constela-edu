/**
 * Os blocos reutilizados das PLATAFORMAS: (a) a evolução no ano letivo por bimestre
 * (`EvolucaoPlataformas`), hoje na tela Elefante e Matific (`/rede/plataformas`, com o recorte
 * `?escola=&serie=` só dela) — o bimestre EM ANDAMENTO marcado, sem dado = texto (nunca 0) — e
 * (b) as escolas no período (`TabelaEscolasNoPeriodo`), hoje a lista da tela Escolas
 * (`/rede/escolas`), em ordem alfabética, com a escola de poucos alunos como "protegido" e a
 * situação da coleta de cada uma. A evolução SÓ da escola (a da ficha) também está aqui: a célula
 * sem número diz só "sem dado"/"protegido", o porquê vai UMA vez para a nota abaixo da tabela, e a
 * escola sem número nenhum vira uma frase só (a ficha inteira está em FichaEscolaRede).
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import EvolucaoPlataformas from "../pages/analise/EvolucaoPlataformas";
import CompararEscolas from "../pages/rede/secretaria/CompararEscolas";
import PlataformasRedePagina from "../pages/rede/secretaria/PlataformasRedePagina";
import { TEXTO_SUPRESSAO, evolucao } from "./AnaliseFixturesDiagnostico";
import {
  TEXTO_SERIES_SUPRIMIDAS, blocoSemNumero, evolucaoDaEscola, evolucaoSeriesSuprimidas,
} from "./EscolasRedeFixtures";
import {
  catalogo, chamadas, consulta, painelRede, plataformasRede, renderTela, secretaria,
} from "./SecretariaFixtures";
import { renderComApp, responder, responderErro, screen, userEvent, waitFor, within } from "./utils";

function semear(evo = evolucao()) {
  responder("GET", "/redes/1/analise/indicadores", catalogo());
  responder("GET", "/redes/1/analise/plataformas", plataformasRede());
  responder("GET", "/redes/1/analise/plataformas/evolucao", evo);
  responder("GET", "/redes/1/dashboard", painelRede());
}

const telaPlataformas = (consultaUrl = "") =>
  renderTela(`/rede/plataformas${consultaUrl}`, <PlataformasRedePagina />);

describe("Evolução por bimestre (tela Elefante e Matific)", () => {
  it("o gráfico da participação e a tabela da rede; o bimestre em andamento aparece marcado", async () => {
    semear();
    telaPlataformas();
    const tabela = await screen.findByTestId("tabela-evolucao-rede");
    const linhas = within(tabela).getAllByRole("row").slice(1);
    expect(linhas.map((l) => within(l).getByRole("rowheader").textContent)).toEqual([
      "1º bimestre02/02 a 17/04", "2º bimestre20/04 a 03/07", "3º bimestre03/08 a 09/10",
      "4º bimestreem andamento13/10 a 18/12",
    ]);
    expect(linhas[0]).toHaveTextContent(/61,2%.*1,4.*38,5.*70,4%.*8,25.*Elefante 3 · Matific 3/);
    expect(linhas[3]).toHaveAttribute("data-em-andamento", "true");
    expect(within(linhas[3]).getByText("em andamento")).toBeInTheDocument();
    // O gráfico responde UMA pergunta (a participação) e diz que o 4º ainda não terminou.
    const img = within(screen.getByTestId("grafico-evolucao")).getByRole("img");
    // No texto do gráfico as datas aparecem UMA vez (o rótulo do backend, que já as traz).
    expect(img).toHaveAttribute("aria-label", expect.stringContaining("Elefante — participação: 1º bimestre (02/02 a 17/04) 61,2%"));
    expect(img).toHaveAttribute("aria-label", expect.stringContaining("O 4º bimestre (13/10 a 18/12) está em andamento"));
    expect(screen.getByTestId("nota-em-andamento")).toHaveTextContent("4º bimestre em andamento (até 18/12)");
    expect(screen.getByTestId("nota-em-andamento")).not.toHaveTextContent("13/10");
    expect(screen.getByTestId("nota-em-andamento")).toHaveTextContent("não leia a diferença como queda");
  });

  it("sem coleta num bimestre é 'sem dado' — nunca 0 — e vira lacuna na linha", async () => {
    semear();
    telaPlataformas();
    const tabela = await screen.findByTestId("tabela-evolucao-rede");
    const segundo = within(tabela).getAllByRole("row")[2];
    expect(within(segundo).getAllByText("sem dado")).toHaveLength(2);       // participação e atividades do Matific
    expect(segundo).not.toHaveTextContent(/\b0([,.]0+)?%/);
    expect(segundo).toHaveTextContent("Elefante 3 · Matific 0");             // a contagem de escolas é número de verdade
    const img = within(screen.getByTestId("grafico-evolucao")).getByRole("img");
    expect(img).toHaveAttribute("aria-label", expect.stringContaining("2º bimestre (20/04 a 03/07) sem dado"));
    // A linha do Matific quebra no 2º bimestre: o 1º fica sozinho (trecho de 1 ponto) e o 3º–4º
    // num trecho de 2 — nunca um trecho só ligando o 1º ao 3º por cima da falta.
    const matific = [...img.querySelectorAll("polyline")].filter((l) => l.getAttribute("stroke") === "#0D9488");
    expect(matific.map((l) => l.getAttribute("points")?.trim().split(/\s+/).length)).toEqual([1, 2]);
  });

  it("a série do recorte vai para a evolução; o período não (cada ponto é um bimestre)", async () => {
    semear();
    telaPlataformas("?serie=5");
    await screen.findByTestId("tabela-evolucao-rede");
    const q = consulta(chamadas("/redes/1/analise/plataformas/evolucao")[0]);
    expect(q.get("serie")).toBe("5");
    expect(q.has("periodo")).toBe(false);
    expect(screen.getByTestId("filtros-evolucao")).toHaveTextContent("O período não se aplica");
    expect(screen.getByTestId("filtros-evolucao")).toHaveTextContent("série (5º ano)");
  });

  it("com uma escola no recorte, a evolução dela aparece à parte, com o porquê de cada falta", async () => {
    semear();
    telaPlataformas("?escola=3");
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    // Uma leitura só, já com a escola (a evolução espera o catálogo confirmar que ela é da rede).
    expect(chamadas("/redes/1/analise/plataformas/evolucao")).toHaveLength(1);
    expect(consulta(chamadas("/redes/1/analise/plataformas/evolucao")[0]).get("escola_id")).toBe("3");
    // A tela da rede mostra a rede ao lado: ela é medida (só a ficha pede só a escola).
    expect(consulta(chamadas("/redes/1/analise/plataformas/evolucao")[0]).get("so_escola")).toBeNull();
    const primeiro = within(escola).getAllByRole("row")[1];
    expect(within(primeiro).getAllByText("sem dado (sem coleta no período)")).toHaveLength(2);
    expect(primeiro).toHaveTextContent("50%");
    expect(screen.getByTestId("evolucao-escola")).toHaveTextContent("EMEF Sintética Beta, por bimestre");
    // O modo da REDE não muda: o porquê continua na célula, sem a nota da ficha.
    expect(screen.queryByTestId("motivos-evolucao-escola")).toBeNull();
  });

  it("escola de outra rede no link não entra na leitura", async () => {
    semear();
    telaPlataformas("?escola=999");
    await screen.findByTestId("tabela-evolucao-rede");
    expect(chamadas("/redes/1/analise/plataformas/evolucao").every((c) => !consulta(c).has("escola_id"))).toBe(true);
    expect(screen.queryByTestId("tabela-evolucao-escola")).toBeNull();
  });

  it("escola com poucos alunos e média escondida em complemento: 'protegido' por extenso, nunca 0", async () => {
    const padrao = evolucao();
    const PROTEGIDA = "poucos alunos neste recorte (texto sintético)";
    semear(evolucao({
      // O formato do serviço: blocos com o motivo, a escola marcada como suprimida.
      modulos: { elefante: true, matific: false },
      bimestres: padrao.bimestres.map((b) => ({
        ...b,
        rede: { ...b.rede, elefante: b.numero === 1
          ? { participacao_pct: 61.2, livros_por_aluno: null, minutos_por_aluno: 38.5,
              metricas_protegidas: ["livros_por_aluno"], texto_sem_dado: null }
          : b.rede.elefante },
        escolas: [{ id: 3, nome: "EMEF Sintética Beta", cobertura: null, suprimido: true,
                    elefante: { participacao_pct: null, livros_por_aluno: null, motivo_sem_dado: "suprimido",
                                texto_sem_dado: PROTEGIDA },
                    matific: null }],
      })),
    }));
    telaPlataformas("?escola=3");
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    const primeiro = within(escola).getAllByRole("row")[1];
    expect(within(primeiro).getAllByText("protegido")).toHaveLength(2);
    expect(within(primeiro).getAllByText("protegido")[0]).toHaveAttribute("title", PROTEGIDA);
    // A rede: a média escondida em complemento sai "protegido"; o Matific não contratado some.
    const rede = screen.getByTestId("tabela-evolucao-rede");
    expect(within(rede).getAllByRole("row")[1]).toHaveTextContent(/61,2%.*protegido.*38,5/);
    expect(within(rede).queryByText("Matific: participação")).not.toBeInTheDocument();
  });

  it("as datas do bimestre aparecem uma vez só em cada linha (o rótulo do backend já as traz)", async () => {
    const padrao = evolucao();
    semear(evolucao({
      bimestres: padrao.bimestres.map((b) => (b.numero !== 1 ? b
        // Ano sem calendário oficial: o rótulo não traz datas, traz o aviso — que fica.
        : { ...b, rotulo: "1º bimestre (aproximado: sem calendário oficial de 2026)" })),
    }));
    telaPlataformas("?escola=2");
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    const rede = screen.getByTestId("tabela-evolucao-rede");
    for (const tabela of [rede, escola]) {
      const cabecalhos = within(tabela).getAllByRole("rowheader").map((r) => r.textContent ?? "");
      expect(cabecalhos[0]).toBe("1º bimestre (aproximado: sem calendário oficial de 2026)02/02 a 17/04");
      expect(cabecalhos[1]).toBe("2º bimestre20/04 a 03/07");
      expect(cabecalhos[3]).toBe("4º bimestreem andamento13/10 a 18/12");
      expect(cabecalhos.every((t) => (t.match(/\d{2}\/\d{2} a \d{2}\/\d{2}/g) ?? []).length === 1)).toBe(true);
    }
  });

  it("rede protegida (série com grupo pequeno): 'Escolas com dado' diz 'protegido', nunca o 0 do serviço", async () => {
    const padrao = evolucao();
    const protegida = { motivo_sem_dado: "suprimido", texto_sem_dado: "poucos alunos (texto sintético)" };
    semear(evolucao({
      bimestres: padrao.bimestres.map((b) => (b.numero !== 1 ? b : {
        ...b,
        // O formato do serviço com a rede suprimida: blocos sem número e a contagem 0 (não null).
        rede: { suprimido: true, escolas_com_dado: { elefante: 0, matific: 0 }, escolas_parciais: { elefante: 0, matific: 0 },
                elefante: { participacao_pct: null, livros_por_aluno: null, minutos_por_aluno: null, ...protegida },
                matific: { participacao_pct: null, atividades_por_aluno: null, ...protegida } },
      })),
    }));
    telaPlataformas("?serie=1");
    const tabela = await screen.findByTestId("tabela-evolucao-rede");
    const celulas = within(within(tabela).getAllByRole("row")[1]).getAllByRole("cell");
    // Elefante (3), Matific (2), escolas com dado, coleta parcial (esta conta as escolas VISÍVEIS
    // com a coleta parada — não é suprimida pelo serviço, e o 0 dela é de verdade).
    expect(celulas[5]).toHaveTextContent(/^protegido/);
    expect(celulas[5]).not.toHaveTextContent(/\d/);
    // Os outros bimestres (rede visível) continuam com a contagem de verdade.
    expect(within(tabela).getAllByRole("row")[2]).toHaveTextContent("Elefante 3 · Matific 0");
  });

  it("escola com a coleta parada no meio do bimestre: o número leva a marca 'coleta parcial' (não parece queda)", async () => {
    const padrao = evolucao();
    semear(evolucao({
      bimestres: padrao.bimestres.map((b) => ({
        ...b,
        escolas: b.escolas.map((e) => {
          if (e.id !== 2) return e;
          // O formato do serviço: o número VEM, com `coleta_parcial` e sem motivo de falta; a
          // cobertura da escola diz "coleta_parcial" naquela plataforma.
          if (b.numero === 3) {
            return { ...e, cobertura: { elefante: "ok", matific: "coleta_parcial" },
                     matific: { participacao_pct: 41, atividades_por_aluno: 4.1, coleta_parcial: true, motivo_sem_dado: null } };
          }
          // Com a data, quando o serviço a mandar (`coberto_ate`).
          if (b.numero === 2) {
            return { ...e, cobertura: { elefante: "coleta_parcial", matific: "ok" },
                     elefante: { participacao_pct: 60, livros_por_aluno: 1.25, coleta_parcial: true,
                                 coberto_ate: "2026-05-29" } };
          }
          return e;
        }),
      })),
    }));
    telaPlataformas("?escola=2");
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    const linhas = within(escola).getAllByRole("row");
    // 3º bimestre: as duas células do Matific marcadas (sem data: o serviço ainda não manda).
    const celulas = within(linhas[3]).getAllByRole("cell");
    expect(celulas[2]).toHaveTextContent("41%coleta parcial");
    expect(celulas[3]).toHaveTextContent("4,1coleta parcial");
    expect(within(celulas[0]).queryByText(/coleta parcial/)).toBeNull();     // o Elefante em dia não leva marca
    // 2º bimestre: a marca com a data.
    expect(within(linhas[2]).getAllByText("coleta parcial (até 29/05)")).toHaveLength(2);
    // O 1º bimestre, completo, sem marca nenhuma.
    expect(linhas[1]).not.toHaveTextContent("coleta parcial");
    expect(screen.getByTestId("legenda-evolucao")).toHaveTextContent("vale só até a parada da coleta");
  });

  it("antes do 1º bimestre: diz que ainda não há evolução", async () => {
    semear(evolucao({ bimestres: [] }));
    telaPlataformas();
    expect(await screen.findByTestId("evolucao-vazia")).toHaveTextContent("Nenhum bimestre do ano letivo começou");
  });

  it("se a evolução falha, o resto da tela continua", async () => {
    responder("GET", "/redes/1/analise/indicadores", catalogo());
    responder("GET", "/redes/1/analise/plataformas", plataformasRede());
    responder("GET", "/redes/1/dashboard", painelRede());
    responderErro("GET", "/redes/1/analise/plataformas/evolucao", 403, "FALHA-EVO");
    telaPlataformas();
    expect(await screen.findByText("Não foi possível carregar a evolução por bimestre: FALHA-EVO")).toBeInTheDocument();
    expect(await screen.findByTestId("plataforma-elefante")).toBeInTheDocument();
    expect(await screen.findByTestId("totais-gerais")).toBeInTheDocument();
  });

  it("as limitações da evolução ficam recolhidas", async () => {
    semear();
    telaPlataformas();
    const bloco = await screen.findByTestId("limitacoes-evolucao");
    const botao = within(bloco).getByRole("button");
    expect(botao).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(botao);
    expect(bloco).toHaveTextContent("O bimestre em andamento ainda não terminou");
  });
});

describe("Evolução SÓ da escola (o modo da ficha da escola)", () => {
  const ficha = (escolaId: number, nome: string, opcoes: { modulos?: { elefante: boolean; matific: boolean } } = {}) =>
    renderComApp(<EvolucaoPlataformas redeId={1} serie={null} escolaId={escolaId} soEscola nomeEscola={nome}
                                      modulos={opcoes.modulos} />, { usuario: secretaria });
  /** Quantas vezes o texto aparece (o porquê sai UMA vez, não em cada célula). */
  const vezes = (el: HTMLElement, texto: string) => (el.textContent ?? "").split(texto).length - 1;

  it("sem a tabela nem o gráfico da rede: o gráfico e a tabela da escola; a falta curta e o porquê uma vez, abaixo", async () => {
    semear();
    ficha(3, "EMEF Sintética Beta");
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    expect(screen.queryByTestId("tabela-evolucao-rede")).toBeNull();
    expect(consulta(chamadas("/redes/1/analise/plataformas/evolucao")[0]).get("escola_id")).toBe("3");
    expect(consulta(chamadas("/redes/1/analise/plataformas/evolucao")[0]).get("so_escola")).toBe("true");
    // Beta: sem coleta do Elefante nos 4 bimestres; o Matific com número. A célula diz só "sem dado"
    // (o porquê na dica); a nota abaixo da tabela diz o porquê UMA vez, com onde ele vale.
    const primeiro = within(escola).getAllByRole("row")[1];
    expect(within(primeiro).getAllByText("sem dado")).toHaveLength(2);
    expect(within(primeiro).getAllByText("sem dado")[0]).toHaveAttribute("title", "sem coleta no período");
    expect(escola).not.toHaveTextContent("sem coleta no período");
    expect(primeiro).toHaveTextContent("50%");
    const motivos = screen.getByTestId("motivos-evolucao-escola");
    expect(motivos).toHaveTextContent("Por que falta número: Elefante, todos os bimestres — sem dado: sem coleta no período.");
    expect(vezes(screen.getByTestId("evolucao-escola"), "sem coleta no período")).toBe(1);
    expect(screen.getByTestId("legenda-evolucao")).toHaveTextContent("“Sem dado” e “protegido” não são zero");
    const grafico = screen.getByTestId("grafico-evolucao");
    expect(grafico).toHaveTextContent("Participação na escola, por bimestre");
    expect(within(grafico).getByRole("img")).toHaveAttribute("aria-label", expect.stringContaining("Matific — participação: 1º bimestre (02/02 a 17/04) 50%"));
    expect(screen.getByTestId("filtros-evolucao")).toHaveTextContent("Vale aqui: a escola e a série (1º ao 5º ano).");
    expect(screen.getByTestId("filtros-evolucao")).not.toHaveTextContent("abaixo da rede");
  });

  it("bimestre de coleta parcial: o número fica na tabela (marcado) e sai do gráfico, com a nota", async () => {
    const padrao = evolucao();
    semear(evolucao({
      bimestres: padrao.bimestres.map((b) => ({
        ...b,
        escolas: [{ id: 2, nome: "EMEF Sintética Alfa", cobertura: { elefante: "ok", matific: "ok" },
                    elefante: { participacao_pct: b.numero === 2 ? 20 : 60, livros_por_aluno: 1.25,
                                coleta_parcial: b.numero === 2, coberto_ate: b.numero === 2 ? "2026-05-30" : null },
                    matific: null }],
      })),
    }));
    renderComApp(<EvolucaoPlataformas redeId={1} serie={null} escolaId={2} soEscola nomeEscola="EMEF Sintética Alfa"
                                      modulos={{ elefante: true, matific: false }} />, { usuario: secretaria });
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    const segundo = within(escola).getAllByRole("row")[2];
    expect(segundo).toHaveTextContent("20%");
    expect(segundo).toHaveTextContent("coleta parcial (até 30/05)");
    const img = within(screen.getByTestId("grafico-evolucao")).getByRole("img");
    expect(img).toHaveAttribute("aria-label", expect.stringContaining("2º bimestre (20/04 a 03/07) sem dado"));
    expect(screen.getByTestId("legenda-evolucao")).toHaveTextContent("o bimestre com a coleta parcial fica de fora");
  });

  it("escola sem número em NENHUMA célula (todas as séries pequenas): uma frase só, com o motivo uma vez — sem a tabela", async () => {
    semear(evolucaoSeriesSuprimidas(4));
    const { container } = ficha(4, "EMEI Sintética Gama");
    const frase = await screen.findByTestId("evolucao-escola-sem-numero");
    expect(frase).toHaveTextContent(
      `Nenhum número desta escola do 1º ao 4º bimestre do ano letivo de 2026 — protegido: ${TEXTO_SERIES_SUPRIMIDAS}.`);
    expect(screen.getByTestId("evolucao-escola")).toContainElement(frase);
    // Nada da tabela repetindo a frase em cada célula, nem gráfico vazio, nem nota/legenda da tabela.
    expect(screen.queryByTestId("tabela-evolucao-escola")).toBeNull();
    expect(screen.queryByTestId("grafico-evolucao")).toBeNull();
    expect(screen.queryByTestId("motivos-evolucao-escola")).toBeNull();
    expect(screen.queryByTestId("legenda-evolucao")).toBeNull();
    expect(vezes(container, TEXTO_SERIES_SUPRIMIDAS)).toBe(1);
    expect(container).not.toHaveTextContent(/(^|\D)0([,.]0+)?%/);
    // O que vale para a leitura e as limitações continuam.
    expect(screen.getByTestId("filtros-evolucao")).toHaveTextContent("Vale aqui: a escola e a série (1º ao 5º ano).");
    expect(screen.getByTestId("limitacoes-evolucao")).toBeInTheDocument();
  });

  it("sem número nenhum, com motivos diferentes por plataforma: a frase e um motivo por linha, sem repetir", async () => {
    semear(evolucaoDaEscola(2, () => ({
      cobertura: { elefante: "sem_coleta", matific: "ok" },
      elefante: blocoSemNumero("sem_coleta", "a escola não tem nenhuma coleta desta plataforma (sintético)"),
      matific: blocoSemNumero("poucos_alunos_medidos", "menos de 5 alunos com dado desta plataforma (sintético)"),
    })));
    ficha(2, "EMEF Sintética Alfa");
    const frase = await screen.findByTestId("evolucao-escola-sem-numero");
    expect(frase).toHaveTextContent("Nenhum número desta escola do 1º ao 4º bimestre do ano letivo de 2026:");
    expect(within(frase).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Elefante — sem dado: sem coleta.",
      "Matific — protegido: menos de 5 alunos com dado desta plataforma (sintético).",
    ]);
    expect(screen.queryByTestId("tabela-evolucao-escola")).toBeNull();
  });

  it("só algumas células sem número: a célula diz o curto e os motivos iguais vão juntos, uma vez, na nota", async () => {
    const SEM_CONTA = "nenhum aluno deste recorte tem conta nesta plataforma (sintético)";
    const PROTEGIDA = "poucos alunos neste recorte (sintético)";
    semear(evolucaoDaEscola(2, (n) => ({
      // O Elefante sem conta no 1º e no 2º bimestre (o mesmo motivo) e com número depois.
      elefante: n <= 2 ? blocoSemNumero("sem_conta", SEM_CONTA)
        : { participacao_pct: 60, livros_por_aluno: 1.5, motivo_sem_dado: null, texto_sem_dado: null },
      // O Matific com número; no 3º, a média de atividades escondida em complemento (protegido).
      matific: n === 3
        ? { participacao_pct: 70, atividades_por_aluno: null, metricas_protegidas: ["atividades_por_aluno"],
            motivo_sem_dado: null, texto_sem_dado: PROTEGIDA }
        : { participacao_pct: 72, atividades_por_aluno: 6.5, motivo_sem_dado: null, texto_sem_dado: null },
    })));
    ficha(2, "EMEF Sintética Alfa");
    const tabela = await screen.findByTestId("tabela-evolucao-escola");
    const linhas = within(tabela).getAllByRole("row");
    // Cada célula sem número: só a palavra (o porquê na dica) — nunca 0, nunca a frase longa.
    for (const linha of [linhas[1], linhas[2]]) {
      const celulas = within(linha).getAllByRole("cell");
      expect(celulas[0]).toHaveTextContent(/^sem dado$/);
      expect(celulas[1]).toHaveTextContent(/^sem dado$/);
      expect(within(celulas[0]).getByText("sem dado")).toHaveAttribute("title", SEM_CONTA);
    }
    const terceiro = within(linhas[3]).getAllByRole("cell");
    expect(terceiro[2]).toHaveTextContent("70%");
    expect(terceiro[3]).toHaveTextContent(/^protegido$/);
    expect(tabela).not.toHaveTextContent(SEM_CONTA);
    expect(tabela).not.toHaveTextContent(PROTEGIDA);
    // A nota: os motivos iguais juntos (o Elefante nos dois bimestres), cada um UMA vez.
    const motivos = screen.getByTestId("motivos-evolucao-escola");
    expect(motivos).toHaveTextContent("Por que faltam números:");
    expect(within(motivos).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      `Elefante, 1º e 2º bimestres — sem dado: ${SEM_CONTA}.`,
      `Matific, 3º bimestre — protegido: ${PROTEGIDA}.`,
    ]);
    expect(vezes(screen.getByTestId("evolucao-escola"), SEM_CONTA)).toBe(1);
  });

  it("o modo da REDE (a tela Elefante e Matific, com a escola no filtro) não muda: o porquê continua na célula", async () => {
    semear(evolucaoSeriesSuprimidas(3));
    telaPlataformas("?escola=3");
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    const primeiro = within(escola).getAllByRole("row")[1];
    expect(within(primeiro).getAllByText(`sem dado (${TEXTO_SERIES_SUPRIMIDAS})`)).toHaveLength(4);
    expect(screen.queryByTestId("evolucao-escola-sem-numero")).toBeNull();
    expect(screen.queryByTestId("motivos-evolucao-escola")).toBeNull();
  });
});

describe("Escolas no período (tela Escolas)", () => {
  const abrir = () => renderTela("/rede/escolas", <CompararEscolas />);

  it("todas as escolas, em ordem alfabética, com as métricas das duas plataformas e a coleta", async () => {
    semear();
    abrir();
    const tabela = await screen.findByTestId("tabela-escolas-periodo");
    expect(within(tabela).getAllByRole("rowheader").map((r) => r.textContent)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEI Sintética Gama",
    ]);
    const beta = screen.getByTestId("escola-periodo-3");
    expect(beta).toHaveTextContent(/85%.*3,25.*45,5.*72,5%.*coleta parcial \(até 20\/09\/2026\).*75%.*14,25.*2,6.*coleta em dia/);
    expect(screen.getByTestId("legenda-escolas-periodo")).toHaveTextContent("não é ranking");
    // Todas as escolas: a leitura nunca leva escola_id.
    await waitFor(() => expect(chamadas("/redes/1/analise/plataformas").length).toBeGreaterThan(0));
    expect(chamadas("/redes/1/analise/plataformas").every((c) => !consulta(c).has("escola_id"))).toBe(true);
  });

  it("escola com poucos alunos: 'protegido' por extenso (nenhum número, nem a coleta)", async () => {
    semear();
    abrir();
    await screen.findByTestId("tabela-escolas-periodo");
    const gama = screen.getByTestId("escola-periodo-4");
    expect(within(gama).getByTestId("escola-protegida")).toHaveTextContent(`Protegido: ${TEXTO_SUPRESSAO}.`);
    expect(gama).not.toHaveTextContent(/\d/);
  });

  it("sem dado e média escondida em complemento: escritos, nunca 0", async () => {
    semear();
    abrir();
    await screen.findByTestId("tabela-escolas-periodo");
    // Alfa: o Matific inteiro sem dado — o porquê uma vez, mais a coleta.
    expect(screen.getByTestId("escola-periodo-2"))
      .toHaveTextContent("Sem dado: menos de 5 alunos com dado desta plataforma no período");
    // Delta: o acerto sem dado; o desempenho protegido (em complemento). A 1ª célula é a caixa
    // "Comparar" da tela Escolas.
    const delta = screen.getByTestId("escola-periodo-5");
    const celulas = within(delta).getAllByRole("cell");
    expect(within(celulas[0]).getByRole("checkbox", { name: "Comparar EMEF Sintética Delta" })).toBeInTheDocument();
    expect(celulas[5]).toHaveTextContent("sem dado");                        // acerto do Elefante
    expect(celulas[9]).toHaveTextContent("protegido");                       // desempenho do Matific
    expect(delta).not.toHaveTextContent(/\b0,0\b/);
  });
});
