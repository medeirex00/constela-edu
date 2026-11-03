/**
 * Indicadores oficiais por PERFIL (etapa E9 — decisões D4 e D5 do dono, 17/10):
 *
 *  - menu: a área dos indicadores (/rede/avaliacoes) fica DENTRO de "Avaliações externas"
 *    para a Secretaria (DESENHO3 §1: o menu dela tem só as três áreas) — ela chega lá pelo
 *    link "Arquivos oficiais de cada número" e o item "Avaliações externas" continua aceso; o
 *    h1 da tela continua "Fontes dos indicadores". O admin global tem o item ("Importações e
 *    fontes"); o coordenador e o professor não têm;
 *  - tela da rede: a Secretaria LÊ (cartões; nada de link para as Análises avançadas, que
 *    saíram do menu dela), mas não vê importar, "Remover edição" nem o robô — só o admin
 *    global vê esses controles;
 *  - o componente "Indicadores oficiais da escola" mostra SÓ a escola (SARESP,
 *    Ideb/Saeb), as referências da rede/SP/Brasil e o ICA como indicador DA REDE, com o
 *    selo de fonte e o motivo de cada ausência (nunca 0); o professor não a vê (nem a
 *    API é chamada). Na Visão da Escola, a seção agora é a "Análise educacional da escola"
 *    (`AnaliseDaEscola`): a troca de escola continua sem mostrar números da anterior.
 *
 * Números, nomes, códigos, datas e arquivos SINTÉTICOS — os mesmos INVENTADOS dos testes
 * das abas (nada dos arquivos do INEP nem da SEDUC — D13).
 */
import { describe, expect, it } from "vitest";

import App from "../App";
import Layout from "../components/Layout";
import type { FonteOficial } from "../components/SeloFonte";
import { useApp } from "../context/AppContext";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import IndicadoresDaEscola, { type RespostaIndicadoresEscola } from "../pages/IndicadoresDaEscola";
import VisaoEscola from "../pages/VisaoEscola";
import type { RespostaAnaliseEscola } from "../pages/analise/tipos";
import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import { semearSecretaria } from "./SecretariaFixtures";
import {
  api, escolaFake, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor, within,
} from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const coordenador = usuarioFake({ nome: "Coordenadora", cargo: "coordenador", escola_id: 1 });
const professor = usuarioFake({ nome: "Professora", cargo: "professor", escola_id: 1 });
const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

// =============================================================================
// Menu
// =============================================================================

function LayoutReal() {
  return (
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>
  );
}

function escolaConfigurada() {
  responder("GET", "/escolas/1/sync/onboarding", { lista_piloto_importada: true });
}

describe("Menu — os indicadores da rede por perfil (D5)", () => {
  // DESENHO3 §1: o menu da Secretaria tem só as três áreas. As fontes dos indicadores
  // (/rede/avaliacoes) não têm item próprio: moram dentro de "Avaliações externas".
  it("a Secretaria não tem item próprio das fontes nem o Painel da Rede: as fontes ficam em Avaliações externas", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { rota: "/", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    const menu = await screen.findByRole("navigation", { name: "Menu principal" });
    expect(await within(menu).findByRole("link", { name: "Avaliações externas" }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas");
    const destinos = screen.queryAllByRole("link").map((l) => l.getAttribute("href"));
    expect(destinos).not.toContain("/rede/avaliacoes");
    expect(destinos).not.toContain("/rede");
    expect(screen.queryAllByRole("link", { name: /Fontes e arquivos oficiais|Fontes dos indicadores|Importações e fontes/ }))
      .toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Painel da Rede" })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: "Análises avançadas" })).toHaveLength(0);
  });

  it("a Secretaria chega às fontes pelo link 'Arquivos oficiais de cada número', com Avaliações externas acesa", async () => {
    escolaConfigurada();
    semearSecretaria();
    semearRede([OPCAO]);
    renderComApp(<App />, { rota: "/rede/avaliacoes-externas", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    const menu = await screen.findByRole("navigation", { name: "Menu principal" }, { timeout: 4000 });
    const acesos = () => Array.from(menu.querySelectorAll("a[aria-current]")).map((a) => a.getAttribute("href"));
    const fontes = await screen.findByRole("link", { name: /Arquivos oficiais de cada número/ }, { timeout: 4000 });
    expect(fontes).toHaveAttribute("href", "/rede/avaliacoes");
    expect(acesos()).toEqual(["/rede/avaliacoes-externas"]);
    await userEvent.click(fontes);
    expect(await screen.findByRole("heading", { level: 1, name: "Fontes dos indicadores" }, { timeout: 4000 }))
      .toBeInTheDocument();
    // Nas fontes, a área dela continua acesa e a trilha diz onde ela está.
    expect(acesos()).toEqual(["/rede/avaliacoes-externas"]);
    const trilha = screen.getByRole("navigation", { name: "Trilha de navegação" });
    expect(Array.from(trilha.querySelectorAll("a, span")).map((el) => el.textContent))
      .toEqual(["Panorama da Rede", "Rede municipal", "Fontes dos indicadores"]);
  });

  it("o admin global também tem o item", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { rota: "/", usuario: admin, escolas: [escolaFake({ id: 1 })] });
    const links = await screen.findAllByRole("link", { name: "Importações e fontes" });
    expect(links[0]).toHaveAttribute("href", "/rede/avaliacoes");
  });

  it.each([["coordenador", coordenador], ["professor", professor]])(
    "o %s não tem o item (a escola lê os indicadores na Visão da Escola)", async (_nome, usuario) => {
      escolaConfigurada();
      renderComApp(<LayoutReal />, { rota: "/", usuario, escolas: [escolaFake({ id: 1 })] });
      // A sessão abriu (nome no cartão do usuário) e o menu do perfil está montado: a
      // página inicial agora se chama "Visão geral" (D4, era "Dashboard"/"Meu Dashboard").
      await screen.findAllByText(usuario.nome);
      await screen.findAllByRole("link", { name: "Visão geral" });
      expect(screen.queryAllByRole("link").map((l) => l.getAttribute("href"))).not.toContain("/rede/avaliacoes");
    });
});

// =============================================================================
// Tela da rede — controles por perfil
// =============================================================================

const OPCAO = { avaliacao: "ideb", nome: "IDEB", tipo: "indicador", indicador: "ideb",
                etapa: "anos_iniciais", componente: null, edicoes: [2023] };

function semearRede(opcoes: unknown[] = []) {
  responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética" }]);
  responder("GET", "/redes/1/avaliacoes/opcoes", opcoes);
  responder("GET", "/avaliacoes", [
    { chave: "ideb", nome: "IDEB", tipo: "indicador", orgao: "INEP", descricao: null },
  ]);
  responder("GET", "/avaliacoes/presets-import", [
    { chave: "ideb_ai", rotulo: "IDEB — Anos Iniciais", avaliacao: "ideb", dica: "Suba o .zip oficial." },
  ]);
  responder("GET", "/avaliacoes/fontes", []);
}

describe("Avaliações externas — controles de importação por perfil (D4)", () => {
  it("a Secretaria lê, mas não vê importar, remover edição nem o robô", async () => {
    semearRede([OPCAO]);
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByRole("heading", { name: "Fontes dos indicadores" })).toBeInTheDocument();
    // A leitura continua; o resumo é o de Avaliações externas. Nada de link para as Análises
    // avançadas, que saíram do menu dela.
    expect(await screen.findByRole("link", { name: /Voltar para Avaliações externas/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas");
    expect(screen.queryByRole("link", { name: "Análises avançadas" })).not.toBeInTheDocument();
    await waitFor(() => expect(api.mock.calls.some(([c]) => String(c) === "/redes/1/avaliacoes/opcoes")).toBe(true));
    expect(screen.queryByText("Importar em 1 clique")).not.toBeInTheDocument();
    expect(screen.queryByText("Importar resultado oficial")).not.toBeInTheDocument();
    expect(screen.queryByText("Coleta automática (robô)")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remover edição/ })).not.toBeInTheDocument();
    expect(container.querySelectorAll('input[type="file"]')).toHaveLength(0);
    // Nem pede a lista do robô (rota só do admin global).
    expect(api.mock.calls.some(([c]) => String(c).startsWith("/avaliacoes/fontes"))).toBe(false);
  });

  it("sem resultado importado, a Secretaria lê quem importa (não 'importe abaixo')", async () => {
    semearRede([]);
    renderComApp(<RedeAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByText(/importados pelo administrador global/)).toBeInTheDocument();
    expect(screen.queryByText(/Importe um arquivo oficial abaixo/)).not.toBeInTheDocument();
  });

  it("o admin global vê importar, remover edição e o robô", async () => {
    semearRede([OPCAO]);
    renderComApp(<RedeAvaliacoes />, { usuario: admin });
    expect(await screen.findByText("Importar em 1 clique")).toBeInTheDocument();
    expect(await screen.findByText("Importar resultado oficial")).toBeInTheDocument();
    expect(await screen.findByText("Coleta automática (robô)")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Remover edição 2023/ })).toBeInTheDocument();
  });
});

// =============================================================================
// Visão da Escola — a seção dos indicadores oficiais
// =============================================================================

function fonte(over: Partial<FonteOficial> = {}): FonteOficial {
  return {
    importacao_id: 31, fonte_nome: "SEDUC-SP — Índice de Excelência Educacional (IEE)",
    arquivo_nome: "Indice de Excelencia Educacional 2025-2026_0.csv", arquivo_data: null,
    last_modified_origem: "Mon, 12 Jan 2026 09:00:00 GMT", url_origem: null, edicao_arquivo: 2025,
    versao_rotulo: null, importado_em: "2026-10-17T12:00:00", coletado_em: null, citacao: null,
    licenca: "Dados abertos da SEDUC-SP: uso livre, com citação obrigatória.",
    parser: "seduc_iee", modo: "upload", notas: [], data_arquivo: "2026-01-12",
    data_arquivo_origem: "last_modified", ...over,
  };
}
const FIEE = fonte();
const FMUN = fonte({ importacao_id: 21, fonte_nome: "SEDUC-SP — Proficiência do SARESP por município",
  arquivo_nome: "Proficiência do SARESP por Municipio de 2025_0.csv", parser: "seduc_saresp_municipio" });
// Um arquivo cujo número NÃO aparece na seção (outra edição): fica fora do selo.
const FNAO = fonte({ importacao_id: 22, arquivo_nome: "Proficiência do SARESP por Municipio de 2022_0.csv",
  parser: "seduc_saresp_municipio", edicao_arquivo: 2022 });
const FIDEB = fonte({ importacao_id: 41, fonte_nome: "INEP — Ideb por escola, anos iniciais",
  arquivo_nome: "pacote_ideb_sintetico.zip", parser: "inep_ideb_escolas", arquivo_data: "2031-06-02T08:15:00",
  edicao_arquivo: 2023, licenca: "INEP: citar a fonte." });
const FICA = fonte({ importacao_id: 5, fonte_nome: "INEP — Indicador Criança Alfabetizada",
  arquivo_nome: "resultados_e_metas_municipios_2025_3.xlsx", parser: "inep_ica_municipios",
  arquivo_data: "2031-05-20T10:30:00" });

// Participação da escola (2º e 5º ano) — INVENTADA; a asserção a escreve pela formatação.
const PART_2 = 72.4;
const PART_5 = 68.9;
const umaCasa = (v: number) => v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

const A_CONFIRMAR = { situacao: "a_confirmar", nivel: null, distancia_adequado: null, calculo_do_constela: true };
function prof(edicao: number, valor: number | null, f: FonteOficial, casas = 1, unidade = "escala_saresp") {
  return { edicao, valor, casas_decimais: valor == null ? null : casas, unidade,
           motivo_ausencia: valor == null ? "nao_divulgado" : null, fonte: f, nivel: A_CONFIRMAR };
}
function terr(chave: string, rotulo: string, mesma: boolean, v: [number, number, number, number] | null) {
  const pares: [string, string][] = [["2_ano", "lp"], ["2_ano", "mt"], ["5_ano", "lp"], ["5_ano", "mt"]];
  return {
    chave, abrangencia: chave.startsWith("estado") ? "uf" : "municipio", codigo_territorio: "3599999",
    rede_ensino: mesma ? "municipal" : "estadual", mesma_rede: mesma, nome: null, rotulo,
    series: pares.map(([etapa, componente], i) => ({ etapa, componente, numeros: v ? [prof(2025, v[i], FMUN)] : [] })),
    tem_dados: Boolean(v),
  };
}
function numI(valor: number | null, casas: number, fonteId: number | null = 41) {
  return { valor, casas_decimais: valor == null ? null : casas, motivo_ausencia: valor == null ? "nao_divulgado" : null,
           proveniencia: "oficial" as const, fonte_id: fonteId };
}
const VAZIO_APROV = { anos_iniciais: null, "1_ano": null, "2_ano": null, "3_ano": null, "4_ano": null, "5_ano": null };
function edIdeb(edicao: number, ideb: number | null, lp: number | null, mt: number | null, extra = {}) {
  return { edicao, ideb: numI(ideb, 1), saeb_lp: numI(lp, 2), saeb_mt: numI(mt, 2), nota_n: null,
           rendimento_p: null, aprovacao: VAZIO_APROV, meta: null, sem_meta: "depois_do_1o_ciclo",
           comparacao_meta: null, variacao_ideb: null, no_arquivo: true, tem_ideb: ideb != null,
           tem_saeb: lp != null, motivo: ideb == null ? "nao_divulgado" : null, fonte_da_edicao_id: 41, ...extra };
}
function numP(edicao: number, valor: number, f: FonteOficial) {
  return { edicao, valor, casas_decimais: 0, operador: null, unidade: "percentual", motivo_ausencia: null,
           fonte: f, detalhe: null };
}
// Os microdados (SP só nas redes municipais): outro arquivo, sem meta.
const FAEEB = fonte({ importacao_id: 7, fonte_nome: "INEP — Microdados da avaliação da alfabetização",
  arquivo_nome: "pacote_aeeb_sintetico.zip", parser: "inep_aeeb_agregados", arquivo_data: "2031-04-11T08:00:00" });
function terrIca(abrangencia: "municipio" | "uf" | "brasil", nome: string, res: number, meta: number | null,
                 rede = abrangencia === "municipio" ? "municipal" : "publica", f: FonteOficial = FICA) {
  const r = numP(2025, res, f);
  const m = meta == null ? null : numP(2025, meta, f);
  return { abrangencia, codigo_territorio: "x", nome, rede_ensino: rede,
           resultados: [r], metas: m ? [m] : [], nivel: [], participacao: [], comparacoes: [],
           destaque: { resultado: r, meta: m, comparacao: null }, tem_dados: true };
}

function respostaEscola(over: Partial<RespostaIndicadoresEscola> = {}): RespostaIndicadoresEscola {
  return {
    escola: { id: 1, nome: "EMEF Sintética Alfa", codigo_inep: "35990001", status: "ativa", pendencia: null },
    rede: { id: 1, nome: "Rede Sintética", codigo_ibge: "3599999", municipio: "Cidade Sintetica" },
    avisos: {
      escopo: "Esta seção mostra só esta escola, com as referências da rede municipal, do Estado de São Paulo e do "
        + "Brasil. Não é ranking: as outras escolas não aparecem.",
      ica_da_rede: "O ICA é da REDE municipal: o INEP não publica o ICA por escola.",
    },
    pendencias: [],
    saresp: {
      avisos: { escala: "O SARESP tem escala própria, da SEDUC-SP.", tps: "TPS = 0: a média da escola é instável." },
      edicoes: [2025, 2024],
      por_edicao: [
        { edicao: 2025,
          proficiencia: { "2_ano": { lp: prof(2025, 148.3, FIEE), mt: prof(2025, 139.6, FIEE) },
                          "5_ano": { lp: prof(2025, null, FIEE), mt: prof(2025, 196.8, FIEE) } },
          participacao: { "2_ano": prof(2025, PART_2, FIEE, 1, "percentual"),
                          "5_ano": prof(2025, PART_5, FIEE, 1, "percentual") },
          tps: prof(2025, 1, FIEE, 0, "binario"), iee: prof(2025, 5.12, FIEE, 2, "indice"),
          meta: prof(2025, 5.46, FIEE, 2, "indice"), icm: null, tem_resultado: true, no_arquivo: true,
          motivo: null, tem_estimativa: false, fonte_da_edicao: FIEE },
        { edicao: 2024,
          proficiencia: { "2_ano": { lp: null, mt: null }, "5_ano": { lp: null, mt: null } },
          participacao: { "2_ano": null, "5_ano": null }, tps: null, iee: null, meta: null, icm: null,
          tem_resultado: false, no_arquivo: false, motivo: "fora_do_arquivo", tem_estimativa: false,
          fonte_da_edicao: null },
      ] as unknown as NonNullable<RespostaIndicadoresEscola["saresp"]>["por_edicao"],
      territorios: [
        terr("rede_municipal", "Cidade Sintetica — rede municipal", true, [137.1, 131.2, 249.4, 263.3]),
        terr("estado_redes_municipais", "Estado de São Paulo — redes municipais", true, [139.2, 133.9, 247.8, 259.4]),
        terr("estado_rede_estadual", "Estado de São Paulo — rede estadual", false, null),
      ] as unknown as NonNullable<RespostaIndicadoresEscola["saresp"]>["territorios"],
      edicoes_rede: [2025], fontes: [FIEE, FMUN, FNAO], tem_dados_escola: true, tem_dados: true,
    },
    ideb: {
      avisos: { comparabilidade: "A série do Ideb e do Saeb do 5º ano não é comparável em todo o período." },
      edicoes: [2019, 2021, 2023], anos_meta: [2019, 2021],
      serie: [
        edIdeb(2019, 1.5, 124.83, 131.47, { meta: numI(2.3, 1), sem_meta: null,
          comparacao_meta: { observado: 1.5, meta: 2.3, diferenca: -0.8, casas_decimais: 1, situacao: "nao_atingiu" } }),
        edIdeb(2021, 1.6, 127.61, 133.29),
        edIdeb(2023, null, null, null),
      ] as unknown as NonNullable<RespostaIndicadoresEscola["ideb"]>["serie"],
      participacao: { disponivel: false, decisao: "D8", texto: "A participação por escola depende da decisão D8." },
      rede_municipal: {
        ideb: {
          territorios: [
            { chave: "rede_municipal", rotulo: "Cidade Sintética — rede municipal", contexto: false, rotulo_contexto: null,
              tem_dados: true, serie: [{ edicao: 2025, ideb: numI(1.6, 1) }] },
            { chave: "uf_rede_publica", rotulo: "São Paulo — rede pública", contexto: true,
              rotulo_contexto: "outra rede — só contexto", tem_dados: true, serie: [{ edicao: 2025, ideb: numI(1.9, 1) }] },
          ],
          edicoes: [2025], anos_meta: [], uf_sem_rede_municipal: true, texto_uf_sem_rede_municipal: null, tem_dados: true,
        },
        saeb: {
          territorios: [{ chave: "rede_municipal", rotulo: "Cidade Sintética — rede municipal", tem_dados: true,
                          edicoes: [{ edicao: 2025, media: { lp: numI(102.81, 2), mt: numI(109.93, 2) } }] }],
          edicoes: [2025], tem_dados: true,
        },
        avisos: {}, tem_dados: true,
      } as unknown as NonNullable<RespostaIndicadoresEscola["ideb"]>["rede_municipal"],
      fontes: [FIDEB], tem_dados_escola: true, tem_dados: true,
    },
    ica: {
      papel: "referencia_da_rede",
      aviso: "O Indicador Criança Alfabetizada (ICA) é da REDE municipal: o INEP não publica o ICA por escola. O "
        + "número aparece só como referência da rede — não é o resultado desta escola.",
      aviso_rede: "O ICA é o indicador da REDE municipal.",
      territorios: [terrIca("municipio", "Cidade Sintética", 30, 32), terrIca("uf", "São Paulo", 34, 33),
                    terrIca("brasil", "Brasil", 23, 23)] as unknown as NonNullable<RespostaIndicadoresEscola["ica"]>["territorios"],
      uf_municipal: terrIca("uf", "São Paulo", 27, null, "municipal", FAEEB) as unknown as
        NonNullable<RespostaIndicadoresEscola["ica"]>["territorios"][number],
      fontes: [FICA, FAEEB], tem_dados: true,
    },
    tem_dados_escola: true, tem_dados: true,
    ...over,
  };
}

describe("Visão da Escola — Indicadores oficiais da escola (D5)", () => {
  it("o coordenador vê os números da escola, as referências e o ICA como indicador da rede", async () => {
    responder("GET", "/escolas/1/indicadores", respostaEscola());
    renderComApp(<IndicadoresDaEscola escolaId={1} />, { usuario: coordenador });
    const secao = await screen.findByTestId("indicadores-escola-saresp");
    expect(screen.getByRole("heading", { name: /Indicadores oficiais da escola/ })).toBeInTheDocument();
    expect(screen.getByTestId("indicadores-escola-nome")).toHaveTextContent("EMEF Sintética Alfa");
    expect(screen.getByText(/as outras escolas não aparecem/)).toBeInTheDocument();
    // SARESP da escola: na precisão publicada; a ausência com o motivo (nunca 0).
    const tabela = within(secao).getByRole("table", { name: /SARESP oficial da escola/ });
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas[1]).toHaveTextContent("2025");
    expect(linhas[1]).toHaveTextContent("148,3");
    expect(linhas[1]).toHaveTextContent("196,8");
    expect(linhas[1]).toHaveTextContent("não divulgado no arquivo oficial");
    expect(linhas[1]).toHaveTextContent(`${umaCasa(PART_2)}% / ${umaCasa(PART_5)}%`);
    expect(linhas[1]).toHaveTextContent("5,12 (5,46)");
    expect(linhas[1]).toHaveTextContent("atingiu");          // o TPS por extenso, nunca o 1 cru
    expect(linhas[1]).not.toHaveTextContent(/\b0,0\b/);
    expect(linhas[2]).toHaveTextContent("Sem resultado: a escola não está no arquivo oficial importado desta edição");
    // Referências: rede municipal e Estado (mesma rede); a rede estadual sem dado não aparece.
    const refs = within(secao).getByTestId("indicadores-escola-saresp-referencias");
    expect(refs).toHaveTextContent("Referências — SARESP 2025");
    expect(refs).toHaveTextContent("Cidade Sintetica — rede municipal");
    expect(refs).toHaveTextContent("249,4");
    expect(refs).toHaveTextContent("Estado de São Paulo — redes municipais");
    expect(refs).not.toHaveTextContent("rede estadual");
    const selo = within(secao).getByTestId("indicadores-escola-saresp-fonte");
    expect(selo).toHaveTextContent("Indice de Excelencia Educacional 2025-2026_0.csv");
    expect(selo).toHaveTextContent("Proficiência do SARESP por Municipio de 2025_0.csv");   // a referência
    expect(selo).not.toHaveTextContent("de 2022_0.csv");      // só os arquivos dos números mostrados
    // Ideb e Saeb: meta × observado; a ausência com o motivo; referências da rede.
    const ideb = screen.getByTestId("indicadores-escola-ideb");
    const tIdeb = within(ideb).getByRole("table", { name: /Ideb e Saeb oficiais da escola/ });
    const lIdeb = within(tIdeb).getAllByRole("row");
    expect(lIdeb[1]).toHaveTextContent("2023");
    expect(lIdeb[1]).toHaveTextContent("não divulgado");
    expect(lIdeb[3]).toHaveTextContent("2019");
    expect(lIdeb[3]).toHaveTextContent("1,5");
    expect(lIdeb[3]).toHaveTextContent("não atingiu (−0,8)");
    expect(lIdeb[3]).toHaveTextContent("124,83");
    const refsIdeb = within(ideb).getByTestId("indicadores-escola-ideb-referencias");
    expect(refsIdeb).toHaveTextContent("Ideb — Cidade Sintética — rede municipal: 1,6 (2025)");
    expect(refsIdeb).toHaveTextContent("outra rede — só contexto");
    expect(refsIdeb).toHaveTextContent("LP 102,81 · MT 109,93 (2025)");
    expect(within(ideb).getByTestId("indicadores-escola-ideb-fonte")).toHaveTextContent("pacote_ideb_sintetico.zip");
    // ICA: indicador DA REDE, nunca "da escola".
    const ica = screen.getByTestId("indicadores-escola-ica");
    expect(within(ica).getByRole("heading", { name: /indicador da rede/ })).toBeInTheDocument();
    expect(ica).toHaveTextContent("o INEP não publica o ICA por escola");
    // Plano 4.8: a mesma rede primeiro (SP só nas redes municipais); SP e Brasil na rede
    // pública por último, rotulados como outra rede.
    const itensIca = within(within(ica).getByTestId("indicadores-escola-ica-territorios")).getAllByRole("listitem");
    expect(itensIca.map((li) => li.textContent)).toEqual([
      "Cidade Sintética (rede municipal): 30% (2025) · meta 32%",
      "São Paulo (redes municipais): 27% (2025)",
      "São Paulo (rede pública): 34% (2025) · meta 33% · outra rede — só contexto",
      "Brasil (rede pública): 23% (2025) · meta 23% · outra rede — só contexto",
    ]);
    expect(within(ica).getByTestId("indicadores-escola-ica-outra-rede")).toHaveTextContent("não é a mesma rede");
    const seloIca = within(ica).getByTestId("indicadores-escola-ica-fonte");
    expect(seloIca).toHaveTextContent("resultados_e_metas_municipios_2025_3.xlsx");
    expect(seloIca).toHaveTextContent("pacote_aeeb_sintetico.zip");     // a fonte de SP (redes municipais)
    // Sem ranking: nenhuma lista de outras escolas.
    expect(screen.queryByText(/Sintética Beta/)).not.toBeInTheDocument();
  });

  it("a Secretaria também vê a seção da escola que selecionou", async () => {
    responder("GET", "/escolas/1/indicadores", respostaEscola());
    renderComApp(<IndicadoresDaEscola escolaId={1} />, { usuario: secretaria });
    expect(await screen.findByTestId("indicadores-escola-saresp")).toBeInTheDocument();
  });

  it("o professor não vê a seção e a API nem é chamada", async () => {
    responder("GET", "/escolas/1/indicadores", respostaEscola());
    renderComApp(
      <><p>tela</p><IndicadoresDaEscola escolaId={1} /></>, { usuario: professor });
    expect(await screen.findByText("tela")).toBeInTheDocument();
    expect(screen.queryByTestId("indicadores-escola")).not.toBeInTheDocument();
    expect(api.mock.calls.some(([c]) => String(c).includes("/indicadores"))).toBe(false);
  });

  it("a recusa da API aparece (não some em silêncio)", async () => {
    responderErro("GET", "/escolas/1/indicadores", 403, "Acesso negado aos dados desta escola.");
    renderComApp(<IndicadoresDaEscola escolaId={1} />, { usuario: coordenador });
    expect(await screen.findByText(/Acesso negado aos dados desta escola/)).toBeInTheDocument();
  });

  it("sem nada importado, diz isso; escola sem INEP e sem rede mostram a pendência", async () => {
    responder("GET", "/escolas/1/indicadores", respostaEscola({
      escola: { id: 1, nome: "EMEF Sintética Alfa", codigo_inep: null, status: "ativa", pendencia: "codigo_inep" },
      pendencias: ["codigo_inep"], saresp: null, ideb: null, ica: null, tem_dados: false, tem_dados_escola: false,
    }));
    renderComApp(<IndicadoresDaEscola escolaId={1} />, { usuario: coordenador });
    expect(await screen.findByTestId("indicadores-escola-vazio")).toHaveTextContent("Nenhum indicador oficial");
    expect(screen.getByTestId("indicadores-escola-sem-inep")).toHaveTextContent("sem código INEP");
  });

  it("participação, TPS, IEE e meta sem número dizem o motivo; a estimativa da D2 não vira código interno",
    async () => {
      const r = respostaEscola();
      const ed = r.saresp!.por_edicao[0];
      ed.participacao["2_ano"] = prof(2025, null, FIEE, 1, "percentual") as typeof ed.participacao["2_ano"];
      ed.tps = prof(2025, 0, FIEE, 0, "binario") as typeof ed.tps;
      ed.iee = prof(2025, null, FIEE, 2, "indice") as typeof ed.iee;
      ed.meta = { ...prof(2025, null, FIEE, 2, "indice"), motivo_ausencia: "participacao_baixa" } as typeof ed.meta;
      ed.proficiencia["5_ano"].lp = { ...prof(2025, null, FIEE), motivo_ausencia: "estimativa_mantida_d2" } as
        typeof ed.proficiencia["5_ano"]["lp"];
      responder("GET", "/escolas/1/indicadores", r);
      renderComApp(<IndicadoresDaEscola escolaId={1} />, { usuario: coordenador });
      const secao = await screen.findByTestId("indicadores-escola-saresp");
      const linha = within(within(secao).getByRole("table", { name: /SARESP oficial da escola/ })).getAllByRole("row")[1];
      const celulas = within(linha).getAllByRole("cell");
      const [part, tps, iee] = celulas.slice(-3);
      expect(part).toHaveTextContent(`—não divulgado no arquivo oficial / ${umaCasa(PART_5)}%`);
      expect(tps).toHaveTextContent("não atingiu");
      expect(tps).toHaveTextContent("média instável");
      expect(tps).not.toHaveTextContent(/^0$/);
      expect(iee).toHaveTextContent("não divulgado no arquivo oficial");
      expect(iee).toHaveTextContent("meta: sem resultado (participação baixa)");
      expect(linha).toHaveTextContent("o número oficial desta edição ainda não foi gravado no Constela");
      expect(linha).not.toHaveTextContent(/D2/);
      expect(secao).toHaveTextContent("TPS = 0");               // o aviso da API sobre o TPS 0
    });

  it("rede sem código IBGE: diz a causa, não 'nada importado'", async () => {
    responder("GET", "/escolas/1/indicadores", respostaEscola({
      rede: { id: 1, nome: "Rede Sintética", codigo_ibge: null, municipio: null },
      pendencias: ["codigo_ibge"], saresp: null, ideb: null, ica: null, tem_dados: false, tem_dados_escola: false,
    }));
    renderComApp(<IndicadoresDaEscola escolaId={1} />, { usuario: coordenador });
    expect(await screen.findByTestId("indicadores-escola-sem-ibge")).toHaveTextContent("sem o código IBGE");
    expect(screen.queryByTestId("indicadores-escola-vazio")).not.toBeInTheDocument();
  });

  it("escola sem rede: o aviso da API, sem referência inventada", async () => {
    responder("GET", "/escolas/1/indicadores", respostaEscola({
      rede: null, pendencias: ["sem_rede"], saresp: null, ideb: null, ica: null, tem_dados: false,
      tem_dados_escola: false,
      avisos: { escopo: "Só esta escola.", sem_rede: "A escola não está vinculada a uma rede no cadastro." },
    }));
    renderComApp(<IndicadoresDaEscola escolaId={1} />, { usuario: coordenador });
    expect(await screen.findByText(/não está vinculada a uma rede/)).toBeInTheDocument();
    expect(screen.queryByTestId("indicadores-escola-ica")).not.toBeInTheDocument();
  });
});

// =============================================================================
// Troca de escola no seletor do topo (Secretaria e admin global)
// =============================================================================

function TrocarParaB() {
  const { selecionarEscola } = useApp();
  return <button type="button" onClick={() => selecionarEscola(2)}>trocar para a escola B</button>;
}

function resumoEscola(id: number, turma: string) {
  return { escola: { id, nome: `Escola ${id}` }, turmas: [{ turma: { id: id * 10, nome: turma, ano_escolar: "5º Ano" },
    total_alunos: 10, media_geral: 50, media_matific: 50, media_elefante: 50, indicadores: {} }] };
}

/** A seção da Visão da Escola agora é a análise da escola (`GET /escolas/{id}/analise`). */
function respostaDe(id: number, marca: string): RespostaAnaliseEscola {
  return {
    escola: { id, nome: `EMEF Sintética ${marca}`, codigo_inep: "35990001", pendencia: null },
    rede: { id: 1, nome: "Rede Sintética" }, indicadores: [], plataformas: null,
    comparacoes_indisponiveis: [{ tema: "ranking", texto: `ESCOPO-DA-ESCOLA-${marca}` }], fontes: {},
  };
}

function montarVisao(usuario: ReturnType<typeof usuarioFake>) {
  responder("GET", "/escolas/1/resumo-escola", resumoEscola(1, "TURMA-DE-A"));
  responder("GET", "/escolas/2/resumo-escola", resumoEscola(2, "TURMA-DE-B"));
  responder("GET", "/escolas/1/analise", respostaDe(1, "A"));
  renderComApp(<><TrocarParaB /><VisaoEscola /></>, {
    usuario, rota: "/escola", escolaSelecionada: 1,
    escolas: [escolaFake({ id: 1, nome: "Escola A" }), escolaFake({ id: 2, nome: "Escola B" })],
  });
}

describe("Visão da Escola — troca de escola com a seção aberta", () => {
  it.each([["admin global", admin], ["Secretaria", secretaria]])(
    "%s: se a leitura da escola B falha, mostra o erro — nunca os números da escola A", async (_nome, usuario) => {
      responderErro("GET", "/escolas/2/analise", 500, "FALHA-DA-ESCOLA-B");
      montarVisao(usuario);
      expect(await screen.findByText("ESCOPO-DA-ESCOLA-A")).toBeInTheDocument();
      expect(screen.getByTestId("analise-escola-nome")).toHaveTextContent("EMEF Sintética A");
      await userEvent.click(screen.getByRole("button", { name: "trocar para a escola B" }));
      expect(await screen.findByText("TURMA-DE-B")).toBeInTheDocument();
      // Os números de A saem já no carregamento de B (sem esperar a resposta).
      expect(screen.queryByText("ESCOPO-DA-ESCOLA-A")).not.toBeInTheDocument();
      // A falha de B (depois da retentativa do useApi) aparece.
      expect(await screen.findByText(/FALHA-DA-ESCOLA-B/, undefined, { timeout: 3000 })).toBeInTheDocument();
      expect(screen.queryByText("ESCOPO-DA-ESCOLA-A")).not.toBeInTheDocument();
      expect(screen.queryByTestId("analise-escola-indisponiveis")).not.toBeInTheDocument();
      expect(screen.queryByTestId("analise-escola-nome")).not.toBeInTheDocument();
    });

  it("com sucesso, a seção passa a mostrar a escola B (com o nome dela)", async () => {
    responder("GET", "/escolas/2/analise", respostaDe(2, "B"));
    montarVisao(admin);
    expect(await screen.findByText("ESCOPO-DA-ESCOLA-A")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "trocar para a escola B" }));
    expect(await screen.findByText("ESCOPO-DA-ESCOLA-B")).toBeInTheDocument();
    expect(screen.getByTestId("analise-escola-nome")).toHaveTextContent("EMEF Sintética B");
    expect(screen.queryByText("ESCOPO-DA-ESCOLA-A")).not.toBeInTheDocument();
  });
});
