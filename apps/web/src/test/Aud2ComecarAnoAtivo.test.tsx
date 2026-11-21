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
    statusMock({ qtd_turmas: 2, qtd_alunos: 41, lista_piloto_importada: true });
    renderComApp(<Comecar />, { rota: "/comecar", usuario: coordenador() });
    // A tela retoma no passo 3 (integrações); volta ao 2 pelo botão.
    await userEvent.click(await screen.findByRole("button", { name: /Voltar/ }));
    expect(await screen.findByText(
      /Já há 2 turma\(s\) e 41 aluno\(s\) no ano letivo atual\./)).toBeInTheDocument();
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

// REV2-SYNC2-2 (sobre G_VIRADA-2): na virada (ano ativo novo, Lista Piloto do ano
// ainda não enviada) o /sync/status devolve 0 turma(s) e 0 aluno(s) com
// lista_piloto_importada=true (a escola tem turmas de outro ano). A tela dizia, num
// aviso VERDE, "Já há 0 turma(s) e 0 aluno(s)… você pode importar outra planilha para
// complementar" e, no fim, "0 turma(s) e 0 aluno(s) cadastrados" com "✓ turmas e
// alunos". O passo marcado e a regra (voltar a pedir a Lista na virada, G_VIRADA-2c)
// continuam do dono: só o TEXTO passa a dizer a verdade.
describe("Comece aqui na virada: ano ativo ainda sem turmas", () => {
  const VIRADA = { qtd_turmas: 0, qtd_alunos: 0, lista_piloto_importada: true };
  const AVISO = "A escola ainda não tem turmas no ano letivo atual: importe a Lista Piloto deste ano.";

  it("passo 2: aviso de importar a Lista do ano, não o 'Já há' verde", async () => {
    statusMock(VIRADA);
    renderComApp(<Comecar />, { rota: "/comecar", usuario: coordenador() });
    await userEvent.click(await screen.findByRole("button", { name: /Voltar/ }));
    const aviso = await screen.findByText(AVISO);
    expect(aviso.closest("[role='status']")?.className ?? "").toMatch(/amber/);
    expect(aviso.closest("[role='status']")?.className ?? "").not.toMatch(/emerald/);
    expect(screen.queryByText(/Já há 0 turma/)).not.toBeInTheDocument();
    expect(screen.queryByText(/complementar/)).not.toBeInTheDocument();
  });

  it("escola pronta: diz que falta a Lista do ano, sem '0 turma(s)' nem '✓ turmas e alunos'",
     async () => {
    statusMock({ ...VIRADA, integracao_configurada: true });
    renderComApp(<Comecar />, { rota: "/comecar", usuario: coordenador() });
    await screen.findByRole("heading", { name: /Escola pronta/i });
    expect(screen.getByText(
      /Ainda não há turmas no ano letivo atual: importe a Lista Piloto deste ano\./,
    )).toBeInTheDocument();
    expect(screen.queryByText(/0 turma\(s\) e 0 aluno\(s\) cadastrados/)).not.toBeInTheDocument();
    expect(screen.queryByText("✓ turmas e alunos")).not.toBeInTheDocument();
    expect(screen.getByText("turmas do ano pendentes")).toBeInTheDocument();
    // A integração continua dita como está.
    expect(screen.getByText("✓ integração configurada")).toBeInTheDocument();
  });

  it("escola pronta sem integração: o mesmo aviso e o caminho para Integrações", async () => {
    statusMock(VIRADA);
    renderComApp(<Comecar />, { rota: "/comecar", usuario: coordenador() });
    // Retoma no passo 3; "Configurar depois" leva ao fim.
    await userEvent.click(await screen.findByRole("button", { name: /Configurar depois/ }));
    await screen.findByRole("heading", { name: /Escola pronta/i });
    expect(screen.getByText(
      /Ainda não há turmas no ano letivo atual: importe a Lista Piloto deste ano\. Você pode conectar as plataformas quando quiser em Integrações\./,
    )).toBeInTheDocument();
  });
});
