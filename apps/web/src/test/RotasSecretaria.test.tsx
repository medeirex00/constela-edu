/**
 * Guardas de ROTA da Secretaria (rede vinculada, não-global — costuma ter cargo
 * "coordenador"). Pelo endereço digitado ela abria telas de escola fora do menu
 * dela e via a escola "vazia" (o backend nunca lhe devolve nome de criança). Aqui
 * a tabela de rotas REAL do App é exercitada com as páginas trocadas por marcas:
 * o que se testa é só quem entra em qual rota.
 */
import { Outlet } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Usuario } from "../lib/types";
import { renderComApp, screen, usuarioFake } from "./utils";

vi.mock("../components/Layout", () => ({ default: () => <Outlet /> }));
vi.mock("../pages/Dashboard", () => ({ default: () => <p>TELA:inicio</p> }));
vi.mock("../pages/Alunos", () => ({ default: () => <p>TELA:alunos</p> }));
vi.mock("../pages/PerfilAluno", () => ({ default: () => <p>TELA:perfil-aluno</p> }));
vi.mock("../pages/EvolucaoAluno", () => ({ default: () => <p>TELA:evolucao-aluno</p> }));
vi.mock("../pages/Premiacoes", () => ({ default: () => <p>TELA:premiacoes</p> }));
vi.mock("../pages/Insights", () => ({ default: () => <p>TELA:insights</p> }));
vi.mock("../pages/RelatoriosArea", () => ({ default: () => <p>TELA:relatorios</p> }));
vi.mock("../pages/Usuarios", () => ({ default: () => <p>TELA:usuarios</p> }));
vi.mock("../pages/Comparador", () => ({ default: () => <p>TELA:comparador</p> }));
vi.mock("../pages/Matific", () => ({ default: () => <p>TELA:matific</p> }));
vi.mock("../pages/Elefante", () => ({ default: () => <p>TELA:elefante</p> }));
vi.mock("../pages/VisaoEscola", () => ({ default: () => <p>TELA:visao-escola</p> }));
vi.mock("../pages/Rankings", () => ({ default: () => <p>TELA:rankings</p> }));
vi.mock("../pages/MinhaConta", () => ({ default: () => <p>TELA:minha-conta</p> }));
vi.mock("../pages/rede/RedeDashboard", () => ({ default: () => <p>TELA:rede</p> }));
vi.mock("../pages/rede/RedeAvaliacoes", () => ({ default: () => <p>TELA:rede-avaliacoes</p> }));
// As telas PRINCIPAIS da Secretaria (DESENHO2 §2.3), todas com a guarda RotaRede.
vi.mock("../pages/rede/secretaria/PanoramaSecretaria", () => ({ default: () => <p>TELA:panorama</p> }));
vi.mock("../pages/rede/secretaria/AcompanhamentoRede", () => ({ default: () => <p>TELA:acompanhamento</p> }));
vi.mock("../pages/rede/secretaria/CompararEscolas", () => ({ default: () => <p>TELA:escolas</p> }));
vi.mock("../pages/rede/secretaria/FichaEscolaRede", () => ({ default: () => <p>TELA:ficha-escola</p> }));
vi.mock("../pages/rede/secretaria/AvaliacoesExternasRede", () => ({ default: () => <p>TELA:avaliacoes-externas</p> }));
vi.mock("../pages/rede/secretaria/PlataformasRedePagina", () => ({ default: () => <p>TELA:plataformas</p> }));
vi.mock("../pages/rede/secretaria/RelatoriosRedePagina", () => ({ default: () => <p>TELA:relatorios-rede</p> }));

const SECRETARIA = usuarioFake({ cargo: "coordenador", rede_id: 7 });
// Promovida a partir de uma conta de escola: guarda o cargo de origem.
const SECRETARIA_ADMIN = usuarioFake({ cargo: "admin", rede_id: 7 });
const COORDENADOR = usuarioFake({ cargo: "coordenador" });
const PROFESSOR = usuarioFake({ cargo: "professor" });

// Rota digitada → marca da página que ela abre.
const TELAS_DE_ESCOLA: [string, string][] = [
  ["/alunos", "TELA:alunos"],
  ["/alunos/5", "TELA:perfil-aluno"],
  ["/alunos/5/evolucao", "TELA:evolucao-aluno"],
  ["/premiacoes", "TELA:premiacoes"],
  ["/insights", "TELA:insights"],
  ["/relatorios", "TELA:relatorios"],
  ["/relatorios/periodo", "TELA:relatorios"],
  ["/usuarios", "TELA:usuarios"],
  ["/comparador", "TELA:comparador"],
  ["/matific", "TELA:matific"],
  ["/elefante", "TELA:elefante"],
];

async function abrir(rota: string, usuario: Usuario) {
  renderComApp(<App />, { rota, usuario });
  return screen.findByText(/^TELA:/);
}

describe("Secretaria pelo endereço digitado", () => {
  it.each(TELAS_DE_ESCOLA)("%s → volta ao Dashboard (Panorama da Rede)", async (rota) => {
    expect(await abrir(rota, SECRETARIA)).toHaveTextContent("TELA:inicio");
  });

  it.each(TELAS_DE_ESCOLA)("%s → Secretaria com cargo admin também volta", async (rota) => {
    expect(await abrir(rota, SECRETARIA_ADMIN)).toHaveTextContent("TELA:inicio");
  });

  // O que ela usa de verdade continua abrindo: Visão da Escola (aberta pelo Painel
  // e pelo Ranking da Rede), Ranking (categoria Escolas), Minha conta e /rede.
  it.each([
    ["/escola", "TELA:visao-escola"],
    ["/ranking", "TELA:rankings"],
    ["/minha-conta", "TELA:minha-conta"],
    ["/rede", "TELA:rede"],
    ["/rede/avaliacoes", "TELA:rede-avaliacoes"],
  ])("%s continua abrindo para a Secretaria", async (rota, marca) => {
    expect(await abrir(rota, SECRETARIA)).toHaveTextContent(marca);
  });
});

// As telas principais novas: a MESMA guarda da análise (RotaRede) — Secretaria e global entram;
// escola (coordenação, professor) volta ao Dashboard. O backend (exigir_rede) é a trava real.
const TELAS_PRINCIPAIS: [string, string][] = [
  ["/rede/visao", "TELA:panorama"],
  ["/rede/acompanhamento", "TELA:acompanhamento"],
  ["/rede/escolas", "TELA:escolas"],
  // A ficha de uma escola (o id no endereço; a tela confere que a escola é da rede).
  ["/rede/escolas/3", "TELA:ficha-escola"],
  ["/rede/escolas/3?periodo=mes&rede=1", "TELA:ficha-escola"],
  ["/rede/avaliacoes-externas?indicador=saresp", "TELA:avaliacoes-externas"],
  ["/rede/plataformas", "TELA:plataformas"],
  ["/rede/relatorios", "TELA:relatorios-rede"],
];
const GLOBAL = usuarioFake({ cargo: "admin", is_global: true, escola_id: null });

describe("Telas principais da Secretaria (RotaRede)", () => {
  it.each(TELAS_PRINCIPAIS)("%s abre para a Secretaria", async (rota, marca) => {
    expect(await abrir(rota, SECRETARIA)).toHaveTextContent(marca);
  });

  it.each(TELAS_PRINCIPAIS)("%s abre para o admin global", async (rota, marca) => {
    expect(await abrir(rota, GLOBAL)).toHaveTextContent(marca);
  });

  it.each(TELAS_PRINCIPAIS)("%s → a coordenação da escola volta ao Dashboard", async (rota) => {
    expect(await abrir(rota, COORDENADOR)).toHaveTextContent("TELA:inicio");
  });

  it.each(TELAS_PRINCIPAIS)("%s → o professor volta ao Dashboard", async (rota) => {
    expect(await abrir(rota, PROFESSOR)).toHaveTextContent("TELA:inicio");
  });
});

describe("Escola (sem rede) não é afetada", () => {
  it.each(TELAS_DE_ESCOLA)("%s abre para o coordenador da escola", async (rota, marca) => {
    expect(await abrir(rota, COORDENADOR)).toHaveTextContent(marca);
  });

  it.each(TELAS_DE_ESCOLA.filter(([r]) => !["/comparador", "/matific", "/elefante"].includes(r)))(
    "%s abre para o professor", async (rota, marca) => {
      expect(await abrir(rota, PROFESSOR)).toHaveTextContent(marca);
    });

  it.each(["/comparador", "/matific", "/elefante"])(
    "%s segue fechada para o professor (tela de gestão)", async (rota) => {
      expect(await abrir(rota, PROFESSOR)).toHaveTextContent("TELA:inicio");
    });
});
