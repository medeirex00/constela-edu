import { describe, expect, it } from "vitest";

import Comecar from "../pages/Comecar";
import { renderComApp, responder, screen, usuarioFake, within } from "./utils";

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

  it("a trilha mostra os quatro passos com o rótulo inteiro (texto e title)", async () => {
    statusMock();
    renderComApp(<Comecar />, { rota: "/comecar", usuario: usuarioFake({ cargo: "coordenador" }) });

    const trilha = await screen.findByRole("list", { name: "Passos da configuração" });
    const itens = within(trilha).getAllByRole("listitem");
    expect(itens.map((li) => li.textContent)).toEqual([
      "Passo 1: Escola", "Passo 2: Turmas e alunos", "Passo 3: Integrações", "Passo 4: Pronto",
    ]);
    expect(itens[0]).toHaveAttribute("aria-current", "step");
    // No estreito o rótulo quebra dentro da pílula; o title guarda o texto completo.
    expect(within(itens[1]).getByTitle("Turmas e alunos")).toBeInTheDocument();
  });

  it("integrações no celular: Concluir em cima, Configurar depois e Voltar embaixo (só a ordem visual)", async () => {
    // Lista Piloto importada e nenhuma plataforma conectada: retoma no passo 3.
    statusMock({ qtd_alunos: 30, qtd_turmas: 3, lista_piloto_importada: true });
    renderComApp(<Comecar />, { rota: "/comecar", usuario: usuarioFake({ cargo: "coordenador" }) });

    const concluir = await screen.findByRole("button", { name: /Concluir/ });
    const configurar = screen.getByRole("button", { name: "Configurar depois" });
    const voltar = screen.getByRole("button", { name: /Voltar/ });
    // No DOM (e no Tab) a ordem continua Voltar → Configurar depois → Concluir; abaixo de
    // 640 px a coluna invertida põe Concluir em cima, com os botões em largura total.
    const grupo = concluir.parentElement as HTMLElement;
    expect(grupo).toBe(configurar.parentElement);
    expect(grupo).toHaveClass("flex-col-reverse", "sm:flex-row");
    expect(grupo.parentElement).toBe(voltar.parentElement);
    expect(grupo.parentElement).toHaveClass("flex-col-reverse", "sm:flex-row", "sm:justify-between");
    expect(voltar.compareDocumentPosition(concluir) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // A nota do botão travado fica centrada no celular e à direita a partir de 640 px.
    expect(screen.getByText(/libera quando pelo menos uma plataforma/)).toHaveClass("text-center", "sm:text-right");
    expect(concluir).toBeDisabled();
  });

  it("bloqueia professor (sem permissão de gestão)", async () => {
    statusMock();
    renderComApp(<Comecar />, { rota: "/comecar", usuario: usuarioFake({ cargo: "professor" }) });

    expect(await screen.findByText(/Somente administradores e coordenadores/i)).toBeInTheDocument();
  });
});
