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
import { renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const ALUNO = {
  id: 10, nome: "Ana Beatriz Ficticia", turma: "3º Ano A", ano_escolar: "3º Ano",
  status: "ativo", foto_url: null, numero_chamada: 4,
};

function bloco(dimensao: string, plataforma: string, aferido: boolean, nota: number | null) {
  return { dimensao, plataforma, contratada: true, aferido, nota, posicao: null,
    n_aferidos: 0, snapshot_em: null, dados: {} };
}

/** O que o motor grava para quem não tem snapshot: o passo a passo das duas
 *  plataformas com nota 0 e os pesos de entrada (nada a renormalizar). */
const DETALHES_DO_MOTOR = {
  modo_normalizacao: "auto",
  matific: { nota: 0, indicadores: [
    { indicador: "Atividades", valor: 0, referencia: 40, normalizado: 0, peso: 50, contribuicao: 0 },
  ] },
  elefante: { nota: 0, indicadores: [
    { indicador: "Livros únicos", valor: 0, referencia: 12, normalizado: 0, peso: 50, contribuicao: 0 },
  ] },
  geral: { pesos: { matific: 50, elefante: 50 }, nota: 0, legado: true },
};

function montar(dimensoes: unknown[] | undefined, detalhes: object = { modo_normalizacao: "auto" }) {
  responder("GET", "/escolas/1/alunos/10/perfil", {
    aluno: ALUNO, posicao: 2,
    nota_matific: 0, nota_elefante: 0, nota_geral: 0,
    ...(dimensoes ? { dimensoes } : {}),
    ficha: {}, calculada_em: null,
    detalhes,
  });
  responder("GET", "/escolas/1/gamificacao/alunos/10", null);
  renderComApp(
    <Routes>
      <Route path="/alunos/:id" element={<PerfilAluno />} />
    </Routes>,
    { rota: "/alunos/10", usuario: usuarioFake({ cargo: "coordenador" }) },
  );
}

// O cartão vem antes do cálculo (que também tem um "Nota Geral", na equação).
const valorDo = async (rotulo: string) =>
  (await screen.findAllByText(rotulo))[0].parentElement?.querySelector("p")?.textContent;

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

  it("sem dado em nenhuma: a Nota Geral também é “—” e o cálculo não afirma zero", async () => {
    montar([bloco("leitura", "elefante", false, null), bloco("matematica", "matific", false, null)],
      DETALHES_DO_MOTOR);
    expect(await valorDo("Nota Matific")).toBe("—");
    expect(await valorDo("Nota Elefante Letrado")).toBe("—");
    expect(await valorDo("Nota Geral")).toBe("—");
    // A seção do cálculo abre sozinha e diz que não há dados — nada de tabela com 0,0.
    expect(screen.getByText("Ainda não há dados desta criança nas plataformas")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(/× 50%/)).not.toBeInTheDocument();
  });

  it("sem dado numa só: o cálculo dela dá lugar ao aviso, o da outra continua", async () => {
    const u = userEvent.setup();
    montar([bloco("leitura", "elefante", true, 0), bloco("matematica", "matific", false, null)],
      { ...DETALHES_DO_MOTOR, geral: { pesos: { elefante: 100 }, nota: 0, legado: true } });
    expect(await valorDo("Nota Geral")).toBe("0,0");
    await u.click(screen.getByRole("button", { name: /Como esta nota foi calculada/ }));
    const aviso = screen.getByText(/Ainda não há dados desta criança nesta plataforma/);
    expect(aviso.parentElement?.querySelector("h3")?.textContent).toBe("Matific");
    // Só a tabela do Elefante Letrado: a do Matific afirmaria "0,0".
    const tabelas = screen.getAllByRole("table");
    expect(tabelas).toHaveLength(1);
    expect(tabelas[0].closest(".rounded-2xl")?.querySelector("h3")?.textContent).toBe("Elefante Letrado");
  });
});
