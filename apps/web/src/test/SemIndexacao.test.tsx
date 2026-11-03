/**
 * Páginas públicas sem login (telão, perfil público e vitrine da rede) pedem
 * aos buscadores que não indexem nem arquivem: `<meta name="robots">` enquanto
 * a página está montada — e só nela (o SPA inteiro não pode ser desindexado,
 * senão o login some dos buscadores). O `X-Robots-Tag` da borda e da API é
 * coberto no backend (tests/test_painel_publico_regressoes.py).
 *
 * Dados INVENTADOS.
 */
import { Route, Routes } from "react-router-dom";

import { ROBOTS_NAO_INDEXAR } from "../hooks/useSemIndexacao";
import Login from "../pages/Login";
import PainelPublico from "../pages/publico/PainelPublico";
import PainelPublicoRede from "../pages/publico/PainelPublicoRede";
import PerfilPublico from "../pages/publico/PerfilPublico";
import { renderComApp, responder, screen } from "./utils";

const metaRobots = () => document.head.querySelectorAll('meta[name="robots"]');

test("o telão da escola marca noindex enquanto está aberto e limpa ao sair", async () => {
  responder("GET", /\/publico\/.+\/painel/, {
    escola: { nome: "Escola do Telão", cor_primaria: "#123456" },
    slides: ["ranking"],
    intervalo_s: 8,
    ranking: [],
    evolucao: [],
    destaques: { dia: null, semana: null, mes: null },
    mural: [],
  });
  const { unmount } = renderComApp(
    <Routes><Route path="/p/:token" element={<PainelPublico />} /></Routes>,
    { rota: "/p/tok123", autenticado: false },
  );
  expect(await screen.findByText("Escola do Telão")).toBeInTheDocument();
  expect(metaRobots()).toHaveLength(1);
  expect(metaRobots()[0].getAttribute("content")).toBe(ROBOTS_NAO_INDEXAR);
  expect(ROBOTS_NAO_INDEXAR).toBe("noindex, nofollow, noarchive");

  unmount();
  expect(metaRobots()).toHaveLength(0);
});

test("o perfil público do aluno também marca noindex", async () => {
  // Sem o campo legado da nota única: a catraca do legado (backend,
  // test_legado_nota_geral.py) não aceita fixture nova com ele, e aqui só
  // interessa o <meta robots> (a linha "Geral" mostra "—").
  responder("GET", /\/publico\/.+\/alunos\/.+/, {
    nome: "Aluna F.",
    turma: null,
    posicao: 1,
    nota_matific: 70,
    nota_elefante: null,
    nivel: 2,
    xp: 120,
    conquistas: [],
    escola: "Escola Inventada",
  });
  const { unmount } = renderComApp(
    <Routes><Route path="/p/:token/alunos/:id" element={<PerfilPublico />} /></Routes>,
    { rota: "/p/tok123/alunos/7", autenticado: false },
  );
  expect(await screen.findByText("Aluna F.")).toBeInTheDocument();
  expect(metaRobots()).toHaveLength(1);
  expect(metaRobots()[0].getAttribute("content")).toBe(ROBOTS_NAO_INDEXAR);
  unmount();
  expect(metaRobots()).toHaveLength(0);
});

test("a vitrine pública da rede também marca noindex", async () => {
  responder("GET", /\/publico\/rede\/.+/, {
    rede_nome: "Rede Municipal Inventada",
    top_leitura: [],
    top_matematica: [],
    unidade_leitura: "livros por aluno",
    unidade_matematica: "estrelas por aluno",
  });
  const { unmount } = renderComApp(
    <Routes><Route path="/rede/p/:token" element={<PainelPublicoRede />} /></Routes>,
    { rota: "/rede/p/tok-rede", autenticado: false },
  );
  expect(await screen.findByRole("heading", { level: 1, name: "Rede Municipal Inventada" }))
    .toBeInTheDocument();
  expect(metaRobots()).toHaveLength(1);
  expect(metaRobots()[0].getAttribute("content")).toBe(ROBOTS_NAO_INDEXAR);
  unmount();
  expect(metaRobots()).toHaveLength(0);
});

test("uma página que não é pública (login) NÃO é desindexada", async () => {
  renderComApp(<Login />, { rota: "/login", autenticado: false });
  expect(await screen.findByRole("button", { name: /entrar/i })).toBeInTheDocument();
  expect(metaRobots()).toHaveLength(0);
});
