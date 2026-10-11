/**
 * Suporte: o guia do perfil, as dúvidas comuns, a regra da nota COMO O SERVIDOR
 * A DEVOLVE (nenhum número da fórmula mora na tela), o exemplo interativo para a
 * gestão e a orientação de sincronização.
 */
import { describe, expect, it } from "vitest";

import Suporte, { PASTAS_GUIAS, type RegraPontuacao } from "../pages/Suporte";
import { FAQ_COORDENACAO, FAQ_PROFESSOR, FAQ_SECRETARIA } from "../pages/suporteConteudo";
import { escolaFake, renderComApp, responder, responderErro, screen, usuarioFake } from "./utils";

const URL_REGRA = "/escolas/1/configuracoes/pontuacao/regra";

function regra(over: Partial<RegraPontuacao> = {}): RegraPontuacao {
  return {
    perfil: "institucional",
    versoes: {
      composicao: "por_dimensao_v1",
      dificuldade: "elefante_dificuldade_v2",
      dificuldade_da_rede: "elefante_dificuldade_v2",
    },
    // Números de TESTE, diferentes dos oficiais: a tela tem de mostrar o que a
    // API manda, não o que ela "sabe".
    dimensoes: [
      { dimensao: "leitura", plataforma: "elefante", contratada: true,
        pesos: { livros: 41, dificuldade: 29, questoes: 25, tempo: 5 },
        subpesos_questoes: { tentativas: 33, acertos: 67 } },
      { dimensao: "matematica", plataforma: "matific", contratada: true,
        pesos: { atividades: 44, media: 31, estrelas: 25 } },
    ],
    normalizacao: { modo: "auto", percentil_referencia: 87, minimo_alunos_percentil: 11,
                    indicadores_volume: ["atividades", "livros"] },
    ...over,
  };
}

const coordenadora = usuarioFake({ cargo: "coordenador", is_global: false });
const professor = usuarioFake({ cargo: "professor", is_global: false });
const secretaria = usuarioFake({ cargo: "coordenador", rede_id: 7 });

function abrir(usuario = coordenadora, dados: RegraPontuacao | null = regra()) {
  if (dados) responder("GET", URL_REGRA, dados);
  return renderComApp(<Suporte />, {
    usuario, escolas: [escolaFake({ id: 1 })],
    ...(usuario.rede_id != null ? { escolaSelecionada: 1 } : {}),
  });
}

describe("Suporte — conteúdo por perfil", () => {
  it("coordenação: guia da coordenação, dúvidas, regra, exemplo e Integrações", async () => {
    abrir();
    const guia = await screen.findByRole("link", { name: "Abrir o Guia da Coordenação" });
    expect(guia).toHaveAttribute("href", PASTAS_GUIAS.coordenacao);
    expect(guia).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: "Ver todos os guias" })).toHaveAttribute("href", PASTAS_GUIAS.todos);
    for (const p of FAQ_COORDENACAO) expect(screen.getByText(p.pergunta)).toBeInTheDocument();
    expect(await screen.findByText("Quer ver um exemplo?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir Integrações" })).toHaveAttribute("href", "/sincronizacao");
  });

  it("professor: guia do professor, sem o exemplo da gestão nem o atalho de Integrações", async () => {
    abrir(professor);
    expect(await screen.findByRole("link", { name: "Abrir o Guia do Professor" }))
      .toHaveAttribute("href", PASTAS_GUIAS.professor);
    for (const p of FAQ_PROFESSOR) expect(screen.getByText(p.pergunta)).toBeInTheDocument();
    expect((await screen.findAllByText(/livros únicos/)).length).toBeGreaterThan(0);
    expect(screen.queryByText("Quer ver um exemplo?")).toBeNull();
    expect(screen.queryByRole("link", { name: "Abrir Integrações" })).toBeNull();
  });

  it("Secretaria: guia da Secretaria", async () => {
    abrir(secretaria);
    expect(await screen.findByRole("link", { name: "Abrir o Guia da Secretaria" }))
      .toHaveAttribute("href", PASTAS_GUIAS.secretaria);
    for (const p of FAQ_SECRETARIA) expect(screen.getByText(p.pergunta)).toBeInTheDocument();
  });

  it("toda lista de dúvidas tem conteúdo", () => {
    for (const lista of [FAQ_COORDENACAO, FAQ_PROFESSOR, FAQ_SECRETARIA]) {
      expect(lista.length).toBeGreaterThan(0);
      for (const p of lista) expect(p.resposta.length).toBeGreaterThan(20);
    }
  });
});

describe("Suporte — a regra da nota vem do servidor", () => {
  it("mostra os pesos, o percentil e a amostra mínima EXATAMENTE como a API devolve", async () => {
    abrir();
    expect(await screen.findByText("41%")).toBeInTheDocument();
    expect(screen.getByText("44%")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
    expect(screen.getByText(/percentil 87/)).toBeInTheDocument();
    expect(screen.getByText(/pelo menos\s+11 alunos/)).toBeInTheDocument();
    expect(screen.getByText(/régua da rede/)).toBeInTheDocument();
    expect(screen.getByText(/elefante_dificuldade_v2/)).toBeInTheDocument();
    // Ausência não é zero.
    expect(screen.getByText(/fora do ranking daquela matéria/)).toBeInTheDocument();
  });

  it("régua própria da escola e referências manuais aparecem como tais", async () => {
    abrir(coordenadora, regra({
      perfil: "personalizado",
      versoes: { composicao: "por_dimensao_v1", dificuldade: "escola_legada_v0",
                 dificuldade_da_rede: "elefante_dificuldade_v2" },
      normalizacao: { modo: "manual", percentil_referencia: 90, minimo_alunos_percentil: 8,
                      indicadores_volume: [] },
    }));
    expect(await screen.findByText(/régua própria, autorizada/)).toBeInTheDocument();
    expect(screen.getByText(/modo manual/)).toBeInTheDocument();
    expect(screen.getByText(/régua própria da escola, por faixa de nível/)).toBeInTheDocument();
  });

  it("matéria fora do plano: diz que não há nota, sem pesos", async () => {
    const r = regra();
    r.dimensoes[1] = { ...r.dimensoes[1], contratada: false };
    abrir(coordenadora, r);
    expect(await screen.findByText(/não faz parte do plano da rede/)).toBeInTheDocument();
    expect(screen.queryByText("44%")).toBeNull();
  });

  it("falha da API: mensagem amigável e nenhum número inventado", async () => {
    responderErro("GET", URL_REGRA, 500, "erro");
    abrir(coordenadora, null);
    expect(await screen.findByText(/Não foi possível carregar a regra da nota/)).toBeInTheDocument();
    expect(screen.queryByText(/%$/)).toBeNull();
  });
});
