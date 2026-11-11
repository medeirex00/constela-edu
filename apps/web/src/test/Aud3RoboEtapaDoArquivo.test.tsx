/**
 * "Automatizar" (a fonte do robô de avaliações) — revisão REV3-INDIC-2. No arquivo oficial do
 * INEP, os nomes das colunas são os mesmos em Anos Iniciais e Anos Finais: só o TOPO do arquivo
 * diz a etapa. A tela mandava só os nomes, e a 1ª coleta de uma fonte sem etapa fixa (o preset
 * do IDEB não a preenche) adotava a etapa que o arquivo da URL declarasse. Agora a tela manda
 * também as linhas do topo do arquivo analisado, até a linha antes dos dados; o backend tira
 * delas a etapa e a guarda como referência.
 *
 * Arquivo, nomes, códigos e URL INVENTADOS.
 */
import { describe, expect, it } from "vitest";

import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import { api, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

const LONGO = "Nota: ".padEnd(600, "x");

function semear() {
  responder("GET", "/redes", [{ id: 1, nome: "Rede Inventada" }]);
  responder("GET", "/avaliacoes/fontes", []);
  responder("GET", "/redes/1/avaliacoes/opcoes", []);
  responder("GET", "/avaliacoes", [
    { chave: "ideb", nome: "IDEB", tipo: "indicador", orgao: "INEP", descricao: null },
  ]);
  responder("GET", "/avaliacoes/presets-import", []);
  responder("UPLOAD", "/avaliacoes/analisar", {
    linhas_lidas: 5, n_colunas: 5,
    primeiras_linhas: [
      ["", "", "Ministério da Educação", "", ""],
      ["Ensino Fundamental Regular - Anos Iniciais", LONGO, "", "", ""],
      ["SG_UF", "NO_MUNICIPIO", "ID_ESCOLA", "NO_ESCOLA", "VL_OBSERVADO_2023"],
      ["SP", "Cidade Inventada", "35012345", "EM Inventada", "5.9"],
      ["SP", "Cidade Inventada", "35012346", "EM Inventada II", "6.1"],
    ],
  });
  responder("POST", "/avaliacoes/fontes", { id: 7 });
}

async function salvarFonte(linhaDados: string) {
  const u = userEvent.setup();
  const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
  await screen.findByText("Importar resultado oficial");
  const entradas = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="file"]'))
    .filter((e) => e.closest('[data-testid="cartao-ica"]') == null);
  await u.upload(entradas[1], new File(["x"], "ideb_inventado.zip", { type: "application/zip" }));
  await screen.findByText(/primeira linha de dados/);

  const linha = screen.getByLabelText("1ª linha de dados (índice)");
  await u.clear(linha);
  await u.type(linha, linhaDados);
  await u.selectOptions(screen.getByLabelText("Coluna do código INEP"), "2");
  await u.selectOptions(screen.getByLabelText("Coluna do valor"), "4");
  await u.type(screen.getByLabelText("URL do arquivo oficial"), "https://exemplo.invalido/ideb.zip");
  await u.click(screen.getByRole("button", { name: /Salvar fonte automática/ }));
  await screen.findByText(/Fonte salva/);
  const chamada = api.mock.calls.find(([caminho, opcoes]) =>
    caminho === "/avaliacoes/fontes" && (opcoes as RequestInit | undefined)?.method === "POST");
  return JSON.parse(String((chamada![1] as RequestInit).body));
}

describe("Automatizar — as linhas do topo do arquivo conferido vão junto com a fonte", () => {
  it("manda as linhas do começo do arquivo até a linha antes dos dados, sem as células vazias", async () => {
    semear();
    const corpo = await salvarFonte("3");
    expect(corpo.mapeamento).toMatchObject({ linha_dados: 3, col_inep: 2, col_valor: 4 });
    expect(corpo.mapeamento.cabecalho).toEqual({ col_inep: "ID_ESCOLA", col_valor: "VL_OBSERVADO_2023" });
    expect(corpo.mapeamento.topo).toEqual([
      ["Ministério da Educação"],
      // a célula longa vai cortada no limite que o backend aceita (500 caracteres)
      ["Ensino Fundamental Regular - Anos Iniciais", LONGO.slice(0, 500)],
      ["SG_UF", "NO_MUNICIPIO", "ID_ESCOLA", "NO_ESCOLA", "VL_OBSERVADO_2023"],
    ]);
  });

  it("sem linha antes dos dados (índice 0), não manda topo", async () => {
    semear();
    const corpo = await salvarFonte("0");
    expect(corpo.mapeamento.topo).toBeUndefined();
  });
});
