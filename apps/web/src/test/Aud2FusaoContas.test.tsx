/**
 * ALUNOS-4: as telas de fusão não oferecem juntar duas fichas com contas
 * diferentes da mesma plataforma (o servidor recusa: os números das duas contas
 * se misturariam) e dizem por quê, antes do clique.
 */
import { vi } from "vitest";

import AcoesAluno from "../components/AcoesAluno";
import ModalAlunosDuplicados from "../components/ModalAlunosDuplicados";
import { api } from "../lib/__mocks__/api";
import type { Aluno } from "../lib/types";
import { renderComApp, responder, screen, userEvent } from "./utils";

const IMPACTO = {
  leituras: 0, snapshots_matific: 2, snapshots_elefante: 0,
  eventos: 0, notas: 0, plataformas: ["matific"],
};
const RECUSA = "As duas fichas têm contas diferentes no Matific: juntar as duas misturaria os "
  + "números das duas contas (a nota e a premiação sairiam de contas trocadas). Por isso esta "
  + "fusão não é feita — fale com o suporte.";

test("lote: o par com contas diferentes não vem marcado, mostra o motivo e fica fora do lote", async () => {
  responder("GET", "/escolas/1/alunos/duplicados", {
    total: 2, alta: 2, provavel: 0, revisar: 0,
    candidatos: [
      { loser_id: 10, manter_id: 11, apagar: "Lara Ficticia Prado", manter: "Lara Ficticia Prado",
        turma: "4º Ano B", confianca: "alta", motivo: "nome_identico", impacto: IMPACTO,
        recusa: RECUSA },
      { loser_id: 20, manter_id: 21, apagar: "Otto Ficticio Reis", manter: "Otto Ficticio Reis",
        turma: "4º Ano B", confianca: "alta", motivo: "nome_identico", impacto: IMPACTO,
        recusa: null },
    ],
  });
  renderComApp(<ModalAlunosDuplicados escolaId={1} aoFechar={() => {}} aoConcluir={() => {}} />);

  expect(await screen.findByText(/contas diferentes no Matific/)).toHaveTextContent("⚠");
  const caixas = screen.getAllByRole("checkbox") as HTMLInputElement[];
  expect(caixas.map((c) => c.checked)).toEqual([false, true]);
  await userEvent.click(screen.getByRole("button", { name: "Desmarcar todos" }));
  await userEvent.click(screen.getByRole("button", { name: "Selecionar todos" }));
  expect((screen.getAllByRole("checkbox") as HTMLInputElement[]).map((c) => c.checked))
    .toEqual([false, true]);
});

const aluno: Aluno = {
  id: 10, nome: "Lara Ficticia Prado", foto_url: null, numero_chamada: 3,
  status: "ativo", turma: "4º Ano B", ano_escolar: "4º Ano",
  data_nascimento: null, observacoes: null,
};

test("fusão manual: contas diferentes no Matific — avisa e não libera o botão", async () => {
  responder("GET", /\/alunos\?busca=/, {
    itens: [{ id: 20, nome: "Lara F Prado", status: "ativo", turma: "4º Ano B" }],
    total: 1, pagina: 1, por_pagina: 8,
  });
  responder("GET", /\/alunos\/fundir\/previa/, (caminho: string) => {
    const q = new URL(`http://x${caminho}`).searchParams;
    return {
      manter: { id: Number(q.get("manter_id")), nome: "x" },
      remover: { id: Number(q.get("remover_id")), nome: "y" },
      leituras: { livros_repetidos: 0, com_data_diferente: 0, no_bimestre: 0, bimestre: null,
                  por_bimestre: [], exemplos: [] },
      contas_em_conflito: ["matific"],
      recusa: RECUSA,
    };
  });
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />);
  await userEvent.click(screen.getByLabelText("Ações de Lara Ficticia Prado"));
  await userEvent.click(await screen.findByText("Fundir com outro aluno"));
  await userEvent.type(screen.getByPlaceholderText(/Buscar o cadastro duplicado/), "Lara");
  await userEvent.click(await screen.findByRole("button", { name: /Lara F Prado/ }));

  const aviso = await screen.findByRole("note", { name: /esta fusão não é feita/ });
  expect(aviso).toHaveTextContent("contas diferentes no Matific");
  await userEvent.type(screen.getByPlaceholderText("FUNDIR"), "FUNDIR");
  expect(screen.getByRole("button", { name: /Fundir cadastros/ })).toBeDisabled();
  expect(api.mock.calls.some(([c, o]) => String(c).endsWith("/alunos/fundir")
    && (o as RequestInit)?.method === "POST")).toBe(false);
});
