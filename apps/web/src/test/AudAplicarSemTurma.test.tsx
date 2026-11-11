/**
 * REV-IMPWEB-1 (regressão de 2ae0f71e, IMPORTACAO-1) — "Aplicar a todos: turma do
 * relatório (nova)" punha "Criar na turma do relatório" também na criança que NÃO tem
 * turma no relatório: a linha nem oferece essa opção, o seletor passava a mostrar
 * "Criar aluno novo…" sem o seletor de turma, o rodapé a contava entre os importados
 * ("2 de 2") e o corpo levava ``criar_em_turma_nome`` nulo — que o backend manda para
 * Revisões ("sem_turma"). Agora o clique só alcança as linhas que têm turma do
 * relatório; a outra fica no destino em que estava.
 *
 * Prévia e turmas REAIS (Placar da escola sem turma no topo), gravadas por
 * backend/tests/test_aud_impweb_aplicar_sem_turma.py — que também confere, no backend,
 * o "sem_turma" do corpo antigo. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import Importacoes from "../pages/Importacoes";
import type { Analise, ResultadoImportacao, Turma } from "../lib/types";
import analise from "./fixtures/importacoes/previa_da_tela/placar_sem_turma_analise.json";
import turmas from "./fixtures/importacoes/previa_da_tela/placar_sem_turma_turmas.json";
import {
  api,
  fireEvent,
  renderComApp,
  responder,
  screen,
  userEvent,
  within,
} from "./utils";

const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";
const COM = "Crianca Ficticia Com Turma";
const SEM = "Crianca Ficticia Sem Turma";

const copia = <T,>(x: unknown) => JSON.parse(JSON.stringify(x)) as T;

async function previa() {
  const u = userEvent.setup();
  responder("GET", "/escolas/1/importacoes", []);
  responder("GET", "/escolas/1/turmas", copia<Turma[]>(turmas));
  responder("UPLOAD", "/escolas/1/importacoes/analisar", copia<Analise>(analise));
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
const opcoes = (s: HTMLSelectElement) => [...s.options].map((o) => o.value);

async function confirmarECorpo(u: ReturnType<typeof userEvent.setup>) {
  responder("POST", URL_CONFIRMAR, {
    mensagem: "ok", importacao_id: 1, qtd_alunos: 1, qtd_erros: 0, avisos: [],
  } satisfies ResultadoImportacao);
  await u.click(screen.getByRole("button", { name: "Sim, importar" }));
  const dialogo = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
  const textoDoDialogo = dialogo.textContent ?? "";
  await u.click(within(dialogo).getByRole("button", { name: "Gravar importação" }));
  const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
  const corpo = JSON.parse(String((chamada?.[1] as RequestInit).body));
  return { textoDoDialogo, linhas: corpo.linhas as Record<string, unknown>[] };
}

describe("'Aplicar a todos: turma do relatório (nova)' não alcança a criança sem turma no relatório", () => {
  it("a linha sem turma continua em 'Ignorar'; o rodapé, a confirmação e o corpo contam só a outra", async () => {
    const corr = (analise as unknown as Analise).linhas.map((l) => l.correspondencia!);
    expect(corr.map((c) => [c.status, c.turma_id, c.turma_nova])).toEqual([
      ["nao_encontrado", null, "1ºA"], ["nao_encontrado", null, null]]);
    const u = await previa();
    expect(destino(SEM).value).toBe("ignorar");
    // A linha sem turma não oferece "Criar na turma do relatório".
    expect(opcoes(destino(SEM))).toEqual(["criar", "ignorar"]);

    await u.click(screen.getByRole("button", { name: /Aplicar a todos: turma do relatório/ }));

    expect(destino(COM).value).toBe("criar_nova");
    expect(destino(SEM).value).toBe("ignorar");
    expect(screen.queryByRole("combobox", { name: `Turma para ${SEM}` })).not.toBeInTheDocument();
    expect(screen.getByText(/aluno\(s\) serão importados/).textContent)
      .toBe("1 de 2 aluno(s) serão importados.");

    const { textoDoDialogo, linhas } = await confirmarECorpo(u);
    expect(textoDoDialogo).toContain("1 de 2 aluno(s) do relatório");
    expect(textoDoDialogo).toContain("1 aluno(s) novo(s) (com a turma do relatório criada, se ainda não existir)");
    expect(textoDoDialogo).toContain("1 ignorado(s) — ficam de fora");
    expect(linhas.map((l) => [l.nome, l.criar_em_turma_id, l.criar_em_turma_nome, l.deixar_para_revisao]))
      .toEqual([[COM, null, "1 ANO A", false]]);
    // Nenhuma linha vai com "criar na turma do relatório" sem o nome da turma.
    expect(linhas.some((l) => l.aluno_id == null && l.criar_em_turma_id == null
      && l.criar_em_turma_nome == null && !l.deixar_para_revisao)).toBe(false);
  });

  it("a turma escolhida em 'Criar aluno novo…' na linha sem turma não é trocada pelo clique", async () => {
    const u = await previa();
    const id3a = (turmas as { id: number; nome: string }[]).find((t) => t.nome === "3º Ano A")!.id;
    await u.selectOptions(destino(SEM), "criar");
    await u.selectOptions(
      screen.getByRole("combobox", { name: `Turma para ${SEM}` }), String(id3a));

    await u.click(screen.getByRole("button", { name: /Aplicar a todos: turma do relatório/ }));

    expect(destino(SEM).value).toBe("criar");
    expect((screen.getByRole("combobox", { name: `Turma para ${SEM}` }) as HTMLSelectElement).value)
      .toBe(String(id3a));
    const { linhas } = await confirmarECorpo(u);
    expect(linhas.map((l) => [l.nome, l.criar_em_turma_id, l.criar_em_turma_nome])).toEqual([
      [COM, null, "1 ANO A"], [SEM, id3a, null]]);
  });
});
