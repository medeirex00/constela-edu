import { describe, expect, it } from "vitest";

import { situacaoIntegracao } from "../components/StatusIntegracao";
import type { Execucao, PlataformaStatus } from "../components/StatusIntegracao";

// Coleta parcial com o alerta "Formato do relatório mudou" (tipo parser_incompativel)
// aberto. A tela não sabe, por execução, se o que falhou foi SÓ a mudança de formato:
// - só formato: repetir não completa (o alerta "Coleta parcial" do servidor não manda
//   repetir — 35993e13);
// - MISTA (uma turma falhou de passagem — http 502, tempo esgotado — e outra veio em
//   outro formato): o servidor diz as duas coisas, "Sincronize de novo para completar"
//   e "O que veio em outro formato não volta com outra coleta" (contrato de
//   test_aud_sync_matific_numero_ilegivel.py::
//   test_formato_ao_lado_de_falha_que_repetir_completa_diz_as_duas_coisas);
// - alerta de formato que ficou aberto de uma coleta ANTERIOR (a parcial com falha
//   não o fecha) e a parcial nova só por tempo esgotado: repetir completa.
// O cartão não pode afirmar nem "não completa" nem "completa": manda ler o "Coleta
// parcial" (que diz, por execução, se repetir completa) e repete o que o servidor diz
// do formato. (REV2-SYNC2-1, sobre PEND-9.)

function execucao(over: Partial<Execucao> = {}): Execucao {
  return {
    id: 30, plataforma: "elefante", origem: "manual", status: "parcial",
    iniciada_em: "2026-10-20T09:00:00Z", finalizada_em: "2026-10-20T09:02:00Z",
    duracao_ms: 120000, qtd_alunos: 7, qtd_turmas: 2, qtd_arquivos: 2, qtd_erros: 0,
    tentativa: 1, erro_resumo: null, qtd_linhas: 40, qtd_em_revisao: 0, qtd_falhas: 1,
    recalculo_pendente: false, motivo: "coleta_parcial", ...over,
  };
}

function plataforma(e: Execucao): PlataformaStatus {
  return {
    plataforma: "elefante", estrategia: "navegador", conectada: true,
    credencial_status: "valida", validada_em: null, ultimo_erro: null,
    agendada: true, cadencia: "diaria", hora_local: "03:00", dia_semana: null,
    proxima_execucao: null, ultima_execucao: e, ultima_tentativa: e,
    ultimo_sucesso_em: "2026-10-20T09:02:00Z", desatualizada: false,
    frescor: "atualizado", idade_horas: 3, limite_horas: 48, falha_categoria: null,
    fila_parada: false,
  };
}

const FORMATO = [{ tipo: "coleta_parcial" }, { tipo: "parser_incompativel" }];
const PROXIMO_PASSO =
  "Veja os alertas: o “Coleta parcial” diz se sincronizar de novo completa o que falhou; "
  + "o que veio em outro formato não volta com outra coleta (alerta “Formato do relatório mudou”).";

/** Nem "não completa" nem "completa": quem diz, por execução, é o "Coleta parcial". */
function naoAfirmaSeRepetirCompleta(frase: string) {
  expect(frase).not.toMatch(/não completa/);
  expect(frase).not.toMatch(/sincronize de novo para completar/i);
  expect(frase).toContain(PROXIMO_PASSO);
}

describe("parcial com o alerta de formato aberto não afirma se repetir completa", () => {
  it("só formato, com alunos aplicados", () => {
    const s = situacaoIntegracao(plataforma(execucao()), "Elefante Letrado", FORMATO);
    expect(s.chave).toBe("parcial");
    expect(s.frase).toContain("7 alunos atualizados");
    naoAfirmaSeRepetirCompleta(s.frase);
  });

  it("sem aluno aplicado (contas conferidas)", () => {
    const s = situacaoIntegracao(plataforma(execucao({ qtd_alunos: 0 })), "Elefante Letrado",
      FORMATO);
    expect(s.rotulo).toBe("Verificado em parte");
    naoAfirmaSeRepetirCompleta(s.frase);
  });

  it("MISTA: uma turma falhou de passagem e outra veio em outro formato (2 falhas)", () => {
    // O servidor diz ali "Sincronize de novo para completar." E "O que veio em outro
    // formato não volta…": o cartão não pode dizer "sincronizar de novo não completa".
    const s = situacaoIntegracao(plataforma(execucao({ qtd_falhas: 2 })), "Elefante Letrado",
      FORMATO);
    expect(s.chave).toBe("parcial");
    expect(s.frase).toContain("(2 falhas)");
    naoAfirmaSeRepetirCompleta(s.frase);
  });

  it("alerta de formato de uma coleta anterior e parcial nova só por tempo esgotado", () => {
    // A parcial com falha não fecha o parser_incompativel aberto antes: repetir
    // completa a turma desta coleta.
    const s = situacaoIntegracao(plataforma(execucao({ id: 31, qtd_falhas: 1 })),
      "Elefante Letrado", FORMATO);
    naoAfirmaSeRepetirCompleta(s.frase);
  });

  it("sem o alerta de formato, a frase de sempre", () => {
    const s = situacaoIntegracao(plataforma(execucao()), "Elefante Letrado",
      [{ tipo: "coleta_parcial" }]);
    expect(s.frase).toContain("Veja o alerta e sincronize de novo para completar.");
  });
});
