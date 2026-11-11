/**
 * Catálogo de Livros fora do alcance da Secretaria (S_G_GRUPO-2).
 *
 * O acervo da escola nasce das leituras das crianças: numa escola em que só uma ou duas
 * leram, os títulos e a coluna "Leituras" são o histórico delas — o que o cartão da rede
 * esconde pelo grupo pequeno. O backend passou a recusar o GET /escolas/{id}/livros à
 * Secretaria (403), e a tela /livros passou de `RotaGestao` a `RotaEscolaOp`, como
 * /elefante e /matific: pelo endereço digitado ela volta ao início, em vez de abrir uma
 * tela que só mostraria o erro. A coordenação, o administrador da escola e o Admin Global
 * seguem com o catálogo. A tabela de rotas é a REAL do App; as páginas viram marcas.
 */
import { Outlet } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import App from "../App";
import fonteDoLayout from "../components/Layout.tsx?raw";
import { podeAbrirRota, type PerfilDaRota } from "../lib/rotasGuardadas";
import type { Usuario } from "../lib/types";
import { renderComApp, screen, usuarioFake } from "./utils";

vi.mock("../components/Layout", () => ({ default: () => <Outlet /> }));
vi.mock("../pages/Dashboard", () => ({ default: () => <p>TELA:inicio</p> }));
vi.mock("../pages/Livros", () => ({ default: () => <p>TELA:livros</p> }));

const SECRETARIA = usuarioFake({ cargo: "coordenador", rede_id: 7, escola_id: null });
const SECRETARIA_PROMOVIDA = usuarioFake({ cargo: "admin", rede_id: 7 });
const COORDENADOR = usuarioFake({ cargo: "coordenador" });
const ADMIN_ESCOLA = usuarioFake({ cargo: "admin" });
const GLOBAL = usuarioFake({ cargo: "admin", is_global: true, escola_id: null });

async function abrir(usuario: Usuario) {
  renderComApp(<App />, { rota: "/livros", usuario });
  return screen.findByText(/^TELA:/);
}

describe("/livros pelo endereço digitado", () => {
  it.each([["Secretaria", SECRETARIA], ["Secretaria promovida (cargo admin)", SECRETARIA_PROMOVIDA]])(
    "%s volta ao início", async (_nome, usuario) => {
      expect(await abrir(usuario)).toHaveTextContent("TELA:inicio");
    });

  it.each([["coordenação", COORDENADOR], ["administração da escola", ADMIN_ESCOLA],
           ["Admin Global", GLOBAL]])(
    "%s continua abrindo o catálogo", async (_nome, usuario) => {
      expect(await abrir(usuario)).toHaveTextContent("TELA:livros");
    });
});

describe("o espelho das guardas e o cartão Contexto acompanham", () => {
  const secretaria: PerfilDaRota = { global: false, secretaria: true, rede: true, gestor: true, admin: false };
  const coordenacao: PerfilDaRota = { global: false, secretaria: false, rede: false, gestor: true, admin: false };
  const todos = () => true;

  it("podeAbrirRota: a Secretaria não abre /livros; a coordenação abre", () => {
    expect(podeAbrirRota("/livros", secretaria, todos)).toBe(false);
    expect(podeAbrirRota("/livros", { ...secretaria, admin: true }, todos)).toBe(false);
    expect(podeAbrirRota("/livros", coordenacao, todos)).toBe(true);
  });

  it("/livros saiu das telas de escola da Secretaria (TELAS_DA_ESCOLA)", () => {
    const achado = /const TELAS_DA_ESCOLA = \[([^\]]*)\]/.exec(fonteDoLayout);
    expect(achado).not.toBeNull();
    expect(Array.from(achado![1].matchAll(/"([^"]+)"/g), (m) => m[1])).not.toContain("/livros");
  });
});
