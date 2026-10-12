/**
 * Avaliações externas: quem vê os controles de IMPORTAR e REMOVER.
 *
 * Decisão do dono: importar e excluir resultados oficiais (IDEB, SAEB...) é do
 * admin global e da Secretaria da rede (com cargo de gestão). A coordenação e a
 * administração de escola — e uma conta de rede com cargo de professor — só
 * consultam. O backend é a barreira (`deps.exigir_admin_global_ou_secretaria`);
 * aqui travamos o lado da tela para não oferecer um botão que daria 403, e para
 * dizer a quem não pode QUEM faz.
 */
import { describe, expect, it } from "vitest";

import { podeGravarAvaliacoes } from "../hooks/usePerfil";
import type { Usuario } from "../lib/types";
import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import { renderComApp, responder, screen, usuarioFake } from "./utils";

const SERIE = {
  avaliacao: "ideb", nome: "IDEB", tipo: "indicador", indicador: "ideb",
  etapa: "anos_iniciais", componente: null, edicoes: [2023],
};
const CORRELACAO = {
  nome: "IDEB", tipo: "indicador", indicador: "ideb", etapa: "anos_iniciais",
  componente: null, edicao: 2023, metrica: "pontuacao_geral",
  pontos: [], n: 0, pearson: null, evolucao: [],
};

function semearRede7() {
  responder("GET", "/redes", [{ id: 7, nome: "Rede Municipal" }]);
  responder("GET", "/redes/7/avaliacoes/opcoes", [SERIE]);
  responder("GET", "/redes/7/avaliacoes/correlacao", CORRELACAO);
  responder("GET", "/avaliacoes", [
    { chave: "ideb", nome: "IDEB", tipo: "indicador", orgao: "INEP", descricao: null },
  ]);
  responder("GET", "/avaliacoes/presets-import", [
    { chave: "ideb_ai", rotulo: "IDEB — Anos Iniciais", avaliacao: "ideb", dica: "" },
  ]);
  responder("GET", "/avaliacoes/fontes", []);
}

async function abrirComo(usuario: Usuario) {
  semearRede7();
  renderComApp(<RedeAvaliacoes />, { usuario });
  // A consulta (correlação) aparece para todos que chegam à tela.
  expect(await screen.findByText("Dispersão por escola")).toBeInTheDocument();
}

const AVISO = /Esta conta só consulta/;

function controlesDeEscrita() {
  return {
    umClique: screen.queryByRole("heading", { name: /Importar oficial em 1 clique/ }),
    mapeado: screen.queryByRole("heading", { name: /Importar resultado oficial/ }),
    remover: screen.queryByRole("button", { name: /Remover edição 2023/ }),
  };
}

describe("Avaliações externas — quem importa e remove", () => {
  it("Secretaria da rede (coordenador): vê importar e remover, sem o aviso", async () => {
    await abrirComo(usuarioFake({ rede_id: 7, escola_id: null, cargo: "coordenador" }));
    const c = controlesDeEscrita();
    expect(await screen.findByRole("heading", { name: /Importar oficial em 1 clique/ }))
      .toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /Importar resultado oficial/ }))
      .toBeInTheDocument();
    expect(c.remover).toBeInTheDocument();
    expect(screen.queryByText(AVISO)).toBeNull();
    // O robô (fontes automáticas) segue só do admin global.
    expect(screen.queryByRole("heading", { name: /Coleta automática/ })).toBeNull();
  });

  it("Admin global: vê importar, remover e o robô", async () => {
    await abrirComo(usuarioFake({ is_global: true, cargo: "admin" }));
    expect(await screen.findByRole("heading", { name: /Importar oficial em 1 clique/ }))
      .toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /Coleta automática/ }))
      .toBeInTheDocument();
    expect(controlesDeEscrita().remover).toBeInTheDocument();
    expect(screen.queryByText(AVISO)).toBeNull();
  });

  it("Coordenação de escola (sem rede): só consulta e lê quem importa", async () => {
    await abrirComo(usuarioFake({ cargo: "coordenador" }));
    const c = controlesDeEscrita();
    expect(c.umClique).toBeNull();
    expect(c.mapeado).toBeNull();
    expect(c.remover).toBeNull();
    const aviso = screen.getByText(AVISO);
    expect(aviso).toHaveTextContent("administrador global");
    expect(aviso).toHaveTextContent("Secretaria da rede");
  });

  it("Administração de escola (sem rede): também só consulta", async () => {
    await abrirComo(usuarioFake({ cargo: "admin" }));
    const c = controlesDeEscrita();
    expect(c.umClique).toBeNull();
    expect(c.mapeado).toBeNull();
    expect(c.remover).toBeNull();
    expect(screen.getByText(AVISO)).toBeInTheDocument();
  });

  it("Conta de rede com cargo de professor: só consulta", async () => {
    await abrirComo(usuarioFake({ rede_id: 7, escola_id: null, cargo: "professor" }));
    const c = controlesDeEscrita();
    expect(c.umClique).toBeNull();
    expect(c.remover).toBeNull();
    expect(screen.getByText(AVISO)).toBeInTheDocument();
  });
});

describe("podeGravarAvaliacoes (mesma regra do backend)", () => {
  it.each([
    ["admin global", { global: true, secretaria: false, gestor: true }, true],
    ["Secretaria com cargo de gestão", { global: false, secretaria: true, gestor: true }, true],
    ["Secretaria com cargo de professor", { global: false, secretaria: true, gestor: false }, false],
    ["coordenação/administração de escola", { global: false, secretaria: false, gestor: true }, false],
    ["professor de escola", { global: false, secretaria: false, gestor: false }, false],
  ])("%s → %s", (_rotulo, perfil, esperado) => {
    expect(podeGravarAvaliacoes(perfil)).toBe(esperado);
  });
});
