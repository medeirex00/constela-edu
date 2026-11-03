/**
 * Professores (pages/ListasSimples → Professores): a Secretaria só consulta. O
 * backend recusa com 403 o POST/PATCH/DELETE por-escola dela
 * (deps.escola_autorizada); a tela já esconde os controles (`podeEditar`). Este
 * arquivo trava o que o RbacSecretaria.test ainda não cobria: o botão de excluir,
 * a coluna de ações e a orientação do estado vazio. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { Professores } from "../pages/ListasSimples";
import { api, renderComApp, responder, screen, usuarioFake, waitFor } from "./utils";

const URL_PROFESSORES = "/escolas/1/professores";
const secretaria = usuarioFake({ rede_id: 7 });

/** Monta como Secretaria e espera o estado ESTÁVEL: ela abre a sessão em "Toda a
 *  Rede" (escolaId nulo) e a escola é reaplicada no contexto, com nova busca da
 *  equipe. Sem esperar essa 2ª busca, um elemento achado na 1ª renderização
 *  (antes do /auth/me) sai do DOM logo depois. */
async function montarComoSecretaria() {
  renderComApp(<Professores />, { usuario: secretaria, escolaSelecionada: 1 });
  await waitFor(() =>
    expect(api.mock.calls.filter(([c]) => String(c) === URL_PROFESSORES).length)
      .toBeGreaterThanOrEqual(2));
}

function semear(professores = [{ id: 1, nome: "Prof Ana", email: null, observacoes: null }]) {
  responder("GET", URL_PROFESSORES, professores);
  responder("GET", "/escolas/1/turmas", []);
}

describe("Professores: Secretaria só consulta", () => {
  it("coordenador vê editar, excluir e a coluna de ações", async () => {
    semear();
    renderComApp(<Professores />);

    expect(await screen.findByText("Prof Ana")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Ações" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar nome e e-mail de Prof Ana" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Excluir Prof Ana" })).toBeInTheDocument();
  });

  it("Secretaria vê a equipe, sem editar, excluir nem a coluna de ações", async () => {
    semear();
    await montarComoSecretaria();

    expect(await screen.findByText("Prof Ana")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Adicionar professor/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Ações" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Editar nome e e-mail de Prof Ana" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Excluir Prof Ana" })).toBeNull();
  });

  it("lista vazia: o coordenador é orientado a adicionar o primeiro", async () => {
    semear([]);
    renderComApp(<Professores />);
    expect(await screen.findByText("Nenhum professor cadastrado")).toBeInTheDocument();
    expect(screen.getByText("Use “Adicionar professor” para cadastrar o primeiro.")).toBeInTheDocument();
  });

  it("lista vazia: a Secretaria não é mandada a um “Adicionar professor” que não tem", async () => {
    semear([]);
    await montarComoSecretaria();
    expect(await screen.findByText("Nenhum professor cadastrado")).toBeInTheDocument();
    expect(screen.queryByText("Use “Adicionar professor” para cadastrar o primeiro.")).toBeNull();
  });
});
