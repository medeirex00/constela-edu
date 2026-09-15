import { useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";

import Rankings from "../pages/Rankings";
import type { RankingItem, RankingLeituraItem, Turma } from "../lib/types";
import {
  api, rankingItemFake, renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, waitFor,
  within,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_GERAL = "/escolas/1/ranking";
const URL_LEITURA = "/escolas/1/ranking/leitura";
const URL_MATEMATICA = "/escolas/1/sync/matific/placar-ao-vivo";
const URL_RESUMO = "/escolas/1/resumo-escola";

const DASHBOARD_REDE = {
  rede_id: 1, modulos: ["leitura", "matematica"], totais: {}, equidade: {}, atencao: [], escolas: [],
};

/** A navegação de CATEGORIAS desta tela. A página da rede tem um tablist
 *  próprio com o mesmo rótulo; o desta tela é o que traz a aba "Alunos". */
function navCategorias(): HTMLElement {
  const nav = screen.getAllByRole("tablist", { name: "Categoria do ranking" })
    .find((t) => within(t).queryByRole("tab", { name: "Alunos" }));
  if (!nav) throw new Error("Navegação de categorias não encontrada");
  return nav;
}

describe("Rankings (tela única com seletor)", () => {
  it("mostra o seletor e alterna o conteúdo sem trocar de página", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    // Geral (padrão, período "tudo") → endpoint /ranking
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);
    // Leitura → endpoint /ranking/leitura
    responder("GET", URL_LEITURA, [
      {
        posicao: 1, aluno_id: 20, nome: "Carla Leitora Silva", turma: "3º Ano A",
        ano_escolar: "3º Ano", livros: 9, pontos: 210, tempo_leitura_min: 60,
      },
    ] as RankingLeituraItem[]);

    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking" });

    // Cabeçalho único + os 4 tipos de ranking de alunos como abas do seletor.
    expect(await screen.findByText("Ranking Geral")).toBeInTheDocument();
    for (const rotulo of ["Geral", "Leitura", "Matemática", "Evolução"]) {
      expect(screen.getByRole("tab", { name: rotulo })).toBeInTheDocument();
    }

    // Começa no Geral: mostra o aluno do /ranking e as colunas da ordem única
    // ("Leitura" também é o nome de uma aba, então mira o cabeçalho da coluna).
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Leitura" })).toBeInTheDocument();
    expect(screen.getByText("Geral (Leitura + Matemática)", { exact: false })).toBeInTheDocument();

    // Troca para Leitura: só o CONTEÚDO muda (busca /ranking/leitura).
    await u.click(screen.getByRole("tab", { name: "Leitura" }));
    expect(await screen.findByRole("link", { name: /Carla Leitora Silva/ })).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader", { name: "Livros" }).length).toBeGreaterThan(0);
    // A classificação OFICIAL de Leitura abre no topo da aba.
    expect(screen.getByText("Classificação oficial — Leitura")).toBeInTheDocument();
    // A competição por turno avisa que o filtro de turma/série não vale para ela.
    expect(screen.getByText(
      "Sempre todas as turmas de cada turno — o filtro de turma e série acima não se aplica aqui.",
    )).toBeInTheDocument();
    // O cabeçalho da tela continua único (sem "voltar" para outra página).
    expect(screen.getByText("Ranking Geral")).toBeInTheDocument();
  });

  it("abas de categoria e de tipo apontam para o painel que controlam (aria-controls / tabpanel)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);

    renderComApp(<Rankings />, { rota: "/ranking" });
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();

    // 1º nível: o painel da categoria é rotulado pela aba ativa (Alunos).
    const abaAlunos = within(navCategorias()).getByRole("tab", { name: "Alunos" });
    const painelAlunos = screen.getByRole("tabpanel", { name: "Alunos" });
    expect(abaAlunos).toHaveAttribute("aria-controls", painelAlunos.id);
    expect(within(navCategorias()).getByRole("tab", { name: "Turmas" }))
      .toHaveAttribute("aria-controls", painelAlunos.id);
    expect(within(painelAlunos).getByRole("tablist", { name: "Tipo de ranking" })).toBeInTheDocument();

    // 2º nível: o painel do tipo é rotulado pela aba Geral e contém a lista.
    const abaGeral = screen.getByRole("tab", { name: "Geral" });
    const painelGeral = screen.getByRole("tabpanel", { name: "Geral" });
    expect(abaGeral).toHaveAttribute("aria-controls", painelGeral.id);
    expect(within(painelGeral).getByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
  });

  it("respeita o tipo vindo da URL (?ver=matematica) para deep-links/atalhos", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_MATEMATICA, {
      periodo: "Este mês", filtro: "start_date=2026-07-01&end_date=2026-07-14",
      atualizado_em: "2026-07-14T12:00:00Z", total: 1, com_link: 1,
      itens: [
        {
          posicao: 1, aluno_id: 30, nome: "Davi Mat Souza", turma: "3º Ano A",
          serie: "3", estrelas: 40, atividades: 12, pontuacao_media: 3.33,
        },
      ],
    });

    renderComApp(<Rankings />, { rota: "/ranking?ver=matematica", periodo: { preset: "mes" } });

    expect(screen.getByRole("tab", { name: "Matemática" })).toHaveAttribute(
      "aria-selected", "true");
    expect(await screen.findByRole("link", { name: /Davi Mat Souza/ })).toBeInTheDocument();
    expect(screen.getByText("Estrelas")).toBeInTheDocument();
  });

  it("segue a URL quando ela muda com a tela JÁ montada (atalho Alt+3/nav)", async () => {
    // Regressão: mudar só a query (?ver=) não remonta a rota; a aba tem que
    // acompanhar a URL mesmo assim (o seletor deriva o tipo do ?ver=).
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);
    responder("GET", "/escolas/1/ranking-evolucao", [
      {
        posicao: 1, aluno_id: 40, nome: "Eva Evolucao Lima", turma: "3º Ano A",
        nota_evolucao: 12,
        ganhos: { atividades: 3, estrelas: 1, livros: 2, tempo_leitura_min: 10, acertos: 4 },
      },
    ]);

    function Harness() {
      const nav = useNavigate();
      return (
        <>
          <button onClick={() => nav("/ranking?ver=evolucao")}>ir-evolucao</button>
          <Rankings />
        </>
      );
    }

    const u = userEvent.setup();
    renderComApp(<Harness />, { rota: "/ranking" });

    // Começa no Geral.
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();

    // Navegação EXTERNA muda só a query → a aba Evolução tem que assumir.
    await u.click(screen.getByRole("button", { name: "ir-evolucao" }));
    expect(await screen.findByRole("link", { name: /Eva Evolucao Lima/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Evolução" })).toHaveAttribute(
      "aria-selected", "true");
  });

  it("Geral com período ≠ ano letivo: avisa e o botão leva para a aba Evolução", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);
    responder("GET", "/escolas/1/ranking-evolucao", [
      {
        posicao: 1, aluno_id: 40, nome: "Eva Evolucao Lima", turma: "3º Ano A",
        nota_evolucao: 12,
        ganhos: { atividades: 3, estrelas: 1, livros: 2, tempo_leitura_min: 10, acertos: 4 },
      },
    ]);

    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking", periodo: { preset: "mes" } });

    // A ordem única do ano continua visível; o aviso aponta para a Evolução.
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    expect(screen.getByText(/A classificação por período fica na aba Evolução/)).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: /Ver a aba Evolução/ }));
    expect(await screen.findByRole("link", { name: /Eva Evolucao Lima/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Evolução" })).toHaveAttribute("aria-selected", "true");
  });

  it("escola sem turmas + turno guardado: a consulta final ao /ranking vai sem turno e o seletor mostra 'Todos os turnos'", async () => {
    responder("GET", URL_TURMAS, [] as Turma[]);
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);

    renderComApp(<Rankings />, { rota: "/ranking", turno: "manha" });

    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    // Sem turma nenhuma, nenhum turno existe nesta escola: a consulta que vale
    // (a última) vai SEM o parâmetro.
    await waitFor(() => {
      const chamadas = api.mock.calls.map((c) => String(c[0]))
        .filter((p) => p === URL_GERAL || p.startsWith(`${URL_GERAL}?`));
      expect(chamadas.length).toBeGreaterThan(0);
      const ultima = chamadas[chamadas.length - 1];
      expect(new URLSearchParams(ultima.split("?")[1] ?? "").has("turno")).toBe(false);
    });
    const seletor = screen.getByLabelText("Turno") as HTMLSelectElement;
    expect(seletor.value).toBe("todos");
    expect(seletor).toHaveDisplayValue("Todos os turnos");
    // ...sem apagar a escolha guardada (vale para outra escola).
    expect(localStorage.getItem("sgpe_turno")).toBe("manha");
  });

  it("categorias: coordenador vê Alunos e Turmas; ?ver=turmas abre o ranking de turmas", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A" })] as Turma[]);
    responder("GET", URL_RESUMO, {
      escola: { id: 1, nome: "Escola" },
      turmas: [{
        turma: { id: 1, nome: "3º Ano A", ano_escolar: "3º Ano" }, total_alunos: 20,
        media_leitura: 71.5, n_leitura: 18, media_matematica: 60, n_matematica: 10,
        media_elefante: 71.5, media_matific: 60,
      }],
    });

    renderComApp(<Rankings />, { rota: "/ranking?ver=turmas" });

    const categorias = await screen.findByRole("tablist", { name: "Categoria do ranking" });
    expect(within(categorias).getByRole("tab", { name: "Alunos" })).toBeInTheDocument();
    expect(within(categorias).getByRole("tab", { name: "Turmas" })).toHaveAttribute("aria-selected", "true");
    // Coordenador de escola NÃO é perfil de rede: sem "Escolas".
    expect(within(categorias).queryByRole("tab", { name: "Escolas" })).not.toBeInTheDocument();
    // Na categoria Turmas não há sub-abas de aluno.
    expect(screen.queryByRole("tab", { name: "Evolução" })).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "3º Ano A" })).toBeInTheDocument();
    expect(screen.getByText("71,5")).toBeInTheDocument();
  });

  it("professor vê só a categoria Alunos (sem seletor de categoria) e ?ver=turmas cai no Geral", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);

    renderComApp(<Rankings />, {
      rota: "/ranking?ver=turmas",
      usuario: usuarioFake({ cargo: "professor", is_global: false }),
    });

    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Categoria do ranking" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Turmas" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Geral" })).toHaveAttribute("aria-selected", "true");
  });

  it("Admin Global com escola selecionada vê Alunos, Turmas e Escolas (antes só via Escolas)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);

    renderComApp(<Rankings />, {
      rota: "/ranking",
      usuario: usuarioFake({ cargo: "admin", is_global: true, escola_id: null }),
    });

    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    const categorias = screen.getByRole("tablist", { name: "Categoria do ranking" });
    for (const rotulo of ["Alunos", "Turmas", "Escolas"]) {
      expect(within(categorias).getByRole("tab", { name: rotulo })).toBeInTheDocument();
    }
  });

  it("Secretaria vê só o ranking de ESCOLAS (a página da rede, com o próprio cabeçalho)", async () => {
    responder("GET", "/redes/1/dashboard", DASHBOARD_REDE);
    renderComApp(<Rankings />, {
      rota: "/ranking",
      usuario: usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null }),
    });

    expect(await screen.findByText("🏆 Ranking da Rede")).toBeInTheDocument();
    expect(screen.queryByText("Ranking Geral")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Alunos" })).not.toBeInTheDocument();
  });

  it("/rede/ranking (atalho 'Ranking de Escolas') abre na categoria Escolas mesmo com escola selecionada", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", "/redes/1/dashboard", DASHBOARD_REDE);
    responder("GET", "/redes", [{ id: 1, nome: "Rede Municipal" }]);

    renderComApp(<Rankings />, {
      rota: "/rede/ranking",
      usuario: usuarioFake({ cargo: "admin", is_global: true, escola_id: null }),
    });

    // A rota /rede/ranking É esta tela (roteada dentro da guarda de rede): abre
    // direto na página da rede, com o título dela e sem o "Ranking Geral".
    expect(await screen.findByRole("heading", { level: 1, name: "🏆 Ranking da Rede" })).toBeInTheDocument();
    expect(screen.queryByText("Ranking Geral")).not.toBeInTheDocument();
    // A navegação de categorias continua acima, para voltar a Alunos/Turmas.
    const categorias = navCategorias();
    expect(within(categorias).getByRole("tab", { name: "Escolas" })).toHaveAttribute("aria-selected", "true");
    expect(within(categorias).getByRole("tab", { name: "Alunos" })).toHaveAttribute("aria-selected", "false");
    // O ranking de alunos NÃO aparece nesse atalho. (Não dá para afirmar "nunca
    // consultado" aqui: este teste monta a tela SEM a guarda de sessão do App,
    // então há um render antes de /auth/me responder em que o perfil ainda não
    // é global; no app, a guarda só renderiza as rotas com o usuário carregado.)
    expect(screen.queryByRole("link", { name: /Ana Beatriz Souza/ })).not.toBeInTheDocument();
  });

  it("?ver=escolas: um único título de página (o da rede), sem o 'Ranking Geral' por cima", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", "/redes/1/dashboard", DASHBOARD_REDE);
    responder("GET", "/redes", [{ id: 1, nome: "Rede Municipal" }]);

    renderComApp(<Rankings />, {
      rota: "/ranking?ver=escolas",
      usuario: usuarioFake({ cargo: "admin", is_global: true, escola_id: null }),
    });

    expect(await screen.findByRole("heading", { level: 1, name: "🏆 Ranking da Rede" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.queryByText("Ranking Geral")).not.toBeInTheDocument();
    // O painel da categoria é rotulado pela aba ativa e contém a página da rede.
    const aba = within(navCategorias()).getByRole("tab", { name: "Escolas" });
    const painel = screen.getByRole("tabpanel", { name: "Escolas" });
    expect(aba).toHaveAttribute("aria-controls", painel.id);
    expect(within(painel).getByRole("heading", { level: 1, name: "🏆 Ranking da Rede" })).toBeInTheDocument();
  });
});
