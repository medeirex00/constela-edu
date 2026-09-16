/**
 * Simulador de Pontuação: o que é DIGITADO é o que é simulado, e a tela diz qual
 * régua produziu o número.
 *
 *  * "Livros por nível" valida contra o vocabulário OFICIAL (AA…Z, Z+, A+): Z+ e
 *    A+ chegam íntegros e um código inexistente vira ERRO VISÍVEL, em vez de ser
 *    descartado em silêncio (ou virar um nível inventado) e simular outro aluno;
 *  * o resultado mostra o `perfil` devolvido pelo backend — no perfil
 *    institucional o motor IGNORA a configuração local de pesos/referências, e
 *    prometer "os pesos atuais da escola" seria falso.
 */
import { describe, expect, it } from "vitest";

import Simulador from "../pages/Simulador";
import {
  api, renderComApp, responder, screen, turmaFake, userEvent, waitFor,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_SIM = "/escolas/1/simulador";

function resultadoFake(over: Record<string, unknown> = {}) {
  const linha = (indicador: string) => ({
    indicador, valor: 20, referencia: 40, normalizado: 50, peso: 40, contribuicao: 20,
  });
  return {
    perfil: "institucional",
    modo_normalizacao: "auto",
    pontos_dificuldade: 12.5,
    // Indicadores com nomes distintos: as duas listas são renderizadas na MESMA
    // <ul>, com o indicador como key.
    matific: { indicadores: [linha("Atividades")], nota: 62.5 },
    elefante: { indicadores: [linha("Pontos de dificuldade")], nota: 71.25 },
    geral: { pesos: { matific: 0.5, elefante: 0.5 }, nota: 66.88, legado: true },
    ...over,
  };
}

function postsDoSimulador() {
  return api.mock.calls.filter(
    ([caminho, opcoes]) => caminho === URL_SIM
      && (opcoes as RequestInit | undefined)?.method === "POST",
  );
}

function corpoDoPost(indice = 0) {
  return JSON.parse(String((postsDoSimulador()[indice][1] as RequestInit).body));
}

async function abrir(over: Record<string, unknown> = {}) {
  responder("GET", URL_TURMAS, [turmaFake()]);
  responder("POST", URL_SIM, resultadoFake(over));
  renderComApp(<Simulador />, { rota: "/simulador" });
  return userEvent.setup();
}

describe("Simulador", () => {
  it("níveis oficiais Z+ e A+ chegam íntegros ao backend", async () => {
    const u = await abrir();

    const campo = await screen.findByLabelText(/Livros por nível/);
    await u.clear(campo);
    await u.type(campo, "AA:2, Z+:3, A+:1");
    await u.click(screen.getByRole("button", { name: /Simular nota/ }));

    await waitFor(() => expect(postsDoSimulador()).toHaveLength(1));
    // A regex antiga (`[A-Za-z]{1,2}`) devolvia só {AA: 2}: os 3 livros Z+ e o
    // livro A+ sumiam da conta sem aviso nenhum.
    expect(corpoDoPost().livros_por_nivel).toEqual({ AA: 2, "Z+": 3, "A+": 1 });
  });

  it("código fora do vocabulário oficial dá erro visível e NÃO chama a API", async () => {
    const u = await abrir();

    const campo = await screen.findByLabelText(/Livros por nível/);
    await u.clear(campo);
    // "pre_leitor" é faixa da escola, não nível oficial: a regex antiga o
    // transformava no nível inexistente "OR" (as duas últimas letras).
    await u.type(campo, "AA:2, pre_leitor:4");
    await u.click(screen.getByRole("button", { name: /Simular nota/ }));

    expect(await screen.findByText(/pre_leitor:4/)).toBeInTheDocument();
    expect(await screen.findByText(/Use níveis do Elefante/)).toBeInTheDocument();
    expect(postsDoSimulador()).toHaveLength(0);
    expect(screen.queryByText("Como chegamos aqui")).toBeNull();
  });

  it("anuncia a régua do MOTOR e mostra o perfil institucional devolvido", async () => {
    const u = await abrir();

    // A descrição não promete mais "os pesos e referências ATUAIS da escola":
    // no perfil institucional o motor ignora a configuração local.
    expect(await screen.findByText(/MESMA régua que o motor aplica nesta escola/))
      .toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: /Simular nota/ }));

    expect(await screen.findByText(/Régua Padrão Constela — a mesma para toda a rede/))
      .toBeInTheDocument();
    expect(screen.queryByText(/personalizada desta escola/)).toBeNull();
  });

  it("perfil personalizado aparece com o vocabulário da tela de Pontuação", async () => {
    const u = await abrir({ perfil: "personalizado" });

    await u.click(await screen.findByRole("button", { name: /Simular nota/ }));

    expect(await screen.findByText(/personalizada desta escola, autorizada pela Constela/))
      .toBeInTheDocument();
    expect(screen.queryByText(/a mesma para toda a rede/)).toBeNull();
  });
});
