/**
 * Tela única "Importar indicadores oficiais" (SARESP/IEE da SEDUC-SP, Ideb e Saeb do
 * INEP) — decisão D-C, opção (a):
 *
 *  - só o admin global vê (a Secretaria nem a vê, nem a API é chamada);
 *  - a fonte escolhida decide a rota e os campos da prévia (o ano e a origem só no SEDUC);
 *  - a prévia mostra os contadores com os nomes da API, os avisos e as recusas;
 *  - a pergunta da troca (D2) vem SEM opção marcada e "Aplicar" fica bloqueado até a
 *    resposta; aplicar reenvia o MESMO arquivo com a resposta dada;
 *  - desfazer chama a rota da família e mostra a recusa ("desfaça antes a #N");
 *  - o CODMUN aceita só dígitos (e não o código IBGE) e grava por PATCH /redes/{id};
 *  - erros de rede ficam visíveis.
 *
 * Nomes, códigos, números, datas e arquivos INVENTADOS (o repositório é público e os
 * arquivos oficiais têm licença própria — D13): nada dos arquivos da SEDUC nem do INEP.
 */
import { describe, expect, it, vi } from "vitest";

import ImportarIndicadoresOficiais from "../pages/rede/ImportarIndicadoresOficiais";
import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import type { ImportacaoOficial, MudancaImportacao } from "../pages/rede/indicadoresImportacao";
import {
  api,
  apiUpload,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  waitFor,
  within,
} from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

const IBGE = "3599999";          // inventado
const CODMUN = "9101";           // inventado (não é o de nenhum município real)
const REDE = { id: 1, nome: "Rede Sintética", uf: "SP", codigo_ibge: IBGE, codigo_municipio_estadual: CODMUN };
const ARQ_MUN = "Proficiencia do SARESP por Municipio de 2031_0.csv";
const ARQ_IEE = "Indice de Excelencia Educacional 2031-2032_0.csv";
const ROTULO_URL = "Endereço de onde baixou (opcional)";
const ROTULO_DATA = "Data de publicação no site (opcional — como aparece na página de download)";

function importacao(over: Partial<ImportacaoOficial> = {}): ImportacaoOficial {
  return {
    id: 41, status: "previa", parser: "seduc_saresp_municipio", modo: "upload", arquivo_nome: ARQ_MUN,
    edicao_arquivo: 2031, contadores: {}, avisos: [], territorios: {}, fora_do_cadastro: [],
    arquivo_data: null, created_at: "2031-10-01T10:00:00", aplicado_em: null, mudancas: [], substituicoes: [],
    ...over,
  };
}

function mudanca(over: Partial<MudancaImportacao> = {}): MudancaImportacao {
  return {
    alvo: "escola", tipo: "nova", avaliacao: "saresp", onde: "EMEF Sintética Alfa", abrangencia: "escola",
    rede_ensino: null, codigo_inep: "35990001", indicador: "proficiencia", edicao: 2031, etapa: "5_ano",
    componente: "portugues", localizacao: null, nivel: null, antes: null, antes_motivo: null, antes_fonte: null,
    depois: 1043.72, depois_motivo: null, ...over,
  };
}

/** Duas médias por escola gravadas sem registro oficial que a prévia trocaria (D2). Os números
 *  ficam de propósito FORA de qualquer escala oficial (acima de mil): nenhum coincide, nem
 *  deslocado, com célula dos arquivos da SEDUC ou do INEP. */
const TROCAS = [
  mudanca({ tipo: "substituicao", antes: 1052.91, antes_fonte: "Estimativa sintética do Constela", depois: 1049.91 }),
  mudanca({ tipo: "substituicao", onde: "EMEF Sintética Beta", codigo_inep: "35990002", componente: "matematica",
            antes: 1061.18, antes_fonte: "Estimativa sintética do Constela", depois: null, depois_motivo: "nao_divulgado" }),
];
const PREVIA_IEE_COM_TROCA = importacao({
  id: 52, parser: "seduc_iee", arquivo_nome: ARQ_IEE,
  contadores: { lidas: 30, recortadas: 18, novas: 16, alteradas: 0, iguais: 0, mantidas: 0, substituicoes: 2,
                ausentes: 1, escolas_casadas: 2, fora_do_cadastro: 0, territorios: 0 },
  mudancas: [mudanca(), ...TROCAS],
  substituicoes: TROCAS.map((t) => ({
    escola_id: 1, escola: t.onde, codigo_inep: t.codigo_inep, edicao: t.edicao, etapa: t.etapa,
    componente: t.componente, antes: { valor: t.antes, fonte: t.antes_fonte, motivo_ausencia: null },
    depois: { valor: t.depois, motivo_ausencia: t.depois_motivo, fonte: "SARESP 2031 oficial" }, diferenca: null,
  })),
});

function montar({ rede = REDE, importacoes = [] as ImportacaoOficial[], familia = "saresp" } = {}) {
  responder("GET", "/redes", [rede]);
  responder("GET", `/redes/1/indicadores/${familia}/importacoes`, importacoes);
  const aoMudar = vi.fn();
  renderComApp(<ImportarIndicadoresOficiais redeId={1} ehGlobal aoMudar={aoMudar} />, { usuario: admin });
  return { aoMudar, usuario: userEvent.setup() };
}

const enviado = (rota: string) => {
  const chamada = apiUpload.mock.calls.find(([caminho]) => caminho === rota);
  return chamada?.[1] as FormData | undefined;
};

describe("Importar indicadores oficiais — quem vê", () => {
  it("quem não é admin global não vê a tela — e nada é pedido à API", async () => {
    const { container } = renderComApp(
      <ImportarIndicadoresOficiais redeId={1} ehGlobal={false} aoMudar={() => undefined} />, { usuario: secretaria });
    await waitFor(() => expect(api.mock.calls.some(([c]) => c === "/auth/me")).toBe(true));
    expect(screen.queryByTestId("importar-oficiais")).toBeNull();
    expect(container.querySelectorAll('input[type="file"]')).toHaveLength(0);
    expect(api.mock.calls.some(([c]) => String(c) === "/redes" || String(c).includes("/indicadores/"))).toBe(false);
  });

  function semearPagina() {
    responder("GET", "/redes", [REDE]);
    responder("GET", "/redes/1/avaliacoes/opcoes", []);
    responder("GET", "/avaliacoes", []);
    responder("GET", "/avaliacoes/presets-import", []);
    responder("GET", "/avaliacoes/fontes", []);
  }

  it("na tela da rede: a Secretaria não vê a importação; o admin global vê, abaixo dos cartões", async () => {
    semearPagina();
    renderComApp(<RedeAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByRole("heading", { name: "Fontes dos indicadores" })).toBeInTheDocument();
    expect(await screen.findByTestId("cartao-ideb")).toBeInTheDocument();
    expect(screen.queryByTestId("importar-oficiais")).toBeNull();
    expect(screen.queryByText(/Importar indicadores oficiais/)).toBeNull();
    expect(api.mock.calls.some(([c]) => /\/indicadores\/(saresp|ideb|saeb)\/importacoes/.test(String(c)))).toBe(false);
  });

  it("o admin global vê a importação logo depois do cartão do Ideb e do Saeb", async () => {
    semearPagina();
    renderComApp(<RedeAvaliacoes />, { usuario: admin });
    const importar = await screen.findByTestId("importar-oficiais");
    await waitFor(() => expect(importar).toHaveTextContent("Importar indicadores oficiais para a rede “Rede Sintética”"));
    const ideb = screen.getByTestId("cartao-ideb");
    expect(ideb.compareDocumentPosition(importar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("Importar indicadores oficiais — fonte e prévia", () => {
  it("sem escolher a fonte não há arquivo a enviar; cada fonte explica qual arquivo usar", async () => {
    const { usuario } = montar();
    await screen.findByTestId("importar-oficiais");
    expect(screen.queryByLabelText(/^Arquivo:/)).toBeNull();
    await usuario.click(screen.getByRole("radio", { name: /Ideb \(pacote\)/ }));
    expect(screen.getByTestId("oficiais-fonte")).toHaveTextContent("preparar");
    expect(screen.getByTestId("oficiais-fonte")).toHaveTextContent("nesta máquina");
    expect(screen.getByLabelText("Arquivo: Ideb (pacote)")).toHaveAttribute("accept", ".zip");
    await usuario.click(screen.getByRole("radio", { name: /SARESP por município/ }));
    expect(screen.getByTestId("oficiais-fonte")).toHaveTextContent("Precisa do CODMUN da rede");
    expect(screen.getByLabelText("Arquivo: SARESP por município")).toHaveAttribute("accept", ".csv");
  });

  it("SARESP por município: a prévia vai para a rota do SARESP com o arquivo, o ano e a origem", async () => {
    const { usuario } = montar();
    responder("UPLOAD", "/redes/1/indicadores/saresp/previa", importacao());
    await usuario.click(await screen.findByRole("radio", { name: /SARESP por município/ }));
    await usuario.type(screen.getByLabelText("Ano do SARESP (só se o nome do arquivo não trouxer)"), "2031");
    await usuario.type(screen.getByLabelText(ROTULO_URL), "https://exemplo.invalido/a.csv");
    await usuario.type(screen.getByLabelText(ROTULO_DATA), "Mon, 06 Oct 2031 09:00:00 GMT");
    const csv = new File(["CODMUN;MEDPROF"], ARQ_MUN, { type: "text/csv" });
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por município"), csv);
    expect(await screen.findByTestId("oficiais-previa")).toHaveTextContent("nada foi gravado");
    const corpo = enviado("/redes/1/indicadores/saresp/previa");
    expect((corpo?.get("arquivo") as File).name).toBe(ARQ_MUN);
    expect(corpo?.get("edicao")).toBe("2031");
    expect(corpo?.get("url_origem")).toBe("https://exemplo.invalido/a.csv");
    expect(corpo?.get("last_modified_origem")).toBe("Mon, 06 Oct 2031 09:00:00 GMT");
  });

  it.each([
    ["Ideb (pacote)", "ideb", "inep_ideb_escolas"],
    ["Saeb (pacote)", "saeb", "inep_saeb_planilha"],
  ])("%s: a prévia vai para a rota da família só com o pacote", async (rotulo, familia, parser) => {
    const { usuario } = montar({ familia });
    responder("UPLOAD", `/redes/1/indicadores/${familia}/previa`,
      importacao({ id: 61, parser, modo: "pacote_cli", arquivo_nome: "arquivo_sintetico_do_orgao.zip" }));
    await usuario.click(await screen.findByRole("radio", { name: new RegExp(rotulo.replace(/[()]/g, "\\$&")) }));
    expect(screen.queryByLabelText(/Ano do SARESP/)).toBeNull();          // o ano e a origem vêm do manifesto
    expect(screen.queryByLabelText(/Endereço de onde baixou/)).toBeNull();
    await usuario.upload(screen.getByLabelText(`Arquivo: ${rotulo}`), new File(["PK"], "pacote_sintetico.zip"));
    expect(await screen.findByTestId("oficiais-previa")).toHaveTextContent("(pacote do preparar)");
    const corpo = enviado(`/redes/1/indicadores/${familia}/previa`);
    expect([...(corpo?.keys() ?? [])]).toEqual(["arquivo"]);
    expect(api).toHaveBeenCalledWith(`/redes/1/indicadores/${familia}/importacoes`, expect.anything());
  });

  it("mostra os contadores com os nomes da API, os avisos, as escolas fora do cadastro e as sem linha", async () => {
    const { usuario } = montar({ familia: "ideb" });
    responder("UPLOAD", "/redes/1/indicadores/ideb/previa", importacao({
      id: 62, parser: "inep_ideb_escolas", modo: "pacote_cli", arquivo_nome: "divulgacao_sintetica.zip",
      arquivo_data: "2031-08-14T10:00:00", edicoes: [2029, 2031],
      contadores: { lidas: 44, recortadas: 40, novas: 12, alteradas: 2, iguais: 5, mantidas: 1, substituicoes: 0,
                    ausentes: 3, escolas_casadas: 4, fora_do_cadastro: 1, territorios: 0, iguais_sem_proveniencia: 6 },
      avisos: ["Aviso sintético da leitura."],
      fora_do_cadastro: [{ codigo_inep: "35990009", nome_no_arquivo: "EMEF SINTETICA FORA" }],
      sem_linha_no_arquivo: [{ escola_id: 7, escola: "EMEF Sintética Gama", codigo_inep: "35990003" }],
      mudancas: [mudanca({ avaliacao: "ideb", indicador: "ideb", etapa: "anos_iniciais", componente: null,
                           depois: null, depois_motivo: "nao_divulgado" })],
    }));
    await usuario.click(await screen.findByRole("radio", { name: /Ideb \(pacote\)/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: Ideb (pacote)"), new File(["PK"], "pacote_sintetico.zip"));
    const previa = await screen.findByTestId("oficiais-previa");
    expect(previa).toHaveTextContent("Ideb por escola (INEP), edição 2031, arquivo de 14/08/2031 — nada foi gravado.");
    expect(previa).toHaveTextContent("Edições no arquivo: 2029, 2031.");
    expect(screen.getByTestId("contador-novas")).toHaveTextContent("12 número(s) novo(s)");
    expect(screen.getByTestId("contador-alteradas")).toHaveTextContent("2 número(s) alterado(s)");
    expect(screen.getByTestId("contador-iguais")).toHaveTextContent("5 igual(is)");
    expect(screen.getByTestId("contador-mantidas")).toHaveTextContent("1 mantido(s)");
    expect(screen.getByTestId("contador-ausentes")).toHaveTextContent("3 sem resultado oficial");
    expect(screen.getByTestId("contador-ausentes")).toHaveTextContent("nunca como zero");
    expect(screen.getByTestId("contador-fora_do_cadastro")).toHaveTextContent("1 escola(s) do arquivo fora do cadastro");
    expect(screen.getByTestId("contador-sem_linha")).toHaveTextContent("1 escola(s) do cadastro sem linha no arquivo");
    expect(screen.getByTestId("contador-escolas_casadas")).toHaveTextContent("4 escola(s) da rede casada(s)");
    expect(screen.getByTestId("contador-iguais_sem_proveniencia")).toHaveTextContent("6 igual(is) aos gravados sem registro");
    expect(screen.getByTestId("contador-lidas")).toHaveTextContent("44 linha(s) lida(s)");
    expect(previa).toHaveTextContent("Aviso sintético da leitura.");
    expect(previa).toHaveTextContent("INEP 35990009 — EMEF SINTETICA FORA");
    expect(previa).toHaveTextContent("EMEF Sintética Gama (INEP 35990003)");
    // ausência nunca vira zero
    expect(within(screen.getByTestId("oficiais-mudancas")).getByText("sem resultado (não divulgado no arquivo oficial)"))
      .toBeInTheDocument();
    // sem troca a decidir: nenhuma pergunta e "Aplicar" liberado
    expect(screen.queryByTestId("oficiais-d2")).toBeNull();
    expect(screen.getByRole("button", { name: "Aplicar esta prévia" })).toBeEnabled();
  });

  it("arquivo de outro tipo que o escolhido: a prévia avisa", async () => {
    const { usuario } = montar();
    responder("UPLOAD", "/redes/1/indicadores/saresp/previa", importacao({ parser: "seduc_iee", arquivo_nome: ARQ_IEE }));
    await usuario.click(await screen.findByRole("radio", { name: /SARESP por município/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por município"), new File(["x"], ARQ_IEE));
    expect(await screen.findByTestId("oficiais-outro-tipo")).toHaveTextContent(
      "Você escolheu “SARESP por município”, mas o arquivo enviado é “IEE (SEDUC-SP)”");
  });

  it("recusa da prévia aparece em português — e a falta do CODMUN aponta o campo", async () => {
    const { usuario } = montar({ rede: { ...REDE, codigo_municipio_estadual: null } });
    responderErro("UPLOAD", "/redes/1/indicadores/saresp/previa", 400,
      "A rede não tem o código do município na SEDUC (CODMUN dos arquivos do SARESP — não é o IBGE). "
      + "Cadastre o código na rede e envie a prévia de novo. Nada foi gravado.");
    await usuario.click(await screen.findByRole("radio", { name: /SARESP por município/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por município"), new File(["x"], ARQ_MUN));
    expect(await screen.findByText(/^Prévia recusada: A rede não tem o código do município na SEDUC/)).toBeInTheDocument();
    expect(screen.getByTestId("codmun-pedido")).toHaveTextContent("grave-o aqui");
    expect(screen.queryByTestId("oficiais-previa")).toBeNull();
  });

  it("pacote errado na família: a recusa do servidor aparece em português, sem identificador interno", async () => {
    const { usuario } = montar({ familia: "saeb" });
    responderErro("UPLOAD", "/redes/1/indicadores/saeb/previa", 400,
      "Este arquivo é o pacote do Ideb por escola (na importação, escolha “Ideb (pacote)”); aqui entra o pacote "
      + "da planilha do Saeb. Nada foi gravado.");
    await usuario.click(await screen.findByRole("radio", { name: /Saeb \(pacote\)/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: Saeb (pacote)"), new File(["PK"], "pacote_sintetico.zip"));
    const recusa = await screen.findByText(/^Prévia recusada: Este arquivo é o pacote do Ideb por escola/);
    expect(recusa).toHaveTextContent("escolha “Ideb (pacote)”");
    expect(recusa.textContent).not.toMatch(/inep_|seduc_|parser/);
  });

  it("se uma recusa ainda citar o identificador interno de um parser, a tela mostra o nome em português", async () => {
    const { usuario } = montar({ familia: "ideb" });
    responderErro("UPLOAD", "/redes/1/indicadores/ideb/previa", 400,
      "Recusado: o pacote é do parser 'inep_saeb_planilha'; aqui entra o inep_ideb_escolas. Nada foi gravado.");
    await usuario.click(await screen.findByRole("radio", { name: /Ideb \(pacote\)/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: Ideb (pacote)"), new File(["PK"], "pacote_sintetico.zip"));
    const recusa = await screen.findByText(/^Prévia recusada: Recusado/);
    expect(recusa).toHaveTextContent("“Saeb — planilha de resultados (INEP)”");
    expect(recusa).toHaveTextContent("“Ideb por escola (INEP)”");
    expect(recusa.textContent).not.toMatch(/inep_|seduc_/);
  });

  it("recusa que CITA o CODMUN, com o CODMUN gravado, não diz que ele falta", async () => {
    const { usuario } = montar();
    responderErro("UPLOAD", "/redes/1/indicadores/saresp/previa", 400,
      `O CODMUN ${CODMUN} aparece com mais de um nome no arquivo (CIDADE SINTETICA, CIDADE SINTETICA DO NORTE). `
      + "Nada foi gravado.");
    await usuario.click(await screen.findByRole("radio", { name: /SARESP por município/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por município"), new File(["x"], ARQ_MUN));
    expect(await screen.findByText(/^Prévia recusada: O CODMUN 9101 aparece com mais de um nome/)).toBeInTheDocument();
    expect(screen.queryByTestId("codmun-pedido")).toBeNull();
  });
});

describe("Importar indicadores oficiais — a troca das médias calculadas (D2) e aplicar", () => {
  async function previaComTroca() {
    const ctx = montar();
    responder("UPLOAD", "/redes/1/indicadores/saresp/previa", PREVIA_IEE_COM_TROCA);
    responder("UPLOAD", "/redes/1/indicadores/saresp/aplicar", (_c: string, corpo: unknown) => {
      const resposta = (corpo as FormData).get("substituir_calculadas");
      return importacao({ id: 52, status: "aplicada", parser: "seduc_iee",
        contadores: { novas: 16, alteradas: 0, iguais: 0, substituicoes: 2,
                      substituicoes_aplicadas: resposta === "sim" ? 2 : 0,
                      substituicoes_mantidas: resposta === "sim" ? 0 : 2 } });
    });
    await ctx.usuario.click(await screen.findByRole("radio", { name: /IEE/ }));
    const csv = new File(["CODIGO_INEP;IEE"], ARQ_IEE);
    await ctx.usuario.upload(screen.getByLabelText("Arquivo: IEE (Índice de Excelência Educacional)"), csv);
    await screen.findByTestId("oficiais-previa");
    return { ...ctx, csv };
  }

  it("a pergunta vem sem opção marcada, com o antes × depois, e 'Aplicar' fica bloqueado até responder", async () => {
    await previaComTroca();
    const d2 = screen.getByTestId("oficiais-d2");
    expect(d2).toHaveTextContent("Trocar 2 número(s) pelo oficial?");
    expect(screen.getByTestId("contador-substituicoes")).toHaveTextContent(
      "2 média(s) calculada(s) pelo Constela a trocar pela oficial");
    const sim = within(d2).getByRole("radio", { name: "Sim, trocar as médias calculadas pelo Constela pelas oficiais" });
    const nao = within(d2).getByRole("radio", { name: "Não, manter as calculadas" });
    expect(sim).not.toBeChecked();
    expect(nao).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Aplicar esta prévia" })).toBeDisabled();
    expect(screen.getByText("Responda a pergunta da troca, acima, para aplicar.")).toBeInTheDocument();
    // o antes × depois de cada escola, na precisão da API e com a ausência escrita
    const linhas = within(d2).getAllByRole("row");
    expect(linhas[1]).toHaveTextContent("EMEF Sintética Alfa");
    expect(linhas[1]).toHaveTextContent("proficiência 5º ano LP 2031");
    expect(linhas[1]).toHaveTextContent("1.052,91");
    expect(linhas[1]).toHaveTextContent("Estimativa sintética do Constela");
    expect(linhas[1]).toHaveTextContent("1.049,91");
    expect(linhas[1]).toHaveTextContent("−3");
    expect(linhas[2]).toHaveTextContent("EMEF Sintética Beta");
    expect(linhas[2]).toHaveTextContent("sem resultado (não divulgado no arquivo oficial)");
    expect(apiUpload.mock.calls.some(([c]) => String(c).endsWith("/aplicar"))).toBe(false);
  });

  it.each([
    ["Sim, trocar as médias calculadas pelo Constela pelas oficiais", "sim", "2 trocado(s) pelo oficial e 0 mantido(s)"],
    ["Não, manter as calculadas", "nao", "0 trocado(s) pelo oficial e 2 mantido(s)"],
  ])("respondendo “%s”, aplicar reenvia o MESMO arquivo com substituir_calculadas=%s", async (rotulo, valor, texto) => {
    const { usuario, csv, aoMudar } = await previaComTroca();
    await usuario.click(screen.getByRole("radio", { name: rotulo }));
    const aplicar = screen.getByRole("button", { name: "Aplicar esta prévia" });
    expect(aplicar).toBeEnabled();
    await usuario.click(aplicar);
    // A confirmação da v2 (no lugar do window.confirm) resume a resposta e a rede; nada vai antes do "sim".
    const dialogo = screen.getByRole("dialog", { name: "Aplicar esta prévia?" });
    expect(dialogo).toHaveTextContent(`Sua resposta: “${rotulo}” (2 número(s))`);
    expect(dialogo).toHaveTextContent("na rede “Rede Sintética”");
    expect(apiUpload.mock.calls.some(([c]) => String(c).endsWith("/aplicar"))).toBe(false);
    await usuario.click(within(dialogo).getByRole("button", { name: "Aplicar" }));
    expect(await screen.findByText(new RegExp(`Importação #52 aplicada: 16 novo\\(s\\).*${
      texto.replace(/[()]/g, "\\$&")}`))).toBeInTheDocument();
    const corpo = enviado("/redes/1/indicadores/saresp/aplicar");
    expect(corpo?.get("previa_id")).toBe("52");
    const reenviado = corpo?.get("arquivo") as File;
    expect(reenviado.name).toBe(csv.name);
    expect(reenviado.size).toBe(csv.size);
    expect(corpo?.get("substituir_calculadas")).toBe(valor);
    expect(aoMudar).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("oficiais-previa")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancelar a confirmação não aplica nada", async () => {
    const { usuario, aoMudar } = await previaComTroca();
    await usuario.click(screen.getByRole("radio", { name: "Não, manter as calculadas" }));
    await usuario.click(screen.getByRole("button", { name: "Aplicar esta prévia" }));
    const dialogo = screen.getByRole("dialog", { name: "Aplicar esta prévia?" });
    await usuario.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiUpload.mock.calls.some(([c]) => String(c).endsWith("/aplicar"))).toBe(false);
    expect(screen.getByTestId("oficiais-previa")).toBeInTheDocument();
    expect(aoMudar).not.toHaveBeenCalled();
  });

  it("no Ideb, a pergunta usa as palavras do Ideb (não fala em média calculada)", async () => {
    const { usuario } = montar({ familia: "ideb" });
    responder("UPLOAD", "/redes/1/indicadores/ideb/previa", importacao({
      id: 63, parser: "inep_ideb_escolas", modo: "pacote_cli", contadores: { substituicoes: 1 },
      mudancas: [mudanca({ tipo: "substituicao", avaliacao: "ideb", indicador: "ideb", etapa: "anos_iniciais",
                           componente: null, antes: 5.2, depois: 5.4 })],
    }));
    await usuario.click(await screen.findByRole("radio", { name: /Ideb \(pacote\)/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: Ideb (pacote)"), new File(["PK"], "pacote_sintetico.zip"));
    const d2 = await screen.findByTestId("oficiais-d2");
    expect(within(d2).getByRole("radio", { name: "Sim, trocar os números sem registro oficial pelos oficiais" }))
      .not.toBeChecked();
    expect(within(d2).getByRole("radio", { name: "Não, manter os números atuais" })).not.toBeChecked();
    expect(d2).toHaveTextContent("Ideb anos iniciais 2031");
    expect(screen.getByRole("button", { name: "Aplicar esta prévia" })).toBeDisabled();
  });

  it("sem troca a decidir, aplicar não manda substituir_calculadas; a recusa do servidor aparece", async () => {
    const { usuario } = montar();
    responder("UPLOAD", "/redes/1/indicadores/saresp/previa",
      importacao({ contadores: { novas: 4, alteradas: 0, iguais: 0, substituicoes: 0 } }));
    responderErro("UPLOAD", "/redes/1/indicadores/saresp/aplicar", 400,
      "O arquivo enviado não é o mesmo da prévia (sha256 diferente). Envie o mesmo arquivo, ou gere uma prévia nova. "
      + "Nada foi gravado.");
    await usuario.click(await screen.findByRole("radio", { name: /SARESP por município/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por município"), new File(["x"], ARQ_MUN));
    await usuario.click(await screen.findByRole("button", { name: "Aplicar esta prévia" }));
    // Sem troca a decidir, o diálogo não fala em resposta.
    const dialogo = screen.getByRole("dialog", { name: "Aplicar esta prévia?" });
    expect(dialogo).not.toHaveTextContent("Sua resposta");
    await usuario.click(within(dialogo).getByRole("button", { name: "Aplicar" }));
    expect(await screen.findByText(/^Aplicação recusada: O arquivo enviado não é o mesmo da prévia/)).toBeInTheDocument();
    expect(enviado("/redes/1/indicadores/saresp/aplicar")?.has("substituir_calculadas")).toBe(false);
  });
});

describe("Importar indicadores oficiais — lista e desfazer", () => {
  const APLICADA = importacao({ id: 21, status: "aplicada", aplicado_em: "2031-10-02T12:00:00", pode_desfazer: true });
  const BLOQUEADA = importacao({ id: 20, status: "aplicada", arquivo_nome: ARQ_IEE, parser: "seduc_iee",
                                 aplicado_em: "2031-10-01T12:00:00", pode_desfazer: false, bloqueada_por: 21 });

  it("lista as importações da família e desfaz pela rota dela", async () => {
    const { usuario, aoMudar } = montar({ importacoes: [APLICADA, BLOQUEADA] });
    responder("POST", "/redes/1/indicadores/saresp/importacoes/21/desfazer", { ...APLICADA, status: "desfeita" });
    await usuario.click(await screen.findByRole("radio", { name: /IEE/ }));
    const lista = await screen.findByTestId("oficiais-lista");
    expect(lista).toHaveTextContent("Importações do SARESP/IEE nesta rede");
    expect(await within(lista).findByText(`#21 · ${ARQ_MUN}`)).toBeInTheDocument();
    expect(lista).toHaveTextContent("SARESP por município (SEDUC-SP)");
    expect(lista).toHaveTextContent("para desfazer, desfaça antes a #21");
    await usuario.click(within(lista).getByRole("button", { name: "Desfazer a importação #21" }));
    // A confirmação da v2 diz o que volta; nada é desfeito antes do "sim".
    const dialogo = screen.getByRole("dialog", { name: "Desfazer a importação?" });
    expect(dialogo).toHaveTextContent(`Desfazer a importação #21 (“${ARQ_MUN}”)? Os números voltam exatamente `
      + "ao estado anterior a ela (inclusive as médias que ela tenha trocado).");
    expect(api.mock.calls.some(([c]) => String(c).endsWith("/desfazer"))).toBe(false);
    await usuario.click(within(dialogo).getByRole("button", { name: "Desfazer importação" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      "/redes/1/indicadores/saresp/importacoes/21/desfazer", { method: "POST" }));
    expect(await screen.findByText(/Importação #21 .* desfeita: os números voltaram ao estado anterior/))
      .toBeInTheDocument();
    expect(aoMudar).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancelar a confirmação do desfazer não desfaz nada", async () => {
    const { usuario, aoMudar } = montar({ importacoes: [APLICADA] });
    await usuario.click(await screen.findByRole("radio", { name: /IEE/ }));
    await usuario.click(await screen.findByRole("button", { name: "Desfazer a importação #21" }));
    const dialogo = screen.getByRole("dialog", { name: "Desfazer a importação?" });
    await usuario.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.mock.calls.some(([c]) => String(c).endsWith("/desfazer"))).toBe(false);
    expect(aoMudar).not.toHaveBeenCalled();
  });

  it("a recusa do desfazer aparece (desfaça antes a #N)", async () => {
    const { usuario, aoMudar } = montar({ familia: "ideb", importacoes: [
      importacao({ id: 31, status: "aplicada", parser: "inep_ideb_escolas", modo: "pacote_cli", pode_desfazer: true }),
    ] });
    responderErro("POST", "/redes/1/indicadores/ideb/importacoes/31/desfazer", 400,
      "A importação #33 (arquivo_sintetico.zip), aplicada depois desta, usa 3 dos números que esta importação gravou. "
      + "Desfazer esta agora não voltaria exatamente ao estado anterior: desfaça antes a #33. Nada foi alterado.");
    await usuario.click(await screen.findByRole("radio", { name: /Ideb \(pacote\)/ }));
    await usuario.click(await screen.findByRole("button", { name: "Desfazer a importação #31" }));
    await usuario.click(within(screen.getByRole("dialog", { name: "Desfazer a importação?" }))
      .getByRole("button", { name: "Desfazer importação" }));
    expect(await screen.findByText(/^Desfazer recusado: .*desfaça antes a #33\. Nada foi alterado\./)).toBeInTheDocument();
    expect(aoMudar).not.toHaveBeenCalled();
  });
});

describe("Importar indicadores oficiais — CODMUN da rede", () => {
  const ROTULO = "CODMUN da rede “Rede Sintética” (código do município na SEDUC-SP)";

  it("mostra o valor atual e explica que não é o IBGE", async () => {
    montar();
    expect(await screen.findByTestId("codmun-atual")).toHaveTextContent(`CODMUN da SEDUC-SP: ${CODMUN}.`);
    expect(screen.getByTestId("ibge-atual")).toHaveTextContent(IBGE);
    expect(screen.getByTestId("codigos-da-rede")).toHaveTextContent("não é o código do IBGE");
  });

  it("sem CODMUN: avisa que o SARESP por município é recusado", async () => {
    montar({ rede: { ...REDE, codigo_municipio_estadual: null } });
    expect(await screen.findByTestId("codmun-atual")).toHaveTextContent(
      "Sem CODMUN cadastrado: o SARESP por município é recusado até ele ser gravado aqui.");
  });

  it("aceita só dígitos (e não o código IBGE) e grava por PATCH /redes/{id}", async () => {
    let leituras = 0;
    responder("GET", "/redes", () => {
      leituras += 1;
      return [leituras === 1 ? REDE : { ...REDE, codigo_municipio_estadual: "4321" }];
    });
    responder("GET", "/redes/1/indicadores/saresp/importacoes", []);
    responder("PATCH", "/redes/1", { ...REDE, codigo_municipio_estadual: "4321" });
    const aoMudar = vi.fn();
    renderComApp(<ImportarIndicadoresOficiais redeId={1} ehGlobal aoMudar={aoMudar} />, { usuario: admin });
    const usuario = userEvent.setup();
    await screen.findByTestId("codmun-atual");
    const campo = screen.getByLabelText(ROTULO);
    const gravar = screen.getByRole("button", { name: "Trocar CODMUN" });
    expect(gravar).toBeDisabled();
    await usuario.type(campo, "43a");
    expect(screen.getByText("Use só dígitos (até 8), sem pontos, traços nem espaços.")).toBeInTheDocument();
    expect(gravar).toBeDisabled();
    await usuario.clear(campo);
    await usuario.type(campo, IBGE);
    expect(screen.getByText(/Esse é o código IBGE da rede/)).toBeInTheDocument();
    expect(gravar).toBeDisabled();
    await usuario.clear(campo);
    await usuario.type(campo, CODMUN);
    expect(screen.getByText("Esse já é o CODMUN gravado.")).toBeInTheDocument();
    expect(gravar).toBeDisabled();
    await usuario.clear(campo);
    await usuario.type(campo, "4321");
    expect(gravar).toBeEnabled();
    await usuario.click(gravar);
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      "/redes/1", { method: "PATCH", body: JSON.stringify({ codigo_municipio_estadual: "4321" }) }));
    expect(await screen.findByText("CODMUN 4321 gravado na rede “Rede Sintética”.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("codmun-atual")).toHaveTextContent("CODMUN da SEDUC-SP: 4321."));
    expect(aoMudar).toHaveBeenCalledTimes(1);
  });

  it("recusa do PATCH aparece", async () => {
    montar({ rede: { ...REDE, codigo_municipio_estadual: null } });
    responderErro("PATCH", "/redes/1", 422, "codigo_municipio_estadual: deve ter só dígitos");
    const usuario = userEvent.setup();
    await usuario.type(await screen.findByLabelText(ROTULO), "77");
    await usuario.click(screen.getByRole("button", { name: "Gravar CODMUN" }));
    expect(await screen.findByText("O código foi recusado: codigo_municipio_estadual: deve ter só dígitos"))
      .toBeInTheDocument();
  });
});

describe("Importar indicadores oficiais — erros de rede", () => {
  it("falha ao ler a rede, a lista e a prévia: tudo visível", async () => {
    responderErro("GET", "/redes", 0, "Falha de conexão. Verifique a internet e tente de novo.");
    responderErro("GET", "/redes/1/indicadores/saresp/importacoes", 0, "Falha de conexão. Verifique a internet e tente de novo.");
    responderErro("UPLOAD", "/redes/1/indicadores/saresp/previa", 0, "Falha de conexão. Verifique a internet e tente de novo.");
    renderComApp(<ImportarIndicadoresOficiais redeId={1} ehGlobal aoMudar={() => undefined} />, { usuario: admin });
    const usuario = userEvent.setup();
    expect(await screen.findByText(/Não foi possível ler os códigos atuais da rede: Falha de conexão/))
      .toBeInTheDocument();
    await usuario.click(screen.getByRole("radio", { name: /SARESP por instância/ }));
    expect(await screen.findByText(/Não foi possível carregar as importações: Falha de conexão/)).toBeInTheDocument();
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por instância"), new File(["x"], "instancia.csv"));
    expect(await screen.findByText(/^Não foi possível gerar a prévia: Falha de conexão/)).toBeInTheDocument();
  });
});

describe("Importar indicadores oficiais — revisão: origem, teclado, leitor de tela e rótulos", () => {
  /** Os pedidos de prévia enviados para `rota`, na ordem. */
  const enviados = (rota: string) =>
    apiUpload.mock.calls.filter(([caminho]) => caminho === rota).map(([, corpo]) => corpo as FormData);

  it("o endereço e a data digitados para um arquivo NÃO vão junto com o próximo (aplicar, trocar de fonte)", async () => {
    const { usuario } = montar();
    responder("UPLOAD", "/redes/1/indicadores/saresp/previa", (_c: string, corpo: unknown) => {
      const nome = ((corpo as FormData).get("arquivo") as File).name;
      return importacao(nome === ARQ_IEE ? { id: 43, parser: "seduc_iee", arquivo_nome: ARQ_IEE } : {});
    });
    responder("UPLOAD", "/redes/1/indicadores/saresp/aplicar", importacao({ status: "aplicada", contadores: {} }));
    await usuario.click(await screen.findByRole("radio", { name: /SARESP por município/ }));
    await usuario.type(screen.getByLabelText(ROTULO_URL), "https://exemplo.invalido/municipio_2031.csv");
    await usuario.type(screen.getByLabelText(ROTULO_DATA), "Mon, 06 Oct 2031 09:00:00 GMT");
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por município"), new File(["x"], ARQ_MUN));
    await usuario.click(await screen.findByRole("button", { name: "Aplicar esta prévia" }));
    await usuario.click(within(screen.getByRole("dialog", { name: "Aplicar esta prévia?" }))
      .getByRole("button", { name: "Aplicar" }));
    expect(await screen.findByText(/^Importação #41 aplicada/)).toBeInTheDocument();
    // depois de aplicar, os campos do arquivo aplicado ficam vazios
    expect(screen.getByLabelText(ROTULO_URL)).toHaveValue("");
    expect(screen.getByLabelText(ROTULO_DATA)).toHaveValue("");
    // e o arquivo seguinte, de outra fonte, vai sem a origem do anterior
    await usuario.click(screen.getByRole("radio", { name: /IEE/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: IEE (Índice de Excelência Educacional)"),
      new File(["x"], ARQ_IEE));
    expect(await screen.findByTestId("oficiais-previa")).toHaveTextContent(`Prévia #43 de “${ARQ_IEE}”`);
    const [primeiro, segundo] = enviados("/redes/1/indicadores/saresp/previa");
    expect(primeiro.get("url_origem")).toBe("https://exemplo.invalido/municipio_2031.csv");
    expect(segundo.has("url_origem")).toBe(false);
    expect(segundo.has("last_modified_origem")).toBe(false);
  });

  it("trocar de fonte ou descartar a prévia apaga o ano e a origem digitados; uma recusa os mantém", async () => {
    const { usuario } = montar();
    responderErro("UPLOAD", "/redes/1/indicadores/saresp/previa", 400, "Recusa sintética. Nada foi gravado.");
    await usuario.click(await screen.findByRole("radio", { name: /SARESP por município/ }));
    await usuario.type(screen.getByLabelText(ROTULO_URL), "https://exemplo.invalido/a.csv");
    await usuario.type(screen.getByLabelText("Ano do SARESP (só se o nome do arquivo não trouxer)"), "2031");
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por município"), new File(["x"], ARQ_MUN));
    expect(await screen.findByText(/^Prévia recusada: Recusa sintética/)).toBeInTheDocument();
    expect(screen.getByLabelText(ROTULO_URL)).toHaveValue("https://exemplo.invalido/a.csv");   // o mesmo arquivo, de novo
    await usuario.click(screen.getByRole("radio", { name: /SARESP por instância/ }));
    expect(screen.getByLabelText(ROTULO_URL)).toHaveValue("");
    expect(screen.getByLabelText("Ano do SARESP (só se o nome do arquivo não trouxer)")).toHaveValue("");

    responder("UPLOAD", "/redes/1/indicadores/saresp/previa", importacao({ parser: "seduc_saresp_instancia" }));
    await usuario.type(screen.getByLabelText(ROTULO_URL), "https://exemplo.invalido/b.csv");
    await usuario.upload(screen.getByLabelText("Arquivo: SARESP por instância"), new File(["x"], "instancia.csv"));
    await screen.findByTestId("oficiais-previa");
    await usuario.click(screen.getByRole("button", { name: "Descartar" }));
    expect(screen.queryByTestId("oficiais-previa")).toBeNull();
    expect(screen.getByLabelText(ROTULO_URL)).toHaveValue("");
  });

  it("o campo de arquivo é alcançável pelo teclado (sr-only, não hidden)", async () => {
    const { usuario } = montar();
    await usuario.click(await screen.findByRole("radio", { name: /IEE/ }));
    const arquivo = screen.getByLabelText("Arquivo: IEE (Índice de Excelência Educacional)");
    expect(arquivo).not.toHaveClass("hidden");
    expect(arquivo).toHaveClass("sr-only");
    screen.getByLabelText(ROTULO_DATA).focus();
    await usuario.tab();
    expect(arquivo).toHaveFocus();
  });

  it("a prévia pronta e a pergunta da troca são anunciadas; o 'Aplicar' bloqueado diz por quê", async () => {
    const { usuario } = montar();
    responder("UPLOAD", "/redes/1/indicadores/saresp/previa", PREVIA_IEE_COM_TROCA);
    const anuncio = await screen.findByTestId("oficiais-anuncio");
    expect(anuncio).toHaveAttribute("role", "status");
    expect(anuncio.textContent).toBe("");
    await usuario.click(screen.getByRole("radio", { name: /IEE/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: IEE (Índice de Excelência Educacional)"),
      new File(["x"], ARQ_IEE));
    await waitFor(() => expect(anuncio).toHaveTextContent("Prévia #52 pronta, logo abaixo: nada foi gravado."));
    expect(anuncio).toHaveTextContent("Responda a pergunta da troca de números para poder aplicar.");
    expect(screen.getByRole("button", { name: "Aplicar esta prévia" }))
      .toHaveAccessibleDescription("Responda a pergunta da troca, acima, para aplicar.");
    await usuario.click(screen.getByRole("radio", { name: "Não, manter as calculadas" }));
    expect(anuncio).not.toHaveTextContent("Responda a pergunta");
    expect(screen.getByRole("button", { name: "Aplicar esta prévia" })).not.toHaveAttribute("aria-describedby");
  });

  it("Saeb: as linhas total, urbana e rural do mesmo número saem com rótulos diferentes", async () => {
    const { usuario } = montar({ familia: "saeb" });
    const base = { alvo: "referencia" as const, avaliacao: "saeb", onde: "Brasil", abrangencia: "brasil",
                   codigo_inep: null, indicador: "pct_nivel", nivel: "0", etapa: "5_ano", componente: "lp",
                   rede_ensino: "estadual", depois: null, depois_motivo: "nao_divulgado" };
    responder("UPLOAD", "/redes/1/indicadores/saeb/previa", importacao({
      id: 64, parser: "inep_saeb_planilha", modo: "pacote_cli",
      mudancas: ["total", "urbana", "rural"].map((localizacao) => mudanca({ ...base, localizacao })),
    }));
    await usuario.click(await screen.findByRole("radio", { name: /Saeb \(pacote\)/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: Saeb (pacote)"), new File(["PK"], "pacote_sintetico.zip"));
    const tabela = await screen.findByTestId("oficiais-mudancas");
    const rotulos = within(tabela).getAllByRole("row").slice(1).map((l) => l.children[1].textContent);
    expect(rotulos).toEqual([
      "% no nível 0 5º ano LP rede estadual área total (urbana e rural) 2031",
      "% no nível 0 5º ano LP rede estadual só área urbana 2031",
      "% no nível 0 5º ano LP rede estadual só área rural 2031",
    ]);
  });

  it("Ideb: a aprovação por série e as redes saem em português (sem 1_ano, publica ou total crus)", async () => {
    const { usuario } = montar({ familia: "ideb" });
    const base = { alvo: "referencia" as const, avaliacao: "ideb", onde: "Brasil", abrangencia: "brasil",
                   codigo_inep: null, indicador: "aprovacao", componente: null, localizacao: "total",
                   depois: null, depois_motivo: "nao_divulgado", edicao: 2029 };
    responder("UPLOAD", "/redes/1/indicadores/ideb/previa", importacao({
      id: 65, parser: "inep_ideb_uf_brasil", modo: "pacote_cli",
      mudancas: [
        mudanca({ ...base, etapa: "1_ano", rede_ensino: "publica" }),
        mudanca({ ...base, etapa: "3_ano", rede_ensino: "total" }),
        mudanca({ ...base, etapa: "4_ano", rede_ensino: "municipal" }),
      ],
    }));
    await usuario.click(await screen.findByRole("radio", { name: /Ideb \(pacote\)/ }));
    await usuario.upload(screen.getByLabelText("Arquivo: Ideb (pacote)"), new File(["PK"], "pacote_sintetico.zip"));
    const tabela = await screen.findByTestId("oficiais-mudancas");
    const rotulos = within(tabela).getAllByRole("row").slice(1).map((l) => l.children[1].textContent);
    expect(rotulos).toEqual([
      "aprovação 1º ano rede pública 2029",
      "aprovação 3º ano todas as redes (públicas e privadas) 2029",
      "aprovação 4º ano rede municipal 2029",
    ]);
    expect(tabela.textContent).not.toMatch(/_ano|rede publica|rede total|área/);
  });

  it("gravar o código IBGE no cartão do ICA faz a importação oficial reler os códigos da rede", async () => {
    // O IBGE só existe depois do PATCH (gravado pelo cartão do ICA).
    let gravado = false;
    const leiturasDepois = () => api.mock.calls.filter(([cam]) => cam === "/redes").length;
    responder("GET", "/redes", () => [gravado ? REDE : { ...REDE, codigo_ibge: null }]);
    responder("GET", "/redes/1/indicadores/ica", () => ({
      rede_id: 1, rede_nome: "Rede Sintética", codigo_ibge: gravado ? IBGE : null,
      indicador: { chave: "ica", nome: "Indicador Criança Alfabetizada (ICA)", orgao: "INEP", descricao: "" },
      aviso_rede: "O ICA é o indicador da REDE municipal.", pendencia: gravado ? null : "codigo_ibge",
      legenda_nivel: [], territorios: [], fontes: [], tem_dados: false,
    }));
    responder("GET", "/redes/1/indicadores/importacoes", []);
    responder("PATCH", "/redes/1", () => { gravado = true; return { ...REDE }; });
    responder("GET", "/redes/1/avaliacoes/opcoes", []);
    responder("GET", "/avaliacoes", []);
    responder("GET", "/avaliacoes/presets-import", []);
    responder("GET", "/avaliacoes/fontes", []);
    renderComApp(<RedeAvaliacoes />, { usuario: admin });
    const usuario = userEvent.setup();
    await waitFor(() => expect(screen.getByTestId("ibge-atual")).toHaveTextContent("Sem código IBGE cadastrado"));
    await usuario.type(await screen.findByLabelText("Código IBGE do município da rede “Rede Sintética” (7 dígitos)"), IBGE);
    const antes = leiturasDepois();
    await usuario.click(screen.getByRole("button", { name: "Gravar código" }));
    await waitFor(() => expect(screen.getByTestId("ibge-atual")).toHaveTextContent(`Código IBGE do município: ${IBGE}`));
    expect(leiturasDepois()).toBeGreaterThan(antes);                // releu os códigos da rede
    // e o próprio IBGE volta a ser recusado como CODMUN
    await usuario.type(screen.getByLabelText("CODMUN da rede “Rede Sintética” (código do município na SEDUC-SP)"), IBGE);
    expect(screen.getByText(/Esse é o código IBGE da rede/)).toBeInTheDocument();
  });
});
