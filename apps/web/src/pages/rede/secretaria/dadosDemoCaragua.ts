import { decimal } from "../../analise/formato";
import { numero } from "../../../lib/formato";

export type RegiaoId = "norte" | "centro" | "sul" | "serra";

export interface EscolaDemo {
  id: string;
  nome: string;
  regiao: RegiaoId;
  latitude: number;
  longitude: number;
  nota: number | null;
  com_dados: number;
  matriculados: number;
}

export interface RegiaoDemo {
  id: RegiaoId;
  nome: string;
  contexto: string;
}

export interface AvaliacaoDemo {
  escola_id: string;
  avaliacao: "SARESP" | "SAEB";
  edicao: number;
  serie: string;
  disciplina: string;
  resultado: number | null;
}

export interface DadosDemoCaragua {
  escolas: EscolaDemo[];
  regioes: RegiaoDemo[];
  avaliacoes: AvaliacaoDemo[];
}

export const FAIXAS = [
  { cor: "#e93242", rotulo: "Atenção", criterio: "< 50" },
  { cor: "#ffc634", rotulo: "Acompanhar", criterio: "50 a < 70" },
  { cor: "#24b865", rotulo: "Bom desempenho", criterio: "≥ 70" },
  { cor: "#8e9bab", rotulo: "Dados insuficientes", criterio: null },
];

export function faixaDemo(nota: number | null) {
  if (nota === null) return FAIXAS[3];
  if (nota < 50) return FAIXAS[0];
  return nota < 70 ? FAIXAS[1] : FAIXAS[2];
}

export function totalizarDemo(escolas: EscolaDemo[]) {
  let soma = 0;
  let comNota = 0;
  let comDados = 0;
  let matriculados = 0;
  for (const escola of escolas) {
    if (escola.nota !== null) {
      soma += escola.nota;
      comNota += 1;
    }
    comDados += escola.com_dados;
    matriculados += escola.matriculados;
  }
  return { nota: comNota > 0 ? soma / comNota : null, comDados, matriculados };
}

export const resultadoDemo = (valor: number | null) => valor === null ? "Sem dados" : decimal(valor, 2);
export const notaDemo = (valor: number | null) => valor === null ? "Sem dados" : decimal(valor, 1);

export function participacaoDemo(comDados: number, matriculados: number): string {
  if (!matriculados) return "Sem dados";
  return decimal(100 * comDados / matriculados, 1) + "%";
}

export function coberturaDemo(comDados: number, matriculados: number): string {
  return numero(comDados) + " de " + numero(matriculados) + " alunos com dados";
}
