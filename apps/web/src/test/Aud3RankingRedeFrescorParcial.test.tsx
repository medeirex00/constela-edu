/**
 * Ranking da Rede (Secretaria) — o estado "parcial" do frescor não é "coleta parcial"
 * (REV3-SERIE-2, costura da fase D).
 *
 * O estado vem de /redes/{id}/ranking/frescor (frescor_ranking.frescor_das_escolas): a
 * escola tem PARTE dos dados além do limite (algumas crianças com o retrato antigo). Numa
 * escola sem integração, ele aparece só com números digitados, sem coleta nenhuma —
 * afirmar "coleta parcial" ou "a última coleta foi parcial" era falso. O SeloFrescor da
 * mesma rede já diz "(ou parte dos dados antiga)"; o aviso do topo e o title do selo
 * "dados de …" da escola agora dizem o mesmo. Escolas fictícias.
 */
import { describe, expect, it } from "vitest";

import RankingDaRede from "../pages/rede/RankingRede";
import { renderComApp, responder, screen, usuarioFake } from "./utils";

const secretaria = usuarioFake({
  nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null,
});

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "Escola", cidade: "Cidade Inventada", status: "ativa",
    latitude: null, longitude: null, total_turmas: 5, total_professores: 4,
    total_alunos: 100, alunos_com_dados: 100, adocao: 100,
    media_geral: 70, media_matific: 70, media_elefante: 70,
    livros: 1000, tempo_leitura_min: 0, atividades: 0, estrelas: 0,
    ativos_matific: 100, ativos_elefante: 100, livros_por_aluno: 10,
    livros_por_matricula: 10, estrelas_por_matricula: 0,
    atividades_por_matricula: 0, tempo_por_matricula_min: 0,
    pontuacao_leitura: 500, pontuacao_matematica: 500, pontuacao_geral: 500,
    dimensoes_pontuadas: ["leitura", "matematica"],
    dimensoes_com_dados: ["leitura", "matematica"],
    alunos_com_nota_elefante: 100, alunos_com_nota_matific: 100,
    adocao_elefante: 100, adocao_matific: 100,
    precisa_atencao: false, motivo_atencao: null,
    ...over,
  };
}

const ESCOLA = cartao({ escola_id: 1, nome: "EMEF Fictícia Digitada" });

function bloco(over: Record<string, unknown> = {}) {
  return {
    plataforma: "elefante", contratada: true, estado: "em_dia",
    dado_mais_recente_em: "2026-10-19", dado_mais_antigo_em: "2026-10-19",
    dias_desde_dado: 1, alunos_com_dado: 100, alunos_com_dado_antigo: 0,
    ajuste_manual_mais_recente_em: null,
    ultima_sincronizacao_ok_em: null, dias_desde_sincronizacao_ok: null, ...over,
  };
}

describe("Ranking da Rede — frescor 'parcial' sem coleta", () => {
  it("o aviso e o selo falam de parte dos dados antiga, não de coleta parcial", async () => {
    responder("GET", "/redes/1/dashboard", {
      rede_id: 1, totais: {}, equidade: {}, atencao: [], escolas: [ESCOLA],
    });
    responder("GET", /^\/redes\/1\/ranking\?/, [{ ...ESCOLA, posicao: 1 }]);
    // Escola sem integração (sem sincronização nenhuma): números digitados, uma parte
    // deles com mais de 7 dias.
    responder("GET", "/redes/1/ranking/frescor", {
      limite_dias: 7, hoje: "2026-10-20",
      escolas: [
        { escola_id: 1, nome: "EMEF Fictícia Digitada", limite_dias: 7, hoje: "2026-10-20",
          estado: "parcial",
          dimensoes: {
            leitura: bloco({ estado: "parcial", dado_mais_antigo_em: "2026-09-01",
              alunos_com_dado_antigo: 30 }),
            matematica: bloco({ plataforma: "matific", estado: "parcial",
              dado_mais_antigo_em: "2026-09-01", alunos_com_dado_antigo: 30 }),
          } },
      ],
    });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent(
      /1 escola\(s\) deste ranking com dado de mais de 7 dias \(ou parte dos dados antiga\)/);
    expect(aviso).not.toHaveTextContent(/coleta parcial/);

    const selo = screen.getByText("dados de 19/10/2026", { selector: "span[title]" });
    expect(selo).toHaveAttribute(
      "title", "O dado desta escola passou de 7 dias (ou parte dos dados dela é antiga).");
    expect(selo.getAttribute("title")).not.toMatch(/coleta/);
  });
});
