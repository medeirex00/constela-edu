/**
 * IMPORTACAO-4 / WEB-1 — o seletor "Turma para os novos alunos" começava na 1ª turma
 * da escola (`turmas[0]`), e "Criar aluno novo…" também: sem turma reconhecida no
 * relatório (texto colado do Matific) ou com a turma por aluno (Placar da escola), um
 * clique em "Aplicar a todos" punha todas as crianças novas numa turma que ninguém
 * escolheu — por cima da turma certa de cada linha. Agora os dois começam vazios
 * ("Escolha a turma"), "Aplicar a todos" só funciona depois de uma escolha e "Sim,
 * importar" espera a turma de cada "Criar aluno novo…".
 *
 * Prévias e turmas REAIS, gravadas por backend/tests/test_aud_impweb_aplicar_a_todos.py
 * (texto sem turma) e test_aud_impweb_turma_da_previa.py (Placar da escola). Dados
 * fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import Importacoes from "../pages/Importacoes";
import type { Analise, ResultadoImportacao, Turma } from "../lib/types";
import semTurma from "./fixtures/importacoes/previa_da_tela/sem_turma_analise.json";
import semTurmaTurmas from "./fixtures/importacoes/previa_da_tela/sem_turma_turmas.json";
import aplicar from "./fixtures/importacoes/previa_da_tela/aplicar_analise.json";
import aplicarTurmas from "./fixtures/importacoes/previa_da_tela/aplicar_turmas.json";
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
  turmas.find((t) => t.nome === nome)!.id;

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

async function corpoEnviado(u: ReturnType<typeof userEvent.setup>) {
  responder("POST", URL_CONFIRMAR, {
    mensagem: "ok", importacao_id: 1, qtd_alunos: 1, qtd_erros: 0, avisos: [],
  } satisfies ResultadoImportacao);
  await u.click(screen.getByRole("button", { name: "Sim, importar" }));
  const dialogo = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
  await u.click(within(dialogo).getByRole("button", { name: "Gravar importação" }));
  const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
  return JSON.parse(String((chamada?.[1] as RequestInit).body));
}

const massa = () => screen.getByRole("combobox", { name: "Turma para os novos alunos" }) as HTMLSelectElement;

describe("'Aplicar a todos' e 'Criar aluno novo…' não começam numa turma que ninguém escolheu", () => {
  it("texto colado sem turma: o seletor começa vazio e 'Aplicar a todos' espera a escolha", async () => {
    const corr = (semTurma as unknown as Analise).linhas[1].correspondencia!;
    expect([corr.status, corr.turma_id, corr.turma_nova]).toEqual(["nao_encontrado", null, null]);
    const u = await previa(semTurma, semTurmaTurmas);
    expect(massa().value).toBe("");
    expect(massa().options[massa().selectedIndex].textContent).toBe("Escolha a turma");
    expect(screen.getByRole("button", { name: "Aplicar a todos" })).toBeDisabled();

    await u.selectOptions(massa(), String(idDe(semTurmaTurmas, "4º Ano B")));
    await u.click(screen.getByRole("button", { name: "Aplicar a todos" }));
    const corpo = await corpoEnviado(u);
    expect(corpo.linhas.find((l: { nome: string }) => l.nome === "Crianca Ficticia Sem Ficha"))
      .toMatchObject({ aluno_id: null, criar_em_turma_id: idDe(semTurmaTurmas, "4º Ano B") });
  });

  it("'Criar aluno novo…' começa sem turma e 'Sim, importar' espera a escolha", async () => {
    const u = await previa(semTurma, semTurmaTurmas);
    const destino = screen.getByRole("combobox", { name: "Destino de Crianca Ficticia Sem Ficha" });
    await u.selectOptions(destino, "criar");
    const turma = screen.getByRole("combobox", { name: "Turma para Crianca Ficticia Sem Ficha" }) as HTMLSelectElement;
    expect(turma.value).toBe("");
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeDisabled();
    expect(screen.getByText("Escolha a turma de cada aluno novo em “Criar aluno novo…” para importar."))
      .toBeInTheDocument();

    await u.selectOptions(turma, String(idDe(semTurmaTurmas, "3º Ano A")));
    expect(screen.getByRole("button", { name: "Sim, importar" })).toBeEnabled();
    const corpo = await corpoEnviado(u);
    expect(corpo.linhas.find((l: { nome: string }) => l.nome === "Crianca Ficticia Sem Ficha"))
      .toMatchObject({ criar_em_turma_id: idDe(semTurmaTurmas, "3º Ano A") });
  });

  it("Placar da escola: 'Aplicar a todos' não troca a turma certa de cada linha pela 1ª turma da escola", async () => {
    const u = await previa(aplicar, aplicarTurmas);
    const t4b = idDe(aplicarTurmas, "4º Ano B");
    expect(massa().value).toBe("");
    // Sem escolha, o botão não faz nada (está desabilitado): as linhas ficam no 4º Ano B.
    expect(screen.getByRole("button", { name: "Aplicar a todos" })).toBeDisabled();
    const corpo = await corpoEnviado(u);
    expect(corpo.linhas.map((l: { criar_em_turma_id: number }) => l.criar_em_turma_id)).toEqual([t4b, t4b]);
  });
});
