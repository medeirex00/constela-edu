/**
 * Exportação em CSV da lista que uma tela de ranking está MOSTRANDO (identidade
 * visual v2, botão "Exportar lista (CSV)").
 *
 * Gerado no navegador, com os itens que a tela já carregou (mesma ordem, mesmos
 * filtros): nenhuma consulta nova e nenhum número calculado aqui — cada célula é
 * o valor que a tabela exibe (ou o número cru que ela formata).
 *
 * Formato pensado para o Excel em português: separador ";" (a vírgula é o
 * separador decimal), BOM UTF-8 (acentos corretos ao abrir com dois cliques) e
 * quebra de linha CRLF. Texto que começa com = + - @ ganha um apóstrofo na frente
 * (proteção contra "injeção de fórmula" ao abrir a planilha); número não.
 */

/** Uma célula: texto (exibido como veio), número (formatado em pt-BR) ou vazio. */
export type CelulaCsv = string | number | null | undefined;

export interface TabelaCsv {
  /** Nome do arquivo baixado (sem caminho), ex.: "ranking-leitura_2026-10-31.csv". */
  nomeArquivo: string;
  cabecalho: string[];
  linhas: CelulaCsv[][];
}

function celula(valor: CelulaCsv): string {
  if (valor == null) return "";
  let texto = typeof valor === "number"
    ? (Number.isFinite(valor) ? valor.toLocaleString("pt-BR", { maximumFractionDigits: 2 }) : "")
    : String(valor);
  if (typeof valor === "string" && /^[=+\-@\t\r]/.test(texto)) texto = `'${texto}`;
  return /[;"\r\n]/.test(texto) ? `"${texto.replace(/"/g, '""')}"` : texto;
}

/** O conteúdo do arquivo (exportado para teste). */
export function conteudoCsv(tabela: Pick<TabelaCsv, "cabecalho" | "linhas">): string {
  const linhas = [tabela.cabecalho, ...tabela.linhas].map((l) => l.map(celula).join(";"));
  return `﻿${linhas.join("\r\n")}\r\n`;
}

/** Baixa a tabela como arquivo .csv (link temporário com `download`). */
export function baixarCsv(tabela: TabelaCsv): void {
  const blob = new Blob([conteudoCsv(tabela)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = tabela.nomeArquivo;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoga no próximo ciclo: alguns navegadores ainda leem o blob logo após o clique.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** "ranking-leitura" + hoje → "ranking-leitura_2026-10-31.csv" (data local, sem fuso). */
export function nomeArquivoCsv(base: string, hoje: Date = new Date()): string {
  const dois = (n: number) => String(n).padStart(2, "0");
  const data = `${hoje.getFullYear()}-${dois(hoje.getMonth() + 1)}-${dois(hoje.getDate())}`;
  const limpo = base
    .normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${limpo || "ranking"}_${data}.csv`;
}
