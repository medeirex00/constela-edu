/**
 * Telas de GESTÃO de escola que a Secretaria (rede vinculada, não-global; costuma ter
 * cargo "coordenador", ou "admin" quando foi promovida de uma escola) abria pelo
 * endereço digitado, embora o backend lhe recuse o conteúdo central delas:
 *
 *   /turmas, /turmas/:id      → GET /escolas/{id}/turmas = [] (turmas_permitidas → [] para
 *                               ela) e 404 no resumo e nos alunos da turma: a tela dizia
 *                               "Esta escola ainda não cadastrou turmas" numa escola com turmas
 *   /professores              → a coluna Turmas vem da mesma lista vazia: "—" para quem tem turma
 *   /conquistas               → GET /gamificacao/mural = 403
 *   /assistente               → GET /assistente/conversas e POST /assistente = 403
 *   /simulador                → GET /turmas = [] ("Cadastre turmas para simular") e POST = 403
 *   /configuracoes/conquistas → o editor abria inteiro e o Salvar dava 403
 *
 * Elas estavam sob `RotaGestao` (só olha `gestor`); agora usam `RotaEscolaOp` (gestão
 * sem Secretaria), como as demais telas de operação de escola. A Visão da Escola
 * (/escola) continua aberta a ela: a ficha da escola na rede leva para lá.
 * O espelho `podeAbrirRota` acompanha: o link "Conquistas e Mural" da Biblioteca
 * some para ela. A tabela de rotas é a REAL do App; as páginas viram marcas.
 */
import { Outlet } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import App from "../App";
import { podeAbrirRota, type PerfilDaRota } from "../lib/rotasGuardadas";
import type { Usuario } from "../lib/types";
import BibliotecaConquistas from "../pages/BibliotecaConquistas";
import { renderComApp, responder, screen, usuarioFake } from "./utils";

vi.mock("../components/Layout", () => ({ default: () => <Outlet /> }));
vi.mock("../pages/Dashboard", () => ({ default: () => <p>TELA:inicio</p> }));
vi.mock("../pages/Turmas", () => ({ default: () => <p>TELA:turmas</p> }));
vi.mock("../pages/TurmaDetalhe", () => ({ default: () => <p>TELA:turma-detalhe</p> }));
vi.mock("../pages/ListasSimples", () => ({ Professores: () => <p>TELA:professores</p> }));
vi.mock("../pages/Conquistas", () => ({ default: () => <p>TELA:conquistas</p> }));
vi.mock("../pages/Assistente", () => ({ default: () => <p>TELA:assistente</p> }));
vi.mock("../pages/Simulador", () => ({ default: () => <p>TELA:simulador</p> }));
vi.mock("../pages/configuracoes/ConfigConquistas", () => ({ default: () => <p>TELA:config-conquistas</p> }));
vi.mock("../pages/VisaoEscola", () => ({ default: () => <p>TELA:visao-escola</p> }));
vi.mock("../pages/configuracoes/Metricas", () => ({ default: () => <p>TELA:metricas</p> }));

const SECRETARIA = usuarioFake({ cargo: "coordenador", rede_id: 7, escola_id: null });
const SECRETARIA_PROMOVIDA = usuarioFake({ cargo: "admin", rede_id: 7 });
const COORDENADOR = usuarioFake({ cargo: "coordenador" });
const ADMIN_ESCOLA = usuarioFake({ cargo: "admin" });
const GLOBAL = usuarioFake({ cargo: "admin", is_global: true, escola_id: null });
const PROFESSOR = usuarioFake({ cargo: "professor" });

// Rota digitada → marca da página que ela abre.
const TELAS: [string, string][] = [
  ["/turmas", "TELA:turmas"],
  ["/turmas/3", "TELA:turma-detalhe"],
  ["/professores", "TELA:professores"],
  ["/conquistas", "TELA:conquistas"],
  ["/assistente", "TELA:assistente"],
  ["/simulador", "TELA:simulador"],
  ["/configuracoes/conquistas", "TELA:config-conquistas"],
];

async function abrir(rota: string, usuario: Usuario) {
  renderComApp(<App />, { rota, usuario });
  return screen.findByText(/^TELA:/);
}

describe("Secretaria pelo endereço digitado: telas de gestão que o backend recusa a ela", () => {
  it.each(TELAS)("%s → a Secretaria volta ao início (Panorama da Rede)", async (rota) => {
    expect(await abrir(rota, SECRETARIA)).toHaveTextContent("TELA:inicio");
  });

  it.each(TELAS)("%s → a Secretaria promovida (cargo admin) também volta", async (rota) => {
    expect(await abrir(rota, SECRETARIA_PROMOVIDA)).toHaveTextContent("TELA:inicio");
  });

  // O que ela usa de verdade continua: a Visão da Escola (aberta pela ficha da escola na
  // rede) e os Critérios de pontuação, que já têm modo de leitura para ela.
  it.each([
    ["/escola", "TELA:visao-escola"],
    ["/metricas", "TELA:metricas"],
  ])("%s continua abrindo para a Secretaria", async (rota, marca) => {
    expect(await abrir(rota, SECRETARIA)).toHaveTextContent(marca);
  });
});

describe("A escola não muda", () => {
  it.each(TELAS)("%s abre para a coordenação da escola", async (rota, marca) => {
    expect(await abrir(rota, COORDENADOR)).toHaveTextContent(marca);
  });

  it.each(TELAS)("%s abre para o administrador da escola", async (rota, marca) => {
    expect(await abrir(rota, ADMIN_ESCOLA)).toHaveTextContent(marca);
  });

  it.each(TELAS)("%s abre para o administrador global", async (rota, marca) => {
    expect(await abrir(rota, GLOBAL)).toHaveTextContent(marca);
  });

  it.each(TELAS)("%s segue fechada para o professor", async (rota) => {
    expect(await abrir(rota, PROFESSOR)).toHaveTextContent("TELA:inicio");
  });
});

describe("o espelho das guardas (podeAbrirRota) acompanha", () => {
  const secretaria: PerfilDaRota = { global: false, secretaria: true, rede: true, gestor: true, admin: false };
  const promovida: PerfilDaRota = { ...secretaria, admin: true };
  const coordenacao: PerfilDaRota = { global: false, secretaria: false, rede: false, gestor: true, admin: false };
  const todos = () => true;

  it.each(TELAS.map(([rota]) => rota))("%s: a Secretaria não abre; a coordenação abre", (rota) => {
    expect(podeAbrirRota(rota, secretaria, todos)).toBe(false);
    expect(podeAbrirRota(rota, promovida, todos)).toBe(false);
    expect(podeAbrirRota(rota, coordenacao, todos)).toBe(true);
  });

  it("a Biblioteca de Conquistas não oferece à Secretaria o link para o mural", async () => {
    const leitura = {
      codigo: "primeira_leitura", nome: "Primeira Leitura", icone: "📖", descricao: "", objetivo: "",
      indicador: "livros_unicos", limite: 1, plataforma: "elefante", xp: 100, raridade: "comum",
      ordem: 1, ativa: true, criada_em: "2026-09-01", unidade: "livros", criterio: "Ler 1 livro",
      desbloqueios: 0, pct_desbloqueio: 0,
    };
    responder("GET", "/escolas/1/gamificacao/biblioteca", {
      conquistas: [leitura],
      estatisticas: {
        total: 1, ativas: 1, alunos: 0, total_desbloqueios: 0, pct_medio_conclusao: 0,
        mais_rara: null, mais_comum: null, maior_xp: null, ranking_desbloqueios: [],
      },
      raridades: { comum: "Comum" }, indicadores: { livros_unicos: "Livros lidos" },
    });
    renderComApp(<BibliotecaConquistas />, { usuario: SECRETARIA, escolaSelecionada: 1 });
    // O catálogo só chega depois que a sessão dela abriu e a escola entrou no contexto.
    await screen.findByText("1 conquista");
    expect(screen.queryByRole("link", { name: "Conquistas e Mural" })).toBeNull();
  });
});
