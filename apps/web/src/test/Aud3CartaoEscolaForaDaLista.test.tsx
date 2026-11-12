/**
 * O cartão da escola no topo do menu diz o NOME da escola aberta fora da lista da sessão
 * (S_G_VIRADA-5, costura da fase D).
 *
 * O GET /escolas da sessão só traz as ativas. Quando o Admin Global abre uma escola
 * inativa (Escolas › Usuários › “Gestão completa”), o AppContext agora (a1484af2) busca
 * a escola aberta com as inativas e preenche `escolaAtual` — Turmas e Configurações já
 * mostravam o nome e o ano dela. O cartão do topo ainda procurava só na lista e dizia
 * “Escola nº 2 (fora da lista)”. Sem conseguir buscar a escola, o rótulo de antes fica.
 * Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import {
  autenticar, escolaFake, renderComApp, responder, responderErro, screen, usuarioFake, waitFor,
  within,
} from "./utils";

const GLOBAL = usuarioFake({
  id: 11, nome: "Raiz Ficticia", cargo: "admin", is_global: true, escola_id: null,
});
const ATIVA = escolaFake({ id: 1, nome: "Escola Ficticia Aberta", ano_letivo_ativo: 2026 });
const INATIVA = escolaFake({
  id: 2, nome: "Escola Ficticia Inativa", ano_letivo_ativo: 2026, status: "inativa",
});

/** A sessão lista só a escola ativa; ``listaComInativas`` responde ao pedido com as
 *  inativas (registrado depois de /escolas, como o AppContext o faz). */
async function montar(listaComInativas: () => void) {
  autenticar(GLOBAL, [ATIVA]);
  listaComInativas();
  for (const id of [1, 2]) {
    responder("GET", `/escolas/${id}/sync/onboarding`, { lista_piloto_importada: true });
  }
  renderComApp(
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>,
    { rota: "/", autenticado: false, escolaSelecionada: 2 },
  );
  await screen.findAllByText(GLOBAL.nome);
}

const seletor = () => screen.getByRole("combobox", { name: "Escola selecionada" });

describe("Cartão da escola com a escola aberta fora da lista da sessão", () => {
  it("Admin Global com uma escola inativa aberta: o cartão diz o nome dela", async () => {
    await montar(() => responder("GET", /incluir_inativas=true/, [ATIVA, INATIVA]));

    await waitFor(() =>
      expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent("Escola Ficticia Inativa"));
    expect(screen.getByTestId("cartao-escola-nome")).not.toHaveTextContent(/fora da lista/);
    // O <select> continua com a escola aberta escolhida, pelo nome.
    expect(seletor()).toHaveValue("2");
    expect(within(seletor()).getByRole("option", { name: "Escola Ficticia Inativa" }))
      .toBeInTheDocument();
    expect(within(seletor()).queryByRole("option", { name: /fora da lista/ })).toBeNull();
    // A escola da lista continua lá uma vez só.
    expect(within(seletor()).getAllByRole("option", { name: "Escola Ficticia Aberta" }))
      .toHaveLength(1);
  });

  it("sem conseguir buscar a escola fora da lista, o cartão diz o número (nada é suposto)", async () => {
    await montar(() => responderErro("GET", /incluir_inativas=true/, 500, "Erro interno"));

    await waitFor(() =>
      expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent("Escola nº 2 (fora da lista)"));
    expect(seletor()).toHaveValue("2");
  });
});
