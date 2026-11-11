/**
 * S_G_ANALISE-2 — o número PROTEGIDO de uma escola (poucos alunos medidos) não é "Sem dado".
 *
 * (1) Escolas (`/rede/escolas`): a tabela "Escolas no período" e a comparação lado a lado
 *     escreviam "Sem dado: menos de 5 alunos com dado desta plataforma no período…" para o bloco
 *     com `motivo_sem_dado = "poucos_alunos_medidos"`, enquanto a legenda logo abaixo diz que esse
 *     caso se chama "Protegido" e o Panorama classifica a MESMA escola como protegida. Agora o
 *     bloco escondido para proteger as crianças diz "Protegido: …" (a regra única
 *     `numeroProtegido`); o que falta de verdade continua "Sem dado: …".
 * (2) Panorama: o número "Sem uso registrado ou sem dado" contava também as protegidas; o rótulo
 *     agora diz as três situações que ele soma.
 * (3) REV3-REDE-1: os cartões das plataformas (`CartoesPlataformas`, na ficha da escola e na Análise
 *     da escola) diziam "Sem dado do Matific: menos de 5 alunos…" logo abaixo da situação de uso
 *     "Protegido (poucos alunos)" da mesma ficha. Agora dizem "Protegido: …"; a falta de verdade
 *     continua "Sem dado do Elefante/Matific: …".
 *
 * Dados sintéticos (as fixtures do próprio projeto).
 */
import { describe, expect, it } from "vitest";

import { CartoesPlataformas } from "../pages/analise/Plataformas";
import { semNumeroDo } from "../pages/analise/PlataformasRede";
import type { MetricasElefante, MetricasMatific } from "../pages/analise/tipos";
import PanoramaSecretaria from "../pages/rede/secretaria/PanoramaSecretaria";
import { classificarRede } from "../pages/rede/secretaria/situacaoDeUso";
import { painelEscolas, plataformasComEpsilon, renderEscolas, semearEscolas } from "./EscolasRedeFixtures";
import { renderTela, semearPanorama } from "./SecretariaFixtures";
import { render, responder, screen, within } from "./utils";

// O texto do serviço (analise/plataformas.py, TEXTOS_COBERTURA[POUCOS_MEDIDOS]) com k = 5.
const POUCOS = "menos de 5 alunos com dado desta plataforma no período: os números não aparecem, para proteger as crianças";

function plataformasReais() {
  const p = plataformasComEpsilon();
  return {
    ...p,
    escolas: p.escolas.map((e) => (e.escola_id === 2 && e.matific
      ? { ...e, matific: { ...e.matific, texto_sem_dado: POUCOS } } : e)),
  };
}

const linhaQueComeca = (tabela: HTMLElement, inicio: string) =>
  within(tabela).getAllByRole("row").filter((r) => r.textContent?.startsWith(inicio));

describe("número protegido da escola não é 'Sem dado'", () => {
  it("Escolas: a tabela e o lado a lado dizem 'Protegido' para poucos alunos medidos, como a legenda e o Panorama", async () => {
    semearEscolas();
    const p = plataformasReais();
    responder("GET", "/redes/1/analise/plataformas", p);
    renderEscolas("/rede/escolas?comparar=2,3");

    const alfa = await screen.findByTestId("escola-periodo-2");
    expect(alfa).toHaveTextContent(`Protegido: ${POUCOS}`);
    expect(alfa.textContent).not.toContain(`Sem dado: ${POUCOS}`);   // antes: "Sem dado: menos de 5…"
    // A legenda da mesma tela e o Panorama chamam o mesmo caso de "Protegido".
    expect(screen.getByTestId("legenda-escolas-periodo")).toHaveTextContent("“Protegido”: poucos alunos");
    const noPanorama = classificarRede(painelEscolas().escolas, p).find((s) => s.escolaId === 2);
    expect(noPanorama?.plataformas.matific?.estado).toBe("protegido");
    // O que falta de verdade continua "Sem dado" (a Épsilon não tem coleta nenhuma).
    expect(screen.getByTestId("escola-periodo-6"))
      .toHaveTextContent("Sem dado: a escola não tem nenhuma coleta desta plataforma (texto sintético)");

    // Lado a lado (Alfa e Beta, nessa ordem): a 1ª linha do Matific com o porquê, as outras
    // "protegido" — nunca "sem dado" para o número que existe e não aparece.
    const lado = await screen.findByTestId("comparacao-lado-a-lado");
    const plataformas = within(lado).getByTestId("comparacao-plataformas");
    expect(plataformas.textContent).not.toContain(`Sem dado: ${POUCOS}`);
    const participacaoMatific = linhaQueComeca(plataformas, "Participação")[1];
    expect(within(participacaoMatific).getAllByRole("cell")[0]).toHaveTextContent(`Protegido: ${POUCOS}.`);
    for (const rotulo of ["Atividades por aluno", "Desempenho (0 a 5)"]) {
      const [linha] = linhaQueComeca(plataformas, rotulo);
      const [celulaAlfa] = within(linha).getAllByRole("cell");
      expect(celulaAlfa).toHaveTextContent(/^protegido$/);
    }
  });

  it("a regra do bloco sem número: proteção diz 'Protegido', falta diz 'Sem dado'", () => {
    const bloco = (motivo: string, texto: string) => ({
      participacao_pct: null, motivo_sem_dado: motivo, texto_sem_dado: texto, metricas_protegidas: [],
    }) as unknown as MetricasMatific;
    expect(semNumeroDo(bloco("poucos_alunos_medidos", POUCOS), "ok")).toBe(`Protegido: ${POUCOS}`);
    expect(semNumeroDo(bloco("series_suprimidas", "todas as séries com poucos alunos (sintético)"), "ok"))
      .toBe("Protegido: todas as séries com poucos alunos (sintético)");
    expect(semNumeroDo(bloco("sem_conta", "ninguém com conta (sintético)"), "ok"))
      .toBe("Sem dado: ninguém com conta (sintético)");
    expect(semNumeroDo(null, null)).toBe("Sem dado: sem dado no período");
    // Bloco com número: nada a dizer no lugar dele.
    expect(semNumeroDo({ participacao_pct: 80 } as unknown as MetricasMatific, "ok")).toBeNull();
  });

  it("ficha da escola: o cartão do Matific diz 'Protegido', como a situação de uso logo acima (REV3-REDE-1)", async () => {
    semearEscolas();
    renderEscolas("/rede/escolas/2");
    const uso = await screen.findByTestId("ficha-uso-matific");
    expect(uso).toHaveTextContent("Matific: Protegido (poucos alunos)");
    const bloco = await screen.findByTestId("ficha-plataformas");
    const matific = within(bloco).getByTestId("plataforma-matific");
    // Antes: "Sem dado do Matific: menos de 5 alunos…" — o mesmo motivo com dois nomes na mesma ficha.
    expect(matific).toHaveTextContent("Protegido: menos de 5 alunos com dado desta plataforma no período.");
    expect(matific).not.toHaveTextContent(/sem dado/i);
    // O Elefante da mesma escola tem número: segue com os números.
    expect(within(bloco).getByTestId("plataforma-elefante")).toHaveTextContent("70%");
  });

  it("ficha da escola sem coleta: o cartão continua 'Sem dado do Elefante' (falta de verdade)", async () => {
    semearEscolas();
    renderEscolas("/rede/escolas/6");
    const bloco = await screen.findByTestId("ficha-plataformas");
    expect(within(bloco).getByTestId("plataforma-elefante"))
      .toHaveTextContent("Sem dado do Elefante: a escola não tem nenhuma coleta desta plataforma (texto sintético).");
    expect(within(bloco).getByTestId("plataforma-matific"))
      .toHaveTextContent("Sem dado do Matific: a escola não tem nenhuma coleta desta plataforma (texto sintético).");
    expect(bloco).not.toHaveTextContent("Protegido");
  });

  it("os cartões das plataformas (ficha e Análise da escola): cada motivo com o nome certo", () => {
    const bloco = (motivo: string | null, texto: string | null) => ({
      alunos_medidos: null, participacao_pct: null, coleta_parcial: false, coberto_ate: null,
      motivo_sem_dado: motivo, texto_sem_dado: texto, metricas_protegidas: [],
    });
    const casos: [string | null, string | null, string][] = [
      ["poucos_alunos_medidos", "menos de 5 alunos medidos (sintético)", "Protegido: menos de 5 alunos medidos (sintético)."],
      ["series_suprimidas", "todas as séries com poucos alunos (sintético)",
       "Protegido: todas as séries com poucos alunos (sintético)."],
      ["suprimido", "escondido junto com um recorte pequeno (sintético)",
       "Protegido: escondido junto com um recorte pequeno (sintético)."],
      ["sem_conta", "ninguém com conta (sintético)", "Sem dado do Elefante: ninguém com conta (sintético)."],
      ["sem_coleta_no_periodo", null, "Sem dado do Elefante: sem dado no período."],
    ];
    for (const [motivo, texto, esperado] of casos) {
      const { unmount } = render(
        <CartoesPlataformas alunos={30} modulos={{ elefante: true, matific: false }} matific={null}
                            elefante={bloco(motivo, texto) as unknown as MetricasElefante} />,
      );
      expect(screen.getByTestId("plataforma-elefante")).toHaveTextContent(esperado);
      unmount();
    }
  });

  it("Panorama: o número das demais escolas diz que soma as sem uso, as sem dado e as protegidas", async () => {
    semearPanorama();
    renderTela("/", <PanoramaSecretaria />);
    const demais = await screen.findByTestId("numero-demais");
    await screen.findByTestId("lista-escolas");
    // Antes: "Sem uso registrado ou sem dado3" — com uma protegida dentro do 3.
    expect(demais).toHaveTextContent("Sem uso registrado, sem dado ou protegidas3");
    expect(demais).toHaveTextContent("1 sem uso registrado · 1 sem dado · 1 protegida");
  });
});
