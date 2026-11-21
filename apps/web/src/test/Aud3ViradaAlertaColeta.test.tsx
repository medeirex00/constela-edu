/**
 * Alerta "coleta_fora_do_ano_letivo" (S_G_VIRADA-1): a coleta feita fora do ano letivo
 * ativo da escola não cria ficha nem muda matrícula, e o backend abre este alerta pedindo
 * a virada do ano. A tela o mostra com rótulo em português (não o código cru) e não o
 * usa para explicar uma falha de execução — ele é aviso de estado, como o de
 * correspondência pendente. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { rotuloAlerta, situacaoIntegracao } from "../components/StatusIntegracao";
import type { Execucao, PlataformaStatus } from "../components/StatusIntegracao";

function execucao(over: Partial<Execucao> = {}): Execucao {
  return {
    id: 10, plataforma: "matific", origem: "manual", status: "concluida",
    iniciada_em: "2027-02-10T15:00:00Z", finalizada_em: "2027-02-10T15:02:00Z",
    duracao_ms: 120000, qtd_alunos: 3, qtd_turmas: 2, qtd_arquivos: 1, qtd_erros: 0,
    tentativa: 1, erro_resumo: null, ...over,
  };
}

function plataforma(ultima: Execucao): PlataformaStatus {
  return {
    plataforma: "matific", estrategia: "navegador", conectada: true,
    credencial_status: "valida", validada_em: null, ultimo_erro: null,
    agendada: false, cadencia: "diaria", hora_local: "03:00", dia_semana: null,
    proxima_execucao: null, ultima_execucao: ultima, ultima_tentativa: ultima,
    ultimo_sucesso_em: "2027-02-10T15:02:00Z", desatualizada: false,
    frescor: "atualizado", idade_horas: 1, limite_horas: 48, falha_categoria: null,
    fila_parada: false,
  };
}

describe("alerta de coleta fora do ano letivo", () => {
  it("tem rótulo em português, não o código cru", () => {
    expect(rotuloAlerta("coleta_fora_do_ano_letivo")).toBe("Coleta fora do ano letivo ativo");
  });

  it("não vira motivo de falha da execução", () => {
    const erro = execucao({ status: "erro" });
    const s = situacaoIntegracao(plataforma(erro), "Matific",
      [{ tipo: "coleta_fora_do_ano_letivo" }]);
    expect(s.rotulo).toBe("Falhou: a última sincronização não terminou");
  });

  it("com a coleta concluída, a integração segue 'Atualizado'", () => {
    const s = situacaoIntegracao(plataforma(execucao()), "Matific",
      [{ tipo: "coleta_fora_do_ano_letivo" }]);
    expect(s.chave).toBe("ok");
  });
});
