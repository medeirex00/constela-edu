/**
 * G_MODULOS-8: "Corrigir turmas duplicadas" avisa, antes do clique, o grupo em que a
 * duplicada tem pontuação por nível própria (do Admin Global) — o servidor recusa
 * consolidá-lo — e não o deixa marcado.
 */
import Turmas from "../pages/Turmas";
import { renderComApp, responder, screen, turmaFake, userEvent } from "./utils";

const RECUSA = "A turma “3 ANO A” tem pontuação por nível própria, definida pelo Admin Global, "
  + "diferente da turma “3º Ano A”: consolidar apagaria essa configuração e mudaria os pontos "
  + "de dificuldade dos alunos. Por isso este grupo não é consolidado — peça ao Admin Global "
  + "para deixar as turmas com a mesma pontuação por nível (Critérios › Elefante Letrado › "
  + "Dificuldade por turma) e consolide depois.";

test("o grupo com pontuação por turma na duplicada mostra o motivo e vem desmarcado", async () => {
  responder("GET", "/escolas/1/turmas", [turmaFake()]);
  responder("GET", "/escolas/1/professores", []);
  responder("GET", "/escolas/1/turmas/duplicadas", [
    { chave: "3|A|", ano_letivo: 2026,
      canonica: { id: 1, nome: "3º Ano A", turno: null, alunos: 3 },
      duplicadas: [{ id: 2, nome: "3 ANO A", turno: null, alunos: 1 }],
      recusa: RECUSA },
    { chave: "4|B|", ano_letivo: 2026,
      canonica: { id: 3, nome: "4º Ano B", turno: null, alunos: 2 },
      duplicadas: [{ id: 4, nome: "4 ANO B", turno: null, alunos: 1 }],
      recusa: null },
  ]);
  renderComApp(<Turmas />, { rota: "/turmas" });

  await userEvent.click(await screen.findByRole("button", { name: /Corrigir duplicadas/ }));
  expect(await screen.findByText(/tem pontuação por nível própria/)).toHaveTextContent("⚠");
  const dialogo = screen.getByRole("dialog");
  const caixas = Array.from(dialogo.querySelectorAll("input[type=checkbox]")) as HTMLInputElement[];
  expect(caixas.map((c) => c.checked)).toEqual([false, true]);
  expect(screen.getByRole("button", { name: "Consolidar 1 grupo(s)" })).toBeEnabled();
});
