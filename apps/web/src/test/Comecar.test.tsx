import { describe, expect, it } from "vitest";

import Comecar from "../pages/Comecar";
import { renderComApp, responder, screen, usuarioFake } from "./utils";

function statusMock(over: Record<string, unknown> = {}) {
  responder("GET", "/escolas/1/sync/status", {
    escola_id: 1, escola_nome: "ESCOLA TESTE", qtd_alunos: 0, qtd_turmas: 0,
    alertas_abertos: 0, lista_piloto_importada: false, integracao_configurada: false,
    plataformas: [
      { plataforma: "matific", conectada: false, credencial_status: "nao_configurada" },
      { plataforma: "elefante", conectada: false, credencial_status: "nao_configurada" },
    ],
    ...over,
  });
}

describe("Comece aqui (onboarding)", () => {
  it("escola nova abre nas boas-vindas com a escola e o botão Começar", async () => {
    statusMock();
    renderComApp(<Comecar />, { rota: "/comecar", usuario: usuarioFake({ cargo: "coordenador" }) });

    expect(await screen.findByRole("heading", { name: "ESCOLA TESTE" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Começar/i })).toBeInTheDocument();
  });

  it("escola já configurada retoma no passo final 'Escola pronta!'", async () => {
    statusMock({ qtd_alunos: 30, qtd_turmas: 3, lista_piloto_importada: true, integracao_configurada: true });
    renderComApp(<Comecar />, { rota: "/comecar", usuario: usuarioFake({ cargo: "coordenador" }) });

    expect(await screen.findByRole("heading", { name: /Escola pronta/i })).toBeInTheDocument();
    expect(screen.getByText(/integração configurada/i)).toBeInTheDocument();
  });

  it("bloqueia professor (sem permissão de gestão)", async () => {
    statusMock();
    renderComApp(<Comecar />, { rota: "/comecar", usuario: usuarioFake({ cargo: "professor" }) });

    expect(await screen.findByText(/Somente administradores e coordenadores/i)).toBeInTheDocument();
  });
});
