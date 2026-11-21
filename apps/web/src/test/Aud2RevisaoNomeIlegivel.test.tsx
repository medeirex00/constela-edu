/**
 * PEND-55 (REV-IMP-1) — pendência cujo nome recebido tem letra ilegível ("�", acento
 * perdido no arquivo): "Criar novo aluno" não é oferecido.
 *
 * O backend recusa (400) criar a ficha com o "�" no nome — ela nasceria assim no
 * certificado e no ranking. A gaveta deixava escolher a turma e clicar, e o gestor só
 * descobria a recusa depois. Agora o bloco explica o caminho: cadastrar a criança em
 * Alunos com o nome certo e escolhê-la nesta pendência. Vincular a uma ficha
 * existente continua disponível. Dados fictícios (a fila é a REAL de
 * backend/tests/test_aud_impweb_revisoes_outra_conta.py, com o nome trocado).
 */
import { describe, expect, it } from "vitest";

import RevisoesIdentidade from "../pages/RevisoesIdentidade";
import type { RevisaoIdentidade } from "../pages/RevisoesIdentidade";
import semContaFila from "./fixtures/importacoes/previa_da_tela/revisoes_sofia_fila.json";
import { renderComApp, responder, screen, turmaFake, userEvent, within } from "./utils";

const BASE = "/escolas/1/importacoes/revisoes";

function mockar(nome: string) {
  const lista = (JSON.parse(JSON.stringify(semContaFila)) as RevisaoIdentidade[]).map((r) => ({
    ...r, nome_recebido: nome, nome_ficha_nova: nome, nome_ficha_nova_por_turma: {},
  }));
  responder("GET", (c) => c.startsWith(BASE) && !/\/revisoes\/\d+/.test(c), () => lista);
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "3º Ano A" })]);
  responder("GET", (c) => c.includes("/importacoes/identidades/"), []);
}

async function blocoCriar(nome: string) {
  mockar(nome);
  const u = userEvent.setup();
  renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
  const [botao] = await screen.findAllByRole("button", { name: `Ver revisão de ${nome}` });
  await u.click(botao);
  const dialogo = await screen.findByRole("dialog", { name: "Revisão de identidade" });
  return within(dialogo).getByRole("region", { name: "Criar novo aluno" });
}

describe("Revisões — nome recebido com letra ilegível", () => {
  it("não oferece 'Criar novo aluno' e diz o caminho que funciona", async () => {
    const bloco = await blocoCriar("Sof�a Almeida Duarte");
    expect(within(bloco).queryByRole("button", { name: /Criar novo aluno/ })).toBeNull();
    expect(within(bloco).queryByRole("combobox", { name: "Turma da ficha nova" })).toBeNull();
    expect(bloco).toHaveTextContent(
      "O nome recebido tem letra ilegível (“�”, acento perdido no arquivo) e a ficha nova "
      + "nasceria com ela. Cadastre a criança em Alunos com o nome certo e escolha-a nesta "
      + "pendência.");
  });

  it("nome legível continua com 'Criar novo aluno'", async () => {
    const bloco = await blocoCriar("Sofia Almeida Duarte");
    expect(within(bloco).getByRole("button", { name: /Criar novo aluno/ })).toBeInTheDocument();
    expect(bloco).not.toHaveTextContent("letra ilegível");
  });
});
