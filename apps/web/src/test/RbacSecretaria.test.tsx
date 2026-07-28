/**
 * Secretaria (rede vinculada, não-global) é SOMENTE LEITURA: não vê os controles
 * de escrita (editar professor, transferir/editar aluno). O coordenador da própria
 * escola (sem rede_id) continua vendo tudo. O backend também barra — aqui travamos
 * o lado do frontend para não mostrar controle que depois daria 403.
 */
import { describe, expect, it, vi } from "vitest";

import AcoesAluno from "../components/AcoesAluno";
import { Professores } from "../pages/ListasSimples";
import type { Aluno } from "../lib/types";
import { renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const aluno: Aluno = {
  id: 10, nome: "Ana Souza", foto_url: null, numero_chamada: 1,
  status: "ativo", turma: "3º Ano A", ano_escolar: "3º Ano",
  data_nascimento: null, observacoes: null,
};
const secretaria = usuarioFake({ rede_id: 7 });

function semearProfessores() {
  responder("GET", "/escolas/1/professores",
    [{ id: 1, nome: "Prof Ana", email: null, observacoes: null }]);
  responder("GET", "/escolas/1/turmas", []);
}

describe("Secretaria é somente leitura", () => {
  it("AcoesAluno: coordenador vê 'Editar dados'", async () => {
    renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />);
    await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
    expect(await screen.findByText("Editar dados")).toBeInTheDocument();
  });

  it("AcoesAluno: Secretaria vê só 'Visualizar' (sem editar/transferir/excluir)", async () => {
    renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />, { usuario: secretaria });
    await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
    expect(await screen.findByText("Visualizar")).toBeInTheDocument();
    expect(screen.queryByText("Editar dados")).toBeNull();
    expect(screen.queryByText("Fundir com outro aluno")).toBeNull();
    expect(screen.queryByText("Excluir")).toBeNull();
  });

  it("Professores: coordenador vê 'Adicionar professor' e o lápis de editar nome", async () => {
    semearProfessores();
    renderComApp(<Professores />);
    expect(await screen.findByText("Prof Ana")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Adicionar professor/ })).toBeInTheDocument();
    expect(screen.getByTitle("Editar nome")).toBeInTheDocument();
  });

  it("Professores: Secretaria não vê 'Adicionar professor' nem o lápis", async () => {
    semearProfessores();
    renderComApp(<Professores />, { usuario: secretaria });
    expect(await screen.findByText("Prof Ana")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Adicionar professor/ })).toBeNull();
    expect(screen.queryByTitle("Editar nome")).toBeNull();
  });
});
