/**
 * Diagnóstico da integração Elefante — tela técnica (só a casca mudou na identidade
 * v2). Trava: só gestão executa; nada roda antes do clique; o resultado mostra os
 * endpoints com o status em texto; as datas saem no horário de Brasília (dataHora),
 * não no fuso do navegador; a falha da execução oferece "Tentar de novo".
 */
import { describe, expect, it } from "vitest";

import DiagnosticoElefante from "../pages/DiagnosticoElefante";
import { act, api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor } from "./utils";

const URL = "/escolas/1/sync/elefante/diagnostico";

const RESULTADO = {
  inventario: {
    ok: true, turmas: 4, auth: "jwt", aceita_datas_personalizadas: true,
    periodos_no_trafego: ["semana", "mes"],
    gerado_em: "2026-10-31T15:30:00Z",
    endpoints: [
      { nome: "relatorio_turma", metodo: "GET", rota: "/api/reports/course", status: 200,
        parametros: ["courseId", "from", "to"], estrutura: "{ itens: [...] }",
        paginacao: { formato: "pagina", chaves_paginacao: ["page"], lista_em: "items", itens: 30 } },
      { nome: "questoes", metodo: "POST", rota: "/api/questions", status: 403, erro: "acesso negado ao robô" },
    ],
  },
  diff: { primeira_vez: false, novos_endpoints: ["questoes"], endpoints_sumidos: [], estrutura_mudou: [],
          avisos: ["Endpoint novo: questoes"] },
  anterior_em: "2026-10-30T12:00:00Z",
};

const chamadas = () => api.mock.calls.filter(([caminho]) => caminho === URL);

describe("Diagnóstico do Elefante", () => {
  it("só executa no clique e mostra endpoints, status e mudanças", async () => {
    responder("POST", URL, RESULTADO);
    renderComApp(<DiagnosticoElefante />, { rota: "/diagnostico-elefante" });
    expect(await screen.findByRole("heading", { level: 1, name: "Diagnóstico da Integração Elefante" })).toBeInTheDocument();
    expect(screen.getByText("Nenhum diagnóstico ainda")).toBeInTheDocument();
    // Celular: a descrição do estado vazio não encosta nas bordas do cartão.
    expect(screen.getByText("Nenhum diagnóstico ainda").parentElement).toHaveClass("px-5");
    expect(chamadas()).toHaveLength(0);

    await userEvent.setup().click(screen.getByRole("button", { name: "Executar diagnóstico" }));
    expect(await screen.findByText("relatorio_turma")).toBeInTheDocument();
    expect(chamadas()).toHaveLength(1);
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("403")).toBeInTheDocument();
    expect(screen.getByText(/acesso negado ao robô/)).toBeInTheDocument();
    expect(screen.getByText("Mudanças detectadas na API")).toBeInTheDocument();
    expect(screen.getByText("JWT (Bearer)")).toBeInTheDocument();
    // Horário de Brasília (15:30 UTC = 12:30), não o fuso de quem abre a tela.
    expect(screen.getByText("31/10/2026, 12:30")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Executar de novo" })).toBeInTheDocument();
  });

  it("falha na execução: diz o motivo e deixa tentar de novo", async () => {
    responderErro("POST", URL, 502, "O Elefante não respondeu.");
    renderComApp(<DiagnosticoElefante />, { rota: "/diagnostico-elefante" });
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Executar diagnóstico" }));
    expect(await screen.findByText("O Elefante não respondeu.")).toBeInTheDocument();
    responder("POST", URL, RESULTADO);
    await u.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("relatorio_turma")).toBeInTheDocument();
  });

  it("professor não executa (acesso restrito)", async () => {
    renderComApp(<DiagnosticoElefante />, {
      rota: "/diagnostico-elefante", usuario: usuarioFake({ cargo: "professor" }),
    });
    // Espera a sessão (/auth/me) carregar de verdade: antes dela, qualquer perfil vê
    // "Acesso restrito" — o teste só vale com o professor já identificado.
    await waitFor(() => expect(api.mock.calls.some(([c]) => c === "/auth/me")).toBe(true));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("Acesso restrito")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Executar diagnóstico" })).toBeNull();
    expect(chamadas()).toHaveLength(0);
  });
});
