/**
 * Filtro do campo do nome que a criança escolhe (cerimônia e vestiário): só letras
 * e espaço — e, entre as letras, nenhuma que não desenhe nada. Os preenchimentos do
 * Hangul (o U+3164 é o "nome invisível" que circula em jogos) e os brancos dos
 * hieróglifos são "letra" para o \p{L}, mas deixariam o nome em branco nas falas e
 * no "É você?". O servidor recusa os mesmos (perfis.LETRAS_INVISIVEIS).
 */
const FORA_DO_NOME = /[^\p{L} ]/gu;
const LETRAS_INVISIVEIS = /[\u115F\u1160\u3164\uFFA0\u{13441}\u{13442}]/gu;

export function soLetrasDoNome(texto: string): string {
  return texto.replace(FORA_DO_NOME, "").replace(LETRAS_INVISIVEIS, "");
}
