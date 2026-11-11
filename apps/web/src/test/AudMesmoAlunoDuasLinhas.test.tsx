/**
 * IMPORTACAO-9 — a tela deixava escolher a MESMA ficha em duas linhas do relatório
 * (a 2ª oferecia "Ana Beatriz Souza — 3º Ano A (90%)") sem dizer nada. O /confirmar
 * guardava só a última linha (o retrato da Ana ficava com os números da outra conta) e
 * ligava as duas contas à ficha. O backend agora recusa (422, nada gravado); a tela
 * avisa, na hora da escolha, que o aluno já está em outra linha, e mostra a recusa.
 *
 * A prévia e a recusa são as REAIS, gravadas por
 * backend/tests/test_aud_impweb_mesmo_aluno.py. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import Importacoes from "../pages/Importacoes";
import type { Analise } from "../lib/types";
import mesmoAluno from "./fixtures/importacoes/previa_da_tela/mesmo_aluno_analise.json";
import recusa from "./fixtures/importacoes/previa_da_tela/mesmo_aluno_confirmar_422.json";
import {
  fireEvent,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
  within,
} from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";

async function previa() {
  const u = userEvent.setup();
  responder("GET", URL_HIST, []);
  responder("GET", URL_TURMAS, [turmaFake()]);
  responder("UPLOAD", URL_ANALISAR, JSON.parse(JSON.stringify(mesmoAluno)) as Analise);
  renderComApp(
    <ImportacaoLoteProvider><Importacoes /></ImportacaoLoteProvider>, { rota: "/importacoes" });
  await screen.findByText("Nenhuma importação ainda");
  await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
  await u.type(screen.getByRole("textbox"), "placar");
  await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
  await screen.findByText("Prévia da importação");
  const data = screen.queryByLabelText("Data do relatório (obrigatória)");
  if (data) fireEvent.change(data, { target: { value: "2026-08-14" } });
  return u;
}

const destino = (nome: string) =>
  screen.getByRole("combobox", { name: `Destino de ${nome}` }) as HTMLSelectElement;
const AVISO = /também foi escolhido para outra linha deste relatório/;

describe("O mesmo aluno escolhido em duas linhas", () => {
  it("a opção diz que o aluno já está em outra linha, e a escolha avisa nas duas linhas", async () => {
    const ana = (mesmoAluno as unknown as Analise).linhas[0].correspondencia!.aluno_id!;
    const u = await previa();
    expect(destino("Ana Beatriz Souza").value).toBe(String(ana));
    const opcao = Array.from(destino("Ana Beatriz Sousa").options).find((o) => o.value === String(ana));
    expect(opcao?.textContent).toMatch(/— já escolhido em outra linha$/);
    expect(screen.queryByText(AVISO)).toBeNull();

    await u.selectOptions(destino("Ana Beatriz Sousa"), String(ana));
    for (const nome of ["Ana Beatriz Souza", "Ana Beatriz Sousa"]) {
      const linha = within(destino(nome).closest("tr") as HTMLElement);
      expect(linha.getByText(AVISO).textContent).toBe(
        "“Ana Beatriz Souza” também foi escolhido para outra linha deste relatório: só uma linha "
        + "pode ir para cada aluno — deixe a outra para a Revisão.");
    }
  });

  it("a recusa do backend (422) aparece na prévia, que continua aberta para corrigir", async () => {
    const ana = (mesmoAluno as unknown as Analise).linhas[0].correspondencia!.aluno_id!;
    const u = await previa();
    await u.selectOptions(destino("Ana Beatriz Sousa"), String(ana));
    const detalhe = (recusa as { detail: string }).detail;
    responderErro("POST", URL_CONFIRMAR, 422, detalhe);
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const dialogo = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    await u.click(within(dialogo).getByRole("button", { name: "Gravar importação" }));
    expect(await screen.findByText(detalhe)).toBeInTheDocument();
    expect(screen.getByText("Prévia da importação")).toBeInTheDocument();
    // Deixando a 2ª linha para a Revisão, o aviso some.
    await u.selectOptions(destino("Ana Beatriz Sousa"), "revisao");
    expect(screen.queryByText(AVISO)).toBeNull();
  });
});
