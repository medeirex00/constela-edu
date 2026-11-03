/**
 * D10 pela ficha, no perfil do aluno (revisão e97e, regressão da prova
 * ProvaAvisoD10Perfil do revisor) — dados fictícios.
 *
 * O Admin Global que tira de "excluído" uma ficha cuja conta da plataforma vale
 * em outra escola recebe `avisos` na resposta de /alunos/acoes. No perfil,
 * `aoMudar` recarrega a página; com a rede levando dezenas de ms, o PerfilAluno
 * troca o conteúdo por <Carregando/> e DESMONTA o AcoesAluno — a janela de
 * aviso sumia junto. Agora o AcoesAluno só avisa a tela (recarrega) depois que
 * o usuário fecha a janela.
 *
 * A latência de 30 ms no GET do perfil é proposital: com o mock instantâneo o
 * fetch resolve num microtask antes de o React renderizar `carregando=true`, e
 * o desmonte não acontece — por isso o teste do AcoesAluno sozinho não pegava.
 */
import { expect, test } from "vitest";
import { Route, Routes } from "react-router-dom";

import PerfilAluno from "../pages/PerfilAluno";
import {
  api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor,
} from "./utils";

const ALUNO = {
  id: 10, nome: "Ana Beatriz Ficticia", turma: "3º Ano A", ano_escolar: "3º Ano",
  status: "excluido",
};

function perfil() {
  return {
    aluno: ALUNO, posicao: null, nota_matific: 100, nota_elefante: 70, nota_geral: 85,
    ficha: {},
    detalhes: {
      matific: { indicadores: [], nota: 100 },
      elefante: { indicadores: [], questoes: null, nota: 70 },
      geral: { pesos: { matific: 50, elefante: 50 }, nota: 85 },
    },
  };
}

const AVISO = "Atenção: esta conta da plataforma continua vinculada a um aluno de outra " +
  "escola do Constela, que não foi alterada.";

const buscasDoPerfil = () =>
  api.mock.calls.filter(([c]) => String(c) === "/escolas/1/alunos/10/perfil").length;

const postouAcao = () => api.mock.calls.some(
  ([c, o]) => String(c).includes("/alunos/acoes") && (o as RequestInit)?.method === "POST",
);

function montarPerfil(usuario = usuarioFake({ cargo: "admin", is_global: true })) {
  responder("GET", "/escolas/1/alunos/10/perfil",
    () => new Promise((ok) => setTimeout(() => ok(perfil()), 30)));
  responder("GET", "/escolas/1/gamificacao/alunos/10", null);
  renderComApp(
    <Routes>
      <Route path="/alunos/:id" element={<PerfilAluno />} />
    </Routes>,
    { rota: "/alunos/10", usuario },
  );
}

async function reativarPeloMenu() {
  await userEvent.click(await screen.findByLabelText("Ações de Ana Beatriz Ficticia"));
  await userEvent.click(await screen.findByText("Reativar"));
  await waitFor(() => expect(postouAcao()).toBe(true));
}

test("Admin Global reativa a ficha excluída pelo perfil e o aviso do D10 fica na tela", async () => {
  responder("POST", /\/alunos\/acoes/,
    { mensagem: "1 aluno(s) reativado(s).", afetados: 1, avisos: [AVISO] });
  montarPerfil();
  await reativarPeloMenu();

  // O aviso aparece e CONTINUA depois do tempo de um recarregamento do perfil.
  expect(await screen.findByText(AVISO)).toBeInTheDocument();
  await new Promise((ok) => setTimeout(ok, 120));
  expect(screen.queryByText(AVISO)).not.toBeNull();
  // Enquanto o aviso está aberto, a página não recarregou (nada a desmontá-lo).
  expect(buscasDoPerfil()).toBe(1);

  // "Entendi" fecha o aviso e só então o perfil é buscado de novo.
  await userEvent.click(screen.getByRole("button", { name: "Entendi" }));
  expect(screen.queryByText(AVISO)).toBeNull();
  await waitFor(() => expect(buscasDoPerfil()).toBeGreaterThanOrEqual(2));
  expect(await screen.findByLabelText("Ações de Ana Beatriz Ficticia")).toBeInTheDocument();
});

test("fechar o aviso pelo fundo da janela também recarrega o perfil", async () => {
  responder("POST", /\/alunos\/acoes/,
    { mensagem: "1 aluno(s) reativado(s).", afetados: 1, avisos: [AVISO] });
  montarPerfil();
  await reativarPeloMenu();

  expect(await screen.findByText(AVISO)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Fechar janela" }));
  expect(screen.queryByText(AVISO)).toBeNull();
  await waitFor(() => expect(buscasDoPerfil()).toBeGreaterThanOrEqual(2));
});

test("reativar sem aviso recarrega o perfil na hora, sem janela de atenção", async () => {
  responder("POST", /\/alunos\/acoes/,
    { mensagem: "1 aluno(s) reativado(s).", afetados: 1, avisos: [] });
  montarPerfil();
  await reativarPeloMenu();

  await waitFor(() => expect(buscasDoPerfil()).toBeGreaterThanOrEqual(2));
  expect(await screen.findByLabelText("Ações de Ana Beatriz Ficticia")).toBeInTheDocument();
  expect(screen.queryByText(/Ação concluída — atenção/)).toBeNull();
});

test("403 do D10 para a gestão da escola continua visível e não recarrega", async () => {
  responderErro("POST", /\/alunos\/acoes/, 403, "Fictício: só o Admin Global decide.");
  montarPerfil(usuarioFake({ cargo: "admin" }));
  await reativarPeloMenu();

  expect(await screen.findByText(/só o Admin Global decide/)).toBeInTheDocument();
  await new Promise((ok) => setTimeout(ok, 120));
  expect(screen.queryByText(/só o Admin Global decide/)).not.toBeNull();
  expect(buscasDoPerfil()).toBe(1);
});
