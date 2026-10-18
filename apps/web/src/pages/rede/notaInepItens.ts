/**
 * Observação do INEP sobre a tabela de itens dos microdados de 2025 — decisão D-B
 * (opção A), aprovada pelo dono (o registro da aprovação fica no plano, fora do
 * repositório).
 *
 * O título e o texto são os APROVADOS, palavra por palavra: não edite sem nova
 * aprovação (o teste `NotaInepItens.test.tsx` trava o texto). Se um dia o texto
 * mudar com aprovação, suba a `versao`.
 *
 * Não é uma nota "como publicada" de um arquivo oficial: é o resumo aprovado de um
 * trecho do Leia-me. Por isso aparece num bloco próprio da aba ICA, logo abaixo da
 * comparação, e NUNCA na lista "Notas dos arquivos oficiais (como publicadas)".
 *
 * O link vai para a página do INEP — nunca para o pacote (.zip) dos microdados,
 * que contém dado de aluno.
 */

export const NOTA_INEP_ITENS = {
  versao: 1,
  decisao: "D-B (opção A)",
  /** Edição da avaliação a que a observação se refere. */
  ano: 2025,
  /** Códigos IBGE das UFs citadas: 35 = São Paulo, 43 = Rio Grande do Sul. */
  ufs: ["35", "43"],
  /** Página do Leia-me dos microdados de 2025 (abril de 2026) onde está a observação. */
  pagina: 22,
  titulo: "Sobre uma observação do INEP nos microdados.",
  texto:
    "Na documentação dos microdados das avaliações estaduais de 2025 (Leia-me, abril de 2026, p. 22), o INEP "
    + "informa que retirou da tabela de itens de prova os itens de São Paulo e do Rio Grande do Sul, porque os "
    + "parâmetros desses itens aparentemente não estavam na escala do Saeb. A observação trata da tabela de itens; "
    + "segundo o mesmo documento, a tabela de resultados dos estados não precisou de ajuste. Os percentuais do ICA "
    + "mostrados aqui são os publicados pelo INEP. Uma observação igual, para Bahia, São Paulo e Rio Grande do Sul, "
    + "já constava no Leia-me de 2024. Fonte: INEP, Microdados AEEB 2025 – Leia-me.",
  link: { href: "https://www.gov.br/inep", rotulo: "Página do INEP (gov.br/inep)" },
} as const;

/** O mínimo de um território que a regra precisa (vale para `TerritorioICA`). */
interface TerritorioComCodigo {
  abrangencia: string;
  codigo_territorio: string;
}

/**
 * A observação aparece só quando a comparação mostrada é a de 2025 e inclui São
 * Paulo ou Rio Grande do Sul. A UF chega como `codigo_territorio` de 2 dígitos (o
 * backend usa os 2 primeiros do código IBGE do município) em DOIS lugares: na UF da
 * rede pública (`territorios`) e na UF só das redes municipais (`uf_municipal`) —
 * por isso a regra recebe todos os territórios da comparação e olha cada UF.
 */
export function notaInepItensSeAplica(
  anoComparacao: number | null | undefined,
  territorios: readonly TerritorioComCodigo[],
): boolean {
  if (anoComparacao !== NOTA_INEP_ITENS.ano) return false;
  const ufs: readonly string[] = NOTA_INEP_ITENS.ufs;
  return territorios.some((t) => t.abrangencia === "uf" && ufs.includes(String(t.codigo_territorio)));
}
