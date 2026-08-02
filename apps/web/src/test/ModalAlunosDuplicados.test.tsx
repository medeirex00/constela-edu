import { describe, expect, it } from "vitest";

import ModalAlunosDuplicados from "../components/ModalAlunosDuplicados";
import { ApiError, renderComApp, responder, screen, userEvent } from "./utils";

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

  it("sub-divide a faixa 🔴 por motivo, SEM 'Selecionar todos' (par a par)", async () => {
    const imp = {
      leituras: 0, snapshots_matific: 1, snapshots_elefante: 0,
      eventos: 0, notas: 0, plataformas: ["matific"],
    };
    responder("GET", URL_PREVIA, {
      total: 4, alta: 0, provavel: 0, revisar: 4,
      candidatos: [
        { loser_id: 1, manter_id: 2, apagar: "Luiz Dias", manter: "Luís Dias",
          turma: "4º C", confianca: "revisar", motivo: "variante", impacto: imp },
        { loser_id: 3, manter_id: 4, apagar: "Bruno Alves", manter: "Bruno Alves",
          turma: "4º C", confianca: "revisar", motivo: "nome_identico", impacto: imp },
        { loser_id: 5, manter_id: 6, apagar: "Ana B", manter: "Ana Beatriz",
          turma: "4º C", confianca: "revisar", motivo: "abreviacao", impacto: imp },
        // motivo desconhecido → cai no CATCH-ALL "Outros" (não pode sumir da tela).
        { loser_id: 7, manter_id: 8, apagar: "Caio X", manter: "Caio Y",
          turma: "4º C", confianca: "revisar", motivo: "futuro_desconhecido", impacto: imp },
      ],
    });
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    // Cada motivo em seu sub-grupo — incluindo o catch-all "Outros".
    expect(await screen.findByText(/Variação de grafia/)).toBeInTheDocument();
    expect(screen.getByText(/Nome idêntico/)).toBeInTheDocument();
    expect(screen.getByText(/Abreviação sem correspondência/)).toBeInTheDocument();
    expect(screen.getByText(/Outros — conferir um a um/)).toBeInTheDocument();
    // O motivo desconhecido NÃO some: seus 4 pares aparecem, um checkbox cada.
    const caixas = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(caixas).toHaveLength(4);
    expect(caixas.every((c) => !c.checked)).toBe(true);
    // Faixas 🔴 NÃO têm atalho de lote — decisão par a par (regra de segurança).
    expect(screen.queryByRole("button", { name: /Selecionar todos/ })).toBeNull();
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

  const imp = {
    leituras: 0, snapshots_matific: 1, snapshots_elefante: 0,
    eventos: 0, notas: 0, plataformas: ["matific"],
  };
  const alta = (loser_id: number, manter_id: number, nome: string) => ({
    loser_id, manter_id, apagar: nome, manter: `${nome} Completo`,
    turma: "4º C", confianca: "alta", motivo: "nome_identico", impacto: imp,
  });

  it("envia em lotes de TAM_LOTE sem partir um leque e soma os resultados", async () => {
    // 19 pares independentes + 1 LEQUE (dois losers → o MESMO manter) = 21 alta.
    const independentes = Array.from({ length: 19 }, (_, i) =>
      alta(100 + i, 500 + i, `Aluno${i}`));
    const leque = [alta(300, 400, "Gemeo A"), alta(301, 400, "Gemeo B")];
    responder("GET", URL_PREVIA, {
      total: 21, alta: 21, provavel: 0, revisar: 0,
      candidatos: [...independentes, ...leque],
    });
    const posts: number[][] = [];
    responder("POST", URL_CORRIGIR, (_c, opcoes) => {
      const body = JSON.parse((opcoes as RequestInit).body as string);
      posts.push(body.loser_ids);
      return { fundidos: body.loser_ids.length, falhas: [], mensagem: "" };
    });

    const u = userEvent.setup();
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    await u.click(await screen.findByRole("button", { name: /Unir 21 selecionada/ }));
    await u.click(screen.getByRole("button", { name: /Confirmar fusão/ }));

    expect(await screen.findByText(/21 aluno\(s\) unificado/)).toBeInTheDocument();
    // Dois POSTs: o 1º com 19, o 2º com o leque INTEIRO (nunca partido no meio).
    expect(posts).toHaveLength(2);
    expect(posts[0]).toHaveLength(19);
    expect([...posts[1]].sort((a, b) => a - b)).toEqual([300, 301]);
  });

  it("falha no meio → reporta o parcial já salvo (não perde o que entrou)", async () => {
    const candidatos = Array.from({ length: 45 }, (_, i) =>
      alta(1 + i, 1000 + i, `Aluno${i}`));   // 45 independentes → lotes de 20/20/5
    responder("GET", URL_PREVIA, {
      total: 45, alta: 45, provavel: 0, revisar: 0, candidatos,
    });
    let chamada = 0;
    responder("POST", URL_CORRIGIR, (_c, opcoes) => {
      chamada += 1;
      if (chamada === 2) return new ApiError(500, "Servidor caiu");   // 2º lote falha
      const body = JSON.parse((opcoes as RequestInit).body as string);
      return { fundidos: body.loser_ids.length, falhas: [], mensagem: "" };
    });

    const u = userEvent.setup();
    renderComApp(
      <ModalAlunosDuplicados escolaId={1} aoFechar={noop} aoConcluir={noop} />);

    await u.click(await screen.findByRole("button", { name: /Unir 45 selecionada/ }));
    await u.click(screen.getByRole("button", { name: /Confirmar fusão/ }));

    // O 1º lote (20) commitou antes da falha: o parcial é reportado, não perdido.
    expect(await screen.findByText(/20 já foram unidas/)).toBeInTheDocument();
  });
});
