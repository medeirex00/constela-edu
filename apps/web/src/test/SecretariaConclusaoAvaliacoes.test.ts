/**
 * A CONCLUSÃO da tabela "Todas as escolas na edição mais recente de cada avaliação"
 * (`conclusaoComparacaoAvaliacoes`, tela Avaliações externas) com a regra de NÃO MISTURAR
 * edições: cada série (avaliação × etapa × componente) fica na edição de referência — a mais
 * recente com resultado entre as escolas —, só os resultados dessa edição contam (com resultado,
 * acima, abaixo) e a frase diz a edição de cada avaliação, nunca "edições de X a Y". A escola que
 * só tem resultado de edição anterior é dita à parte: o último oficial dela fica na ficha.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import type { EscolaDiagnostico, OficialDiagnostico } from "../pages/analise/tiposDiagnostico";
import { conclusaoComparacaoAvaliacoes } from "../pages/rede/secretaria/conclusoes";
import { oficial } from "./AnaliseFixturesDiagnostico";
import { diagnostico } from "./SecretariaFixtures";

const CAUSAL = /\bcausa|\befeito|impacto|graças/i;

/** O diagnóstico padrão com os resultados oficiais de cada escola trocados (por id). */
function comOficiais(porEscola: Record<number, OficialDiagnostico[]>) {
  const padrao = diagnostico();
  return diagnostico({
    escolas: padrao.escolas.map((e): EscolaDiagnostico => (porEscola[e.id] ? { ...e, oficiais: porEscola[e.id] } : e)),
  });
}

const lp = (over: Partial<OficialDiagnostico>) => oficial(over);
const mt = (over: Partial<OficialDiagnostico>) => oficial({ rotulo: "SARESP · 5º ano · MT", componente: "mt", ...over });
const ideb = (over: Partial<OficialDiagnostico>) => oficial({
  indicador: "ideb", rotulo: "Ideb · anos iniciais", etapa: "anos_iniciais", componente: null, edicao: 2023, valor: 6.1,
  valor_rede: 6.0, ...over });

describe("Conclusão das avaliações por escola — só a edição de referência de cada série", () => {
  it("todas na edição de referência: diz a edição de cada avaliação (não 'edições de 2023 a 2025')", () => {
    const frase = conclusaoComparacaoAvaliacoes(diagnostico());
    expect(frase).toBe(
      "3 de 4 escolas têm resultado oficial na edição mais recente de cada avaliação (IEE 2025, Ideb 2023, SARESP "
      + "2025). Em ao menos uma avaliação, 1 fica abaixo da rede municipal e 1 acima.");
    expect(frase).not.toMatch(/edições de/);
    expect(frase).not.toMatch(CAUSAL);
  });

  it("escola só com resultado de edição anterior: não conta como 'com resultado' nem como 'abaixo'; a frase diz onde ele está", () => {
    // Beta tem só o SARESP LP de 2024 (abaixo da rede); Alfa já tem o de 2025.
    const frase = conclusaoComparacaoAvaliacoes(comOficiais({
      3: [lp({ edicao: 2024, valor: 198.0, diferenca_rede: -14.4, posicao_rede: "abaixo" })],
    }));
    expect(frase).toBe(
      "2 de 4 escolas têm resultado oficial na edição mais recente de cada avaliação (IEE 2025, Ideb 2023, SARESP "
      + "2025). Em ao menos uma avaliação, nenhuma fica abaixo da rede municipal e 1 acima. 1 escola só tem resultado "
      + "de edição anterior: o último oficial dela fica na ficha da escola.");
  });

  it("duas escolas só com edição anterior: o plural por extenso", () => {
    const frase = conclusaoComparacaoAvaliacoes(comOficiais({
      3: [lp({ edicao: 2024, posicao_rede: "abaixo" })],
      5: [ideb({ edicao: 2021, posicao_rede: "acima" }), lp({ edicao: 2023, posicao_rede: "acima" })],
      2: [lp({ valor: 219.6, posicao_rede: "acima" }), ideb({ edicao: 2023, posicao_rede: "na_media" })],
    }));
    expect(frase).toBe(
      "1 de 4 escolas tem resultado oficial na edição mais recente de cada avaliação (Ideb 2023, SARESP 2025). Em ao "
      + "menos uma avaliação, nenhuma fica abaixo da rede municipal e 1 acima. 2 escolas só têm resultado de edição "
      + "anterior: o último oficial de cada uma fica na ficha da escola.");
  });

  it("a referência é por série: a mesma avaliação com edições diferentes diz cada uma com o seu recorte", () => {
    // SARESP 5º ano: a LP já tem 2025 (Alfa e Beta); a MT só existe em 2024 (Beta) — é a referência dela.
    const frase = conclusaoComparacaoAvaliacoes(comOficiais({
      3: [lp({ valor: 198.0, posicao_rede: "abaixo" }), mt({ edicao: 2024, valor: 230.1, posicao_rede: "acima" })],
    }));
    expect(frase).toBe(
      "3 de 4 escolas têm resultado oficial na edição mais recente de cada avaliação (IEE 2025; Ideb 2023; SARESP "
      + "2025 no 5º ano em Língua Portuguesa e 2024 no 5º ano em Matemática). Em ao menos uma avaliação, 1 fica abaixo "
      + "da rede municipal e 2 acima.");
  });

  it("etapas diferentes em edições diferentes: o recorte é a etapa", () => {
    const frase = conclusaoComparacaoAvaliacoes(comOficiais({
      2: [lp({ valor: 219.6, posicao_rede: "acima" })],
      3: [lp({ etapa: "2_ano", rotulo: "SARESP · 2º ano · LP", edicao: 2024, posicao_rede: null })],
      5: [],
    }));
    expect(frase).toBe(
      "2 de 4 escolas têm resultado oficial na edição mais recente de cada avaliação (SARESP 2025 no 5º ano e 2024 no "
      + "2º ano). Em ao menos uma avaliação, nenhuma fica abaixo da rede municipal e 1 acima.");
  });

  it("sem escola ou sem nenhum resultado: a frase de sempre", () => {
    expect(conclusaoComparacaoAvaliacoes(diagnostico({ escolas: [] }))).toBe("A rede não tem escolas cadastradas.");
    expect(conclusaoComparacaoAvaliacoes(comOficiais({ 2: [], 3: [], 5: [] })))
      .toBe("Nenhuma escola da rede tem resultado oficial importado ainda.");
  });
});
