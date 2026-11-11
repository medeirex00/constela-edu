/**
 * Painel da turma: a dica do botão "Cartões do Quest" descreve o que o PDF traz
 * (G_QUEST-8). Ela prometia "QR, código e senha de figuras de cada aluno", da versão
 * anterior à decisão de produto de 09/07/2026: o cartão NÃO tem senha nem PIN (o
 * código é a credencial). O professor esperava uma senha para entregar às crianças
 * que o PDF não tem. Dados fictícios.
 */
import { expect, test } from "vitest";
import { Route, Routes } from "react-router-dom";

import TurmaDetalhe from "../pages/TurmaDetalhe";
import { renderComApp, responder, screen, usuarioFake } from "./utils";

test("a dica do botão fala do QR, do código e da folha do professor, sem senha", async () => {
  responder("GET", "/escolas/1/turmas/5/resumo", {
    turma: { id: 5, nome: "3º Ano A", ano_escolar: "3º Ano" },
    total_alunos: 0, media_geral: 0, media_matific: 0, media_elefante: 0, indicadores: {},
  });
  responder("GET", "/escolas/1/turmas", []);
  responder("GET", /\/escolas\/1\/turmas\/5\/alunos/, []);
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: "/turmas/5", usuario: usuarioFake({ cargo: "professor" }) },
  );

  const botao = await screen.findByRole("button", { name: /Cartões do Quest/ });
  const dica = botao.getAttribute("title") ?? "";
  expect(dica).not.toMatch(/senha|figura|PIN/i);
  expect(dica).toMatch(/QR/);
  expect(dica).toMatch(/código/);
  expect(dica).toMatch(/folha do professor/);
});
