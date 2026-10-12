/**
 * MÓDULOS CONTRATADOS (SaaS) no frontend: a interface se adapta ao plano da rede.
 *
 * Regra que estes testes travam: o que a rede NÃO contratou não aparece — nem
 * como zero, nem como aba vazia. E "sem dados" continua diferente de "não
 * contratado" (o primeiro aparece, vazio).
 */
import { describe, expect, it } from "vitest";

import { useModulosDaEscola } from "../hooks/useModulos";
import RankingDaRede from "../pages/rede/RankingRede";
import {
  escolaComContrato, escolaFake, renderComApp, responder, screen, userEvent, usuarioFake, waitFor,
} from "./utils";

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EM Teste", cidade: "Caraguatatuba", status: "ativa",
    latitude: null, longitude: null, total_turmas: 5, total_professores: 4,
    total_alunos: 100, alunos_com_dados: 100, adocao: 100,
    media_geral: 75, media_matific: 80, media_elefante: 70,
    dimensoes_com_dados: ["leitura", "matematica"],
    alunos_com_nota_elefante: 100, alunos_com_nota_matific: 100,
    adocao_elefante: 100, adocao_matific: 100,
    livros: 500, tempo_leitura_min: 6000, atividades: 900, estrelas: 1200,
    ativos_matific: 100, ativos_elefante: 100, livros_por_aluno: 5,
    livros_por_matricula: 5, estrelas_por_matricula: 12,
    atividades_por_matricula: 9, tempo_por_matricula_min: 60,
    pontuacao_leitura: 1000, pontuacao_matematica: 1000, pontuacao_geral: 1000,
    dimensoes_pontuadas: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null,
    ...over,
  };
}

function painel(modulos: string[], over: Record<string, unknown> = {}) {
  return {
    rede_id: 1, modulos, totais: {}, equidade: {}, atencao: [],
    escolas: [cartao(over)],
  };
}

const secretaria = (modulos: string[]) => usuarioFake({
  nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null, modulos,
});

describe("Módulos contratados — Ranking da Rede", () => {
  it("A) ambos contratados: as 4 abas aparecem", async () => {
    responder("GET", "/redes/1/dashboard", painel(["leitura", "matematica"]));
    renderComApp(<RankingDaRede />, { usuario: secretaria(["leitura", "matematica"]) });
    await screen.findByText("🏆 Ranking da Rede");

    for (const aba of ["Geral", "Leitura", "Matemática", "Engajamento"]) {
      expect(screen.getByRole("tab", { name: new RegExp(aba, "i") })).toBeInTheDocument();
    }
  });

  it("B) só Leitura: a aba Matemática não existe", async () => {
    responder("GET", "/redes/1/dashboard", painel(["leitura"]));
    renderComApp(<RankingDaRede />, { usuario: secretaria(["leitura"]) });
    await screen.findByText("🏆 Ranking da Rede");

    expect(screen.getByRole("tab", { name: /Leitura/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Matemática/i })).not.toBeInTheDocument();
    // Geral e Engajamento valem para qualquer plano.
    expect(screen.getByRole("tab", { name: /Geral/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Engajamento/i })).toBeInTheDocument();
  });

  it("C) só Matemática: a aba Leitura não existe", async () => {
    responder("GET", "/redes/1/dashboard", painel(["matematica"]));
    renderComApp(<RankingDaRede />, { usuario: secretaria(["matematica"]) });
    await screen.findByText("🏆 Ranking da Rede");

    expect(screen.getByRole("tab", { name: /Matemática/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /^Leitura$/i })).not.toBeInTheDocument();
  });

  it("o explicador só explica o módulo contratado", async () => {
    responder("GET", "/redes/1/dashboard", painel(["leitura"]));
    renderComApp(<RankingDaRede />, { usuario: secretaria(["leitura"]) });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    expect(screen.getByText(/Nota de Leitura \(0–100\)/i)).toBeInTheDocument();
    expect(screen.queryByText(/Nota de Matemática \(0–100\)/i)).not.toBeInTheDocument();
    // E diz explicitamente que a Geral é a própria Leitura nesta rede.
    expect(screen.getByText(/apenas a Leitura/i)).toBeInTheDocument();
  });

  it("D) contratado SEM dados continua aparecendo (≠ não contratado)", async () => {
    // Matific contratado, mas nenhuma escola tem dado dele.
    responder("GET", "/redes/1/dashboard",
      painel(["leitura", "matematica"], {
        ativos_matific: 0, media_matific: 0, pontuacao_matematica: 0,
        dimensoes_com_dados: ["leitura"], dimensoes_pontuadas: ["leitura"],
        adocao_matific: 0,
      }));
    renderComApp(<RankingDaRede />, { usuario: secretaria(["leitura", "matematica"]) });
    await screen.findByText("🏆 Ranking da Rede");

    // A aba CONTINUA lá — o módulo faz parte do plano, só não tem dados ainda.
    expect(screen.getByRole("tab", { name: /Matemática/i })).toBeInTheDocument();
  });
});

/** Mostra o que `useModulosDaEscola` resolve, para o teste ler. */
function SondaModulosDaEscola() {
  const { modulos } = useModulosDaEscola();
  return <p data-testid="modulos">{modulos.join(",")}</p>;
}

describe("useModulosDaEscola — o contrato da ESCOLA aberta", () => {
  // O Admin Global recebe o catálogo inteiro no /auth/me; as rotas da escola
  // exigem o plano da rede DELA (403 fora dele). Sem este hook, a aba
  // Desempenho, o Top 5 e as colunas da turma consultavam a matéria recusada.
  it("Admin Global numa escola cuja rede só contratou Matemática: só Matemática", async () => {
    renderComApp(<SondaModulosDaEscola />, {
      usuario: usuarioFake({ cargo: "admin", is_global: true, escola_id: null,
                             modulos: ["leitura", "matematica"] }),
      escolas: [escolaComContrato(["matematica"])],
    });
    await waitFor(() => expect(screen.getByTestId("modulos")).toHaveTextContent(/^matematica$/));
  });

  it("vale o que está no plano do usuário E no da escola (interseção)", async () => {
    renderComApp(<SondaModulosDaEscola />, {
      usuario: usuarioFake({ modulos: ["leitura"] }),
      escolas: [escolaComContrato(["leitura", "matematica"])],
    });
    await waitFor(() => expect(screen.getByTestId("modulos")).toHaveTextContent(/^leitura$/));
  });

  it("API anterior (escola sem `modulos`): cai no plano do usuário, como antes", async () => {
    renderComApp(<SondaModulosDaEscola />, {
      usuario: usuarioFake({ cargo: "admin", is_global: true, escola_id: null }),
      escolas: [escolaFake()],
    });
    await screen.findByTestId("modulos");
    expect(screen.getByTestId("modulos")).toHaveTextContent(/^leitura,matematica$/);
  });
});
