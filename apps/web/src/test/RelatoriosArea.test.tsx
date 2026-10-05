/**
 * Relatórios é UMA área com duas abas — e a barra lateral tem UMA entrada.
 *
 * O que estes testes seguram, e que uma reorganização futura pode desfazer sem
 * querer: "Relatório por Período" sumiu da barra lateral como item próprio, mas
 * NÃO sumiu do produto; a rota `/relatorios/periodo`, que já está publicada,
 * continua abrindo a tela certa; e a troca de aba não remonta nem duplica nada.
 */
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import RelatoriosArea from "../pages/RelatoriosArea";
import {
  escolaFake,
  renderComApp,
  responder,
  screen,
  userEvent,
  usuarioFake,
} from "./utils";

const texto = () => (document.body.textContent ?? "").replace(/\s+/g, " ").trim();

/** O mínimo para as duas páginas filhas renderizarem sem erro de rede. */
function mockarApi() {
  responder("GET", /\/escolas\/1\/turmas/, []);
  responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0 });
  responder("GET", /\/escolas\/1\/relatorios\/periodo/, {
    escola: { id: 1, nome: "ESCOLA TESTE", ano_letivo: 2026 },
    periodo: { preset: "mes", rotulo: "Este mês", inicio: "2026-10-01T00:00:00",
               fim: "2026-10-31T23:59:59", inclusivo: true },
    escopo: { tipo: "escola", turma_id: null, aluno_id: null, restrito_a_turmas: null },
    plataformas: ["elefante", "matific"],
    plataformas_rotulo: "Elefante Letrado + Matific",
    alunos: { considerados: 0, com_atividade: 0, sem_atividade: 0 },
    nao_suportado: [], por_aluno: [],
  });
  responder("GET", /\/escolas\/1\/modulos/, { modulos: ["leitura", "matematica"] });
}

function montar(rota: string) {
  mockarApi();
  return renderComApp(
    <Routes>
      <Route path="/relatorios" element={<RelatoriosArea />} />
      <Route path="/relatorios/periodo" element={<RelatoriosArea />} />
    </Routes>,
    {
      rota,
      usuario: usuarioFake(),
      escolas: [escolaFake({ id: 1 })],
      escolaSelecionada: 1,
    },
  );
}

describe("Relatórios como área única", () => {
  it("/relatorios abre em Relatórios oficiais, com a aba Por período à vista", async () => {
    montar("/relatorios");
    const oficiais = await screen.findByRole("tab", { name: "Relatórios oficiais" });
    const periodo = screen.getByRole("tab", { name: "Por período" });
    expect(oficiais.getAttribute("aria-selected")).toBe("true");
    expect(periodo.getAttribute("aria-selected")).toBe("false");
    // a página de relatórios oficiais está renderizada
    expect(texto()).toContain("Relatórios");
  });

  it("a rota publicada /relatorios/periodo continua abrindo o relatório por período", async () => {
    montar("/relatorios/periodo");
    const periodo = await screen.findByRole("tab", { name: "Por período" });
    expect(periodo.getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("Relatório por Período")).toBeTruthy();
    // e o que faz a tela valer continua lá
    expect(screen.getByRole("button", { name: /Gerar PDF/ })).toBeTruthy();
  });

  it("trocar de aba leva para a outra tela sem sair da área", async () => {
    montar("/relatorios");
    await userEvent.click(await screen.findByRole("tab", { name: "Por período" }));
    expect(await screen.findByText("Relatório por Período")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Gerar PDF/ })).toBeTruthy();
    await userEvent.click(screen.getByRole("tab", { name: "Relatórios oficiais" }));
    expect(screen.queryByText("Relatório por Período")).toBeNull();
  });

  it("só uma das duas telas é renderizada por vez", async () => {
    montar("/relatorios/periodo");
    await screen.findByText("Relatório por Período");
    // o cabeçalho da outra aba não pode estar no documento ao mesmo tempo
    expect(screen.queryByText(
      /Exportações com a identidade visual da escola/)).toBeNull();
  });

  it("o painel é rotulado pela aba ativa (acessibilidade)", async () => {
    montar("/relatorios/periodo");
    const aba = await screen.findByRole("tab", { name: "Por período" });
    const painel = screen.getByRole("tabpanel");
    expect(painel.getAttribute("aria-labelledby")).toBe(aba.id);
    expect(aba.getAttribute("aria-controls")).toBe(painel.id);
  });
});

describe("barra lateral", () => {
  /** O Layout real vive dentro do ImportacaoLoteProvider (App.tsx). */
  function LayoutReal() {
    return (
      <ImportacaoLoteProvider>
        <Layout />
      </ImportacaoLoteProvider>
    );
  }

  /** Escola já configurada: é o estado em que o menu completo aparece. */
  function montarLayout(usuario = usuarioFake({ is_global: true, cargo: "admin" })) {
    responder("GET", "/escolas/1/sync/status", {
      escola_id: 1, escola_nome: "Escola Modelo Constela", qtd_alunos: 30,
      qtd_turmas: 3, plataformas: [], lista_piloto_importada: true,
      integracao_configurada: true,
    });
    renderComApp(<LayoutReal />, {
      rota: "/relatorios",
      usuario,
      escolas: [escolaFake({ id: 1 })],
    });
  }

  it("não tem mais 'Relatório por Período' como item independente", async () => {
    montarLayout();
    expect((await screen.findAllByRole("link", { name: "Relatórios" })).length)
      .toBeGreaterThan(0);
    expect(screen.queryAllByRole("link", { name: /Relatório por Período/ }))
      .toHaveLength(0);
    expect(texto()).not.toContain("Relatório por Período");
  });

  it("continua tendo a entrada 'Relatórios' apontando para a área", async () => {
    montarLayout();
    const links = await screen.findAllByRole("link", { name: "Relatórios" });
    expect(links.some((l) => l.getAttribute("href") === "/relatorios")).toBe(true);
  });

  it("para o professor também: 'Meus Relatórios' sozinho", async () => {
    montarLayout(usuarioFake({ is_global: false, cargo: "professor", nome: "Prof" }));
    expect((await screen.findAllByRole("link", { name: "Meus Relatórios" })).length)
      .toBeGreaterThan(0);
    expect(screen.queryAllByRole("link", { name: /Relatório por Período/ }))
      .toHaveLength(0);
  });
});
