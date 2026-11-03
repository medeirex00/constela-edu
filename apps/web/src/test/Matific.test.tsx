import { describe, expect, it } from "vitest";

import type { MatificAluno } from "../lib/types";
import Matific from "../pages/Matific";
import { api, renderComApp, responder, responderErro, screen, userEvent, waitFor, within } from "./utils";

const URL_MATIFIC = "/escolas/1/matific";

function matificFake(over: Partial<MatificAluno> = {}): MatificAluno {
  return {
    aluno_id: 10,
    nome: "Ana Beatriz Souza",
    turma: "3º Ano A",
    ano_escolar: "3º Ano",
    atividades: 42,
    estrelas: 15,
    pontuacao_media: 87.5,
    data_referencia: "2026-06-01T10:00:00Z",
    ...over,
  };
}

const LINHAS = [
  matificFake(),
  matificFake({ aluno_id: 11, nome: "João Pedro Barbosa", atividades: 30, estrelas: 8 }),
];

/** PUTs disparados na aluna editada (para inspecionar o corpo enviado). */
function chamadasPut() {
  return api.mock.calls.filter(
    ([caminho, opcoes]) => caminho === "/escolas/1/matific/10"
      && (opcoes as RequestInit | undefined)?.method === "PUT",
  );
}

describe("Matific", () => {
  it("lista o estado atual dos alunos na plataforma", async () => {
    responder("GET", URL_MATIFIC, LINHAS);
    renderComApp(<Matific />, { rota: "/matific" });

    expect(await screen.findByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "João Pedro Barbosa" })).toBeInTheDocument();
    // Atividades da primeira linha (inteiro, sem formatação decimal frágil).
    expect(screen.getByText("42")).toBeInTheDocument();
    // Sem jargão em inglês na descrição (revisão v2): "histórico de alterações", não "log".
    expect(screen.getByText(/Edições manuais geram novo registro e ficam no histórico de alterações\./))
      .toBeInTheDocument();
    expect(screen.queryByText(/log de auditoria/)).toBeNull();
  });

  it("celular: a turma vai no chip sob o nome, a Média fica presa e os filtros empilham", async () => {
    // A coluna Turma sumia abaixo de 768 px e, no celular, Média e Editar ficavam fora
    // da tela sem aviso. Agora a turma está sob o nome (uma vez só no DOM), a Média é a
    // coluna presa à direita e o botão de editar tem 40 px no celular.
    responder("GET", URL_MATIFIC, [...LINHAS, matificFake({ aluno_id: 12, nome: "Carla Dias", turma: "4º Ano B" })]);
    renderComApp(<Matific />, { rota: "/matific" });

    const link = await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    const tabela = screen.getByRole("table");
    expect(within(tabela).queryByRole("columnheader", { name: "Turma" })).toBeNull();
    const celulas = within(link.closest("tr") as HTMLElement).getAllByRole("cell");
    expect(within(celulas[0]).getByText("3º Ano A")).toBeInTheDocument();
    expect(within(tabela).getByRole("columnheader", { name: "Média" })).toHaveClass("presa-celular");
    expect(celulas[3]).toHaveTextContent("87,5");
    expect(celulas[3]).toHaveClass("presa-celular");
    expect(screen.getByRole("button", { name: "Editar dados de Ana Beatriz Souza" }))
      .toHaveClass("max-sm:h-10", "max-sm:w-10");

    // Busca e turma: cada uma em linha inteira no celular; o select é nativo com a seta da v2.
    const turma = screen.getByRole("combobox", { name: "Filtrar por turma" });
    expect(turma).toHaveClass("appearance-none", "pr-10");
    expect(turma.parentElement).toHaveClass("w-full", "sm:w-48");
    expect(screen.getByRole("searchbox", { name: "Buscar aluno pelo nome" }).parentElement)
      .toHaveClass("w-full", "sm:w-60");
  });

  it("mostra o estado vazio quando nenhum aluno está ativo", async () => {
    responder("GET", URL_MATIFIC, []);
    renderComApp(<Matific />, { rota: "/matific" });

    expect(await screen.findByText("Nenhum aluno ativo")).toBeInTheDocument();
    expect(
      screen.getByText("Cadastre alunos ou importe um relatório da Matific."),
    ).toBeInTheDocument();
  });

  it("registro legado fora da escala 0–5: corrigir atividades não reenvia a média", async () => {
    // O modal pré-carrega a média gravada. Reenviá-la num registro legado (87,5)
    // devolvia 422 e travava a correção — restando ao gestor INVENTAR um número
    // ≤ 5 no lugar do medido. A média só viaja quando é editada.
    const u = userEvent.setup();
    responder("GET", URL_MATIFIC, LINHAS);
    responder("PUT", "/escolas/1/matific/10", (_caminho, corpo) => {
      const dados = JSON.parse((corpo as RequestInit).body as string);
      return matificFake({ ...dados, pontuacao_media: 87.5 });
    });
    renderComApp(<Matific />, { rota: "/matific" });

    await u.click(await screen.findByRole("button", { name: "Editar dados de Ana Beatriz Souza" }));
    // A tela explica o registro fora da escala em vez de só recusar o salvamento.
    expect(await screen.findByText(/fora da escala atual/)).toBeInTheDocument();

    const atividades = screen.getByLabelText("Atividades finalizadas");
    await u.clear(atividades);
    await u.type(atividades, "45");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    await waitFor(() => expect(chamadasPut()).toHaveLength(1));
    const corpo = JSON.parse(String((chamadasPut()[0][1] as RequestInit).body));
    expect(corpo.atividades).toBe(45);
    // Ausente = "não mexi nisso": o servidor preserva a média medida.
    expect(corpo).not.toHaveProperty("pontuacao_media");
  });

  it("média acima de 5 é barrada no cliente, em português, sem chamar a API", async () => {
    const u = userEvent.setup();
    responder("GET", URL_MATIFIC, LINHAS);
    renderComApp(<Matific />, { rota: "/matific" });

    await u.click(await screen.findByRole("button", { name: "Editar dados de Ana Beatriz Souza" }));
    const media = await screen.findByLabelText(/Pontuação média \(0 a 5\)/);
    await u.clear(media);
    await u.type(media, "85");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    // Antes: 422 do Pydantic em inglês ("Input should be less than or equal to 5").
    expect(await screen.findByText(/A média do Matific vai de 0 a 5/)).toBeInTheDocument();
    expect(chamadasPut()).toHaveLength(0);
  });

  it("mostra falha quando a API erra", async () => {
    responderErro("GET", URL_MATIFIC, 500, "Erro interno");
    renderComApp(<Matific />, { rota: "/matific" });

    expect(await screen.findByText("Não foi possível carregar")).toBeInTheDocument();
  });

  it("abre a edição e salva os dados via PUT", async () => {
    const u = userEvent.setup();
    responder("GET", URL_MATIFIC, LINHAS);
    responder("PUT", "/escolas/1/matific/10", (_caminho, corpo) => {
      const dados = JSON.parse((corpo as RequestInit).body as string);
      return matificFake({ ...dados });
    });
    renderComApp(<Matific />, { rota: "/matific" });

    // Abre o modal de edição da primeira aluna.
    await u.click(await screen.findByRole("button", { name: "Editar dados de Ana Beatriz Souza" }));
    expect(await screen.findByText("Editar Matific — Ana Beatriz Souza")).toBeInTheDocument();

    // Ajusta um campo auditável e salva.
    const motivo = screen.getByLabelText(/Motivo da edição/);
    await u.type(motivo, "correção do relatório");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    // O PUT foi disparado no endpoint da aluna editada.
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/escolas/1/matific/10",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    // E o modal fecha após salvar com sucesso.
    await waitFor(() =>
      expect(screen.queryByText("Editar Matific — Ana Beatriz Souza")).not.toBeInTheDocument(),
    );
    // Depois de salvar, a lista continua na tela.
    expect(screen.getByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
  });

  it("busca pelo nome e filtra por turma só na tela (sem nova consulta)", async () => {
    const u = userEvent.setup();
    responder("GET", URL_MATIFIC, [
      ...LINHAS,
      matificFake({ aluno_id: 12, nome: "Carla Dias", turma: "4º Ano B", atividades: 7 }),
    ]);
    renderComApp(<Matific />, { rota: "/matific" });
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    const consultas = api.mock.calls.length;

    await u.type(screen.getByRole("searchbox", { name: "Buscar aluno pelo nome" }), "joao");
    expect(screen.getByRole("link", { name: "João Pedro Barbosa" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ana Beatriz Souza" })).toBeNull();
    expect(screen.getByText("1 de 3 alunos")).toBeInTheDocument();

    await u.clear(screen.getByRole("searchbox", { name: "Buscar aluno pelo nome" }));
    await u.selectOptions(screen.getByRole("combobox", { name: "Filtrar por turma" }), "4º Ano B");
    expect(screen.getByRole("link", { name: "Carla Dias" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "João Pedro Barbosa" })).toBeNull();

    // Filtro sem resultado: estado vazio com "Limpar filtros", que devolve a lista.
    await u.type(screen.getByRole("searchbox", { name: "Buscar aluno pelo nome" }), "zzz");
    expect(screen.getByText("Nenhum aluno com esses filtros")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Limpar filtros" }));
    expect(screen.getAllByRole("link")).toHaveLength(3);
    expect(api.mock.calls.length).toBe(consultas);
  });
});
