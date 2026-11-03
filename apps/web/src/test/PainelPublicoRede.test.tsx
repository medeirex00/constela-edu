/**
 * Vitrine pública da rede (/rede/p/:token): comportamento (o layout responsivo
 * é medido no Playwright, e2e-publico/vitrine.spec.ts — o jsdom não tem layout).
 *
 *  - só nome de escola + valor (nada de aluno); listas ordenadas com 5 itens;
 *    medalha com texto acessível ("1º lugar") e nome inteiro no DOM e no title;
 *  - uma falha TRANSITÓRIA da recarga de 60 s mantém o último quadro bom (não
 *    "pisca" para "Reconectando…"), como o telão da escola; 429 é transitório;
 *  - 404 (vitrine desligada / token inválido) tira a vitrine do ar — inclusive
 *    depois de ter carregado;
 *  - a página marca o <html> com `tela-publica` (escala 4K, fundo escuro, foco);
 *  - as listas têm role="list" (VoiceOver: list-style none tira a semântica);
 *  - o cartão da matéria FORA DO PLANO (fora de `modulos`) não aparece; o da
 *    matéria contratada sem dado mostra "Sem dados ainda."; sem `modulos`
 *    (backend anterior ao campo), os dois cartões, como antes.
 *
 * Dados INVENTADOS (nenhum nome ou número real).
 */
import { Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import PainelPublicoRede from "../pages/publico/PainelPublicoRede";
import { ApiError, renderComApp, responder, responderErro, screen, within } from "./utils";

const ROTA_API = /\/publico\/rede\/.+/;

function abrirVitrine(token = "tok-rede") {
  return renderComApp(
    <Routes>
      <Route path="/rede/p/:token" element={<PainelPublicoRede />} />
    </Routes>,
    { rota: `/rede/p/${token}`, autenticado: false },
  );
}

const vitrineFake = () => ({
  rede_nome: "Rede Municipal de Vila Inventada",
  top_leitura: [
    { nome: "EMEI/EMEF PROFª ANASTÁCIA MIRANDA DE OLIVEIRA CAMPOS", valor: 12.4 },
    { nome: "EMEI/EMEF PROF. BALTAZAR QUINTINO DA SILVEIRA LUZ", valor: 9.85 },
    { nome: "EMEF PROFª CELESTINA ARAÚJO VALADARES DO NASCIMENTO", valor: 7.3 },
    { nome: "EMEI/EMEF PROF. DORIVAL ESTEVES MACHADO DE ANDRADE", valor: 3.1 },
    { nome: "ESCOLA MUNICIPAL ESTRELA GUIA DO BAIRRO JARDIM AURORA", valor: 1.5 },
  ],
  top_matematica: [
    { nome: "EMEF PROFª FLORIPES BITENCOURT GUIMARÃES DE SOUZA", valor: 1234.5 },
    { nome: "EMEI/EMEF PROF. GERALDINO TAVARES ROCHA FILHO", valor: 456.25 },
  ],
  unidade_leitura: "livros por aluno",
  unidade_matematica: "estrelas por aluno",
});

test("mostra a rede, as duas listas ordenadas e o nome INTEIRO de cada escola", async () => {
  responder("GET", ROTA_API, vitrineFake());
  abrirVitrine();

  expect(await screen.findByRole("heading", { level: 1, name: "Rede Municipal de Vila Inventada" }))
    .toBeInTheDocument();
  const leitura = screen.getByRole("region", { name: "Leitura" });
  const matematica = screen.getByRole("region", { name: "Matemática" });
  expect(within(leitura).getByText("livros por aluno")).toBeInTheDocument();
  expect(within(matematica).getByText("estrelas por aluno")).toBeInTheDocument();

  // role="list" explícito: com list-style none (preflight), o Safari/VoiceOver
  // não anuncia o <ol> como lista sem ele.
  expect(within(leitura).getByRole("list")).toHaveAttribute("role", "list");
  expect(within(matematica).getByRole("list")).toHaveAttribute("role", "list");
  const linhas = within(within(leitura).getByRole("list")).getAllByRole("listitem");
  expect(linhas).toHaveLength(5);
  expect(within(within(matematica).getByRole("list")).getAllByRole("listitem")).toHaveLength(2);

  // Nome completo no DOM (leitor de tela) e no title (TV com 2 linhas).
  const nome = "EMEI/EMEF PROFª ANASTÁCIA MIRANDA DE OLIVEIRA CAMPOS";
  expect(within(linhas[0]).getByText(nome)).toHaveAttribute("title", nome);
  // Medalha: emoji decorativo + posição por extenso para o leitor de tela.
  expect(within(linhas[0]).getByText("1º lugar")).toBeInTheDocument();
  expect(within(linhas[2]).getByText("3º lugar")).toBeInTheDocument();
  expect(linhas[3]).toHaveTextContent("4º lugar");
  // Valor em pt-BR, inteiro ("1.234,5").
  expect(within(matematica).getByText("1.234,5")).toBeInTheDocument();
  expect(within(linhas[1]).getByText("9,85")).toBeInTheDocument();
});

test("matéria sem escola com dado mostra 'Sem dados ainda.' (não inventa zero)", async () => {
  // Sem `modulos`: o backend anterior ao campo — a tela mostra os dois cartões.
  responder("GET", ROTA_API, { ...vitrineFake(), top_matematica: [] });
  abrirVitrine();

  const matematica = await screen.findByRole("region", { name: "Matemática" });
  expect(within(matematica).getByText("Sem dados ainda.")).toBeInTheDocument();
  expect(within(matematica).queryByRole("list")).toBeNull();
});

test("matéria CONTRATADA sem dado continua com o cartão e 'Sem dados ainda.'", async () => {
  responder("GET", ROTA_API, {
    ...vitrineFake(), top_matematica: [], modulos: ["leitura", "matematica"],
  });
  const { container } = abrirVitrine();

  const matematica = await screen.findByRole("region", { name: "Matemática" });
  expect(within(matematica).getByText("Sem dados ainda.")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Leitura" })).toBeInTheDocument();
  // Dois cartões: a grade de sempre (duas colunas no modo TV).
  expect(container.querySelector(".vitrine-cartoes")).not.toHaveClass("vitrine-cartoes-um");
});

test("Matemática fora do plano: o cartão não aparece (não é 'Sem dados ainda.')", async () => {
  responder("GET", ROTA_API, { ...vitrineFake(), top_matematica: [], modulos: ["leitura"] });
  const { container } = abrirVitrine();

  const leitura = await screen.findByRole("region", { name: "Leitura" });
  expect(within(within(leitura).getByRole("list")).getAllByRole("listitem")).toHaveLength(5);
  expect(screen.queryByRole("region", { name: "Matemática" })).toBeNull();
  expect(screen.queryByText("Matemática")).toBeNull();
  expect(screen.queryByText("estrelas por aluno")).toBeNull();
  expect(screen.queryByText("Sem dados ainda.")).toBeNull();
  // Um cartão só: a grade de uma coluna (centralizado no modo TV).
  expect(container.querySelector(".vitrine-cartoes")).toHaveClass("vitrine-cartoes-um");
});

test("Leitura fora do plano: só o cartão da Matemática", async () => {
  responder("GET", ROTA_API, { ...vitrineFake(), top_leitura: [], modulos: ["matematica"] });
  abrirVitrine();

  const matematica = await screen.findByRole("region", { name: "Matemática" });
  expect(within(matematica).getByText("1.234,5")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Leitura" })).toBeNull();
  expect(screen.queryByText("livros por aluno")).toBeNull();
  expect(screen.queryByText("Sem dados ainda.")).toBeNull();
});

test("erro transitório APÓS carregar mantém a vitrine (não pisca para 'Reconectando')", async () => {
  vi.useFakeTimers();
  try {
    let n = 0;
    responder("GET", ROTA_API, () => {
      n += 1;
      return n === 1 ? vitrineFake() : new ApiError(503, "reiniciando");
    });
    abrirVitrine();
    await vi.advanceTimersByTimeAsync(0); // 1ª carga
    expect(screen.getByText("Rede Municipal de Vila Inventada")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(60_000); // recarga de 60 s falha…
    await vi.advanceTimersByTimeAsync(1_000);  // …e a retentativa também
    expect(n).toBeGreaterThanOrEqual(3);
    vi.useRealTimers();                         // deixa o React concluir o render
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText("Rede Municipal de Vila Inventada")).toBeInTheDocument();
    expect(screen.queryByText(/Reconectando|não encontrada/i)).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

test("vitrine desligada DEPOIS de carregar (404 na recarga) sai do ar", async () => {
  vi.useFakeTimers();
  try {
    let n = 0;
    responder("GET", ROTA_API, () => {
      n += 1;
      return n === 1 ? vitrineFake() : new ApiError(404, "não encontrada");
    });
    abrirVitrine();
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByText("Rede Municipal de Vila Inventada")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(60_000); // recarga: 404 (não é transitório)
    vi.useRealTimers();                         // deixa o React concluir o render
    expect(await screen.findByText(/Vitrine não encontrada ou desativada/i)).toBeInTheDocument();
    expect(n).toBe(2);
    expect(screen.queryByText("Rede Municipal de Vila Inventada")).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

test("sem nenhum dado, falha transitória (0, 408, 429, 5xx) mostra 'Reconectando'", async () => {
  for (const status of [0, 408, 429, 503]) {
    responderErro("GET", ROTA_API, status, "falha");
    const { unmount } = abrirVitrine(`tok-${status}`);
    expect(await screen.findByText(/Reconectando à vitrine/i, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByText(/não encontrada ou desativada/i)).toBeNull();
    unmount();
  }
});

test("token inválido / vitrine desligada (404) mostra 'não encontrada ou desativada'", async () => {
  responderErro("GET", ROTA_API, 404, "not found");
  abrirVitrine();

  expect(await screen.findByText(/Vitrine não encontrada ou desativada/i)).toBeInTheDocument();
  expect(screen.queryByText(/Reconectando/i)).toBeNull();
});

test("marca o <html> com 'tela-publica' enquanto a vitrine está aberta", async () => {
  responder("GET", ROTA_API, vitrineFake());
  const { unmount } = abrirVitrine();
  await screen.findByRole("heading", { level: 1 });
  expect(document.documentElement).toHaveClass("tela-publica");
  // Fundo decorativo fora da árvore de acessibilidade.
  expect(document.querySelector("[data-fundo-constela]")).toHaveAttribute("aria-hidden", "true");
  unmount();
  expect(document.documentElement).not.toHaveClass("tela-publica");
});

test("empate: mesmo valor, mesma posição (1º, 1º, 3º) — a ordem alfabética não decide medalha", async () => {
  responder("GET", ROTA_API, {
    ...vitrineFake(),
    top_leitura: [
      { nome: "ESCOLA FICTÍCIA ALFA DO EMPATE NO PRIMEIRO LUGAR", valor: 3.1 },
      { nome: "ESCOLA FICTÍCIA BETA DO EMPATE NO PRIMEIRO LUGAR", valor: 3.1 },
      { nome: "ESCOLA FICTÍCIA GAMA LOGO ABAIXO DAS EMPATADAS", valor: 2.4 },
      { nome: "ESCOLA FICTÍCIA DELTA EMPATADA NO QUARTO LUGAR", valor: 1.2 },
      { nome: "ESCOLA FICTÍCIA ÉPSILON EMPATADA NO QUARTO LUGAR", valor: 1.2 },
    ],
  });
  abrirVitrine();
  const leitura = await screen.findByRole("region", { name: "Leitura" });
  const linhas = within(within(leitura).getByRole("list")).getAllByRole("listitem");
  // A posição lida pelo leitor de tela (emoji decorativo + "Nº lugar" oculto).
  const posicoes = linhas.map((l) => l.querySelector(".vitrine-medalha")?.textContent?.match(/\d+º lugar/)?.[0]);
  expect(posicoes).toEqual(["1º lugar", "1º lugar", "3º lugar", "4º lugar", "4º lugar"]);
  // As duas empatadas no topo levam a MESMA medalha (ouro); a seguinte, bronze.
  expect(linhas[0].textContent).toContain("🥇");
  expect(linhas[1].textContent).toContain("🥇");
  expect(linhas[2].textContent).toContain("🥉");
});

test("com a posição do backend, a vitrine só exibe — mesmo valor, o desempate dele vale (igual ao Ranking da Rede)", async () => {
  // O Ranking da Rede desempata o mesmo "2,0 livros por aluno" pela adoção do
  // Elefante e põe BETA em 1º; a vitrine não pode coroar as duas com ouro.
  responder("GET", ROTA_API, {
    ...vitrineFake(),
    top_leitura: [
      { nome: "ESCOLA FICTÍCIA BETA COM MAIS ADOÇÃO", valor: 2.0, posicao: 1 },
      { nome: "ESCOLA FICTÍCIA ALFA COM MENOS ADOÇÃO", valor: 2.0, posicao: 2 },
      { nome: "ESCOLA FICTÍCIA GAMA", valor: 1.4, posicao: 3 },
    ],
  });
  abrirVitrine();
  const leitura = await screen.findByRole("region", { name: "Leitura" });
  const linhas = within(within(leitura).getByRole("list")).getAllByRole("listitem");
  const posicoes = linhas.map((l) => l.querySelector(".vitrine-medalha")?.textContent?.match(/\d+º lugar/)?.[0]);
  expect(posicoes).toEqual(["1º lugar", "2º lugar", "3º lugar"]);
  expect(linhas[0].textContent).toContain("🥇");
  expect(linhas[1].textContent).toContain("🥈");
});

test("token VENCIDO guardado no navegador: a vitrine abre e a sessão não é restaurada (nada de /login)", async () => {
  // A TV que religa no dia seguinte, ou a Secretaria que abre a vitrine na mesma janela com
  // o login vencido: antes, o /auth/me dava 401 e a página pública virava a tela de login.
  const anterior = window.location.pathname;
  window.history.pushState({}, "", "/rede/p/tok-rede");
  // O token como o app o lê (o mock do api guarda em memória).
  const { guardarToken } = await import("../lib/__mocks__/api");
  guardarToken("token-vencido-sintetico");
  responder("GET", ROTA_API, vitrineFake());
  responderErro("GET", "/auth/me", 401, "Sessão expirada");
  try {
    abrirVitrine();
    expect(await screen.findByRole("heading", { level: 1, name: "Rede Municipal de Vila Inventada" }))
      .toBeInTheDocument();
    const { api } = await import("./utils");
    expect(api.mock.calls.some(([caminho]) => caminho === "/auth/me")).toBe(false);
  } finally {
    window.history.pushState({}, "", anterior);
  }
});
