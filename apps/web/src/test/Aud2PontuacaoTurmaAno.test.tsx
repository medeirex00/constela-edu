/**
 * Pontuação por turma depois da virada do ano letivo (G_VIRADA-5): a configuração é por
 * turma e as turmas de um ano novo são outras — o seletor diz de que ano letivo são as
 * turmas listadas (a API manda só as do ano ativo), e a escola sem turma no ano ativo
 * recebe o aviso com o ano, não um "cadastre turmas" sem contexto.
 */
import { describe, expect, it } from "vitest";

import { PontuacaoPorTurma } from "../pages/configuracoes/dificuldade";
import { renderComApp, responder, screen, usuarioFake } from "./utils";

const URL = "/escolas/1/configuracoes/pontuacao-turma";
const global = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });
const CATALOGO = [{ codigo: "D", pontos_padrao: 4, faixa: "Nível 2" }];

describe("PontuacaoPorTurma — ano letivo das turmas", () => {
  it("o seletor diz o ano letivo das turmas listadas", async () => {
    responder("GET", URL, {
      catalogo: CATALOGO,
      ano_letivo: 2027,
      turmas: [{ turma_id: 2, nome: "3º Ano A", ano_escolar: "3º Ano", ano_letivo: 2027,
                 pontos: {} }],
    });
    renderComApp(<PontuacaoPorTurma />, { usuario: global });

    const seletor = await screen.findByRole("combobox", { name: "Turma do ano letivo 2027" });
    expect(seletor).toHaveDisplayValue("3º Ano A · 3º Ano");
  });

  it("sem turma no ano letivo ativo, o aviso diz o ano", async () => {
    responder("GET", URL, { catalogo: CATALOGO, ano_letivo: 2027, turmas: [] });
    renderComApp(<PontuacaoPorTurma />, { usuario: global });

    expect(await screen.findByText(
      "Nenhuma turma ativa no ano letivo 2027. Cadastre as turmas deste ano para configurar a "
      + "pontuação por nível.",
    )).toBeInTheDocument();
  });
});
