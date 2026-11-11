import { describe, expect, it } from "vitest";

import Comecar from "../pages/Comecar";
import { renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

// O /sync/status passou a contar alunos e turmas do ANO LETIVO ATIVO (como /alunos e
// /turmas). O "Comece aqui" diz isso ao lado dos números: na virada, "0 turma(s) · 0
// aluno(s) cadastrados" fazia parecer que a escola tinha perdido o cadastro do ano
// anterior.
function statusMock(over: Record<string, unknown> = {}) {
  responder("GET", "/escolas/1/sync/status", {
    escola_id: 1, escola_nome: "ESCOLA FICTICIA", qtd_alunos: 0, qtd_turmas: 0,
    alertas_abertos: 0, lista_piloto_importada: false, integracao_configurada: false,
    plataformas: [
      { plataforma: "matific", conectada: false, credencial_status: "nao_configurada" },
      { plataforma: "elefante", conectada: false, credencial_status: "nao_configurada" },
    ],
    ...over,
  });
}

const coordenador = () => usuarioFake({ cargo: "coordenador" });

describe("Comece aqui: os números são do ano letivo ativo", () => {
  it("boas-vindas", async () => {
    statusMock({ qtd_turmas: 2, qtd_alunos: 41 });
    renderComApp(<Comecar />, { rota: "/comecar", usuario: coordenador() });
    expect(await screen.findByText(
      /2 turma\(s\) · 41 aluno\(s\) cadastrados no ano letivo atual\./)).toBeInTheDocument();
  });

  it("passo da Lista Piloto já importada", async () => {
    statusMock({ qtd_turmas: 0, qtd_alunos: 0, lista_piloto_importada: true });
    renderComApp(<Comecar />, { rota: "/comecar", usuario: coordenador() });
    // A tela retoma no passo 3 (integrações); volta ao 2 pelo botão.
    await userEvent.click(await screen.findByRole("button", { name: /Voltar/ }));
    expect(await screen.findByText(
      /Já há 0 turma\(s\) e 0 aluno\(s\) no ano letivo atual\./)).toBeInTheDocument();
  });

  it("escola pronta", async () => {
    statusMock({ qtd_turmas: 3, qtd_alunos: 30, lista_piloto_importada: true,
                 integracao_configurada: true });
    renderComApp(<Comecar />, { rota: "/comecar", usuario: coordenador() });
    await screen.findByRole("heading", { name: /Escola pronta/i });
    expect(screen.getByText(
      /3 turma\(s\) e 30 aluno\(s\) cadastrados no ano letivo atual e as plataformas conectadas\./,
    )).toBeInTheDocument();
  });
});
