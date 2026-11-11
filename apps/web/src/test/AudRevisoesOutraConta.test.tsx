/**
 * Auditoria (Revisões de identidade): "outra conta leva ao mesmo aluno" não afirma que a
 * ficha já tem outra conta; "conta com nomes ou números diferentes" não afirma que a
 * conta veio em mais de uma linha.
 *
 * IMPORTACAO-11 / REVERIFICACAO-2: o motivo ``outra_identidade_na_plataforma`` nasce por
 * três caminhos — a ficha já tem outra conta; outra conta do mesmo relatório leva a ela;
 * uma conta numa pendência leva a ela. Com a Sofia SEM conta nenhuma, a gaveta dizia
 * "Duas contas na mesma ficha", "O aluno encontrado já tem outra conta nesta plataforma"
 * e "Atenção: esta ficha tem duas contas no Matific" — o gestor procurava uma conta que
 * não existe. ``id_externo_duplicado`` dizia "Conta repetida no relatório" / "veio em
 * mais de uma linha" com a disputa vinda de um relatório anterior.
 *
 * As respostas são as REAIS (/revisoes e /identidades), gravadas por
 * backend/tests/test_aud_impweb_revisoes_outra_conta.py. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import RevisoesIdentidade from "../pages/RevisoesIdentidade";
import type { RevisaoIdentidade } from "../pages/RevisoesIdentidade";
import dupFila from "./fixtures/importacoes/previa_da_tela/revisoes_dup_fila.json";
import comContaContas from "./fixtures/importacoes/previa_da_tela/revisoes_sofia_com_conta_contas.json";
import comContaFila from "./fixtures/importacoes/previa_da_tela/revisoes_sofia_com_conta_fila.json";
import semContaContas from "./fixtures/importacoes/previa_da_tela/revisoes_sofia_contas.json";
import semContaFila from "./fixtures/importacoes/previa_da_tela/revisoes_sofia_fila.json";
import { api, renderComApp, responder, screen, turmaFake, userEvent, waitFor, within } from "./utils";

const BASE = "/escolas/1/importacoes/revisoes";
const CONTAS_DA_SOFIA = "/escolas/1/importacoes/identidades/matific/aluno/3";
const AVISO = "Atenção: duas contas da mesma plataforma";

const copia = <T,>(valor: unknown) => JSON.parse(JSON.stringify(valor)) as T;

function mockar(fila: unknown, contas?: unknown) {
  const lista = copia<RevisaoIdentidade[]>(fila);
  responder("GET", (c) => c.startsWith(BASE) && !/\/revisoes\/\d+/.test(c), () => lista);
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "3º Ano A" })]);
  if (contas !== undefined) responder("GET", CONTAS_DA_SOFIA, copia(contas));
}

async function abrir(nome: string) {
  const u = userEvent.setup();
  renderComApp(<RevisoesIdentidade />, { rota: "/revisoes-identidade" });
  const [botao] = await screen.findAllByRole("button", { name: `Ver revisão de ${nome}` });
  await u.click(botao);
  return screen.findByRole("dialog", { name: "Revisão de identidade" });
}

/** Espera a consulta das contas da ficha responder (o aviso depende dela). */
async function contasCarregadas() {
  await waitFor(() => expect(api.mock.calls.some(([c]) => c === CONTAS_DA_SOFIA)).toBe(true));
  await waitFor(() => expect(screen.queryByText("Carregando as contas…")).toBeNull());
}

describe("Revisões — outra conta leva ao mesmo aluno, com a ficha SEM conta", () => {
  it("o filtro, a orientação e a gaveta não dizem que a ficha já tem outra conta", async () => {
    expect(semContaContas).toEqual([]);
    mockar(semContaFila, semContaContas);
    const dialogo = await abrir("Sofia Almeida Duarte");
    await contasCarregadas();

    expect(screen.getByRole("option", { name: "Outra conta leva ao mesmo aluno (2)" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Duas contas na mesma ficha/ })).toBeNull();
    const identidade = within(dialogo).getByRole("region", { name: "Identidade recebida" });
    expect(identidade).toHaveTextContent(
      "Outra conta da plataforma também leva a este aluno: já vinculada à ficha, vinda no mesmo "
      + "relatório ou esperando em outra pendência desta lista.");
    expect(within(dialogo).queryByRole("note", { name: AVISO })).toBeNull();
    expect(dialogo.textContent).not.toMatch(/já tem outra conta|tem duas contas/);
  });
});

describe("Revisões — outra conta leva ao mesmo aluno, com a ficha que JÁ tem conta", () => {
  it("aí o aviso de duas contas aparece", async () => {
    mockar(comContaFila, comContaContas);
    const dialogo = await abrir("Sofia Almeida Duarte");
    const aviso = await within(dialogo).findByRole("note", { name: AVISO });
    expect(within(aviso).getByText(/esta ficha tem duas contas no Matific/i)).toBeInTheDocument();
  });

  it("sem conseguir consultar as contas da ficha, o aviso não afirma nada", async () => {
    mockar(comContaFila);   // GET das contas sem resposta (falha)
    const dialogo = await abrir("Sofia Almeida Duarte");
    await contasCarregadas();
    expect(within(dialogo).queryByRole("note", { name: AVISO })).toBeNull();
  });
});

describe("Revisões — a mesma conta com nomes ou números diferentes", () => {
  it("vinda de um relatório anterior: nem o filtro nem a orientação dizem 'no relatório'", async () => {
    mockar(dupFila);
    const dialogo = await abrir("Crianca Ficticia Um");
    expect(screen.getByRole("option", { name: "Conta com nomes ou números diferentes (2)" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Conta repetida no relatório/ })).toBeNull();
    // A orientação da tela (o "Motivo:" logo acima é o texto do backend, que já diz
    // "ou já há uma pendência assim aberta para ele").
    const orientacao = within(dialogo).getByText(/^A mesma conta da plataforma veio/);
    expect(orientacao.textContent).toMatch(
      /^A mesma conta da plataforma veio com nomes ou números diferentes — neste relatório ou num anterior que ainda espera aqui\./);
    expect(orientacao.textContent).not.toMatch(/em mais de uma linha/);
  });
});
