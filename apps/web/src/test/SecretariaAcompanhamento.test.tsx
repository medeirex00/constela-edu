/**
 * ESCOLAS EM ACOMPANHAMENTO (`/rede/acompanhamento`) — DESENHO2 §2.3.2: a conclusão, a caixa
 * "Como ler", as escolas com sinal de ATENÇÃO em ordem alfabética, cada uma com dois blocos
 * separados (avaliações externas × Elefante e Matific no ano letivo), o selo de natureza e a
 * referência de cada sinal, "Ver a escola"; depois, recolhidos, as escolas sem sinal e os dados
 * incompletos; CSV dos sinais. Sem níveis, categorias nem leituras exploratórias.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/csvRanking", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/csvRanking")>();
  return { ...original, baixarCsv: vi.fn() };
});

import { baixarCsv } from "../lib/csvRanking";
import AcompanhamentoRede from "../pages/rede/secretaria/AcompanhamentoRede";
import {
  antes, caminhosLidos, chamadas, consulta, diagnostico, renderTela, semCausalidade, semJargao, semearSecretaria,
} from "./SecretariaFixtures";
import { responder, screen, userEvent, within } from "./utils";

const ROTA = "/rede/acompanhamento";

async function abrir(opcoes: Parameters<typeof renderTela>[2] = {}) {
  const r = renderTela(ROTA, <AcompanhamentoRede />, opcoes);
  await screen.findByTestId("acompanhamento-conclusao");
  return r;
}

beforeEach(() => vi.mocked(baixarCsv).mockClear());

describe("Escolas em acompanhamento — a lista", () => {
  it("a conclusão primeiro, depois 'Como ler' e a lista em ordem alfabética só com as escolas em atenção", async () => {
    semearSecretaria();
    await abrir();
    expect(screen.getByRole("heading", { level: 1, name: "Escolas em acompanhamento" })).toBeInTheDocument();
    const conclusao = screen.getByTestId("acompanhamento-conclusao");
    expect(conclusao).toHaveTextContent("2 de 4 escolas têm algum sinal de atenção.");
    const comoLer = screen.getByTestId("como-ler-acompanhamento");
    expect(comoLer).toHaveTextContent("Um sinal indica onde olhar primeiro. Não é diagnóstico nem nota da escola.");
    expect(comoLer).toHaveTextContent("os sinais de uma e de outra não se somam");
    const lista = screen.getByTestId("lista-acompanhamento");
    expect(antes(conclusao, comoLer)).toBe(true);
    expect(antes(comoLer, lista)).toBe(true);
    // A resposta veio Delta, Beta, Gama, Alfa: a lista é alfabética e só tem quem tem sinal de atenção.
    expect(within(lista).getAllByRole("heading", { level: 3 }).map((h) => h.textContent))
      .toEqual(["EMEF Sintética Alfa", "EMEF Sintética Beta"]);
    expect(screen.getByTestId("frase-separacao")).toHaveTextContent("não se comparam diretamente");
  });

  it("dois blocos separados por escola: avaliações externas e plataformas (ano letivo), com selo e referência", async () => {
    semearSecretaria();
    await abrir();
    const alfa = screen.getByTestId("acompanhamento-escola-2");
    const aval = within(alfa).getByTestId("bloco-avaliacoes");
    const plat = within(alfa).getByTestId("bloco-plataformas");
    expect(within(aval).getByRole("heading", { level: 4 })).toHaveTextContent("Nas avaliações externas");
    expect(aval).toHaveTextContent("IEE 2025: 4,80, abaixo da meta 5,20 (não atingiu).");
    // O texto já começa pela referência ("IEE 2025: …"): a linha "Referência" não a repete.
    expect(aval).not.toHaveTextContent("Referência: IEE 2025");
    expect(aval.querySelector("[data-natureza=oficial]")).toHaveTextContent("Oficial");
    // O sinal FAVORÁVEL não entra (a lista é de atenção); o de plataforma vai para o outro bloco.
    expect(aval).not.toHaveTextContent("acima da rede municipal");
    expect(aval).not.toHaveTextContent("Elefante");
    expect(within(plat).getByRole("heading", { level: 4 })).toHaveTextContent("No Elefante e no Matific (ano letivo de 2026)");
    expect(plat).toHaveTextContent("Elefante: participação de 55% — abaixo da rede (68,3%).");
    // Dois selos no sinal de plataforma: o número é da plataforma; "abaixo da rede" (com a
    // tolerância do Constela) é Calculado pelo Constela — como a mesma conta nas avaliações.
    expect(plat.querySelector("[data-natureza=plataforma]")).toHaveTextContent("Plataforma");
    expect(plat.querySelector("[data-natureza=calculado]")).toHaveTextContent("Calculado pelo Constela");
    const beta = screen.getByTestId("acompanhamento-escola-3");
    const avalBeta = within(beta).getByTestId("bloco-avaliacoes");
    expect(avalBeta.querySelectorAll("[data-natureza=calculado]")).toHaveLength(2);
    // "SARESP 2025, 5º ano, LP: …" com a referência "SARESP 2025 · 5º ano · LP": não repete. A da
    // tendência traz as duas edições (não é o começo do texto): fica.
    expect(avalBeta).not.toHaveTextContent("Referência: SARESP 2025 · 5º ano · LP");
    expect(avalBeta).toHaveTextContent("Referência: SARESP 2024–2025 · 5º ano · LP");
    // A do sinal de plataforma (a janela) também não é o começo do texto: fica.
    expect(plat).toHaveTextContent("Referência: Elefante · 01/01/2026–31/12/2026");
  });

  it("cada sinal de plataforma leva Plataforma E Calculado pelo Constela; o de avaliação e o de dados, só o dele", async () => {
    semearSecretaria();
    await abrir();
    const selos = (li: Element) => [...li.querySelectorAll("[data-natureza]")].map((s) => s.getAttribute("data-natureza"));
    const sinaisDePlataforma = screen.getAllByTestId("bloco-plataformas").flatMap((b) => [...b.querySelectorAll("li")]);
    expect(sinaisDePlataforma.length).toBeGreaterThan(0);
    for (const li of sinaisDePlataforma) expect(selos(li)).toEqual(["plataforma", "calculado"]);
    for (const li of screen.getAllByTestId("bloco-avaliacoes").flatMap((b) => [...b.querySelectorAll("li")])) {
      expect(selos(li)).toHaveLength(1);
    }
    // "Como ler" diz de quem é cada parte.
    expect(screen.getByTestId("como-ler-acompanhamento"))
      .toHaveTextContent("O número é da plataforma; a comparação com a rede é do Constela");
    await userEvent.click(within(screen.getByTestId("dados-incompletos")).getByRole("button"));
    for (const li of screen.getByTestId("dados-incompletos-3").querySelectorAll("li")) expect(selos(li)).toEqual(["dados"]);
  });

  it("os textos do servidor sem sigla nem 'diagnóstico' (a tela diz que não é diagnóstico) e sem mandar importar", async () => {
    semearSecretaria();
    const d = diagnostico();
    responder("GET", "/redes/1/analise/diagnostico", diagnostico({
      escolas: d.escolas.map((e) => (e.id !== 2 ? e : {
        ...e,
        sinais: [
          ...e.sinais.map((s) => (s.codigo === "meta_iee"
            ? { ...s, texto: "IEE 2025: 4,80, com meta 5,20 — meta não cumprida (pelo ICM oficial da SEDUC)." } : s)),
          { codigo: "numero_sem_registro", eixo: "dados", componente: "geral", natureza: "dados", direcao: "informativo",
            texto: "Ideb 2023: número gravado antes, sem o registro do arquivo oficial — não entra no diagnóstico "
              + "(importe o arquivo oficial desta edição).", referencia: "Ideb 2023" },
        ],
      })),
    }));
    const { container } = await abrir();
    const alfa = screen.getByTestId("acompanhamento-escola-2");
    expect(within(alfa).getByTestId("bloco-avaliacoes")).toHaveTextContent("meta não cumprida (segundo a SEDUC).");
    await userEvent.click(within(screen.getByTestId("dados-incompletos")).getByRole("button"));
    expect(screen.getByTestId("dados-incompletos-2")).toHaveTextContent("— não gera sinal (falta importar o arquivo "
      + "oficial desta edição — quem importa é o administrador global).");
    expect(container).not.toHaveTextContent(/\bICM\b|diagnóstico \(|importe o arquivo/);
  });

  it("sem níveis, categorias nem leituras exploratórias (isso é das Análises avançadas); sem causa nem jargão", async () => {
    semearSecretaria();
    const { container } = await abrir();
    expect(container).not.toHaveTextContent(/Prioritário|Oportunidade|Convergente|Divergente|Inconclusiva|Exploratório|Hipótese/);
    semCausalidade(container);
    semJargao(container);
  });

  it("'Ver a escola' põe a escola no contexto e abre a Visão da Escola com o 'Voltar' para esta lista", async () => {
    semearSecretaria();
    await abrir();
    await userEvent.click(screen.getByRole("button", { name: "Ver a escola EMEF Sintética Beta" }));
    expect(await screen.findByText("TELA:escola")).toBeInTheDocument();
    const onde = screen.getByTestId("onde");
    expect(onde).toHaveTextContent("/escola");
    expect(localStorage.getItem("sgpe_escola")).toBe("3");
    expect(onde).toHaveAttribute("data-voltar-caminho", ROTA);
    expect(onde).toHaveAttribute("data-voltar-texto", "Voltar para Escolas em acompanhamento");
  });
});

describe("Escolas em acompanhamento — recolhidos, CSV e leituras", () => {
  it("as escolas sem sinal e os dados incompletos ficam recolhidos; o termo técnico sai em língua simples", async () => {
    semearSecretaria();
    await abrir();
    const semSinal = screen.getByTestId("escolas-sem-sinal");
    const botao = within(semSinal).getByRole("button", { name: "Escolas sem sinal de atenção (2)" });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(botao);
    expect(within(semSinal).getAllByRole("listitem").map((l) => l.textContent))
      .toEqual(["EMEF Sintética Delta", "EMEI Sintética Gama"]);
    expect(semSinal).toHaveTextContent("Sem sinal não quer dizer sem problema");

    const incompletos = screen.getByTestId("dados-incompletos");
    await userEvent.click(within(incompletos).getByRole("button", { name: "Dados incompletos (3 escolas)" }));
    expect(screen.getByTestId("dados-incompletos-4")).toHaveTextContent("Cadastro: sem código INEP no cadastro");
    expect(screen.getByTestId("dados-incompletos-4").querySelector("[data-natureza=dados]")).toHaveTextContent("Dados");
    // "média instável (TPS = 0)" do servidor → a língua simples do fluxo principal.
    expect(screen.getByTestId("dados-incompletos-3"))
      .toHaveTextContent("SARESP 2025, 5º ano, MT: média instável (poucos alunos fizeram a prova).");
    semJargao(incompletos);
  });

  it("rede com um só módulo: o não contratado NÃO vira 'dado incompleto' de cada escola — diz uma vez, em 'Como ler'", async () => {
    semearSecretaria();
    const d = diagnostico();
    // O servidor manda o sinal para CADA escola (inclusive a Delta, sem outro sinal de dados).
    responder("GET", "/redes/1/analise/diagnostico", diagnostico({
      modulos: { elefante: true, matific: false },
      escolas: d.escolas.map((e) => ({ ...e, sinais: [...e.sinais, {
        codigo: "modulo_nao_contratado", eixo: "dados", componente: "mt", natureza: "dados", direcao: "informativo",
        texto: "Matific: a rede não contratou este módulo — sem dado de plataforma para Matemática.",
        referencia: "Contrato da rede" }] })),
    }));
    const { container } = await abrir();
    expect(screen.getByTestId("modulo-nao-contratado"))
      .toHaveTextContent("A rede não contratou o Matific: não há sinal de plataforma para Matemática.");
    // A contagem é a das faltas de verdade (Alfa, Beta e Gama), não as 4 escolas da rede.
    const incompletos = screen.getByTestId("dados-incompletos");
    await userEvent.click(within(incompletos).getByRole("button", { name: "Dados incompletos (3 escolas)" }));
    expect(screen.queryByTestId("dados-incompletos-5")).toBeNull();
    expect(container).not.toHaveTextContent("a rede não contratou este módulo");
    // No CSV o sinal fica, com o rótulo próprio (não "Dados incompletos").
    await userEvent.click(screen.getByRole("button", { name: /Exportar sinais \(CSV\)/ }));
    const t = vi.mocked(baixarCsv).mock.calls[0][0];
    const doContrato = t.linhas.filter((l) => String(l[5]).includes("não contratou este módulo"));
    expect(doContrato).toHaveLength(4);
    expect(doContrato.every((l) => l[2] === "Módulo não contratado pela rede")).toBe(true);
  });

  it("nenhuma escola em atenção: diz isso (sem lista vazia e sem afirmar que vai tudo bem)", async () => {
    semearSecretaria();
    const d = diagnostico();
    responder("GET", "/redes/1/analise/diagnostico", diagnostico({
      escolas: d.escolas.map((e) => ({ ...e, sinais: e.sinais.filter((s) => s.direcao !== "atencao") })),
    }));
    await abrir();
    expect(screen.getByTestId("acompanhamento-conclusao")).toHaveTextContent("Nenhuma escola com sinal de atenção nesta leitura.");
    expect(screen.queryByTestId("lista-acompanhamento")).toBeNull();
    expect(screen.getByTestId("escolas-sem-sinal")).toHaveTextContent("Escolas sem sinal de atenção (4)");
  });

  it("Exportar sinais (CSV): uma linha por sinal, escolas em ordem alfabética, fonte e tipo escritos", async () => {
    semearSecretaria();
    await abrir();
    await userEvent.click(screen.getByRole("button", { name: /Exportar sinais \(CSV\)/ }));
    const t = vi.mocked(baixarCsv).mock.calls[0][0];
    expect(t.nomeArquivo).toMatch(/^escolas-em-acompanhamento_\d{4}-\d{2}-\d{2}\.csv$/);
    expect(t.cabecalho).toEqual(["Escola", "Código INEP", "Onde", "Tipo de sinal", "Natureza", "Sinal", "Referência"]);
    const escolas = t.linhas.map((l) => l[0]);
    expect(escolas).toEqual([...escolas].sort((a, b) => String(a).localeCompare(String(b), "pt-BR")));
    const iee = t.linhas.find((l) => l[6] === "IEE 2025")!;
    expect(iee.slice(2, 5)).toEqual(["Avaliações externas", "atenção", "Oficial"]);
    const gama = t.linhas.filter((l) => l[0] === "EMEI Sintética Gama");
    expect(gama.every((l) => l[2] === "Dados incompletos" && l[1] === "sem código INEP")).toBe(true);
    expect(t.linhas.flat().some((c) => c === 0)).toBe(false);
    // O texto de cada sinal como a tela o mostra: língua simples, sem a sigla técnica do servidor.
    expect(t.linhas.map((l) => l[5]).join(" ")).toContain("média instável (poucos alunos fizeram a prova)");
    expect(t.linhas.flat().join(" ")).not.toMatch(/\bTPS\b/);
  });

  it("lê só o diagnóstico, no ANO LETIVO (o período global não muda a tela)", async () => {
    semearSecretaria();
    await abrir({ periodo: { preset: "bimestre" } });
    expect(caminhosLidos()).toEqual(["/redes/1/analise/diagnostico"]);
    expect(consulta(chamadas("/redes/1/analise/diagnostico")[0]).get("periodo")).toBe("ano_letivo");
  });
});
