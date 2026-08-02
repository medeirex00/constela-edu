import { describe, expect, it } from "vitest";

import ModalAlunosDuplicados from "../components/ModalAlunosDuplicados";
import { renderComApp, responder, screen, userEvent } from "./utils";

const URL_PREVIA = "/escolas/1/alunos/duplicados";
const URL_CORRIGIR = "/escolas/1/alunos/duplicados/corrigir";

function previa() {
  return {
    total: 3,
    alta: 1,
    provavel: 1,
    revisar: 1,
    candidatos: [
      {
        loser_id: 10, manter_id: 11,
        apagar: "Bruno Alves Costa", manter: "Bruno Alves Costa",
        turma: "4º C", confianca: "alta", motivo: "nome_identico",
        impacto: {
          leituras: 2, snapshots_matific: 1, snapshots_elefante: 0,
          eventos: 3, notas: 1, plataformas: ["matific"],
        },
      },
      {
        loser_id: 20, manter_id: 21,
        apagar: "Akemi Carolina Vieira",
        manter: "Akemi Carolina Vieira Gomes Kariya",
        turma: "4º C", confianca: "provavel", motivo: "subconjunto",
        impacto: {
          leituras: 0, snapshots_matific: 0, snapshots_elefante: 1,
          eventos: 0, notas: 0, plataformas: ["elefante"],
        },
      },
      {
        loser_id: 30, manter_id: 31,
        apagar: "Ana B", manter: "Ana Beatriz Souza",
        turma: "4º C", confianca: "revisar", motivo: "abreviacao",
        impacto: {
          leituras: 0, snapshots_matific: 1, snapshots_elefante: 0,
          eventos: 0, notas: 0, plataformas: ["matific"],
        },
      },
    ],
  };
}

const noop = () => {};

describe("ModalAlunosDuplicados", () => {
  it("pré-marca só a 'alta'; 'provável' e 'revisar' vêm desmarcadas", async () => {
    responder("GET", URL_PREVIA, previa());
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    expect(await screen.findByText("Akemi Carolina Vieira")).toBeInTheDocument();
    const caixas = screen.getAllByRole("checkbox") as HTMLInputElement[];
    // Ordem dos grupos: 🟢 alta (Bruno) → 🟡 provável (Akemi) → 🔴 revisar (Ana B).
    expect(caixas[0].checked).toBe(true);   // alta pré-marcada
    expect(caixas[1].checked).toBe(false);  // provável NÃO pré-marcada
    expect(caixas[2].checked).toBe(false);  // revisar NÃO pré-marcada
    // O aviso "confira: pode ser outra criança" só existe na faixa 🔴 revisar.
    expect(screen.getByText(/confira:/)).toBeInTheDocument();
  });

  it("exige confirmação e envia loser_ids + FUNDIR", async () => {
    responder("GET", URL_PREVIA, previa());
    let enviado: { loser_ids: number[]; confirmacao: string } | null = null;
    responder("POST", URL_CORRIGIR, (_caminho, opcoes) => {
      enviado = JSON.parse((opcoes as RequestInit).body as string);
      return { fundidos: 2, falhas: [], mensagem: "2 fusão(ões) aplicada(s)." };
    });

    const u = userEvent.setup();
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    await screen.findByText("Akemi Carolina Vieira");
    // Marca também a 🟡 provável (Akemi) — a 🟢 alta (Bruno) já vem marcada.
    await u.click((screen.getAllByRole("checkbox") as HTMLInputElement[])[1]);

    // 1º clique → pede confirmação (não envia ainda).
    await u.click(screen.getByRole("button", { name: /Unir 2 selecionada/ }));
    expect(enviado).toBeNull();
    expect(await screen.findByText(/irreversível/)).toBeInTheDocument();

    // 2º clique → confirma e envia.
    await u.click(screen.getByRole("button", { name: /Confirmar fusão/ }));

    expect(await screen.findByText(/unificado/)).toBeInTheDocument();
    expect(enviado!.confirmacao).toBe("FUNDIR");
    expect([...enviado!.loser_ids].sort()).toEqual([10, 20]);
  });

  it("'Selecionar todos' une a faixa 🟡 provável num clique", async () => {
    responder("GET", URL_PREVIA, previa());
    const u = userEvent.setup();
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    await screen.findByText("Akemi Carolina Vieira");
    // A faixa 🟡 provável (Akemi = caixa[1]) vem DESMARCADA por padrão.
    expect((screen.getAllByRole("checkbox") as HTMLInputElement[])[1].checked).toBe(false);

    // A 🟢 alta já vem marcada (botão "Desmarcar todos"); os "Selecionar todos"
    // são das faixas 🟡 provável (1º) e 🔴 revisar (2º). O 1º une a provável.
    const marcar = screen.getAllByRole("button", { name: /Selecionar todos/ });
    await u.click(marcar[0]);   // faixa 🟡 provável
    expect((screen.getAllByRole("checkbox") as HTMLInputElement[])[1].checked).toBe(true);
    // Vira "Desmarcar todos" e limpa de volta (o último = a provável recém-marcada).
    const desmarcar = screen.getAllByRole("button", { name: /Desmarcar todos/ });
    await u.click(desmarcar[desmarcar.length - 1]);
    expect((screen.getAllByRole("checkbox") as HTMLInputElement[])[1].checked).toBe(false);
  });
});
