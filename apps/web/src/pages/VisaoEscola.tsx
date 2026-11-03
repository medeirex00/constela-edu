/** Visão da escola (PRD §78): comparação entre todas as turmas.
 *
 * Identidade v2: indicadores da escola em StatCards (somas REAIS das turmas — só o
 * que é aditivo: alunos, tempo e atividades; "livros únicos" por turma não somam),
 * e a tabela "Desempenho por turma" no padrão da referência. A barra da média agora
 * é ABSOLUTA (0–100) — antes era relativa à maior média e a melhor turma aparecia
 * sempre cheia. Ao lado de cada média, quantos alunos têm dado (o denominador), e
 * "sem dado" no lugar de um 0 que não existe.
 */
import { BookOpen, Calculator, ChevronLeft, Clock, GraduationCap, School, Users } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import AcessoUsuariosDaEscola from "../components/AcessoUsuariosDaEscola";
import { TabelaRolavel } from "../components/TabelaRolavel";
import { BarraProgresso, Card, Erro, IconePastel, PageHeader, Skeleton, StatCard, Vazio, classesTabela } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import { nota, numero, tempoLeitura } from "../lib/formato";
import AnaliseDaEscola from "./analise/AnaliseDaEscola";

/** Matéria escondida da Secretaria (grupo pequeno: menos de 3 alunos com dado ou só 1
 *  ou 2 com resultado acima de zero, ou o complemento que protege outra turma). O texto
 *  vem do backend. */
interface Oculto { motivo: "grupo_pequeno" | "complementar"; texto: string }

interface ResumoTurma {
  turma: { id: number; nome: string; ano_escolar: string };
  total_alunos: number;
  // `null` só para a Secretaria, na matéria escondida (ver `oculto`).
  media_geral: number | null;
  media_matific: number | null;
  media_elefante: number | null;
  indicadores: Record<string, number | null>;
  grupo_pequeno?: boolean;
  oculto?: { leitura?: Oculto | null; matematica?: Oculto | null };
  // Vocabulário novo (opcional: um bundle em cache pode falar com uma API anterior).
  n_leitura?: number;
  n_matematica?: number;
  contratadas?: string[];
  alcance?: number;
}

interface ResumoEscola {
  escola: { id: number; nome: string };
  turmas: ResumoTurma[];
}

/** Valor escondido da Secretaria: "—" e a palavra "protegido", com o motivo inteiro no
 *  leitor de tela e na dica. Nunca 0. */
function Protegido({ oculto }: { oculto: Oculto }) {
  return (
    <span className="inline-flex flex-col items-end leading-tight" title={oculto.texto}>
      <span aria-hidden className="font-semibold text-zinc-500 dark:text-zinc-400">—</span>
      <span aria-hidden className="whitespace-nowrap text-[11px] text-zinc-500 dark:text-zinc-400">protegido</span>
      <span className="sr-only">{oculto.texto}</span>
    </span>
  );
}

/** Média da dimensão com o denominador; sem aluno com dado, diz "sem dado" (não 0). */
function MediaComCobertura({ media, n, total, oculto }: {
  media: number | null; n?: number; total: number; oculto?: Oculto | null;
}) {
  if (oculto) return <Protegido oculto={oculto} />;
  if (n === 0) return <span className="whitespace-nowrap text-xs text-zinc-500 dark:text-zinc-400">sem dado</span>;
  return (
    <span className="inline-flex flex-col items-end leading-tight">
      <span className="font-semibold text-zinc-800 dark:text-zinc-100">{nota(media)}</span>
      {/* Numa linha só: antes "5 de 5 alunos" quebrava em três. No tablet em pé a palavra
          "alunos" fica só para o leitor de tela (a legenda da tabela explica o "n de N"). */}
      {n != null && (
        <span className="whitespace-nowrap text-[11px] text-zinc-500 dark:text-zinc-400">
          {n} de {total}<span className="sr-only lg:not-sr-only lg:whitespace-nowrap"> alunos</span>
        </span>
      )}
    </span>
  );
}

/* Tabela "Desempenho por turma": são nove colunas. A versão folgada (selo da série,
   células largas, barras longas) só cabe no cartão a partir de 1440 px com a barra
   lateral; abaixo disso as células ficam mais justas e o selo sai (a série continua na
   linha de baixo do nome), e tudo cabe com ~960 px de conteúdo (notebook 1280 e tablet
   1024 deitado). No tablet em pé (< 1024 px) as barras e os ícones dos cabeçalhos saem
   (os números ficam), e cabe em 820 px; se ainda faltar largura (768 px), a tabela rola
   de lado com a coluna "detalhes" presa à direita e uma sombra na borda dela, avisando
   que há mais colunas por baixo.
   No celular (< 640 px) o que fica preso é a TURMA, à esquerda: ao deslizar a tabela,
   Leitura, Matific e as demais passam ao lado do nome, e o aviso "Deslize..." aparece em
   cima. O "detalhes" ali rola junto com as outras (o nome da turma já leva ao mesmo
   lugar), para não esconder Leitura e Matific por baixo de duas colunas presas. */
const PAD = "px-3 min-[1440px]:px-4";
const TH = classesTabela.th.replace("px-4", PAD);
const TD = `${PAD} py-3`;
const COLUNA_PRESA =
  "sm:sticky sm:right-0 sm:z-[1] sm:bg-white sm:shadow-[-10px_0_10px_-10px_rgba(26,28,56,0.3)] dark:sm:bg-zinc-900 " +
  "dark:sm:shadow-[-10px_0_10px_-10px_rgba(0,0,0,0.7)] lg:static lg:bg-transparent lg:shadow-none " +
  "dark:lg:bg-transparent dark:lg:shadow-none";
const PRESA_ESQUERDA_CELULAR = "presa-esquerda-celular"; // index.css (irmã da presa-celular)
/** Cartões de KPI: 2 por linha já no celular (números curtos; um por linha deixava meio
 *  cartão vazio). Com número ímpar de cartões, o último ocupa a linha inteira no celular. */
const GRADE_KPI = "mb-6 grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2";

/** O "Voltar" de quem é de rede: para a tela de onde a Visão da Escola foi aberta, com o
 *  nome dela. Quem abre a tela passa a origem no estado da navegação:
 *    navegar("/escola", { state: { voltar: { caminho: "/rede/escolas/3",
 *                                            texto: "Voltar para a ficha da escola" } } })
 *  Sem origem (link direto, recarga numa aba nova, tela que ainda não passa a origem), volta
 *  à página de rede do perfil, com o nome dela: a Secretaria, ao Panorama da Rede (a página
 *  inicial dela — o Painel da Rede saiu do menu dela, DESENHO3 §5); o Admin Global, ao Painel
 *  da Rede ("Voltar para a visão da rede" levava ao Painel e se confundia com a tela "Visão
 *  da rede", /rede/visao, dele). */
export interface VoltaDaVisaoEscola { caminho: string; texto: string }
export interface EstadoDaVisaoEscola { voltar?: VoltaDaVisaoEscola }

const VOLTA_DA_SECRETARIA: VoltaDaVisaoEscola = { caminho: "/", texto: "Voltar ao Panorama da Rede" };
const VOLTA_DO_GLOBAL: VoltaDaVisaoEscola = { caminho: "/rede", texto: "Voltar ao Painel da Rede" };

/** A origem do estado, se for um caminho DESTE sistema ("/...", nunca "//outro-site") com
 *  texto; senão, o padrão do perfil. */
function voltaDoEstado(estado: unknown, padrao: VoltaDaVisaoEscola): VoltaDaVisaoEscola {
  const v = (estado as EstadoDaVisaoEscola | null | undefined)?.voltar;
  const valida = typeof v?.caminho === "string" && v.caminho.startsWith("/") && !v.caminho.startsWith("//")
    && typeof v.texto === "string" && v.texto.trim() !== "";
  return valida ? { caminho: v.caminho, texto: v.texto } : padrao;
}

export default function VisaoEscola() {
  const { escolaId } = useApp();
  const { rede, secretaria } = usePerfil();
  const { state: estadoDaNavegacao } = useLocation();
  const { dados: resumo, erro, carregando, recarregar } = useApi<ResumoEscola>(
    escolaId ? `/escolas/${escolaId}/resumo-escola` : null,
  );

  const volta = voltaDoEstado(estadoDaNavegacao, secretaria ? VOLTA_DA_SECRETARIA : VOLTA_DO_GLOBAL);
  const voltar = rede && (
    <Link
      to={volta.caminho}
      className="mb-4 inline-flex items-center gap-1 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm font-semibold text-indigo-600 shadow-cartao transition-colors hover:border-indigo-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-indigo-300"
    >
      <ChevronLeft size={16} aria-hidden /> {volta.texto}
    </Link>
  );
  const cabecalho = (
    <PageHeader
      titulo="Visão da Escola"
      descricao="Como cada turma está em leitura e matemática, lado a lado — e quantos alunos têm dado em cada média."
    />
  );

  // Em vez de engolir a falha, mostra um estado de erro com "Tentar de novo".
  if (!carregando && erro) {
    return (
      <div>
        {voltar}
        {cabecalho}
        <Card><Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} /></Card>
      </div>
    );
  }
  // Sem escola no contexto não há o que buscar: a Secretaria começa toda sessão em "Toda a Rede
  // Municipal", e "Ver as turmas da escola" aberto numa aba nova (ou a recarga) chega aqui sem
  // escola. Em vez do esqueleto sem fim, o caminho por extenso — para quem é de rede, a tela Escolas.
  if (!escolaId) {
    return (
      <div>
        {voltar}
        {cabecalho}
        <Card>
          <Vazio
            icone={School}
            titulo="Escolha uma escola"
            descricao={rede
              ? "A Visão da Escola mostra as turmas de uma escola. Em Escolas, abra a ficha da escola e use “Ver as turmas da escola”."
              : "Use o cartão Escola, no fim do menu lateral (no tablet e no celular, dentro do menu)."}
            acao={rede ? (
              <Link to="/rede/escolas"
                    className="inline-flex items-center gap-1 rounded-lg text-sm font-semibold text-indigo-700 hover:underline dark:text-indigo-300">
                Ir para Escolas
              </Link>
            ) : undefined}
          />
        </Card>
      </div>
    );
  }
  if (!resumo) {
    return (
      <div>
        {voltar}
        {cabecalho}
        <span className="sr-only">Carregando...</span>
        <div className={GRADE_KPI} aria-hidden>
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36 rounded-cartao" />)}
        </div>
        <Skeleton className="h-64 rounded-cartao" />
      </div>
    );
  }

  const turmas = resumo.turmas;
  const contratadas = turmas.find((t) => t.contratadas)?.contratadas ?? ["leitura", "matematica"];
  const temLeitura = contratadas.includes("leitura");
  const temMatematica = contratadas.includes("matematica");
  const soma = (chave: string) => turmas.reduce((acc, t) => acc + (Number(t.indicadores?.[chave]) || 0), 0);
  // Secretaria: turmas com a matéria escondida (grupo pequeno) ficam FORA da soma. O total
  // diz isso; se nenhuma turma visível tem número, o total é "—" (somar só zeros e chamar
  // de total da escola seria mentir sobre as turmas escondidas).
  const totalDaEscola = (chave: string, materia: "leitura" | "matematica",
                         formatar: (v: number) => string, detalhe: string) => {
    const protegidas = turmas.filter((t) => t.oculto?.[materia]).length;
    const valor = soma(chave);
    if (protegidas === 0) return { valor: formatar(valor), detalhe };
    return {
      valor: valor > 0 ? formatar(valor) : "—",
      detalhe: `${detalhe} · sem ${protegidas} turma(s) protegida(s) (poucos alunos com resultado)`,
    };
  };
  const tempoEscola = totalDaEscola("tempo_leitura_min", "leitura", tempoLeitura, "Elefante Letrado, somado das turmas");
  const atividadesEscola = totalDaEscola("atividades", "matematica", numero, "somadas das turmas");
  const algumaProtegida = turmas.some((t) => t.oculto?.leitura || t.oculto?.matematica);
  const totalAlunos = turmas.reduce((acc, t) => acc + t.total_alunos, 0);
  const temAlcance = turmas.some((t) => t.alcance != null);
  const th = TH;

  return (
    <div>
      {voltar}
      {cabecalho}
      {/* Admin Global: Escola → Usuários, mesmo sem turmas/alunos/Lista Piloto. */}
      <AcessoUsuariosDaEscola />

      {turmas.length > 0 && (
        <div className={GRADE_KPI} data-testid="indicadores-da-escola">
          <StatCard icone={<GraduationCap size={20} />} tom="violeta" rotulo="Turmas" valor={numero(turmas.length)} detalhe="no ano letivo ativo" />
          <StatCard icone={<Users size={20} />} tom="azul" rotulo="Alunos" valor={numero(totalAlunos)} detalhe="matriculados e ativos" />
          {temLeitura && (
            <StatCard icone={<Clock size={20} />} tom="violeta" rotulo="Tempo de leitura" valor={tempoEscola.valor} detalhe={tempoEscola.detalhe} />
          )}
          {temMatematica && (
            <StatCard icone={<Calculator size={20} />} tom="teal" rotulo="Atividades Matific" valor={atividadesEscola.valor} detalhe={atividadesEscola.detalhe} />
          )}
        </div>
      )}

      <Card className="p-5 sm:p-6">
        <h2 className="mb-4 flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
          <IconePastel icone={School} tom="violeta" tamanho="sm" />
          Desempenho por turma
        </h2>
        {turmas.length === 0 ? (
          <Vazio icone={GraduationCap} titulo="Nenhuma turma no ano letivo ativo" />
        ) : (
          <>
            <TabelaRolavel rotulo="Desempenho por turma: tabela completa">
              <table className={`${classesTabela.tabela} tabular-nums`}>
                <thead>
                  <tr>
                    <th scope="col" className={`${th} ${PRESA_ESQUERDA_CELULAR}`}>Turma</th>
                    <th scope="col" className={`${th} text-right`}>Alunos</th>
                    {/* No tablet em pé o rótulo quebra em duas linhas, num ponto escolhido. */}
                    <th scope="col" className={th}>Média <span className="block lg:inline">geral</span></th>
                    {temLeitura && (
                      <th scope="col" className={`${th} text-right`}>
                        <span className="inline-flex items-center gap-1"><BookOpen size={13} aria-hidden className="hidden text-indigo-500 lg:block" />Leitura</span>
                      </th>
                    )}
                    {temMatematica && (
                      <th scope="col" className={`${th} text-right`}>
                        <span className="inline-flex items-center gap-1"><Calculator size={13} aria-hidden className="hidden text-teal-600 lg:block" />Matific</span>
                      </th>
                    )}
                    {temAlcance && <th scope="col" className={th} title="Alunos da turma com dado de alguma plataforma contratada">Alcance</th>}
                    {temLeitura && <th scope="col" className={`${th} text-right`}>Livros</th>}
                    {temLeitura && <th scope="col" className={`${th} text-right`}>Tempo</th>}
                    <th scope="col" className={`${th} ${COLUNA_PRESA}`}><span className="sr-only">Detalhes</span></th>
                  </tr>
                </thead>
                <tbody>
                  {turmas.map((item) => (
                    <tr key={item.turma.id} className={classesTabela.tr}>
                      <td className={`${TD} ${PRESA_ESQUERDA_CELULAR}`}>
                        <div className="flex items-center gap-3">
                          <span aria-hidden className="hidden h-9 min-w-9 shrink-0 place-items-center rounded-xl bg-indigo-50 px-2 text-xs font-bold text-indigo-700 min-[1440px]:grid dark:bg-indigo-500/15 dark:text-indigo-300">
                            {(item.turma.ano_escolar || "").slice(0, 3) || "•"}
                          </span>
                          <span className="min-w-0 whitespace-nowrap">
                            {/* Secretaria vê só o agregado por turma — o detalhe da turma
                                (alunos nominais) é PII e fica bloqueado (404 no backend). */}
                            {secretaria ? (
                              <span className="block font-semibold text-zinc-800 dark:text-zinc-100">{item.turma.nome}</span>
                            ) : (
                              <Link to={`/turmas/${item.turma.id}`} className="block font-semibold text-zinc-800 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300">
                                {item.turma.nome}
                              </Link>
                            )}
                            <span className="block text-xs text-zinc-500 dark:text-zinc-400">{item.turma.ano_escolar}</span>
                          </span>
                        </div>
                      </td>
                      <td className={`${TD} text-right text-zinc-700 dark:text-zinc-200`}>{numero(item.total_alunos)}</td>
                      <td className={TD}>
                        <div className="flex items-center gap-2.5 min-[1440px]:min-w-[9rem]">
                          {/* Escala ABSOLUTA 0–100 (a mesma da nota). A barra é desenho
                              (aria-hidden): no tablet em pé sai, e o número fica. */}
                          {item.media_geral != null && (
                            <span className="hidden w-12 shrink-0 lg:block min-[1440px]:w-auto min-[1440px]:flex-1">
                              <BarraProgresso valor={item.media_geral} />
                            </span>
                          )}
                          <span className="font-bold text-zinc-900 dark:text-white">{nota(item.media_geral)}</span>
                        </div>
                      </td>
                      {temLeitura && (
                        <td className={`${TD} text-right`}>
                          <MediaComCobertura media={item.media_elefante} n={item.n_leitura} total={item.total_alunos} oculto={item.oculto?.leitura} />
                        </td>
                      )}
                      {temMatematica && (
                        <td className={`${TD} text-right`}>
                          <MediaComCobertura media={item.media_matific} n={item.n_matematica} total={item.total_alunos} oculto={item.oculto?.matematica} />
                        </td>
                      )}
                      {temAlcance && (
                        <td className={TD}>
                          {item.alcance != null ? (
                            <div className="flex items-center gap-2 min-[1440px]:min-w-[7rem]">
                              <span className="hidden w-10 shrink-0 lg:block min-[1440px]:w-auto min-[1440px]:flex-1">
                                <BarraProgresso valor={item.alcance} tom="teal" />
                              </span>
                              <span className="whitespace-nowrap text-xs font-semibold text-zinc-700 dark:text-zinc-200">{nota(item.alcance)}%</span>
                            </div>
                          ) : "—"}
                        </td>
                      )}
                      {temLeitura && (
                        <td className={`${TD} text-right text-zinc-700 dark:text-zinc-200`}>
                          {item.oculto?.leitura ? <Protegido oculto={item.oculto.leitura} /> : numero(item.indicadores.livros_unicos ?? 0)}
                        </td>
                      )}
                      {temLeitura && (
                        <td className={`${TD} whitespace-nowrap text-right text-zinc-700 dark:text-zinc-200`}>
                          {item.oculto?.leitura ? <Protegido oculto={item.oculto.leitura} /> : tempoLeitura(item.indicadores.tempo_leitura_min ?? 0)}
                        </td>
                      )}
                      <td className={`${TD} text-right ${COLUNA_PRESA}`}>
                        {!secretaria && (
                          <Link to={`/turmas/${item.turma.id}`} className="text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-300">
                            detalhes
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TabelaRolavel>
            <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
              Médias de 0 a 100, só de quem tem dado da plataforma (o “n de N” ao lado). Alcance = alunos da turma
              com dado de alguma plataforma contratada. Retrato atual do ano letivo.
              {algumaProtegida && (
                <> “Protegido”: a turma tem menos de 3 alunos com dado nessa matéria, ou só 1 ou 2 com resultado acima de zero (ou o número dela
                  permitiria descobrir o de outra turma assim); para proteger as crianças, a média e os
                  totais não aparecem.</>
              )}
            </p>
          </>
        )}
      </Card>
      {/* Análise educacional da escola: os indicadores oficiais DELA (com as referências
          da rede), as plataformas por série no período e o que não dá para comparar. O
          professor não chega aqui (RotaGestao) e a seção nem chamaria a API. */}
      <AnaliseDaEscola escolaId={escolaId} />
    </div>
  );
}
