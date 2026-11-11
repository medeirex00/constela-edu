/**
 * Calendário oficial dos bimestres (lido do backend) e elegibilidade às premiações
 * (espelho do backend).
 *
 * Saiu de pages/Relatorios.tsx (que continua re-exportando `bimestreDeHoje` e
 * `participaDePremiacao`) para que o menu, o Ranking, as Premiações e a Visão Geral usem
 * as MESMAS funções sem carregar a página de Relatórios. O calendário vem do backend
 * (`useCalendarioBimestres`); as funções recebem a resposta dele.
 */
import { useApi } from "../hooks/useApi";

/** Um bimestre do calendário oficial: número e início/fim INCLUSIVOS (AAAA-MM-DD). */
export interface BimestreOficial {
  numero: number;
  inicio: string;
  fim: string;
}

/** Resposta de GET /escolas/{id}/configuracoes/calendario-bimestres?ano=AAAA — a MESMA
 *  fonte que o backend usa (`backend/app/services/bimestres.py`: a constante de 2026 e a
 *  variável BIMESTRES_CALENDARIO para os anos novos). `bimestres: null` = o ano não tem
 *  calendário cadastrado. */
export interface CalendarioDoAno {
  ano: number;
  bimestres: BimestreOficial[] | null;
}

/** Cópia do calendário de 2026 do backend (`PERIODOS` de services/bimestres.py) só para a
 *  PRIMEIRA pintura, antes de a rota responder; a resposta do servidor é quem manda.
 *  Início e fim de cada bimestre, inclusivos: 02/02–22/04, 23/04–23/07, 24/07–04/10,
 *  05/10–31/12.
 *
 *  Antes esta cópia era a ÚNICA fonte da web e só tinha 2026: de 2027 em diante o
 *  certificado abria no "1º bimestre" dizendo "pelo calendário oficial" e MANDAVA esse
 *  número ao backend, mesmo com o calendário do ano cadastrado lá. Ano que nem o servidor
 *  nem esta cópia conhecem não tem bimestre "de hoje" (`null`): a tela pede a escolha.
 *
 *  Não é o mês do relógio: em 01/10 o 3º bimestre ainda não acabou, e era exatamente aí
 *  que o mapa por mês fazia o seletor abrir em "4º". */
const EMBUTIDO_2026: CalendarioDoAno = {
  ano: 2026,
  bimestres: [
    { numero: 1, inicio: "2026-02-02", fim: "2026-04-22" },
    { numero: 2, inicio: "2026-04-23", fim: "2026-07-23" },
    { numero: 3, inicio: "2026-07-24", fim: "2026-10-04" },
    { numero: 4, inicio: "2026-10-05", fim: "2026-12-31" },
  ],
};

const DIA_MS = 24 * 60 * 60 * 1000;

function diaUTC(d: Date): number {
  return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
}

function isoUTC(iso: string): number {
  const [ano, mes, dia] = iso.split("-").map(Number);
  return Date.UTC(ano, mes - 1, dia);
}

/** Os bimestres do ano, em ordem, com as datas em milissegundos UTC — do servidor quando
 *  ele já respondeu por ESTE ano, senão da cópia de 2026. `null` = sem calendário. */
function bimestresDoAno(ano: number, calendario?: CalendarioDoAno | null) {
  const fonte = calendario?.ano === ano ? calendario : EMBUTIDO_2026.ano === ano ? EMBUTIDO_2026 : null;
  if (!fonte?.bimestres?.length) return null;
  return fonte.bimestres
    .map((b) => ({ numero: b.numero, ano, inicio: isoUTC(b.inicio), fim: isoUTC(b.fim) }))
    .sort((a, b) => a.numero - b.numero);
}

/**
 * O bimestre que a tela abre marcado na data — a MESMA regra de `bimestre_sugerido` do
 * backend: dentro de um bimestre, ele; no recesso, o próximo; depois do 4º, o 4º.
 * `null` quando o ano não tem calendário conhecido — nunca um número inventado (antes
 * era 1, enviado ao backend como se fosse a escolha de alguém).
 */
export function bimestreDeHoje(d: Date, calendario?: CalendarioDoAno | null): number | null {
  const doAno = bimestresDoAno(d.getFullYear(), calendario);
  if (!doAno) return null;
  const dia = diaUTC(d);
  const achado = doAno.find((b) => dia <= b.fim);
  return achado ? achado.numero : 4;
}

/**
 * Bimestre em curso na data, com quantos dias faltam para o fim (contando o dia de
 * hoje como dia em curso: no último dia, faltam 0). `null` fora do calendário
 * (férias entre bimestres ou ano sem calendário) — nunca um número inventado.
 */
export function bimestreEmCurso(
  d: Date,
  calendario?: CalendarioDoAno | null,
): { numero: number; ano: number; inicio: Date; fim: Date; diasParaOFim: number } | null {
  const dia = diaUTC(d);
  const b = (bimestresDoAno(d.getFullYear(), calendario) ?? []).find((x) => dia >= x.inicio && dia <= x.fim);
  if (!b) return null;
  return {
    numero: b.numero,
    ano: b.ano,
    inicio: new Date(b.inicio),
    fim: new Date(b.fim),
    diasParaOFim: Math.round((b.fim - dia) / DIA_MS),
  };
}

/** O SERVIDOR respondeu que o ano da data não tem calendário oficial cadastrado (e não
 *  só "ainda não respondeu"): é quando a tela pode dizer isso a quem usa. */
export function semCalendarioOficial(d: Date, calendario?: CalendarioDoAno | null): boolean {
  return calendario?.ano === d.getFullYear() && !calendario.bimestres?.length;
}

/** O calendário oficial do ANO DE HOJE, lido do backend (uma vez por hora, em cache).
 *  `null` enquanto não respondeu, se falhou ou sem escola: as funções acima caem na
 *  cópia de 2026 e, fora dela, não inventam bimestre. */
export function useCalendarioBimestres(escolaId: number | null | undefined): CalendarioDoAno | null {
  const ano = new Date().getFullYear();
  const { dados } = useApi<CalendarioDoAno>(
    escolaId ? `/escolas/${escolaId}/configuracoes/calendario-bimestres?ano=${ano}` : null,
    { cacheMs: 60 * 60 * 1000 },
  );
  return dados?.ano === ano ? dados : null;
}

/** Turmas que NÃO concorrem às premiações — espelho de
 *  `backend/app/services/elegibilidade.py`. O backend barra de verdade (409);
 *  isto aqui só evita oferecer na tela um nome que não pode ser emitido. */
const RE_ETAPA_FORA =
  /\b(FASE|ETAPA|EMEI|INFANTIL|MATERNAL|BERCARIO|CRECHE|JARDIM|PRE|EJA|MINIGRUPO)\b/;
// O `O` maiúsculo na classe não é descuido: NFKD decompõe "º" em "o", e o rótulo
// é passado para MAIÚSCULAS logo em seguida — "4º" chega aqui como "4O".
const RE_ANO_EXPLICITO = /\b(\d\s*[º°O]?\s*ANO|ANO\s*\d)\b/;

export function participaDePremiacao(anoEscolar: string | null | undefined): boolean {
  const plano = (anoEscolar ?? "")
    .normalize("NFKD").replace(/[̀-ͯ]/g, "").toUpperCase().trim();
  if (!plano) return true; // sem rótulo não dá para afirmar que é fase
  if (!RE_ANO_EXPLICITO.test(plano) && RE_ETAPA_FORA.test(plano)) return false;
  const n = Number((plano.match(/\d/) ?? [])[0]);
  return n >= 1 && n <= 5;
}
