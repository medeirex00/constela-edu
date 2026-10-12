/**
 * Configurações Gerais (cor primária, brasão da cidade, logos, dados da escola,
 * backup, IA) é do ADMINISTRADOR. A coordenação não vê o item no menu, não abre a
 * rota (RotaAdmin a manda ao Dashboard) e Alt+0 não a leva até lá — e continua
 * editando as medalhas por "Gamificação → Editar conquistas". O backend é a trava
 * real (tests/test_coordenador_sem_config_institucional.py); aqui é a interface.
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { RotaAdmin } from "../App";
import { useApp } from "../context/AppContext";
import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { destinosDoTeclado } from "../lib/atalhos";
import { escolaFake, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

function LayoutReal() {
  return (
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>
  );
}

function escolaConfigurada() {
  responder("GET", "/escolas/1/sync/status", {
    escola_id: 1, escola_nome: "Escola Modelo Constela", qtd_alunos: 30, qtd_turmas: 3,
    plataformas: [], lista_piloto_importada: true, integracao_configurada: true,
  });
}

const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
const adminEscola = usuarioFake({ is_global: false, cargo: "admin", nome: "Admin Local" });
const global = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });

describe("Menu — Configurações Gerais só para o administrador", () => {
  it("coordenação: sem Configurações Gerais, com Editar conquistas e Pontuação", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    expect((await screen.findAllByRole("link", { name: "Pontuação" })).length).toBeGreaterThan(0);
    const editar = await screen.findAllByRole("link", { name: "Editar conquistas" });
    expect(editar[0]).toHaveAttribute("href", "/configuracoes/conquistas");
    expect(screen.queryAllByRole("link", { name: "Configurações Gerais" })).toHaveLength(0);
  });

  it.each([["admin da escola", adminEscola], ["Admin Global", global]])(
    "%s: vê Configurações Gerais (e edita as medalhas por lá)", async (_rotulo, usuario) => {
      escolaConfigurada();
      renderComApp(<LayoutReal />, { usuario, escolas: [escolaFake({ id: 1 })] });
      expect((await screen.findAllByRole("link", { name: "Configurações Gerais" })).length)
        .toBeGreaterThan(0);
      expect(screen.queryAllByRole("link", { name: "Editar conquistas" })).toHaveLength(0);
    });

  it("o Suporte do menu abre a página interna /suporte, para todos os perfis", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    const suporte = await screen.findAllByRole("link", { name: "Suporte" });
    expect(suporte[0]).toHaveAttribute("href", "/suporte");
    expect(suporte[0]).not.toHaveAttribute("target");
  });
});

/** Como no app: as guardas só rodam com a sessão aberta (o Layout espera o
 *  usuário). Sem isto, o 1º render — ainda sem usuário — redirecionaria todo
 *  mundo e o teste da coordenação passaria por acaso. */
function RotasDeTeste() {
  const { usuario } = useApp();
  if (!usuario) return <p>Abrindo a sessão</p>;
  return (
    <Routes>
      <Route path="/" element={<p>Tela inicial</p>} />
      <Route path="/configuracoes" element={<RotaAdmin><p>Tela de Configurações Gerais</p></RotaAdmin>} />
    </Routes>
  );
}

describe("Rota /configuracoes (RotaAdmin)", () => {
  it("coordenação que digita a URL vai para o Dashboard", async () => {
    renderComApp(<RotasDeTeste />, { rota: "/configuracoes", usuario: coordenadora });
    expect(await screen.findByText("Tela inicial")).toBeInTheDocument();
    expect(screen.queryByText("Tela de Configurações Gerais")).toBeNull();
  });

  it("Secretaria (rede vinculada) também não opera a escola por aqui", async () => {
    renderComApp(<RotasDeTeste />, {
      rota: "/configuracoes", usuario: usuarioFake({ cargo: "admin", rede_id: 7 }),
    });
    expect(await screen.findByText("Tela inicial")).toBeInTheDocument();
  });

  it.each([["admin da escola", adminEscola], ["Admin Global", global]])(
    "%s abre a tela", async (_rotulo, usuario) => {
      renderComApp(<RotasDeTeste />, { rota: "/configuracoes", usuario });
      expect(await screen.findByText("Tela de Configurações Gerais")).toBeInTheDocument();
    });
});

describe("Atalho Alt+0", () => {
  it("só leva a Configurações Gerais quem pode abri-la", () => {
    expect(destinosDoTeclado(true)["0"]).toBe("/configuracoes");
    expect(destinosDoTeclado(false)["0"]).toBeUndefined();
    // As demais teclas continuam iguais para todos.
    expect(destinosDoTeclado(false)["1"]).toBe("/");
  });
});

describe("Notificação de backup (aponta para Configurações Gerais)", () => {
  const backup = {
    id: 9, tipo: "backup.gerado", severidade: "info", titulo: "Backup gerado",
    rota: "/configuracoes", lida: false, autor: "Admin", data: "2026-10-10T10:00:00",
  };

  it.each([
    ["coordenação: sem link (antes caía calada no Dashboard)", coordenadora, true],
    ["admin da escola: abre Configurações Gerais", adminEscola, false],
  ])("%s", async (_rotulo, usuario, semLink) => {
    escolaConfigurada();
    responder("GET", "/notificacoes/contador", { nao_lidas: 1 });
    responder("GET", "/notificacoes", [backup]);
    responder("POST", "/notificacoes/marcar-lidas", {});
    renderComApp(<LayoutReal />, { usuario, escolas: [escolaFake({ id: 1 })] });
    await userEvent.click(await screen.findByRole("button", { name: /Notificações/ }));
    const item = (await screen.findByText("Backup gerado")).closest("button");
    expect(item).not.toBeNull();
    if (semLink) expect(item).toBeDisabled();
    else expect(item).toBeEnabled();
  });
});
