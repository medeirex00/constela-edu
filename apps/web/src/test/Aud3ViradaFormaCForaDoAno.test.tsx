/**
 * Coleta de fora do ano letivo ativo sem nenhuma conta da escola conferida
 * (REV3-VIRADA-2, sobre S_G_VIRADA-1). O backend passa a fechar essa coleta como
 * 'sem_atualizacao' com o motivo próprio 'fora_do_ano_sem_conferencia', que NÃO conta
 * como em dia (forma C na janela da virada). A tela precisa dizer isso: sem o motivo
 * conhecido, o card caía no fim da função e dizia "Sem dados ainda" para uma escola com
 * dados, e o histórico mostrava o código cru. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import {
  descreverExecucao, situacaoIntegracao, tentativaVerificada,
} from "../components/StatusIntegracao";
import type { Execucao, PlataformaStatus } from "../components/StatusIntegracao";

const MOTIVO = "fora_do_ano_sem_conferencia";

function execucao(over: Partial<Execucao> = {}): Execucao {
  return {
    id: 20, plataforma: "elefante", origem: "manual", status: "sem_atualizacao",
    iniciada_em: "2027-02-10T15:00:00Z", finalizada_em: "2027-02-10T15:02:00Z",
    duracao_ms: 120000, qtd_alunos: 0, qtd_turmas: 1, qtd_arquivos: 1, qtd_erros: 0,
    qtd_linhas: 2, qtd_em_revisao: 0, tentativa: 1, erro_resumo: null, motivo: MOTIVO,
    ...over,
  };
}

function plataforma(ultima: Execucao, over: Partial<PlataformaStatus> = {}): PlataformaStatus {
  return {
    plataforma: "elefante", estrategia: "navegador", conectada: true,
    credencial_status: "valida", validada_em: null, ultimo_erro: null,
    agendada: true, cadencia: "diaria", hora_local: "03:00", dia_semana: null,
    proxima_execucao: null, ultima_execucao: ultima, ultima_tentativa: ultima,
    ultimo_sucesso_em: "2027-02-07T15:02:00Z", desatualizada: false,
    frescor: "atualizado", idade_horas: 24, limite_horas: 48, falha_categoria: null,
    fila_parada: false, ...over,
  };
}

describe("coleta fora do ano letivo sem conta da escola conferida", () => {
  it("o card diz o que aconteceu e que não conta como em dia (não 'Sem dados ainda')", () => {
    const s = situacaoIntegracao(plataforma(execucao()), "Elefante Letrado",
      [{ tipo: "coleta_fora_do_ano_letivo" }]);
    expect(s.chave).toBe("sem_atualizacao");
    expect(s.tom).toBe("alerta");
    expect(s.rotulo).toBe("Sem atualização: coleta fora do ano letivo");
    expect(s.frase).toContain("fora do ano letivo ativo da escola");
    expect(s.frase).toContain("nenhuma conta já ligada a um aluno desta escola veio nela");
    expect(s.frase).toContain("não conta como dado em dia");
    expect(s.frase).toContain("“Coleta fora do ano letivo ativo”");
    expect(s.frase).not.toContain("já estão desatualizados");
    // Nada foi para a fila: o card não manda resolver revisões.
    expect(s.frase).not.toContain("Revisões de identidade");
    expect(s.link).toBeUndefined();
  });

  it("com o prazo da agenda vencido, avisa que os dados já estão desatualizados", () => {
    const s = situacaoIntegracao(plataforma(execucao(), { desatualizada: true }),
      "Elefante Letrado", [{ tipo: "coleta_fora_do_ano_letivo" }, { tipo: "desatualizada" }]);
    expect(s.rotulo).toBe("Sem atualização: coleta fora do ano letivo");
    expect(s.frase).toContain("(os dados desta plataforma já estão desatualizados)");
  });

  it("não é uma verificação ('nada mudou') e o histórico traz o motivo em português", () => {
    expect(tentativaVerificada(plataforma(execucao()))).toBe(false);
    expect(descreverExecucao({ status: "sem_atualizacao", motivo: MOTIVO })).toEqual({
      rotulo: "sem atualização: coleta fora do ano letivo, nenhuma conta da escola reconhecida",
      tom: "alerta",
    });
  });
});
