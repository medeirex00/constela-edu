import { describe, expect, it } from "vitest";

import {
  descreverExecucao,
  idadeHumana,
  precisaVerificacao,
  recalculoPendente,
  rotuloAlerta,
  situacaoIntegracao,
} from "../components/StatusIntegracao";
import type { EscolaStatus, Execucao, PlataformaStatus } from "../components/StatusIntegracao";

/** Execução fictícia (só o que a regra lê). */
function execucao(over: Partial<Execucao> = {}): Execucao {
  return {
    id: 10, plataforma: "matific", origem: "manual", status: "concluida",
    iniciada_em: "2026-10-20T09:00:00Z", finalizada_em: "2026-10-20T09:02:00Z",
    duracao_ms: 120000, qtd_alunos: 20, qtd_turmas: 2, qtd_arquivos: 2, qtd_erros: 0,
    tentativa: 1, erro_resumo: null, ...over,
  };
}

/** Matific conectado e em dia — cada teste muda só o que importa. */
function plataforma(over: Partial<PlataformaStatus> = {}): PlataformaStatus {
  const ultima = execucao();
  return {
    plataforma: "matific", estrategia: "navegador", conectada: true,
    credencial_status: "valida", validada_em: null, ultimo_erro: null,
    agendada: true, cadencia: "diaria", hora_local: "03:00", dia_semana: null,
    proxima_execucao: null, ultima_execucao: ultima, ultima_tentativa: ultima,
    ultimo_sucesso_em: "2026-10-20T09:02:00Z", desatualizada: false,
    frescor: "atualizado", idade_horas: 3, limite_horas: 48, falha_categoria: null,
    fila_parada: false, ...over,
  };
}

describe("situacaoIntegracao — estados distintos e honestos", () => {
  it("em dia → 'Atualizado' com a idade do último sucesso", () => {
    const s = situacaoIntegracao(plataforma());
    expect(s.chave).toBe("ok");
    expect(s.rotulo).toBe("Atualizado");
    expect(s.frase).toContain("há 3 horas");
  });

  it("última coleta sem dados NÃO é 'Funcionando'/'Atualizado' (era o falso positivo)", () => {
    const vazia = execucao({ status: "sem_dados", qtd_alunos: 0 });
    const s = situacaoIntegracao(plataforma({ ultima_execucao: vazia, ultima_tentativa: vazia }));
    expect(s.chave).toBe("sem_dados_coleta");
    expect(s.rotulo).toBe("Sem dados na última coleta");
    expect(s.tom).toBe("alerta");
    expect(s.rotulo).not.toMatch(/Funcionando|Atualizado/);
  });

  it("resposta antiga (sem ultima_tentativa) com execução sem dados também não vira sucesso", () => {
    const vazia = execucao({ status: "sem_dados" });
    const p = plataforma({ ultima_execucao: vazia, frescor: undefined, idade_horas: undefined });
    delete (p as Partial<PlataformaStatus>).ultima_tentativa;
    expect(situacaoIntegracao(p).chave).toBe("sem_dados_coleta");
  });

  it("dado velho → 'Dados desatualizados' com a idade, mesmo sem agenda", () => {
    const s = situacaoIntegracao(plataforma({
      agendada: false, cadencia: "manual", frescor: "desatualizado", idade_horas: 240,
    }));
    expect(s.chave).toBe("desatualizada");
    expect(s.rotulo).toBe("Dados desatualizados (10 dias)");
  });

  it("agenda ativa com o agendador do servidor desligado: a frase diz que está pausada", () => {
    const s = situacaoIntegracao(
      plataforma({ frescor: "desatualizado", desatualizada: true, idade_horas: 400 }),
      "Matific", [], false);
    expect(s.frase).toContain("pausada no servidor");
    const ligado = situacaoIntegracao(
      plataforma({ frescor: "desatualizado", desatualizada: true, idade_horas: 400 }),
      "Matific", [], true);
    expect(ligado.frase).not.toContain("pausada");
  });

  it("falha NUNCA vira sucesso: última tentativa com erro vence o dado ainda em dia", () => {
    const erro = execucao({ id: 11, status: "erro", erro_resumo: "Timeout ao abrir o placar" });
    const s = situacaoIntegracao(plataforma({
      ultima_execucao: erro, ultima_tentativa: erro, falha_categoria: "indisponibilidade_externa",
    }), "Matific", [{ tipo: "timeout" }]);
    expect(s.chave).toBe("falhou");
    expect(s.rotulo).toBe("Falhou: demorou demais");
    expect(s.categoria).toBe("indisponibilidade_externa");
    expect(s.frase).toContain("não respondeu como esperado");
    expect(s.detalheTecnico).toBe("Timeout ao abrir o placar");
  });

  it("distingue acesso recusado × plataforma × processamento", () => {
    const erro = execucao({ status: "erro" });
    const recusada = situacaoIntegracao(plataforma({
      conectada: false, credencial_status: "invalida", ultima_tentativa: erro,
    }));
    expect(recusada.categoria).toBe("autenticacao");
    expect(recusada.frase).toContain("recusou o acesso");

    const processamento = situacaoIntegracao(plataforma({
      ultima_execucao: erro, ultima_tentativa: erro, falha_categoria: "processamento",
    }), "Matific", [{ tipo: "erro_inesperado" }]);
    expect(processamento.rotulo).toBe("Falhou: erro ao processar");
    expect(processamento.frase).toContain("do nosso lado");

    // Sem falha_categoria (backend antigo): a categoria vem do tipo do alerta.
    const captcha = situacaoIntegracao(plataforma({
      ultima_execucao: erro, ultima_tentativa: erro, falha_categoria: undefined,
    }), "Matific", [{ tipo: "captcha" }]);
    expect(captcha.rotulo).toBe("Falhou: bloqueio anti-robô da plataforma");
    expect(captcha.categoria).toBe("indisponibilidade_externa");
  });

  it("servidor sem como coletar → 'Coleta indisponível neste servidor'", () => {
    const erro = execucao({ status: "erro", erro_resumo: "Playwright não está instalado" });
    const s = situacaoIntegracao(plataforma({
      ultima_execucao: erro, ultima_tentativa: erro, falha_categoria: "indisponivel",
    }));
    expect(s.chave).toBe("indisponivel");
    expect(s.rotulo).toBe("Coleta indisponível neste servidor");
    expect(s.tom).toBe("erro");
  });

  it("fila esperando um agendador desligado não é 'Sincronizando'", () => {
    const fila = execucao({ id: 12, status: "fila", finalizada_em: null });
    const parada = situacaoIntegracao(plataforma({ ultima_execucao: fila, fila_parada: true }));
    expect(parada.chave).not.toBe("andamento");
    const viva = situacaoIntegracao(plataforma({ ultima_execucao: fila, fila_parada: false }));
    expect(viva.chave).toBe("andamento");
  });

  it("validação que não terminou (navegador) é 'Conexão não validada', não 'senha recusada'", () => {
    const s = situacaoIntegracao(plataforma({
      conectada: false, credencial_status: "nao_validada", ultima_tentativa: null,
      ultima_execucao: null, ultimo_erro: "A página não respondeu.",
    }));
    expect(s.chave).toBe("nao_validada");
    expect(s.frase).toContain("validação não foi concluída");
    expect(s.detalheTecnico).toBe("A página não respondeu.");
  });

  it("aviso de revisão do Matific não explica uma falha", () => {
    const erro = execucao({ status: "erro" });
    const s = situacaoIntegracao(plataforma({ ultima_execucao: erro, ultima_tentativa: erro }),
      "Matific", [{ tipo: "queda_matific" }]);
    expect(s.rotulo).toBe("Falhou: a última sincronização não terminou");
  });
});

describe("idadeHumana e banner", () => {
  it("formata a idade", () => {
    expect(idadeHumana(null)).toBeNull();
    expect(idadeHumana(0)).toBe("há menos de 1 hora");
    expect(idadeHumana(1)).toBe("há 1 hora");
    expect(idadeHumana(30)).toBe("há 30 horas");
    expect(idadeHumana(72)).toBe("há 3 dias");
  });

  it("o banner lista a plataforma com dado velho mesmo sem agenda", () => {
    const v = precisaVerificacao({
      escola_id: 1, escola_nome: "ESCOLA TESTE", qtd_alunos: 1, qtd_turmas: 1,
      alertas_abertos: 0, lista_piloto_importada: true, integracao_configurada: true,
      plataformas: [plataforma({ agendada: false, frescor: "desatualizado" })],
    }, 0);
    expect(v.desatualizadas).toEqual(["Matific"]);
  });

  it("banner e card concordam sobre 'Dados desatualizados' depois de uma verificação", () => {
    // Antes: depois de 48 h sem dado novo, o card dizia "Verificado: nada mudou" e o
    // banner, "Dados desatualizados" (o banner não tinha a exceção da verificação).
    const escolaCom = (p: PlataformaStatus): EscolaStatus => ({
      escola_id: 1, escola_nome: "ESCOLA TESTE", qtd_alunos: 1, qtd_turmas: 1,
      alertas_abertos: 0, lista_piloto_importada: true, integracao_configurada: true,
      plataformas: [p],
    });
    const velho: Partial<PlataformaStatus> = {
      frescor: "desatualizado", idade_horas: 72, desatualizada: false };
    const semAtualizacao = (motivo: string | null) =>
      terminada({ status: "sem_atualizacao", qtd_alunos: 0, motivo });
    const casos: Array<[string, PlataformaStatus, boolean]> = [
      ["nada mudou", com(semAtualizacao("nada_mudou"), velho), false],
      ["total retido", com(semAtualizacao("queda_retida"), velho), false],
      ["sem motivo (backend antigo)", com(semAtualizacao(null), velho), false],
      ["linhas descartadas", com(semAtualizacao("linhas_descartadas"), velho), true],
      ["concluída antiga", com(terminada({ status: "concluida" }), velho), true],
      ["nada mudou, mas a agenda venceu",
        com(semAtualizacao("nada_mudou"), { ...velho, desatualizada: true }), true],
    ];
    for (const [nome, p, esperado] of casos) {
      const card = situacaoIntegracao(p).chave === "desatualizada";
      const banner = precisaVerificacao(escolaCom(p), 0).desatualizadas.length > 0;
      expect([nome, card, banner]).toEqual([nome, esperado, esperado]);
    }
  });
});

// --- Etapa 2: contrato comum dos estados finais da execução -------------------

/** Execução terminada com as contagens NOVAS (qtd_linhas presente). */
function terminada(over: Partial<Execucao> = {}): Execucao {
  return execucao({
    id: 20, qtd_alunos: 3, qtd_linhas: 40, qtd_em_revisao: 0, qtd_falhas: 0,
    recalculo_pendente: false, motivo: null, ...over,
  });
}

/** Plataforma cuja última execução (e tentativa) é ``e``. */
function com(e: Execucao, over: Partial<PlataformaStatus> = {}): PlataformaStatus {
  return plataforma({ ultima_execucao: e, ultima_tentativa: e, ...over });
}

describe("situacaoIntegracao — estados do contrato (etapa 2)", () => {
  it("os cinco status finais têm rótulos e tons distintos", () => {
    const concluida = situacaoIntegracao(com(terminada({ status: "concluida" })));
    const parcial = situacaoIntegracao(com(terminada({ status: "parcial", qtd_falhas: 1 })));
    const semAtualizacao = situacaoIntegracao(com(terminada({
      status: "sem_atualizacao", qtd_alunos: 0, motivo: "nada_mudou" })));
    const semDados = situacaoIntegracao(com(terminada({
      status: "sem_dados", qtd_alunos: 0, qtd_linhas: 0 })));
    const erro = situacaoIntegracao(com(terminada({
      status: "erro", qtd_alunos: 0, motivo: "falha_download" })));
    const todos = [concluida, parcial, semAtualizacao, semDados, erro];
    expect(todos.map((s) => s.chave)).toEqual(
      ["ok", "parcial", "sem_atualizacao", "sem_dados_coleta", "falhou"]);
    expect(new Set(todos.map((s) => s.tom)).size).toBe(5);
    expect(new Set(todos.map((s) => s.rotulo)).size).toBe(5);
    expect(parcial.rotulo).not.toMatch(/^Atualizado$/);
    expect(semAtualizacao.rotulo).not.toMatch(/^Atualizado$/);
  });

  it("parcial mostra os alunos atualizados e as falhas, nunca 'Atualizado'", () => {
    const s = situacaoIntegracao(com(terminada({
      status: "parcial", qtd_alunos: 12, qtd_falhas: 2, erro_resumo: "turma 3B: HTTP 500" })));
    expect(s.chave).toBe("parcial");
    expect(s.rotulo).toBe("Atualizado em parte");
    expect(s.tom).toBe("parcial");
    expect(s.frase).toContain("12 alunos atualizados");
    expect(s.frase).toContain("2 falhas");
    expect(s.detalheTecnico).toBe("turma 3B: HTTP 500");
  });

  it("parcial por falha depois de gravar diz que o que chegou foi aplicado", () => {
    const s = situacaoIntegracao(com(terminada({
      status: "parcial", qtd_alunos: 1, motivo: "falha_apos_gravacao" })));
    expect(s.frase).toContain("falhou depois de já ter gravado parte dos dados");
    expect(s.frase).toContain("1 aluno atualizado");
  });

  it("parcial SEM aluno aplicado (D2(6): só o endpoint dos nomes falhou) não diz que aplicou dados", () => {
    // Payload do /sync/status: parcial/coleta_parcial, 0 alunos, 1 falha, sem erro_resumo.
    const conferida = terminada({
      status: "parcial", motivo: "coleta_parcial", qtd_alunos: 0, qtd_linhas: 3, qtd_falhas: 1 });
    const s = situacaoIntegracao(com(conferida), "Matific", [{ tipo: "coleta_parcial" }]);
    expect(s.chave).toBe("parcial");           // o banner continua listando a plataforma
    expect(s.tom).toBe("parcial");
    expect(s.rotulo).toBe("Verificado em parte");
    expect(s.rotulo).not.toMatch(/Atualizado/);
    expect(s.frase).not.toMatch(/aplicou dados|alunos? atualizados?/);
    expect(s.frase).toContain("conferiu as contas já ligadas e nenhum número mudou");
    expect(s.frase).toContain("(1 falha)");
    expect(precisaVerificacao({
      escola_id: 1, escola_nome: "ESCOLA FICTÍCIA", qtd_alunos: 3, qtd_turmas: 1,
      alertas_abertos: 1, lista_piloto_importada: true, integracao_configurada: true,
      plataformas: [com(conferida)],
    }, 0).parciais).toEqual(["Matific"]);
    // Com aluno aplicado, segue "Atualizado em parte" com a contagem.
    const aplicada = situacaoIntegracao(com({ ...conferida, qtd_alunos: 12 }));
    expect(aplicada.rotulo).toBe("Atualizado em parte");
    expect(aplicada.frase).toContain("aplicou dados (12 alunos atualizados)");
  });

  it("sem atualização: 'nada mudou' × 'correspondência pendente' (com link para Revisões)", () => {
    const nada = situacaoIntegracao(com(terminada({
      status: "sem_atualizacao", qtd_alunos: 0, motivo: "nada_mudou" })));
    expect(nada.rotulo).toBe("Verificado: nada mudou");
    expect(nada.link ?? null).toBeNull();

    const pendente = situacaoIntegracao(com(terminada({
      status: "sem_atualizacao", qtd_alunos: 0, qtd_em_revisao: 5,
      motivo: "correspondencia_pendente" })));
    expect(pendente.chave).toBe("correspondencia_pendente");
    expect(pendente.rotulo).toBe("Sem atualização: correspondência pendente");
    // qtd_em_revisao conta CONTAS distintas (uma criança com 5 livros = 1).
    expect(pendente.frase).toContain("5 contas aguardam");
    expect(pendente.link).toEqual({ para: "/revisoes-identidade", texto: "Ver revisões de identidade" });
  });

  it("tudo em revisão sem nenhuma conta da escola conferida tem estado próprio (não é 'em dia')", () => {
    const tudo = terminada({
      status: "sem_atualizacao", qtd_alunos: 0, qtd_em_revisao: 4, motivo: "tudo_em_revisao" });
    const s = situacaoIntegracao(com(tudo));
    expect(s.chave).toBe("tudo_em_revisao");
    expect(s.tom).toBe("alerta");
    expect(s.rotulo).toBe("Sem atualização: nenhuma conta da escola reconhecida");
    expect(s.frase).toContain("4 contas aguardam");
    expect(s.frase).toContain("não conta como dado em dia");
    expect(s.frase).toContain("se o acesso cadastrado é o desta escola");
    expect(s.frase).not.toContain("já estão desatualizados");
    expect(s.link).toEqual({ para: "/revisoes-identidade", texto: "Ver revisões de identidade" });
    // Não se confunde com a correspondência pendente nem com "nada mudou".
    expect(s.rotulo).not.toMatch(/correspondência pendente|nada mudou|Atualizado/);
    // Passado o prazo da agenda, a frase diz que o dado já está desatualizado.
    const velha = situacaoIntegracao(com(tudo, { desatualizada: true, frescor: "desatualizado" }));
    expect(velha.chave).toBe("tudo_em_revisao");
    expect(velha.frase).toContain("já estão desatualizados");
    // Sem a contagem (resposta antiga), não inventa número.
    const semContagem = situacaoIntegracao(com(terminada({
      status: "sem_atualizacao", qtd_alunos: 0, qtd_em_revisao: null, motivo: "tudo_em_revisao" })));
    expect(semContagem.frase).toContain("todas as linhas aguardam");
  });

  it("fila de revisão vazia (só linhas sem vínculo) não diz '0 contas aguardam' (revisão e95)", () => {
    for (const motivo of ["tudo_em_revisao", "correspondencia_pendente"]) {
      const s = situacaoIntegracao(com(terminada({
        status: "sem_atualizacao", qtd_alunos: 0, qtd_em_revisao: 0, motivo })));
      expect(s.chave).toBe(motivo);
      expect(s.frase).not.toMatch(/0 contas? aguarda/);
      expect(s.frase).toContain("nenhuma foi para Revisões de identidade");
    }
  });

  it("linhas descartadas por defeito NÃO são 'nada mudou' (o backend não conta como verificação)", () => {
    const defeito = terminada({ status: "sem_atualizacao", qtd_alunos: 0, motivo: "linhas_descartadas" });
    const s = situacaoIntegracao(com(defeito));
    expect(s.rotulo).toBe("Sem atualização: linhas com defeito");
    expect(s.tom).toBe("alerta");
    expect(s.frase).toContain("com defeito");
    expect(s.rotulo).not.toContain("nada mudou");
    // Não segura o frescor: com o dado velho pela idade, vale "desatualizados".
    const velho = situacaoIntegracao(com(defeito, { frescor: "desatualizado", idade_horas: 300 }));
    expect(velho.chave).toBe("desatualizada");
    // Parcial pelo mesmo motivo não diz que "parte da coleta falhou".
    const parcial = situacaoIntegracao(com(terminada({
      status: "parcial", qtd_alunos: 3, qtd_falhas: 0, motivo: "linhas_descartadas" })));
    expect(parcial.frase).toContain("veio com defeito");
    expect(parcial.frase).not.toContain("parte da coleta falhou");
    expect(descreverExecucao({ status: "sem_atualizacao", motivo: "linhas_descartadas" }).rotulo)
      .toBe("sem atualização: linhas com defeito descartadas");
  });

  it("tempo e questões que não vieram (S9) não são 'nada mudou' nem 'parte da coleta falhou'", () => {
    const semCampos = terminada({ status: "sem_atualizacao", qtd_alunos: 0, motivo: "campos_nao_atualizados" });
    const s = situacaoIntegracao(com(semCampos));
    expect(s.rotulo).toBe("Sem atualização: tempo ou questões não vieram");
    expect(s.tom).toBe("alerta");
    expect(s.frase).toContain("valor da coleta anterior");
    const parcial = situacaoIntegracao(com(terminada({
      status: "parcial", qtd_alunos: 3, qtd_falhas: 0, motivo: "campos_nao_atualizados" })));
    expect(parcial.frase).toContain("tempo de leitura ou questões");
    expect(parcial.frase).not.toContain("parte da coleta falhou");
    expect(descreverExecucao({ status: "sem_atualizacao", motivo: "campos_nao_atualizados" }).rotulo)
      .toBe("sem atualização: tempo ou questões não vieram da plataforma");
  });

  it("S9: a frase não afirma QUAIS campos faltaram nem manda sincronizar de novo", () => {
    // O motivo é o mesmo quando só 'responses' sumiu: a tela não sabe quais campos
    // faltaram (o alerta crítico sabe), e um campo renomeado não volta com outra coleta.
    for (const status of ["parcial", "sem_atualizacao"] as const) {
      const s = situacaoIntegracao(com(terminada({
        status, qtd_alunos: status === "parcial" ? 2 : 0, qtd_falhas: 0,
        motivo: "campos_nao_atualizados" })));
      expect(s.frase).not.toMatch(/o tempo de leitura e as questões/);
      expect(s.frase).not.toMatch(/sincronize de novo/i);
      expect(s.frase).toContain("não os traz de volta");
    }
  });

  it("total menor retido (queda do Matific) é verificação com estado próprio, sem link para revisões", () => {
    const retida = terminada({ status: "sem_atualizacao", qtd_alunos: 0, motivo: "queda_retida" });
    const s = situacaoIntegracao(com(retida));
    expect(s.rotulo).toBe("Verificado: total menor retido");
    expect(s.tom).toBe("alerta");
    expect(s.link ?? null).toBeNull();
    expect(s.frase).toContain("valor gravado foi mantido");
    // Conta como verificação: a idade do dado sozinha não vira "desatualizados".
    const pelaIdade = situacaoIntegracao(com(retida, { frescor: "desatualizado", idade_horas: 300 }));
    expect(pelaIdade.chave).toBe("sem_atualizacao");
    expect(descreverExecucao({ status: "sem_atualizacao", motivo: "queda_retida" }).rotulo)
      .toBe("sem atualização: total menor retido para conferência");
    expect(rotuloAlerta("contas_ausentes")).toBe("Contas vinculadas ausentes na coleta");
  });

  it("'nada mudou' não vira 'desatualizado' pela idade do dado; a regra da agenda ainda vale", () => {
    const nada = terminada({ status: "sem_atualizacao", qtd_alunos: 0, motivo: "nada_mudou" });
    const pelaIdade = situacaoIntegracao(com(nada, { frescor: "desatualizado", idade_horas: 300 }));
    expect(pelaIdade.chave).toBe("sem_atualizacao");
    const pelaAgenda = situacaoIntegracao(com(nada, { desatualizada: true, idade_horas: 300 }));
    expect(pelaAgenda.chave).toBe("desatualizada");
  });

  it("sem dados = a plataforma não trouxe dados (estado próprio, não sucesso)", () => {
    const s = situacaoIntegracao(com(terminada({ status: "sem_dados", qtd_alunos: 0, qtd_linhas: 0 })));
    expect(s.rotulo).toBe("Sem dados na última coleta");
    expect(s.frase).toContain("A plataforma não trouxe dados");
  });

  it("erro traduz o código do contrato (motivo da execução)", () => {
    const casos: [string, string, string, string][] = [
      ["sem_acesso_ao_dado", "Falhou: sem acesso aos dados", "autenticacao", "recusou o acesso ao relatório"],
      ["falha_download", "Falhou: falha ao baixar o relatório", "indisponibilidade_externa", "respondeu com erro"],
      ["timeout", "Falhou: demorou demais", "indisponibilidade_externa", "tempo máximo"],
      ["parser_incompativel", "Falhou: formato do relatório mudou", "processamento", "formato que o Constela não reconhece"],
      // N6: sem admin/coordenador ativo, a coleta nem começa (cadastro, não plataforma).
      ["escola_sem_responsavel", "Falhou: escola sem administrador ou coordenador ativo",
        "configuracao", "Cadastre ou reative um em Usuários"],
    ];
    for (const [codigo, rotulo, categoria, trecho] of casos) {
      const s = situacaoIntegracao(com(terminada({ status: "erro", qtd_alunos: 0, motivo: codigo }),
        { falha_categoria: undefined }));
      expect(s.chave).toBe("falhou");
      expect(s.rotulo).toBe(rotulo);
      expect(s.categoria).toBe(categoria);
      expect(s.frase).toContain(trecho);
    }
  });

  it("erro da escola externa diz o que conferir (não 'confira usuário e senha')", () => {
    const casos: [string, string, string, string][] = [
      ["conta_multiescola", "Falhou: a conta enxerga mais de uma escola", "autenticacao",
        "escolhe qual delas é esta escola"],
      ["escola_externa_trocada", "Falhou: a conta é de outra escola", "autenticacao",
        "Confira se a credencial é desta escola"],
      ["escola_externa_em_outra_escola", "Falhou: escola da plataforma já usada por outra escola",
        "autenticacao", "já alimenta outra escola do Constela"],
      ["escola_nao_identificada", "Falhou: escola da conta não identificada", "processamento",
        "não disse de qual escola são os dados"],
      // D8: credencial de outra escola sem vínculo — nada gravado, nem pendência.
      ["contas_de_outra_escola", "Falhou: todas as contas são de outra escola", "autenticacao",
        "nada foi gravado"],
    ];
    for (const [codigo, rotulo, categoria, trecho] of casos) {
      const s = situacaoIntegracao(com(terminada({ status: "erro", qtd_alunos: 0, motivo: codigo }),
        { falha_categoria: undefined }));
      expect(s.chave).toBe("falhou");
      expect(s.rotulo).toBe(rotulo);
      expect(s.categoria).toBe(categoria);
      expect(s.frase).toContain(trecho);
      expect(s.frase).not.toContain("Confira usuário e senha");
    }
    expect(descreverExecucao({ status: "erro", motivo: "conta_multiescola" }).rotulo)
      .toBe("falhou: a conta enxerga mais de uma escola");
  });

  it("período inválido é falha de CONFIGURAÇÃO do pedido, não 'erro do nosso lado'", () => {
    const erro = terminada({ status: "erro", qtd_alunos: 0, motivo: "periodo_invalido" });
    for (const falha_categoria of ["configuracao", undefined] as const) {
      const s = situacaoIntegracao(com(erro, { falha_categoria }), "Matific",
        [{ tipo: "periodo_invalido" }]);
      expect(s.chave).toBe("falhou");
      expect(s.rotulo).toBe("Falhou: período inválido");
      expect(s.categoria).toBe("configuracao");
      expect(s.frase).toContain("Ajuste as datas");
      expect(s.frase).not.toContain("do nosso lado");
    }
    // Só o alerta (sem o código na execução): a frase da categoria.
    const soAlerta = situacaoIntegracao(com(terminada({ status: "erro", qtd_alunos: 0 }),
      { falha_categoria: undefined }), "Matific", [{ tipo: "periodo_invalido" }]);
    expect(soAlerta.categoria).toBe("configuracao");
    expect(soAlerta.frase).toContain("configuração que não é aceita");
    expect(rotuloAlerta("periodo_invalido")).toBe("Período inválido");
    expect(descreverExecucao({ status: "erro", motivo: "periodo_invalido" }).rotulo)
      .toBe("falhou: período inválido");
  });

  it("execução que falhou por senha salva ilegível não diz 'a plataforma recusou'", () => {
    // Backend (resíduo e97): motivo 'credencial_ilegivel', a credencial NÃO vira 'invalida'.
    const erro = terminada({ status: "erro", qtd_alunos: 0, motivo: "credencial_ilegivel" });
    // Já recadastrada (o card não está mais em 'ilegivel'): a falha da última execução.
    const s = situacaoIntegracao(com(erro, { credencial_status: "nao_validada", falha_categoria: undefined }),
      "Elefante", [{ tipo: "credencial_ilegivel" }]);
    expect(s.chave).toBe("falhou");
    expect(s.rotulo).toBe("Falhou: senha salva ilegível");
    expect(s.categoria).toBe("configuracao");
    expect(s.frase).toContain("não pôde ser lida pelo servidor");
    expect(s.frase).not.toContain("recusou");
    expect(rotuloAlerta("credencial_ilegivel")).toBe("Senha salva ilegível");
    expect(descreverExecucao({ status: "erro", motivo: "credencial_ilegivel" }).rotulo)
      .toBe("falhou: senha salva ilegível");
    // Ainda ilegível: o "Recadastre o acesso" vence a falha da execução.
    const ilegivel = situacaoIntegracao(com(erro, { credencial_status: "ilegivel" }), "Elefante",
      [{ tipo: "credencial_ilegivel" }]);
    expect(ilegivel.chave).toBe("credencial_ilegivel");
  });

  it("ultimo_status/ultimo_motivo do /status valem sobre a execução", () => {
    const antiga = execucao({ status: "erro", erro_resumo: "HTTP 403" });
    const s = situacaoIntegracao(com(antiga, { ultimo_status: "erro", ultimo_motivo: "sem_acesso_ao_dado" }));
    expect(s.rotulo).toBe("Falhou: sem acesso aos dados");
    expect(s.detalheTecnico).toBe("HTTP 403");
    // ultimo_status não-terminal (fila) é ignorado.
    const fila = situacaoIntegracao(com(execucao(), { ultimo_status: "fila" }));
    expect(fila.chave).toBe("ok");
  });

  it("alertas de estado da etapa 2 não viram motivo de falha", () => {
    const erro = execucao({ status: "erro" });
    const s = situacaoIntegracao(com(erro), "Matific",
      [{ tipo: "coleta_parcial" }, { tipo: "recalculo_pendente" }, { tipo: "plataforma_sem_dados" }]);
    expect(s.rotulo).toBe("Falhou: a última sincronização não terminou");
  });
});

describe("nova tentativa na fila — não é 'Sincronizando' e não esconde a falha", () => {
  const falha = execucao({ id: 30, status: "erro", motivo: "timeout", erro_resumo: "estourou o teto" });
  const retry = execucao({ id: 31, status: "fila", tentativa: 2, iniciada_em: null, finalizada_em: null });

  it("agendador ligado: nova tentativa pendente, com a falha anterior", () => {
    const s = situacaoIntegracao(
      plataforma({ ultima_execucao: retry, ultima_tentativa: falha, falha_categoria: undefined }),
      "Matific", [], true);
    expect(s.chave).toBe("nova_tentativa");
    expect(s.rotulo).toBe("Nova tentativa pendente");
    expect(s.rotulo).not.toMatch(/Sincronizando/);
    expect(s.frase).toContain("A última sincronização falhou (demorou demais)");
    expect(s.frase).toContain("começa sozinha");
    expect(s.detalheTecnico).toBe("estourou o teto");
  });

  it("agendador desligado: diz que a nova tentativa não roda sozinha", () => {
    const s = situacaoIntegracao(
      plataforma({ ultima_execucao: retry, ultima_tentativa: falha }), "Matific", [], false);
    expect(s.chave).toBe("nova_tentativa");
    expect(s.frase).toContain("agendador, que está desligado");
    expect(s.frase).not.toContain("começa sozinha");
  });

  it("um pedido novo na fila (tentativa 1) continua 'Sincronizando'", () => {
    const pedido = execucao({ id: 32, status: "fila", tentativa: 1 });
    expect(situacaoIntegracao(plataforma({ ultima_execucao: pedido, ultima_tentativa: falha })).chave)
      .toBe("andamento");
  });
});

describe("textos e rótulos auxiliares", () => {
  it("'chegar sozinhos' só com o agendador ligado", () => {
    const semCred = plataforma({ credencial_status: "nao_configurada", conectada: false });
    expect(situacaoIntegracao(semCred, "Matific", [], true).frase).toContain("chegar sozinhos");
    expect(situacaoIntegracao(semCred, "Matific", [], false).frase).not.toContain("sozinhos");
    expect(situacaoIntegracao(semCred, "Matific").frase).not.toContain("sozinhos");
  });

  it("descreverExecucao: rótulo por status e motivo", () => {
    expect(descreverExecucao({ status: "concluida" }).rotulo).toBe("concluída");
    expect(descreverExecucao({ status: "parcial" }).rotulo).toBe("parcial");
    expect(descreverExecucao({ status: "sem_atualizacao", motivo: "nada_mudou" }).rotulo)
      .toBe("sem atualização: nada mudou");
    expect(descreverExecucao({ status: "sem_atualizacao", motivo: "correspondencia_pendente" }).rotulo)
      .toBe("sem atualização: correspondência pendente");
    expect(descreverExecucao({ status: "sem_atualizacao", motivo: "tudo_em_revisao" }))
      .toEqual({ rotulo: "sem atualização: nenhuma conta da escola reconhecida", tom: "alerta" });
    expect(descreverExecucao({ status: "sem_atualizacao", motivo: "nada_mudou" }).tom).toBe("info");
    expect(descreverExecucao({ status: "sem_dados" }).rotulo).toBe("a plataforma não trouxe dados");
    expect(descreverExecucao({ status: "erro", motivo: "sem_acesso_ao_dado" }).rotulo)
      .toBe("falhou: sem acesso aos dados");
    expect(descreverExecucao({ status: "erro" }).rotulo).toBe("falhou");
    expect(descreverExecucao({ status: "fila", tentativa: 2 }).rotulo).toBe("nova tentativa pendente");
    expect(descreverExecucao({ status: "fila", tentativa: 1 }).rotulo).toBe("na fila");
  });

  it("recálculo pendente: o /status vale; sem o campo, cai na execução", () => {
    const pendente = terminada({ status: "parcial", recalculo_pendente: true });
    expect(recalculoPendente(com(pendente))).toBe(true);
    expect(recalculoPendente(com(pendente, { recalculo_pendente: false }))).toBe(false);
    expect(recalculoPendente(com(terminada({ status: "concluida" }), { recalculo_pendente: true }))).toBe(true);
    expect(recalculoPendente(plataforma())).toBe(false);
  });

  it("o banner lista recálculo pendente, coleta parcial e correspondência pendente", () => {
    const escola: EscolaStatus = {
      escola_id: 1, escola_nome: "ESCOLA TESTE", qtd_alunos: 1, qtd_turmas: 1,
      alertas_abertos: 0, lista_piloto_importada: true, integracao_configurada: true,
      plataformas: [
        com(terminada({ status: "parcial", qtd_falhas: 1 }), { recalculo_pendente: true }),
        com(terminada({ plataforma: "elefante", status: "sem_atualizacao", motivo: "correspondencia_pendente" }),
          { plataforma: "elefante" }),
      ],
    };
    const v = precisaVerificacao(escola, 0);
    expect(v.recalculoPendente).toEqual(["Matific"]);
    expect(v.parciais).toEqual(["Matific"]);
    expect(v.correspondenciaPendente).toEqual(["Elefante Letrado"]);
    expect(v.tudoEmRevisao).toEqual([]);
  });

  it("o banner separa 'tudo em revisão' da correspondência pendente", () => {
    const escola: EscolaStatus = {
      escola_id: 1, escola_nome: "ESCOLA TESTE", qtd_alunos: 1, qtd_turmas: 1,
      alertas_abertos: 0, lista_piloto_importada: true, integracao_configurada: true,
      plataformas: [
        com(terminada({ status: "sem_atualizacao", qtd_alunos: 0, motivo: "tudo_em_revisao" })),
        com(terminada({ plataforma: "elefante", status: "sem_atualizacao", motivo: "correspondencia_pendente" }),
          { plataforma: "elefante" }),
      ],
    };
    const v = precisaVerificacao(escola, 0);
    expect(v.tudoEmRevisao).toEqual(["Matific"]);
    expect(v.correspondenciaPendente).toEqual(["Elefante Letrado"]);
  });
});

describe("credencial ilegível (chave trocada sem recifrar) — S16", () => {
  it("'ilegivel' pede o recadastro e nunca vira 'Atualizado', mesmo com a última coleta concluída", () => {
    const s = situacaoIntegracao(
      plataforma({ conectada: false, credencial_status: "ilegivel" }), "Elefante Letrado");
    expect(s.chave).toBe("credencial_ilegivel");
    expect(s.tom).toBe("erro");
    expect(s.rotulo).toBe("Recadastre o acesso");
    expect(s.rotulo).not.toMatch(/Atualizado|Funcionando|conectad/i);
    expect(s.frase).toContain("Elefante Letrado");
    expect(s.frase).toContain("Salvar e validar");
  });

  it("vence o 'Sincronizando' de uma execução que vai falhar sem a senha", () => {
    const viva = execucao({ status: "executando", finalizada_em: null });
    const s = situacaoIntegracao(plataforma({
      conectada: false, credencial_status: "ilegivel", ultima_execucao: viva,
    }));
    expect(s.chave).toBe("credencial_ilegivel");
  });

  it("o banner lista as plataformas a recadastrar", () => {
    const escola: EscolaStatus = {
      escola_id: 1, escola_nome: "ESCOLA TESTE", qtd_alunos: 1, qtd_turmas: 1,
      alertas_abertos: 0, lista_piloto_importada: true, integracao_configurada: true,
      plataformas: [
        plataforma({ plataforma: "elefante", conectada: false, credencial_status: "ilegivel" }),
        plataforma(),
      ],
    };
    expect(precisaVerificacao(escola, 0).recadastrar).toEqual(["Elefante Letrado"]);
    escola.plataformas = [plataforma()];
    expect(precisaVerificacao(escola, 0).recadastrar).toEqual([]);
  });
});
