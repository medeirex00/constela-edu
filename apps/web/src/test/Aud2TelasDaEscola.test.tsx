/**
 * `TELAS_DA_ESCOLA` do Layout (PEND-33, limpeza de RBAC-1/RBAC-2): a lista das telas de
 * escola de onde "Toda a Rede Municipal" leva a Secretaria ao Panorama da Rede só pode ter
 * telas que a Secretaria ABRE. Turmas, Professores e Simulador passaram a RotaEscolaOp (ela
 * é mandada ao Dashboard antes de o Layout montar), e as três entradas tinham ficado mortas.
 * A lista é lida do código-fonte do Layout (como o LayoutNotificacoesRotas faz com o App).
 */
import { describe, expect, it } from "vitest";

import fonteDoLayout from "../components/Layout.tsx?raw";
import { podeAbrirRota, type PerfilDaRota } from "../lib/rotasGuardadas";

function telasDaEscola(): string[] {
  const achado = /const TELAS_DA_ESCOLA = \[([^\]]*)\]/.exec(fonteDoLayout);
  expect(achado, "TELAS_DA_ESCOLA não encontrada no Layout").not.toBeNull();
  return Array.from(achado![1].matchAll(/"([^"]+)"/g), (m) => m[1]);
}

describe("Layout — telas de escola da Secretaria", () => {
  const secretaria: PerfilDaRota = { global: false, secretaria: true, rede: true, gestor: true, admin: false };
  const todos = () => true;

  it("toda tela da lista abre para a Secretaria (nenhuma entrada morta)", () => {
    const telas = telasDaEscola();
    expect(telas.length).toBeGreaterThan(0);
    expect(telas.filter((rota) => !podeAbrirRota(rota, secretaria, todos))).toEqual([]);
  });

  // O Catálogo de Livros saiu (S_G_GRUPO-2): passou a RotaEscolaOp, como Turmas e Simulador.
  it("as telas de escola que ela abre continuam na lista", () => {
    expect(telasDaEscola()).toEqual(expect.arrayContaining(["/escola", "/metricas"]));
  });
});
