/**
 * G_LGPD-3: as duas telas de fusão dizem o que acontece com o Constela Quest
 * (o progresso e o cartão que a criança usa) e não oferecem a fusão que o servidor
 * vai recusar (as duas fichas com progresso no jogo).
 */
import { vi } from "vitest";

import AcoesAluno from "../components/AcoesAluno";
import ModalAlunosDuplicados from "../components/ModalAlunosDuplicados";
import { api } from "../lib/__mocks__/api";
import type { Aluno } from "../lib/types";
import { renderComApp, responder, screen, userEvent } from "./utils";

const IMPACTO = {
  leituras: 0, snapshots_matific: 0, snapshots_elefante: 0,
  eventos: 0, notas: 0, plataformas: [],
};
const SEM_LEITURAS = {
  livros_repetidos: 0, com_data_diferente: 0, no_bimestre: 0, bimestre: null,
  por_bimestre: [], exemplos: [],
};
const TEXTO_MOVE = "Constela Quest: o progresso de “Ana Beatriz Souza” passa para a ficha que fica; "
  + "vale o cartão de “Ana Beatriz Souza”, que é o que a criança usa, e o de "
  + "“Ana Beatriz Souza Lima” deixa de entrar.";
const TEXTO_CONFLITO = "As duas fichas têm progresso no Constela Quest: esta fusão não será feita, "
  + "porque juntar as duas apagaria o progresso de uma delas. Fale com o suporte.";

function previaLote() {
  return {
    total: 2, alta: 2, provavel: 0, revisar: 0,
    candidatos: [
      { loser_id: 10, manter_id: 11, apagar: "Ana Beatriz Souza", manter: "Ana Beatriz Souza Lima",
        turma: "3º Ano A", confianca: "alta", motivo: "nome_identico", impacto: IMPACTO,
        quest: { tem_quest: true, conflito: false, texto: TEXTO_MOVE } },
      { loser_id: 20, manter_id: 21, apagar: "Caio Ficticio Rocha", manter: "Caio Ficticio Rocha",
        turma: "3º Ano A", confianca: "alta", motivo: "nome_identico", impacto: IMPACTO,
        quest: { tem_quest: true, conflito: true, texto: TEXTO_CONFLITO } },
    ],
  };
}

const noop = () => {};

test("lote: cada par diz o que acontece com o Quest; o par em conflito não vem marcado", async () => {
  responder("GET", "/escolas/1/alunos/duplicados", previaLote());
  renderComApp(<ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

  expect(await screen.findByText(TEXTO_MOVE)).toBeInTheDocument();
  expect(screen.getByText(new RegExp(TEXTO_CONFLITO.slice(0, 40)))).toBeInTheDocument();
  const caixas = screen.getAllByRole("checkbox") as HTMLInputElement[];
  expect(caixas[0].checked).toBe(true);
  expect(caixas[1].checked).toBe(false);   // "alta", mas o servidor vai recusar

  // "Desmarcar/Selecionar todos" não põe o par em conflito na conta.
  await userEvent.click(screen.getByRole("button", { name: "Desmarcar todos" }));
  await userEvent.click(screen.getByRole("button", { name: "Selecionar todos" }));
  expect((screen.getAllByRole("checkbox") as HTMLInputElement[]).map((c) => c.checked))
    .toEqual([true, false]);

  await userEvent.click(screen.getByRole("button", { name: /Unir 1 selecionada/ }));
  expect(await screen.findByText(/No Constela Quest, ficam o progresso e o cartão que a criança usa/))
    .toBeInTheDocument();
});

test("lote: marcar o par em conflito à mão avisa, na confirmação, que ele não será unido", async () => {
  responder("GET", "/escolas/1/alunos/duplicados", previaLote());
  renderComApp(<ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);
  await screen.findByText(TEXTO_MOVE);
  await userEvent.click((screen.getAllByRole("checkbox") as HTMLInputElement[])[1]);
  await userEvent.click(screen.getByRole("button", { name: /Unir 2 selecionada/ }));
  expect(await screen.findByText(/1 par\(es\) marcado\(s\) não será\(ão\) unido\(s\)/))
    .toBeInTheDocument();
});

const aluno: Aluno = {
  id: 10, nome: "Ana Beatriz Souza", foto_url: null, numero_chamada: 1,
  status: "ativo", turma: "3º Ano A", ano_escolar: "3º Ano",
  data_nascimento: null, observacoes: null,
};

async function abrirFusao(quest: object) {
  responder("GET", /\/alunos\?busca=/, {
    itens: [{ id: 20, nome: "Ana Beatriz Souza Lima", status: "ativo", turma: "3º Ano A" }],
    total: 1, pagina: 1, por_pagina: 8,
  });
  responder("GET", /\/alunos\/fundir\/previa/, (caminho: string) => {
    const q = new URL(`http://x${caminho}`).searchParams;
    return {
      manter: { id: Number(q.get("manter_id")), nome: "x" },
      remover: { id: Number(q.get("remover_id")), nome: "y" },
      leituras: SEM_LEITURAS,
      quest,
    };
  });
  responder("POST", /\/alunos\/fundir$/, { ok: true });
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />);
  await userEvent.click(screen.getByLabelText("Ações de Ana Beatriz Souza"));
  await userEvent.click(await screen.findByText("Fundir com outro aluno"));
  await userEvent.type(screen.getByPlaceholderText(/Buscar o cadastro duplicado/), "Ana");
  await userEvent.click(await screen.findByRole("button", { name: /Ana Beatriz Souza Lima/ }));
}

test("fusão manual: as duas fichas com progresso no Quest — avisa e não libera o botão", async () => {
  await abrirFusao({ tem_quest: true, conflito: true, texto: TEXTO_CONFLITO });
  const aviso = await screen.findByRole("note", { name: /Constela Quest/ });
  expect(aviso).toHaveTextContent("As duas fichas têm progresso no Constela Quest");
  await userEvent.type(screen.getByPlaceholderText("FUNDIR"), "FUNDIR");
  expect(screen.getByRole("button", { name: /Fundir cadastros/ })).toBeDisabled();
  expect(api.mock.calls.some(([c, o]) => String(c).endsWith("/alunos/fundir")
    && (o as RequestInit)?.method === "POST")).toBe(false);
});

test("fusão manual: diz o que fica do Quest e libera a fusão", async () => {
  await abrirFusao({ tem_quest: true, conflito: false, texto: TEXTO_MOVE });
  expect(await screen.findByText(TEXTO_MOVE)).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("FUNDIR"), "FUNDIR");
  expect(screen.getByRole("button", { name: /Fundir cadastros/ })).toBeEnabled();
});
