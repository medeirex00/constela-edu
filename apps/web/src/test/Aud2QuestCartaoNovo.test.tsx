/**
 * Painel da turma: "Novo cartão do Quest" no menu de cada aluno (G_QUEST-1).
 *
 * A folha "só do professor" manda gerar o cartão novo de quem perdeu o dele (código e
 * QR novos; os antigos param de entrar) e a bible §21 trata isso como autosserviço,
 * mas a tela só reimprimia a turma: o cartão perdido seguia entrando. Agora o menu
 * do aluno oferece a ação, com confirmação, e ela chama o cartão individual com
 * `regenerar=true`. Para a ficha inativa a API revoga sem emitir cartão (204, sem PDF)
 * e a tela diz isso. Dados fictícios.
 */
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

const quest = vi.hoisted(() => ({
  baixarCartaoDoAluno: vi.fn(),
  baixarCartoesDaTurma: vi.fn(),
}));
vi.mock("@constela/quest-core", () => quest);

import TurmaDetalhe from "../pages/TurmaDetalhe";
import { ApiError, fireEvent, renderComApp, responder, screen, usuarioFake, within } from "./utils";

const RESUMO = {
  turma: { id: 5, nome: "3º Ano A", ano_escolar: "3º Ano" },
  total_alunos: 2, media_geral: 80, media_matific: 80, media_elefante: 80,
  indicadores: { livros_unicos: 3, tempo_leitura_min: 40 },
};

function alunoGestao(id: number, nome: string, status: string) {
  return {
    // Sem nota (a tela mostra "sem nota"): o teste não lê desempenho.
    id, nome, foto_url: null, numero_chamada: id, status, turma: "3º Ano A",
    ano_escolar: "3º Ano", created_at: null,
  };
}

const criar = URL.createObjectURL;
const revogar = URL.revokeObjectURL;
let baixados: string[] = [];

beforeEach(() => {
  quest.baixarCartaoDoAluno.mockReset();
  quest.baixarCartoesDaTurma.mockReset();
  baixados = [];
  Object.assign(URL, { createObjectURL: vi.fn(() => "blob:teste"), revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    baixados.push(this.download);
  });
  responder("GET", "/escolas/1/turmas/5/resumo", RESUMO);
  responder("GET", "/escolas/1/turmas", []);
  responder("GET", /\/escolas\/1\/turmas\/5\/alunos/, [
    alunoGestao(21, "Bruno Ficticio", "ativo"),
    alunoGestao(22, "Carla Ficticia", "arquivado"),
  ]);
});

afterEach(() => {
  Object.assign(URL, { createObjectURL: criar, revokeObjectURL: revogar });
  vi.restoreAllMocks();
});

function abrir(cargo = "professor") {
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: "/turmas/5", usuario: usuarioFake({ cargo }) },
  );
}

async function escolherNoMenu(aluno: string, item: string) {
  fireEvent.click(await screen.findByLabelText(`Ações de ${aluno}`));
  fireEvent.click(screen.getByRole("menuitem", { name: item }));
}

test("o menu do aluno gera o cartão novo com regenerar=true, depois de confirmar", async () => {
  quest.baixarCartaoDoAluno.mockResolvedValue({
    blob: new Blob(["%PDF-1.4"], { type: "application/pdf" }),
    nomeArquivo: "cartao-quest-bruno-ficticio.pdf",
  });
  abrir();
  await escolherNoMenu("Bruno Ficticio", "Novo cartão do Quest");

  // Confirmação antes: o cartão antigo deixa de entrar.
  const dialogo = await screen.findByRole("dialog");
  expect(dialogo).toHaveTextContent("Bruno Ficticio");
  expect(dialogo).toHaveTextContent(/cartão antigo para de entrar/);
  expect(quest.baixarCartaoDoAluno).not.toHaveBeenCalled();

  fireEvent.click(within(dialogo).getByRole("button", { name: "Gerar cartão novo" }));
  expect(await screen.findByText(/Cartão novo de Bruno Ficticio gerado/)).toBeInTheDocument();
  expect(quest.baixarCartaoDoAluno).toHaveBeenCalledWith(1, 21, true);
  expect(quest.baixarCartoesDaTurma).not.toHaveBeenCalled();
  expect(baixados).toEqual(["cartao-quest-bruno-ficticio.pdf"]);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("cancelar a confirmação não troca o cartão", async () => {
  abrir("admin");
  await escolherNoMenu("Bruno Ficticio", "Novo cartão do Quest");
  const dialogo = await screen.findByRole("dialog");
  fireEvent.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(quest.baixarCartaoDoAluno).not.toHaveBeenCalled();
});

test("ficha inativa: a revogação sai sem cartão novo (204) e a tela diz isso", async () => {
  quest.baixarCartaoDoAluno.mockResolvedValue({ blob: new Blob([]), nomeArquivo: "cartao-quest.pdf" });
  abrir();
  await escolherNoMenu("Carla Ficticia", "Revogar cartão do Quest");
  const dialogo = await screen.findByRole("dialog");
  expect(dialogo).toHaveTextContent(/não sai cartão novo/);

  fireEvent.click(within(dialogo).getByRole("button", { name: "Revogar cartão" }));
  expect(await screen.findByText(/Cartão do Quest de Carla Ficticia revogado/)).toBeInTheDocument();
  expect(quest.baixarCartaoDoAluno).toHaveBeenCalledWith(1, 22, true);
  expect(baixados).toEqual([]);
});

test("ficha inativa que nunca teve cartão (422): a tela explica, sem a mensagem genérica", async () => {
  quest.baixarCartaoDoAluno.mockRejectedValue(new ApiError(422, "Não foi possível gerar o PDF."));
  abrir();
  await escolherNoMenu("Carla Ficticia", "Revogar cartão do Quest");
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Revogar cartão" }));
  expect(await screen.findByText(/Carla Ficticia não tem cartão do Quest para revogar/)).toBeInTheDocument();
});
