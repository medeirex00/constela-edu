/**
 * Sino de notificações × guardas de rota: um aviso que aponta para uma tela que
 * o perfil NÃO abre (as guardas de App.tsx o mandariam de volta ao Dashboard)
 * aparece sem clique — o mesmo tratamento que o aviso de backup já tinha para
 * quem não é administrador. O professor, por exemplo, não abre Importações
 * (RotaEscolaOp) nem Métricas (RotaGestao); a escola sem Leitura contratada não
 * abre o Elefante (RotaModulo).
 *
 * A tabela de `lib/rotasGuardadas` é espelho de App.tsx: o primeiro bloco lê o
 * App.tsx e falha se uma guarda for criada, removida ou mudada só de um lado.
 */
import { describe, expect, it } from "vitest";

import fonteDoApp from "../App.tsx?raw";
import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { podeAbrirRota, ROTAS_GUARDADAS } from "../lib/rotasGuardadas";
import { escolaFake, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

function guardasDoApp(): { caminho: string; guardas: string[]; modulo?: string }[] {
  const rotas: { caminho: string; guardas: string[]; modulo?: string }[] = [];
  for (const [, caminho, elemento] of fonteDoApp.matchAll(/<Route path="([^"]+)" element=\{(.*)\} \/>/g)) {
    const guardas: string[] = [];
    let modulo: string | undefined;
    for (const [, nome, mod] of elemento.matchAll(/<(Rota\w+)(?: modulo="(\w+)")?>/g)) {
      if (nome === "RotaModulo") modulo = mod;
      else guardas.push(nome);
    }
    if (guardas.length || modulo) rotas.push({ caminho, guardas, ...(modulo ? { modulo } : {}) });
  }
  return rotas;
}

describe("rotasGuardadas — espelho das guardas de App.tsx", () => {
  it("lista exatamente as rotas guardadas de App.tsx, com as mesmas guardas", () => {
    const doApp = guardasDoApp();
    expect(doApp.length).toBeGreaterThan(20);   // o leitor achou as rotas
    expect(ROTAS_GUARDADAS).toEqual(doApp);
  });

  it("nenhuma guarda de App.tsx escapa do leitor (rota quebrada em várias linhas)", () => {
    // O leitor acima só enxerga `<Route ... />` numa linha. Toda abertura `<RotaX`
    // de App.tsx (as definições são `function RotaX`, sem `<`) tem de estar
    // contada na tabela; senão uma rota escrita em várias linhas sumiria da conferência.
    const aberturasNoApp = [...fonteDoApp.matchAll(/<Rota\w+/g)].length;
    const guardasNaTabela = ROTAS_GUARDADAS.reduce(
      (soma, r) => soma + r.guardas.length + (r.modulo ? 1 : 0), 0);
    expect(aberturasNoApp).toBeGreaterThan(20);
    expect(guardasNaTabela).toBe(aberturasNoApp);
  });

  const professor = { global: false, secretaria: false, rede: false, gestor: false, admin: false };
  const coordenador = { ...professor, gestor: true };
  const secretaria = { ...professor, secretaria: true, rede: true, gestor: true };
  const todos = () => true;

  it("professor não abre telas de gestão/operação; abre as sem guarda", () => {
    for (const rota of ["/importacoes", "/metricas", "/configuracoes", "/turmas/7",
      "/revisoes-identidade?status=pendente", "/elefante"]) {
      expect(podeAbrirRota(rota, professor, todos), rota).toBe(false);
    }
    for (const rota of ["/ranking", "/alunos", "/alunos/12", "/usuarios", "/suporte"]) {
      expect(podeAbrirRota(rota, professor, todos), rota).toBe(true);
    }
  });

  it("coordenação abre gestão e operação, mas não Configurações Gerais", () => {
    expect(podeAbrirRota("/importacoes", coordenador, todos)).toBe(true);
    expect(podeAbrirRota("/metricas", coordenador, todos)).toBe(true);
    expect(podeAbrirRota("/configuracoes", coordenador, todos)).toBe(false);
    expect(podeAbrirRota("/configuracoes/conquistas", coordenador, todos)).toBe(true);
  });

  it("Secretaria não opera a escola; módulo não contratado fecha a tela dele", () => {
    expect(podeAbrirRota("/importacoes", secretaria, todos)).toBe(false);
    expect(podeAbrirRota("/metricas", secretaria, todos)).toBe(true);
    const soMatematica = (m: string) => m === "matematica";
    expect(podeAbrirRota("/elefante", coordenador, soMatematica)).toBe(false);
    expect(podeAbrirRota("/matific", coordenador, soMatematica)).toBe(true);
  });
});

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

function aviso(id: number, titulo: string, rota: string) {
  return { id, tipo: "x", severidade: "info", titulo, rota, lida: false, autor: null,
    data: "2026-10-10T10:00:00" };
}

async function abrirSino(usuario: ReturnType<typeof usuarioFake>, avisos: ReturnType<typeof aviso>[]) {
  escolaConfigurada();
  responder("GET", "/notificacoes/contador", { nao_lidas: avisos.length });
  responder("GET", "/notificacoes", avisos);
  responder("POST", "/notificacoes/marcar-lidas", {});
  renderComApp(<LayoutReal />, { usuario, escolas: [escolaFake({ id: 1 })] });
  await userEvent.click(await screen.findByRole("button", { name: /Notificações/ }));
}

async function botaoDo(titulo: string) {
  const item = (await screen.findByText(titulo)).closest("button");
  expect(item).not.toBeNull();
  return item as HTMLButtonElement;
}

describe("Sino — aviso para tela que o perfil não abre fica sem clique", () => {
  const avisos = [
    aviso(1, "Nova importação de dados concluída", "/importacoes"),
    aviso(2, "Pesos do cálculo foram alterados", "/metricas"),
    aviso(3, "Novo aluno cadastrado", "/alunos/12"),
  ];

  it("professor: Importações e Métricas sem clique; o aluno continua clicável", async () => {
    await abrirSino(usuarioFake({ cargo: "professor", nome: "Prof. Rui" }), avisos);
    expect(await botaoDo("Nova importação de dados concluída")).toBeDisabled();
    expect(await botaoDo("Pesos do cálculo foram alterados")).toBeDisabled();
    expect(await botaoDo("Novo aluno cadastrado")).toBeEnabled();
  });

  it("coordenação: os mesmos avisos levam às telas", async () => {
    await abrirSino(usuarioFake({ cargo: "coordenador", nome: "Coordenadora" }), avisos);
    expect(await botaoDo("Nova importação de dados concluída")).toBeEnabled();
    expect(await botaoDo("Pesos do cálculo foram alterados")).toBeEnabled();
    expect(await botaoDo("Novo aluno cadastrado")).toBeEnabled();
  });

  it("escola sem Leitura contratada: aviso do Elefante sem clique", async () => {
    await abrirSino(
      usuarioFake({ cargo: "coordenador", nome: "Coordenadora", modulos: ["matematica"] }),
      [aviso(4, "Dados do Elefante Letrado editados manualmente", "/elefante"),
        aviso(5, "Dados da Matific editados manualmente", "/matific")],
    );
    expect(await botaoDo("Dados do Elefante Letrado editados manualmente")).toBeDisabled();
    expect(await botaoDo("Dados da Matific editados manualmente")).toBeEnabled();
  });
});
