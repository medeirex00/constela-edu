import { describe, expect, it } from "vitest";

import Sincronizacao from "../pages/Sincronizacao";
import { renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

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
    // Situação: conectada, última execução concluída e em dia.
    expect(screen.getByText("Funcionando")).toBeInTheDocument();
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
    expect(screen.queryByText("Funcionando")).not.toBeInTheDocument();
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
    // O Elefante (sem erro) segue "Funcionando" e sem detalhe técnico.
    const cardElefante = screen.getByRole("heading", { name: "Elefante Letrado" }).closest(".card") as HTMLElement;
    expect(within(cardElefante).getByText("Funcionando")).toBeInTheDocument();
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
});
