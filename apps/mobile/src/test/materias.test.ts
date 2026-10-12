/**
 * Notas e rankings POR MATÉRIA no app — as regras das telas Painel, Ranking e
 * Perfil do aluno, com o código REAL de `../materias`.
 *
 * O que estes testes travam (Arquitetura 2; plano de retirada da nota geral,
 * item 11):
 *  - ausência de dado numa matéria é "—", nunca 0,0 — e o zero legítimo
 *    (tem dado, ainda não produziu) continua 0,0;
 *  - matéria fora do plano da rede some, em vez de virar "—";
 *  - pacote antigo do cache (sem `ranking_por_dimensao`) e servidor anterior
 *    degradam para uma MENSAGEM, nunca para um crash nem para a lista legada
 *    ordenada pela nota composta.
 */
import type {
  Dashboard,
  DesempenhoDimensao,
  PacoteSincronizacao,
  PerfilAluno,
  RankingItem,
} from "@constela/core";
import { ApiError } from "@constela/core";
import { describe, expect, it } from "vitest";

import {
  blocosDoPerfil,
  calculoDaMateria,
  estadoDoRanking,
  linhasDaMateria,
  materiasDaEscola,
  materiasDoUsuario,
  mediasDaEscola,
  notasDoItem,
  rankingDaRota,
  totalAferidos,
  valorDaMateria,
} from "../materias";

// Fixtures montadas só com os campos que o app LÊ: nenhuma traz a nota composta,
// que é justamente o que as telas deixaram de consumir.
function item(campos: Partial<RankingItem> = {}): RankingItem {
  return {
    posicao: 1,
    aluno_id: 1,
    nome: "Ana",
    turma: "4ºA",
    ano_escolar: "4º Ano",
    nota_matific: 50,
    nota_elefante: 60,
    ...campos,
  } as RankingItem;
}

function itemDaMateria(materia: "leitura" | "matematica", campos: Partial<RankingItem> = {}) {
  return item({ dimensao: materia, aferido: true, nota: 70, n_aferidos: 21, ...campos });
}

function painel(campos: Partial<Dashboard> = {}): Dashboard {
  return {
    escola: { id: 1, nome: "EM Teste", cidade: null, estado: null, logotipo_url: null,
      ano_letivo_ativo: 2026, status: "ativa" },
    total_alunos: 30,
    total_turmas: 2,
    total_professores: 3,
    total_atividades: 100,
    total_livros: 40,
    tempo_leitura_min: 600,
    top10: [],
    ...campos,
  } as Dashboard;
}

function pacote(campos: Partial<PacoteSincronizacao> = {}): PacoteSincronizacao {
  return {
    gerado_em: "2026-10-12T10:00:00+00:00",
    dashboard: painel(),
    ranking: [],
    evolucao: [],
    alertas: [],
    mural: [],
    ...campos,
  };
}

function perfil(campos: Partial<PerfilAluno> = {}): PerfilAluno {
  return {
    aluno: { id: 7, nome: "Bia", foto_url: null, numero_chamada: null, status: "ativo",
      turma: "4ºA", ano_escolar: "4º Ano" },
    nota_matific: 0,
    nota_elefante: 72,
    posicao: 2,
    detalhes: {
      matific: { indicadores: [], nota: 0 },
      elefante: { indicadores: [], nota: 72 },
    },
    calculada_em: "2026-10-01T00:00:00",
    ...campos,
  } as PerfilAluno;
}

function dimensao(campos: Partial<DesempenhoDimensao>): DesempenhoDimensao {
  return {
    dimensao: "leitura", plataforma: "elefante", contratada: true, aferido: true,
    nota: 72, posicao: 3, n_aferidos: 21, snapshot_em: null, dados: {},
    ...campos,
  };
}

describe("valor de uma matéria: ausência não é zero", () => {
  it("zero legítimo (tem dado) continua 0,0", () => {
    expect(valorDaMateria(0, true)).toBe("0,0");
  });

  it("sem dado da plataforma, nota nula ou nota que nem veio viram —", () => {
    expect(valorDaMateria(80, false)).toBe("—");
    expect(valorDaMateria(null, true)).toBe("—");
    expect(valorDaMateria(undefined, undefined)).toBe("—");
  });

  it("servidor anterior ao carimbo de aferição: mostra o número (não inventa ausência)", () => {
    expect(valorDaMateria(72.5, undefined)).toBe("72,5");
  });
});

describe("quais matérias aparecem (contrato da rede)", () => {
  it("módulos ausentes ou vazios = payload antigo ⇒ as duas, como no web", () => {
    expect(materiasDoUsuario(undefined)).toEqual(["leitura", "matematica"]);
    expect(materiasDoUsuario([])).toEqual(["leitura", "matematica"]);
    expect(materiasDoUsuario(["leitura", "quest"])).toEqual(["leitura"]);
  });

  it("as chaves de ranking_por_dimensao SÃO o contrato da escola (vale até para o admin global)", () => {
    const p = pacote({ ranking_por_dimensao: { leitura: [] } });
    expect(materiasDaEscola(p, ["leitura", "matematica"])).toEqual(["leitura"]);
  });

  it("sem a lista por matéria, a nota NULA no Top prova o módulo fora do plano", () => {
    const p = pacote({
      dashboard: painel({ top10: [item({ nota_matific: null }), item({ aluno_id: 2, nota_matific: null })] }),
    });
    expect(materiasDaEscola(p, undefined)).toEqual(["leitura"]);
  });

  it("servidor anterior (nota numérica) ou Top vazio: valem os módulos do usuário", () => {
    expect(materiasDaEscola(pacote({ dashboard: painel({ top10: [item()] }) }), undefined))
      .toEqual(["leitura", "matematica"]);
    expect(materiasDaEscola(pacote(), ["matematica"])).toEqual(["matematica"]);
    expect(materiasDaEscola(undefined, undefined)).toEqual(["leitura", "matematica"]);
  });
});

describe("aba de uma matéria no Ranking", () => {
  const ociosa = { carregando: false };

  it("usa a lista por matéria do pacote quando ela vem", () => {
    const lista = [itemDaMateria("leitura")];
    const estado = estadoDoRanking("leitura", pacote({ ranking_por_dimensao: { leitura: lista } }), ociosa);
    expect(estado).toEqual({ tipo: "lista", itens: lista });
  });

  it("pacote antigo do cache NUNCA cai na lista legada da nota composta", () => {
    const antigo = pacote({ ranking: [item({ aluno_id: 99, nome: "Legado" })] });
    expect(estadoDoRanking("leitura", antigo, ociosa).tipo).toBe("aviso");
    expect(estadoDoRanking("leitura", antigo, { carregando: true })).toEqual({ tipo: "carregando" });
  });

  it("pacote antigo + rota oficial: usa a lista carimbada com a matéria", () => {
    const daRota = [itemDaMateria("matematica", { nota: 0 })];
    const estado = estadoDoRanking("matematica", pacote(), { dados: daRota, carregando: false });
    expect(estado).toEqual({ tipo: "lista", itens: daRota });
  });

  it("servidor que ignora ?dimensao= (devolve o legado): aviso, não a lista legada", () => {
    expect(rankingDaRota([item()], "leitura")).toBeNull();
    expect(rankingDaRota([itemDaMateria("matematica")], "leitura")).toBeNull();
    expect(rankingDaRota({ detail: "x" }, "leitura")).toBeNull();
    const estado = estadoDoRanking("leitura", pacote(), { dados: [item()], carregando: false });
    expect(estado.tipo).toBe("aviso");
    expect(estado.tipo === "aviso" && estado.texto).toContain("ainda não envia");
  });

  it("nenhum aferido é uma lista vazia válida (não um aviso)", () => {
    expect(estadoDoRanking("leitura", pacote(), { dados: [], carregando: false }))
      .toEqual({ tipo: "lista", itens: [] });
  });

  it("403 da rota = matéria fora do plano; offline sem cache = conecte-se", () => {
    const negado = estadoDoRanking("matematica", pacote(),
      { erro: new ApiError(403, "Módulo não contratado"), carregando: false });
    expect(negado).toEqual({ tipo: "aviso", texto: "Matemática não faz parte do plano desta rede." });
    const offline = estadoDoRanking("leitura", undefined, { carregando: false });
    expect(offline.tipo === "aviso" && offline.texto).toContain("conecte-se");
  });

  it("linhas mostram a nota DA matéria e o denominador carimbado", () => {
    const itens = [
      itemDaMateria("leitura", { nota: 88.5, posicao: 1 }),
      itemDaMateria("leitura", { aluno_id: 2, nota: 0, posicao: 2 }),
      itemDaMateria("leitura", { aluno_id: 3, nota: null, posicao: 3 }),
    ];
    expect(linhasDaMateria(itens).map((l) => l.valor)).toEqual(["88,5", "0,0", "—"]);
    expect(totalAferidos(itens)).toBe(21);
    expect(totalAferidos([itemDaMateria("leitura", { n_aferidos: null })])).toBe(1);
  });
});

describe("Painel: médias e Top por matéria", () => {
  it("Top: — para quem não usa a plataforma, 0,0 para o zero legítimo", () => {
    const notas = notasDoItem(
      item({ nota_elefante: 0, aferido_leitura: true, nota_matific: 0, aferido_matematica: false }),
      ["leitura", "matematica"]);
    expect(notas.map((n) => `${n.rotulo} ${n.valor}`)).toEqual(["Leitura 0,0", "Matemática —"]);
  });

  it("Top: só as matérias da escola", () => {
    expect(notasDoItem(item(), ["leitura"]).map((n) => n.materia)).toEqual(["leitura"]);
  });

  it("média sem ninguém com dado é —, não 0,0", () => {
    const medias = mediasDaEscola(
      painel({ media_leitura: 64.25, alunos_com_dado_leitura: 12,
        media_matematica: 0, alunos_com_dado_matematica: 0 }),
      ["leitura", "matematica"]);
    expect(medias).toEqual([
      { materia: "leitura", rotulo: "Leitura", comDado: 12, valor: "64,25" },
      { materia: "matematica", rotulo: "Matemática", comDado: 0, valor: "—" },
    ]);
  });

  it("pacote anterior às médias por matéria: null (a tela avisa)", () => {
    expect(mediasDaEscola(painel(), ["leitura", "matematica"])).toBeNull();
  });
});

describe("Perfil do aluno por matéria", () => {
  it("usa perfil.dimensoes (oficial): posição por matéria e — sem dado", () => {
    const p = perfil({
      dimensoes: [
        dimensao({ dimensao: "leitura", nota: 72, posicao: 3, n_aferidos: 21 }),
        dimensao({ dimensao: "matematica", plataforma: "matific", aferido: false,
          nota: null, posicao: null, n_aferidos: 18 }),
      ],
    });
    const { blocos, carimbado } = blocosDoPerfil(p, undefined);
    expect(carimbado).toBe(true);
    expect(blocos).toEqual([
      { materia: "leitura", rotulo: "Leitura", aferido: true, valor: "72,0", posicao: "3º de 21" },
      { materia: "matematica", rotulo: "Matemática", aferido: false, valor: "—", posicao: null },
    ]);
    // O passo a passo de quem não tem dado não aparece (seria uma conta de zeros).
    expect(calculoDaMateria(p, blocos[1])).toBeNull();
    expect(calculoDaMateria(p, blocos[0])).toEqual({ indicadores: [], nota: 72 });
  });

  it("matéria fora do plano some; módulos do usuário recortam", () => {
    const p = perfil({ dimensoes: [dimensao({ dimensao: "leitura" })] });
    expect(blocosDoPerfil(p, undefined).blocos.map((b) => b.materia)).toEqual(["leitura"]);
    const ambas = perfil({
      dimensoes: [dimensao({ dimensao: "leitura" }),
        dimensao({ dimensao: "matematica", plataforma: "matific" })],
    });
    expect(blocosDoPerfil(ambas, ["matematica"]).blocos.map((b) => b.materia)).toEqual(["matematica"]);
  });

  it("servidor que não monta dimensoes: lê o bloco que o motor gravou em detalhes", () => {
    const p = perfil({
      dimensoes: [],
      detalhes: {
        elefante: { indicadores: [], nota: 72 },
        matific: { indicadores: [], nota: 0 },
        dimensoes: {
          leitura: { contratada: true, aferido: true, nota: 72, posicao: 1, n_aferidos: 9 },
          matematica: { contratada: false, aferido: false, nota: null, posicao: null, n_aferidos: 0 },
        },
      } as PerfilAluno["detalhes"],
    });
    const { blocos, carimbado } = blocosDoPerfil(p, ["leitura", "matematica"]);
    expect(carimbado).toBe(true);
    expect(blocos).toEqual([
      { materia: "leitura", rotulo: "Leitura", aferido: true, valor: "72,0", posicao: "1º de 9" },
    ]);
  });

  it("perfil sem carimbo nenhum (escola não recalculada) não quebra e avisa", () => {
    const { blocos, carimbado } = blocosDoPerfil(perfil(), undefined);
    expect(carimbado).toBe(false);
    expect(blocos.map((b) => [b.materia, b.valor, b.posicao])).toEqual([
      ["leitura", "72,0", null],
      ["matematica", "0,0", null],
    ]);
  });

  it("sem nota calculada (calculada_em nulo), o 0,0 de preenchimento vira —", () => {
    const vazio = perfil({ calculada_em: null, nota_matific: 0, nota_elefante: 0, detalhes: {} });
    const { blocos } = blocosDoPerfil(vazio, undefined);
    expect(blocos.map((b) => b.valor)).toEqual(["—", "—"]);
    expect(blocos.every((b) => calculoDaMateria(vazio, b) === null)).toBe(true);
  });
});
