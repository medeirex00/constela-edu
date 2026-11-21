/** O que a ficha do aluno no app mostra em cada nota.
 *
 *  O MESMO critério da web (`apps/web/src/pages/PerfilAluno.tsx`): o `aferido` de
 *  `perfil.dimensoes` separa "sem dado" ("—") do zero legítimo ("0,0"). As notas
 *  de plataforma chegam 0,0 para quem não tem retrato, e o motor grava o passo a
 *  passo com nota 0 — sem este corte, o app afirmava "Matific 0,0" para a criança
 *  que nunca abriu o Matific. Sem `dimensoes` (servidor antigo), mostra o número
 *  que veio (`notaDaMateria`), sem inventar ausência.
 *
 *  Lógica pura, fora da tela, para o teste rodar sem o React Native. */
import { nota, notaDaMateria, type PerfilAluno } from "@constela/core";

type PerfilDasNotas = Pick<PerfilAluno, "nota_matific" | "nota_elefante" | "nota_geral" | "dimensoes">;

export interface NotasDoPerfil {
  matific: string;
  leitura: string;
  geral: string;
  /** Mostrar o passo a passo da plataforma? `false` = sem dado dela: a tabela
   *  afirmaria um zero que não foi medido. */
  calculoMatific: boolean;
  calculoLeitura: boolean;
  /** Sem dado em NENHUMA dimensão contratada: a Nota Geral também é "—". */
  semDadoNenhum: boolean;
}

export function notasDoPerfil(perfil: PerfilDasNotas): NotasDoPerfil {
  const aferido = (dimensao: string) =>
    perfil.dimensoes?.find((d) => d.dimensao === dimensao)?.aferido;
  const semDadoNenhum = Boolean(perfil.dimensoes?.length)
    && (perfil.dimensoes ?? []).every((d) => !d.aferido);
  return {
    matific: notaDaMateria(perfil.nota_matific, aferido("matematica")),
    leitura: notaDaMateria(perfil.nota_elefante, aferido("leitura")),
    geral: semDadoNenhum ? "—" : nota(perfil.nota_geral),
    calculoMatific: aferido("matematica") !== false,
    calculoLeitura: aferido("leitura") !== false,
    semDadoNenhum,
  };
}
