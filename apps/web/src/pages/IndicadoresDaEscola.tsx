/**
 * Seção "Indicadores oficiais da escola" da Visão da Escola — etapa E9 dos indicadores
 * oficiais (plano, 5.2; decisão D5 do dono, 17/10). Vive num arquivo próprio e entra na
 * `VisaoEscola` por uma linha (a página tem trabalho paralelo).
 *
 * Lê `GET /escolas/{id}/indicadores` — o coordenador (ou o admin) da própria escola, a
 * Secretaria da rede da escola e o admin global; o professor não lê (a seção nem chama a
 * API). Mostra SÓ esta escola: o SARESP oficial (proficiência do IEE, participação, TPS,
 * IEE e meta) e o Ideb/Saeb do 5º ano, com o motivo de cada ausência (nunca 0), e as
 * REFERÊNCIAS da rede municipal, do Estado e do Brasil. O ICA aparece só como indicador
 * DA REDE (o INEP não o publica por escola), comparado na mesma rede (SP só nas redes
 * municipais) e com SP e Brasil da rede pública rotulados como outra rede. Sem ranking:
 * nenhuma outra escola aparece. O selo de fonte acompanha cada bloco.
 *
 * A resposta só é mostrada quando é DA escola selecionada (`dados.escola.id`): ao trocar de
 * escola no seletor do topo, o `useApi` guarda a resposta anterior até a nova chegar — a
 * seção mostra o carregamento ou o erro, nunca os números de outra escola.
 */
import { BadgeCheck } from "lucide-react";

import SeloFonte, { fontesUnicas, type FonteOficial } from "../components/SeloFonte";
import { Badge, Card, Carregando, IconePastel, Mensagem } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import { Aviso, Bloco, Nota, Situacao } from "./rede/IdebBlocos";
import { nomeComRede, percentual, type RespostaICA, type TerritorioICA } from "./rede/ica";
import {
  MOTIVOS_IDEB, textoAusenciaIDEB, textoSemMeta, valorIDEB,
  type EdicaoIDEB, type FonteIDEB, type NumeroIDEB, type RedeMunicipalIDEB,
} from "./rede/ideb";
import {
  COMPONENTES, ETAPAS, MOTIVOS_SARESP, ROTULO_ETAPA, SIGLA_COMPONENTE, media, serieDe, textoAusencia,
  type EdicaoEscola, type FonteSARESP, type NumeroSARESP, type TerritorioSARESP,
} from "./rede/saresp";

interface SarespDaEscola {
  avisos: Record<string, string>;
  edicoes: number[];
  por_edicao: (EdicaoEscola & { fonte_da_edicao: FonteSARESP | null })[];
  territorios: TerritorioSARESP[];
  edicoes_rede: number[];
  fontes: FonteSARESP[];
  tem_dados_escola: boolean;
  tem_dados: boolean;
}

interface IdebDaEscola {
  avisos: Record<string, string>;
  edicoes: number[];
  anos_meta: number[];
  serie: (EdicaoIDEB & { fonte_da_edicao_id: number | null })[];
  participacao: { disponivel: boolean; decisao: string; texto: string };
  rede_municipal: RedeMunicipalIDEB;
  fontes: FonteIDEB[];
  tem_dados_escola: boolean;
  tem_dados: boolean;
}

type IcaDaEscola = Pick<RespostaICA, "territorios" | "uf_municipal" | "fontes" | "tem_dados" | "aviso_rede"> & {
  papel: "referencia_da_rede";
  aviso: string;
};

export interface RespostaIndicadoresEscola {
  escola: { id: number; nome: string; codigo_inep: string | null; status: string; pendencia: string | null };
  rede: { id: number; nome: string; codigo_ibge: string | null; municipio: string | null } | null;
  avisos: Record<string, string>;
  pendencias: string[];
  saresp: SarespDaEscola | null;
  ideb: IdebDaEscola | null;
  ica: IcaDaEscola | null;
  tem_dados_escola: boolean;
  tem_dados: boolean;
}

const TH = "px-2 py-1.5 text-left font-medium";
const TD = "px-2 py-1.5 tabular-nums";
/** Cabeçalho de LINHA (edição, território): alinhado à esquerda como as células. */
const TH_LINHA = `${TD} text-left`;

/** O número na precisão publicada; sem número, "—" com o MOTIVO (nunca 0). */
function Celula({ valor, ausencia }: { valor: string; ausencia: string | null }) {
  if (ausencia === null) return <>{valor}</>;
  return (
    <span className="text-zinc-400" title={ausencia}>
      —<span className="block text-[11px] leading-tight">{ausencia}</span>
    </span>
  );
}

/** Na visão da escola, a "estimativa mantida" (decisão D2) não aparece — o coordenador não
 *  vê o bloco das estimativas: a célula diz só que o oficial não foi gravado. */
const OFICIAL_NAO_GRAVADO = "o número oficial desta edição ainda não foi gravado no Constela";

function motivoSaresp(motivo: string | null | undefined): string {
  if (motivo === "estimativa_mantida_d2") return OFICIAL_NAO_GRAVADO;
  return MOTIVOS_SARESP[motivo ?? ""] ?? "sem resultado";
}

function ausenciaSaresp(n: NumeroSARESP | null | undefined): string {
  return n?.motivo_ausencia === "estimativa_mantida_d2" ? OFICIAL_NAO_GRAVADO : textoAusencia(n);
}

/** Número do SARESP na precisão publicada (`casas` quando a fonte não diz); sem número, o motivo. */
function celulaSaresp(n: NumeroSARESP | null | undefined, casas = 1, sufixo = "") {
  const valor = n && n.valor != null ? `${media({ ...n, casas_decimais: n.casas_decimais ?? casas })}${sufixo}` : "";
  return <Celula valor={valor} ausencia={n && n.valor != null ? null : ausenciaSaresp(n)} />;
}

/** TPS como a aba da rede: "atingiu" / "não atingiu (média instável)" — nunca o 1/0 cru. */
function celulaTps(n: NumeroSARESP | null | undefined) {
  if (!n || n.valor == null) return <Celula valor="" ausencia={ausenciaSaresp(n)} />;
  return n.valor >= 1 ? <>atingiu</> : (
    <>não atingiu <span className="block text-[11px] text-amber-700 dark:text-amber-400">média instável</span></>
  );
}

function celulaIdeb(n: NumeroIDEB | null | undefined, casas: number) {
  return <Celula valor={valorIDEB(n, casas)} ausencia={n && n.valor != null ? null : textoAusenciaIDEB(n)} />;
}

// --- SARESP --------------------------------------------------------------------------

function SarespEscola({ s }: { s: SarespDaEscola }) {
  const edicoes = [...s.por_edicao].sort((a, b) => b.edicao - a.edicao);
  // A edição das referências: a mais nova com resultado da escola (ou a mais nova da rede).
  const comResultado = edicoes.find((e) => e.tem_resultado)?.edicao;
  const edRef = comResultado ?? (s.edicoes_rede.length ? Math.max(...s.edicoes_rede) : null);
  const referencias = s.territorios.filter((t) => t.tem_dados);
  const colunas = ETAPAS.flatMap((et) => COMPONENTES.map((c) => ({ et, c })));
  // O selo cita os arquivos dos números MOSTRADOS: os da escola (ou o arquivo da edição,
  // quando ela não tem número) e os das referências da edição exibida.
  const fontes = fontesUnicas([
    ...edicoes.flatMap((ed) => [
      ...ETAPAS.flatMap((et) => [...COMPONENTES.map((c) => ed.proficiencia[et][c]?.fonte), ed.participacao[et]?.fonte]),
      ed.tps?.fonte, ed.iee?.fonte, ed.meta?.fonte, ed.fonte_da_edicao,
    ]),
    ...(edRef == null ? [] : referencias.flatMap((t) => colunas.map(({ et, c }) =>
      serieDe(t, et, c).find((n) => n.edicao === edRef)?.fonte))),
  ]);
  return (
    <Bloco titulo="SARESP (SEDUC-SP) — 2º e 5º ano" testId="indicadores-escola-saresp">
      {s.avisos.escala && <Nota>{s.avisos.escala}</Nota>}
      {edicoes.length === 0 ? (
        <p className="text-sm text-zinc-500">Sem resultado oficial do SARESP importado para a escola.</p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">SARESP oficial da escola por edição</caption>
            <thead>
              <tr className="border-b border-zinc-200 text-zinc-500 dark:border-zinc-800">
                <th className={TH}>Edição</th>
                {colunas.map(({ et, c }) => (
                  <th key={`${et}-${c}`} className={TH}>{ROTULO_ETAPA[et]} {SIGLA_COMPONENTE[c]}</th>
                ))}
                <th className={TH}>Participação (2º / 5º)</th>
                <th className={TH}>TPS</th>
                <th className={TH}>IEE (meta)</th>
              </tr>
            </thead>
            <tbody>
              {edicoes.map((ed) => (
                <tr key={ed.edicao} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <th scope="row" className={`${TH_LINHA} font-medium`}>{ed.edicao}</th>
                  {!ed.no_arquivo && !ed.tem_resultado ? (
                    <td colSpan={colunas.length + 3} className={`${TD} text-zinc-500`}>
                      Sem resultado: {motivoSaresp(ed.motivo)}
                    </td>
                  ) : (
                    <>
                      {colunas.map(({ et, c }) => (
                        <td key={`${et}-${c}`} className={TD}>{celulaSaresp(ed.proficiencia[et][c])}</td>
                      ))}
                      <td className={TD}>
                        {ETAPAS.map((et, i) => (
                          <span key={et}>{i > 0 && " / "}{celulaSaresp(ed.participacao[et], 1, "%")}</span>
                        ))}
                      </td>
                      <td className={TD}>{celulaTps(ed.tps)}</td>
                      <td className={TD}>
                        {celulaSaresp(ed.iee, 2)}
                        {ed.meta && ed.meta.valor != null ? (
                          ` (${media({ ...ed.meta, casas_decimais: ed.meta.casas_decimais ?? 2 })})`
                        ) : (
                          <span className="block text-[11px] leading-tight text-zinc-400">
                            meta: {ausenciaSaresp(ed.meta)}
                          </span>
                        )}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {s.avisos.tps && edicoes.some((e) => e.tps?.valor === 0) && <Nota>{s.avisos.tps}</Nota>}
      {referencias.length > 0 && edRef != null && (
        <div className="relative overflow-x-auto" data-testid="indicadores-escola-saresp-referencias">
          <table className="w-full text-xs">
            <caption className="py-1 text-left text-xs font-medium text-zinc-600 dark:text-zinc-300">
              Referências — SARESP {edRef}
            </caption>
            <thead>
              <tr className="border-b border-zinc-200 text-zinc-500 dark:border-zinc-800">
                <th className={TH}>Território</th>
                {colunas.map(({ et, c }) => (
                  <th key={`${et}-${c}`} className={TH}>{ROTULO_ETAPA[et]} {SIGLA_COMPONENTE[c]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {referencias.map((t) => (
                <tr key={t.chave} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <th scope="row" className={`${TH_LINHA} font-normal`}>
                    {t.rotulo}
                    {!t.mesma_rede && <span className="block text-[11px] text-zinc-400">outra rede — só contexto</span>}
                  </th>
                  {colunas.map(({ et, c }) => (
                    <td key={`${et}-${c}`} className={TD}>
                      {celulaSaresp(serieDe(t, et, c).find((n) => n.edicao === edRef))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <SeloFonte fontes={fontes} testId="indicadores-escola-saresp-fonte" />
    </Bloco>
  );
}

// --- Ideb e Saeb -----------------------------------------------------------------------

function ultimoIdeb(serie: { edicao: number; ideb: NumeroIDEB | null }[]) {
  return [...serie].sort((a, b) => b.edicao - a.edicao).find((e) => e.ideb?.valor != null) ?? null;
}

function IdebEscola({ d }: { d: IdebDaEscola }) {
  const serie = [...d.serie].sort((a, b) => b.edicao - a.edicao);
  const terrIdeb = d.rede_municipal.ideb.territorios.filter((t) => t.tem_dados);
  const terrSaeb = d.rede_municipal.saeb.territorios.filter((t) => t.tem_dados);
  const ultimoSaeb = (t: (typeof terrSaeb)[number]) => [...t.edicoes].sort((a, b) => b.edicao - a.edicao)[0];
  // O selo cita os arquivos dos números MOSTRADOS (a série da escola e a última edição de
  // cada referência).
  const ids = new Set<number>();
  const usar = (n: NumeroIDEB | null | undefined) => { if (n?.fonte_id != null) ids.add(n.fonte_id); };
  for (const ed of serie) {
    [ed.ideb, ed.meta, ed.saeb_lp, ed.saeb_mt].forEach(usar);
    if (ed.fonte_da_edicao_id != null) ids.add(ed.fonte_da_edicao_id);
  }
  terrIdeb.forEach((t) => usar(ultimoIdeb(t.serie)?.ideb));
  terrSaeb.forEach((t) => { const u = ultimoSaeb(t); usar(u?.media.lp); usar(u?.media.mt); });
  const fontes: FonteOficial[] = d.fontes.filter((f) => ids.has(f.importacao_id));
  return (
    <Bloco titulo="Ideb e Saeb do 5º ano (INEP)" testId="indicadores-escola-ideb">
      {d.avisos.comparabilidade && <Aviso>{d.avisos.comparabilidade}</Aviso>}
      {serie.length === 0 ? (
        <p className="text-sm text-zinc-500">Sem resultado oficial do Ideb importado para a escola.</p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">Ideb e Saeb oficiais da escola por edição</caption>
            <thead>
              <tr className="border-b border-zinc-200 text-zinc-500 dark:border-zinc-800">
                <th className={TH}>Edição</th>
                <th className={TH}>Ideb</th>
                <th className={TH}>Meta</th>
                <th className={TH}>Saeb LP</th>
                <th className={TH}>Saeb MT</th>
              </tr>
            </thead>
            <tbody>
              {serie.map((ed) => (
                <tr key={ed.edicao} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <th scope="row" className={`${TH_LINHA} font-medium`}>{ed.edicao}</th>
                  <td className={TD}>
                    {ed.ideb?.valor != null
                      ? valorIDEB(ed.ideb, 1)
                      : <Celula valor="" ausencia={ed.ideb ? textoAusenciaIDEB(ed.ideb)
                                                          : MOTIVOS_IDEB[ed.motivo ?? ""] ?? "sem resultado"} />}
                    {ed.ideb?.proveniencia === "sem_registro" && (
                      <span className="block text-[11px] text-amber-700 dark:text-amber-400">sem registro oficial</span>
                    )}
                  </td>
                  <td className={TD}>
                    {ed.meta?.valor != null ? (
                      <span className="inline-flex flex-wrap items-center gap-1">
                        {valorIDEB(ed.meta, 1)} {ed.comparacao_meta && <Situacao c={ed.comparacao_meta} />}
                      </span>
                    ) : ed.meta ? (
                      <Celula valor="" ausencia={textoAusenciaIDEB(ed.meta)} />
                    ) : (
                      <span className="text-zinc-400">{textoSemMeta(ed.edicao, ed.sem_meta, d.anos_meta) ?? "—"}</span>
                    )}
                  </td>
                  <td className={TD}>{celulaIdeb(ed.saeb_lp, 2)}</td>
                  <td className={TD}>{celulaIdeb(ed.saeb_mt, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(terrIdeb.length > 0 || terrSaeb.length > 0) && (
        <ul className="space-y-1 text-xs text-zinc-600 dark:text-zinc-300" data-testid="indicadores-escola-ideb-referencias">
          <li className="font-medium">Referências</li>
          {terrIdeb.map((t) => {
            const ult = ultimoIdeb(t.serie);
            return (
              <li key={`ideb-${t.chave}`}>
                Ideb — {t.rotulo}: {ult ? `${valorIDEB(ult.ideb, 1)} (${ult.edicao})` : "sem resultado"}
                {t.contexto && t.rotulo_contexto ? ` · ${t.rotulo_contexto}` : ""}
              </li>
            );
          })}
          {terrSaeb.map((t) => {
            const ult = ultimoSaeb(t);
            return (
              <li key={`saeb-${t.chave}`}>
                Saeb do 5º ano — {t.rotulo}: {ult
                  ? `LP ${valorIDEB(ult.media.lp, 2)} · MT ${valorIDEB(ult.media.mt, 2)} (${ult.edicao})`
                  : "sem resultado"}
              </li>
            );
          })}
        </ul>
      )}
      {d.participacao && !d.participacao.disponivel && <Nota>{d.participacao.texto}</Nota>}
      <SeloFonte fontes={fontes} testId="indicadores-escola-ideb-fonte" />
    </Bloco>
  );
}

// --- ICA (da rede) -------------------------------------------------------------------------

function IcaDaRede({ ica }: { ica: IcaDaEscola }) {
  // Plano 4.8: a comparação é na MESMA rede — o município e SP só nas redes municipais
  // (microdados); SP e Brasil na rede pública (como o INEP divulga o ICA) são OUTRA rede,
  // ficam por último e com o rótulo explícito (como na aba ICA da rede).
  const comDados: TerritorioICA[] = ica.territorios.filter((t) => t.tem_dados);
  const ufm = ica.uf_municipal?.tem_dados ? ica.uf_municipal : null;
  const mesmaRede = (t: TerritorioICA) => t.rede_ensino === "municipal";
  const territorios = [
    ...comDados.filter((t) => t.abrangencia === "municipio"),
    ...(ufm ? [ufm] : []),
    ...comDados.filter((t) => t.abrangencia !== "municipio"),
  ];
  const fontes = fontesUnicas(territorios.flatMap((t) => [t.destaque?.resultado.fonte, t.destaque?.meta?.fonte]));
  return (
    <Bloco titulo="Criança Alfabetizada (ICA) — indicador da rede" testId="indicadores-escola-ica">
      <Nota>{ica.aviso}</Nota>
      {territorios.length === 0 ? (
        <p className="text-sm text-zinc-500">Sem o ICA oficial importado para a rede.</p>
      ) : (
        <ul className="space-y-1 text-xs text-zinc-700 dark:text-zinc-200" data-testid="indicadores-escola-ica-territorios">
          {territorios.map((t) => (
            <li key={`${t.abrangencia}-${t.rede_ensino}`}>
              <span className="font-medium">{nomeComRede(t)}</span>:{" "}
              {t.destaque
                ? `${percentual(t.destaque.resultado)} (${t.destaque.resultado.edicao})`
                  + (t.destaque.meta ? ` · meta ${percentual(t.destaque.meta)}` : "")
                : "sem resultado"}
              {!mesmaRede(t) && <span className="text-zinc-400"> · outra rede — só contexto</span>}
            </li>
          ))}
        </ul>
      )}
      {territorios.some((t) => !mesmaRede(t)) && (
        <p className="text-[11px] text-zinc-500" data-testid="indicadores-escola-ica-outra-rede">
          SP e Brasil na rede pública (estadual e municipal) são como o INEP divulga o ICA — não é a mesma rede do
          município. A comparação na mesma rede é “São Paulo (redes municipais)”, dos microdados.
        </p>
      )}
      <SeloFonte fontes={fontes} testId="indicadores-escola-ica-fonte" />
    </Bloco>
  );
}

// --- Seção ---------------------------------------------------------------------------------

/** O conteúdo (só apresentação) — a partir da resposta da API. */
export function ConteudoIndicadoresEscola({ dados }: { dados: RespostaIndicadoresEscola }) {
  // Sem o código IBGE da rede, nada é recortado pelo município: dizer a causa, não "nada importado".
  const semIbge = Boolean(dados.rede) && dados.pendencias.includes("codigo_ibge");
  return (
    <>
      <p className="text-xs text-zinc-500">{dados.avisos.escopo}</p>
      {dados.pendencias.includes("sem_rede") && dados.avisos.sem_rede && <Aviso>{dados.avisos.sem_rede}</Aviso>}
      {dados.escola.pendencia === "codigo_inep" && (
        <Aviso testId="indicadores-escola-sem-inep">
          A escola está sem código INEP no cadastro: os arquivos oficiais não casam com ela. Quem cadastra o
          código é o administrador global do Constela.
        </Aviso>
      )}
      {semIbge && (
        <Aviso testId="indicadores-escola-sem-ibge">
          A rede está sem o código IBGE do município no cadastro: os arquivos oficiais não podem ser recortados para o
          município, e as referências da rede ficam vazias. Quem cadastra o código é o administrador global do
          Constela.
        </Aviso>
      )}
      {dados.rede && !dados.tem_dados && !semIbge && (
        <p className="rounded-2xl border border-dashed border-zinc-300 p-4 text-sm text-zinc-500 dark:border-zinc-700"
           data-testid="indicadores-escola-vazio">
          Nenhum indicador oficial importado ainda para a escola nem para a rede.
        </p>
      )}
      {dados.saresp && dados.saresp.tem_dados && <SarespEscola s={dados.saresp} />}
      {dados.ideb && dados.ideb.tem_dados && <IdebEscola d={dados.ideb} />}
      {dados.ica && dados.ica.tem_dados && <IcaDaRede ica={dados.ica} />}
    </>
  );
}

export default function IndicadoresDaEscola({ escolaId }: { escolaId: number | null }) {
  const { gestor, secretaria } = usePerfil();
  // O professor não lê os indicadores oficiais (D5): a seção nem chama a API.
  const pode = gestor || secretaria;
  const { dados, carregando, erro } = useApi<RespostaIndicadoresEscola>(
    pode && escolaId ? `/escolas/${escolaId}/indicadores` : null);
  if (!pode || !escolaId) return null;
  // Ao trocar de escola, o useApi guarda a resposta ANTERIOR até a nova chegar (ou falhar):
  // só a resposta desta escola é mostrada — nunca os números de outra sob este cabeçalho.
  const daEscola = dados && dados.escola.id === escolaId ? dados : null;
  return (
    <section className="mt-6" data-testid="indicadores-escola" aria-label="Indicadores oficiais da escola">
      <Card className="space-y-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <IconePastel icone={BadgeCheck} tom="violeta" />
            <div className="min-w-0">
              <h2 className="text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
                Indicadores oficiais da escola
              </h2>
              {daEscola && (
                <p className="mt-0.5 text-xs text-zinc-500" data-testid="indicadores-escola-nome">{daEscola.escola.nome}</p>
              )}
            </div>
          </div>
          <Badge tom="destaque">INEP · SEDUC-SP</Badge>
        </div>
        {carregando && !daEscola ? (
          <Carregando texto="Carregando os indicadores oficiais..." />
        ) : erro && !daEscola ? (
          <Mensagem tipo="erro">Não foi possível carregar os indicadores oficiais: {erro.message}</Mensagem>
        ) : daEscola ? (
          <ConteudoIndicadoresEscola dados={daEscola} />
        ) : null}
      </Card>
    </section>
  );
}
