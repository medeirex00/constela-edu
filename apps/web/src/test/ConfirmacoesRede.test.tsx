/**
 * Telas da rede — ações que apagam pedem confirmação no diálogo da v2 (`Confirmacao`),
 * não no `window.confirm` do navegador:
 *
 *  - "Remover edição" (Importações e fontes, só admin global): o diálogo diz QUAL série e
 *    edição sai; o DELETE só vai depois do "Remover edição"; "Cancelar" não chama a API;
 *  - remover uma fonte do robô: idem, com o nome da fonte;
 *  - remover uma meta da rede (aba Secretaria): antes removia num clique; agora o diálogo
 *    diz qual meta (rótulo e alvo exibidos) e a MESMA rota DELETE só vai depois do "sim".
 *
 * Redes, escolas, fontes, metas e números INVENTADOS.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("leaflet", () => ({ default: { divIcon: () => ({}) } }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({ setView: () => undefined, fitBounds: () => undefined }),
}));

import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import RedeDashboard from "../pages/rede/RedeDashboard";
import {
  api,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  waitFor,
  within,
} from "./utils";

const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });
const secretaria = usuarioFake({ nome: "Secretaria", rede_id: 7, cargo: "coordenador", escola_id: null });

/** Chamadas à API com o método pedido (o mock recebe `api(caminho, { method })`). */
const chamadas = (metodo: string) =>
  api.mock.calls.filter(([, opcoes]) => (opcoes as RequestInit | undefined)?.method === metodo);

// =============================================================================
// Importações e fontes (RedeAvaliacoes) — só o admin global vê estes controles
// =============================================================================

const OPCAO = { avaliacao: "ideb", nome: "IDEB", tipo: "indicador", indicador: "ideb",
                etapa: "anos_iniciais", componente: null, edicoes: [2031] };

const FONTE = {
  id: 5, avaliacao: "ideb", avaliacao_nome: "IDEB", nome: "IDEB 2031 sintético",
  url: "https://exemplo.invalido/ideb_2031.zip", edicao: 2031, indicador: "ideb", unidade: "indice",
  cadencia: "manual", ativo: true, mapeamento: { linha_dados: 1, col_inep: 0, col_valor: 1 },
  ultima_coleta: null, proxima_coleta: null, ultimo_status: "nunca", ultimo_erro: null, ultimo_resumo: null,
};

function semearAvaliacoes({ fontes = [] as unknown[] } = {}) {
  responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética" }]);
  responder("GET", "/redes/1/avaliacoes/opcoes", [OPCAO]);
  responder("GET", "/avaliacoes", [
    { chave: "ideb", nome: "IDEB", tipo: "indicador", orgao: "INEP", descricao: null },
  ]);
  responder("GET", "/avaliacoes/presets-import", []);
  responder("GET", "/avaliacoes/fontes", fontes);
}

describe("Remover uma edição importada — confirmação da v2", () => {
  it("abre o diálogo com a série e a edição; o DELETE só vai depois de confirmar", async () => {
    semearAvaliacoes();
    responder("DELETE", "/avaliacoes/resultados", { removidos: 3 });
    const usuario = userEvent.setup();
    renderComApp(<RedeAvaliacoes />, { usuario: admin });

    await usuario.click(await screen.findByRole("button", { name: /Remover edição 2031/ }));
    const dialogo = screen.getByRole("dialog", { name: "Remover esta edição?" });
    expect(dialogo).toHaveTextContent("Remover os resultados de “IDEB · ideb · anos_iniciais · edição 2031”?");
    expect(dialogo).toHaveTextContent("Apaga só ESTA série (não afeta outras edições, etapas nem componentes).");
    expect(chamadas("DELETE")).toHaveLength(0);

    await usuario.click(within(dialogo).getByRole("button", { name: "Remover edição" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      "/avaliacoes/resultados?avaliacao=ideb&edicao=2031&indicador=ideb&etapa=anos_iniciais",
      { method: "DELETE" }));
    expect(await screen.findByText("3 resultado(s) removido(s) da edição 2031.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancelar fecha o diálogo e não chama a API", async () => {
    semearAvaliacoes();
    const usuario = userEvent.setup();
    renderComApp(<RedeAvaliacoes />, { usuario: admin });

    await usuario.click(await screen.findByRole("button", { name: /Remover edição 2031/ }));
    const dialogo = screen.getByRole("dialog", { name: "Remover esta edição?" });
    await usuario.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(chamadas("DELETE")).toHaveLength(0);
  });

  it("a recusa do servidor aparece na tela e o diálogo fecha", async () => {
    semearAvaliacoes();
    responderErro("DELETE", "/avaliacoes/resultados", 409,
      "Série com importação oficial: desfaça pela própria importação.");
    const usuario = userEvent.setup();
    renderComApp(<RedeAvaliacoes />, { usuario: admin });

    await usuario.click(await screen.findByRole("button", { name: /Remover edição 2031/ }));
    await usuario.click(within(screen.getByRole("dialog", { name: "Remover esta edição?" }))
      .getByRole("button", { name: "Remover edição" }));
    expect(await screen.findByText("Série com importação oficial: desfaça pela própria importação."))
      .toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Remover uma fonte do robô — confirmação da v2", () => {
  it("abre o diálogo com o nome da fonte; o DELETE só vai depois de confirmar", async () => {
    semearAvaliacoes({ fontes: [FONTE] });
    responder("DELETE", "/avaliacoes/fontes/5", null);
    const usuario = userEvent.setup();
    renderComApp(<RedeAvaliacoes />, { usuario: admin });

    await usuario.click(await screen.findByRole("button", { name: "Remover a fonte IDEB 2031 sintético" }));
    const dialogo = screen.getByRole("dialog", { name: "Remover a fonte automática?" });
    expect(dialogo).toHaveTextContent("Remover a fonte “IDEB 2031 sintético”? Os resultados já importados permanecem.");
    expect(chamadas("DELETE")).toHaveLength(0);

    await usuario.click(within(dialogo).getByRole("button", { name: "Remover fonte" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/avaliacoes/fontes/5", { method: "DELETE" }));
    expect(await screen.findByText("Fonte removida.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancelar fecha o diálogo e não chama a API", async () => {
    semearAvaliacoes({ fontes: [FONTE] });
    const usuario = userEvent.setup();
    renderComApp(<RedeAvaliacoes />, { usuario: admin });

    await usuario.click(await screen.findByRole("button", { name: "Remover a fonte IDEB 2031 sintético" }));
    const dialogo = screen.getByRole("dialog", { name: "Remover a fonte automática?" });
    await usuario.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(chamadas("DELETE")).toHaveLength(0);
  });
});

// =============================================================================
// Secretaria (RedeDashboard) — metas da rede
// =============================================================================

const META = {
  id: 11, metrica: "pontuacao_geral", rotulo: "Índice da rede (0–1000)", sufixo: "", alvo: 640,
  atual: 512, progresso: 80, atingida: false, descricao: null,
  escolas_atingiram: 1, escolas_total: 3, comparavel: true,
};

function semearSecretaria() {
  responder("GET", "/redes/7/dashboard", {
    rede_id: 7,
    modulos: ["leitura", "matematica"],
    totais: {
      escolas: 0, escolas_ativas: 0, alunos: 0, turmas: 0, professores: 0,
      alunos_com_dados: 0, adocao: 0, media_geral: 0, media_matific: 0, media_elefante: 0,
      pontuacao_geral: 0, escolas_em_atencao: 0, livros: 0, tempo_leitura_min: 0, atividades: 0,
      estrelas: 0, ativos_matific: 0, ativos_elefante: 0, livros_por_aluno: 0, melhor_escola: null,
    },
    equidade: {
      gap_indice: 0, escola_maior_indice: 0, escola_menor_indice: 0, escolas_abaixo_do_indice_medio: 0,
      gap_media: 0, escola_maior_media: 0, escola_menor_media: 0, escolas_abaixo_da_media: 0,
    },
    escolas: [],
    atencao: [],
  });
  responder("GET", "/redes/7/metas", [META]);
  responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
}

describe("Metas da rede — remover pede confirmação", () => {
  it("remover abre o diálogo com a meta exibida, sem chamar a API", async () => {
    semearSecretaria();
    const usuario = userEvent.setup();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });

    await usuario.click(await screen.findByRole("button", { name: "Remover a meta Índice da rede (0–1000)" }));
    const dialogo = screen.getByRole("dialog", { name: "Remover esta meta?" });
    // O mesmo rótulo e o mesmo alvo da linha (nota(640) = "640,0").
    expect(dialogo).toHaveTextContent("A meta Índice da rede (0–1000) (alvo 640,0) sai da rede");
    expect(within(dialogo).getByRole("button", { name: "Remover meta" })).toBeEnabled();
    expect(chamadas("DELETE")).toHaveLength(0);
  });

  it("confirmar chama a MESMA rota DELETE da meta e mostra o resultado", async () => {
    semearSecretaria();
    responder("DELETE", "/redes/7/metas/pontuacao_geral", []);
    const usuario = userEvent.setup();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });

    await usuario.click(await screen.findByRole("button", { name: "Remover a meta Índice da rede (0–1000)" }));
    await usuario.click(within(screen.getByRole("dialog", { name: "Remover esta meta?" }))
      .getByRole("button", { name: "Remover meta" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/redes/7/metas/pontuacao_geral", { method: "DELETE" }));
    expect(chamadas("DELETE")).toHaveLength(1);
    expect(await screen.findByText("Meta “Índice da rede (0–1000)” removida.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancelar fecha o diálogo e não chama a API", async () => {
    semearSecretaria();
    const usuario = userEvent.setup();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });

    await usuario.click(await screen.findByRole("button", { name: "Remover a meta Índice da rede (0–1000)" }));
    const dialogo = screen.getByRole("dialog", { name: "Remover esta meta?" });
    await usuario.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(chamadas("DELETE")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Remover a meta Índice da rede (0–1000)" })).toBeEnabled();
  });

  it("a falha do DELETE aparece na tela (não some em silêncio)", async () => {
    semearSecretaria();
    responderErro("DELETE", "/redes/7/metas/pontuacao_geral", 500, "Falha sintética ao remover.");
    const usuario = userEvent.setup();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });

    await usuario.click(await screen.findByRole("button", { name: "Remover a meta Índice da rede (0–1000)" }));
    await usuario.click(within(screen.getByRole("dialog", { name: "Remover esta meta?" }))
      .getByRole("button", { name: "Remover meta" }));
    expect(await screen.findByText("Falha sintética ao remover.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
