/**
 * UPLOADS-9 — a tela mandava o texto colado como CAMPO de formulário (`texto`). O
 * servidor corta campo que não é arquivo em 1 MB e respondia, em inglês, "Part
 * exceeded maximum size of 1024KB." — embora o mesmo conteúdo num .txt seja aceito
 * até 10 MB. Agora o texto colado vai como o arquivo "texto-colado.txt": o mesmo
 * caminho e o mesmo teto do .txt enviado (backend/tests/test_aud_impweb_texto_colado.py
 * confere que o backend lê os dois do mesmo jeito e que o arquivo passa de 1 MB).
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import Importacoes from "../pages/Importacoes";
import type { Analise } from "../lib/types";
import analiseReal from "./fixtures/importacoes/analise_matific_motivos.json";
import {
  apiUpload,
  fireEvent,
  renderComApp,
  responder,
  screen,
  turmaFake,
  userEvent,
} from "./utils";

function lerBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const leitor = new FileReader();
    leitor.onload = () => resolve(String(leitor.result));
    leitor.onerror = () => reject(leitor.error);
    leitor.readAsText(blob);
  });
}

describe("Texto colado em Importações", () => {
  it("vai como o arquivo 'texto-colado.txt' (não como campo de formulário de até 1 MB)", async () => {
    const u = userEvent.setup();
    responder("GET", "/escolas/1/importacoes", []);
    responder("GET", "/escolas/1/turmas", [turmaFake()]);
    responder("UPLOAD", "/escolas/1/importacoes/analisar", JSON.parse(JSON.stringify(analiseReal)) as Analise);
    renderComApp(
      <ImportacaoLoteProvider><Importacoes /></ImportacaoLoteProvider>, { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    const texto = "Nome do aluno\tAtividades finalizadas\tEstrelas\nAna Beatriz Souza\t42\t120\nZefa Q\t10\t35\n";
    fireEvent.change(screen.getByRole("textbox"), { target: { value: texto } });
    await u.selectOptions(screen.getByRole("combobox", { name: "Plataforma" }), "matific");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");

    const [caminho, dados] = apiUpload.mock.calls[0] as [string, FormData];
    expect(caminho).toBe("/escolas/1/importacoes/analisar");
    expect(dados.get("texto")).toBeNull();
    const arquivo = dados.get("arquivo") as File;
    expect(arquivo).toBeInstanceOf(Blob);
    expect(arquivo.name).toBe("texto-colado.txt");
    expect(arquivo.type).toMatch(/^text\/plain/);
    expect(await lerBlob(arquivo)).toBe(texto);
    expect(dados.get("plataforma")).toBe("matific");
  });
});
