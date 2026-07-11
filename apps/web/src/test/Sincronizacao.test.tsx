import { describe, expect, it } from "vitest";

import Sincronizacao from "../pages/Sincronizacao";
import { renderComApp, responder, screen } from "./utils";

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
