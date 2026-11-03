/**
 * ELEFANTE E MATIFIC (`/rede/plataformas`) — DESENHO2 §2.3.5: a frase da plataforma; o período
 * e a série desta tela (padrão: ano letivo, do 1º ao 5º ano, na URL) valendo para os cartões e a
 * evolução; a conclusão antes dos cartões; "O que cada número mede"; a evolução no ano letivo
 * (com o recorte de escola só dela); os totais acumulados (painel da rede) com o período certo de
 * cada plataforma, o cadastro à parte e a ausência por extenso; "Sobre os dados" recolhido; o
 * link para a tela Escolas, no mesmo período e série. (Os detalhes da evolução estão em AnalisePlataformas.)
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import PlataformasRedePagina from "../pages/rede/secretaria/PlataformasRedePagina";
import { FRASE_PLATAFORMA, METRICAS_ELEFANTE, METRICAS_MATIFIC } from "../pages/rede/secretaria/oQueMede";
import {
  LIMITACOES_COM_RELACAO, antes, caminhosLidos, chamadas, consulta, evolucao, painelRede, plataformasRede, renderTela,
  semCausalidade, semJargao, semearSecretaria,
} from "./SecretariaFixtures";
import { responder, screen, userEvent, waitFor, within } from "./utils";

const ROTA = "/rede/plataformas";

async function abrir(rota = ROTA, opcoes: Parameters<typeof renderTela>[2] = {}) {
  const r = renderTela(rota, <PlataformasRedePagina />, opcoes);
  await screen.findByTestId("conclusao-plataformas");
  await screen.findByTestId("totais-gerais");
  return r;
}

describe("Elefante e Matific — a tela", () => {
  it("a frase da plataforma, a conclusão antes dos cartões e o que cada número mede", async () => {
    semearSecretaria();
    const { container } = await abrir();
    expect(screen.getByRole("heading", { level: 1, name: "Elefante e Matific" })).toBeInTheDocument();
    expect(screen.getByText(FRASE_PLATAFORMA)).toBeInTheDocument();
    const conclusao = screen.getByTestId("conclusao-plataformas");
    expect(conclusao).toHaveTextContent(
      "No ano letivo de 2026, 70% dos alunos com conta leram ao menos um livro no Elefante e 80% dos alunos com dado "
      + "no período fizeram ao menos uma atividade no Matific.");
    expect(antes(conclusao, screen.getByTestId("plataforma-elefante"))).toBe(true);
    expect(screen.getByTestId("plataforma-matific")).toHaveTextContent("Atividades por aluno");
    const mede = screen.getByTestId("o-que-cada-numero-mede");
    for (const m of [...METRICAS_ELEFANTE, ...METRICAS_MATIFIC]) expect(mede).toHaveTextContent(m.oQueMede);
    expect(within(screen.getByTestId("o-que-mede-elefante")).getAllByText(/./, { selector: "dt" })).toHaveLength(5);
    expect(screen.getByLabelText("Período")).toHaveValue("ano_letivo");
    semCausalidade(container);
    semJargao(container);
  });

  it("evolução no ano letivo e totais acumulados, na ordem; o resto recolhido", async () => {
    semearSecretaria();
    await abrir();
    const evolucao = await screen.findByTestId("tabela-evolucao-rede");
    const totais = screen.getByTestId("totais-gerais");
    expect(antes(screen.getByTestId("plataforma-elefante"), evolucao)).toBe(true);
    expect(antes(evolucao, totais)).toBe(true);
    expect(totais).toHaveTextContent("Alunos400");
    expect(totais).toHaveTextContent("Com dado de alguma plataforma90,0%360 de 400 alunos");
    expect(screen.getByTestId("totais-elefante")).toHaveTextContent("Livros lidos1.300");
    expect(screen.getByTestId("totais-elefante")).toHaveTextContent("Tempo de leitura303h 20min");
    expect(screen.getByTestId("totais-matific")).toHaveTextContent("Atividades5.130");
    expect(screen.getByTestId("totais-matific")).toHaveTextContent("Estrelas10.800");
    // A média interna (0–100) fica, com o que ela é — e que NÃO compara escolas.
    expect(screen.getByTestId("media-interna")).toHaveTextContent("não serve para comparar escolas");
    expect(screen.getByTestId("media-interna").querySelector("[data-natureza=calculado]")).not.toBeNull();
    // Sobre os dados: recolhido; aberto, a cobertura, as lacunas por série e as limitações.
    const sobre = screen.getByTestId("sobre-os-dados");
    const botao = within(sobre).getByRole("button");
    expect(botao).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(botao);
    expect(within(sobre).getByTestId("cobertura-coletas")).toHaveTextContent("Última coleta: Elefante 18/10/2026");
    expect(within(within(sobre).getByTestId("tabela-lacunas-serie")).getAllByRole("row")).toHaveLength(6);
    expect(within(sobre).getByTestId("limitacoes-plataformas")).toHaveTextContent("Questões do Elefante");
    // A média interna de cada plataforma (o Panorama antigo mostrava as duas) continua junto.
    expect(screen.getByTestId("media-interna")).toHaveTextContent("71,9 (Elefante 61,2 · Matific 68,5)");
  });

  it("'Sobre os dados' aberto: limitações em língua simples, sem as frases da relação estatística", async () => {
    semearSecretaria();
    responder("GET", "/redes/1/analise/plataformas", plataformasRede({ limitacoes: LIMITACOES_COM_RELACAO }));
    const { container } = await abrir();
    await userEvent.click(within(screen.getByTestId("sobre-os-dados")).getByRole("button"));
    const limitacoes = screen.getByTestId("limitacoes-plataformas");
    expect(within(limitacoes).getAllByRole("listitem").map((l) => l.textContent)).toEqual([
      "Coleta atrasada: a escola aparece como coleta parcial (texto sintético).",
      "Grupo de alunos: alunos ativos do 1º ao 5º ano (texto sintético).",
      "As plataformas só têm dados do ano letivo em curso; as avaliações oficiais por escola são de anos anteriores.",
    ]);
    semJargao(container);
    semCausalidade(container);
  });

  it("lê as plataformas no ANO LETIVO (mesmo com outro período global), a evolução, o painel e o catálogo", async () => {
    semearSecretaria();
    await abrir(ROTA, { periodo: { preset: "mes" } });
    await screen.findByTestId("tabela-evolucao-rede");
    expect(caminhosLidos().sort()).toEqual([
      "/redes/1/analise/indicadores", "/redes/1/analise/plataformas", "/redes/1/analise/plataformas/evolucao",
      "/redes/1/dashboard",
    ]);
    expect(consulta(chamadas("/redes/1/analise/plataformas")[0]).get("periodo")).toBe("ano_letivo");
    expect(chamadas("/redes/1/analise/plataformas/evolucao")[0]).toBe("/redes/1/analise/plataformas/evolucao");
  });

  it("o período desta tela fica na URL e a conclusão diz de quando é; os totais acumulados não mudam", async () => {
    semearSecretaria();
    responder("GET", "/redes/1/analise/plataformas", (c: string) => (consulta(c).get("periodo") === "mes"
      ? plataformasRede({ janela: { inicio: "2026-10-01", fim: "2026-10-31", rotulo: "Este mês", preset: "mes" } })
      : plataformasRede()));
    await abrir();
    await userEvent.selectOptions(screen.getByLabelText("Período"), "mes");
    await waitFor(() => expect(screen.getByTestId("conclusao-plataformas"))
      .toHaveTextContent("No período (este mês, de 01/10/2026 a 31/10/2026), 70% dos alunos"));
    expect(screen.getByTestId("onde")).toHaveTextContent(`${ROTA}?periodo=mes`);
    expect(chamadas("/redes/1/dashboard")).toHaveLength(1);
    // A tela Escolas (o nome novo; sem o parâmetro `aba`, que não existe mais), no mesmo período.
    expect(screen.getByRole("link", { name: /^Escolas › Elefante e Matific/ }))
      .toHaveAttribute("href", "/rede/escolas?periodo=mes");
    expect(screen.queryByText(/Comparar escolas/)).toBeNull();
  });

  it("totais escondidos da Secretaria (grupo pequeno): 'protegido' por extenso e o aviso — nunca 0", async () => {
    semearSecretaria();
    responder("GET", "/redes/1/dashboard", painelRede({
      livros: null, tempo_leitura_min: null, livros_por_aluno: null,
      grupo_pequeno: { leitura: 1, matematica: 0, texto: "1 escola fica fora dos totais de leitura (texto sintético)." },
    }));
    await abrir();
    const elefante = screen.getByTestId("totais-elefante");
    expect(within(elefante).getAllByText("protegido (poucos alunos)")).toHaveLength(2);   // livros e tempo
    expect(elefante).not.toHaveTextContent(/Livros lidos0\b/);
    expect(screen.getByText("1 escola fica fora dos totais de leitura (texto sintético).")).toBeInTheDocument();
  });

  it("totais acumulados: cada plataforma com o seu período (Elefante desde o início; Matific no ano letivo)", async () => {
    semearSecretaria();
    const { container } = await abrir();
    const titulo = screen.getByRole("heading", { level: 2, name: /Totais acumulados/ });
    expect(titulo).toBeInTheDocument();
    expect(container).not.toHaveTextContent("Totais do ano letivo");
    expect(screen.getByTestId("totais-quando")).toHaveTextContent(
      "Elefante: acumulado desde o início da conta de cada aluno na plataforma. Matific: no ano letivo.");
    expect(screen.getByTestId("totais-quando")).toHaveTextContent("não mudam com o período nem com a série escolhidos acima");
    const elefante = screen.getByTestId("totais-elefante");
    expect(elefante).toHaveTextContent("Livros lidos1.300títulos únicos, desde o início no Elefante");
    expect(elefante).toHaveTextContent("Tempo de leitura303h 20mino mínimo registrado, desde o início no Elefante");
    expect(elefante).toHaveAttribute("aria-label", "Elefante Letrado, acumulado desde o início");
    // Um só "livros por aluno" na tela: o do período, com o que mede (o dos totais tinha outra conta).
    expect(elefante).not.toHaveTextContent("Livros por aluno");
    expect(screen.getByTestId("totais-matific")).toHaveTextContent("Atividades5.130no ano letivo");
    // Sem o termo interno "retrato".
    expect(container).not.toHaveTextContent(/retrato/i);
  });

  it("totais: o cadastro à parte (sem o selo Plataforma) e a média das notas dizendo o que é", async () => {
    semearSecretaria();
    await abrir();
    const cadastro = screen.getByTestId("totais-cadastro");
    expect(cadastro).toHaveTextContent("Cadastro da rede");
    expect(cadastro).toHaveTextContent("Alunos400");
    expect(cadastro).toHaveTextContent("Professores22");
    expect(cadastro).toHaveTextContent("Escolas ativas4situação “ativa” no cadastro, de 4 cadastradas — não indica uso das plataformas");
    expect(cadastro.querySelector("[data-natureza]")).toBeNull();
    const plataformas = screen.getByTestId("totais-plataformas");
    expect(plataformas.querySelector("[data-natureza=plataforma]")).not.toBeNull();
    expect(plataformas).toHaveTextContent("Com dado de alguma plataforma90,0%");
    expect(plataformas).not.toHaveTextContent("Professores");
    const media = screen.getByTestId("media-interna");
    expect(media).toHaveTextContent("Média das notas do Constela (0 a 100): 71,9 (Elefante 61,2 · Matific 68,5).");
    expect(media).toHaveTextContent("comparando-o com os colegas da própria escola — não é avaliação de aprendizagem");
  });

  it("totais sem nenhuma medição (o servidor manda 0, não null): 'sem dado' por extenso, nunca 0", async () => {
    semearSecretaria();
    responder("GET", "/redes/1/dashboard", painelRede({
      media_matific: 0, ativos_matific: 0, atividades: 0, estrelas: 0, media_geral: 61.2,
    }));
    await abrir();
    const matific = screen.getByTestId("totais-matific");
    expect(matific).toHaveTextContent("Atividadessem dado");
    expect(matific).toHaveTextContent("Estrelassem dado");
    expect(matific).not.toHaveTextContent(/Atividades0|Estrelas0/);
    expect(screen.getByTestId("media-interna")).toHaveTextContent("61,2 (Elefante 61,2 · Matific sem dado)");
    expect(screen.getByTestId("media-interna")).not.toHaveTextContent("Matific 0");
  });

  it("nada medido em nenhuma plataforma: a média geral também é 'sem dado'", async () => {
    semearSecretaria();
    responder("GET", "/redes/1/dashboard", painelRede({
      media_geral: 0, media_matific: 0, media_elefante: 0, ativos_matific: 0, ativos_elefante: 0, livros: 0,
      tempo_leitura_min: 0, atividades: 0, estrelas: 0,
    }));
    await abrir();
    expect(screen.getByTestId("media-interna"))
      .toHaveTextContent("Média das notas do Constela (0 a 100): sem dado (Elefante sem dado · Matific sem dado).");
    expect(screen.getByTestId("totais-elefante")).toHaveTextContent("Livros lidossem dado");
    expect(screen.getByTestId("totais-elefante")).not.toHaveTextContent(/Livros lidos0|0min/);
  });

  it("a evolução: as limitações dela em língua simples, sem repetir as de 'Sobre os dados'", async () => {
    semearSecretaria();
    responder("GET", "/redes/1/analise/plataformas", plataformasRede({ limitacoes: LIMITACOES_COM_RELACAO }));
    // O serviço junta as do bimestre com as MESMAS do uso no período (que "Sobre os dados" já mostra).
    responder("GET", "/redes/1/analise/plataformas/evolucao", evolucao({ limitacoes: [
      "A proteção das crianças (k = 5) é decidida pelo número de alunos (texto sintético).",
      ...LIMITACOES_COM_RELACAO,
    ] }));
    const { container } = await abrir();
    const bloco = await screen.findByTestId("limitacoes-evolucao");
    await userEvent.click(within(bloco).getByRole("button"));
    expect(within(bloco).getAllByRole("listitem").map((l) => l.textContent))
      .toEqual(["A proteção das crianças é decidida pelo número de alunos (texto sintético)."]);
    semJargao(container);
    semCausalidade(container);
  });

  it("rede só com o Matific: a tela se chama 'Matific' e não mostra o Elefante", async () => {
    semearSecretaria();
    const p = plataformasRede();
    responder("GET", "/redes/1/analise/plataformas", plataformasRede({
      modulos: { elefante: false, matific: true }, rede: { ...p.rede, elefante: null },
    }));
    responder("GET", "/redes/1/dashboard", painelRede({}, ["matematica"]));
    await abrir();
    expect(screen.getByRole("heading", { level: 1, name: "Matific" })).toBeInTheDocument();
    expect(screen.queryByTestId("plataforma-elefante")).toBeNull();
    expect(screen.queryByTestId("totais-elefante")).toBeNull();
    expect(screen.queryByTestId("o-que-mede-elefante")).toBeNull();
  });
});

describe("Elefante e Matific — a série e o recorte da evolução", () => {
  it("a série (no topo, junto do período) vale para os cartões e a evolução; a escola, só para a evolução", async () => {
    semearSecretaria();
    await abrir();
    await screen.findByTestId("tabela-evolucao-rede");
    expect(screen.getByTestId("recorte-plataformas")).toHaveTextContent("série (1º ao 5º ano)");
    const recorte = screen.getByTestId("recorte-evolucao");
    expect(within(recorte).queryByLabelText("Série")).toBeNull();
    await userEvent.selectOptions(within(recorte).getByLabelText("Escola"), "3");
    expect(await screen.findByTestId("tabela-evolucao-escola")).toBeInTheDocument();
    expect(screen.getByTestId("evolucao-escola")).toHaveTextContent("EMEF Sintética Beta, por bimestre");
    await userEvent.selectOptions(screen.getByLabelText("Série"), "5");
    await waitFor(() => {
      const lidas = chamadas("/redes/1/analise/plataformas/evolucao");
      const ultima = consulta(lidas[lidas.length - 1]);
      expect(ultima.get("escola_id")).toBe("3");
      expect(ultima.get("serie")).toBe("5");
    });
    expect(screen.getByTestId("onde")).toHaveTextContent("escola=3");
    expect(screen.getByTestId("onde")).toHaveTextContent("serie=5");
    // Os cartões do período vêm da MESMA série (a leitura das plataformas leva a série, nunca a escola).
    await waitFor(() => expect(chamadas("/redes/1/analise/plataformas").some((c) => consulta(c).get("serie") === "5"))
      .toBe(true));
    expect(chamadas("/redes/1/analise/plataformas").every((c) => !consulta(c).has("escola_id"))).toBe(true);
    expect(screen.getByTestId("recorte-plataformas")).toHaveTextContent("Vale aqui: período (Ano letivo de 2026) e série (5º ano).");
    expect(screen.getByTestId("conclusao-plataformas")).toHaveTextContent("No ano letivo de 2026, no 5º ano, 70% dos alunos");
    // Os totais acumulados não dependem da série (uma leitura só do painel).
    expect(chamadas("/redes/1/dashboard")).toHaveLength(1);
  });

  it("o link antigo da aba das plataformas com a série (?serie=2) abre a tela já no 2º ano — cartões, lacunas, links", async () => {
    semearSecretaria();
    await abrir(`${ROTA}?serie=2`);
    expect(screen.getByLabelText("Série")).toHaveValue("2");
    expect(consulta(chamadas("/redes/1/analise/plataformas")[0]).get("serie")).toBe("2");
    await waitFor(() => expect(consulta(chamadas("/redes/1/analise/plataformas/evolucao")[0]).get("serie")).toBe("2"));
    expect(screen.getByTestId("recorte-plataformas")).toHaveTextContent("série (2º ano)");
    // O quadro de lacunas mostra só a série escolhida (as outras viriam com "0 escolas", um zero falso).
    await userEvent.click(within(screen.getByTestId("sobre-os-dados")).getByRole("button"));
    const linhas = within(screen.getByTestId("tabela-lacunas-serie")).getAllByRole("row").slice(1);
    expect(linhas).toHaveLength(1);
    expect(linhas[0]).toHaveTextContent("2º ano");
    expect(screen.getByRole("link", { name: /^Escolas › Elefante e Matific/ }))
      .toHaveAttribute("href", "/rede/escolas?serie=2");
  });
});
