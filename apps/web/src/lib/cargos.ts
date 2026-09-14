/**
 * Cargos (perfis) de usuário de ESCOLA — espelho de `CARGOS` no backend
 * (routers/admin.py). Fonte única para as telas que criam/exibem usuários; o
 * backend continua validando e recusando qualquer outro valor (400).
 */
export const CARGOS = [
  { valor: "admin", rotulo: "Administrador", descricao: "Acesso total: usuários, configurações, importações e exclusões." },
  { valor: "coordenador", rotulo: "Coordenador", descricao: "Acesso a tudo da escola, exceto usuários e configurações de sistema." },
  { valor: "professor", rotulo: "Professor", descricao: "Vê apenas as turmas designadas a ele, com dados resumidos." },
] as const;

export type Cargo = (typeof CARGOS)[number]["valor"];

export function rotuloCargo(valor: string): string {
  return CARGOS.find((c) => c.valor === valor)?.rotulo ?? valor;
}
