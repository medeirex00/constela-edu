/**
 * A SITUAÇÃO DE USO de cada escola (DESENHO3 §2, `situacaoDeUso.ts`) — função pura: junta o
 * cartão do painel (`/dashboard`: cadastro e alunos) com a escola das plataformas no ano letivo
 * (`/analise/plataformas`) e diz, por plataforma CONTRATADA e no geral, se há uso, se não há uso
 * registrado, se falta dado (e qual) ou se o número está protegido. Ausência nunca vira "sem
 * uso"; o painel (contas e retratos sem período) nunca decide uso.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import type { EscolaPlataformas, MetricasElefante, MetricasMatific } from "../pages/analise/tipos";
import {
  ROTULO_ESTADO, classificarEscola, classificarRede, complementoDoGeral, contarSituacoes, datasDoSemUsoParcial,
  escolasDoCadastro, rotuloGeral, usoDaPlataforma,
} from "../pages/rede/secretaria/situacaoDeUso";
import { cartaoEscola, painelDoPanorama, plataformasDoPanorama } from "./SecretariaFixtures";

const AS_DUAS = { elefante: true, matific: true };

function elefante(over: Partial<MetricasElefante> = {}): MetricasElefante {
  return {
    alunos_medidos: 40, alunos_com_leitura: 30, participacao_pct: 75, livros_por_aluno: 2.5, minutos_por_aluno: 30,
    nivel_medio: "J", taxa_acerto_pct: 70, janela_questoes: null, coleta_parcial: false, coberto_ate: null,
    texto_cobertura: null, metricas_protegidas: [], motivo_sem_dado: null, texto_sem_dado: null, ...over,
  };
}

function matific(over: Partial<MetricasMatific> = {}): MetricasMatific {
  return {
    alunos_medidos: 40, alunos_com_retrato: 40, participacao_pct: 60, atividades_por_aluno: 9, estrelas_por_aluno: 20,
    desempenho_medio: 2.2, coleta_parcial: false, coberto_ate: null, texto_cobertura: null, metricas_protegidas: [],
    motivo_sem_dado: null, texto_sem_dado: null, ...over,
  };
}

function escola(over: Partial<EscolaPlataformas> = {}): EscolaPlataformas {
  return {
    escola_id: 9, nome: "EMEF Sintética Teste", alunos: 50, suprimido: false,
    cobertura: { elefante: "ok", matific: "ok" }, ultima_coleta: null, coberto_ate: null,
    elefante: elefante(), matific: matific(), series: [], ...over,
  };
}

describe("Uso de UMA plataforma", () => {
  it("com uso: a participação por extenso (Elefante pelos alunos que leram; Matific pela taxa)", () => {
    // O denominador de CADA plataforma (o do cartão da rede e da conclusão): no Elefante, os alunos
    // com conta; no Matific, os alunos com dado no período. O número do Elefante conta também a
    // releitura: "um livro", nunca "um livro novo".
    expect(usoDaPlataforma("elefante", escola())).toEqual({
      estado: "com_uso", texto: "75% dos alunos com conta leram ao menos um livro", ate: null,
    });
    expect(usoDaPlataforma("matific", escola())).toEqual({
      estado: "com_uso", texto: "60% dos alunos com dado no período fizeram ao menos uma atividade", ate: null,
    });
    expect(usoDaPlataforma("matific", escola()).texto).not.toContain("com conta");
    // O Elefante decide pelos alunos que leram, mesmo sem a taxa.
    const soContagem = escola({ elefante: elefante({ participacao_pct: null, alunos_com_leitura: 3 }) });
    expect(usoDaPlataforma("elefante", soContagem)).toMatchObject({
      estado: "com_uso", texto: "pelo menos um aluno leu um livro",
    });
    const soMatific = escola({ matific: matific({ participacao_pct: null }), series: [
      { serie: 3, alunos: 20, suprimido: false, elefante: null, matific: matific({ participacao_pct: 40 }) },
    ] });
    expect(usoDaPlataforma("matific", soMatific).texto).toMatch(/^pelo menos um aluno fez uma atividade/);
  });

  it("coleta parcial: com uso, a frase diz até quando vale (a data do bloco ou da escola)", () => {
    const parcial = escola({
      cobertura: { elefante: "coleta_parcial", matific: "ok" },
      elefante: elefante({ coleta_parcial: true, coberto_ate: "2026-09-20T00:10:00-03:00" }),
    });
    expect(usoDaPlataforma("elefante", parcial)).toEqual({
      estado: "com_uso", texto: "75% dos alunos com conta leram ao menos um livro (coleta até 20/09/2026)",
      ate: "20/09/2026",
    });
    // Só a cobertura da escola marca o parcial; a data vem de `coberto_ate` da escola.
    const pelaEscola = escola({
      cobertura: { elefante: "ok", matific: "coleta_parcial" },
      coberto_ate: { elefante: null, matific: "2026-08-31T03:00:00" },
    });
    expect(usoDaPlataforma("matific", pelaEscola).ate).toBe("31/08/2026");
  });

  it("sem uso registrado: só com a coleta em dia (ou parcial, com a data) e o número zero", () => {
    const zero = escola({ elefante: elefante({ alunos_com_leitura: 0, participacao_pct: 0 }),
                          matific: matific({ participacao_pct: 0 }) });
    expect(usoDaPlataforma("elefante", zero)).toEqual({
      estado: "sem_uso", texto: "nenhum aluno leu um livro no período", ate: null,
    });
    expect(usoDaPlataforma("matific", zero)).toEqual({
      estado: "sem_uso", texto: "nenhum aluno fez atividade no período", ate: null,
    });
    const parcialZero = escola({
      cobertura: { elefante: "coleta_parcial", matific: "ok" },
      elefante: elefante({ alunos_com_leitura: 0, participacao_pct: 0, coleta_parcial: true, coberto_ate: "2026-09-20" }),
    });
    expect(usoDaPlataforma("elefante", parcialZero)).toEqual({
      estado: "sem_uso", texto: "nenhum uso registrado até 20/09/2026 (coleta parcial)", ate: "20/09/2026",
    });
  });

  it("zero SEM a coleta em dia (cobertura desconhecida) não é 'sem uso': é sem dado", () => {
    const semCobertura = escola({ cobertura: null, elefante: elefante({ alunos_com_leitura: 0, participacao_pct: 0 }) });
    expect(usoDaPlataforma("elefante", semCobertura)).toEqual({
      estado: "sem_dado", texto: "sem coleta em dia do Elefante", ate: null,
    });
  });

  it("sem dado, por cada motivo, com o texto do servidor (nunca 0)", () => {
    const motivos: [string, string][] = [
      ["sem_coleta", "a escola não tem nenhuma coleta desta plataforma"],
      ["sem_coleta_no_periodo", "nenhuma coleta desta plataforma cobre o período pedido"],
      ["sem_conta_na_plataforma", "nenhum aluno deste recorte tem conta nesta plataforma"],
      ["modulo_nao_contratado", "a rede não contratou este módulo"],
    ];
    for (const [motivo, texto] of motivos) {
      const e = escola({ elefante: elefante({ participacao_pct: null, alunos_com_leitura: null, motivo_sem_dado: motivo,
                                               texto_sem_dado: texto }) });
      expect(usoDaPlataforma("elefante", e)).toEqual({ estado: "sem_dado", texto, ate: null });
    }
    // Sem o texto do servidor: o nome da plataforma.
    const semTexto = escola({ matific: matific({ participacao_pct: null, motivo_sem_dado: "sem_coleta" }) });
    expect(usoDaPlataforma("matific", semTexto)).toEqual({ estado: "sem_dado", texto: "sem dado do Matific", ate: null });
    // Sem a escola na análise, ou sem o bloco.
    expect(usoDaPlataforma("elefante", undefined))
      .toEqual({ estado: "sem_dado", texto: "sem dado das plataformas para esta escola", ate: null });
    expect(usoDaPlataforma("matific", escola({ matific: null })))
      .toEqual({ estado: "sem_dado", texto: "sem dado do Matific", ate: null });
  });

  it("sem aluno do 1º ao 5º ano: com matrícula, diz que as plataformas medem do 1º ao 5º; sem nenhuma, diz isso", () => {
    const e = escola({
      alunos: 0, cobertura: { elefante: "sem_alunos_no_recorte", matific: "sem_alunos_no_recorte" },
      elefante: elefante({ participacao_pct: null, alunos_com_leitura: null, motivo_sem_dado: "sem_alunos_no_recorte",
                           texto_sem_dado: "nenhum aluno ativo do 1º ao 5º ano matriculado no ano letivo" }),
    });
    expect(usoDaPlataforma("elefante", e, 35)).toEqual({
      estado: "sem_dado", texto: "só alunos fora do 1º ao 5º ano (as plataformas são medidas do 1º ao 5º ano)", ate: null,
    });
    expect(usoDaPlataforma("elefante", e, 0)).toEqual({
      estado: "sem_dado", texto: "nenhum aluno matriculado no ano letivo", ate: null,
    });
    // Sem o cartão do painel: o texto do servidor.
    expect(usoDaPlataforma("elefante", e).texto).toBe("nenhum aluno ativo do 1º ao 5º ano matriculado no ano letivo");
  });

  it("protegido: escola suprimida; motivo de poucos alunos (ou séries suprimidas)", () => {
    const suprimida = escola({ suprimido: true, texto_supressao: "poucos alunos (texto sintético)", elefante: null,
                               matific: null, cobertura: null });
    expect(usoDaPlataforma("elefante", suprimida))
      .toEqual({ estado: "protegido", texto: "poucos alunos (texto sintético)", ate: null });
    for (const motivo of ["poucos_alunos_medidos", "series_suprimidas"]) {
      const e = escola({ matific: matific({ participacao_pct: null, motivo_sem_dado: motivo, texto_sem_dado: "protegido (sintético)" }) });
      expect(usoDaPlataforma("matific", e)).toEqual({ estado: "protegido", texto: "protegido (sintético)", ate: null });
    }
  });

  it("métrica protegida no total: com série VISÍVEL com uso é 'com uso' (o total segue protegido); sem, protegido", () => {
    const protegidoNoTotal = elefante({ alunos_com_leitura: null, participacao_pct: null,
                                        metricas_protegidas: ["alunos_com_leitura", "participacao_pct"] });
    const serie = (n: number, uso: number, suprimido = false) => ({
      serie: n, alunos: 20, suprimido, elefante: suprimido ? null : elefante({ alunos_com_leitura: uso, participacao_pct: uso ? 50 : 0 }),
      matific: null,
    });
    const comSerie = escola({ elefante: protegidoNoTotal, series: [serie(2, 0), serie(3, 8)] });
    expect(usoDaPlataforma("elefante", comSerie)).toEqual({
      estado: "com_uso", texto: "pelo menos um aluno leu um livro (o total da escola fica protegido: poucos alunos)",
      ate: null,
    });
    // A série com uso SUPRIMIDA não conta; a visível tem zero: protegido.
    const semSerie = escola({ elefante: protegidoNoTotal, series: [serie(2, 0), serie(3, 8, true)] });
    expect(usoDaPlataforma("elefante", semSerie))
      .toEqual({ estado: "protegido", texto: "número protegido (poucos alunos)", ate: null });
    // Sem número E sem a marca de protegido: falta de dado, não proteção.
    const semMarca = escola({ elefante: elefante({ alunos_com_leitura: null, participacao_pct: null }) });
    expect(usoDaPlataforma("elefante", semMarca))
      .toEqual({ estado: "sem_dado", texto: "sem dado do Elefante no período", ate: null });
  });
});

describe("Situação da escola e da rede", () => {
  it("só as plataformas CONTRATADAS: a rede só com o Matific não tem Elefante na situação", () => {
    const s = classificarEscola(cartaoEscola({ escola_id: 9 }), escola(), { elefante: false, matific: true });
    expect(Object.keys(s.plataformas)).toEqual(["matific"]);
    expect(s.geral).toBe("com_uso");
    // Nenhuma contratada: sem dado (nunca "sem uso").
    expect(classificarEscola(cartaoEscola(), escola(), { elefante: false, matific: false }).geral).toBe("sem_dado");
  });

  it("geral: com uso se ALGUMA tem uso; sem uso só se TODAS estão medidas e zeradas; senão protegida ou sem dado", () => {
    const zeroE = elefante({ alunos_com_leitura: 0, participacao_pct: 0 });
    const zeroM = matific({ participacao_pct: 0 });
    const semColeta = matific({ participacao_pct: null, motivo_sem_dado: "sem_coleta", texto_sem_dado: "sem coleta" });
    const protegidoM = matific({ participacao_pct: null, motivo_sem_dado: "poucos_alunos_medidos" });
    const geral = (e: EscolaPlataformas) => classificarEscola(cartaoEscola(), e, AS_DUAS).geral;
    expect(geral(escola({ elefante: zeroE, matific: matific() }))).toBe("com_uso");
    expect(geral(escola({ elefante: zeroE, matific: zeroM }))).toBe("sem_uso");
    expect(geral(escola({ elefante: zeroE, matific: semColeta }))).toBe("sem_dado");
    expect(geral(escola({ elefante: zeroE, matific: protegidoM }))).toBe("protegido");
    expect(geral(escola({ suprimido: true, elefante: null, matific: null }))).toBe("protegido");
    expect(ROTULO_ESTADO.protegido).toBe("Protegida (poucos alunos)");
  });

  it("geral 'sem uso' com coleta PARCIAL: a escola leva a data (a mais antiga das parciais) e a frase diz até quando", () => {
    const zeroE = (ate: string | null) => elefante({ alunos_com_leitura: 0, participacao_pct: 0, coleta_parcial: true,
                                                     coberto_ate: ate });
    const zeroM = matific({ participacao_pct: 0 });
    // Elefante parado em 15/03 (zero até lá) e Matific em dia com zero: o resto do ano do
    // Elefante não foi medido — "sem uso registrado" só até 15/03.
    const uma = classificarEscola(cartaoEscola(), escola({
      cobertura: { elefante: "coleta_parcial", matific: "ok" }, elefante: zeroE("2026-03-15"), matific: zeroM,
    }), AS_DUAS);
    expect(uma).toMatchObject({ geral: "sem_uso", parcialGeral: true, ateGeral: "15/03/2026" });
    expect(complementoDoGeral(uma)).toBe("até 15/03/2026 (coleta parcial)");
    expect(rotuloGeral(uma)).toBe("Sem uso registrado até 15/03/2026 (coleta parcial)");
    // As duas parciais: vale a data MAIS ANTIGA (pela data, não pelo texto: 20/03 é antes de 15/09).
    const duas = classificarEscola(cartaoEscola(), escola({
      cobertura: { elefante: "coleta_parcial", matific: "coleta_parcial" }, elefante: zeroE("2026-09-15"),
      matific: matific({ participacao_pct: 0, coleta_parcial: true, coberto_ate: "2026-03-20T03:00:00" }),
    }), AS_DUAS);
    expect(duas).toMatchObject({ geral: "sem_uso", parcialGeral: true, ateGeral: "20/03/2026" });
    // Parcial sem a data: continua dizendo que a coleta é parcial (nunca o "sem uso" de coleta em dia).
    const semData = classificarEscola(cartaoEscola(), escola({
      cobertura: { elefante: "coleta_parcial", matific: "ok" }, elefante: zeroE(null), matific: zeroM,
    }), AS_DUAS);
    expect(semData).toMatchObject({ geral: "sem_uso", parcialGeral: true, ateGeral: null });
    expect(rotuloGeral(semData)).toBe("Sem uso registrado (coleta parcial)");
    // Todas em dia: a frase de sempre, sem data.
    const emDia = classificarEscola(cartaoEscola(), escola({
      elefante: elefante({ alunos_com_leitura: 0, participacao_pct: 0 }), matific: zeroM,
    }), AS_DUAS);
    expect(emDia).toMatchObject({ geral: "sem_uso", parcialGeral: false, ateGeral: null });
    expect(complementoDoGeral(emDia)).toBeNull();
    expect(rotuloGeral(emDia)).toBe("Sem uso registrado");
    // Com uso (mesmo com coleta parcial): o geral não leva data — a data fica na frase da plataforma.
    const comUso = classificarEscola(cartaoEscola(), escola({
      cobertura: { elefante: "coleta_parcial", matific: "ok" },
      elefante: elefante({ coleta_parcial: true, coberto_ate: "2026-03-15" }),
    }), AS_DUAS);
    expect(comUso).toMatchObject({ geral: "com_uso", parcialGeral: false, ateGeral: null });
    expect(rotuloGeral(comUso)).toBe("Com uso no ano letivo");
    // A contagem por extenso recebe uma data por escola "sem uso" parcial (null: sem a data).
    expect(datasDoSemUsoParcial([uma, duas, semData, emDia, comUso])).toEqual(["15/03/2026", "20/03/2026", null]);
  });

  it("o cadastro vem do painel (ativa × inativa, alunos) e NUNCA decide uso (conta com dado sem coleta = sem dado)", () => {
    const inativa = classificarEscola(cartaoEscola({ status: "inativa", total_alunos: 12 }), escola(), AS_DUAS);
    expect(inativa).toMatchObject({ ativa: false, alunos: 12, geral: "com_uso" });
    // O painel diz 120 alunos com dado e 80% de adoção — sem coleta no período, é sem dado.
    const semColeta = escola({
      cobertura: { elefante: "sem_coleta", matific: "sem_coleta" },
      elefante: elefante({ participacao_pct: null, alunos_com_leitura: null, motivo_sem_dado: "sem_coleta", texto_sem_dado: "sem coleta" }),
      matific: matific({ participacao_pct: null, motivo_sem_dado: "sem_coleta", texto_sem_dado: "sem coleta" }),
    });
    expect(classificarEscola(cartaoEscola({ alunos_com_dados: 120, adocao: 80 }), semColeta, AS_DUAS).geral).toBe("sem_dado");
    // Sem o cartão (só a análise trouxe a escola): cadastro desconhecido, por extenso na tela.
    expect(classificarEscola(undefined, escola(), AS_DUAS)).toMatchObject({ escolaId: 9, ativa: null, alunos: null });
  });

  it("a rede: TODAS as escolas do painel (inativa e sem alunos inclusive), em ordem alfabética, e as contagens", () => {
    const lista = classificarRede(painelDoPanorama().escolas, plataformasDoPanorama());
    expect(lista.map((s) => s.nome)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEF Sintética Épsilon",
      "EMEF Sintética Zeta", "EMEI Sintética Gama",
    ]);
    const porNome = Object.fromEntries(lista.map((s) => [s.nome.split(" ").pop(), s]));
    expect(porNome.Alfa.plataformas).toMatchObject({ elefante: { estado: "com_uso" }, matific: { estado: "protegido" } });
    expect(porNome.Beta.plataformas.elefante).toMatchObject({ estado: "com_uso", ate: "20/09/2026" });
    expect(porNome.Gama).toMatchObject({ geral: "protegido", ativa: true });
    expect(porNome.Épsilon).toMatchObject({ geral: "sem_dado", ativa: false, alunos: 0 });
    expect(porNome.Épsilon.plataformas.elefante?.texto).toBe("nenhum aluno matriculado no ano letivo");
    expect(porNome.Zeta).toMatchObject({ geral: "sem_uso", ativa: true, parcialGeral: false, ateGeral: null });
    expect(contarSituacoes(lista)).toEqual({ com_uso: 3, sem_uso: 1, sem_dado: 1, protegido: 1 });
    // Uma escola só da análise (sem cartão) também entra — com o cadastro desconhecido.
    const extra = plataformasDoPanorama();
    extra.escolas.push(escola({ escola_id: 99, nome: "EMEF Sintética Ômega" }));
    expect(classificarRede(painelDoPanorama().escolas, extra).map((s) => s.escolaId)).toContain(99);
  });

  it("sem a leitura do uso: TODAS as escolas do painel, em ordem alfabética, só com o cadastro (nada de uso)", () => {
    const lista = escolasDoCadastro(painelDoPanorama().escolas);
    expect(lista.map((e) => e.nome)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEF Sintética Épsilon",
      "EMEF Sintética Zeta", "EMEI Sintética Gama",
    ]);
    expect(lista.find((e) => e.escolaId === 6)).toEqual({ escolaId: 6, nome: "EMEF Sintética Épsilon", ativa: false, alunos: 0 });
    // Só o cadastro: nenhuma situação de uso inventada.
    for (const e of lista) expect(Object.keys(e).sort()).toEqual(["alunos", "ativa", "escolaId", "nome"]);
  });
});
