import type { Avatar } from "@constela/quest-core";

/** Extrai os slots do avatar humanoide para passar ao <Boneco />. */
export function propsBoneco(a: Avatar | undefined) {
  return {
    pele: a?.pele, cabelo: a?.cabelo, camiseta: a?.camiseta,
    calca: a?.calca, tenis: a?.tenis, chapeu: a?.chapeu,
    costas: a?.costas, mao: a?.mao, pet: a?.pet,
  };
}
