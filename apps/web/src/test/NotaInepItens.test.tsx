/**
 * Observação do INEP sobre a tabela de itens dos microdados de 2025 na aba ICA
 * (decisão D-B, opção A):
 *
 *  - aparece num bloco próprio, logo abaixo da comparação, só quando a comparação
 *    é a de 2025 e inclui São Paulo ou Rio Grande do Sul — olhando a UF da rede
 *    pública e a das redes municipais;
 *  - é informativa (não fala em erro, "inválido" nem "não comparável");
 *  - não mexe nos números nem na ordem da comparação;
 *  - não entra na lista das notas "como publicadas" dos arquivos;
 *  - o texto é o aprovado, palavra por palavra, e o link vai para a página do
 *    INEP (nunca para o pacote dos microdados).
 *
 * Números, códigos de município, arquivos e datas INVENTADOS (licença CC BY-ND,
 * repositório público): nada dos arquivos do INEP; nenhum dado de aluno.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import AbaICA from "../pages/rede/AbaICA";
import CartaoICA, { type FonteICA, type RespostaICA } from "../pages/rede/CartaoICA";
import { NOTA_INEP_ITENS, notaInepItensSeAplica } from "../pages/rede/notaInepItens";
import { act, renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

/** O texto aprovado pelo dono, copiado aqui de propósito: se a constante mudar, o teste falha. */
const TEXTO_APROVADO =
  "Sobre uma observação do INEP nos microdados. Na documentação dos microdados das avaliações estaduais de 2025 "
  + "(Leia-me, abril de 2026, p. 22), o INEP informa que retirou da tabela de itens de prova os itens de São Paulo "
  + "e do Rio Grande do Sul, porque os parâmetros desses itens aparentemente não estavam na escala do Saeb. A "
  + "observação trata da tabela de itens; segundo o mesmo documento, a tabela de resultados dos estados não precisou "
  + "de ajuste. Os percentuais do ICA mostrados aqui são os publicados pelo INEP. Uma observação igual, para Bahia, "
  + "São Paulo e Rio Grande do Sul, já constava no Leia-me de 2024. Fonte: INEP, Microdados AEEB 2025 – Leia-me.";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const MUN = "Município Sintético";

function fonte(over: Partial<FonteICA> = {}): FonteICA {
  return {
    importacao_id: 31, fonte_nome: "INEP — Indicador Criança Alfabetizada",
    arquivo_nome: "planilha_municipios_sintetica.xlsx", arquivo_data: "2026-05-04T10:00:00",
    last_modified_origem: null, url_origem: null, edicao_arquivo: 2025, versao_rotulo: null,
    importado_em: "2026-10-12T12:00:00", coletado_em: null, citacao: null,
    licenca: "Dado público do Inep (citar a fonte).", parser: "inep_ica_municipios", modo: "upload",
    notas: [], ...over,
  };
}
const FMUN = fonte();
const FUF = fonte({ importacao_id: 32, arquivo_nome: "planilha_ufs_sintetica.xlsx", parser: "inep_ica_ufs",
  notas: ["* Nota sintética de rodapé da planilha de UFs."] });
const FMICRO = fonte({ importacao_id: 33, fonte_nome: "INEP — Microdados da avaliação da alfabetização",
  arquivo_nome: "pacote_sintetico.zip", arquivo_data: "2026-02-09T10:00:00", parser: "inep_aeeb_agregados",
  modo: "pacote_cli" });

type Numero = RespostaICA["territorios"][number]["resultados"][number];
type Territorio = RespostaICA["territorios"][number];

function num(edicao: number, valor: number, f: FonteICA, casas = 0): Numero {
  return { edicao, valor, casas_decimais: casas, operador: null, unidade: "percentual", motivo_ausencia: null,
           fonte: f, detalhe: null, nivel: null };
}

function territorio(abrangencia: Territorio["abrangencia"], codigo: string, nome: string, rede: string,
                    resultados: Numero[]): Territorio {
  const ultimo = [...resultados].reverse().find((r) => r.valor != null);
  return {
    abrangencia, codigo_territorio: codigo, nome, rede_ensino: rede, resultados, metas: [], nivel: [],
    participacao: [], media_lp: [], distribuicao_niveis: [], comparacoes: [],
    destaque: ultimo ? { resultado: ultimo, meta: null, comparacao: null } : null,
    tem_dados: resultados.length > 0,
  };
}

interface Opcoes {
  /** Código IBGE (2 dígitos) da UF; o município herda os 2 primeiros. */
  uf?: string;
  nomeUf?: string;
  /** Anos com resultado (o último é o da comparação). */
  anos?: number[];
  /** Sem a UF da rede pública em `territorios` (só a das redes municipais). */
  semUfPublica?: boolean;
  semNotasDosArquivos?: boolean;
}

// Valores sintéticos por ano — nunca os oficiais.
const MUNV: Record<number, number> = { 2023: 19, 2024: 24, 2025: 28 };
const UFV: Record<number, number> = { 2023: 21, 2024: 29, 2025: 33 };
const UFMV: Record<number, number> = { 2024: 27.41, 2025: 29.86 };
const BRV: Record<number, number> = { 2023: 25, 2024: 22, 2025: 31 };

function resposta({ uf = "35", nomeUf = "São Paulo", anos = [2023, 2024, 2025], semUfPublica = false,
                    semNotasDosArquivos = false }: Opcoes = {}): RespostaICA {
  const codMun = `${uf}99999`;
  const mun = territorio("municipio", codMun, MUN, "municipal", anos.map((a) => num(a, MUNV[a], FMUN)));
  const ufp = territorio("uf", uf, nomeUf, "publica", anos.map((a) => num(a, UFV[a], FUF)));
  const ufm = territorio("uf", uf, nomeUf, "municipal",
    anos.filter((a) => a in UFMV).map((a) => num(a, UFMV[a], FMICRO, 2)));
  const br = territorio("brasil", "BR", "Brasil", "publica", anos.map((a) => num(a, BRV[a], FUF)));
  const fUf = semNotasDosArquivos ? { ...FUF, notas: [] } : FUF;
  return {
    rede_id: 1, rede_nome: "Rede Sintética", codigo_ibge: codMun,
    indicador: { chave: "ica", nome: "Indicador Criança Alfabetizada (ICA)", orgao: "INEP", descricao: "" },
    aviso_rede: "O ICA é o indicador da REDE municipal: o INEP não publica o ICA por escola.",
    pendencia: null, corte_alfabetizado: 743, legenda_nivel: [],
    territorios: semUfPublica ? [mun, br] : [mun, ufp, br],
    uf_municipal: ufm,
    fontes: [fUf, FMUN, FMICRO], tem_dados: true,
  };
}

/** A aba direto, com o contexto do app assentado (sem aviso de act). */
async function montar(dados: RespostaICA) {
  const r = renderComApp(<AbaICA dados={dados} />, { usuario: secretaria });
  await act(async () => {});
  return r;
}

function nota(): HTMLElement {
  return screen.getByTestId("ica-nota-inep-itens");
}

function itensDaComparacao(ano = 2025): string[] {
  const lista = screen.getByRole("list", { name: new RegExp(`ICA em ${ano}, na ordem fixa`) });
  return within(lista).getAllByRole("listitem").map((li) => li.textContent?.split("%")[0] ?? "");
}

afterEach(() => vi.restoreAllMocks());

describe("Aba ICA — observação do INEP sobre a tabela de itens (2025)", () => {
  it("aparece com SP em 2025, logo abaixo da comparação, cita a tabela de itens, SP, RS e o Leia-me, com link para gov.br/inep", async () => {
    responder("GET", "/redes/1/indicadores/ica", resposta());
    const usuario = userEvent.setup();
    renderComApp(<CartaoICA redeId={1} ehGlobal={false} />, { usuario: secretaria });
    await usuario.click(await screen.findByRole("tab", { name: "Série, níveis e média de LP" }));

    const bloco = nota();
    expect(bloco).toHaveTextContent("tabela de itens");
    expect(bloco).toHaveTextContent("São Paulo");
    expect(bloco).toHaveTextContent("Rio Grande do Sul");
    expect(bloco).toHaveTextContent("Leia-me");
    // título em destaque, separado do parágrafo
    expect(within(bloco).getByTestId("ica-nota-inep-itens-titulo")).toHaveClass("font-semibold");
    expect(within(bloco).getByTestId("ica-nota-inep-itens-titulo"))
      .toHaveTextContent("Sobre uma observação do INEP nos microdados.");

    // bloco próprio, logo abaixo da comparação de 2025
    const comparacao = screen.getByRole("region", { name: "Comparação em 2025" });
    expect(comparacao.nextElementSibling).toBe(bloco);
    expect(comparacao).not.toContainElement(bloco);

    // o link vai para a página do INEP — nunca para o pacote dos microdados
    const link = within(bloco).getByRole("link", { name: /gov\.br\/inep/ });
    expect(link).toHaveAttribute("href", "https://www.gov.br/inep");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.getAttribute("href")).not.toMatch(/zip|microdados|download/i);
    expect(within(bloco).getAllByRole("link")).toHaveLength(1);

    // RS chegando só pela UF das redes municipais (sem a UF da rede pública): também aparece
    await montar(resposta({ uf: "43", nomeUf: "Rio Grande do Sul", semUfPublica: true }));
    expect(screen.getAllByTestId("ica-nota-inep-itens")).toHaveLength(2);
  });

  it("é informativa: não fala em 'não comparável', 'inválido' nem 'erro'", async () => {
    await montar(resposta());
    const texto = nota().textContent ?? "";
    expect(texto.length).toBeGreaterThan(0);
    expect(texto).not.toMatch(/não comparáve/i);
    expect(texto).not.toMatch(/inválid/i);
    expect(texto).not.toMatch(/\berros?\b/i);
    expect(nota()).not.toHaveAttribute("role", "alert");
  });

  it("some com outro estado e quando só há 2023 (ou o último ano não é 2025)", async () => {
    const { unmount } = await montar(resposta({ uf: "31", nomeUf: "Estado Sintético" }));
    expect(screen.getByRole("region", { name: "Comparação em 2025" })).toBeInTheDocument();
    expect(screen.queryByTestId("ica-nota-inep-itens")).not.toBeInTheDocument();
    unmount();

    const so2023 = await montar(resposta({ anos: [2023] }));
    expect(screen.getByRole("region", { name: "Comparação em 2023" })).toBeInTheDocument();
    expect(screen.queryByTestId("ica-nota-inep-itens")).not.toBeInTheDocument();
    so2023.unmount();

    await montar(resposta({ anos: [2023, 2024] }));
    expect(screen.getByRole("region", { name: "Comparação em 2024" })).toBeInTheDocument();
    expect(screen.queryByTestId("ica-nota-inep-itens")).not.toBeInTheDocument();

    // a regra, direto: só 2025, só UF 35/43, olhando cada território da comparação
    const sp = { abrangencia: "uf", codigo_territorio: "35" };
    const rs = { abrangencia: "uf", codigo_territorio: "43" };
    const outra = { abrangencia: "uf", codigo_territorio: "31" };
    const munSp = { abrangencia: "municipio", codigo_territorio: "3599999" };
    expect(notaInepItensSeAplica(2025, [munSp, outra, rs])).toBe(true);
    expect(notaInepItensSeAplica(2025, [sp])).toBe(true);
    expect(notaInepItensSeAplica(2025, [munSp, outra])).toBe(false);
    expect(notaInepItensSeAplica(2023, [sp, rs])).toBe(false);
    expect(notaInepItensSeAplica(undefined, [sp])).toBe(false);
  });

  it("com SP ainda sem resultado importado: a observação aparece separada e não sugere resultado de SP", async () => {
    // Decisão do dono (18/10): a observação pode aparecer sem resultado de SP, desde que
    // fique separada dos resultados oficiais e não dê a entender que existe um resultado.
    const dados = resposta();
    const semSp: RespostaICA = {
      ...dados,
      territorios: dados.territorios.map((t) => (t.abrangencia === "uf"
        ? { ...t, resultados: [], destaque: null, tem_dados: false } : t)),
      uf_municipal: { ...dados.uf_municipal, resultados: [], destaque: null, tem_dados: false },
    };
    await montar(semSp);

    // a linha de SP na comparação diz que não há resultado — sem barra e sem percentual
    const lista = screen.getByRole("list", { name: /ICA em 2025, na ordem fixa/ });
    const linhasSp = within(lista).getAllByRole("listitem").filter((li) => li.textContent?.includes("São Paulo"));
    expect(linhasSp).toHaveLength(1);
    expect(linhasSp[0]).toHaveTextContent("sem resultado importado");
    expect(linhasSp[0].textContent).not.toContain("%");

    // a observação é um bloco à parte (fora da comparação e da lista de resultados)
    const bloco = nota();
    expect(bloco.tagName).toBe("ASIDE");
    expect(screen.getByRole("region", { name: "Comparação em 2025" })).not.toContainElement(bloco);
    expect(lista).not.toContainElement(bloco);
    // e não traz nenhum número de resultado (nem percentual), só a referência ao documento
    expect(bloco.textContent).not.toContain("%");
    expect(bloco.textContent).not.toMatch(/\d+,\d+/);
    expect(bloco).not.toHaveAttribute("role", "alert");
  });

  it("os números e a ordem fixa da comparação ficam intactos", async () => {
    const esperado = [`${MUN} (rede municipal)28`, "São Paulo (rede pública)33", "São Paulo (redes municipais)29,86",
                      "Brasil (rede pública)31"];
    const comNota = await montar(resposta());
    expect(screen.getByTestId("ica-nota-inep-itens")).toBeInTheDocument();
    expect(itensDaComparacao()).toEqual(esperado);
    const lista = screen.getByRole("list", { name: /ICA em 2025, na ordem fixa/ });
    expect(lista).not.toContainElement(nota());
    comNota.unmount();

    // os mesmos dados com outro código de UF (sem a observação): a comparação é idêntica
    await montar(resposta({ uf: "31" }));
    expect(screen.queryByTestId("ica-nota-inep-itens")).not.toBeInTheDocument();
    expect(itensDaComparacao()).toEqual(esperado);
  });

  it("não entra na lista de notas dos arquivos oficiais (como publicadas)", async () => {
    const { unmount } = await montar(resposta());
    const notas = screen.getByTestId("ica-notas");
    const regiaoNotas = screen.getByRole("region", { name: "Notas dos arquivos oficiais (como publicadas)" });
    expect(notas).toHaveTextContent("* Nota sintética de rodapé da planilha de UFs. (planilha_ufs_sintetica.xlsx)");
    expect(within(notas).getAllByRole("listitem")).toHaveLength(1);
    expect(regiaoNotas).not.toContainElement(nota());
    expect(regiaoNotas.textContent).not.toContain("tabela de itens");
    expect(regiaoNotas.textContent).not.toContain("Leia-me");
    unmount();

    // sem nota nos arquivos: a lista some, a observação continua (não depende dela)
    await montar(resposta({ semNotasDosArquivos: true }));
    expect(screen.queryByTestId("ica-notas")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Notas dos arquivos oficiais (como publicadas)" }))
      .not.toBeInTheDocument();
    expect(nota()).toBeInTheDocument();
  });

  it("texto travado: igual ao aprovado, palavra por palavra, com ano, UFs, página e link da constante", async () => {
    expect(`${NOTA_INEP_ITENS.titulo} ${NOTA_INEP_ITENS.texto}`).toBe(TEXTO_APROVADO);
    expect(NOTA_INEP_ITENS.titulo).toBe("Sobre uma observação do INEP nos microdados.");
    expect(NOTA_INEP_ITENS.ano).toBe(2025);
    expect([...NOTA_INEP_ITENS.ufs]).toEqual(["35", "43"]);
    expect(NOTA_INEP_ITENS.pagina).toBe(22);
    expect(NOTA_INEP_ITENS.texto).toContain(`p. ${NOTA_INEP_ITENS.pagina})`);
    expect(NOTA_INEP_ITENS.texto).toContain(`avaliações estaduais de ${NOTA_INEP_ITENS.ano}`);
    expect(NOTA_INEP_ITENS.link.href).toBe("https://www.gov.br/inep");
    expect(NOTA_INEP_ITENS.versao).toBe(1);

    // na tela, o título e o parágrafo saem exatamente da constante
    await montar(resposta());
    expect(screen.getByTestId("ica-nota-inep-itens-titulo").textContent?.trim()).toBe(NOTA_INEP_ITENS.titulo);
    expect(screen.getByTestId("ica-nota-inep-itens-texto").textContent).toBe(NOTA_INEP_ITENS.texto);
  });
});
