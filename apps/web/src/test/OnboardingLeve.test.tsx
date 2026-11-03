/**
 * A barra lateral NÃO paga o GET /sync/status (e97z, 27/10).
 *
 * O Layout decide o menu do primeiro acesso ("Comece aqui") pelo `useOnboarding`.
 * Ele buscava o /sync/status inteiro — o endpoint mais caro da API (~20 consultas,
 * segundos com o banco em outra região) — só para ler `lista_piloto_importada`, a
 * cada montagem da navegação, em qualquer tela. Agora lê o GET leve
 * `/escolas/{id}/sync/onboarding`; o /sync/status fica com a tela de Integrações
 * (e o "Comece aqui", que usa os demais campos dele). Nenhum handler de
 * /sync/status é registrado aqui: se o Layout o pedisse, a chamada apareceria
 * no mock (e cairia no 404).
 */
import { describe, expect, it } from "vitest";

import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { api, escolaFake, renderComApp, responder, screen, usuarioFake, waitFor } from "./utils";

/** O Layout real vive dentro do ImportacaoLoteProvider (App.tsx). */
function LayoutReal() {
  return (
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>
  );
}

const pediu = (trecho: string) =>
  api.mock.calls.some(([caminho]) => String(caminho).includes(trecho));

const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora Ficticia" });
const adminEscola = usuarioFake({ is_global: false, cargo: "admin", nome: "Admin Ficticio" });
const adminGlobal = usuarioFake({ is_global: true, cargo: "admin", nome: "Root Ficticio" });

describe("Barra lateral — onboarding pelo endpoint leve, sem /sync/status", () => {
  it.each([
    ["coordenação", coordenadora],
    ["administração da escola", adminEscola],
    ["Admin Global", adminGlobal],
  ])("%s, escola configurada: lê /sync/onboarding e nunca /sync/status", async (_perfil, usuario) => {
    responder("GET", "/escolas/1/sync/onboarding", { lista_piloto_importada: true });
    renderComApp(<LayoutReal />, { rota: "/", usuario, escolas: [escolaFake({ id: 1 })] });

    await screen.findAllByText(usuario.nome);
    await waitFor(() => expect(pediu("/escolas/1/sync/onboarding")).toBe(true));
    // Configurada: menu completo, sem o "Comece aqui".
    expect(await screen.findAllByText("Integrações")).not.toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Comece aqui" })).toHaveLength(0);
    expect(pediu("/sync/status")).toBe(false);
  });

  it("escola ainda sem Lista Piloto: o 'Comece aqui' vem do /sync/onboarding, sem /sync/status", async () => {
    responder("GET", "/escolas/1/sync/onboarding", { lista_piloto_importada: false });
    renderComApp(<LayoutReal />, { rota: "/", usuario: adminEscola, escolas: [escolaFake({ id: 1 })] });

    await screen.findAllByText("Comece aqui");
    expect(screen.queryAllByRole("link", { name: "Comece aqui" }).length).toBeGreaterThan(0);
    expect(pediu("/sync/status")).toBe(false);
  });

  it("Secretaria e professor não perguntam nada do onboarding", async () => {
    const secretaria = usuarioFake({ nome: "Secretaria Ficticia", cargo: "coordenador", rede_id: 1,
      escola_id: null });
    const professor = usuarioFake({ is_global: false, cargo: "professor", nome: "Professor Ficticio" });
    for (const usuario of [secretaria, professor]) {
      const { unmount } = renderComApp(<LayoutReal />, { rota: "/", usuario, escolas: [escolaFake({ id: 1 })] });
      await screen.findAllByText(usuario.nome);
      // Menu completo do perfil, nunca o do primeiro acesso (a escola já vem preparada).
      expect(screen.queryAllByRole("link", { name: "Comece aqui" })).toHaveLength(0);
      if (usuario === secretaria) {
        expect(screen.getAllByRole("link", { name: "Avaliações externas" }).length).toBeGreaterThan(0);
      }
      unmount();
    }
    expect(pediu("/sync/onboarding")).toBe(false);
    expect(pediu("/sync/status")).toBe(false);
  });
});
