/**
 * Perfil do aluno — a nota POR MATÉRIA e "Como esta nota foi calculada".
 *
 * REGRA NOVA — Decisão 1 do dono (2026-10-12): transição da `nota_geral` para as
 * notas por disciplina. Este arquivo travava a equação da Nota Geral
 * ("Elefante 70 × 50% + Matific 100 × 50% = 85" tinha de fechar com a nota);
 * a nota geral saiu da tela e a equação saiu junto, então os testes foram
 * reescritos porque a regra aprovada mudou. Agora o perfil:
 *   1. mostra um cartão por matéria CONTRATADA (`dimensoes[]` da API), com a
 *      nota da matéria e a posição COM o denominador, e um cartão de Adoção;
 *   2. sem dado da plataforma mostra "—" e o motivo — nunca 0,0;
 *   3. não mostra a nota geral, a posição na ordem única nem a equação, mesmo
 *      com a API ainda mandando os campos legados (contrato);
 *   4. sem nota calculada não afirma "não aferido" de ninguém.
 */
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import PerfilAluno from "../pages/PerfilAluno";
import { renderComApp, responder, screen, usuarioFake, within } from "./utils";

const ALUNO = {
  id: 10, nome: "Ana Beatriz Souza", turma: "3º Ano A", ano_escolar: "3º Ano",
  status: "ativo",
};

const LEITURA = {
  dimensao: "leitura", plataforma: "elefante", contratada: true, aferido: true,
  nota: 70, posicao: 3, n_aferidos: 21, snapshot_em: "2026-10-01",
  dados: { livros_unicos: 12 },
};
const MATEMATICA = {
  dimensao: "matematica", plataforma: "matific", contratada: true, aferido: true,
  nota: 64.5, posicao: 1, n_aferidos: 18, snapshot_em: "2026-10-01",
  dados: { atividades: 40 },
};

/** Payload do perfil como a API manda HOJE: os blocos por matéria E os campos
 *  legados (nota geral 85, 1º na ordem única, a equação em `detalhes.geral`) —
 *  valores escolhidos para não coincidir com nada que a tela deve mostrar. */
function perfil(over: Record<string, unknown> = {}) {
  return {
    aluno: ALUNO,
    posicao: 1,
    nota_matific: 64.5,
    nota_elefante: 70,
    nota_geral: 85,
    ficha: {},
    calculada_em: "2026-10-02T03:00:00",
    dimensoes: [LEITURA, MATEMATICA],
    adocao: { contratadas: ["leitura", "matematica"], com_dados: ["leitura", "matematica"], pct: 100 },
    detalhes: {
      matific: { indicadores: [], nota: 64.5 },
      elefante: { indicadores: [], questoes: null, nota: 70 },
      geral: { pesos: { matific: 50, elefante: 50 }, nota: 85 },
    },
    ...over,
  };
}

async function abrir(dados: Record<string, unknown>) {
  responder("GET", "/escolas/1/alunos/10/perfil", dados);
  responder("GET", "/escolas/1/gamificacao/alunos/10", null);
  renderComApp(
    <Routes>
      <Route path="/alunos/:id" element={<PerfilAluno />} />
    </Routes>,
    { rota: "/alunos/10", usuario: usuarioFake({ cargo: "coordenador" }) },
  );
  await screen.findByText("Como esta nota foi calculada");
}

/** O cartão do topo cujo rótulo começa pela matéria. */
function cartao(rotulo: RegExp): HTMLElement {
  const titulo = screen.getAllByText(rotulo)
    .find((el) => el.tagName === "P" && el.closest(".card"));
  if (!titulo) throw new Error(`cartão ${rotulo} não encontrado`);
  return titulo.closest(".card") as HTMLElement;
}

describe("Perfil do aluno — desempenho por matéria", () => {
  it("um cartão por matéria, com a posição E o denominador, e o cartão de Adoção", async () => {
    await abrir(perfil());

    const leitura = cartao(/^Leitura/);
    expect(within(leitura).getByText("70,0")).toBeInTheDocument();
    expect(within(leitura).getByText("3º de 21 na escola em Leitura")).toBeInTheDocument();

    const matematica = cartao(/^Matemática/);
    expect(within(matematica).getByText("64,5")).toBeInTheDocument();
    expect(within(matematica).getByText("1º de 18 na escola em Matemática")).toBeInTheDocument();

    const adocao = cartao(/^Adoção/);
    expect(within(adocao).getByText("100%")).toBeInTheDocument();
    expect(within(adocao).getByText("2 de 2 matérias com dado")).toBeInTheDocument();
  });

  it("não mostra a nota geral, a posição na ordem única nem a equação que as juntava", async () => {
    await abrir(perfil());

    expect(screen.queryByText("Nota Geral")).not.toBeInTheDocument();
    expect(screen.queryByText("85,0")).not.toBeInTheDocument();
    expect(screen.queryByText(/º no ranking/)).not.toBeInTheDocument();
    expect(screen.queryByText(/×/)).not.toBeInTheDocument();
    // Cada matéria segue explicada pela tabela dela.
    expect(screen.getByRole("heading", { name: "Matific" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Elefante Letrado" })).toBeInTheDocument();
  });

  it("sem dado da plataforma: '—' e o motivo, nunca 0,0 — e a Adoção conta só o que tem dado", async () => {
    await abrir(perfil({
      dimensoes: [LEITURA, { ...MATEMATICA, aferido: false, nota: null, posicao: null, dados: {} }],
      adocao: { contratadas: ["leitura", "matematica"], com_dados: ["leitura"], pct: 50 },
      detalhes: { elefante: { indicadores: [], questoes: null, nota: 70 } },
    }));

    const matematica = cartao(/^Matemática/);
    expect(within(matematica).getByText("—")).toBeInTheDocument();
    expect(within(matematica).getByText("Ainda não aferido: sem dado do Matific.")).toBeInTheDocument();
    expect(within(matematica).queryByText("0,0")).not.toBeInTheDocument();
    expect(within(matematica).queryByText(/º/)).not.toBeInTheDocument();

    const adocao = cartao(/^Adoção/);
    expect(within(adocao).getByText("50%")).toBeInTheDocument();
    expect(within(adocao).getByText("1 de 2 matérias com dado")).toBeInTheDocument();
  });

  it("rede só com Leitura: a API manda só a Leitura e a tela não inventa Matemática", async () => {
    await abrir(perfil({
      dimensoes: [LEITURA],
      adocao: { contratadas: ["leitura"], com_dados: ["leitura"], pct: 100 },
      detalhes: { elefante: { indicadores: [], questoes: null, nota: 70 } },
    }));

    expect(cartao(/^Leitura/)).toBeInTheDocument();
    expect(screen.queryByText(/^Matemática/)).not.toBeInTheDocument();
    expect(within(cartao(/^Adoção/)).getByText("1 de 1 matéria com dado")).toBeInTheDocument();
  });

  it("sem nota calculada: nenhum cartão afirmando 'não aferido'", async () => {
    await abrir(perfil({ dimensoes: [], adocao: null, detalhes: {}, calculada_em: null }));

    expect(screen.getByText("Ainda não há nota calculada para este aluno")).toBeInTheDocument();
    expect(screen.queryByText(/Ainda não aferido/)).not.toBeInTheDocument();
    expect(screen.queryByText("Adoção")).not.toBeInTheDocument();
  });
});
