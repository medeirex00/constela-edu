/**
 * "Automatizar" (a fonte do robô de avaliações) — auditoria S_G_INDICADORES-2. A fonte
 * guarda o cabeçalho de cada coluna mapeada como estava no arquivo conferido na tela, e o
 * backend confere a cada coleta que o arquivo da URL ainda é aquele (antes, o robô lia
 * pelas posições e gravava outra coluna, ou outra etapa, com status "ok").
 *
 * Arquivo, nomes, códigos e URL INVENTADOS.
 */
import { describe, expect, it } from "vitest";

import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import { api, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

function semear() {
  responder("GET", "/redes", [{ id: 1, nome: "Rede Inventada" }]);
  responder("GET", "/avaliacoes/fontes", []);
  responder("GET", "/redes/1/avaliacoes/opcoes", []);
  responder("GET", "/avaliacoes", [
    { chave: "ideb", nome: "IDEB", tipo: "indicador", orgao: "INEP", descricao: null },
  ]);
  responder("GET", "/avaliacoes/presets-import", []);
  responder("UPLOAD", "/avaliacoes/analisar", {
    linhas_lidas: 3, n_colunas: 3,
    primeiras_linhas: [["Resultados inventados"], ["CO_ESCOLA", "NO_ESCOLA", "IDEB_2023"],
                       ["35012345", "EM Inventada", "6,1"]],
  });
  responder("POST", "/avaliacoes/fontes", { id: 7 });
}

describe("Automatizar — o cabeçalho conferido vai junto com a fonte", () => {
  it("manda o texto do cabeçalho de cada coluna mapeada (a linha antes dos dados)", async () => {
    semear();
    const u = userEvent.setup();
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByText("Importar resultado oficial");
    const entradas = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="file"]'))
      .filter((e) => e.closest('[data-testid="cartao-ica"]') == null);
    await u.upload(entradas[1], new File(["x"], "ideb_inventado.csv", { type: "text/csv" }));
    await screen.findByText(/primeira linha de dados/);

    const linha = screen.getByLabelText("1ª linha de dados (índice)");
    await u.clear(linha);
    await u.type(linha, "2");
    await u.selectOptions(screen.getByLabelText("Coluna do valor"), "2");
    await u.type(screen.getByLabelText("URL do arquivo oficial"), "https://exemplo.invalido/ideb.csv");
    await u.click(screen.getByRole("button", { name: /Salvar fonte automática/ }));

    await screen.findByText(/Fonte salva/);
    const chamada = api.mock.calls.find(([caminho, opcoes]) =>
      caminho === "/avaliacoes/fontes" && (opcoes as RequestInit | undefined)?.method === "POST");
    const corpo = JSON.parse(String((chamada![1] as RequestInit).body));
    expect(corpo.mapeamento).toMatchObject({ linha_dados: 2, col_inep: 0, col_valor: 2 });
    expect(corpo.mapeamento.cabecalho).toEqual({ col_inep: "CO_ESCOLA", col_valor: "IDEB_2023" });
  });
});
