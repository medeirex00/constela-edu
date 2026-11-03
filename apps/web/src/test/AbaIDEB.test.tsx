/**
 * Aba "IDEB e SAEB" (etapas E8a e E8b) na tela da rede — o que a tela garante:
 *
 *  - a parte "Rede municipal" (aberta primeiro quando há número da rede): o Ideb da rede
 *    × a meta (tracejada) e × o Brasil nas redes municipais no MESMO gráfico; a UF na rede
 *    pública FORA do gráfico, na tabela, rotulada "outra rede, só contexto"; a nota do
 *    Saeb do Ideb com o universo (só escolas urbanas) num "ver mais" da seção do Ideb; o
 *    Saeb da planilha com a localização Total explícita, a distribuição por nível (LP 0–9,
 *    MT 0–10) em barras com a tabela de níveis nas LINHAS, e os cortes com a fonte; o
 *    contexto amostral do 2º ano rotulado ("amostral, só contexto", "não é o ICA");
 *  - nada de "aguardando o arquivo oficial": só o que falta (a planilha do Saeb 2023,
 *    adiada; o que a base não importou);
 *  - a tabela por escola em ordem de NOME (sem ranking), uma edição por vez: o Ideb, a
 *    meta com "atingiu / não atingiu" na precisão publicada (Ideb ≥ meta = atingiu, o
 *    empate incluído), a variação desde a edição anterior e o Saeb de LP e MT;
 *  - "Ideb não divulgado" (nunca 0); escola sem INEP = pendência de cadastro; escola
 *    sem linha no arquivo diz isso; números do 1 clique marcados "sem registro
 *    oficial" (e "difere do arquivo oficial" quando a troca foi recusada), com a origem
 *    e a data à vista no bloco (o selo oficial não os cobre);
 *  - a série de UMA escola escolhida: Ideb com a meta TRACEJADA num gráfico e o Saeb
 *    noutro, a linha quebrando onde não há número, o eixo do Ideb rotulado com o valor
 *    de cada linha, e a tabela equivalente;
 *  - os avisos: comparabilidade da série TODA (não só 2021), 2025 e município/SP/Brasil
 *    "aguardando o arquivo oficial", participação por escola sem coluna (só com a D8);
 *  - o selo de fonte em cada bloco (arquivo, divulgação, data do arquivo);
 *  - cobertura: sem linha no arquivo, sem INEP, códigos do arquivo fora do cadastro;
 *  - sem dado: "sem resultado importado"; erro da API visível;
 *  - nada de largura mínima: as tabelas são de largura fixa (sem rolagem lateral).
 *
 * Números, datas, nomes, códigos e arquivos SINTÉTICOS (os mesmos INVENTADOS do teste
 * do backend) — nada do arquivo do INEP (repositório público — D13).
 */
import { describe, expect, it } from "vitest";

import { textoFonte, type FonteOficial } from "../components/SeloFonte";
import CartaoIDEB, { type RespostaIDEB } from "../pages/rede/CartaoIDEB";
import type {
  ComparacaoMeta,
  ContextoAmostral,
  DistribuicaoSaeb,
  EdicaoIDEB,
  EdicaoIdebRede,
  EscolaIDEB,
  NumeroIDEB,
  RedeMunicipalIDEB,
  TerritorioIdeb,
  TerritorioSaeb,
} from "../pages/rede/ideb";
import { renderComApp, responder, responderErro, screen, userEvent, usuarioFake, within } from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });

const FONTE: FonteOficial = {
  importacao_id: 41,
  fonte_nome: "INEP — Ideb por escola, anos iniciais (Ideb, Saeb do 5º ano e rendimento)",
  arquivo_nome: "ideb.zip", arquivo_data: "2031-06-02T08:15:00", last_modified_origem: null,
  url_origem: "https://exemplo.invalido/ideb_sintetico.zip", edicao_arquivo: 2023, versao_rotulo: "ideb",
  importado_em: "2031-06-03T10:00:00", coletado_em: "2031-05-14T09:30:00", citacao: "Fonte sintética de teste.",
  licenca: "Licença sintética de teste: citar a fonte.", parser: "inep_ideb_escolas", modo: "pacote_cli",
  notas: ["Fonte: arquivo sintético de teste", "Notas: ND - marcador sintético de não divulgação;"],
};

function num(valor: number | null, casas: number, extra: Partial<NumeroIDEB> = {}): NumeroIDEB {
  return { valor, casas_decimais: valor == null ? null : casas, motivo_ausencia: valor == null ? "nao_divulgado" : null,
           proveniencia: "oficial", fonte_id: FONTE.importacao_id, ...extra };
}

function comp(observado: number, meta: number, diferenca: number, situacao: ComparacaoMeta["situacao"]): ComparacaoMeta {
  return { observado, meta, diferenca, casas_decimais: 1, situacao };
}

const ANOS = [2019, 2021, 2023];

/** (Ideb, LP, MT, N, P, aprovação 1º–5º) por edição — os INVENTADOS do backend (a
 *  aprovação da Alfa, outra também inventada: longe de qualquer percentual oficial). */
type Valores = [number | null, number | null, number | null, number | null, number | null, number | null];

function ed(edicao: number, v: Valores | null, extra: Partial<EdicaoIDEB> = {}): EdicaoIDEB {
  const vazio = { anos_iniciais: null, "1_ano": null, "2_ano": null, "3_ano": null, "4_ano": null, "5_ano": null };
  if (!v) {
    return { edicao, ideb: null, saeb_lp: null, saeb_mt: null, nota_n: null, rendimento_p: null, aprovacao: vazio,
             meta: null, sem_meta: null, comparacao_meta: null, variacao_ideb: null, no_arquivo: false,
             tem_ideb: false, tem_saeb: false, motivo: "fora_do_arquivo", ...extra };
  }
  const [ideb, lp, mt, n, p, aprov] = v;
  return {
    edicao, ideb: num(ideb, 1), saeb_lp: num(lp, 2), saeb_mt: num(mt, 2), nota_n: num(n, 6), rendimento_p: num(p, 6),
    aprovacao: { ...vazio, anos_iniciais: num(aprov, 1) }, meta: null,
    sem_meta: edicao > 2021 ? "depois_do_1o_ciclo" : null, comparacao_meta: null, variacao_ideb: null,
    no_arquivo: true, tem_ideb: ideb != null, tem_saeb: lp != null || mt != null,
    motivo: ideb == null ? "nao_divulgado" : null, ...extra,
  };
}

function escola(escola_id: number, nome: string, codigo_inep: string | null, serie: EdicaoIDEB[]): EscolaIDEB {
  return { escola_id, nome, codigo_inep, status: "ativa", pendencia: codigo_inep ? null : "codigo_inep", serie,
           tem_sem_registro: serie.some((e) => [e.ideb, e.saeb_lp, e.saeb_mt].some((n) => n?.proveniencia === "sem_registro")) };
}

// --- Rede municipal (E8b): fontes e números INVENTADOS ---------------------------------

const FONTE_MUN: FonteOficial = {
  ...FONTE, importacao_id: 51, fonte_nome: "INEP — Ideb por município, anos iniciais (rede municipal)",
  arquivo_nome: "divulgacao_anos_iniciais_municipios_2025.zip", edicao_arquivo: 2025, parser: "inep_ideb_municipios",
  notas: [],
};
const FONTE_UF: FonteOficial = {
  ...FONTE, importacao_id: 52, fonte_nome: "INEP — Ideb de Brasil, regiões e UFs, anos iniciais",
  arquivo_nome: "divulgacao_regioes_ufs_ideb_2025.zip", edicao_arquivo: 2025, parser: "inep_ideb_uf_brasil", notas: [],
};
const FONTE_BR: FonteOficial = { ...FONTE_UF, importacao_id: 53, arquivo_nome: "divulgacao_brasil_ideb_2025.zip" };
const FONTE_SAEB: FonteOficial = {
  ...FONTE, importacao_id: 61, fonte_nome: "INEP — Saeb: resultados de Brasil, estados e municípios (planilha)",
  arquivo_nome: "saeb_2025_brasil_estados_municipios_censitario.xlsx", edicao_arquivo: 2025,
  parser: "inep_saeb_planilha", notas: [],
};
const FONTE_SAEB_21: FonteOficial = { ...FONTE_SAEB, importacao_id: 62, arquivo_nome: "saeb_2021.xlsx", edicao_arquivo: 2021 };

const URBANAS = "Só escolas urbanas (universo do INEP no Ideb): não é a média “Total” da planilha do Saeb, que inclui as rurais.";
const AVISOS_REDE = {
  mesma_rede: "A comparação é na MESMA rede: a rede municipal do município × o Brasil nas redes municipais.",
  universo: "A nota do Saeb que entra no Ideb do território é a das escolas URBANAS. Ela nunca se compara com a média “Total” da planilha.",
  saeb_planilha: "Média e distribuição por nível do Saeb do 5º ano pela planilha. Não é a nota do Saeb do Ideb (só urbanas).",
  niveis: "A distribuição por nível vem do arquivo oficial. O Constela não calcula nível.",
  saeb_2023: "Saeb 2023 pela planilha do INEP (RAR com XLSB): adiado.",
  amostral: "O Saeb do 2º ano é AMOSTRAL: só o estado e o Brasil. Aqui é só contexto — não é número da rede.",
  nao_e_ica: "A taxa de alfabetização do Saeb 2021 NÃO é o Indicador Criança Alfabetizada (ICA).",
};

function numT(valor: number | null, casas: number, fonte: FonteOficial): NumeroIDEB {
  return { ...num(valor, casas), fonte_id: fonte.importacao_id };
}

/** [edição, Ideb, meta, nota LP, nota MT] — INVENTADOS (Ideb 1,x; nota do Saeb 1xx). */
type LinhaIdeb = [number, number | null, number | null, number, number];

function edRede(fonte: FonteOficial, [edicao, ideb, meta, lp, mt]: LinhaIdeb,
                comparacao: ComparacaoMeta | null = null): EdicaoIdebRede {
  return {
    edicao, ideb: numT(ideb, 1, fonte), meta: meta == null ? null : numT(meta, 1, fonte),
    sem_meta: meta == null ? (edicao > 2021 ? "depois_do_1o_ciclo" : "antes_das_metas") : null,
    comparacao_meta: comparacao, nota_saeb: { lp: numT(lp, 2, fonte), mt: numT(mt, 2, fonte) },
    nota_n: numT(2.104371, 6, fonte), rendimento_p: numT(0.471263, 6, fonte), aprovacao: numT(36.4, 1, fonte),
  };
}

function territorioIdeb(chave: TerritorioIdeb["chave"], nome: string, rotulo: string, fonte: FonteOficial,
                        serie: EdicaoIdebRede[], contexto = false): TerritorioIdeb {
  return {
    chave, abrangencia: chave === "rede_municipal" ? "municipio" : chave.startsWith("uf") ? "uf" : "brasil",
    codigo_territorio: chave === "rede_municipal" ? "3599999" : chave.startsWith("uf") ? "35" : "BR",
    rede_ensino: chave === "uf_rede_publica" ? "publica" : "municipal", mesma_rede: !contexto, contexto,
    posicao: 0, nome, rotulo, rotulo_contexto: contexto ? "outra rede, só contexto" : null,
    motivo_contexto: contexto ? "O arquivo do Ideb por UF do INEP não traz a rede municipal de São Paulo." : null,
    universo_saeb: { chave: "urbanas", rotulo: URBANAS, indicadores: ["ideb", "nota_saeb", "nota_n"] },
    serie, anos_meta: [2019, 2021], tem_dados: serie.length > 0,
  };
}

/** Níveis SINTÉTICOS (os do teste do backend), com a faixa de cada um. */
const DIST_LP5 = [18.2, 21.5, 17.3, 13.9, 10.4, 7.6, 5.1, 3.4, 1.8, 0.8];
const DIST_MT5 = [12.1, 16.4, 18.7, 16.2, 13.5, 9.8, 6.3, 3.9, 2.0, 0.8, 0.3];
/** O percentual como a tela escreve (2 casas, vírgula), a partir do dado do teste. */
const pct = (v: number) => `${v.toFixed(2).replace(".", ",")}%`;

function faixas(n: number) {
  return Array.from({ length: n }, (_, k) => ({ nivel: k, inicio: k === 0 ? null : 100 + 25 * k,
                                               fim: k === n - 1 ? null : 125 + 25 * k }));
}

function dist(valores: (number | null)[], fonte: FonteOficial): DistribuicaoSaeb {
  const f = faixas(valores.length);
  return {
    niveis: valores.map((v, k) => ({ ...numT(v, 2, fonte), nivel: k, inicio: f[k].inicio, fim: f[k].fim })),
    soma: valores.every((v) => v != null) ? 100 : null,
  };
}

function territorioSaeb(chave: TerritorioSaeb["chave"], nome: string, rotulo: string,
                        medias: [number, number, number, FonteOficial][]): TerritorioSaeb {
  return {
    chave, abrangencia: chave === "rede_municipal" ? "municipio" : chave.startsWith("uf") ? "uf" : "brasil",
    codigo_territorio: chave === "rede_municipal" ? "3599999" : chave.startsWith("uf") ? "35" : "BR",
    rede_ensino: "municipal", localizacao: "total", mesma_rede: true, posicao: 0, nome, rotulo,
    edicoes: medias.map(([edicao, lp, mt, fonte]) => ({
      edicao, media: { lp: numT(lp, 2, fonte), mt: numT(mt, 2, fonte) },
      niveis: { lp: dist(DIST_LP5, fonte), mt: dist(DIST_MT5, fonte) },
    })),
    tem_dados: medias.length > 0,
  };
}

function reguaSaeb(): RedeMunicipalIDEB["saeb"]["regua"] {
  return {
    lp: faixas(10), mt: faixas(11),
    fonte: "INEP — Dicionário da planilha de resultados do Saeb 2025 (Brasil, estados e municípios): de 25 em 25 pontos.",
    edicoes_com_cortes_no_arquivo: [2025],
    texto_outras_edicoes: "As planilhas de 2019 e 2021 trazem os mesmos níveis só pelo número, sem escrever os cortes.",
    unidade: "escala_saeb",
  };
}

function redeVazia(): RedeMunicipalIDEB {
  return {
    ideb: { territorios: [], edicoes: [], anos_meta: [], uf_sem_rede_municipal: false, texto_uf_sem_rede_municipal: null,
            tem_dados: false },
    saeb: { territorios: [], edicoes: [], localizacao: "total", rotulo_localizacao: "Total (escolas urbanas e rurais)",
            regua: reguaSaeb(), edicoes_importadas_rede: [], tem_dados: false },
    avisos: AVISOS_REDE, tem_dados: false,
  };
}

function contextoVazio(): ContextoAmostral {
  return { territorios: [], edicoes: [], desenho: "amostral", etapa: "2_ano", unidade_media: "escala_alfabetizacao",
           aviso: AVISOS_REDE.amostral, nao_e_ica: AVISOS_REDE.nao_e_ica, tem_dados: false };
}

function redeCompleta(): RedeMunicipalIDEB {
  const mun = territorioIdeb("rede_municipal", "Cidade Sintética", "Cidade Sintética — rede municipal", FONTE_MUN, [
    edRede(FONTE_MUN, [2019, 1.2, 1.4, 107.43, 114.86], comp(1.2, 1.4, -0.2, "nao_atingiu")),
    edRede(FONTE_MUN, [2021, 1.5, 1.4, 108.91, 116.27], comp(1.5, 1.4, 0.1, "atingiu")),
    edRede(FONTE_MUN, [2023, null, null, 109.72, 117.35]),
    edRede(FONTE_MUN, [2025, 1.6, null, 110.38, 118.04]),
  ]);
  const br = territorioIdeb("brasil_redes_municipais", "Brasil", "Brasil — redes municipais", FONTE_BR, [
    edRede(FONTE_BR, [2019, 1.1, 1.3, 104.62, 111.38]), edRede(FONTE_BR, [2021, 1.2, 1.3, 105.17, 112.09]),
    edRede(FONTE_BR, [2023, 1.3, null, 105.84, 112.73]), edRede(FONTE_BR, [2025, 1.4, null, 106.51, 113.42]),
  ]);
  const sp = territorioIdeb("uf_rede_publica", "São Paulo", "São Paulo — rede pública (estadual e municipal)", FONTE_UF, [
    edRede(FONTE_UF, [2019, 1.7, 1.6, 112.06, 119.83]), edRede(FONTE_UF, [2021, 1.8, 1.7, 112.94, 120.57]),
    edRede(FONTE_UF, [2023, 1.8, null, 113.61, 121.18]), edRede(FONTE_UF, [2025, 1.9, null, 114.27, 121.96]),
  ], true);
  return {
    ideb: {
      territorios: [mun, br, sp], edicoes: [2019, 2021, 2023, 2025], anos_meta: [2019, 2021],
      uf_sem_rede_municipal: true,
      texto_uf_sem_rede_municipal: "O arquivo do Ideb por UF do INEP não traz a rede municipal de São Paulo (redes "
        + "importadas da UF: total, pública e estadual): São Paulo aparece na rede pública, como contexto rotulado.",
      tem_dados: true,
    },
    saeb: {
      territorios: [
        territorioSaeb("rede_municipal", "Cidade Sintética", "Cidade Sintética — rede municipal",
                       [[2021, 101.37, 108.64, FONTE_SAEB_21], [2025, 102.81, 109.93, FONTE_SAEB]]),
        territorioSaeb("uf_redes_municipais", "São Paulo", "São Paulo — redes municipais",
                       [[2021, 103.42, 110.17, FONTE_SAEB_21], [2025, 104.06, 111.58, FONTE_SAEB]]),
        territorioSaeb("brasil_redes_municipais", "Brasil", "Brasil — redes municipais",
                       [[2021, 100.29, 106.81, FONTE_SAEB_21], [2025, 100.94, 107.36, FONTE_SAEB]]),
      ],
      edicoes: [2021, 2025], localizacao: "total", rotulo_localizacao: "Total (escolas urbanas e rurais)",
      regua: reguaSaeb(), edicoes_importadas_rede: [2021, 2025], tem_dados: true,
    },
    avisos: AVISOS_REDE, tem_dados: true,
  };
}

function contextoCompleto(): ContextoAmostral {
  const t = (chave: string, abrangencia: "uf" | "brasil", nome: string, lp: number, mt: number, tx: number) => ({
    chave, abrangencia, codigo_territorio: abrangencia === "uf" ? "35" : "BR", rede_ensino: "municipal",
    localizacao: "total", desenho: "amostral" as const, posicao: 0, nome,
    rotulo: `${nome} — redes municipais (amostral, só contexto)`,
    edicoes: [{ edicao: 2021, media: { lp: numT(lp, 2, FONTE_SAEB_21), mt: numT(mt, 2, FONTE_SAEB_21) },
                tx_alfabetizado: numT(tx, 2, FONTE_SAEB_21) }],
    tem_dados: true,
  });
  return { ...contextoVazio(), edicoes: [2021], tem_dados: true,
           territorios: [t("uf_redes_municipais", "uf", "São Paulo", 612.4, 621.7, 11.2),
                         t("brasil_redes_municipais", "brasil", "Brasil", 614.7, 623.8, 11.9)] };
}

function resposta(over: Partial<RespostaIDEB> = {}): RespostaIDEB {
  const alfa = escola(11, "EMEF Sintética Alfa", "35990101", [
    ed(2019, [1.5, 124.83, 131.47, 2.381946, 0.612347, 23.6],
       { meta: num(2.3, 1), comparacao_meta: comp(1.5, 2.3, -0.8, "nao_atingiu") }),
    ed(2021, [1.6, 127.61, 133.29, 2.452318, 0.637219, 24.9],
       { meta: num(2.4, 1), comparacao_meta: comp(1.6, 2.4, -0.8, "nao_atingiu"),
         variacao_ideb: { desde: 2019, diferenca: 0.1, casas_decimais: 1 } }),
    ed(2023, [1.7, 129.94, 135.18, 2.513467, 0.659821, 26.2],
       { variacao_ideb: { desde: 2021, diferenca: 0.1, casas_decimais: 1 } }),
  ]);
  const beta = escola(12, "EMEF Sintética Beta", "35990102", [
    ed(2019, [1.5, 118.29, 123.47, 2.164903, 0.708426, 34.6], { meta: num(null, 1) }),
    ed(2021, [null, null, null, null, 0.693518, 36.1], { meta: num(2.2, 1) }),
    ed(2023, [null, null, null, null, null, null]),
  ]);
  const delta = escola(13, "EMEF Sintética Delta", "35990105", [
    ed(2019, [2.2, 121.07, 126.41, 2.351862, 0.583164, 47.2],
       { meta: num(2.2, 1), comparacao_meta: comp(2.2, 2.2, 0, "atingiu") }),
    ed(2021, [2.4, 122.56, 127.83, 2.398417, 0.591427, 48.9],
       { meta: num(2.1, 1), comparacao_meta: comp(2.4, 2.1, 0.3, "atingiu"),
         variacao_ideb: { desde: 2019, diferenca: 0.2, casas_decimais: 1 } }),
    ed(2023, [2.3, 123.95, 128.62, 2.427649, 0.596318, 49.6],
       { variacao_ideb: { desde: 2021, diferenca: -0.1, casas_decimais: 1 } }),
  ]);
  const zeta = escola(15, "EMEF Sintética Zeta", "35990106", ANOS.map((a) => ed(a, null)));
  const gama = escola(14, "EMEF SINTETICA GAMA", null, ANOS.map((a) => ed(a, null, { motivo: "sem_codigo_inep" })));
  const ref = (e: EscolaIDEB) => ({ escola_id: e.escola_id, nome: e.nome, codigo_inep: e.codigo_inep });
  return {
    rede_id: 1, rede_nome: "Rede Sintética", codigo_ibge: "3599999", municipio: "Cidade Sintética",
    indicadores: {
      ideb: { chave: "ideb", nome: "IDEB", orgao: "INEP", descricao: "" },
      saeb: { chave: "saeb", nome: "SAEB", orgao: "INEP", descricao: "" },
    },
    pendencias: [],
    avisos: {
      comparabilidade: "A série do Ideb e do Saeb do 5º ano (2019–2023) não é comparável em todo o período. O aviso vale para a série TODA, não só para 2021.",
      pandemia: "2021 foi aplicado na pandemia: o INEP publicou uma nota própria.",
      sem_ranking: "A tabela por escola está em ordem alfabética: não é ranking.",
      ausencia: "Sem resultado não é zero.",
      participacao: "A participação por escola depende de uma decisão ainda pendente (D8).",
      metas: "Metas do Ideb: só as do 1º ciclo.",
      precisao: "Ideb e meta comparados na precisão publicada (1 casa decimal). Ideb igual ou acima da meta = atingiu.",
      escala: "O Saeb do 5º ano tem escala própria.",
      sem_registro: "Números marcados “sem registro oficial” foram gravados antes, pelo botão de 1 clique.",
      media_das_escolas: "O Constela não calcula a média das escolas no lugar do número oficial da rede.",
    },
    campos: { ideb: { rotulo: "Ideb", unidade: "indice", casas_publicadas: 1 } },
    edicoes: ANOS, anos_meta: [2019, 2021],
    // De propósito FORA da ordem alfabética: a tela mostra por NOME.
    escolas: [zeta, gama, delta, beta, alfa],
    cobertura: [2023, 2021, 2019].map((edicao) => ({
      edicao, total_escolas: 5, com_ideb: edicao === 2019 ? 3 : 2, com_saeb: edicao === 2019 ? 3 : 2,
      sem_resultado: edicao === 2019 ? [] : [{ ...ref(beta), motivo: "nao_divulgado" }],
      sem_linha_no_arquivo: [ref(zeta)], sem_inep: [ref(gama)],
      fora_do_cadastro: [{ codigo_inep: "35990103", nome_no_arquivo: "EMEF SINTETICA GAMA (fora do cadastro)" }],
      arquivo_importado: true, fonte_id: FONTE.importacao_id,
    })),
    sem_registro_oficial: { total: 0, por_edicao: {}, difere_do_oficial: 0 },
    participacao: { disponivel: false, decisao: "D8",
                    texto: "A participação por escola depende de uma decisão ainda pendente (D8)." },
    rede_municipal: redeVazia(),
    contexto_amostral: contextoVazio(),
    pendentes: [
      { chave: "ideb_escolas_2025", edicao: 2025, situacao: "sem_importacao",
        arquivo: "divulgacao_anos_iniciais_escolas_2025.zip",
        texto: "Ideb e Saeb 2025 por escola: o arquivo oficial do INEP não foi importado para esta rede." },
      { chave: "ideb_municipio", edicao: null, situacao: "sem_importacao",
        arquivo: "divulgacao_anos_iniciais_municipios_AAAA.zip",
        texto: "Ideb da rede municipal: o arquivo oficial do INEP não foi importado para esta rede." },
      { chave: "saeb_planilha_2023", edicao: 2023, situacao: "adiado", arquivo: "planilha_de_resultados_2023.rar",
        texto: "Saeb 2023 pela planilha do INEP (RAR com XLSB): adiado." },
    ],
    fontes: [FONTE],
    tem_dados_escolas: true,
    tem_dados: true,
    ...over,
  };
}

async function montar(dados: RespostaIDEB = resposta(), ehGlobal = false) {
  responder("GET", "/redes/1/indicadores/ideb", dados);
  const r = renderComApp(<CartaoIDEB redeId={1} ehGlobal={ehGlobal} />, { usuario: secretaria });
  await screen.findByTestId("cartao-ideb");
  return r;
}

function tabelaEscolas(edicao: number): HTMLElement {
  return screen.getByRole("table", { name: new RegExp(`Ideb e Saeb do 5º ano em ${edicao} por escola`) });
}

function linhaDa(tabela: HTMLElement, cabecalho: string): HTMLElement {
  const tr = within(tabela).getByRole("rowheader", { name: cabecalho }).closest("tr");
  if (!tr) throw new Error(`sem linha para ${cabecalho}`);
  return tr;
}

/** As linhas de grade do eixo Y (rótulo e altura), de baixo para cima. */
function eixoY(grafico: HTMLElement): { rotulo: number; y: number }[] {
  const svg = grafico.querySelector("svg");
  if (!svg) throw new Error("gráfico sem svg");
  return Array.from(svg.children).flatMap((g) => {
    const linha = Array.from(g.children).find((c) => c.tagName.toLowerCase() === "line");
    const texto = Array.from(g.children).find((c) => c.tagName.toLowerCase() === "text");
    return linha && texto ? [{ rotulo: Number(texto.textContent), y: Number(linha.getAttribute("y1")) }] : [];
  });
}

/** Os trechos (polylines) de UMA série do gráfico, pela cor. */
function trechos(grafico: HTMLElement, cor: string): string[][] {
  return Array.from(grafico.querySelectorAll(`polyline[stroke="${cor}"]`))
    .map((p) => (p.getAttribute("points") ?? "").trim().split(/\s+/).filter(Boolean));
}

describe("Aba IDEB e SAEB — por escola", () => {
  it("ordem por NOME (sem ranking), a edição mais nova primeiro e 'Ideb não divulgado' (nunca 0)", async () => {
    await montar();
    expect(await screen.findByRole("tab", { name: "Por escola" })).toHaveAttribute("aria-selected", "true");
    const tabela = tabelaEscolas(2023);
    expect(within(tabela).getAllByRole("rowheader").map((th) => th.textContent)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEF SINTETICA GAMA",
      "EMEF Sintética Zeta"]);
    expect(screen.getByTestId("cartao-ideb").textContent).not.toMatch(/ranking:|melhor|pior|posição/i);
    expect(linhaDa(tabela, "EMEF Sintética Alfa")).toHaveTextContent("1,7");
    expect(linhaDa(tabela, "EMEF Sintética Alfa")).toHaveTextContent("129,94");
    expect(linhaDa(tabela, "EMEF Sintética Alfa")).toHaveTextContent("+0,1 desde 2021");
    const beta = linhaDa(tabela, "EMEF Sintética Beta");
    expect(beta).toHaveTextContent("Ideb não divulgado");
    // LP e MT sem número pelo mesmo motivo: uma célula só (cabe no celular).
    expect(within(beta).getByText("Saeb não divulgado")).toHaveAttribute("colspan", "2");
    expect(beta.textContent).not.toMatch(/(^|\s)0(,0)?(\s|$)/);
    expect(linhaDa(tabela, "EMEF SINTETICA GAMA")).toHaveTextContent(
      "sem código INEP Pendência de cadastro: sem o código INEP, a escola não casa com o arquivo oficial.");
    expect(linhaDa(tabela, "EMEF Sintética Zeta")).toHaveTextContent(
      "Sem resultado: a escola não tem linha no arquivo oficial importado.");
    // 2023: o INEP não definiu meta — nada comparado.
    expect(screen.getByTestId("ideb-metas-edicao")).toHaveTextContent(
      "Metas: o INEP não definiu meta do Ideb para 2023 — nada é comparado.");
    expect(within(tabela).queryByText(/atingiu/)).toBeNull();
  });

  it("meta × observado na precisão publicada: não atingiu, atingiu e o empate = atingiu (Ideb ≥ meta)", async () => {
    const u = userEvent.setup();
    await montar();
    await u.selectOptions(screen.getByLabelText("Edição"), "2019");
    const t19 = tabelaEscolas(2019);
    const alfa = linhaDa(t19, "EMEF Sintética Alfa");
    expect(alfa).toHaveTextContent("1,5");
    expect(alfa).toHaveTextContent("meta 2,3");
    expect(within(alfa).getByText("não atingiu (−0,8)")).toBeInTheDocument();
    // 2,2 × 2,2: o empate na precisão publicada é "atingiu" (o Ideb de 1 casa é o oficial).
    expect(within(linhaDa(t19, "EMEF Sintética Delta")).getByText("atingiu (0,0)")).toBeInTheDocument();
    expect(screen.getByTestId("cartao-ideb").textContent).not.toMatch(/inconclusivo|empate/);
    expect(linhaDa(t19, "EMEF Sintética Beta")).toHaveTextContent("meta não divulgada");
    expect(screen.getByTestId("ideb-metas-edicao")).toHaveTextContent("na precisão publicada (1 casa decimal)");
    expect(screen.getByTestId("ideb-metas-edicao")).toHaveTextContent("Ideb igual ou acima da meta = atingiu");
    await u.selectOptions(screen.getByLabelText("Edição"), "2021");
    const t21 = tabelaEscolas(2021);
    expect(within(linhaDa(t21, "EMEF Sintética Delta")).getByText("atingiu (+0,3)")).toBeInTheDocument();
    // A Beta tem meta em 2021, mas o Ideb não foi divulgado: nada comparado.
    const beta21 = linhaDa(t21, "EMEF Sintética Beta");
    expect(beta21).toHaveTextContent("Ideb não divulgado");
    expect(beta21).toHaveTextContent("meta 2,2");
    expect(within(beta21).queryByText(/atingiu/)).toBeNull();
  });

  it("cada número com a fonte; selo do bloco com a divulgação e a data do arquivo; participação sem coluna", async () => {
    await montar();
    const tabela = tabelaEscolas(2023);
    const fonte = textoFonte(FONTE);
    expect(fonte).toBe("INEP — Ideb por escola, anos iniciais (Ideb, Saeb do 5º ano e rendimento), divulgação 2023, "
      + "arquivo de 02/06/2031 (ideb.zip)");
    expect(within(tabela).getByText("1,7").closest("[title]")).toHaveAttribute("title", `Fonte: ${fonte}`);
    expect(within(tabela).getByText("135,18").closest("[title]")).toHaveAttribute("title", `Fonte: ${fonte}`);
    const selo = screen.getByTestId("ideb-selo-escolas");
    expect(selo).toHaveTextContent(`Fonte: ${fonte}`);
    expect(selo).toHaveTextContent("Licença sintética de teste");
    // Participação: a coluna NÃO existe; a tela explica (só com a D8).
    expect(within(tabela).queryByRole("columnheader", { name: /participa/i })).toBeNull();
    expect(screen.getByTestId("ideb-participacao")).toHaveTextContent(
      "Participação por escola: sem coluna. A participação por escola depende de uma decisão ainda pendente (D8).");
  });

  it("números do 1 clique: marcados 'sem registro oficial' (e 'difere do arquivo oficial'), com o bloco explicando", async () => {
    const dados = resposta();
    const alfa = dados.escolas.find((e) => e.nome === "EMEF Sintética Alfa");
    if (!alfa) throw new Error("fixture sem a Alfa");
    const a23 = alfa.serie[2];
    const antigo = { proveniencia: "sem_registro" as const, fonte_id: null, fonte_texto: "IDEB 2023 — arquivo_sintetico.zip",
                     gravado_em: "2031-04-20T10:00:00", difere_do_oficial: false };
    a23.ideb = { ...num(1.7, 1), ...antigo };
    a23.saeb_mt = { ...num(134.81, 2), ...antigo, difere_do_oficial: true, recusado_na_importacao: 41 };
    dados.sem_registro_oficial = { total: 2, por_edicao: { "2023": 2 }, difere_do_oficial: 1 };
    await montar(dados);
    const linha = linhaDa(tabelaEscolas(2023), "EMEF Sintética Alfa");
    const marcas = within(linha).getAllByTestId("ideb-marca-sem-registro");
    expect(marcas).toHaveLength(2);                                  // Ideb e MT (a LP é oficial)
    expect(marcas[0].textContent).toMatch(/^\* \(sem registro oficial: IDEB 2023 — arquivo_sintetico\.zip — gravado em/);
    expect(marcas[1]).toHaveTextContent("difere do arquivo oficial");
    expect(marcas[1]).toHaveTextContent("≠ arquivo oficial");
    expect(marcas[0]).toHaveAttribute("title",
      expect.stringContaining("Sem registro oficial: IDEB 2023 — arquivo_sintetico.zip — gravado em"));
    // O número sem registro não leva a fonte oficial no título; a LP (oficial) leva.
    expect(within(linha).getByText("1,7").closest("[title]")).toBeNull();
    expect(within(linha).getByText("129,94").closest("[title]")).toHaveAttribute("title", `Fonte: ${textoFonte(FONTE)}`);
    expect(screen.getByTestId("ideb-legenda-sem-registro")).toHaveTextContent("* sem registro oficial");
    const bloco = screen.getByTestId("ideb-sem-registro");
    expect(bloco).toHaveTextContent("gravados antes, pelo botão de 1 clique");
    expect(bloco).toHaveTextContent("Nesta rede: 2 número(s) sem registro oficial (2 em 2023).");
    expect(bloco).toHaveTextContent("1 difere do arquivo oficial: a troca pelo número do arquivo foi recusada");
    // A origem e a data À VISTA (no celular não há o título da marca), uma vez só.
    const origens = screen.getByTestId("ideb-origens-escolas");
    expect(origens.querySelectorAll("p")).toHaveLength(1);
    expect(origens).toHaveTextContent(/^\* Sem registro oficial: IDEB 2023 — arquivo_sintetico\.zip — gravado em/);
  });

  it("só números do 1 clique (sem arquivo oficial): a origem e a data à vista, sem selo oficial; uma edição = “(2023)”", async () => {
    const u = userEvent.setup();
    const antigo = (fonte_texto: string) => ({ proveniencia: "sem_registro" as const, fonte_id: null, fonte_texto,
                                              gravado_em: "2031-04-20T10:00:00", difere_do_oficial: false });
    const a23 = ed(2023, [1.7, 129.94, 135.18, null, null, null], {
      ideb: { ...num(1.7, 1), ...antigo("IDEB 2023 — arquivo_sintetico.zip") },
      saeb_lp: { ...num(129.94, 2), ...antigo("SAEB 2023 — arquivo_sintetico.zip") },
      saeb_mt: { ...num(135.18, 2), ...antigo("SAEB 2023 — arquivo_sintetico.zip") },
      nota_n: null, rendimento_p: null, sem_meta: "sem_arquivo_oficial",
      aprovacao: { anos_iniciais: null, "1_ano": null, "2_ano": null, "3_ano": null, "4_ano": null, "5_ano": null },
    });
    const alfa = escola(11, "EMEF Sintética Alfa", "35990101", [a23]);
    const beta = escola(12, "EMEF Sintética Beta", "35990102", [ed(2023, null, { motivo: "sem_importacao" })]);
    const dados = resposta({
      escolas: [beta, alfa], edicoes: [2023], anos_meta: [], fontes: [],
      cobertura: [{ edicao: 2023, total_escolas: 2, com_ideb: 1, com_saeb: 1,
                    sem_resultado: [{ escola_id: 12, nome: beta.nome, codigo_inep: beta.codigo_inep, motivo: "sem_importacao" }],
                    sem_linha_no_arquivo: [], sem_inep: [], fora_do_cadastro: [], arquivo_importado: false, fonte_id: null }],
      sem_registro_oficial: { total: 3, por_edicao: { "2023": 3 }, difere_do_oficial: 0 },
    });
    dados.avisos.comparabilidade = "A série do Ideb e do Saeb do 5º ano (2023) não é comparável em todo o período.";
    await montar(dados);
    expect(linhaDa(tabelaEscolas(2023), "EMEF Sintética Alfa")).toHaveTextContent("1,7");
    expect(screen.queryByTestId("ideb-selo-escolas")).toBeNull();            // nenhuma fonte oficial
    const origens = screen.getByTestId("ideb-origens-escolas");
    expect(Array.from(origens.querySelectorAll("p")).map((p) => p.textContent?.replace(/ — gravado em .*$/, ""))).toEqual([
      "* Sem registro oficial: IDEB 2023 — arquivo_sintetico.zip",
      "* Sem registro oficial: SAEB 2023 — arquivo_sintetico.zip"]);       // LP e MT: a mesma origem, uma linha
    expect(origens).toHaveTextContent("gravado em");
    await u.click(screen.getByRole("tab", { name: "Série de uma escola" }));
    expect(screen.getByRole("heading", { name: "Série de EMEF Sintética Alfa (2023)" })).toBeInTheDocument();
    expect(screen.getByTestId("ideb-origens-serie")).toHaveTextContent("Sem registro oficial: SAEB 2023 — arquivo_sintetico.zip");
    expect(screen.queryByTestId("ideb-selo-serie")).toBeNull();
    expect(screen.getByTestId("cartao-ideb").textContent).not.toContain("2023–2023");
  });
});

describe("Aba IDEB e SAEB — avisos", () => {
  it("comparabilidade da série TODA (com a nota de 2021) e o que falta — nunca 'aguardando'", async () => {
    await montar();
    const aviso = screen.getByTestId("ideb-aviso-comparabilidade");
    expect(aviso).toHaveTextContent("(2019–2023) não é comparável em todo o período");
    expect(aviso).toHaveTextContent("vale para a série TODA, não só para 2021");
    expect(aviso).toHaveTextContent("2021 foi aplicado na pandemia");
    const pendentes = screen.getByTestId("ideb-pendentes");
    // O ADIADO à vista; o que a base não importou, a um toque.
    expect(pendentes).toHaveTextContent("Saeb 2023 pela planilha do INEP (RAR com XLSB): adiado.");
    const sem = within(pendentes).getByTestId("ideb-pendentes-sem-importacao");
    expect(sem).toHaveTextContent("Arquivos oficiais ainda não importados nesta rede (2)");
    expect(sem.querySelectorAll("li")).toHaveLength(2);
    expect(sem).toHaveTextContent("Ideb e Saeb 2025 por escola: o arquivo oficial do INEP não foi importado");
    expect(screen.getByTestId("cartao-ideb").textContent).not.toMatch(/aguardando/i);
    // Nenhum número de município, SP ou Brasil inventado na tela.
    expect(screen.getByTestId("cartao-ideb").textContent).not.toMatch(/média das escolas: \d/);
  });

  it("com tudo importado: só a planilha de 2023 (adiada) aparece no que falta", async () => {
    const dados = resposta({ pendentes: [{ chave: "saeb_planilha_2023", edicao: 2023, situacao: "adiado",
                                          arquivo: "planilha_de_resultados_2023.rar",
                                          texto: "Saeb 2023 pela planilha do INEP (RAR com XLSB): adiado." }] });
    await montar(dados);
    const pendentes = screen.getByTestId("ideb-pendentes");
    expect(pendentes).toHaveTextContent("adiado");
    expect(within(pendentes).queryByTestId("ideb-pendentes-sem-importacao")).toBeNull();
    expect(pendentes.textContent).not.toContain("2025");
  });

  it("2021 só na série da rede (sem escola em 2021): a nota da pandemia aparece", async () => {
    const dados = comRede({ edicoes: [2019, 2023] });
    await montar(dados);
    expect(dados.rede_municipal.ideb.edicoes).toContain(2021);
    expect(screen.getByTestId("ideb-aviso-comparabilidade")).toHaveTextContent("2021 foi aplicado na pandemia");
  });

  it("sem 2021 na série, o aviso de comparabilidade continua (vale para a série toda)", async () => {
    const dados = resposta({ edicoes: [2019, 2023] });
    dados.avisos.comparabilidade = "A série (2019–2023) não é comparável em todo o período: vale para a série TODA.";
    await montar(dados);
    const aviso = screen.getByTestId("ideb-aviso-comparabilidade");
    expect(aviso).toHaveTextContent("vale para a série TODA");
    expect(aviso).not.toHaveTextContent("pandemia");
  });
});

describe("Aba IDEB e SAEB — série de uma escola", () => {
  it("Ideb com a meta TRACEJADA num gráfico, Saeb noutro, e a tabela equivalente", async () => {
    const u = userEvent.setup();
    await montar();
    await u.click(screen.getByRole("tab", { name: "Série de uma escola" }));
    // A primeira por nome com resultado: a Alfa.
    expect(screen.getByLabelText("Escola")).toHaveDisplayValue("EMEF Sintética Alfa");
    const gIdeb = screen.getByTestId("ideb-grafico-ideb");
    expect(trechos(gIdeb, "#6C5CE7").map((t) => t.length)).toEqual([3]);       // 2019–2023 ligados
    const meta = gIdeb.querySelectorAll('polyline[stroke-dasharray="6 4"]');
    expect(meta).toHaveLength(1);
    expect((meta[0].getAttribute("points") ?? "").trim().split(/\s+/)).toHaveLength(2);   // 2019 e 2021
    expect(within(gIdeb).getByText("Meta do Ideb (1º ciclo) (tracejada)")).toBeInTheDocument();
    const gSaeb = screen.getByTestId("ideb-grafico-saeb");
    expect(within(gSaeb).getByText("Língua Portuguesa")).toBeInTheDocument();
    expect(within(gSaeb).getByText("Matemática")).toBeInTheDocument();
    expect(gIdeb.querySelector("svg")).toHaveAttribute("aria-label", expect.stringContaining("com a meta do 1º ciclo tracejada"));
    const tabela = screen.getByRole("table", { name: /Números dos gráficos: Ideb, meta e Saeb do 5º ano de EMEF Sintética Alfa/ });
    expect(within(tabela).getAllByRole("rowheader").map((th) => th.textContent)).toEqual(["2019", "2021", "2023"]);
    const l19 = linhaDa(tabela, "2019");
    for (const trecho of ["1,5", "meta 2,3", "não atingiu (−0,8)", "124,83", "131,47"]) {
      expect(l19).toHaveTextContent(trecho);
    }
    // Eixo do Ideb da Alfa (1,5 a 2,4): faixa 1–3, cada linha com o seu valor.
    expect(eixoY(gIdeb).map((l) => l.rotulo)).toEqual([1, 2, 3]);
    const npa = screen.getByTestId("ideb-n-p-aprovacao");
    expect(npa).toHaveTextContent("2,381946");
    expect(npa).toHaveTextContent("23,6%");
    expect(screen.getByTestId("ideb-selo-serie")).toHaveTextContent("divulgação 2023, arquivo de 02/06/2031");
  });

  it("escolher outra escola: a linha quebra onde não há número (nunca 0) e só entram escolas com resultado", async () => {
    const u = userEvent.setup();
    await montar();
    await u.click(screen.getByRole("tab", { name: "Série de uma escola" }));
    const seletor = screen.getByLabelText("Escola");
    expect(within(seletor).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta"]);   // Gama e Zeta sem número
    await u.selectOptions(seletor, "EMEF Sintética Beta");
    const gIdeb = screen.getByTestId("ideb-grafico-ideb");
    expect(trechos(gIdeb, "#6C5CE7").map((t) => t.length)).toEqual([1]);       // só 2019: lacuna depois
    const tabela = screen.getByRole("table", { name: /Números dos gráficos: .* EMEF Sintética Beta/ });
    expect(linhaDa(tabela, "2023")).toHaveTextContent("Ideb não divulgado");
    expect(linhaDa(tabela, "2023").textContent).not.toMatch(/(^|\s)0(,0)?(\s|$)/);
  });

  it("eixo do Ideb com faixa de amplitude ímpar: cada linha de grade rotulada com o SEU valor", async () => {
    // Ideb de 1,1 a 2,4 (INVENTADOS): a faixa 0–3 poria a linha do meio em 1,5, rotulada "2".
    const u = userEvent.setup();
    const dados = resposta();
    const alfa = dados.escolas.find((e) => e.nome === "EMEF Sintética Alfa");
    if (!alfa) throw new Error("fixture sem a Alfa");
    alfa.serie[0].ideb = num(1.1, 1);
    await montar(dados);
    await u.click(screen.getByRole("tab", { name: "Série de uma escola" }));
    const gIdeb = screen.getByTestId("ideb-grafico-ideb");
    const eixo = eixoY(gIdeb);
    expect(eixo.map((l) => l.rotulo)).toEqual([0, 2, 4]);
    // O rótulo do meio é o valor da linha do meio (sem arredondar) ...
    const [baixo, meio, topo] = eixo;
    const valorEm = (y: number) => baixo.rotulo + ((topo.rotulo - baixo.rotulo) * (baixo.y - y)) / (baixo.y - topo.y);
    expect(valorEm(meio.y)).toBe(meio.rotulo);
    // ... e os pontos caem onde o eixo diz.
    for (const [titulo, valor] of [["Ideb observado — 2019: 1,1", 1.1], ["Ideb observado — 2021: 1,6", 1.6],
                                   ["Meta do Ideb (1º ciclo) — 2021: 2,4", 2.4]] as const) {
      const ponto = Array.from(gIdeb.querySelectorAll("circle")).find((c) => c.querySelector("title")?.textContent === titulo);
      expect(ponto, titulo).toBeTruthy();
      expect(valorEm(Number(ponto?.getAttribute("cy")))).toBeCloseTo(valor, 6);
    }
  });
});

describe("Aba IDEB e SAEB — cobertura", () => {
  it("com Ideb/Saeb, sem resultado, sem linha no arquivo, sem INEP e códigos do arquivo fora do cadastro", async () => {
    const u = userEvent.setup();
    await montar();
    await u.click(screen.getByRole("tab", { name: "Cobertura" }));
    const c = screen.getByTestId("ideb-cobertura-2023");
    expect(c).toHaveTextContent("2 de 5 escolas da rede com Ideb em 2023; 2 com Saeb do 5º ano.");
    expect(c).toHaveTextContent("Sem Ideb (1) — sem resultado não é zero:EMEF Sintética Beta: Ideb não divulgado");
    expect(c).toHaveTextContent("Com código INEP, sem linha no arquivo oficial (1):EMEF Sintética Zeta (INEP 35990106)");
    expect(c).toHaveTextContent("Sem código INEP no cadastro (1) — pendência de cadastro:EMEF SINTETICA GAMA");
    expect(c).toHaveTextContent("INEP 35990103 — “EMEF SINTETICA GAMA (fora do cadastro)”, como está no arquivo");
    expect(c).toHaveTextContent("só pelo código INEP, nunca pelo nome");
    expect(c).toHaveTextContent("Fonte: INEP — Ideb por escola");
    expect(c).toHaveTextContent("Notas: ND - marcador sintético de não divulgação;");
    await u.selectOptions(screen.getByLabelText("Edição"), "2019");
    expect(screen.getByTestId("ideb-cobertura-2019")).toHaveTextContent("3 de 5 escolas da rede com Ideb em 2019");
  });
});

function comRede(over: Partial<RespostaIDEB> = {}): RespostaIDEB {
  return resposta({
    rede_municipal: redeCompleta(), contexto_amostral: contextoCompleto(),
    fontes: [FONTE, FONTE_MUN, FONTE_UF, FONTE_BR, FONTE_SAEB, FONTE_SAEB_21], ...over,
  });
}

/** Só a referência pública — o estado e o Brasil que OUTRA rede importou —, nada da rede: o
 *  território do município vazio e `rede_municipal.tem_dados` falso, como a API manda. */
function soReferencia(over: Partial<RespostaIDEB> = {}): RespostaIDEB {
  const completa = redeCompleta();
  const vazio = <T extends { tem_dados: boolean }>(t: T, campo: "serie" | "edicoes"): T => ({ ...t, [campo]: [], tem_dados: false });
  const rede: RedeMunicipalIDEB = {
    ...completa,
    ideb: { ...completa.ideb,
            territorios: completa.ideb.territorios.map((t) => (t.chave === "rede_municipal" ? vazio(t, "serie") : t)) },
    saeb: { ...completa.saeb, edicoes_importadas_rede: [],
            territorios: completa.saeb.territorios.map((t) => (t.chave === "rede_municipal" ? vazio(t, "edicoes") : t)) },
    tem_dados: false,
  };
  const pendentes = [
    ...resposta().pendentes,
    ...[2019, 2021, 2025].map((edicao) => ({
      chave: `saeb_planilha_${edicao}`, edicao, situacao: "sem_importacao" as const, arquivo: `planilha_${edicao}.xlsx`,
      texto: `Saeb ${edicao} pela planilha do INEP (médias e níveis do 5º ano): não foi importado para esta rede.`,
    })),
  ];
  return comRede({ rede_municipal: rede, pendentes, ...over });
}

/** A rede sem o arquivo de UF (e, com `semBrasil`, sem o do Brasil): o território vem vazio e
 *  sem motivo (a API não afirma o que um arquivo não importado traz). */
function semArquivoDeUf(semBrasil = false): RespostaIDEB {
  const dados = comRede();
  const ideb = dados.rede_municipal.ideb;
  ideb.territorios = ideb.territorios.map((t) =>
    t.chave === "uf_rede_publica" || (semBrasil && t.chave === "brasil_redes_municipais")
      ? { ...t, serie: [], tem_dados: false, motivo_contexto: null } : t);
  ideb.uf_sem_rede_municipal = false;
  ideb.texto_uf_sem_rede_municipal = null;
  return dados;
}

function tabelaIdebRede(): HTMLElement {
  return screen.getByRole("table", { name: /^Ideb por edição:/ });
}

describe("Aba IDEB e SAEB — rede municipal", () => {
  it("abre na rede: Ideb × meta tracejada × Brasil municipal no gráfico; a UF pública FORA dele, rotulada", async () => {
    await montar(comRede());
    expect(screen.getByRole("tab", { name: "Rede municipal" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Ideb da rede municipal (2019–2025)" })).toBeInTheDocument();
    const g = screen.getByTestId("ideb-rede-grafico");
    // A rede (violeta, com a lacuna de 2023), a meta TRACEJADA e o Brasil (vermelho); sem a UF pública.
    expect(trechos(g, "#6C5CE7").map((t) => t.length)).toEqual([2, 1]);
    expect(g.querySelectorAll('polyline[stroke-dasharray="6 4"]')).toHaveLength(1);
    expect(trechos(g, "#DC2626").map((t) => t.length)).toEqual([4]);
    expect(within(g).getByText("Brasil — redes municipais")).toBeInTheDocument();
    expect(within(g).queryByText(/São Paulo/)).toBeNull();
    expect(g.querySelector("svg")).toHaveAttribute("aria-label", expect.stringContaining("(mesma rede)"));
    const contexto = screen.getByTestId("ideb-rede-contexto");
    expect(contexto).toHaveTextContent("São Paulo — rede pública (estadual e municipal): outra rede, só contexto.");
    expect(contexto).toHaveTextContent("não traz a rede municipal de São Paulo");
    expect(screen.getByTestId("ideb-rede")).toHaveTextContent("não entra no gráfico: é outra rede");
  });

  it("tabela do Ideb da rede: meta e 'atingiu/não atingiu' na rede; Brasil e a UF (contexto) ao lado; ausência ≠ 0", async () => {
    await montar(comRede());
    const t = tabelaIdebRede();
    expect(within(t).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Edição", "Rede municipal", "Brasil (redes municipais)", "São Paulo (rede pública)outra rede, só contexto"]);
    const l19 = linhaDa(t, "2019");
    expect(l19).toHaveTextContent("1,2");
    expect(l19).toHaveTextContent("meta 1,4");
    expect(within(l19).getByText("não atingiu (−0,2)")).toBeInTheDocument();
    expect(within(l19).getAllByText(/atingiu/)).toHaveLength(1);              // só a rede tem a situação
    expect(within(linhaDa(t, "2021")).getByText("atingiu (+0,1)")).toBeInTheDocument();
    const l23 = linhaDa(t, "2023");
    expect(l23).toHaveTextContent("Ideb não divulgado");
    expect(l23.textContent).not.toMatch(/(^|\s)0(,0)?(\s|$)/);
    expect(linhaDa(t, "2025")).toHaveTextContent("1,6");
    expect(screen.getByTestId("ideb-rede-metas")).toHaveTextContent(
      "Em 2023 e 2025, o INEP não definiu meta do Ideb (as metas do 1º ciclo vão até 2021) — nada é comparado.");
    // Cada número com a SUA fonte (divulgação do arquivo do município, da UF ou do Brasil).
    expect(within(l19).getByText("1,2").closest("[title]")).toHaveAttribute("title", `Fonte: ${textoFonte(FONTE_MUN)}`);
    expect(textoFonte(FONTE_MUN)).toContain("divulgação 2025");
    const selo = screen.getByTestId("ideb-rede-selo");
    for (const f of [FONTE_MUN, FONTE_UF, FONTE_BR]) expect(selo).toHaveTextContent(`Fonte: ${textoFonte(f)}`);
  });

  it("a nota do Saeb do Ideb só na seção do Ideb, com o universo (só escolas urbanas)", async () => {
    await montar(comRede());
    const nota = screen.getByTestId("ideb-rede-nota-saeb");
    expect(within(nota).getByTestId("ideb-rede-universo")).toHaveTextContent(
      "Universo da nota do Saeb no Ideb: Só escolas urbanas (universo do INEP no Ideb)");
    const tabela = within(nota).getByRole("table", { name: /Nota do Saeb que entra no Ideb \(só escolas urbanas\)/ });
    const n25 = linhaDa(tabela, "2025");
    expect(n25).toHaveTextContent("110,38");
    expect(n25).toHaveTextContent("118,04");
    expect(nota).toHaveTextContent("nunca se compara com a média “Total” da planilha");
    // A seção do Saeb (planilha) não mostra a nota do Ideb.
    expect(screen.getByTestId("ideb-saeb-rede").textContent).not.toContain("110,38");
  });

  it("Saeb da planilha: localização Total explícita, médias na mesma dependência e 2023 adiado", async () => {
    await montar(comRede());
    expect(screen.getByTestId("ideb-saeb-localizacao")).toHaveTextContent(
      "Localização: Total (escolas urbanas e rurais). Comparação na mesma dependência: as redes municipais.");
    const t = screen.getByRole("table", { name: /^Média do Saeb do 5º ano .* localização Total/ });
    expect(within(t).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Edição", "Rede municipal", "São Paulo (redes municipais)", "Brasil (redes municipais)"]);
    const l25 = linhaDa(t, "2025");
    expect(l25).toHaveTextContent("LP 102,81");
    expect(l25).toHaveTextContent("MT 109,93");
    expect(l25).toHaveTextContent("LP 104,06");
    expect(screen.getByTestId("ideb-saeb-2023")).toHaveTextContent("Saeb 2023 pela planilha do INEP (RAR com XLSB): adiado.");
    expect(screen.getByTestId("ideb-saeb-rede-selo")).toHaveTextContent(`Fonte: ${textoFonte(FONTE_SAEB)}`);
    expect(textoFonte(FONTE_SAEB)).toContain("Saeb 2025");
  });

  it("níveis: barras empilhadas com 10 (LP) e 11 (MT) níveis, tabela com os níveis nas linhas e os cortes com a fonte", async () => {
    const u = userEvent.setup();
    await montar(comRede());
    const niveis = screen.getByTestId("ideb-saeb-niveis");
    const barras = within(niveis).getAllByRole("img");
    // A rede em 2021 e 2025; o estado e o Brasil (redes municipais) em 2025.
    expect(barras.map((b) => b.getAttribute("aria-label")?.split(" — Nível")[0])).toEqual([
      "Cidade Sintética — rede municipal — 2021", "Cidade Sintética — rede municipal — 2025",
      "São Paulo — redes municipais — 2025", "Brasil — redes municipais — 2025"]);
    expect(barras[1].children).toHaveLength(10);
    expect(barras[1]).toHaveAttribute("aria-label", expect.stringContaining(`Nível 9: ${pct(DIST_LP5[9])}`));
    // Sem a tabela embutida de uma coluna por nível (rolaria no celular): a nossa, com os níveis nas LINHAS.
    const tabela = within(niveis).getByRole("table", { name: /Língua Portuguesa: Cidade Sintética — rede municipal por edição/ });
    expect(within(tabela).getAllByRole("rowheader").map((th) => th.textContent)).toHaveLength(11);   // 0–9 e a soma
    expect(linhaDa(tabela, "Nível 0 (abaixo de 125)")).toHaveTextContent(pct(DIST_LP5[0]));
    expect(linhaDa(tabela, "Nível 9 (325 ou mais)")).toHaveTextContent(pct(DIST_LP5[9]));
    expect(linhaDa(tabela, "Soma")).toHaveTextContent(pct(100));
    await u.selectOptions(within(niveis).getByLabelText("Componente"), "mt");
    expect(within(niveis).getAllByRole("img")[0].children).toHaveLength(11);
    const tMt = within(niveis).getByRole("table", { name: /Matemática: Cidade Sintética — rede municipal por edição/ });
    expect(linhaDa(tMt, "Nível 10 (350 ou mais)")).toHaveTextContent(pct(DIST_MT5[10]));
    const cortes = screen.getByTestId("ideb-saeb-cortes");
    expect(cortes).toHaveTextContent("Fonte dos cortes: INEP — Dicionário da planilha de resultados do Saeb 2025");
    expect(cortes).toHaveTextContent("As planilhas de 2019 e 2021 trazem os mesmos níveis só pelo número");
    const tc = within(cortes).getByRole("table", { name: /Cortes dos níveis do Saeb do 5º ano/ });
    expect(linhaDa(tc, "1")).toHaveTextContent("125 a menos de 150");
    expect(linhaDa(tc, "10")).toHaveTextContent("a escala de LP vai até o nível 9");
  });

  it("nível sem número: 'não divulgado' e sem soma — nunca 0", async () => {
    const u = userEvent.setup();
    const dados = comRede();
    const e25 = dados.rede_municipal.saeb.territorios[0].edicoes[1];
    e25.niveis.lp = dist([18.2, 21.5, 17.3, null, 10.4, 7.6, 5.1, 3.4, 1.8, 0.8], FONTE_SAEB);
    await montar(dados);
    await u.click(screen.getByText("Ver os números do gráfico (Língua Portuguesa)"));
    const tabela = screen.getByRole("table", { name: /Língua Portuguesa: Cidade Sintética — rede municipal por edição/ });
    const n3 = linhaDa(tabela, "Nível 3 (175 a menos de 200)");
    expect(n3).toHaveTextContent("não divulgado");
    expect(n3.textContent).not.toMatch(/(^|\s)0(,00)?%/);
    expect(linhaDa(tabela, "Soma").textContent).toContain("—");
  });

  it("contexto amostral do 2º ano: só estado e Brasil, rotulado 'amostral' e 'não é o ICA'", async () => {
    await montar(comRede());
    const bloco = screen.getByTestId("ideb-amostral");
    expect(within(bloco).getByRole("heading", { name: "Contexto amostral — Saeb do 2º ano (2021)" })).toBeInTheDocument();
    expect(bloco).toHaveTextContent("amostral, só contexto");
    expect(bloco).toHaveTextContent("não é o ICA");
    expect(screen.getByTestId("ideb-amostral-aviso")).toHaveTextContent("NÃO é o Indicador Criança Alfabetizada (ICA)");
    const t = within(bloco).getByRole("table", { name: /Saeb do 2º ano \(amostral\)/ });
    expect(within(t).getAllByRole("rowheader").map((th) => th.textContent)).toEqual([
      "São Paulo (redes municipais), 2021", "Brasil (redes municipais), 2021"]);
    expect(linhaDa(t, "São Paulo (redes municipais), 2021")).toHaveTextContent(pct(11.2));
    expect(t).toHaveAccessibleName(/amostral/);
    expect(bloco.textContent).not.toMatch(/Cidade Sintética/);                  // nunca a rede
  });

  it("nada da rede importado: abre por escola e a parte da rede diz o que falta (estado e Brasil inclusive)", async () => {
    const u = userEvent.setup();
    await montar(resposta());
    expect(screen.getByRole("tab", { name: "Por escola" })).toHaveAttribute("aria-selected", "true");
    await u.click(screen.getByRole("tab", { name: "Rede municipal" }));
    expect(screen.getByTestId("ideb-rede-sem-dado")).toHaveTextContent("Sem o Ideb da rede municipal importado");
    expect(screen.getByTestId("ideb-saeb-rede-sem-dado")).toHaveTextContent(
      "Sem a planilha de resultados do Saeb importada (médias e níveis da rede, do estado e do Brasil).");
    expect(screen.queryByTestId("ideb-amostral")).toBeNull();
  });

  it("só o Brasil e a UF (de outra rede), sem a rede importada: abre por escola; a rede não nega o estado e o Brasil", async () => {
    const u = userEvent.setup();
    await montar(soReferencia());
    // A UF e o Brasil não são número da rede: as escolas, que têm número, vêm primeiro.
    expect(screen.getByRole("tab", { name: "Por escola" })).toHaveAttribute("aria-selected", "true");
    const sem = within(screen.getByTestId("ideb-pendentes")).getByTestId("ideb-pendentes-sem-importacao");
    for (const ed of [2019, 2021, 2025]) expect(sem).toHaveTextContent(`Saeb ${ed} pela planilha do INEP`);
    await u.click(screen.getByRole("tab", { name: "Rede municipal" }));
    expect(screen.getByTestId("ideb-rede-sem-dado")).toHaveTextContent("Sem o Ideb da rede municipal importado");
    const saeb = screen.getByTestId("ideb-saeb-rede-sem-dado");
    expect(saeb).toHaveTextContent(
      "Sem a planilha de resultados do Saeb importada para esta rede (médias e níveis da rede municipal).");
    expect(saeb).not.toHaveTextContent(/estado|Brasil/);
    // O contexto amostral (estado e Brasil, rotulado) continua.
    expect(screen.getByTestId("ideb-amostral")).toBeInTheDocument();
  });

  it("só a referência e nenhuma escola com número: abre na rede (o contexto é o que há)", async () => {
    await montar(soReferencia({ escolas: [], edicoes: [], cobertura: [], tem_dados_escolas: false }));
    expect(screen.getByRole("tab", { name: "Rede municipal" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("ideb-rede-sem-dado")).toBeInTheDocument();
    expect(screen.getByTestId("ideb-amostral")).toBeInTheDocument();
  });

  it("planilha do Saeb importada para a rede sem o município: diz isso, não 'sem a planilha'", async () => {
    const dados = soReferencia();
    dados.rede_municipal.saeb.edicoes_importadas_rede = [2025];
    await montar(dados);
    await userEvent.setup().click(screen.getByRole("tab", { name: "Rede municipal" }));
    const saeb = screen.getByTestId("ideb-saeb-rede-sem-dado");
    expect(saeb).toHaveTextContent(
      "A planilha de resultados do Saeb importada para esta rede (2025) não traz número da rede municipal");
    expect(saeb).not.toHaveTextContent("Sem a planilha");
  });

  it("sem o arquivo de UF: nada de aviso sobre o que ele traz, nem coluna vazia da UF", async () => {
    await montar(semArquivoDeUf());
    expect(screen.queryByTestId("ideb-rede-contexto")).toBeNull();
    expect(screen.getByTestId("ideb-rede").textContent).not.toMatch(/não traz a rede municipal|não entra no gráfico/);
    expect(within(tabelaIdebRede()).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Edição", "Rede municipal", "Brasil (redes municipais)"]);
    expect(screen.getByTestId("ideb-rede-grafico").querySelector("figcaption")).toHaveTextContent(
      "Ideb da rede, meta (tracejada) e Brasil — redes municipais — a mesma rede");
  });

  it("sem o arquivo de UF nem o do Brasil: a legenda não cita o Brasil, que não está no gráfico", async () => {
    await montar(semArquivoDeUf(true));
    const g = screen.getByTestId("ideb-rede-grafico");
    expect(g.querySelector("figcaption")?.textContent).toBe("Ideb da rede e meta (tracejada)");
    expect(g.querySelector("svg")?.getAttribute("aria-label")).not.toMatch(/Brasil|mesma rede/);
    expect(trechos(g, "#DC2626")).toEqual([]);
    expect(within(tabelaIdebRede()).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Edição", "Rede municipal"]);
    expect(within(g).queryByText(/Brasil/)).toBeNull();
  });

  it("só a rede importada (sem escola): as partes por escola dizem isso, sem quebrar", async () => {
    const u = userEvent.setup();
    await montar(comRede({ escolas: [], edicoes: [], cobertura: [], tem_dados_escolas: false }));
    expect(screen.getByTestId("ideb-rede")).toBeInTheDocument();
    await u.click(screen.getByRole("tab", { name: "Por escola" }));
    expect(screen.getByTestId("ideb-sem-escolas")).toHaveTextContent("Nenhuma escola da rede com resultado importado");
    await u.click(screen.getByRole("tab", { name: "Cobertura" }));
    expect(screen.getByTestId("ideb-sem-escolas")).toBeInTheDocument();
  });

  it("2025 por escola: a edição mais nova aberta, sem meta (depois do 1º ciclo)", async () => {
    const dados = comRede();
    const alfa = dados.escolas.find((e) => e.nome === "EMEF Sintética Alfa");
    if (!alfa) throw new Error("fixture sem a Alfa");
    alfa.serie.push(ed(2025, [1.9, 128.26, 133.71, 2.497125, 0.664318, 27.1],
                       { variacao_ideb: { desde: 2023, diferenca: 0.2, casas_decimais: 1 } }));
    dados.edicoes = [2019, 2021, 2023, 2025];
    const u = userEvent.setup();
    await montar(dados);
    await u.click(screen.getByRole("tab", { name: "Por escola" }));
    expect(screen.getByLabelText("Edição")).toHaveDisplayValue("2025");
    const linha = linhaDa(tabelaEscolas(2025), "EMEF Sintética Alfa");
    expect(linha).toHaveTextContent("1,9");
    expect(linha).toHaveTextContent("+0,2 desde 2023");
    expect(screen.getByTestId("ideb-metas-edicao")).toHaveTextContent("o INEP não definiu meta do Ideb para 2025");
  });
});

describe("Aba IDEB e SAEB — sem dado, erro e celular", () => {
  it("sem dado: 'sem resultado importado' — nunca 0", async () => {
    await montar(resposta({ escolas: [], edicoes: [], cobertura: [], fontes: [], tem_dados: false }), true);
    const vazio = screen.getByTestId("ideb-sem-dado");
    expect(vazio).toHaveTextContent("Sem resultado do Ideb e do Saeb importado para a rede.");
    expect(vazio).toHaveTextContent("preparar");                    // admin global: como importar
    expect(screen.queryByTestId("aba-ideb")).toBeNull();
    expect(screen.getByTestId("cartao-ideb").textContent).not.toMatch(/(^|\s)0(,0)?(\s|$)/);
  });

  it("rede sem código IBGE: a pendência aparece; erro da API fica visível", async () => {
    await montar(resposta({ pendencias: ["codigo_ibge"], tem_dados: false, escolas: [], edicoes: [] }));
    expect(screen.getByTestId("ideb-pendencias")).toHaveTextContent("não tem o código IBGE");
    expect(screen.getByTestId("ideb-pendencias")).toHaveTextContent("administrador global");
  });

  it("erro 403 da API: a mensagem aparece (nada de tela vazia)", async () => {
    responderErro("GET", "/redes/1/indicadores/ideb", 403, "Acesso negado: você não pertence a esta rede.");
    renderComApp(<CartaoIDEB redeId={1} ehGlobal={false} />, { usuario: secretaria });
    expect(await screen.findByText(/Não foi possível carregar o Ideb e o Saeb: Acesso negado/)).toBeInTheDocument();
  });

  it("tabelas de largura fixa e nada de largura mínima (sem rolagem lateral no celular)", async () => {
    const u = userEvent.setup();
    const { container } = await montar(comRede());
    const conferir = () => {
      expect(container.querySelector('[class*="min-w-["]')).toBeNull();
      expect(container.querySelector("[data-testid='aba-ideb'] .overflow-x-auto")).toBeNull();
      for (const t of Array.from(container.querySelectorAll("[data-testid='aba-ideb'] table"))) {
        expect(t.className).toContain("table-fixed");
      }
    };
    conferir();                                                    // a parte "Rede municipal"
    await u.click(screen.getByRole("tab", { name: "Por escola" }));
    conferir();
    await u.click(screen.getByRole("tab", { name: "Série de uma escola" }));
    conferir();
    await u.click(screen.getByRole("tab", { name: "Cobertura" }));
    conferir();
  });
});
