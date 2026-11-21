/**
 * REV-IMPWEB-2 (sobre d606e754, IMPORTACAO-9) — o aviso do mesmo aluno em duas linhas
 * mandava "deixe a outra para a Revisão" em qualquer linha, também quando nenhuma das
 * duas oferece "Deixar para a Revisão": a Ana (vínculo exato) e uma criança nova cujo
 * nome lembra o dela, com a Ana escolhida nas duas. Quem seguia o aviso não achava a
 * opção. Agora o aviso diz a saída que existe: outro destino para uma delas.
 *
 * A prévia é a REAL, gravada por backend/tests/test_aud_impweb_mesmo_aluno_sem_revisao.py
 * (que também confere a recusa do /confirmar com a Ana nas duas linhas). Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import Importacoes from "../pages/Importacoes";
import type { Analise } from "../lib/types";
import mesmoAlunoNovo from "./fixtures/importacoes/previa_da_tela/mesmo_aluno_novo_analise.json";
import { fireEvent, renderComApp, responder, screen, turmaFake, userEvent, within } from "./utils";

const AVISO = /também foi escolhido para outra linha deste relatório/;
const destino = (nome: string) =>
  screen.getByRole("combobox", { name: `Destino de ${nome}` }) as HTMLSelectElement;
const opcoes = (s: HTMLSelectElement) => Array.from(s.options).map((o) => o.value);

async function previa() {
  const u = userEvent.setup();
  responder("GET", "/escolas/1/importacoes", []);
  responder("GET", "/escolas/1/turmas", [turmaFake()]);
  responder("UPLOAD", "/escolas/1/importacoes/analisar",
    JSON.parse(JSON.stringify(mesmoAlunoNovo)) as Analise);
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

describe("O mesmo aluno em duas linhas que não oferecem 'Deixar para a Revisão'", () => {
  it("o aviso pede outro destino para uma delas, não a Revisão", async () => {
    const [linhaAna, linhaNova] = (mesmoAlunoNovo as unknown as Analise).linhas;
    const ana = linhaAna.correspondencia!.aluno_id!;
    expect(linhaNova.correspondencia!.status).toBe("nao_encontrado");
    const u = await previa();
    for (const nome of ["Ana Beatriz Souza", "Ana Beatriz Moura"]) {
      expect(opcoes(destino(nome))).not.toContain("revisao");
    }

    await u.selectOptions(destino("Ana Beatriz Moura"), String(ana));
    for (const nome of ["Ana Beatriz Souza", "Ana Beatriz Moura"]) {
      const linha = within(destino(nome).closest("tr") as HTMLElement);
      expect(linha.getByText(AVISO).textContent).toBe(
        "“Ana Beatriz Souza” também foi escolhido para outra linha deste relatório: só uma "
        + "linha pode ir para cada aluno — escolha outro destino para uma delas.");
    }

    // Seguindo o aviso (outro destino para a criança nova), ele some.
    await u.selectOptions(destino("Ana Beatriz Moura"), "ignorar");
    expect(screen.queryByText(AVISO)).toBeNull();
  });
});
