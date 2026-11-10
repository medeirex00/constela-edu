import { describe, expect, it } from "vitest";

import Sincronizacao from "../pages/Sincronizacao";
import {
  api, fireEvent, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor, within,
} from "./utils";

/** A política de criação de aluno da escola (GET existente). Padrão: "permitir". */
const URL_POLITICA = "/escolas/1/configuracoes/sincronizacao";
function mockPolitica(criar_aluno: "permitir" | "bloquear" = "permitir") {
  responder("GET", URL_POLITICA, { criar_aluno });
}

const STATUS = {
  escola_id: 1, escola_nome: "ESCOLA TESTE", qtd_alunos: 12, qtd_turmas: 3,
  alertas_abertos: 0, lista_piloto_importada: true, integracao_configurada: true,
  plataformas: [
    {
      plataforma: "matific", estrategia: "navegador", conectada: true,
      credencial_status: "valida", validada_em: null, ultimo_erro: null,
      agendada: false, cadencia: "manual", proxima_execucao: null, ultima_execucao: null,
    },
    {
      plataforma: "elefante", estrategia: "navegador", conectada: false,
      credencial_status: "nao_configurada", validada_em: null, ultimo_erro: null,
      agendada: false, cadencia: "manual", proxima_execucao: null, ultima_execucao: null,
    },
  ],
};

function mocks() {
  mockPolitica();
  responder("GET", "/escolas/1/sync/status", STATUS);
  responder("GET", "/escolas/1/sync/historico?limite=30", []);
  responder("GET", "/escolas/1/sync/alertas?resolvido=false", []);
  responder("GET", "/sync/dashboard", {
    escolas_total: 1, escolas_configuradas: 1, escolas_sincronizadas: 0,
    escolas_com_erro: 0, em_andamento: 0, fila: 0, workers_ativos: 0,
    scheduler_ligado: false, ultima_sincronizacao: null, duracao_ultima_ms: null,
    tempo_medio_ms: null, alertas_abertos: 0,
  });
}

describe("Sincronização", () => {
  it("mostra os cards das plataformas e o botão de sincronizar", async () => {
    mocks();
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByRole("heading", { name: "Matific" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Elefante Letrado" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Sincronizar agora/i }),
    ).toBeInTheDocument();
    // Etapa 4: escola marcada como "Integração configurada".
    expect(screen.getByText(/Integração configurada/i)).toBeInTheDocument();
  });

  it("desabilita 'Sincronizar Matific' sem credencial válida", async () => {
    mocks();
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    // Elefante está 'nao_configurada' -> botão desabilitado
    const btn = await screen.findByRole("button", { name: /Sincronizar Elefante Letrado/i });
    expect(btn).toBeDisabled();
  });

  it("a falha de 'Sincronizar Matific' aparece no card do Matific (perto do botão)", async () => {
    mocks();
    responderErro("POST", /\/escolas\/1\/sync\/agora/, 409, "Já existe uma coleta na fila.");
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Sincronizar Matific/i }));
    const cardMatific = screen.getByRole("heading", { name: "Matific" }).closest(".card") as HTMLElement;
    expect(await within(cardMatific).findByText("Já existe uma coleta na fila.")).toBeInTheDocument();
    // Uma vez só na tela: o topo não repete o erro do card.
    expect(screen.getAllByText("Já existe uma coleta na fila.")).toHaveLength(1);
  });
});

// --- Tela "Integrações": situação por plataforma, cobertura e banner ---------

/** Execução concluída (contadores ANTIGOS: registros processados / linhas não vinculadas). */
const EXEC_OK = {
  id: 7, plataforma: "elefante", origem: "scheduler", status: "concluida",
  iniciada_em: "2026-09-10T03:00:00Z", finalizada_em: "2026-09-10T03:02:00Z",
  duracao_ms: 120000, qtd_alunos: 25, qtd_turmas: 2, qtd_arquivos: 1, qtd_erros: 2,
  tentativa: 1, erro_resumo: null, conector_versao: null, parser_versao: null,
  created_at: "2026-09-10T03:00:00Z",
};

/** Elefante conectado, agendado e com a última execução concluída. */
function elefanteConectado(over: Record<string, unknown> = {}) {
  return {
    plataforma: "elefante", estrategia: "navegador", conectada: true,
    credencial_status: "valida", validada_em: "2026-09-01T12:00:00Z", ultimo_erro: null,
    agendada: true, cadencia: "diaria", hora_local: "03:00", dia_semana: null,
    proxima_execucao: "2026-09-15T03:00:00Z", ultima_execucao: EXEC_OK,
    ultimo_sucesso_em: "2026-09-10T03:02:00Z", desatualizada: false,
    ...over,
  };
}

function mocksIntegracoes(statusOver: Record<string, unknown>, alertas: unknown[] = []) {
  mockPolitica();
  responder("GET", "/escolas/1/sync/status", { ...STATUS, ...statusOver });
  responder("GET", "/escolas/1/sync/historico?limite=30", []);
  responder("GET", "/escolas/1/sync/alertas?resolvido=false", alertas);
}

describe("Integrações — o que a escola vê", () => {
  it("mostra a cobertura por aluno quando o backend informa (X de Y, zero livros, dado mais recente)", async () => {
    mocksIntegracoes({
      plataformas: [
        STATUS.plataformas[0],
        elefanteConectado({
          alunos_com_dados: 40, alunos_sem_dados: 10, alunos_com_zero_registros: 3,
          dado_mais_recente_em: "2026-09-09T00:00:00Z",
        }),
      ],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("40 de 50 alunos com dados")).toBeInTheDocument();
    expect(screen.getByText(/3 com zero livros \(zero real, não falta de dado\)/)).toBeInTheDocument();
    expect(screen.getByText(/dado mais recente:/)).toBeInTheDocument();
    // Com cobertura por aluno, os contadores brutos da execução NÃO aparecem.
    expect(screen.queryByText(/registros processados/i)).not.toBeInTheDocument();
    // Situação: conectada, última execução concluída e em dia. ("Atualizado" —
    // antes "Funcionando", que também aparecia para "sem dados".)
    expect(screen.getByText("Atualizado")).toBeInTheDocument();
    // Sem problema algum → sem banner.
    expect(screen.queryByText(/Atenção: há dados que precisam de verificação/)).not.toBeInTheDocument();
  });

  it("sem os campos novos, não inventa números: mostra só os contadores da última execução", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("registros processados na última sincronização: 25")).toBeInTheDocument();
    expect(screen.getByText("linhas não vinculadas: 2")).toBeInTheDocument();
    expect(screen.queryByText(/alunos com dados/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/zero livros/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/dado mais recente/i)).not.toBeInTheDocument();
    // Nunca rotula o contador bruto como "alunos sincronizados".
    expect(screen.queryByText(/alunos sincronizados/i)).not.toBeInTheDocument();
  });

  it("cobertura null (backend não conseguiu contar) cai nos contadores da última execução", async () => {
    mocksIntegracoes({
      plataformas: [
        STATUS.plataformas[0],
        elefanteConectado({ alunos_com_dados: null, alunos_sem_dados: null }),
      ],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("registros processados na última sincronização: 25")).toBeInTheDocument();
    expect(screen.getByText("linhas não vinculadas: 2")).toBeInTheDocument();
    expect(screen.queryByText(/alunos com dados/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Nenhum aluno ativo matriculado/)).not.toBeInTheDocument();
  });

  it("cobertura null e sem execução → 'Nenhum dado recebido ainda' (nunca um número)", async () => {
    mocksIntegracoes({
      plataformas: [
        STATUS.plataformas[0],
        elefanteConectado({ alunos_com_dados: null, alunos_sem_dados: null, ultima_execucao: null }),
      ],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    const card = (await screen.findByRole("heading", { name: "Elefante Letrado" })).closest(".card") as HTMLElement;
    expect(within(card).getByText("Nenhum dado recebido ainda.")).toBeInTheDocument();
    expect(within(card).queryByText(/alunos com dados/i)).toBeNull();
    expect(within(card).queryByText(/registros processados/i)).toBeNull();
  });

  it("0 com dados e 0 sem dados → 'Nenhum aluno ativo matriculado no ano letivo', nunca '0 de 0'", async () => {
    mocksIntegracoes({
      plataformas: [
        STATUS.plataformas[0],
        elefanteConectado({ alunos_com_dados: 0, alunos_sem_dados: 0, alunos_com_zero_registros: 0 }),
      ],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Nenhum aluno ativo matriculado no ano letivo")).toBeInTheDocument();
    expect(screen.queryByText(/0 de 0/)).not.toBeInTheDocument();
    expect(screen.queryByText(/alunos com dados/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/zero livros/i)).not.toBeInTheDocument();
  });

  it("com alertas abertos mostra o banner e o alerta dentro do card da plataforma", async () => {
    mocksIntegracoes(
      { alertas_abertos: 1, plataformas: [STATUS.plataformas[0], elefanteConectado()] },
      [{
        id: 5, plataforma: "elefante", tipo: "falha_download", severidade: "warn",
        mensagem: "Não foi possível baixar o relatório.", resolvido: false,
        created_at: "2026-09-11T03:00:00Z",
      }],
    );
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Atenção: há dados que precisam de verificação.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver alertas" })).toBeInTheDocument();
    // /alunos não filtra pendências: sem pendências não há link para lá, e o
    // antigo "Pendências de alunos" (que prometia uma lista) não existe mais.
    expect(screen.queryByRole("link", { name: /Pendências de alunos/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "Abrir Alunos" })).toBeNull();
    expect(screen.getByRole("link", { name: "Ver importações (avançado)" })).toHaveAttribute("href", "/importacoes");
    // O alerta aparece com rótulo humano, a mensagem e o botão Resolver.
    expect(screen.getByText("Falha ao baixar o relatório")).toBeInTheDocument();
    expect(screen.getByText(/Não foi possível baixar o relatório\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolver" })).toBeInTheDocument();
  });

  it("plataforma desatualizada → badge 'Dados desatualizados', banner e envio manual em destaque", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado({ desatualizada: true })] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Dados desatualizados")).toBeInTheDocument();
    expect(screen.queryByText("Atualizado")).not.toBeInTheDocument();
    expect(screen.getByText("Atenção: há dados que precisam de verificação.")).toBeInTheDocument();
    expect(screen.getByText(/Dados desatualizados: Elefante Letrado\./)).toBeInTheDocument();
    // O caminho alternativo (relatório manual) existe em cada card.
    expect(screen.getAllByRole("link", { name: /Enviar relatório manualmente/ }).length).toBe(2);
  });

  it("pendências de correspondência: texto honesto e link para Revisões de identidade", async () => {
    mocksIntegracoes({
      pendencias_correspondencia_30d: 4,
      plataformas: [STATUS.plataformas[0], elefanteConectado()],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Atenção: há dados que precisam de verificação.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Nos últimos 30 dias, 4 linha(s) de relatório ficaram sem aluno correspondente. As que ainda aguardam decisão estão em Revisões de identidade, onde você escolhe o aluno certo.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver revisões de identidade" }))
      .toHaveAttribute("href", "/revisoes-identidade");
    expect(screen.queryByRole("link", { name: "Abrir Alunos" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Pendências de alunos/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Ver importações (avançado)" })).toHaveAttribute("href", "/importacoes");
    // Sem alertas abertos, não oferece "Ver alertas".
    expect(screen.queryByRole("link", { name: "Ver alertas" })).toBeNull();
  });

  it("'Falhou' mostra motivo humano; o erro cru fica só no detalhe técnico (card e logs); 'Ainda não configurada' sem credencial", async () => {
    mocksIntegracoes({
      plataformas: [
        STATUS.plataformas[1], // elefante nao_configurada
        {
          ...STATUS.plataformas[0],
          ultima_execucao: { ...EXEC_OK, plataforma: "matific", status: "erro", erro_resumo: "Senha recusada" },
          ultimo_sucesso_em: null, desatualizada: false,
        },
      ],
    });
    responder("GET", "/escolas/1/sync/logs", []);
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    // Sem alerta aberto que explique a falha → motivo genérico, nunca o texto cru.
    expect(await screen.findByText("Falhou: a última sincronização não terminou")).toBeInTheDocument();
    expect(screen.queryByText("Falhou: Senha recusada")).toBeNull();
    expect(screen.getByText("Ainda não configurada")).toBeInTheDocument();

    // O texto cru continua acessível, recolhido dentro do card.
    const detalhe = screen.getByText("Detalhe técnico: Senha recusada");
    const recolhivel = detalhe.closest("details")!;
    expect(recolhivel).not.toBeNull();
    expect(recolhivel).not.toHaveAttribute("open");
    const u = userEvent.setup();
    await u.click(screen.getByText("Ver detalhe técnico"));
    expect(recolhivel).toHaveAttribute("open");

    // E no painel de logs da execução.
    await u.click(screen.getByRole("button", { name: "Ver o registro da falha" }));
    const painel = await screen.findByRole("dialog", { name: "Logs da execução #7" });
    expect(within(painel).getByText("Detalhe técnico: Senha recusada")).toBeInTheDocument();
  });

  it("credencial recusada/expirada vira motivo humano; o erro cru da credencial vai para o detalhe técnico", async () => {
    mocksIntegracoes({
      plataformas: [
        {
          ...STATUS.plataformas[0],
          conectada: false, credencial_status: "invalida",
          ultimo_erro: "HTTP 401 Unauthorized: invalid_grant",
        },
        elefanteConectado({ conectada: false, credencial_status: "expirada", ultimo_erro: "password expired (code 17)" }),
      ],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Falhou: senha recusada pela plataforma")).toBeInTheDocument();
    expect(screen.getByText("Falhou: senha expirada")).toBeInTheDocument();
    expect(screen.queryByText(/^Falhou: HTTP 401/)).toBeNull();
    expect(screen.queryByText(/^Falhou: password expired/)).toBeNull();
    expect(screen.getByText("Detalhe técnico: HTTP 401 Unauthorized: invalid_grant")).toBeInTheDocument();
    expect(screen.getByText("Detalhe técnico: password expired (code 17)")).toBeInTheDocument();
  });

  it("execução com erro + alerta aberto da plataforma → badge com o rótulo do tipo de alerta", async () => {
    mocksIntegracoes(
      {
        alertas_abertos: 2,
        plataformas: [
          {
            ...STATUS.plataformas[0],
            ultima_execucao: {
              ...EXEC_OK, plataforma: "matific", status: "erro",
              erro_resumo: "TimeoutError: page.goto exceeded 30000ms",
            },
            ultimo_sucesso_em: null, desatualizada: false,
          },
          elefanteConectado(),
        ],
      },
      [
        // Aviso de estado não explica a falha: o motivo vem do alerta de falha.
        {
          id: 8, plataforma: "matific", tipo: "desatualizada", severidade: "warn",
          mensagem: "Sem sincronização recente.", resolvido: false, created_at: "2026-09-11T03:00:00Z",
        },
        {
          id: 9, plataforma: "matific", tipo: "falha_download", severidade: "critico",
          mensagem: "Não foi possível baixar o relatório.", resolvido: false, created_at: "2026-09-11T03:00:00Z",
        },
      ],
    );
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Falhou: falha ao baixar o relatório")).toBeInTheDocument();
    expect(screen.queryByText(/^Falhou: TimeoutError/)).toBeNull();
    expect(screen.getByText("Detalhe técnico: TimeoutError: page.goto exceeded 30000ms")).toBeInTheDocument();
    // O Elefante (sem erro) segue "Atualizado" e sem detalhe técnico.
    const cardElefante = screen.getByRole("heading", { name: "Elefante Letrado" }).closest(".card") as HTMLElement;
    expect(within(cardElefante).getByText("Atualizado")).toBeInTheDocument();
    expect(within(cardElefante).queryByText(/Detalhe técnico/)).toBeNull();
  });

  it("'Ver diagnóstico' só no card do Elefante e para gestor; 'Detalhes técnicos' existe para todos", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    renderComApp(<Sincronizacao />, {
      rota: "/sincronizacao", usuario: usuarioFake({ cargo: "coordenador" }),
    });

    const cardElefante = (await screen.findByRole("heading", { name: "Elefante Letrado" })).closest(".card")!;
    expect(within(cardElefante as HTMLElement).getByRole("link", { name: /Ver diagnóstico/ }))
      .toHaveAttribute("href", "/diagnostico-elefante");
    const cardMatific = screen.getByRole("heading", { name: "Matific" }).closest(".card")!;
    expect(within(cardMatific as HTMLElement).queryByRole("link", { name: /Ver diagnóstico/ })).toBeNull();
    // Histórico/logs ficam recolhidos em "Detalhes técnicos" para quem não é global.
    const detalhes = screen.getByRole("button", { name: /Detalhes técnicos/ });
    expect(detalhes).toHaveAttribute("aria-expanded", "false");
  });

  it("card separa ÚLTIMO DADO APLICADO de ÚLTIMA TENTATIVA e diz quando a agenda está pausada no servidor", async () => {
    const falha = {
      ...EXEC_OK, id: 9, status: "erro", erro_resumo: "Timeout",
      iniciada_em: "2026-10-19T12:00:00Z", finalizada_em: "2026-10-19T12:01:00Z",
    };
    mocksIntegracoes({
      agendador_ativo: false,
      plataformas: [
        STATUS.plataformas[0],
        elefanteConectado({
          ultima_execucao: falha, ultima_tentativa: falha,
          frescor: "desatualizado", desatualizada: true, idade_horas: 960,
          falha_categoria: "indisponibilidade_externa",
        }),
      ],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    const card = (await screen.findByRole("heading", { name: "Elefante Letrado" })).closest(".card") as HTMLElement;
    // Etapa 2: "Último sucesso" virou "Último dado aplicado" (verificação sem
    // dado novo é outra coisa, mostrada à parte quando o backend informa).
    expect(within(card).getByText("Último dado aplicado")).toBeInTheDocument();
    expect(within(card).getByText("há 40 dias")).toBeInTheDocument();
    expect(within(card).getByText(/última tentativa: .*\(falhou\)/)).toBeInTheDocument();
    // Falha vence "desatualizado" no selo — e nunca vira sucesso.
    expect(within(card).getByText(/^Falhou:/)).toBeInTheDocument();
    expect(within(card).queryByText("Atualizado")).toBeNull();
    // Agenda "ativa" com o agendador do servidor desligado: dito com todas as letras.
    expect(within(card).getByText("pausada no servidor")).toBeInTheDocument();
    expect(within(card).getByText(/desligada no servidor: sincronize manualmente/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Ver o registro da falha" })).toBeInTheDocument();
  });

  it("horário da agenda é o de Brasília (não 'fuso do servidor')", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    const card = (await screen.findByRole("heading", { name: "Elefante Letrado" })).closest(".card") as HTMLElement;
    await userEvent.setup().click(within(card).getByRole("button", { name: /Configurar conexão/ }));
    expect(within(card).getByText(/horário de Brasília/)).toBeInTheDocument();
    expect(within(card).queryByText(/fuso do servidor/)).toBeNull();
  });
});

// --- Etapa 2: honestidade da tela sobre o contrato comum --------------------

/** Execução TERMINADA com as contagens novas (alunos distintos, linhas, …). */
function execNova(over: Record<string, unknown> = {}) {
  return {
    ...EXEC_OK, id: 21, plataforma: "elefante", origem: "manual", status: "concluida",
    iniciada_em: "2026-10-20T10:00:00Z", finalizada_em: "2026-10-20T10:05:00Z",
    qtd_alunos: 3, qtd_linhas: 40, qtd_em_revisao: 0, qtd_falhas: 0,
    recalculo_pendente: false, motivo: null, periodo: null,
    ...over,
  };
}

function elefanteCom(exec: Record<string, unknown>, over: Record<string, unknown> = {}) {
  return elefanteConectado({ ultima_execucao: exec, ultima_tentativa: exec, ...over });
}

function cardDe(nome: string): HTMLElement {
  return screen.getByRole("heading", { name: nome }).closest(".card") as HTMLElement;
}

describe("Integrações — estados do contrato (etapa 2)", () => {
  it("'chegam sozinhos' só aparece com o agendador ligado", async () => {
    mocksIntegracoes({ agendador_ativo: true, plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    const { unmount } = renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    expect(await screen.findByText(/Os dados das plataformas chegam sozinhos/)).toBeInTheDocument();
    unmount();
  });

  it("agendador desligado: a tela diz que os dados só chegam quando alguém sincroniza", async () => {
    mocksIntegracoes({ agendador_ativo: false, plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    expect(await screen.findByText(/A atualização automática está desligada neste servidor/)).toBeInTheDocument();
    expect(screen.queryByText(/chegam sozinhos/)).toBeNull();
  });

  it("sem agendador_ativo (resposta antiga) não promete atualização automática", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    expect(await screen.findByText(/Aqui você confere se os dados das plataformas estão chegando/)).toBeInTheDocument();
    expect(screen.queryByText(/chegam sozinhos/)).toBeNull();
  });

  it("parcial: badge próprio, alunos atualizados, linhas, revisão e falhas, banner e registro", async () => {
    const parcial = execNova({ status: "parcial", qtd_alunos: 12, qtd_linhas: 80, qtd_em_revisao: 2, qtd_falhas: 1 });
    mocksIntegracoes(
      { alertas_abertos: 1, plataformas: [STATUS.plataformas[0], elefanteCom(parcial)] },
      [{
        id: 40, plataforma: "elefante", tipo: "coleta_parcial", severidade: "warn",
        mensagem: "1 turma falhou de 5.", resolvido: false, created_at: "2026-10-20T10:05:00Z",
      }],
    );
    responder("GET", "/escolas/1/sync/logs", []);
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    expect(within(card).getByText("Atualizado em parte")).toBeInTheDocument();
    expect(within(card).queryByText("Atualizado")).toBeNull();
    const resumo = within(card).getByRole("list", { name: "Resumo da última coleta" });
    expect(within(resumo).getByText("12 alunos atualizados")).toBeInTheDocument();
    expect(within(resumo).getByText("80 linhas recebidas")).toBeInTheDocument();
    expect(within(resumo).getByText("2 em revisão")).toBeInTheDocument();
    expect(within(resumo).getByText("1 falha")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Escolher o aluno certo em Revisões de identidade" }))
      .toHaveAttribute("href", "/revisoes-identidade");
    // O alerta da coleta parcial aparece no card, com rótulo humano.
    expect(within(card).getByText("Coleta parcial")).toBeInTheDocument();
    expect(within(card).getByText(/última tentativa: .*\(parcial\)/)).toBeInTheDocument();
    // Banner do topo.
    expect(screen.getByText(/Coleta parcial: Elefante Letrado/)).toBeInTheDocument();
    // O registro da coleta parcial está a um clique.
    await userEvent.setup().click(within(card).getByRole("button", { name: "Ver o registro da coleta" }));
    expect(await screen.findByRole("dialog", { name: "Logs da execução #21" })).toBeInTheDocument();
  });

  it("parcial sem aluno aplicado (D2(6), Matific): 'Verificado em parte' e o banner diz 'aplicado ou conferido'", async () => {
    // Só o endpoint dos nomes falhou; as contas já ligadas foram conferidas sem número mudado.
    const conferida = execNova({
      plataforma: "matific", status: "parcial", motivo: "coleta_parcial",
      qtd_alunos: 0, qtd_linhas: 3, qtd_falhas: 1,
    });
    mocksIntegracoes(
      { alertas_abertos: 1, plataformas: [elefanteCom(conferida, { plataforma: "matific" }), STATUS.plataformas[1]] },
      [{
        id: 41, plataforma: "matific", tipo: "coleta_parcial", severidade: "warn",
        mensagem: "Os nomes do Placar não vieram nesta coleta.", resolvido: false,
        created_at: "2026-10-20T10:05:00Z",
      }],
    );
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    await screen.findByRole("heading", { name: "Matific" });
    const card = cardDe("Matific");
    expect(within(card).getByText("Verificado em parte")).toBeInTheDocument();
    expect(within(card).queryByText("Atualizado em parte")).toBeNull();
    expect(within(card).getByText(/conferiu as contas já ligadas e nenhum número mudou/)).toBeInTheDocument();
    expect(within(card).queryByText(/aplicou dados/)).toBeNull();
    // Banner do topo: a plataforma continua listada, sem afirmar que só houve dado aplicado.
    expect(screen.getByText(/Coleta parcial: Matific/))
      .toHaveTextContent("o que chegou foi aplicado ou conferido");
  });

  it("recálculo pendente aparece em vermelho no topo e no card", async () => {
    const exec = execNova({ status: "parcial", motivo: "falha_apos_gravacao", recalculo_pendente: true });
    mocksIntegracoes({
      plataformas: [STATUS.plataformas[0], elefanteCom(exec, { recalculo_pendente: true })],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Recálculo pendente: Elefante Letrado.")).toBeInTheDocument();
    const alertas = screen.getAllByRole("alert");
    expect(alertas.some((a) => /Recálculo pendente/.test(a.textContent ?? ""))).toBe(true);
    const card = cardDe("Elefante Letrado");
    expect(within(card).getByText("Recálculo pendente.")).toBeInTheDocument();
    expect(within(card).getByText(/falhou depois de já ter gravado parte dos dados/)).toBeInTheDocument();
    expect(within(card).getByText(/última tentativa: .*\(parcial: falhou depois de gravar\)/)).toBeInTheDocument();
  });

  it("recálculo pendente: o gestor recalcula pela própria tela e o aviso some", async () => {
    const exec = execNova({ status: "concluida", recalculo_pendente: true });
    mocksIntegracoes({
      plataformas: [STATUS.plataformas[0], elefanteCom(exec, { recalculo_pendente: true })],
    });
    const posts: string[] = [];
    responder("POST", "/escolas/1/importacoes/recalcular", (caminho: string) => {
      posts.push(caminho);
      // O backend fecha a pendência: o /status recarregado vem sem ela.
      mocksIntegracoes({
        plataformas: [STATUS.plataformas[0],
          elefanteCom({ ...exec, recalculo_pendente: false }, { recalculo_pendente: false })],
      });
      return { ok: true };
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Recálculo pendente: Elefante Letrado.")).toBeInTheDocument();
    expect(screen.queryByText(/Avise o\s+suporte para refazer o recálculo/)).toBeNull();
    await userEvent.setup().click(screen.getByRole("button", { name: /Recalcular agora/ }));
    await waitFor(() => expect(posts).toEqual(["/escolas/1/importacoes/recalcular"]));
    await waitFor(() => expect(screen.queryByText(/Recálculo pendente/)).toBeNull());
  });

  it("recálculo pendente para quem não é gestor: orienta, sem o botão", async () => {
    const exec = execNova({ status: "concluida", recalculo_pendente: true });
    mocksIntegracoes({
      plataformas: [STATUS.plataformas[0], elefanteCom(exec, { recalculo_pendente: true })],
    });
    renderComApp(<Sincronizacao />, {
      rota: "/sincronizacao", usuario: usuarioFake({ cargo: "professor" }),
    });
    expect(await screen.findByText("Recálculo pendente: Elefante Letrado.")).toBeInTheDocument();
    expect(screen.getByText(/Peça à coordenação da escola para usar “Recalcular agora”/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Recalcular agora/ })).toBeNull();
  });

  it("sem recálculo pendente, nenhum aviso de recálculo", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteCom(execNova(), { recalculo_pendente: false })] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    await screen.findByRole("heading", { name: "Elefante Letrado" });
    expect(screen.queryByText(/Recálculo pendente/)).toBeNull();
  });

  it("'Último dado aplicado' × 'última verificação' (nada mudou)", async () => {
    const nada = execNova({ status: "sem_atualizacao", qtd_alunos: 0, motivo: "nada_mudou" });
    mocksIntegracoes({
      plataformas: [STATUS.plataformas[0], elefanteCom(nada, {
        ultimo_sucesso_em: "2026-10-10T10:00:00Z", ultima_verificacao_em: "2026-10-20T10:05:00Z",
        ultimo_status: "sem_atualizacao", ultimo_motivo: "nada_mudou",
      })],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    expect(within(card).getByText("Último dado aplicado")).toBeInTheDocument();
    expect(within(card).getByText(/^última verificação: /)).toBeInTheDocument();
    expect(within(card).getByText("Verificado: nada mudou")).toBeInTheDocument();
    expect(within(card).getByText(/última tentativa: .*\(sem atualização: nada mudou\)/)).toBeInTheDocument();
    expect(within(card).getByText("0 alunos atualizados")).toBeInTheDocument();
  });

  it("sem ultima_verificacao_em (resposta antiga) a linha de verificação não aparece", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    await screen.findByRole("heading", { name: "Elefante Letrado" });
    expect(within(cardDe("Elefante Letrado")).queryByText(/última verificação/)).toBeNull();
  });

  it("sem atualização por correspondência pendente: motivo, link para revisões e banner", async () => {
    const pendente = execNova({
      status: "sem_atualizacao", qtd_alunos: 0, qtd_em_revisao: 7, motivo: "correspondencia_pendente",
    });
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteCom(pendente)] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    expect(within(card).getByText("Sem atualização: correspondência pendente")).toBeInTheDocument();
    expect(within(card).getByText(/7 contas aguardam a escolha do aluno certo/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Ver revisões de identidade" }))
      .toHaveAttribute("href", "/revisoes-identidade");
    expect(screen.getByText(/Sem atualização por correspondência pendente: Elefante Letrado/)).toBeInTheDocument();
  });

  it("tudo em revisão: estado próprio no card, histórico e banner (não é 'em dia')", async () => {
    const tudo = execNova({
      status: "sem_atualizacao", qtd_alunos: 0, qtd_em_revisao: 5, motivo: "tudo_em_revisao",
    });
    mocksIntegracoes({
      plataformas: [STATUS.plataformas[0], elefanteCom(tudo, {
        ultimo_status: "sem_atualizacao", ultimo_motivo: "tudo_em_revisao",
      })],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    expect(within(card).getByText("Sem atualização: nenhuma conta da escola reconhecida")).toBeInTheDocument();
    expect(within(card).getByText(/5 contas aguardam em Revisões de identidade/)).toBeInTheDocument();
    expect(within(card).getByText(/não conta como dado em dia/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Ver revisões de identidade" }))
      .toHaveAttribute("href", "/revisoes-identidade");
    expect(within(card).getByText(
      /última tentativa: .*\(sem atualização: nenhuma conta da escola reconhecida\)/)).toBeInTheDocument();
    expect(within(card).queryByText("Sem atualização: correspondência pendente")).toBeNull();
    expect(screen.getByText(/Nenhuma conta da escola reconhecida na última coleta: Elefante Letrado/))
      .toBeInTheDocument();
    expect(screen.queryByText(/Sem atualização por correspondência pendente/)).toBeNull();
  });

  it("sem dados: a plataforma não trouxe dados (não é sucesso)", async () => {
    const vazia = execNova({ status: "sem_dados", qtd_alunos: 0, qtd_linhas: 0 });
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteCom(vazia)] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    expect(within(card).getByText("Sem dados na última coleta")).toBeInTheDocument();
    expect(within(card).getByText(/A plataforma não trouxe dados/)).toBeInTheDocument();
    expect(within(card).getByText(/última tentativa: .*\(a plataforma não trouxe dados\)/)).toBeInTheDocument();
    expect(within(card).queryByText("Atualizado")).toBeNull();
  });

  it("erro com código traduzido (sem acesso aos dados), nunca o texto cru no badge", async () => {
    const erro = execNova({
      status: "erro", qtd_alunos: 0, qtd_linhas: 0, motivo: "sem_acesso_ao_dado",
      erro_resumo: "HTTP 403 em /api/school_student",
    });
    mocksIntegracoes({
      plataformas: [STATUS.plataformas[0], elefanteCom(erro, { falha_categoria: "autenticacao" })],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    expect(within(card).getByText("Falhou: sem acesso aos dados")).toBeInTheDocument();
    expect(within(card).getByText(/recusou o acesso ao relatório/)).toBeInTheDocument();
    expect(within(card).queryByText(/^Falhou: HTTP 403/)).toBeNull();
    expect(within(card).getByText("Detalhe técnico: HTTP 403 em /api/school_student")).toBeInTheDocument();
    expect(within(card).getByText(/última tentativa: .*\(falhou: sem acesso aos dados\)/)).toBeInTheDocument();
  });

  it("nova tentativa na fila: 'Nova tentativa pendente', sem esconder a falha anterior", async () => {
    const falha = execNova({
      id: 50, status: "erro", qtd_alunos: 0, motivo: "timeout", erro_resumo: "teto de 2700 s",
    });
    const retry = { ...execNova({ id: 51, status: "fila", tentativa: 2 }), iniciada_em: null, finalizada_em: null };
    mocksIntegracoes({
      agendador_ativo: true,
      plataformas: [STATUS.plataformas[0], elefanteConectado({ ultima_execucao: retry, ultima_tentativa: falha })],
    });
    responder("GET", "/escolas/1/sync/logs", []);
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    expect(within(card).getByText("Nova tentativa pendente")).toBeInTheDocument();
    expect(within(card).queryByText("Sincronizando")).toBeNull();
    expect(within(card).getByText(/A última sincronização falhou \(demorou demais\)/)).toBeInTheDocument();
    expect(within(card).getByText(/última tentativa: .*\(falhou: demorou demais\)/)).toBeInTheDocument();
    await userEvent.setup().click(within(card).getByRole("button", { name: "Ver o registro da falha" }));
    expect(await screen.findByRole("dialog", { name: "Logs da execução #50" })).toBeInTheDocument();
  });

  it("histórico com as contagens novas: colunas por aluno, rótulos por status e execução antiga marcada", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    responder("GET", "/escolas/1/sync/historico?limite=30", [
      execNova({ id: 60, status: "parcial", qtd_alunos: 9, qtd_linhas: 50, qtd_em_revisao: 4, qtd_falhas: 2,
        recalculo_pendente: true }),
      execNova({ id: 61, status: "sem_atualizacao", qtd_alunos: 0, motivo: "nada_mudou" }),
      execNova({ id: 62, plataforma: "matific", status: "sem_dados", qtd_alunos: 0, qtd_linhas: 0,
        periodo: { inicio: "2026-10-01", fim: "2026-10-15" } }),
      execNova({ id: 63, status: "erro", qtd_alunos: 0, motivo: "parser_incompativel" }),
      { ...EXEC_OK, id: 64, qtd_alunos: 88 },   // execução antiga: sem qtd_linhas
    ]);
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    await userEvent.setup().click(await screen.findByRole("button", { name: /Detalhes técnicos/ }));

    const tabela = await screen.findByRole("table");
    for (const coluna of ["Alunos atualizados", "Linhas recebidas", "Em revisão", "Falhas"]) {
      expect(within(tabela).getByRole("columnheader", { name: coluna })).toBeInTheDocument();
    }
    expect(within(tabela).queryByRole("columnheader", { name: "Registros" })).toBeNull();
    expect(within(tabela).getByText("parcial")).toBeInTheDocument();
    expect(within(tabela).getByText("recálculo pendente")).toBeInTheDocument();
    expect(within(tabela).getByText("sem atualização: nada mudou")).toBeInTheDocument();
    expect(within(tabela).getByText("a plataforma não trouxe dados")).toBeInTheDocument();
    expect(within(tabela).getByText("período 01/10/2026 a 15/10/2026")).toBeInTheDocument();
    expect(within(tabela).getByText("falhou: formato do relatório mudou")).toBeInTheDocument();
    expect(within(tabela).getByText("88*")).toBeInTheDocument();
    expect(screen.getByText(/Execuções marcadas com \* são anteriores a essa contagem/)).toBeInTheDocument();
  });

  it("histórico só com execuções antigas mantém 'Registros' e a explicação antiga", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    responder("GET", "/escolas/1/sync/historico?limite=30", [EXEC_OK]);
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    await userEvent.setup().click(await screen.findByRole("button", { name: /Detalhes técnicos/ }));
    const tabela = await screen.findByRole("table");
    expect(within(tabela).getByRole("columnheader", { name: "Registros" })).toBeInTheDocument();
    expect(within(tabela).queryByRole("columnheader", { name: "Alunos atualizados" })).toBeNull();
    expect(within(tabela).getByText("concluída")).toBeInTheDocument();
  });
});

describe("Integrações — coleta do Matific de um dia só", () => {
  async function abrirPeriodo(matificOver: Record<string, unknown> = {}) {
    const posts: string[] = [];
    mocksIntegracoes({
      plataformas: [{ ...STATUS.plataformas[0], ...matificOver }, STATUS.plataformas[1]],
    });
    responder("POST", "/escolas/1/sync/agora", (caminho: string) => { posts.push(caminho); return []; });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    await screen.findByRole("heading", { name: "Matific" });
    const card = cardDe("Matific");
    const u = userEvent.setup();
    await u.click(within(card).getByRole("button", { name: /coletar um período específico/ }));
    return { card, posts, u };
  }

  it("semântica do fim desconhecida (campo ausente): 1 dia fica desabilitado, com explicação", async () => {
    const { card } = await abrirPeriodo();
    fireEvent.change(within(card).getByLabelText("De"), { target: { value: "2026-10-20" } });
    fireEvent.change(within(card).getByLabelText("Até"), { target: { value: "2026-10-20" } });
    expect(within(card).getByRole("button", { name: /Coletar do Matific este período/ })).toBeDisabled();
    expect(within(card).getByText(/Período de um dia só não é aceito/)).toBeInTheDocument();
    expect(within(card).getByText(/semântica do fim de período do Matific ainda não foi confirmada/)).toBeInTheDocument();
  });

  it("semântica desconhecida não muda intervalos de 2 dias ou mais", async () => {
    const { card, posts, u } = await abrirPeriodo({ periodo_um_dia_permitido: false });
    fireEvent.change(within(card).getByLabelText("De"), { target: { value: "2026-10-19" } });
    fireEvent.change(within(card).getByLabelText("Até"), { target: { value: "2026-10-20" } });
    const botao = within(card).getByRole("button", { name: /Coletar do Matific este período/ });
    expect(botao).toBeEnabled();
    await u.click(botao);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toContain("inicio=2026-10-19");
    expect(posts[0]).toContain("fim=2026-10-20");
  });

  it("com periodo_um_dia_permitido o botão aceita início = fim", async () => {
    const { card, posts, u } = await abrirPeriodo({ periodo_um_dia_permitido: true });
    fireEvent.change(within(card).getByLabelText("De"), { target: { value: "2026-10-20" } });
    fireEvent.change(within(card).getByLabelText("Até"), { target: { value: "2026-10-20" } });
    expect(within(card).queryByText(/semântica do fim de período/)).toBeNull();
    const botao = within(card).getByRole("button", { name: /Coletar do Matific este período/ });
    expect(botao).toBeEnabled();
    await u.click(botao);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toContain("inicio=2026-10-20");
    expect(posts[0]).toContain("fim=2026-10-20");
  });
});

describe("Integrações — agenda com o agendador desligado", () => {
  it("a agenda salva não promete 'próxima' quando o agendador do servidor está desligado", async () => {
    mocksIntegracoes({ agendador_ativo: false, plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    await userEvent.setup().click(within(card).getByRole("button", { name: /Configurar conexão/ }));
    expect(within(card).getByText(/Salvo, mas pausado: o agendador está desligado no servidor/)).toBeInTheDocument();
    expect(within(card).queryByText(/Ativo · próxima/)).toBeNull();
  });

  it("com o agendador ligado a agenda mostra a próxima execução", async () => {
    mocksIntegracoes({ agendador_ativo: true, plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });
    await screen.findByRole("heading", { name: "Elefante Letrado" });
    const card = cardDe("Elefante Letrado");
    await userEvent.setup().click(within(card).getByRole("button", { name: /Configurar conexão/ }));
    expect(within(card).getByText(/Ativo · próxima/)).toBeInTheDocument();
  });
});

describe("Integrações — visão geral do admin global", () => {
  const DASH = {
    escolas_total: 2, escolas_configuradas: 2, escolas_sincronizadas: 1,
    escolas_com_erro: 0, escolas_desatualizadas: 0, em_andamento: 0, fila: 0, workers_ativos: 0,
    scheduler_ligado: false, ultima_sincronizacao: null, duracao_ultima_ms: null,
    tempo_medio_ms: null, alertas_abertos: 0,
  };
  const global = usuarioFake({ cargo: "admin", is_global: true, escola_id: 1 });

  it("rótulos seguem o backend (dado aplicado) e os pré-requisitos do agendador aparecem", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    responder("GET", "/sync/dashboard", {
      ...DASH,
      prerequisitos_agendador: {
        habilitado: false, forcar: false, pode_iniciar: false, decisao_no_boot: "desligado",
        criticos_falhos: ["credenciais_legiveis"],
        verificacoes: [
          { id: "teto_coerente", ok: true, critico: true, motivo: "SYNC_TRAVADA_S (3600 s) > teto (2700 s)." },
          { id: "credenciais_legiveis", ok: false, critico: true,
            motivo: "Credencial ausente ou ilegível em 1 de 2 integração(ões)." },
          { id: "fila_da_agenda", ok: false, critico: false, motivo: "Pior caso em série passa de 1 h." },
        ],
      },
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao", usuario: global });

    const bloco = await screen.findByRole("region", { name: "Pré-requisitos do agendador" });
    expect(within(bloco).getByText(/1 pré-requisito\(s\) crítico\(s\) falhando/)).toBeInTheDocument();
    expect(within(bloco).getByText(/no boot: desligado/)).toBeInTheDocument();
    const lista = within(bloco).getByRole("list", { name: "Pré-requisitos que falharam" });
    expect(within(lista).getByText("credenciais_legiveis")).toBeInTheDocument();
    expect(within(lista).getByText("fila_da_agenda")).toBeInTheDocument();
    expect(within(lista).queryByText("teto_coerente")).toBeNull();     // ok não polui
    // Conta escola que aplicou dado em QUALQUER época (não é "em dia": isso é o
    // "Desatualizadas" ao lado) — o rótulo não sugere estado atual.
    expect(screen.getByText("Já sincronizaram")).toBeInTheDocument();
    expect(screen.getByText("com dado aplicado alguma vez")).toBeInTheDocument();
    // O StatCard do painel (os cards das plataformas usam o mesmo rótulo).
    expect(screen.getAllByText("Último dado aplicado").some((e) => e.tagName === "SPAN")).toBe(true);
    expect(screen.queryByText("Última concluída")).toBeNull();
    expect(screen.queryByText("com coleta concluída")).toBeNull();
  });

  it("painel antigo, sem o bloco: nada de pré-requisitos inventados", async () => {
    mocksIntegracoes({ plataformas: [STATUS.plataformas[0], elefanteConectado()] });
    responder("GET", "/sync/dashboard", DASH);
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao", usuario: global });
    await screen.findByText("com dado aplicado alguma vez");
    expect(screen.queryByRole("region", { name: "Pré-requisitos do agendador" })).toBeNull();
  });
});

describe("Integrações — credencial ilegível (S16)", () => {
  it("credencial gravada como válida que o servidor não lê: pede recadastro e não deixa sincronizar", async () => {
    mocksIntegracoes({
      plataformas: [
        STATUS.plataformas[0],
        elefanteConectado({ conectada: false, credencial_status: "ilegivel" }),
      ],
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao" });

    expect(await screen.findByText("Recadastre o acesso")).toBeInTheDocument();
    expect(screen.queryByText("Atualizado")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sincronizar Elefante Letrado/i })).toBeDisabled();
    expect(screen.getByText(/Atenção: há dados que precisam de verificação/)).toBeInTheDocument();
    expect(screen.getByText(/Recadastre o acesso: Elefante Letrado/)).toBeInTheDocument();
  });
});

// --- Política de criação de aluno (antes: só pela API, sem tela) --------------

describe("Integrações — política de criação de aluno", () => {
  const global = usuarioFake({ cargo: "admin", is_global: true, escola_id: 1 });
  const REGIAO = { name: "Criação de alunos pela sincronização" };
  const puts = () => api.mock.calls.filter(([, opcoes]) =>
    (opcoes as RequestInit | undefined)?.method === "PUT");
  const BLOQUEAR = "Bloquear a criação de alunos pela plataforma?";
  /** A caixa do diálogo de confirmação (o Modal do design system), pelo título. */
  const dialogo = (titulo: string) => within(screen.getByRole("heading", { name: titulo }).parentElement!);

  it("o Admin Global vê a política e a muda com confirmação, explicação e motivo", async () => {
    mocks();
    const corpos: unknown[] = [];
    responder("PUT", URL_POLITICA, (_c: string, opcoes: RequestInit | FormData) => {
      const corpo = JSON.parse(String((opcoes as RequestInit).body));
      corpos.push(corpo);
      mockPolitica(corpo.criar_aluno);              // o backend grava; o GET relido vem novo
      return { criar_aluno: corpo.criar_aluno };
    });
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao", usuario: global });
    const usuario = userEvent.setup();

    const regiao = await screen.findByRole("region", REGIAO);
    expect(await within(regiao).findByText("Permitida")).toBeInTheDocument();
    expect(within(regiao).getByText(/podem criar a ficha de um aluno que não for reconhecido/))
      .toBeInTheDocument();

    // Cancelar não grava nada.
    await usuario.click(within(regiao).getByRole("button", { name: "Bloquear a criação pela plataforma" }));
    await usuario.click(dialogo(BLOQUEAR).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("heading", { name: BLOQUEAR })).toBeNull();
    expect(puts()).toHaveLength(0);

    // Confirmar: o efeito é explicado ANTES (não matricula; nada já gravado muda).
    await usuario.click(within(regiao).getByRole("button", { name: "Bloquear a criação pela plataforma" }));
    const caixa = dialogo(BLOQUEAR);
    expect(caixa.getByText(/a plataforma não\s+matricula ninguém/)).toBeInTheDocument();
    expect(caixa.getByText(/A Lista Piloto e o cadastro pela tela de Alunos continuam criando/))
      .toBeInTheDocument();
    expect(caixa.getByText("Nada já gravado muda e nada é recalculado.")).toBeInTheDocument();
    await usuario.type(caixa.getByRole("textbox", { name: /Motivo/ }), "matrícula vem da Lista Piloto");
    await usuario.click(caixa.getByRole("button", { name: "Confirmar: bloquear" }));

    await waitFor(() => expect(corpos).toEqual([
      { criar_aluno: "bloquear", motivo: "matrícula vem da Lista Piloto" }]));
    expect(await within(regiao).findByText("Bloqueada")).toBeInTheDocument();
    expect(within(regiao).getByText("Política salva: a plataforma não cria mais alunos nesta escola."))
      .toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: BLOQUEAR })).toBeNull();
    // E o caminho de volta, também com confirmação (motivo vazio vai como null).
    await usuario.click(within(regiao).getByRole("button", { name: "Permitir a criação pela plataforma" }));
    const volta = dialogo("Permitir que a plataforma crie alunos?");
    expect(volta.getByText(/vira ficha nova, ativa, sem RA e sem nascimento/)).toBeInTheDocument();
    // A exceção (A2/A5), igual ao Suporte: nome abreviado e duas contas com o mesmo nome
    // não viram ficha nem com a política permitindo — vão para a fila.
    const efeito = volta.getByText(/vira ficha nova, ativa/).textContent ?? "";
    expect(efeito).toContain("nome abreviado (como “ZEFA Q”)");
    expect(efeito).toContain("duas contas com o mesmo nome no mesmo relatório");
    expect(efeito).toMatch(/não viram ficha e esperam em Revisões de identidade/);
    await usuario.click(volta.getByRole("button", { name: "Confirmar: permitir" }));
    await waitFor(() => expect(corpos).toHaveLength(2));
    expect(corpos[1]).toEqual({ criar_aluno: "permitir", motivo: null });
    expect(await within(regiao).findByText("Permitida")).toBeInTheDocument();
  });

  it("o admin da escola só vê o estado: sem botão de mudar, nenhuma gravação", async () => {
    mocks();
    mockPolitica("bloquear");
    renderComApp(<Sincronizacao />, {
      rota: "/sincronizacao", usuario: usuarioFake({ cargo: "admin", is_global: false }),
    });

    const regiao = await screen.findByRole("region", REGIAO);
    expect(await within(regiao).findByText("Bloqueada")).toBeInTheDocument();
    expect(within(regiao).getByText(/A plataforma não matricula ninguém nesta escola/)).toBeInTheDocument();
    expect(within(regiao).getByText("Só a Administração Global altera esta política.")).toBeInTheDocument();
    expect(within(regiao).queryByRole("button")).toBeNull();
    expect(screen.queryByRole("button", { name: /criação pela plataforma/ })).toBeNull();
    expect(puts()).toHaveLength(0);
  });

  it("a coordenação também lê em modo leitura", async () => {
    mocks();
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao", usuario: usuarioFake({ cargo: "coordenador" }) });
    const regiao = await screen.findByRole("region", REGIAO);
    expect(await within(regiao).findByText("Permitida")).toBeInTheDocument();
    expect(within(regiao).queryByRole("button")).toBeNull();
  });

  it("professor não vê o card nem consulta a política (o GET pede cargo de gestão)", async () => {
    mocks();
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao", usuario: usuarioFake({ cargo: "professor" }) });
    await screen.findByRole("heading", { name: "Matific" });
    expect(screen.queryByRole("region", REGIAO)).toBeNull();
    expect(api.mock.calls.some(([c]) => String(c) === URL_POLITICA)).toBe(false);
  });

  it("recusa do servidor ao salvar fica no diálogo e o estado não muda", async () => {
    mocks();
    responderErro("PUT", URL_POLITICA, 403, "Apenas o Admin Global pode alterar.");
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao", usuario: global });
    const usuario = userEvent.setup();

    const regiao = await screen.findByRole("region", REGIAO);
    await usuario.click(await within(regiao).findByRole("button", { name: "Bloquear a criação pela plataforma" }));
    await usuario.click(dialogo(BLOQUEAR).getByRole("button", { name: "Confirmar: bloquear" }));
    expect(await dialogo(BLOQUEAR).findByText("Apenas o Admin Global pode alterar.")).toBeInTheDocument();
    expect(within(regiao).getByText("Permitida")).toBeInTheDocument();
    expect(within(regiao).queryByText(/Política salva/)).toBeNull();
  });

  it("falha ao ler a política aparece no card, sem esconder o resto da tela", async () => {
    mocks();
    responderErro("GET", URL_POLITICA, 403, "Sem acesso a esta escola.");
    renderComApp(<Sincronizacao />, { rota: "/sincronizacao", usuario: global });
    const regiao = await screen.findByRole("region", REGIAO);
    expect(await within(regiao).findByText(/Não foi possível ler a política desta escola: Sem acesso a esta escola\./))
      .toBeInTheDocument();
    expect(within(regiao).queryByRole("button")).toBeNull();
    expect(screen.getByRole("heading", { name: "Matific" })).toBeInTheDocument();
  });
});
