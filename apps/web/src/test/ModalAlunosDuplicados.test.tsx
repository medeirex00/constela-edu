import { describe, expect, it } from "vitest";

import ModalAlunosDuplicados from "../components/ModalAlunosDuplicados";
import { renderComApp, responder, screen, userEvent } from "./utils";

const URL_PREVIA = "/escolas/1/alunos/duplicados";
const URL_AUTO = "/escolas/1/alunos/duplicados/auto";
const URL_CORRIGIR = "/escolas/1/alunos/duplicados/corrigir";

function planoAuto(over: Partial<ReturnType<typeof _plano>> = {}) {
  return { ..._plano(), ...over };
}
function _plano() {
  return { resumo: { total_alunos: 30, grupos_auto: 0, fusoes_auto: 0, revisar: 1 },
           grupos: [] as unknown[] };
}

function previa() {
  return {
    total: 2,
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
        turma: "4º C", confianca: "revisar", motivo: "subconjunto",
        impacto: {
          leituras: 0, snapshots_matific: 0, snapshots_elefante: 1,
          eventos: 0, notas: 0, plataformas: ["elefante"],
        },
      },
    ],
  };
}

const noop = () => {};

describe("ModalAlunosDuplicados", () => {
  it("marca alta por padrão e deixa 'revisar' desmarcada", async () => {
    responder("GET", URL_PREVIA, previa());
    responder("GET", URL_AUTO, planoAuto());
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    expect(await screen.findByText("Akemi Carolina Vieira")).toBeInTheDocument();
    const caixas = screen.getAllByRole("checkbox") as HTMLInputElement[];
    // Ordem: grupo alta (Bruno) antes do grupo revisar (Akemi).
    expect(caixas[0].checked).toBe(true);   // alta pré-marcada
    expect(caixas[1].checked).toBe(false);  // revisar desmarcada
    // Alerta de "revisar" visível (o "confira:" só existe na linha do par).
    expect(screen.getByText(/confira:/)).toBeInTheDocument();
  });

  it("exige confirmação e envia loser_ids + FUNDIR", async () => {
    responder("GET", URL_PREVIA, previa());
    responder("GET", URL_AUTO, planoAuto());
    let enviado: { loser_ids: number[]; confirmacao: string } | null = null;
    responder("POST", URL_CORRIGIR, (_caminho, opcoes) => {
      enviado = JSON.parse((opcoes as RequestInit).body as string);
      return { fundidos: 2, falhas: [], mensagem: "2 fusão(ões) aplicada(s)." };
    });

    const u = userEvent.setup();
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    await screen.findByText("Akemi Carolina Vieira");
    // Marca também a de "revisar".
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

  it("'Selecionar todos' marca o grupo inteiro de uma vez", async () => {
    responder("GET", URL_PREVIA, previa());
    responder("GET", URL_AUTO, planoAuto());
    const u = userEvent.setup();
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    await screen.findByText("Akemi Carolina Vieira");
    // No grupo "revisar", o par vem DESMARCADO por padrão.
    const revisar = (screen.getAllByRole("checkbox") as HTMLInputElement[])[1];
    expect(revisar.checked).toBe(false);

    // O botão "Selecionar todos" do grupo revisar (o último) marca-o de uma vez.
    const marcar = screen.getAllByRole("button", { name: /Selecionar todos/ });
    await u.click(marcar[marcar.length - 1]);   // grupo "revisar"
    expect((screen.getAllByRole("checkbox") as HTMLInputElement[])[1].checked).toBe(true);
    // Vira "Desmarcar todos" (o último) e limpa de volta.
    const desmarcar = screen.getAllByRole("button", { name: /Desmarcar todos/ });
    await u.click(desmarcar[desmarcar.length - 1]);
    expect((screen.getAllByRole("checkbox") as HTMLInputElement[])[1].checked).toBe(false);
  });

  it("'Resolver automaticamente' funde os de alta confiança num clique", async () => {
    responder("GET", URL_PREVIA, previa());
    responder("GET", URL_AUTO, planoAuto({
      resumo: { total_alunos: 30, grupos_auto: 1, fusoes_auto: 2, revisar: 1 },
      grupos: [{ canonico_id: 11, canonico: "ABRAÃO LUÍS DIAS", turma: "4ºC",
                 duplicatas: [{ loser_id: 10, nome: "ABRAAO L" }] }],
    }));
    let enviado: { confirmacao: string } | null = null;
    responder("POST", URL_AUTO, (_c, opcoes) => {
      enviado = JSON.parse((opcoes as RequestInit).body as string);
      return { fundidos: 2, falhas: [], mensagem: "2 resolvida(s)." };
    });

    const u = userEvent.setup();
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    const botao = await screen.findByRole("button", { name: /Resolver 2 automaticamente/ });
    await u.click(botao);

    expect(enviado!.confirmacao).toBe("FUNDIR");
    expect(await screen.findByText(/resolvida\(s\) automaticamente/)).toBeInTheDocument();
  });
});
