/**
 * G_ANALISE-2 (auditoria, fase C): o número da rede PROTEGIDO (menos de 5 alunos medidos — o
 * serviço manda o bloco inteiro com `motivo_sem_dado = "poucos_alunos_medidos"` e
 * `metricas_protegidas` vazia) é "protegido" em todas as frases e células da Secretaria — nunca
 * "sem dado", ao lado das escolas que dizem "Protegido (poucos alunos)". Uma função só decide:
 * `numeroProtegido` (o motivo do bloco OU a métrica em `metricas_protegidas`).
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import EvolucaoPlataformas from "../pages/analise/EvolucaoPlataformas";
import { numeroProtegido } from "../pages/analise/formato";
import type { MetricasElefante, RespostaPlataformas } from "../pages/analise/tipos";
import PanoramaSecretaria from "../pages/rede/secretaria/PanoramaSecretaria";
import { conclusaoPlataformas } from "../pages/rede/secretaria/conclusoes";
import { evolucao, plataformasRede } from "./AnaliseFixturesDiagnostico";
import { plataformasDoPanorama, renderTela, secretaria, semearPanorama } from "./SecretariaFixtures";
import { renderComApp, responder, screen, within } from "./utils";

const TEXTO_POUCOS = "menos de 5 alunos com dado desta plataforma no período: os números não aparecem, "
  + "para proteger as crianças";

/** O bloco do Elefante da rede como o serviço manda com 4 alunos medidos (k = 5). */
function elefanteProtegido(base: MetricasElefante): MetricasElefante {
  return {
    ...base, alunos_medidos: 4, alunos_com_leitura: null, participacao_pct: null, livros_por_aluno: null,
    minutos_por_aluno: null, nivel_medio: null, nivel_medio_posicao: null, taxa_acerto_pct: null,
    metricas_protegidas: [], texto_metricas_protegidas: null,
    motivo_sem_dado: "poucos_alunos_medidos", texto_sem_dado: TEXTO_POUCOS,
  } as MetricasElefante;
}

function comElefanteProtegido(p: RespostaPlataformas): RespostaPlataformas {
  return { ...p, rede: { ...p.rede, elefante: elefanteProtegido(p.rede.elefante as MetricasElefante) } };
}

describe("Número da rede protegido (poucos alunos medidos) — nunca 'sem dado'", () => {
  it("numeroProtegido: o motivo do bloco ou a métrica escondida; falta de dado não é proteção", () => {
    expect(numeroProtegido({ motivo_sem_dado: "poucos_alunos_medidos", metricas_protegidas: [] }, "participacao_pct"))
      .toBe(true);
    expect(numeroProtegido({ motivo_sem_dado: "series_suprimidas" })).toBe(true);
    expect(numeroProtegido({ motivo_sem_dado: "suprimido" })).toBe(true);
    expect(numeroProtegido({ motivo_sem_dado: null, metricas_protegidas: ["livros_por_aluno"] }, "livros_por_aluno"))
      .toBe(true);
    expect(numeroProtegido({ motivo_sem_dado: null, metricas_protegidas: ["livros_por_aluno"] }, "participacao_pct"))
      .toBe(false);
    expect(numeroProtegido({ motivo_sem_dado: "sem_coleta_no_periodo", metricas_protegidas: [] }, "participacao_pct"))
      .toBe(false);
    expect(numeroProtegido(null, "participacao_pct")).toBe(false);
  });

  it("a conclusão diz que a participação no Elefante fica protegida", () => {
    const frase = conclusaoPlataformas(comElefanteProtegido(plataformasRede()));
    expect(frase).not.toContain("o Elefante ficou sem dado");
    expect(frase).toContain("a participação no Elefante fica protegida (poucos alunos)");
  });

  it("o Panorama: o cartão da rede diz 'protegido (poucos alunos)' e não afirma a soma das escolas", async () => {
    semearPanorama();
    const p = plataformasDoPanorama();
    responder("GET", "/redes/1/analise/plataformas", {
      ...comElefanteProtegido(p), rede: { ...comElefanteProtegido(p).rede, escolas_com_dado: { elefante: 2, matific: 2 } },
    });
    renderTela("/", <PanoramaSecretaria />);
    const pct = await screen.findByTestId("participacao-elefante-pct");
    expect(pct).toHaveTextContent("protegido (poucos alunos)");
    expect(pct).not.toHaveTextContent("sem dado");
    expect(screen.getByTestId("participacao-elefante-intensidade")).toHaveTextContent("protegido (poucos alunos)");
    expect(screen.getByTestId("participacao-elefante")).not.toHaveTextContent("Soma das 2 escolas");
    expect(screen.getByTestId("conclusao-plataformas")).not.toHaveTextContent("o Elefante ficou sem dado");
  });

  it("a evolução da rede: a célula do bimestre protegido diz 'protegido'", async () => {
    const padrao = evolucao();
    responder("GET", "/redes/1/analise/plataformas/evolucao", {
      ...padrao,
      bimestres: padrao.bimestres.map((b) => (b.numero !== 1 || !b.rede ? b : {
        ...b,
        rede: { ...b.rede, elefante: { participacao_pct: null, livros_por_aluno: null, minutos_por_aluno: null,
                                       motivo_sem_dado: "poucos_alunos_medidos", texto_sem_dado: TEXTO_POUCOS,
                                       coleta_parcial: false, metricas_protegidas: [] } },
      })),
    });
    renderComApp(<EvolucaoPlataformas redeId={1} serie={null} />, { usuario: secretaria });
    const tabela = await screen.findByTestId("tabela-evolucao-rede");
    const primeiro = within(tabela).getAllByRole("row")[1];
    expect(within(primeiro).getAllByText("protegido")).toHaveLength(3);
    expect(within(primeiro).queryByText("sem dado")).toBeNull();
  });
});
