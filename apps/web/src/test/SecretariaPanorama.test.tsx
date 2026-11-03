/**
 * PANORAMA DA REDE (`/` da Secretaria; `/rede/visao` do admin global) — DESENHO3 §2: "A rede no
 * Constela" (cadastradas ≠ ativas ≠ com uso, as demais por extenso), "Participação no ano letivo"
 * por plataforma contratada, "Todas as escolas da rede" (todas, em ordem alfabética, com o
 * cadastro, a situação de uso e o link para a ficha; filtro por situação), "Escolas em destaque"
 * (o critério escrito, o mesmo da vitrine) com a vitrine logo abaixo, "Metas da rede" recolhida e
 * o rodapé com as Avaliações externas — que NÃO são o elemento principal. Ausência e proteção por
 * extenso (nunca 0), nenhuma atividade inventada, nenhuma palavra causal nem termo técnico.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { MetasDaRede, type MetaProgresso } from "../pages/rede/comum";
import FichaEscolaRede from "../pages/rede/secretaria/FichaEscolaRede";
import PanoramaSecretaria from "../pages/rede/secretaria/PanoramaSecretaria";
import { textoDestaquesVazio } from "../pages/rede/secretaria/conclusoes";
import { FRASE_PLATAFORMA, O_QUE_MEDE_REDE } from "../pages/rede/secretaria/oQueMede";
import {
  admin, caminhosLidos, chamadas, consulta, destaquesRede, painelDoPanorama, plataformasDoPanorama, renderTela,
  secretaria, semCausalidade, semJargao, semearPanorama,
} from "./SecretariaFixtures";
import { renderComApp, responder, responderErro, screen, userEvent, waitFor, within } from "./utils";

async function abrir(opcoes: Parameters<typeof renderTela>[2] = {}) {
  const r = renderTela("/", <PanoramaSecretaria />, opcoes);
  await screen.findByTestId("conclusao-rede");
  await screen.findByTestId("lista-escolas");
  await screen.findByTestId("criterio-destaques");
  await screen.findByTestId("conclusao-plataformas");
  return r;
}

const linha = (id: number) => screen.getByTestId(`escola-${id}`);

/** Metas sintéticas: livros (acumulados), adoção SEM dado medido e atividades do Matific. */
const META = { sufixo: "", descricao: null, escolas_atingiram: null, escolas_total: null, comparavel: false };
const METAS: MetaProgresso[] = [
  { ...META, id: 1, metrica: "livros", rotulo: "Livros lidos na rede", alvo: 15000, atual: 12400, progresso: 82.7,
    atingida: false },
  { ...META, id: 2, metrica: "adocao", rotulo: "Engajamento (adoção)", sufixo: "%", alvo: 90, atual: 0, progresso: 0,
    atingida: false, medida: false },
  { ...META, id: 3, metrica: "atividades", rotulo: "Atividades Matific na rede", alvo: 6000, atual: 5130,
    progresso: 85.5, atingida: false },
];

/** O mundo do Panorama com a Zeta (id 7) SEM uso, mas com a coleta do Elefante PARCIAL (parada em
 *  15/03/2026): o Matific está em dia e zerado. O resto do ano do Elefante não foi medido. */
function semearZetaParcial() {
  semearPanorama();
  const p = plataformasDoPanorama();
  responder("GET", "/redes/1/analise/plataformas", {
    ...p,
    escolas: p.escolas.map((e) => (e.escola_id !== 7 ? e : {
      ...e, cobertura: { elefante: "coleta_parcial", matific: "ok" },
      elefante: { ...e.elefante!, coleta_parcial: true, coberto_ate: "2026-03-15T00:10:00-03:00" },
    })),
  });
}
const nomesDaLista = () =>
  within(screen.getByTestId("lista-escolas")).getAllByRole("listitem").map((li) => within(li).getAllByRole("link")[0].textContent);

describe("Panorama da Rede — a ordem do desenho", () => {
  it("cabeçalho com o nome da rede; as seções na ordem; as avaliações externas só no rodapé", async () => {
    semearPanorama();
    const { container } = await abrir();
    expect(screen.getByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeInTheDocument();
    expect(screen.getByTestId("secretaria-rede-nome")).toHaveTextContent("Rede Sintética Norte");
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "A rede no Constela", "Participação no ano letivo", "Todas as escolas da rede", "Escolas em destaque",
      "Reconhecimento público", "Metas da rede",
    ]);
    // Nada do Panorama antigo: nem cartões de avaliação, nem o destaque do ICA, nem "Para fazer agora".
    for (const testId of ["em-resumo", "cartao-avaliacoes", "destaque-ica", "conclusao-avaliacoes", "para-fazer-agora"]) {
      expect(screen.queryByTestId(testId)).toBeNull();
    }
    expect(container).not.toHaveTextContent(/Para fazer agora|ICA 2025|meta de 60%/);
    // As avaliações externas: um link discreto no rodapé, com a frase dos períodos diferentes.
    const rodape = screen.getByTestId("rodape-panorama");
    expect(within(rodape).getByRole("link", { name: "Avaliações externas" })).toHaveAttribute("href", "/rede/avaliacoes-externas");
    expect(within(rodape).getByTestId("frase-separacao")).toHaveTextContent(
      "As avaliações oficiais são de outras edições e as plataformas, do ano letivo de 2026: são medidas e períodos "
      + "diferentes — não se comparam diretamente.");
    // Nenhuma tabela de ranking; nenhuma palavra causal nem termo técnico.
    expect(container.querySelectorAll("table")).toHaveLength(0);
    expect(container).not.toHaveTextContent(/Top 5|Melhor escola|Equidade|1º lugar/);
    semCausalidade(container);
    semJargao(container);
  });

  it("lê só o necessário: painel, plataformas NO ANO LETIVO (mesmo com outro período global), destaques, nome, frescor e vitrine", async () => {
    semearPanorama();
    await abrir({ periodo: { preset: "mes" } });
    await screen.findByRole("button", { name: /Ligar vitrine pública/ });
    expect(caminhosLidos().sort()).toEqual([
      "/redes", "/redes/1/analise/plataformas", "/redes/1/dashboard", "/redes/1/destaques", "/redes/1/publico",
      "/redes/1/ranking/frescor",
    ]);
    expect(consulta(chamadas("/redes/1/analise/plataformas")[0]).get("periodo")).toBe("ano_letivo");
    // Nada das leituras pesadas nem do catálogo das avaliações.
    expect(chamadas("/redes/1/analise/diagnostico")).toHaveLength(0);
    expect(chamadas("/redes/1/analise/indicadores")).toHaveLength(0);
  });
});

describe("A rede no Constela — cadastradas, ativas e com uso não são sinônimos", () => {
  it("a conclusão e os quatro números, cada um com o que mede e o selo", async () => {
    semearPanorama();
    await abrir();
    expect(screen.getByTestId("conclusao-rede"))
      .toHaveTextContent("6 escolas cadastradas, 5 ativas no cadastro; 3 com uso do Constela no ano letivo de 2026.");
    expect(screen.getByTestId("numero-cadastradas")).toHaveTextContent("Escolas cadastradas6");
    expect(screen.getByTestId("numero-ativas")).toHaveTextContent("Ativas no cadastro5");
    expect(screen.getByTestId("numero-com-uso")).toHaveTextContent("Com uso no ano letivo3");
    const demais = screen.getByTestId("numero-demais");
    expect(demais).toHaveTextContent("Sem uso registrado ou sem dado3");
    expect(demais).toHaveTextContent("1 sem uso registrado · 1 sem dado · 1 protegida");
    // "Ativa" é situação do cadastro: o que mede diz que não indica uso.
    expect(screen.getByTestId("numero-ativas").querySelector("[data-o-que-mede]")).toHaveTextContent(O_QUE_MEDE_REDE.ativas);
    expect(screen.getByTestId("numero-ativas")).toHaveTextContent("não indica uso");
    // O uso do Elefante conta também a releitura: "um livro", nunca "um livro novo".
    expect(screen.getByTestId("numero-com-uso").querySelector("[data-o-que-mede]")).toHaveTextContent(
      "pelo menos um aluno do 1º ao 5º ano leu um livro no Elefante ou fez uma atividade no Matific no ano letivo, "
      + "pelas coletas");
    expect(screen.getByTestId("numero-com-uso")).not.toHaveTextContent("livro novo");
    expect(screen.getByTestId("numero-com-uso")).toHaveTextContent("ano letivo de 2026, pelas coletas");
    // Um ano letivo só: nenhuma frase de anos misturados.
    expect(screen.queryByTestId("anos-letivos-mistos")).toBeNull();
    for (const id of ["numero-cadastradas", "numero-ativas", "numero-com-uso", "numero-demais"]) {
      expect(screen.getByTestId(id).querySelector("[data-o-que-mede]")).not.toBeNull();
      expect(screen.getByTestId(id).querySelector("[data-natureza=calculado]")).toHaveTextContent("Calculado pelo Constela");
    }
  });

  it("o uso nunca sai do painel: a escola com contas no painel e sem coleta fica sem dado (não 'com uso')", async () => {
    semearPanorama();
    const p = plataformasDoPanorama();
    // A Delta perde as coletas do ano letivo; no painel ela continua com 120 alunos com dado e 80% de adoção.
    responder("GET", "/redes/1/analise/plataformas", {
      ...p,
      escolas: p.escolas.map((e) => (e.escola_id !== 5 ? e : {
        ...e, cobertura: { elefante: "sem_coleta", matific: "sem_coleta" },
        elefante: { ...e.elefante!, participacao_pct: null, alunos_com_leitura: null, motivo_sem_dado: "sem_coleta",
                    texto_sem_dado: "a escola não tem nenhuma coleta desta plataforma" },
        matific: { ...e.matific!, participacao_pct: null, motivo_sem_dado: "sem_coleta",
                   texto_sem_dado: "a escola não tem nenhuma coleta desta plataforma" },
      })),
    });
    await abrir();
    expect(screen.getByTestId("numero-com-uso")).toHaveTextContent("Com uso no ano letivo2");
    expect(screen.getByTestId("numero-demais")).toHaveTextContent("1 sem uso registrado · 2 sem dado · 1 protegida");
    const delta = linha(5);
    expect(within(delta).getByTestId("situacao-geral")).toHaveTextContent("Sem dado");
    expect(delta).toHaveTextContent("a escola não tem nenhuma coleta desta plataforma");
    expect(delta).not.toHaveTextContent(/%/);
  });

  it("sem o painel: os números do cadastro dizem que não carregaram (nunca 0); o resto da tela continua", async () => {
    semearPanorama();
    responderErro("GET", "/redes/1/dashboard", 500, "FALHA-PAINEL");
    renderTela("/", <PanoramaSecretaria />);
    expect(await screen.findByText("Não foi possível carregar as escolas da rede: FALHA-PAINEL")).toBeInTheDocument();
    expect(screen.getByTestId("numero-cadastradas")).toHaveTextContent("não foi possível carregar");
    expect(screen.getByTestId("numero-com-uso")).toHaveTextContent("não foi possível carregar");
    expect(screen.getByTestId("numero-cadastradas")).not.toHaveTextContent(/\b0\b/);
    expect(await screen.findByTestId("conclusao-plataformas")).toHaveTextContent("No ano letivo de 2026");
    expect(await screen.findByTestId("destaques-leitura")).toBeInTheDocument();
  });

  it("escolas em anos letivos diferentes: nenhum rótulo afirma o ano mais comum, e a tela diz isso por extenso", async () => {
    semearPanorama();
    const p = plataformasDoPanorama();
    responder("GET", "/redes/1/analise/plataformas", {
      ...p, janela: { ...p.janela, preset: "ano_letivo", ano_letivo: 2026, anos_letivos: [2025, 2026] },
      limitacoes: [...p.limitacoes, "As escolas da rede estão em anos letivos diferentes (2025, 2026): o período de "
        + "cada uma é o do ano dela."],
    });
    await abrir();
    const frase = "As escolas da rede estão em anos letivos diferentes (2025, 2026): o uso de cada escola é o do ano "
      + "letivo dela.";
    expect(screen.getByTestId("anos-letivos-mistos")).toHaveTextContent(frase);
    expect(screen.getByTestId("anos-letivos-mistos-participacao")).toHaveTextContent(frase);
    // Nem a conclusão, nem o número "com uso", nem a participação, nem o rodapé afirmam 2026.
    expect(screen.getByTestId("conclusao-rede"))
      .toHaveTextContent("6 escolas cadastradas, 5 ativas no cadastro; 3 com uso do Constela no ano letivo.");
    expect(screen.getByTestId("numero-com-uso")).toHaveTextContent("ano letivo de cada escola (2025, 2026), pelas coletas");
    expect(screen.getByTestId("conclusao-plataformas")).toHaveTextContent(/^No ano letivo, 70% dos alunos com conta/);
    expect(screen.getByTestId("participacao-elefante-quando")).toHaveTextContent("Ano letivo de cada escola (2025, 2026).");
    for (const id of ["conclusao-rede", "numero-com-uso", "conclusao-plataformas", "participacao-elefante-quando",
      "participacao-matific-quando", "frase-separacao"]) {
      expect(screen.getByTestId(id), id).not.toHaveTextContent(/ano letivo de 2026|Ano letivo de 2026/);
    }
  });
});

describe("Participação no ano letivo", () => {
  it("por plataforma contratada: a participação e a intensidade, o que mede, o selo, o período e a última coleta", async () => {
    semearPanorama();
    await abrir();
    expect(screen.getByTestId("conclusao-plataformas")).toHaveTextContent(
      "No ano letivo de 2026, 70% dos alunos com conta leram ao menos um livro no Elefante e 80% dos alunos com dado "
      + "no período fizeram ao menos uma atividade no Matific.");
    expect(screen.getByTestId("participacao-ano-letivo")).toHaveTextContent(FRASE_PLATAFORMA);
    expect(screen.getByTestId("participacao-elefante-pct")).toHaveTextContent("Participação70%");
    expect(screen.getByTestId("participacao-elefante-pct")).toHaveTextContent("O que mede: Dos alunos com conta, quantos leram");
    expect(screen.getByTestId("participacao-elefante-intensidade")).toHaveTextContent("Livros novos por aluno3,25");
    expect(screen.getByTestId("participacao-matific-pct")).toHaveTextContent("Participação80%");
    expect(screen.getByTestId("participacao-matific-intensidade")).toHaveTextContent("Atividades por aluno14,25");
    const quando = screen.getByTestId("participacao-elefante-quando");
    expect(quando.querySelector("[data-natureza=plataforma]")).toHaveTextContent("Plataforma");
    expect(quando).toHaveTextContent("Ano letivo de 2026 (01/01/2026 a 31/12/2026). Última coleta: 18/10/2026.");
    expect(screen.getByTestId("participacao-matific-quando")).toHaveTextContent("Última coleta: 19/10/2026.");
    expect(screen.getByRole("link", { name: /Ver o uso em detalhe/ })).toHaveAttribute("href", "/rede/plataformas");
  });

  it("número da rede protegido diz 'protegido (poucos alunos)'; sem número, 'sem dado no período' — nunca 0", async () => {
    semearPanorama();
    const p = plataformasDoPanorama();
    responder("GET", "/redes/1/analise/plataformas", {
      ...p,
      rede: { ...p.rede,
              matific: { ...p.rede.matific!, participacao_pct: null, atividades_por_aluno: null,
                         metricas_protegidas: ["participacao_pct", "atividades_por_aluno"] },
              elefante: { ...p.rede.elefante!, livros_por_aluno: null } },
    });
    await abrir();
    expect(screen.getByTestId("participacao-matific-pct")).toHaveTextContent("protegido (poucos alunos)");
    expect(screen.getByTestId("participacao-matific-pct")).not.toHaveTextContent(/\b0([,.]0+)?%?/);
    expect(screen.getByTestId("participacao-elefante-intensidade")).toHaveTextContent("sem dado no período");
    expect(screen.getByTestId("conclusao-plataformas")).toHaveTextContent("a participação no Matific fica protegida (poucos alunos)");
  });

  it("o número da rede diz quantas escolas entraram na soma (só as com a coleta em dia) e o escopo do servidor", async () => {
    semearPanorama();
    const p = plataformasDoPanorama();
    const escopo = "Os números da rede somam só as escolas com a coleta em dia (texto sintético).";
    responder("GET", "/redes/1/analise/plataformas", {
      ...p, rede: { ...p.rede, escolas_com_dado: { elefante: 3, matific: 6 }, texto_blocos: escopo },
    });
    await abrir();
    // 3 das 6 escolas no Elefante: o número da rede NÃO é o da rede inteira — a tela diz isso.
    expect(screen.getByTestId("participacao-elefante-escolas")).toHaveTextContent(
      "Soma de 3 das 6 escolas: as com a coleta em dia no período (ou cobrindo ao menos 90% dele). As demais ficam "
      + "fora da soma — sem dado não é zero.");
    expect(screen.getByTestId("participacao-matific-escolas"))
      .toHaveTextContent("Soma das 6 escolas da rede (todas com a coleta em dia ou cobrindo ao menos 90% do período).");
    expect(screen.getByTestId("participacao-escopo")).toHaveTextContent(escopo);
  });

  it("sem a contagem de escolas na resposta: nenhuma frase inventada", async () => {
    semearPanorama();
    await abrir();
    expect(screen.queryByTestId("participacao-elefante-escolas")).toBeNull();
    expect(screen.queryByTestId("participacao-escopo")).toBeNull();
  });
});

describe("Todas as escolas da rede", () => {
  it("TODAS, em ordem alfabética: a inativa como inativa, a sem avaliação externa, a sem alunos — cada uma com a ficha", async () => {
    semearPanorama();
    await abrir();
    expect(nomesDaLista()).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEF Sintética Épsilon",
      "EMEF Sintética Zeta", "EMEI Sintética Gama",
    ]);
    expect(screen.getByTestId("todas-as-escolas")).toHaveTextContent("Em ordem alfabética — não é ranking.");
    // Os alunos do painel contam TODAS as etapas (a tela Escolas e o uso, só do 1º ao 5º ano): o rótulo diz.
    expect(screen.getByTestId("todas-as-escolas")).toHaveTextContent("os alunos contam todas as etapas");
    // A Épsilon: inativa no cadastro, nenhum aluno, sem dado — por extenso, sem atividade inventada.
    const epsilon = linha(6);
    expect(within(epsilon).getByTestId("cadastro")).toHaveTextContent("Inativa");
    expect(epsilon).toHaveTextContent("Alunos no ano letivo (todas as etapas)nenhum");
    expect(within(epsilon).getByTestId("situacao-geral")).toHaveTextContent("Sem dado");
    expect(within(epsilon).getByTestId("uso-elefante")).toHaveTextContent("Sem dadonenhum aluno matriculado no ano letivo");
    expect(epsilon).not.toHaveTextContent(/%|Com uso/);
    // A Gama (sem código INEP: nenhuma avaliação externa) aparece; protegida nas plataformas.
    const gama = linha(4);
    expect(within(gama).getByTestId("cadastro")).toHaveTextContent("Ativa");
    expect(within(gama).getByTestId("situacao-geral")).toHaveTextContent("Protegida (poucos alunos)");
    expect(within(gama).getByTestId("uso-matific")).toHaveTextContent("Protegido (poucos alunos)");
    expect(gama).not.toHaveTextContent(/%/);
    // A Zeta: coleta em dia e nenhum uso.
    expect(within(linha(7)).getByTestId("situacao-geral")).toHaveTextContent("Sem uso registrado");
    expect(within(linha(7)).getByTestId("uso-elefante")).toHaveTextContent("nenhum aluno leu um livro no período");
    expect(within(linha(7)).getByTestId("uso-matific")).toHaveTextContent("nenhum aluno fez atividade no período");
    // A Beta: com uso, coleta parcial do Elefante com a data. O Elefante conta também a releitura
    // ("um livro", não "um livro novo"); o Matific, sobre os alunos com dado no período — os mesmos
    // denominadores do cartão "Participação no ano letivo", na mesma página.
    expect(within(linha(3)).getByTestId("uso-elefante"))
      .toHaveTextContent("Com uso85% dos alunos com conta leram ao menos um livro (coleta até 20/09/2026)");
    expect(within(linha(3)).getByTestId("uso-matific"))
      .toHaveTextContent("Com uso75% dos alunos com dado no período fizeram ao menos uma atividade");
    expect(screen.getByTestId("lista-escolas")).not.toHaveTextContent(/livro novo|com conta fizeram/);
    expect(within(linha(3)).getByTestId("situacao-geral")).toHaveTextContent("Com uso no ano letivo");
    // A situação nunca é só cor: a pílula tem o texto e a marca do estado.
    expect(within(linha(3)).getByTestId("situacao-geral").querySelector("[data-estado=com_uso]")).not.toBeNull();
    // O nome leva à ficha da escola.
    expect(within(linha(2)).getByRole("link", { name: "EMEF Sintética Alfa" })).toHaveAttribute("href", "/rede/escolas/2");
    await userEvent.click(within(linha(6)).getByRole("link", { name: "EMEF Sintética Épsilon" }));
    expect(screen.getByTestId("onde")).toHaveTextContent("/rede/escolas/6");
  });

  it("o filtro por situação (com a contagem de cada uma)", async () => {
    semearPanorama();
    await abrir();
    const filtro = screen.getByTestId("filtro-situacao");
    expect(within(filtro).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Todas (6)", "Com uso (3)", "Sem uso registrado (1)", "Sem dado ou protegidas (2)",
    ]);
    expect(within(filtro).getByRole("button", { name: "Todas (6)" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(filtro).getByRole("button", { name: "Com uso (3)" }));
    expect(nomesDaLista()).toEqual(["EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta"]);
    await userEvent.click(within(filtro).getByRole("button", { name: "Sem uso registrado (1)" }));
    expect(nomesDaLista()).toEqual(["EMEF Sintética Zeta"]);
    await userEvent.click(within(filtro).getByRole("button", { name: "Sem dado ou protegidas (2)" }));
    expect(nomesDaLista()).toEqual(["EMEF Sintética Épsilon", "EMEI Sintética Gama"]);
    expect(within(filtro).getByRole("button", { name: "Sem dado ou protegidas (2)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("'sem uso registrado' com coleta PARCIAL: a lista e a contagem por extenso dizem até quando (nunca o 'sem uso' em dia)", async () => {
    semearZetaParcial();
    await abrir();
    const zeta = within(linha(7)).getByTestId("situacao-geral");
    expect(zeta).toHaveTextContent("Sem uso registrado até 15/03/2026 (coleta parcial)");
    expect(zeta.querySelector("[data-estado=sem_uso]")).toHaveTextContent("Sem uso registrado");
    expect(within(linha(7)).getByTestId("uso-elefante")).toHaveTextContent("nenhum uso registrado até 15/03/2026 (coleta parcial)");
    // A contagem por extenso leva a data; não sobra nenhum "sem uso registrado" de coleta em dia.
    const demais = screen.getByTestId("numero-demais");
    expect(demais).toHaveTextContent("1 sem uso registrado até 15/03/2026 (coleta parcial) · 1 sem dado · 1 protegida");
    expect(demais).not.toHaveTextContent(/1 sem uso registrado ·/);
    // A escola continua no filtro "Sem uso registrado" (com a data na linha).
    await userEvent.click(within(screen.getByTestId("filtro-situacao")).getByRole("button", { name: "Sem uso registrado (1)" }));
    expect(nomesDaLista()).toEqual(["EMEF Sintética Zeta"]);
  });

  it("a ficha da escola diz a mesma situação geral, com a data da coleta parcial", async () => {
    semearZetaParcial();
    responderErro("GET", (c: string) => /^\/escolas\/7\/analise(\?|$)/.test(c), 500, "SEM-AVALIACAO-NO-TESTE");
    renderComApp(
      <Routes><Route path="/rede/escolas/:escolaId" element={<FichaEscolaRede />} /></Routes>,
      { usuario: secretaria, rota: "/rede/escolas/7" },
    );
    expect(await screen.findByTestId("ficha-situacao-uso"))
      .toHaveTextContent("Situação: Sem uso registrado até 15/03/2026 (coleta parcial)");
  });

  it("a ficha da escola com a coleta em dia: 'Sem uso registrado', sem data nem 'parcial'", async () => {
    semearPanorama();
    responderErro("GET", (c: string) => /^\/escolas\/7\/analise(\?|$)/.test(c), 500, "SEM-AVALIACAO-NO-TESTE");
    renderComApp(
      <Routes><Route path="/rede/escolas/:escolaId" element={<FichaEscolaRede />} /></Routes>,
      { usuario: secretaria, rota: "/rede/escolas/7" },
    );
    const uso = await screen.findByTestId("ficha-situacao-uso");
    expect(uso).toHaveTextContent("Situação: Sem uso registrado");
    expect(uso).not.toHaveTextContent(/parcial|até \d/);
    expect(screen.queryByTestId("ficha-situacao-complemento")).toBeNull();
  });

  it("um DOM só (cartões no celular, linhas no desktop): os rótulos de cada campo estão no próprio item", async () => {
    semearPanorama();
    await abrir();
    const alfa = linha(2);
    const rotulos = Array.from(alfa.querySelectorAll("dt")).map((dt) => dt.textContent);
    expect(rotulos).toEqual(["Cadastro", "Alunos no ano letivo (todas as etapas)", "Elefante", "Matific", "Situação geral"]);
    // Nenhum nome de escola duplicado (sem render duplo para o celular).
    expect(screen.getAllByRole("link", { name: "EMEF Sintética Zeta" })).toHaveLength(1);
    // O cabeçalho das colunas (desktop) também diz que os alunos são de todas as etapas.
    expect(screen.getByTestId("todas-as-escolas")).toHaveTextContent("Alunos (todas as etapas)");
  });

  it("o uso não carregou (as plataformas falharam): TODAS as escolas do painel continuam, com a ficha e o uso por extenso", async () => {
    semearPanorama();
    responderErro("GET", "/redes/1/analise/plataformas", 500, "FALHA-USO");
    renderTela("/", <PanoramaSecretaria />);
    const lista = await screen.findByTestId("lista-escolas");
    // As 6 do painel (a inativa e a sem alunos inclusive), em ordem alfabética, cada uma com a ficha.
    expect(nomesDaLista()).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEF Sintética Épsilon",
      "EMEF Sintética Zeta", "EMEI Sintética Gama",
    ]);
    expect(within(linha(6)).getByRole("link", { name: "EMEF Sintética Épsilon" })).toHaveAttribute("href", "/rede/escolas/6");
    expect(within(linha(6)).getByTestId("cadastro")).toHaveTextContent("Inativa");
    expect(linha(2)).toHaveTextContent("Alunos no ano letivo (todas as etapas)150");
    // O uso por extenso em cada escola — nunca "sem uso", "sem dado" nem um número.
    for (const li of within(lista).getAllByRole("listitem")) {
      expect(within(li).getByTestId("uso-indisponivel")).toHaveTextContent("não foi possível carregar o uso");
      expect(li).toHaveAttribute("data-situacao", "uso_indisponivel");
    }
    expect(lista).not.toHaveTextContent(/Sem uso|Sem dado|Com uso|Protegid|%/);
    expect(screen.getByTestId("lista-sem-uso")).toHaveTextContent(
      "Não foi possível carregar o uso das plataformas (FALHA-USO): a lista mostra o cadastro e os alunos de cada escola");
    // Sem situação, sem filtro (não há o que filtrar); a seção não vira só a mensagem de erro.
    expect(screen.queryByTestId("filtro-situacao")).toBeNull();
    expect(screen.queryByText(/Não foi possível carregar as escolas da rede/)).toBeNull();
    // Os números de uso dizem que não carregaram (nunca 0); o cadastro continua.
    expect(screen.getByTestId("numero-com-uso")).toHaveTextContent("não foi possível carregar");
    expect(screen.getByTestId("numero-cadastradas")).toHaveTextContent("Escolas cadastradas6");
    await userEvent.click(within(linha(3)).getByRole("link", { name: "EMEF Sintética Beta" }));
    expect(screen.getByTestId("onde")).toHaveTextContent("/rede/escolas/3");
  });

  it("enquanto o uso carrega, a lista espera (não aparece uma lista sem filtro que muda logo depois)", async () => {
    semearPanorama();
    responder("GET", "/redes/1/analise/plataformas", () => new Promise(() => {}));
    renderTela("/", <PanoramaSecretaria />);
    await screen.findByTestId("numero-cadastradas");
    await waitFor(() => expect(screen.getByTestId("numero-cadastradas")).toHaveTextContent("Escolas cadastradas6"));
    expect(screen.getByTestId("todas-as-escolas")).toHaveTextContent("Carregando as escolas da rede...");
    expect(screen.queryByTestId("lista-escolas")).toBeNull();
    expect(screen.queryByTestId("uso-indisponivel")).toBeNull();
  });
});

describe("Escolas em destaque e a vitrine", () => {
  it("o critério ESCRITO (o mesmo da vitrine), as escolas de cada plataforma com o link para a ficha e o Ranking", async () => {
    semearPanorama();
    await abrir();
    const criterio = screen.getByTestId("criterio-destaques");
    expect(criterio).toHaveTextContent("Critério (o mesmo da vitrine pública)");
    expect(criterio).toHaveTextContent("livros lidos desde o início da conta de cada aluno");
    expect(criterio).toHaveTextContent("estrelas por aluno no ano letivo");
    expect(criterio).toHaveTextContent("Entram só escolas ativas, com pelo menos 5 alunos do 1º ao 5º ano");
    // Quem soma, POR PLATAFORMA (livro na leitura, estrela na matemática).
    expect(criterio).toHaveTextContent(
      "na leitura, pelo menos 5 deles com algum livro lido; na matemática, pelo menos 5 deles com alguma estrela");
    expect(criterio).not.toHaveTextContent(/livro lido ou alguma estrela/);
    expect(criterio).toHaveTextContent("Aparecem as 5 maiores de cada plataforma");
    expect(screen.getByTestId("escolas-em-destaque").querySelector("[data-natureza=calculado]"))
      .toHaveTextContent("Calculado pelo Constela");
    // O critério vem ANTES das listas.
    expect(criterio.compareDocumentPosition(screen.getByTestId("destaques-leitura")) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    const leitura = screen.getByTestId("destaques-leitura");
    expect(within(leitura).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "1.EMEF Sintética Alfa12,4 livros por aluno", "2.EMEF Sintética Delta9,7 livros por aluno",
    ]);
    expect(within(leitura).getByRole("link", { name: "EMEF Sintética Delta" })).toHaveAttribute("href", "/rede/escolas/5");
    expect(screen.getByTestId("destaques-leitura-fora")).toHaveTextContent(
      "1 escola ficou fora desta lista para proteger as crianças: o número dela fica protegido (poucos alunos).");
    expect(within(screen.getByTestId("destaques-matematica")).getByRole("link", { name: "EMEF Sintética Beta" }))
      .toHaveAttribute("href", "/rede/escolas/3");
    expect(screen.queryByTestId("destaques-matematica-fora")).toBeNull();
    // O Ranking da Rede é OUTRA medida (a pontuação do Constela), não a continuação destes destaques:
    // o nome do link e a frase dizem isso (antes: "Ver a ordem completa no Ranking da Rede").
    expect(screen.getByRole("link", { name: "Ranking da Rede (pontuação do Constela — outra medida)" }))
      .toHaveAttribute("href", "/rede/ranking");
    expect(screen.queryByText(/ordem completa/)).toBeNull();
    expect(screen.getByTestId("ranking-outra-medida")).toHaveTextContent(
      "A ordem do Ranking da Rede é a da pontuação do Constela, não os livros por aluno ou as estrelas por aluno "
      + "destes destaques: as posições podem ser diferentes.");
    // No celular, o nome longo não fica espremido ao lado do valor: a linha quebra (o valor desce).
    for (const li of within(leitura).getAllByRole("listitem")) expect(li).toHaveClass("flex-wrap");
  });

  it("matéria contratada sem escola elegível (o servidor manda escolas: []): o vazio por extenso nas duas", async () => {
    semearPanorama();
    responder("GET", "/redes/1/destaques", destaquesRede({
      leitura: { escolas: [], fora_por_protecao: 0 }, matematica: { escolas: [], fora_por_protecao: 0 },
    }));
    await abrir();
    for (const materia of ["leitura", "matematica"]) {
      const card = screen.getByTestId(`destaques-${materia}`);
      expect(screen.getByTestId(`destaques-${materia}-vazio`))
        .toHaveTextContent("Nenhuma escola com dados suficientes para este critério ainda.");
      expect(within(card).queryByRole("listitem")).toBeNull();
      expect(screen.queryByTestId(`destaques-${materia}-fora`)).toBeNull();
    }
    // O critério continua escrito e o caminho para o Ranking continua lá.
    expect(screen.getByTestId("criterio-destaques")).toHaveTextContent("Entram só escolas ativas");
    expect(screen.getByRole("link", { name: /Ranking da Rede \(pontuação do Constela — outra medida\)/ })).toBeInTheDocument();
  });

  it("lista vazia porque as que entrariam ficaram fora por proteção: UMA frase, coerente (não 'sem dados suficientes')", async () => {
    semearPanorama();
    responder("GET", "/redes/1/destaques", destaquesRede({ leitura: { escolas: [], fora_por_protecao: 1 } }));
    await abrir();
    const leitura = screen.getByTestId("destaques-leitura");
    expect(screen.getByTestId("destaques-leitura-vazio")).toHaveTextContent(textoDestaquesVazio(1));
    expect(leitura).toHaveTextContent("a única que entraria ficou fora para proteger as crianças");
    expect(leitura).not.toHaveTextContent("dados suficientes");
    // Nada da segunda frase (a de quem ficou fora abaixo de uma lista com escolas).
    expect(screen.queryByTestId("destaques-leitura-fora")).toBeNull();
    expect(leitura.textContent?.match(/fora/g)).toHaveLength(1);
  });

  it("os destaques com erro não derrubam a tela", async () => {
    semearPanorama();
    responderErro("GET", "/redes/1/destaques", 500, "FALHA-DESTAQUES");
    renderTela("/", <PanoramaSecretaria />);
    expect(await screen.findByText("Não foi possível carregar as escolas em destaque: FALHA-DESTAQUES")).toBeInTheDocument();
    expect(await screen.findByTestId("lista-escolas")).toBeInTheDocument();
    expect(screen.getByTestId("conclusao-rede")).toHaveTextContent("3 com uso");
  });

  it("'Reconhecimento público' logo abaixo dos destaques: a vitrine da rede, com Ligar e as matérias contratadas", async () => {
    semearPanorama();
    await abrir();
    const reconhecimento = screen.getByTestId("reconhecimento-publico");
    expect(reconhecimento).toHaveTextContent("A vitrine pública usa o mesmo critério das escolas em destaque");
    // Uma escola ficou fora da leitura para proteger as crianças: a vitrine NÃO mostra "estas mesmas" escolas.
    expect(reconhecimento).not.toHaveTextContent(/estas mesmas|as mesmas escolas/);
    expect(reconhecimento).toHaveTextContent(
      "Os destaques acima têm menos escolas que a vitrine: aqui fica de fora a escola com o número protegido (poucos alunos).");
    expect(within(reconhecimento).getByRole("heading", { level: 3, name: /Vitrine pública/ })).toBeInTheDocument();
    expect(await within(reconhecimento).findByRole("button", { name: "Ligar vitrine pública" })).toBeInTheDocument();
    expect(reconhecimento).toHaveTextContent("as 5 melhores escolas em leitura e matemática — sem nome de criança");
    const destaques = screen.getByTestId("escolas-em-destaque");
    expect(destaques.compareDocumentPosition(reconhecimento) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("vitrine no ar: copiar e abrir o link do servidor; sem escola fora por proteção, nada de 'menos escolas'", async () => {
    semearPanorama();
    responder("GET", "/redes/1/publico", { ativo: true, token: "tok", url: "https://vitrine.exemplo.test/rede/p/tok" });
    const d = destaquesRede();
    responder("GET", "/redes/1/destaques", destaquesRede({ leitura: { ...d.leitura!, fora_por_protecao: 0 } }));
    await abrir();
    const reconhecimento = screen.getByTestId("reconhecimento-publico");
    expect(reconhecimento).toHaveTextContent("A vitrine pública usa o mesmo critério das escolas em destaque");
    expect(reconhecimento).not.toHaveTextContent("menos escolas");
    expect(await within(reconhecimento).findByRole("link", { name: /Abrir vitrine/ }))
      .toHaveAttribute("href", "https://vitrine.exemplo.test/rede/p/tok");
    expect(within(reconhecimento).getByRole("button", { name: /Copiar link/ })).toBeInTheDocument();
    expect(within(reconhecimento).getByRole("button", { name: /Desligar/ })).toBeInTheDocument();
  });
});

describe("Metas da rede (recolhida)", () => {
  it("fechada de início (sem ler as metas); ao abrir, o progresso e o cadastro da rede", async () => {
    semearPanorama();
    await abrir();
    const botao = screen.getByRole("button", { name: "Metas da rede" });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    expect(chamadas("/redes/1/metas")).toHaveLength(0);
    await userEvent.click(botao);
    expect(botao).toHaveAttribute("aria-expanded", "true");
    const metas = screen.getByTestId("metas-da-rede");
    expect(await within(metas).findByRole("heading", { level: 3, name: "Progresso das metas" })).toBeInTheDocument();
    expect(within(metas).getByRole("heading", { level: 3, name: "Cadastro das metas" })).toBeInTheDocument();
    expect(await within(metas).findByText(/Nenhuma meta definida ainda. Cadastre a primeira em “Cadastro das metas”/))
      .toBeInTheDocument();
    expect(chamadas("/redes/1/metas")).toHaveLength(1);
  });

  it("cada meta diz de quando é o número (livros desde o início da conta; adoção sem período, não é uso)", async () => {
    semearPanorama();
    responder("GET", "/redes/1/metas", METAS);
    await abrir();
    expect(screen.getByTestId("metas-da-rede")).toHaveTextContent("As metas não seguem todas o ano letivo");
    await userEvent.click(screen.getByRole("button", { name: "Metas da rede" }));
    const notas = await within(screen.getByTestId("metas-da-rede")).findAllByTestId("nota-da-meta");
    expect(notas.map((n) => n.textContent)).toEqual([
      "soma os livros lidos desde o início da conta de cada aluno (não só no ano letivo)",
      "parte dos alunos com conta ou dado em alguma plataforma, sem período — não é uso",
      "atividades do ano letivo no Matific, pela última coleta",
    ]);
  });

  it("o Painel da Rede (as mesmas metas, sem a nota): fica igual", async () => {
    responder("GET", "/redes/1/metas", METAS);
    renderComApp(<MetasDaRede redeId={1} />, { usuario: secretaria });
    expect(await screen.findByText("12.400,0")).toBeInTheDocument();
    expect(screen.queryByTestId("nota-da-meta")).toBeNull();
  });
});

describe("Rede só com o Matific", () => {
  it("nenhum produto não contratado: participação, escolas, destaques, critério e vitrine só do Matific", async () => {
    semearPanorama();
    const p = plataformasDoPanorama();
    responder("GET", "/redes/1/dashboard", painelDoPanorama(["matematica"]));
    responder("GET", "/redes/1/analise/plataformas", {
      ...p, modulos: { elefante: false, matific: true }, rede: { ...p.rede, elefante: null },
      escolas: p.escolas.map((e) => ({ ...e, elefante: null })),
    });
    responder("GET", "/redes/1/destaques", destaquesRede({ modulos: ["matematica"], leitura: null }));
    const { container } = await abrir();
    await screen.findByTestId("destaques-matematica");
    await screen.findByRole("button", { name: "Ligar vitrine pública" });
    expect(screen.queryByTestId("destaques-leitura")).toBeNull();
    expect(screen.queryByTestId("participacao-elefante")).toBeNull();
    expect(screen.getByTestId("participacao-matific")).toBeInTheDocument();
    expect(screen.getByTestId("conclusao-plataformas")).not.toHaveTextContent("Elefante");
    expect(within(linha(2)).queryByTestId("uso-elefante")).toBeNull();
    expect(within(linha(2)).getByTestId("uso-matific")).toBeInTheDocument();
    expect(screen.getByTestId("numero-com-uso").querySelector("[data-o-que-mede]")).toHaveTextContent(
      "pelo menos um aluno do 1º ao 5º ano fez uma atividade no Matific no ano letivo");
    expect(screen.getByTestId("criterio-destaques")).not.toHaveTextContent(/Leitura|livro/);
    expect(screen.getByTestId("reconhecimento-publico")).toHaveTextContent("as 5 melhores escolas em matemática — sem nome");
    // O Ranking é outra medida — e a frase cita só as estrelas (nada de livros numa rede sem o Elefante).
    expect(screen.getByTestId("ranking-outra-medida")).toHaveTextContent(
      "A ordem do Ranking da Rede é a da pontuação do Constela, não as estrelas por aluno destes destaques");
    expect(screen.getByTestId("ranking-outra-medida")).not.toHaveTextContent(/livro/);
    expect(within(linha(3)).getByTestId("uso-matific"))
      .toHaveTextContent("75% dos alunos com dado no período fizeram ao menos uma atividade");
    expect(container).not.toHaveTextContent(/Elefante|livros? (novos?|lidos?)/);
  });
});

describe("Visão da rede — o admin global", () => {
  it("a mesma tela com o h1 do menu dele, o seletor de rede e todos os links levando a rede escolhida", async () => {
    semearPanorama();
    responder("GET", "/redes", [{ id: 2, nome: "Rede Sintética Sul" }, { id: 1, nome: "Rede Sintética Norte" }]);
    renderTela("/rede/visao", <PanoramaSecretaria />, { usuario: admin });
    await screen.findByTestId("lista-escolas");
    await screen.findByTestId("destaques-leitura");
    expect(screen.getByRole("heading", { level: 1, name: "Visão da rede" })).toBeInTheDocument();
    // A primeira em ordem alfabética (Norte), com o seletor porque há duas.
    expect(screen.getByLabelText("Rede analisada")).toHaveValue("1");
    await waitFor(() => expect(screen.getByTestId("secretaria-rede-nome")).toHaveTextContent("Rede Sintética Norte"));
    expect(within(linha(2)).getByRole("link", { name: "EMEF Sintética Alfa" })).toHaveAttribute("href", "/rede/escolas/2?rede=1");
    expect(within(screen.getByTestId("destaques-leitura")).getByRole("link", { name: "EMEF Sintética Delta" }))
      .toHaveAttribute("href", "/rede/escolas/5?rede=1");
    expect(screen.getByRole("link", { name: /Ver o uso em detalhe/ })).toHaveAttribute("href", "/rede/plataformas?rede=1");
    expect(screen.getByRole("link", { name: "Avaliações externas" })).toHaveAttribute("href", "/rede/avaliacoes-externas?rede=1");
    expect(screen.getByRole("link", { name: /Comparar escolas lado a lado/ })).toHaveAttribute("href", "/rede/escolas?rede=1");
    // Os Relatórios e exportações e as Escolas em acompanhamento: o global não os tem no menu e
    // chegava a eles por aqui — no rodapé, com a rede escolhida.
    const atalhos = within(screen.getByTestId("rodape-panorama")).getByTestId("atalhos-do-global");
    expect(within(atalhos).getByRole("link", { name: "Relatórios e exportações" }))
      .toHaveAttribute("href", "/rede/relatorios?rede=1");
    expect(within(atalhos).getByRole("link", { name: "Escolas em acompanhamento" }))
      .toHaveAttribute("href", "/rede/acompanhamento?rede=1");
    // A vitrine e as metas são as da rede ESCOLHIDA aqui (não a que o Painel da Rede abre).
    await waitFor(() => expect(chamadas("/redes/1/publico").length).toBeGreaterThan(0));
    expect(chamadas("/redes/2/publico")).toHaveLength(0);
  });

  it("a Secretaria não vê os atalhos do global (Relatórios e exportações, Escolas em acompanhamento)", async () => {
    semearPanorama();
    await abrir();
    expect(screen.queryByTestId("atalhos-do-global")).toBeNull();
    expect(screen.queryByRole("link", { name: "Relatórios e exportações" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Escolas em acompanhamento" })).toBeNull();
  });

  it("o Ranking da Rede numa rede que ele não abre: o aviso diz qual rede o Ranking mostra", async () => {
    semearPanorama();
    // O servidor lista a Sul primeiro: o Ranking (que ainda não troca de rede) abre a Sul; aqui está a Norte.
    responder("GET", "/redes", [{ id: 2, nome: "Rede Sintética Sul" }, { id: 1, nome: "Rede Sintética Norte" }]);
    renderTela("/rede/visao", <PanoramaSecretaria />, { usuario: admin });
    await screen.findByTestId("destaques-leitura");
    expect(screen.getByRole("link", { name: /Ranking da Rede \(pontuação do Constela — outra medida\)/ }))
      .toHaveAttribute("href", "/rede/ranking?rede=1");
    expect(within(screen.getByTestId("escolas-em-destaque")).getByTestId("aviso-outra-rede"))
      .toHaveTextContent("O Ranking da Rede abre a rede “Rede Sintética Sul”, não a escolhida aqui");
  });

  it("na rede que o Ranking abre: sem aviso (e a Secretaria nunca vê o aviso)", async () => {
    semearPanorama();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }, { id: 2, nome: "Rede Sintética Sul" }]);
    renderTela("/rede/visao", <PanoramaSecretaria />, { usuario: admin });
    await screen.findByTestId("destaques-leitura");
    expect(screen.queryByTestId("aviso-outra-rede")).toBeNull();
  });
});
