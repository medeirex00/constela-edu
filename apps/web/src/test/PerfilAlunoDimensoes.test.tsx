/**
 * Ficha do aluno × desempenho por dimensão: o `aferido` de `perfil.dimensoes`
 * (que o backend passou a enviar — `backend/tests/test_perfil_dimensoes_contrato.py`)
 * separa "sem dado" ("—") do zero legítimo ("0,0"). As notas de plataforma chegam
 * 0,0 para quem não tem snapshot; sem os blocos a ficha afirmava esse 0,0.
 * Dados fictícios.
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import PerfilAluno from "../pages/PerfilAluno";
import { renderComApp, responder, screen, usuarioFake } from "./utils";

const ALUNO = {
  id: 10, nome: "Ana Beatriz Ficticia", turma: "3º Ano A", ano_escolar: "3º Ano",
  status: "ativo", foto_url: null, numero_chamada: 4,
};

function bloco(dimensao: string, plataforma: string, aferido: boolean, nota: number | null) {
  return { dimensao, plataforma, contratada: true, aferido, nota, posicao: null,
    n_aferidos: 0, snapshot_em: null, dados: {} };
}

function montar(dimensoes: unknown[] | undefined) {
  responder("GET", "/escolas/1/alunos/10/perfil", {
    aluno: ALUNO, posicao: 2,
    nota_matific: 0, nota_elefante: 0, nota_geral: 0,
    ...(dimensoes ? { dimensoes } : {}),
    ficha: {}, calculada_em: null,
    detalhes: { modo_normalizacao: "auto" },
  });
  responder("GET", "/escolas/1/gamificacao/alunos/10", null);
  renderComApp(
    <Routes>
      <Route path="/alunos/:id" element={<PerfilAluno />} />
    </Routes>,
    { rota: "/alunos/10", usuario: usuarioFake({ cargo: "coordenador" }) },
  );
}

const valorDo = async (rotulo: string) =>
  (await screen.findByText(rotulo)).parentElement?.querySelector("p")?.textContent;

describe("Perfil do aluno — sem dado é “—”, zero legítimo é 0,0", () => {
  it("Matemática sem snapshot mostra “—”; Leitura com snapshot e nada produzido mostra 0,0", async () => {
    montar([bloco("leitura", "elefante", true, 0), bloco("matematica", "matific", false, null)]);
    expect(await valorDo("Nota Matific")).toBe("—");
    expect(await valorDo("Nota Elefante Letrado")).toBe("0,0");
  });

  it("quem tem dado nas duas segue com o número", async () => {
    montar([bloco("leitura", "elefante", true, 0), bloco("matematica", "matific", true, 0)]);
    expect(await valorDo("Nota Matific")).toBe("0,0");
    expect(await valorDo("Nota Elefante Letrado")).toBe("0,0");
  });
});
