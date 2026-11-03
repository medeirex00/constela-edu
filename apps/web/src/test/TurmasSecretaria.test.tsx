/**
 * Turmas: a Secretaria (rede vinculada, não-global) só CONSULTA. O backend recusa
 * com 403 todo POST/PUT/DELETE por-escola dela (deps.escola_autorizada), então a
 * tela não mostra criar, criar várias, consolidar duplicadas, seleção em massa nem
 * editar/arquivar/excluir na linha. O coordenador da própria escola (sem rede_id)
 * continua com todos os controles. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import Turmas from "../pages/Turmas";
import {
  api,
  renderComApp,
  responder,
  screen,
  turmaFake,
  userEvent,
  usuarioFake,
  waitFor,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_PROFESSORES = "/escolas/1/professores";
const secretaria = usuarioFake({ rede_id: 7 });
const DESCRICAO_SECRETARIA =
  "Turmas da escola selecionada, só para consulta. Quem cadastra e edita é a escola.";

function semear(turmas = [turmaFake({ id: 3, nome: "3º Ano A", professor_id: null })]) {
  responder("GET", URL_TURMAS, turmas);
  responder("GET", URL_PROFESSORES, []);
}

/** Monta como Secretaria e espera o estado ESTÁVEL. A Secretaria abre a sessão em
 *  "Toda a Rede" (escolaId nulo) e só então a escola é reaplicada no contexto —
 *  a lista é buscada de novo. Sem esperar essa 2ª busca, um elemento achado na
 *  1ª renderização (antes do /auth/me) sai do DOM logo depois. */
async function montarComoSecretaria() {
  renderComApp(<Turmas />, { rota: "/turmas", usuario: secretaria, escolaSelecionada: 1 });
  // O texto só existe para a Secretaria: prova que a sessão dela abriu.
  await screen.findByText(DESCRICAO_SECRETARIA);
  await waitFor(() =>
    expect(api.mock.calls.filter(([c]) => String(c).startsWith(URL_TURMAS)).length)
      .toBeGreaterThanOrEqual(2));
}

describe("Turmas: Secretaria só consulta", () => {
  it("Secretaria vê a lista, mas nenhum controle de escrita", async () => {
    semear();
    // A Secretaria entra em "Toda a Rede"; para uma tela POR ESCOLA ela seleciona
    // a escola no contexto (escolaSelecionada).
    await montarComoSecretaria();

    expect(await screen.findByRole("link", { name: "3º Ano A" })).toBeInTheDocument();
    expect(screen.getByText(DESCRICAO_SECRETARIA)).toBeInTheDocument();
    expect(screen.queryByText("Cadastre, edite e organize as turmas da escola.")).toBeNull();

    // Cabeçalho da página: sem criar, criar várias nem consolidar.
    expect(screen.queryByRole("button", { name: /Adicionar Turma/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Criar várias/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Corrigir duplicadas/ })).toBeNull();

    // Seleção em massa: nem o "selecionar todas" nem o checkbox da linha.
    expect(screen.queryByRole("checkbox", { name: "Selecionar todas as turmas visíveis" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Selecionar turma 3º Ano A" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Excluir selecionadas/ })).toBeNull();

    // Ações da linha (editar, arquivar, excluir) e a coluna delas.
    expect(screen.queryByRole("button", { name: "Editar turma 3º Ano A" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Arquivar turma 3º Ano A" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Excluir turma 3º Ano A" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Ações" })).toBeNull();

    // O indicador não manda a Secretaria a um "Editar" que ela não tem.
    expect(screen.getByText("Turmas ativas ainda sem titular")).toBeInTheDocument();
    expect(screen.queryByText("Defina o titular em “Editar”")).toBeNull();

    // Consultar continua: o interruptor de arquivadas/outros anos é só leitura.
    expect(
      screen.getByRole("switch", { name: "Mostrar turmas arquivadas e de outros anos letivos" }),
    ).toBeInTheDocument();
  });

  it("Secretaria numa escola sem turmas não é mandada ao “Adicionar Turma”", async () => {
    semear([]);
    await montarComoSecretaria();

    expect(await screen.findByText("Nenhuma turma cadastrada")).toBeInTheDocument();
    expect(screen.getByText("Esta escola ainda não cadastrou turmas.")).toBeInTheDocument();
    expect(screen.queryByText(/Use o botão “Adicionar Turma”/)).toBeNull();
  });

  it("coordenador continua com todos os controles de escrita", async () => {
    semear();
    const u = userEvent.setup();
    renderComApp(<Turmas />, { rota: "/turmas" });

    expect(await screen.findByRole("link", { name: "3º Ano A" })).toBeInTheDocument();
    expect(screen.getByText("Cadastre, edite e organize as turmas da escola.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Adicionar Turma/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Criar várias/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Corrigir duplicadas/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Ações" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar turma 3º Ano A" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Arquivar turma 3º Ano A" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Excluir turma 3º Ano A" })).toBeInTheDocument();
    expect(screen.getByText("Defina o titular em “Editar”")).toBeInTheDocument();

    // A seleção em massa continua: marcar a linha abre a barra de exclusão.
    expect(screen.getByRole("checkbox", { name: "Selecionar todas as turmas visíveis" })).toBeInTheDocument();
    await u.click(screen.getByRole("checkbox", { name: "Selecionar turma 3º Ano A" }));
    expect(screen.getByRole("button", { name: /Excluir selecionadas/ })).toBeInTheDocument();
  });

  it("coordenador numa escola sem turmas é orientado a criar a primeira", async () => {
    semear([]);
    renderComApp(<Turmas />, { rota: "/turmas" });

    expect(await screen.findByText("Nenhuma turma cadastrada")).toBeInTheDocument();
    expect(
      screen.getByText("Use o botão “Adicionar Turma” (ou “Criar várias”) para criar a primeira."),
    ).toBeInTheDocument();
  });
});
