/**
 * "/" da Secretaria é SEMPRE o Panorama da Rede (DESENHO3 §1), com "Toda a Rede Municipal"
 * ou com uma escola escolhida no cartão Contexto: escolher uma escola leva à FICHA dela
 * (/rede/escolas/{id}, no Layout) — o antigo "Panorama Geral da <Escola>" (com o atalho
 * "‹ Toda a Rede Municipal") saiu.
 *
 * Renderiza o Dashboard (o despachante). O Panorama em si tem os testes dele
 * (SecretariaPanorama.test.tsx): aqui ele vira um marcador, e o teste confere QUAL tela o
 * despachante abre em cada contexto.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("../pages/rede/secretaria/PanoramaSecretaria", () => ({
  default: () => <h1>Panorama da Rede</h1>,
}));

import { useApp } from "../context/AppContext";
import Dashboard from "../pages/Dashboard";
import { escolaFake, renderComApp, screen, usuarioFake, waitFor } from "./utils";

const secretaria = usuarioFake({ rede_id: 7, cargo: "coordenador" });
const escolas = [
  escolaFake({ id: 1, nome: "EMEF Fictícia Aurora" }),
  escolaFake({ id: 2, nome: "EMEF Escola B" }),
];

/** O contexto escolhido (o mesmo que o cartão Contexto grava). */
function Contexto() {
  const { escolaId, usuario } = useApp();
  return <p data-testid="contexto">{usuario ? (escolaId ?? "rede") : "sem sessão"}</p>;
}

describe("Dashboard da Secretaria: sempre o Panorama da Rede", () => {
  it("com 'Toda a Rede Municipal' (o padrão): o Panorama da Rede", async () => {
    renderComApp(<><Dashboard /><Contexto /></>, { usuario: secretaria, escolas });

    await waitFor(() => expect(screen.getByTestId("contexto")).toHaveTextContent("rede"));
    expect(await screen.findByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeInTheDocument();
  });

  it("com uma escola no contexto: continua o Panorama da Rede — nada do panorama de uma escola só", async () => {
    renderComApp(<><Dashboard /><Contexto /></>, { usuario: secretaria, escolas, escolaSelecionada: 1 });

    await waitFor(() => expect(screen.getByTestId("contexto")).toHaveTextContent("1"));
    expect(await screen.findByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeInTheDocument();
    expect(screen.queryByText(/Panorama Geral da/)).toBeNull();
    expect(screen.queryByText("EMEF Fictícia Aurora")).toBeNull();
    expect(screen.queryByRole("button", { name: /Toda a Rede Municipal/ })).toBeNull();
  });
});
