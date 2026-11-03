/** Inteligência Pedagógica (PRD §129–§153): índices e alertas automáticos.
 *
 * Identidade v2: alertas no topo (abertos — é o que dá para agir), como a lista
 * "Destaques recentes" (ícone pastel por gravidade, pílula com a gravidade por
 * extenso); índices numa tabela no padrão do Ranking (avatar com iniciais, chip
 * da turma, barra fina). A explicação dos índices foi para um "Como ler"
 * recolhível — o texto continua todo na página. Os índices são percentis (50 =
 * aluno mediano) e a persistência é do próprio aluno: nada foi reetiquetado.
 */
import { AlertTriangle, ChevronDown, Info, Lightbulb, Search, ShieldAlert, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Avatar,
  Card,
  Chip,
  Erro,
  IconePastel,
  PageHeader,
  Skeleton,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota } from "../lib/formato";
import { normalizar } from "../lib/nomes";

interface IndiceAluno {
  aluno_id: number;
  nome: string;
  turma: string;
  engajamento: number;
  evolucao: number;
  persistencia: number;
}

interface Alerta {
  tipo: string;
  gravidade: "alta" | "media" | "baixa";
  aluno_id: number;
  nome: string;
  turma: string;
  texto: string;
}

interface InsightsResposta {
  indices: IndiceAluno[];
  alertas: Alerta[];
}

/** Gravidade por extenso (a API manda o enum sem acento) e o visual de cada uma. */
const GRAVIDADE: Record<Alerta["gravidade"], { rotulo: string; tom: "rosa" | "ambar" | "azul"; pilula: string }> = {
  alta: { rotulo: "Alta", tom: "rosa", pilula: "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300" },
  media: { rotulo: "Média", tom: "ambar", pilula: "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300" },
  baixa: { rotulo: "Baixa", tom: "azul", pilula: "bg-sky-50 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" },
};

/** Células da tabela de índices: mais justas abaixo de 1280 px (tablet e notebook com
 *  a gaveta), para as colunas caberem sem rolagem lateral. No celular (< 640 px) a
 *  tabela vai de borda a borda do cartão: a coluna do aluno recupera o recuo do cartão
 *  (pl-5), os índices ficam mais justos e o rótulo perde o espaçamento entre letras —
 *  assim o nome e o Engajamento cabem inteiros e o resto vem deslizando a tabela. */
const th = `${classesTabela.th.replace("px-4", "px-3 xl:px-4")} max-sm:tracking-normal`;
const td = "px-3 py-3 xl:px-4";
const COLUNA_ALUNO = "max-sm:pl-5";
const COLUNA_INDICE = "max-sm:px-2 max-sm:last:pr-5";

/** Barra 0–100 com o número ao lado (a cor nunca é a única informação). Abaixo de
 *  1280 px a barra encurta; no celular ela sai e fica só o número (o número é o dado). */
function BarraIndice({ valor }: { valor: number }) {
  const cor = valor >= 66
    ? "from-emerald-400 to-emerald-500"
    : valor >= 33 ? "from-ouro-300 to-ouro-500" : "from-rose-300 to-rose-500";
  return (
    <div className="flex items-center gap-2.5">
      <div aria-hidden className="h-2 w-12 shrink-0 overflow-hidden rounded-full bg-zinc-100 max-sm:hidden xl:w-20 dark:bg-zinc-800">
        <div className={`h-full rounded-full bg-gradient-to-r ${cor}`} style={{ width: `${Math.max(0, Math.min(100, valor))}%` }} />
      </div>
      <span className="w-10 text-right font-semibold tabular-nums text-zinc-800 dark:text-zinc-100">{nota(valor)}</span>
    </div>
  );
}

export default function Insights() {
  const { escolaId } = useApp();
  const [verAlertas, setVerAlertas] = useState(true);
  const [comoLer, setComoLer] = useState(false);
  const [busca, setBusca] = useState("");
  // /insights é o endpoint mais pesado (evolução em 4 janelas). Já foi
  // otimizado no backend, mas escolas grandes ainda podem passar dos 15 s
  // padrão — damos folga para não cair no timeout (que virava "sem conexão").
  const { dados: dadosInsights, erro, carregando, recarregar } = useApi<InsightsResposta>(
    escolaId ? `/escolas/${escolaId}/insights` : null,
    { timeoutMs: 45000 },
  );

  const indices = useMemo(() => {
    const alvo = normalizar(busca.trim());
    const lista = dadosInsights?.indices ?? [];
    return alvo ? lista.filter((i) => normalizar(i.nome).includes(alvo)) : lista;
  }, [dadosInsights, busca]);

  const cabecalho = (
    <PageHeader
      titulo="Inteligência Pedagógica"
      descricao="Índices e alertas calculados por regras transparentes sobre os dados reais — sem caixa-preta."
    />
  );

  // Estado de erro discreto — antes o erro era engolido com arrays vazios.
  if (!carregando && erro) {
    return (
      <div className="space-y-6">
        {cabecalho}
        <Card><Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} /></Card>
      </div>
    );
  }
  if (!dadosInsights) {
    return (
      <div className="space-y-6">
        {cabecalho}
        <span className="sr-only">Carregando...</span>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-3" aria-hidden>
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 rounded-cartao" />)}
        </div>
        <Skeleton className="h-72 rounded-cartao" />
      </div>
    );
  }

  const { alertas } = dadosInsights;
  const contagem = (g: Alerta["gravidade"]) => alertas.filter((a) => a.gravidade === g).length;

  return (
    <div className="space-y-6">
      {cabecalho}

      {/* Resumo dos alertas por gravidade (contagens reais da resposta). */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        {(["alta", "media", "baixa"] as const).map((g) => (
          <Card key={g} className="flex items-center gap-4 p-5">
            <IconePastel icone={g === "alta" ? ShieldAlert : g === "media" ? AlertTriangle : Info} tom={GRAVIDADE[g].tom} tamanho="lg" />
            <div>
              <p className="text-[28px] font-bold leading-none tracking-tight text-zinc-900 tabular-nums dark:text-white">{contagem(g)}</p>
              <p className="mt-1 text-sm font-medium text-zinc-600 dark:text-zinc-300">
                alerta(s) de gravidade {GRAVIDADE[g].rotulo.toLowerCase()}
              </p>
            </div>
          </Card>
        ))}
      </div>

      <Card className="p-5 sm:p-6">
        <button
          type="button"
          onClick={() => setVerAlertas((v) => !v)}
          aria-expanded={verAlertas}
          className="-m-1 flex w-full items-center gap-3 rounded-xl p-1 text-left"
        >
          <IconePastel icone={AlertTriangle} tom="ambar" tamanho="sm" />
          <h2 className="text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
            Alertas ({alertas.length})
          </h2>
          <ChevronDown
            size={18}
            aria-hidden
            className={`ml-auto text-zinc-400 transition-transform ${verAlertas ? "rotate-180" : ""}`}
          />
        </button>
        {verAlertas && (
          <div className="mt-4">
            {alertas.length === 0 ? (
              <Vazio icone={Sparkles} titulo="Nenhum alerta" descricao="Todos os alunos estão com dados recentes e desempenho estável." />
            ) : (
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {alertas.map((alerta, indice) => {
                  const g = GRAVIDADE[alerta.gravidade] ?? GRAVIDADE.baixa;
                  return (
                    <li key={indice} className="flex items-start gap-3 py-3.5">
                      <IconePastel
                        icone={alerta.gravidade === "alta" ? ShieldAlert : alerta.gravidade === "media" ? AlertTriangle : Info}
                        tom={g.tom}
                        tamanho="sm"
                        className="mt-0.5"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-zinc-800 dark:text-zinc-100">{alerta.texto}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-2">
                          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${g.pilula}`}>
                            Gravidade {g.rotulo.toLowerCase()}
                          </span>
                          {alerta.turma && <Chip>{alerta.turma}</Chip>}
                          <Link
                            to={`/alunos/${alerta.aluno_id}`}
                            className="text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-300"
                          >
                            ver perfil de {alerta.nome}
                          </Link>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </Card>

      <Card className="p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
            <IconePastel icone={Lightbulb} tom="violeta" tamanho="sm" />
            Índices por aluno
          </h2>
          <div className="relative ml-auto w-full sm:w-64">
            <Search size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              aria-label="Buscar aluno"
              className={`${estiloInput} pl-9`}
              placeholder="Buscar aluno…"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>
        </div>

        {/* "Como ler" — a explicação inteira, recolhível (antes ficava espremida no cabeçalho). */}
        <button
          type="button"
          onClick={() => setComoLer((v) => !v)}
          aria-expanded={comoLer}
          aria-controls="como-ler-indices"
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg text-xs font-semibold text-indigo-600 hover:text-indigo-700 dark:text-indigo-300"
        >
          <Info size={14} aria-hidden /> Como ler os índices
          <ChevronDown size={14} aria-hidden className={`transition-transform ${comoLer ? "rotate-180" : ""}`} />
        </button>
        <div id="como-ler-indices" hidden={!comoLer}
             className="mt-2 rounded-2xl bg-zinc-50 p-4 text-xs leading-relaxed text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-300">
          engajamento e evolução = posição na escola (percentil · 50 = aluno mediano) · persistência (semanal) = ritmo do próprio aluno nesta semana (0–100 · 100 = manteve ou superou o próprio ritmo)
        </div>

        <div className="mt-4">
          {dadosInsights.indices.length === 0 ? (
            <Vazio icone={Lightbulb} titulo="Sem dados" descricao="Importe relatórios para calcular os índices." />
          ) : indices.length === 0 ? (
            <Vazio icone={Search} titulo="Nenhum aluno encontrado" descricao="Nenhum nome corresponde à busca." />
          ) : (
            // No celular a moldura sai do recuo do cartão (-mx-5) para ganhar 40 px; o
            // aviso "Deslize a tabela..." aparece ACIMA dela quando há coluna escondida.
            <TabelaRolavel rotulo="Índices por aluno: tabela completa" className="max-sm:-mx-5">
              <table className={classesTabela.tabela}>
                <thead>
                  <tr>
                    <th scope="col" className={`${th} ${COLUNA_ALUNO}`}>Aluno</th>
                    <th scope="col" className={`${th} ${COLUNA_INDICE}`}>Engajamento</th>
                    <th scope="col" className={`${th} ${COLUNA_INDICE}`}>Evolução</th>
                    {/* Abaixo de xl o rótulo quebra em duas linhas, num ponto escolhido
                        (antes saía cortado em "PERSISTÊN…" na borda do cartão). */}
                    <th scope="col" className={`${th} ${COLUNA_INDICE}`}>
                      Persistência <span className="block xl:inline">(semanal)</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {indices.map((item) => (
                    <tr key={item.aluno_id} className={classesTabela.tr}>
                      <td className={`${td} ${COLUNA_ALUNO}`}>
                        {/* A turma vai no chip sob o nome (era uma coluna à parte; uma vez
                            só no DOM, como em Turmas e Usuários): a coluna a menos é o que
                            deixa os índices à vista no celular. O nome quebra em até duas
                            linhas (largura mínima no celular) em vez de uma palavra por linha.
                            O avatar é decorativo e sai no celular. */}
                        <div className="flex items-center gap-3">
                          <Avatar nome={item.nome} chave={item.aluno_id} tamanho="sm" className="max-sm:hidden" />
                          <div className="min-w-0 max-sm:min-w-[8.5rem]">
                            <Link
                              to={`/alunos/${item.aluno_id}`}
                              title={item.nome}
                              className="block font-semibold leading-snug text-zinc-800 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300"
                            >
                              {item.nome}
                            </Link>
                            {item.turma && <Chip className="mt-1">{item.turma}</Chip>}
                          </div>
                        </div>
                      </td>
                      <td className={`${td} ${COLUNA_INDICE}`}><BarraIndice valor={item.engajamento} /></td>
                      <td className={`${td} ${COLUNA_INDICE}`}><BarraIndice valor={item.evolucao} /></td>
                      <td className={`${td} ${COLUNA_INDICE}`}><BarraIndice valor={item.persistencia} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TabelaRolavel>
          )}
        </div>
      </Card>
    </div>
  );
}
