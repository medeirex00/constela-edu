/**
 * Gestão de redes — código INEP digitado (auditoria S_G_INDICADORES-4). O código INEP
 * tem 8 dígitos: o que tem um dígito a mais ou a menos, ou uma letra, não é enviado (o
 * backend também o recusa com 400) e aparece como erro com o nome da escola — antes, a
 * tela dizia "salvo" e o backend gravava OUTRO código (cortado ou completado com zeros)
 * ou apagava o que a escola tinha. Depois de salvar, o campo mostra o código GRAVADO.
 *
 * Escolas, nomes e códigos FICTÍCIOS.
 */
import { describe, expect, it } from "vitest";

import RedeGestao from "../pages/rede/RedeGestao";
import { api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake } from "./utils";

const adminGlobal = usuarioFake({ nome: "Admin Global", cargo: "admin", is_global: true, escola_id: null });

function escola(id: number, nome: string, codigo_inep: string | null) {
  return { id, nome, cidade: null, estado: null, bairro: null, status: "ativa", rede_id: 1,
           latitude: null, longitude: null, codigo_inep };
}

function semearRede(escolas: ReturnType<typeof escola>[]) {
  responder("GET", "/redes/gerenciar", {
    redes: [{ id: 1, nome: "Rede Inventada", uf: "SP", codigo_ibge: null, status: "ativa" }],
    escolas, usuarios: [],
  });
  responder("GET", "/redes/1/modulos", []);
}

function patchesDe(id: number) {
  return api.mock.calls.filter(([caminho, opcoes]) =>
    caminho === `/redes/escolas/${id}` && (opcoes as RequestInit | undefined)?.method === "PATCH");
}

describe("Gestão de redes — o código INEP tem 8 dígitos", () => {
  it("um dígito a mais, uma letra ou um texto não vão ao backend e viram erro com o nome da escola", async () => {
    semearRede([escola(11, "EMEF Inventada Alfa", "35990001"), escola(12, "EMEF Inventada Beta", null),
                escola(13, "EMEF Inventada Gama", null), escola(14, "EMEF Inventada Delta", null)]);
    responder("PATCH", "/redes/escolas/14", { id: 14, codigo_inep: "35990004" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByDisplayValue("35990001");
    const [alfa, beta, gama, delta] = screen.getAllByPlaceholderText("código INEP");
    await u.clear(alfa);
    await u.type(alfa, "INEP?");
    await u.type(beta, "350123456");
    await u.type(gama, "3501234S");
    await u.type(delta, "35990004");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));

    expect(await screen.findByText(/1 código\(s\) salvo\(s\); 3 com erro:/)).toBeInTheDocument();
    const detalhes = screen.getByTestId("aviso-detalhes");
    for (const nome of ["EMEF Inventada Alfa", "EMEF Inventada Beta", "EMEF Inventada Gama"]) {
      expect(detalhes).toHaveTextContent(`${nome}: o código INEP tem 8 dígitos`);
    }
    expect(detalhes).not.toHaveTextContent("EMEF Inventada Delta:");
    expect(patchesDe(11)).toHaveLength(0);       // o código da Alfa NÃO é apagado
    expect(patchesDe(12)).toHaveLength(0);
    expect(patchesDe(13)).toHaveLength(0);
    expect(patchesDe(14)).toHaveLength(1);
  });

  it("a recusa do backend aparece com a mensagem dele", async () => {
    semearRede([escola(11, "EMEF Inventada Alfa", null)]);
    responderErro("PATCH", "/redes/escolas/11", 400,
      "O código INEP da escola tem 8 dígitos, só números (ex.: 35012345): confira o código digitado. Nada foi alterado.");
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByText("Códigos INEP das escolas");
    await u.type(screen.getByPlaceholderText("código INEP"), "35990001");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText(/0 código\(s\) salvo\(s\); 1 com erro:/)).toBeInTheDocument();
    expect(screen.getByTestId("aviso-detalhes")).toHaveTextContent(
      "EMEF Inventada Alfa: O código INEP da escola tem 8 dígitos");
  });

  it("depois de salvar, o campo mostra o código gravado (o '0' à esquerda do cadastro antigo sai)", async () => {
    semearRede([escola(11, "EMEF Inventada Alfa", null)]);
    responder("PATCH", "/redes/escolas/11", { id: 11, codigo_inep: "35990001" });
    const u = userEvent.setup();
    renderComApp(<RedeGestao />, { usuario: adminGlobal });
    await screen.findByText("Códigos INEP das escolas");
    const campo = screen.getByPlaceholderText("código INEP");
    await u.type(campo, "035990001");
    await u.click(screen.getByRole("button", { name: /Salvar códigos/ }));
    expect(await screen.findByText("1 código(s) salvo(s).")).toBeInTheDocument();
    expect(campo).toHaveValue("35990001");
  });
});
