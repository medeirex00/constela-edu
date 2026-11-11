import { describe, expect, it } from "vitest";

import { situacaoIntegracao } from "../components/StatusIntegracao";
import type { Execucao, PlataformaStatus } from "../components/StatusIntegracao";

// Coleta parcial em que uma parte falhou por MUDANÇA DE FORMATO (alerta
// "Formato do relatório mudou", tipo parser_incompativel, aberto): sincronizar de
// novo não completa — a próxima coleta lê o mesmo formato. Desde 35993e13 a turma do
// Elefante cujos livros vêm sem data em todas as linhas sai 'parcial/coleta_parcial'
// com essa falha, e o alerta do servidor já não manda repetir; a frase da tela ainda
// mandava "sincronize de novo para completar".

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

describe("parcial com o formato do relatório mudado não manda sincronizar de novo", () => {
  it("com alunos aplicados", () => {
    const s = situacaoIntegracao(plataforma(execucao()), "Elefante Letrado", FORMATO);
    expect(s.chave).toBe("parcial");
    expect(s.frase).toContain("7 alunos atualizados");
    expect(s.frase).not.toMatch(/sincronize de novo para completar/);
    expect(s.frase).toContain(
      "Veja o alerta “Formato do relatório mudou”: sincronizar de novo não completa.");
  });

  it("sem aluno aplicado (contas conferidas)", () => {
    const s = situacaoIntegracao(plataforma(execucao({ qtd_alunos: 0 })), "Elefante Letrado",
      FORMATO);
    expect(s.rotulo).toBe("Verificado em parte");
    expect(s.frase).not.toMatch(/sincronize de novo para completar/);
    expect(s.frase).toContain(
      "Veja o alerta “Formato do relatório mudou”: sincronizar de novo não completa.");
  });

  it("sem o alerta de formato, a frase de sempre", () => {
    const s = situacaoIntegracao(plataforma(execucao()), "Elefante Letrado",
      [{ tipo: "coleta_parcial" }]);
    expect(s.frase).toContain("Veja o alerta e sincronize de novo para completar.");
  });
});
