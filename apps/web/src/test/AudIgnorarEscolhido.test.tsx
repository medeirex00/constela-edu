/**
 * IMPORTACAO-5 — "Aplicar a todos" trocava toda linha nova que não era "importar" nem
 * ia para a Revisão, inclusive a que o gestor tinha marcado "Ignorar" (linha de teste,
 * conta de professor, aluno de outra escola): a linha voltava para "Criar" e virava
 * ficha de criança. O "Ignorar" escolhido agora é preservado; o "Ignorar" padrão (a
 * linha sem turma, que ninguém escolheu) continua recebendo a ação de "Aplicar a todos".
 *
 * Prévias e turmas REAIS (backend/tests/test_aud_impweb_turma_da_previa.py e
 * test_aud_impweb_aplicar_a_todos.py). Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import Importacoes from "../pages/Importacoes";
import type { Analise, ResultadoImportacao, Turma } from "../lib/types";
import aplicar from "./fixtures/importacoes/previa_da_tela/aplicar_analise.json";
import aplicarTurmas from "./fixtures/importacoes/previa_da_tela/aplicar_turmas.json";
import semTurma from "./fixtures/importacoes/previa_da_tela/sem_turma_analise.json";
import semTurmaTurmas from "./fixtures/importacoes/previa_da_tela/sem_turma_turmas.json";
import {
  api,
  fireEvent,
  renderComApp,
  responder,
  screen,
  userEvent,
  within,
} from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";

const copia = <T,>(x: unknown) => JSON.parse(JSON.stringify(x)) as T;
const idDe = (turmas: { id: number; nome: string }[], nome: string) =>
  String(turmas.find((t) => t.nome === nome)!.id);

async function previa(analise: unknown, turmas: unknown) {
  const u = userEvent.setup();
  responder("GET", URL_HIST, []);
  responder("GET", URL_TURMAS, copia<Turma[]>(turmas));
  responder("UPLOAD", URL_ANALISAR, copia<Analise>(analise));
  renderComApp(
    <ImportacaoLoteProvider><Importacoes /></ImportacaoLoteProvider>, { rota: "/importacoes" });
  await screen.findByText("Nenhuma importação ainda");
  await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
  await u.type(screen.getByRole("textbox"), "relatorio");
  await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
  await screen.findByText("Prévia da importação");
  const data = screen.queryByLabelText("Data do relatório (obrigatória)");
  if (data) fireEvent.change(data, { target: { value: "2026-08-14" } });
  return u;
}

const destino = (nome: string) =>
  screen.getByRole("combobox", { name: `Destino de ${nome}` }) as HTMLSelectElement;

describe("'Aplicar a todos' respeita o 'Ignorar' que o gestor escolheu", () => {
  it("a linha marcada 'Ignorar' continua fora; a outra recebe a turma escolhida", async () => {
    const u = await previa(aplicar, aplicarTurmas);
    await u.selectOptions(destino("Crianca Ficticia Quarto Dois"), "ignorar");
    await u.selectOptions(screen.getByRole("combobox", { name: "Turma para os novos alunos" }),
      idDe(aplicarTurmas, "3º Ano A"));
    await u.click(screen.getByRole("button", { name: "Aplicar a todos" }));
    expect(destino("Crianca Ficticia Quarto Dois").value).toBe("ignorar");
    expect(destino("Crianca Ficticia Quarto Um").value).toBe("criar");
    expect((screen.getByRole("combobox", { name: "Turma para Crianca Ficticia Quarto Um" }) as HTMLSelectElement)
      .value).toBe(idDe(aplicarTurmas, "3º Ano A"));

    responder("POST", URL_CONFIRMAR, {
      mensagem: "ok", importacao_id: 1, qtd_alunos: 1, qtd_erros: 0, avisos: [],
    } satisfies ResultadoImportacao);
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const dialogo = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(dialogo).toHaveTextContent("1 ignorado(s) — ficam de fora");
    await u.click(within(dialogo).getByRole("button", { name: "Gravar importação" }));
    const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
    const corpo = JSON.parse(String((chamada?.[1] as RequestInit).body));
    expect(corpo.linhas.map((l: { nome: string }) => l.nome)).toEqual(["Crianca Ficticia Quarto Um"]);
  });

  it("o 'Ignorar' padrão (aluno novo sem turma, que ninguém escolheu) recebe a ação", async () => {
    const u = await previa(semTurma, semTurmaTurmas);
    expect(destino("Crianca Ficticia Sem Ficha").value).toBe("ignorar");
    await u.selectOptions(screen.getByRole("combobox", { name: "Turma para os novos alunos" }),
      idDe(semTurmaTurmas, "4º Ano B"));
    await u.click(screen.getByRole("button", { name: "Aplicar a todos" }));
    expect(destino("Crianca Ficticia Sem Ficha").value).toBe("criar");
  });
});
