/**
 * Gestão de redes — código IBGE do município da rede (revisão REV3-INDIC-4). O cadastro
 * recusa com 409 o código que já é de outra rede e manda "tirar o código da outra rede";
 * só que nenhuma tela trocava nem limpava o código de uma rede que já tinha um (o campo do
 * ICA só aparece sem código e exige 7 dígitos). Uma rede com o código de outra cidade
 * travava a rede certa sem saída pela tela. Agora a Gestão de redes edita e limpa o código
 * da rede escolhida, mostrando a recusa do backend.
 *
 * Redes, nomes e códigos FICTÍCIOS (o município 3599999 não existe).
 */
import { describe, expect, it } from "vitest";

import RedeGestao from "../pages/rede/RedeGestao";
import { api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake } from "./utils";

const adminGlobal = usuarioFake({ nome: "Admin Global", cargo: "admin", is_global: true, escola_id: null });
const ROTULO = "Código IBGE do município (7 dígitos)";

function semear(codigo_ibge: string | null) {
  responder("GET", "/redes/gerenciar", {
    redes: [{ id: 1, nome: "Rede Inventada Norte", uf: "SP", codigo_ibge, status: "ativa" },
            { id: 2, nome: "Rede Inventada Sul", uf: "SP", codigo_ibge: null, status: "ativa" }],
    escolas: [], usuarios: [],
  });
  responder("GET", "/redes/1/modulos", []);
}

function patchesDaRede() {
  return api.mock.calls
    .filter(([caminho, opcoes]) =>
      caminho === "/redes/1" && (opcoes as RequestInit | undefined)?.method === "PATCH")
    .map(([, opcoes]) => JSON.parse(String((opcoes as RequestInit).body)));
}

async function abrir() {
  const u = userEvent.setup();
  renderComApp(<RedeGestao />, { usuario: adminGlobal });
  const campo = await screen.findByLabelText(ROTULO);
  return { u, campo: campo as HTMLInputElement };
}

describe("Gestão de redes — o código IBGE da rede se corrige e se tira pela tela", () => {
  it("mostra o código da rede escolhida e o tira (vazio) com PATCH codigo_ibge \"\"", async () => {
    semear("3599999");
    responder("PATCH", "/redes/1", { id: 1, nome: "Rede Inventada Norte", uf: "SP", codigo_ibge: null, status: "ativa" });
    const { u, campo } = await abrir();
    expect(campo.value).toBe("3599999");
    await u.clear(campo);
    await u.click(screen.getByRole("button", { name: /Tirar o código IBGE/ }));
    expect(await screen.findByText(/Código IBGE tirado da rede “Rede Inventada Norte”/)).toBeInTheDocument();
    expect(patchesDaRede()).toEqual([{ codigo_ibge: "" }]);
  });

  it("troca o código e mostra a recusa (409) do backend, palavra por palavra", async () => {
    semear("3599998");
    const recusa = "O código IBGE 3599999 já é da rede “Rede Inventada Sul” (id 2). Cada rede tem o seu "
      + "município: confira o código ou, em Gestão de redes, tire-o primeiro da outra rede. Nada foi alterado.";
    responderErro("PATCH", "/redes/1", 409, recusa);
    const { u, campo } = await abrir();
    await u.clear(campo);
    await u.type(campo, "3599999");
    await u.click(screen.getByRole("button", { name: /Salvar código IBGE/ }));
    expect(await screen.findByText(recusa)).toBeInTheDocument();
    expect(patchesDaRede()).toEqual([{ codigo_ibge: "3599999" }]);
    expect(campo.value).toBe("3599999");        // o que foi digitado fica para corrigir
  });

  it("código sem 7 dígitos não vai ao backend", async () => {
    semear(null);
    const { u, campo } = await abrir();
    await u.type(campo, "35999");
    expect(screen.getByRole("button", { name: /Salvar código IBGE/ })).toBeDisabled();
    expect(patchesDaRede()).toEqual([]);
  });
});
