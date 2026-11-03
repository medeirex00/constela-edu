/**
 * Os TEXTOS das telas principais da Secretaria (DESENHO2 §1): o "O que mede" de cada indicador
 * e métrica (§1.1), a frase que separa avaliações de plataformas (§1.4), a reescrita dos termos
 * técnicos que o servidor manda (§1.5) e as frases-conclusão (§1, "conclusão primeiro") — sem
 * causalidade, com a ausência por extenso. E os do Panorama da Rede (DESENHO3 §2): cadastradas ×
 * ativas × com uso, as demais por extenso e o critério das escolas em destaque.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import {
  conclusaoAvaliacoes, conclusaoComparacaoAvaliacoes, conclusaoComparacaoPlataformas, conclusaoIndicador,
  conclusaoPlataformas, conclusaoRedeNoConstela, quandoDaJanela, textoDemaisSituacoes, textoDestaquesVazio,
  textoForaPorProtecao, textoReconhecimentoPublico,
} from "../pages/rede/secretaria/conclusoes";
import {
  FRASE_PLATAFORMA, INDICADORES_EXPLICADOS, METRICAS_ELEFANTE, METRICAS_MATIFIC, NOTA_DAS_METAS_NO_PANORAMA,
  O_QUE_MEDE_REDE, ROTULO_LINK_RANKING, criterioDosDestaques, fraseAnosMistos, fraseRankingOutraMedida,
  fraseSeparacao, textoEscolasNaSoma, textoSimples, textosDoFluxoPrincipal,
} from "../pages/rede/secretaria/oQueMede";
import {
  LIMITACOES_COM_RELACAO, METODOLOGIA_COM_RELACAO, catalogo, diagnostico, plataformasRede,
} from "./SecretariaFixtures";

const CAUSAL = /\bcausa|\befeito|impacto|graças/i;
const JARGAO = /Spearman|coorte|\bTPS\b|IC 95|correla|proveni|\bk\s*=/i;

describe("O que mede (§1.1)", () => {
  it("os cinco indicadores oficiais e as métricas das duas plataformas têm a frase, sem causa nem jargão", () => {
    expect(Object.keys(INDICADORES_EXPLICADOS).sort()).toEqual(["ica", "ideb", "iee", "saeb", "saresp"]);
    const textos = [
      ...Object.values(INDICADORES_EXPLICADOS).flatMap((i) => [i.oQueMede, i.abrangencia, i.frequencia, i.meta]),
      ...METRICAS_ELEFANTE.map((m) => m.oQueMede), ...METRICAS_MATIFIC.map((m) => m.oQueMede), FRASE_PLATAFORMA,
    ];
    for (const t of textos) {
      expect(t.length).toBeGreaterThan(3);
      expect(t).not.toMatch(CAUSAL);
      expect(t).not.toMatch(JARGAO);
    }
    expect(INDICADORES_EXPLICADOS.ica.abrangencia).toContain("só para a rede");
    expect(INDICADORES_EXPLICADOS.iee.abrangencia).toContain("não existe para a rede");
    expect(INDICADORES_EXPLICADOS.ideb.meta).toBe("Metas oficiais só até 2021");
    expect(METRICAS_ELEFANTE.map((m) => m.rotulo)).toEqual([
      "Participação", "Livros novos por aluno", "Minutos de leitura por aluno", "Acerto nas questões", "Nível médio dos livros",
    ]);
    expect(METRICAS_ELEFANTE[2].oQueMede).toContain("É um mínimo");
    expect(METRICAS_MATIFIC.map((m) => m.rotulo)).toEqual(["Participação", "Atividades por aluno", "Estrelas por aluno", "Desempenho"]);
    expect(FRASE_PLATAFORMA).toBe("Mostra quanto e como as crianças usam a plataforma — não é avaliação oficial de aprendizagem.");
  });
});

describe("A frase que separa avaliações de plataformas (§1.4)", () => {
  it("anos diferentes: a frase do desenho; o mesmo ano: medidas diferentes, sem dizer 'outras edições'", () => {
    expect(fraseSeparacao(2025, 2026)).toBe(
      "As avaliações oficiais são de outras edições (até 2025) e as plataformas, do ano letivo de 2026: são medidas e "
      + "períodos diferentes — não se comparam diretamente.");
    // A edição da avaliação é a MAIS NOVA ("até"): as outras avaliações podem ser de antes.
    expect(fraseSeparacao(2026, 2026)).toBe(
      "As avaliações oficiais (até 2026) e as plataformas (ano letivo de 2026) são medidas diferentes — não se "
      + "comparam diretamente.");
    expect(fraseSeparacao(null, null)).toContain("do ano letivo corrente");
  });
});

describe("Língua simples para os textos do servidor (§1.5)", () => {
  it("reescreve a média instável, o índice de médias instáveis, o k e a coorte — o motivo continua", () => {
    expect(textoSimples("média instável (TPS = 0: participação abaixo do mínimo do SARESP): não se compara com a rede"))
      .toBe("média instável (poucos alunos fizeram a prova): não se compara com a rede");
    expect(textoSimples("IEE calculado com médias de TPS = 0 (participação abaixo do mínimo): não gera sinal de tendência"))
      .toBe("IEE calculado com médias instáveis (poucos alunos fizeram a prova): não gera sinal de tendência");
    expect(textoSimples("IEE de escola com TPS = 0 (participação abaixo do mínimo do SARESP): o índice é o oficial."))
      .toBe("IEE de escola com média instável (participação abaixo do mínimo do SARESP): o índice é o oficial.");
    expect(textoSimples("TPS = 0: a escola não atingiu a taxa mínima de participação do SARESP."))
      .toBe("Média instável: a escola não atingiu a taxa mínima de participação do SARESP.");
    expect(textoSimples("Elefante: poucos alunos — os números não aparecem, para proteger as crianças (k = 5)."))
      .toBe("Elefante: poucos alunos — os números não aparecem, para proteger as crianças.");
    expect(textoSimples("Resultados oficiais de outra edição/coorte e uso das plataformas em outro ano."))
      .toBe("Resultados oficiais de outra edição (outro grupo de alunos) e uso das plataformas em outro ano.");
    expect(textoSimples(null)).toBe("");
  });

  it("sem jargão interno nem ordem de importar (só o admin global importa): 1 clique, D2, CODMUN, ICM, diagnóstico", () => {
    // Os textos no MOLDE dos do servidor (indicadores.py, diagnostico.py, consulta_ideb.py).
    expect(textoSimples("só há números gravados antes, sem o registro do arquivo oficial: importe o arquivo oficial "
      + "desta edição")).toBe("só há números gravados antes, sem o registro do arquivo oficial: falta importar o arquivo "
      + "oficial desta edição — quem importa é o administrador global");
    expect(textoSimples("o código INEP foi cadastrado depois da importação; reimporte o arquivo oficial desta edição"))
      .toBe("o código INEP foi cadastrado depois da importação; o arquivo oficial desta edição precisa ser importado de "
        + "novo — quem importa é o administrador global");
    expect(textoSimples("o número oficial não foi gravado: a estimativa do Constela foi mantida (decisão D2)"))
      .toBe("o número oficial não foi gravado: a estimativa do Constela foi mantida");
    expect(textoSimples("A rede não tem o código do município na SEDUC (CODMUN): o SARESP da rede por município não "
      + "pode ser recortado.")).toBe("A rede não tem o código do município na SEDUC: o SARESP da rede por município não "
      + "pode ser recortado. Quem cadastra é o administrador global.");
    expect(textoSimples("Números marcados “sem registro oficial” foram gravados antes, pelo botão de importação em 1 "
      + "clique, sem prévia nem registro do arquivo. A importação oficial só os mantém quando são iguais."))
      .toBe("Números marcados “sem registro oficial” foram gravados antes, sem o registro do arquivo oficial. A "
        + "importação oficial só os mantém quando são iguais.");
    expect(textoSimples("IEE 2025: 1,52, com meta 2,10 — meta não cumprida (pelo ICM oficial da SEDUC)."))
      .toBe("IEE 2025: 1,52, com meta 2,10 — meta não cumprida (segundo a SEDUC).");
    expect(textoSimples("Ideb 2023: número gravado antes, sem o registro do arquivo oficial — não entra no diagnóstico "
      + "(importe o arquivo oficial desta edição).")).toBe("Ideb 2023: número gravado antes, sem o registro do arquivo "
      + "oficial — não gera sinal (falta importar o arquivo oficial desta edição — quem importa é o administrador global).");
    expect(textoSimples("* número gravado antes, sem o registro do arquivo oficial (o botão de importação em 1 clique, "
      + "sem prévia). Não é a Estimativa Constela e não entra nos destaques nem na relação com as plataformas."))
      .toBe("* número gravado antes, sem o registro do arquivo oficial. Não é a Estimativa Constela e não entra nos "
        + "resultados da rede nos cartões.");
  });

  it("sem a relação com as plataformas nem 'destaques' (nome de campo da API) no fluxo principal", () => {
    expect(textoSimples("Oficial × estimativa: só os números com o registro do arquivo oficial entram nos destaques e "
      + "na relação com as plataformas. A Estimativa Constela aparece à parte.")).toBe("Oficial × estimativa: só os "
      + "números com o registro do arquivo oficial entram nos resultados da rede nos cartões. A Estimativa Constela "
      + "aparece à parte.");
    expect(textoSimples("Ideb 2023: 2 de 4 escola(s) com número gravado antes — o número aparece marcado e não entra "
      + "nos destaques nem na relação (1 difere do arquivo oficial).")).toBe("Ideb 2023: 2 de 4 escola(s) com número "
      + "gravado antes — o número aparece marcado e não entra nos resultados da rede nos cartões (1 difere do arquivo "
      + "oficial).");
    expect(textoSimples("IEE de escola com TPS = 0 (participação abaixo do mínimo do SARESP): o índice é o oficial, mas "
      + "foi calculado com médias instáveis — ele fica fora da relação com as plataformas.")).toBe("IEE de escola com "
      + "média instável (participação abaixo do mínimo do SARESP): o índice é o oficial, mas foi calculado com médias "
      + "instáveis.");
  });

  it("metodologia e limitações: sem as frases da relação estatística (Spearman, intervalo, causa e efeito); o resto fica", () => {
    expect(textosDoFluxoPrincipal(METODOLOGIA_COM_RELACAO))
      .toEqual(["Sem resultado não é zero: cada falta vem com o motivo (texto sintético)."]);
    expect(textosDoFluxoPrincipal(LIMITACOES_COM_RELACAO)).toEqual([
      "Coleta atrasada: a escola aparece como coleta parcial (texto sintético).",
      "Grupo de alunos: alunos ativos do 1º ao 5º ano (texto sintético).",
      "As plataformas só têm dados do ano letivo em curso; as avaliações oficiais por escola são de anos anteriores.",
    ]);
    for (const t of textosDoFluxoPrincipal([...METODOLOGIA_COM_RELACAO, ...LIMITACOES_COM_RELACAO])) {
      expect(t).not.toMatch(CAUSAL);
      expect(t).not.toMatch(JARGAO);
    }
    // Sem frase da relação, o texto passa inteiro (só a língua simples).
    expect(textosDoFluxoPrincipal(["Datas: as coletas são diárias. Leituras à noite podem cair no dia seguinte."]))
      .toEqual(["Datas: as coletas são diárias. Leituras à noite podem cair no dia seguinte."]);
    expect(textosDoFluxoPrincipal(null)).toEqual([]);
  });
});

describe("Frases-conclusão", () => {
  it("avaliações: a meta diz se está bom (atingiu, abaixo, empate); sem meta, o resultado mais recente", () => {
    const c = catalogo();
    expect(conclusaoAvaliacoes(c.destaques, c)).toBe("ICA 2025: 58% — abaixo da meta de 60%.");
    const atingiu = c.destaques.map((d) => (d.indicador === "ica" ? { ...d, valor: 61, situacao_meta: "atingiu" as const } : d));
    expect(conclusaoAvaliacoes(atingiu, c)).toBe("ICA 2025: 61% — atingiu a meta de 60%.");
    const empate = c.destaques.map((d) => (d.indicador === "ica" ? { ...d, valor: 60, situacao_meta: "inconclusivo" as const } : d));
    expect(conclusaoAvaliacoes(empate, c)).toBe("ICA 2025: 60% — igual à meta de 60% na precisão divulgada.");
    const semMeta = c.destaques.filter((d) => d.indicador !== "ica");
    expect(conclusaoAvaliacoes(semMeta, c))
      .toBe("Resultado oficial mais recente: SARESP 2025 (5º ano, Língua Portuguesa): 212,4 (sem meta oficial).");
  });

  it("avaliações sem meta: o 'mais recente' é a edição MAIS NOVA (não o 1º da ordem fixa) e o 'sem meta' diz qual", () => {
    const c = catalogo();
    // O ICA 2023 (as metas dele começam depois) vem primeiro na ordem fixa; o SARESP 2025 é mais novo.
    const ica2023 = c.destaques.map((d) => (d.indicador === "ica"
      ? { ...d, edicao: 2023, meta: null, situacao_meta: null, diferenca_meta: null,
          texto_sem_meta: "não há meta oficial para esta edição" } : d));
    expect(conclusaoAvaliacoes(ica2023, c))
      .toBe("Resultado oficial mais recente: SARESP 2025 (5º ano, Língua Portuguesa): 212,4 (sem meta oficial).");
    // Só o ICA, sem a meta daquela edição: o indicador TEM meta — falta só a desta edição.
    expect(conclusaoAvaliacoes(ica2023.filter((d) => d.indicador === "ica"), c))
      .toBe("Resultado oficial mais recente: ICA 2023: 58% (sem meta para esta edição).");
    // Empate de edição: fica a ordem fixa (o ICA primeiro).
    const empate = ica2023.map((d) => (d.indicador === "ica" ? { ...d, edicao: 2025 } : d));
    expect(conclusaoAvaliacoes(empate, c)).toBe("Resultado oficial mais recente: ICA 2025: 58% (sem meta para esta edição).");
  });

  it("plataformas com uma série escolhida: a frase diz a série (sem ela, o texto de sempre)", () => {
    const p = plataformasRede();
    expect(conclusaoPlataformas(p, 2)).toBe(
      "No ano letivo de 2026, no 2º ano, 70% dos alunos com conta leram ao menos um livro no Elefante e 80% dos alunos "
      + "com dado no período fizeram ao menos uma atividade no Matific.");
    expect(conclusaoComparacaoPlataformas(p, 2)).toBe(
      "Ano letivo de 2026 (01/01/2026 a 31/12/2026), 2º ano: das 4 escolas, 3 com número do Elefante e 2 com número do "
      + "Matific.");
    expect(conclusaoComparacaoPlataformas(p)).not.toContain("ano:");
  });

  it("plataformas: o período dito por extenso (ano letivo × outro período); sem dado é texto", () => {
    expect(quandoDaJanela({ inicio: "2026-10-01", fim: "2026-10-31", rotulo: "Este mês", preset: "mes" }))
      .toBe("No período (este mês, de 01/10/2026 a 31/10/2026)");
    expect(quandoDaJanela({ inicio: "2026-02-02", fim: "2026-12-18", rotulo: "Ano letivo de 2026", preset: "ano_letivo",
                            ano_letivo: 2026 })).toBe("No ano letivo de 2026");
    const p = plataformasRede();
    const semDado = plataformasRede({ rede: { ...p.rede, elefante: { ...p.rede.elefante!, participacao_pct: null } } });
    expect(conclusaoPlataformas(semDado)).toBe(
      "No ano letivo de 2026, o Elefante ficou sem dado e 80% dos alunos com dado no período fizeram ao menos uma "
      + "atividade no Matific.");
    expect(conclusaoPlataformas(semDado)).not.toMatch(/\b0%/);
  });

  it("plataformas: a participação PROTEGIDA (poucos alunos) não vira 'sem dado'", () => {
    const p = plataformasRede();
    const protegida = plataformasRede({ rede: { ...p.rede,
      elefante: { ...p.rede.elefante!, participacao_pct: null, metricas_protegidas: ["participacao_pct", "livros_por_aluno"] },
      matific: { ...p.rede.matific!, participacao_pct: null, metricas_protegidas: ["participacao_pct"] } } });
    expect(conclusaoPlataformas(protegida)).toBe(
      "No ano letivo de 2026, a participação no Elefante fica protegida (poucos alunos) e a participação no Matific fica "
      + "protegida (poucos alunos).");
    expect(conclusaoPlataformas(protegida)).not.toMatch(/sem dado|\b0%/);
    // Protegida só OUTRA métrica (não a participação): a participação nula continua "sem dado".
    const outra = plataformasRede({ rede: { ...p.rede,
      elefante: { ...p.rede.elefante!, participacao_pct: null, metricas_protegidas: ["livros_por_aluno"] } } });
    expect(conclusaoPlataformas(outra)).toContain("o Elefante ficou sem dado");
  });

  it("comparação das avaliações: quantas escolas têm número, de quais edições, e quantas acima/abaixo da rede", () => {
    expect(conclusaoComparacaoAvaliacoes(diagnostico())).toBe(
      "3 de 4 escolas têm resultado oficial na edição mais recente de cada avaliação (IEE 2025, Ideb 2023, "
      + "SARESP 2025). Em ao menos uma avaliação, 1 fica abaixo da rede municipal e 1 acima.");
    expect(conclusaoComparacaoAvaliacoes(diagnostico({ escolas: [] }))).toBe("A rede não tem escolas cadastradas.");
    // Nenhuma abaixo: "nenhuma fica", não "0 ficam".
    const d = diagnostico();
    const semAbaixo = diagnostico({
      escolas: d.escolas.map((e) => ({
        ...e, oficiais: e.oficiais.map((o) => (o.posicao_rede === "abaixo" ? { ...o, posicao_rede: "na_media" as const } : o)),
      })),
    });
    expect(conclusaoComparacaoAvaliacoes(semAbaixo)).toContain("nenhuma fica abaixo da rede municipal e 1 acima.");
  });
});

describe("Conclusão do cartão de um indicador", () => {
  it("a edição mais recente SEM número da rede é dita por extenso (não parece contradição com o ano do número)", () => {
    const c = catalogo();
    const saeb = { ...c.indicadores.find((i) => i.chave === "saeb")!, edicoes: [2021, 2023], edicao_mais_recente: 2023 };
    const destaque = {
      ...c.destaques[0], indicador: "saeb", rotulo: "Saeb da rede", edicao: 2021, valor: 210, casas: 2,
      unidade: "pontos", meta: null, situacao_meta: null,
    };
    const frase = conclusaoIndicador(saeb, { ...c, destaques: [destaque] });
    expect(frase).toMatch(/^Rede em 2021.*: 210,00/);
    expect(frase).toContain("Na edição de 2023, não há resultado oficial da rede.");
    // Quando o número É da edição mais recente, nada a acrescentar.
    const ica = c.indicadores.find((i) => i.chave === "ica")!;
    expect(conclusaoIndicador(ica, c)).not.toContain("não há resultado oficial");
  });
});

describe("Panorama da Rede (DESENHO3 §2)", () => {
  it("cadastradas, ativas e com uso: separados e por extenso (singular, 'nenhuma', sem o uso ainda)", () => {
    expect(conclusaoRedeNoConstela(6, 5, 3, 2026))
      .toBe("6 escolas cadastradas, 5 ativas no cadastro; 3 com uso do Constela no ano letivo de 2026.");
    expect(conclusaoRedeNoConstela(1, 1, 0, null))
      .toBe("1 escola cadastrada, 1 ativa no cadastro; nenhuma com uso do Constela no ano letivo.");
    expect(conclusaoRedeNoConstela(3, 0, null, 2026)).toBe("3 escolas cadastradas, nenhuma ativa no cadastro.");
    expect(conclusaoRedeNoConstela(0, 0, 0, 2026)).toBe("Nenhuma escola cadastrada na rede ainda.");
  });

  it("as demais escolas por situação (só as que existem), as que ficaram fora dos destaques", () => {
    expect(textoDemaisSituacoes({ com_uso: 3, sem_uso: 1, sem_dado: 1, protegido: 1 }))
      .toBe("1 sem uso registrado · 1 sem dado · 1 protegida");
    expect(textoDemaisSituacoes({ com_uso: 0, sem_uso: 0, sem_dado: 4, protegido: 2 })).toBe("4 sem dado · 2 protegidas");
    expect(textoDemaisSituacoes({ com_uso: 5, sem_uso: 0, sem_dado: 0, protegido: 0 })).toBe("nenhuma");
    expect(textoForaPorProtecao(0)).toBeNull();
    expect(textoForaPorProtecao(1)).toBe(
      "1 escola ficou fora desta lista para proteger as crianças: o número dela fica protegido (poucos alunos).");
    expect(textoForaPorProtecao(2)).toContain("2 escolas ficaram fora desta lista");
  });

  it("'sem uso registrado' com coleta parcial: por extenso com a data (a mais antiga primeiro), fora da conta em dia", () => {
    // 4 sem uso: 1 em dia, 2 parciais até 15/09 e 1 até 20/03 (pela DATA: 20/03 vem antes de 15/09).
    expect(textoDemaisSituacoes({ com_uso: 1, sem_uso: 4, sem_dado: 1, protegido: 0 },
      ["15/09/2026", "20/03/2026", "15/09/2026"])).toBe("1 sem uso registrado · 1 sem uso registrado até 20/03/2026 "
      + "(coleta parcial) · 2 sem uso registrado até 15/09/2026 (coleta parcial) · 1 sem dado");
    // Só parciais: nenhuma "em dia" na frase; a parcial sem a data diz que é parcial.
    expect(textoDemaisSituacoes({ com_uso: 0, sem_uso: 2, sem_dado: 0, protegido: 0 }, ["20/03/2026", null]))
      .toBe("1 sem uso registrado até 20/03/2026 (coleta parcial) · 1 sem uso registrado (coleta parcial)");
    // Sem parcial: a frase de sempre.
    expect(textoDemaisSituacoes({ com_uso: 0, sem_uso: 2, sem_dado: 0, protegido: 0 })).toBe("2 sem uso registrado");
    expect(O_QUE_MEDE_REDE.demais).toContain("com a coleta parcial, a tela diz até que data");
  });

  it("destaques vazios: UMA frase só — sem dados suficientes, ou todas as que entrariam ficaram fora por proteção", () => {
    expect(textoDestaquesVazio(0)).toBe("Nenhuma escola com dados suficientes para este critério ainda.");
    expect(textoDestaquesVazio(1)).toBe("Nenhuma escola aparece nesta lista: a única que entraria ficou fora para "
      + "proteger as crianças — o número dela fica protegido (poucos alunos).");
    expect(textoDestaquesVazio(2)).toBe("Nenhuma escola aparece nesta lista: as 2 que entrariam ficaram fora para "
      + "proteger as crianças — o número delas fica protegido (poucos alunos).");
    // Quem ficou fora por proteção TEM dados: a frase não diz que falta dado.
    for (const n of [1, 2]) expect(textoDestaquesVazio(n)).not.toContain("dados suficientes");
  });

  it("reconhecimento público: o mesmo critério; com escola fora por proteção, os destaques daqui têm menos escolas", () => {
    expect(textoReconhecimentoPublico(0)).toBe("A vitrine pública usa o mesmo critério das escolas em destaque e as "
      + "mostra num link aberto — sem login e sem nome de criança.");
    expect(textoReconhecimentoPublico(1)).toBe(`${textoReconhecimentoPublico(0)} Os destaques acima têm menos escolas `
      + "que a vitrine: aqui fica de fora a escola com o número protegido (poucos alunos).");
    for (const n of [0, 1, 3]) {
      expect(textoReconhecimentoPublico(n)).not.toMatch(/estas mesmas|as mesmas escolas/);
      expect(textoReconhecimentoPublico(n)).not.toMatch(CAUSAL);
    }
  });

  it("o que mede cada número da rede: 'ativa' não indica uso; o uso só das plataformas contratadas", () => {
    expect(O_QUE_MEDE_REDE.ativas).toContain("não indica uso");
    // O uso do Elefante conta também a releitura: "um livro", nunca "um livro novo".
    expect(O_QUE_MEDE_REDE.comUso({ elefante: true, matific: true })).toBe(
      "Escolas em que pelo menos um aluno do 1º ao 5º ano leu um livro no Elefante ou fez uma atividade no "
      + "Matific no ano letivo, pelas coletas.");
    expect(O_QUE_MEDE_REDE.comUso({ elefante: true, matific: false })).not.toContain("livro novo");
    expect(O_QUE_MEDE_REDE.comUso({ elefante: false, matific: true })).not.toContain("Elefante");
    expect(O_QUE_MEDE_REDE.comUso({ elefante: true, matific: false })).not.toContain("Matific");
    for (const t of [O_QUE_MEDE_REDE.cadastradas, O_QUE_MEDE_REDE.ativas, O_QUE_MEDE_REDE.demais,
      O_QUE_MEDE_REDE.comUso({ elefante: true, matific: true })]) {
      expect(t).not.toMatch(CAUSAL);
      expect(t).not.toMatch(JARGAO);
    }
  });

  it("o critério dos destaques: o da vitrine (leitura acumulada desde o início da conta; Matific no ano letivo)", () => {
    const duas = criterioDosDestaques({ elefante: true, matific: true }, 5, 5);
    expect(duas).toHaveLength(3);
    expect(duas[0]).toContain("livros lidos desde o início da conta de cada aluno");
    expect(duas[1]).toContain("estrelas por aluno no ano letivo");
    // Quem soma vale POR PLATAFORMA (o servidor): livro na leitura, estrela na matemática — não "um ou outro".
    expect(duas[2]).toBe("Entram só escolas ativas, com pelo menos 5 alunos do 1º ao 5º ano; na leitura, pelo menos 5 "
      + "deles com algum livro lido; na matemática, pelo menos 5 deles com alguma estrela. Aparecem as 5 maiores de "
      + "cada plataforma. É o mesmo critério da vitrine pública.");
    expect(duas.join(" ")).not.toMatch(/livro lido ou alguma estrela/);
    const soMatific = criterioDosDestaques({ elefante: false, matific: true }, 5, 5);
    expect(soMatific.join(" ")).not.toMatch(/Elefante|livro|Leitura/);
    expect(soMatific[1]).toBe("Entram só escolas ativas, com pelo menos 5 alunos do 1º ao 5º ano; na matemática, pelo "
      + "menos 5 deles com alguma estrela. Aparecem as 5 maiores da plataforma. É o mesmo critério da vitrine pública.");
    for (const t of duas) {
      expect(t).not.toMatch(CAUSAL);
      expect(t).not.toMatch(JARGAO);
    }
  });

  it("o Ranking da Rede é outra medida: o nome do link e a frase citam só o que a rede contratou", () => {
    expect(ROTULO_LINK_RANKING).toBe("Ranking da Rede (pontuação do Constela — outra medida)");
    expect(fraseRankingOutraMedida({ elefante: true, matific: true })).toBe(
      "A ordem do Ranking da Rede é a da pontuação do Constela, não os livros por aluno ou as estrelas por aluno "
      + "destes destaques: as posições podem ser diferentes.");
    expect(fraseRankingOutraMedida({ elefante: false, matific: true })).not.toMatch(/livro/);
    expect(fraseRankingOutraMedida({ elefante: true, matific: false })).not.toMatch(/estrela/);
    expect(fraseRankingOutraMedida({ elefante: true, matific: true })).not.toMatch(/continua|ordem completa/);
  });

  it("quantas escolas entraram no número da rede: parte, todas, nenhuma — sem a contagem, nada", () => {
    expect(textoEscolasNaSoma(3, 8)).toBe("Soma de 3 das 8 escolas: as com a coleta em dia no período (ou cobrindo "
      + "ao menos 90% dele). As demais ficam fora da soma — sem dado não é zero.");
    expect(textoEscolasNaSoma(8, 8)).toBe("Soma das 8 escolas da rede (todas com a coleta em dia ou cobrindo ao menos 90% do período).");
    expect(textoEscolasNaSoma(1, 1)).toBe("Número da única escola da rede (com a coleta em dia ou cobrindo ao menos 90% do período).");
    expect(textoEscolasNaSoma(0, 8)).toBe("Nenhuma das 8 escolas entrou na soma: sem a coleta em dia no período ou com os números protegidos (poucos alunos).");
    expect(textoEscolasNaSoma(undefined, 8)).toBeNull();
    expect(textoEscolasNaSoma(3, 0)).toBeNull();
  });

  it("anos letivos misturados e as notas das metas: por extenso, sem causa nem jargão", () => {
    expect(fraseAnosMistos([2025, 2026])).toBe(
      "As escolas da rede estão em anos letivos diferentes (2025, 2026): o uso de cada escola é o do ano letivo dela.");
    // Adoção não é uso; os livros das metas são desde o início da conta; atividades, do ano letivo.
    expect(NOTA_DAS_METAS_NO_PANORAMA.adocao).toContain("sem período — não é uso");
    expect(NOTA_DAS_METAS_NO_PANORAMA.livros).toContain("desde o início da conta de cada aluno");
    expect(NOTA_DAS_METAS_NO_PANORAMA.atividades).toContain("do ano letivo");
    // Toda métrica que aceita meta tem a nota (as mesmas do cadastro de metas).
    expect(Object.keys(NOTA_DAS_METAS_NO_PANORAMA).sort()).toEqual([
      "adocao", "atividades", "livros", "media_elefante", "media_geral", "media_matific", "pontuacao_geral",
    ]);
    for (const t of [fraseAnosMistos([2025, 2026]), ...Object.values(NOTA_DAS_METAS_NO_PANORAMA)]) {
      expect(t).not.toMatch(CAUSAL);
      expect(t).not.toMatch(JARGAO);
    }
  });
});
