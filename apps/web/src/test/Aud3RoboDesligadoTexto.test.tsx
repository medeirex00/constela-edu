/**
 * Robô de avaliações desligado: a tela não promete a coleta automática (auditoria
 * S_G_INDICADORES-5). O robô AUTOMÁTICO vem desligado (decisão registrada) e a fonte
 * mensal só é coletada pelo "Coletar agora"; a tela dizia, sem condição, "O robô passa a
 * baixar e importar sozinho" e mostrava "próxima: <data>". A API agora diz em cada fonte se
 * o robô está ligado (`robo_habilitado`), e os textos seguem isso. O robô continua desligado.
 *
 * Fontes, nomes, códigos e URL INVENTADOS.
 */
import { describe, expect, it } from "vitest";

import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import { renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

function fonte(robo_habilitado: boolean) {
  return {
    id: 7, avaliacao: "ideb", avaliacao_nome: "IDEB", nome: "IDEB inventado 2023",
    url: "https://exemplo.invalido/ideb.csv", edicao: 2023, indicador: "ideb", unidade: "indice",
    cadencia: "mensal", ativo: true, mapeamento: { linha_dados: 1, col_inep: 0, col_valor: 1 },
    ultima_coleta: null, proxima_coleta: "2026-11-11T09:00:00", ultimo_status: "nunca",
    ultimo_erro: null, ultimo_resumo: null, robo_habilitado,
  };
}

function semear(fontes: unknown[] = []) {
  responder("GET", "/redes", [{ id: 1, nome: "Rede Inventada" }]);
  responder("GET", "/avaliacoes/fontes", fontes);
  responder("GET", "/redes/1/avaliacoes/opcoes", []);
  responder("GET", "/avaliacoes", [
    { chave: "ideb", nome: "IDEB", tipo: "indicador", orgao: "INEP", descricao: null },
  ]);
  responder("GET", "/avaliacoes/presets-import", []);
  responder("UPLOAD", "/avaliacoes/analisar", {
    linhas_lidas: 2, n_colunas: 2, primeiras_linhas: [["CO_ESCOLA", "IDEB_2023"], ["35012345", "6,1"]],
  });
}

async function salvarFonte() {
  const u = userEvent.setup();
  const { container } = renderComApp(<RedeAvaliacoes />, { usuario: admin });
  await screen.findByText("Importar resultado oficial");
  const entradas = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="file"]'))
    .filter((e) => e.closest('[data-testid="cartao-ica"]') == null);
  await u.upload(entradas[1], new File(["x"], "ideb_inventado.csv", { type: "text/csv" }));
  await screen.findByText(/primeira linha de dados/);
  // O quadro "Automatizar" não promete que o sistema baixa e importa sozinho.
  expect(container.textContent).not.toContain("O sistema passa a baixar dessa URL e importar sozinho");
  expect(container.textContent).toContain("só acontece com o robô ligado no servidor");
  await u.type(screen.getByLabelText("URL do arquivo oficial"), "https://exemplo.invalido/ideb.csv");
  await u.click(screen.getByRole("button", { name: /Salvar fonte automática/ }));
  return container;
}

describe("Robô de avaliações desligado — a tela diz a verdade", () => {
  it("salvar a fonte mensal com o robô desligado manda usar o “Coletar agora”", async () => {
    semear();
    responder("POST", "/avaliacoes/fontes", fonte(false));
    const container = await salvarFonte();
    expect(await screen.findByText(/A coleta automática está desligada neste servidor/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("O robô passa a baixar e importar sozinho");
  });

  it("com o robô ligado, a fonte mensal é coletada sozinha", async () => {
    semear();
    responder("POST", "/avaliacoes/fontes", fonte(true));
    await salvarFonte();
    expect(await screen.findByText("Fonte salva. O robô passa a baixar e importar sozinho, uma vez por mês."))
      .toBeInTheDocument();
  });

  it("na lista, a fonte mensal com o robô desligado não mostra “próxima”", async () => {
    semear([fonte(false)]);
    renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByText("IDEB inventado 2023");
    expect(screen.getByText(/coleta automática desligada: use “Coletar agora”/)).toBeInTheDocument();
    expect(screen.queryByText(/próxima:/)).toBeNull();
  });

  it("na lista, com o robô ligado, a fonte mensal mostra a próxima coleta", async () => {
    semear([fonte(true)]);
    renderComApp(<RedeAvaliacoes />, { usuario: admin });
    await screen.findByText("IDEB inventado 2023");
    expect(screen.getByText(/próxima:/)).toBeInTheDocument();
    expect(screen.queryByText(/coleta automática desligada/)).toBeNull();
  });
});
