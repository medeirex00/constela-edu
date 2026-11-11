/**
 * VISÃO GERAL ("/") — a tela inicial. O CONTEÚDO muda pelo perfil (despacho abaixo):
 *   - Admin Global → panorama de todas as redes (PanoramaGlobal);
 *   - SEDUC/Secretaria → SEMPRE o Panorama da Rede (rede/secretaria/PanoramaSecretaria),
 *     com ou sem escola no cartão Contexto (a escola escolhida abre a ficha dela);
 *   - gestão da escola (admin/coordenador) e professor → o painel da ESCOLA, na
 *     identidade visual v2 (referência 1 aprovada pelo dono).
 *
 * Painel da escola, de cima para baixo — cada bloco busca o SEU dado e tem o seu
 * esqueleto, o seu vazio e o seu erro com "Tentar de novo" (um bloco com erro não
 * derruba os outros):
 *   1. saudação + o período dos números ("4º bimestre · 2026", vindo da rota);
 *   2. quatro indicadores do bimestre (GET /visao-geral?periodo=bimestre), com a pílula
 *      de variação SÓ quando há o valor anterior real (> 0) — a comparação é a MESMA
 *      quantidade de dias do bimestre anterior (decisão D6); módulo fora do plano some;
 *   3. "Alunos ativos por semana" (GET /atividade-semanal?semanas=8): semana sem coleta
 *      é lacuna, nunca 0; ao lado, o cartão escuro do FIM DO BIMESTRE (calendário
 *      oficial — não existe data de premiação no sistema) com o top 3 real da
 *      premiação do bimestre (GET /premiacoes) e o botão "Gerar certificados" em lote;
 *   4. gestão: "Desempenho por turma" (GET /resumo-escola) e "Destaques recentes"
 *      (GET /gamificacao/mural) — as duas rotas negam o professor (403), então ele vê
 *      no lugar os destaques e alertas que o painel dele já usava (GET /insights);
 *   5. "No ano letivo": o que o painel já mostrava (média geral, totais, Top 5 do
 *      Ranking Geral, selo de frescor e, na gestão, destaques/alertas), mais compacto.
 *
 * Nada aqui calcula pontuação, ranking ou premiação: a tela só formata o que chega.
 * O professor recebe tudo recortado às turmas dele pelo próprio backend.
 */
import {
  AlertTriangle,
  ArrowRight,
  Award,
  BarChart3,
  BookOpen,
  Calculator,
  CalendarDays,
  CheckCircle2,
  Clock3,
  GraduationCap,
  Info,
  Lightbulb,
  Rocket,
  School,
  Sparkles,
  Star,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  lazy,
  Suspense,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { paraData } from "@constela/core";

import GerarCertificados from "../components/GerarCertificados";
import { GraficoSemanal, type SerieSemanal } from "../components/GraficoSemanal";
import { SeloFrescorDaEscola } from "../components/SeloFrescor";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Avatar,
  BarraProgresso,
  Botao,
  Card,
  Carregando,
  Chip,
  ESTILOS_BOTAO,
  Erro,
  IconePastel,
  Medalha,
  PageHeader,
  PosicaoBolinha,
  Skeleton,
  StatCard,
  TAMANHOS_BOTAO,
  Vazio,
  Variacao,
  classesTabela,
  type TomPastel,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi, type ResultadoUseApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import { bimestreEmCurso, useCalendarioBimestres } from "../lib/calendarioBimestres";
import { dataHora, nota, numero, tempoLeitura } from "../lib/formato";
import type { ModeloCertificado } from "../lib/tiposCertificados";
import type {
  AtividadeSemanal,
  ComparacaoVisaoGeral,
  MuralEscola,
  PeriodoVisaoGeral,
  ResumoEscolaPainel,
  ResumoTurmaPainel,
  VisaoGeral,
} from "../lib/tiposVisaoGeral";
import type { Dashboard as DadosDashboard, Premiacoes as DadosPremiacoes } from "../lib/types";

// Panorama da REDE (Secretaria: a página inicial dela, DESENHO3 §2) e o GLOBAL de todas as
// redes (Admin Global). Lazy: mantém o chunk do Dashboard leve para o professor/coordenador
// (que nunca os veem); o de RedeDashboard puxa o Leaflet do mapa.
const PanoramaSecretaria = lazy(() => import("./rede/secretaria/PanoramaSecretaria"));
const PanoramaGlobal = lazy(() =>
  import("./rede/RedeDashboard").then((m) => ({ default: m.PanoramaGlobal })));

/* --- Inteligência (mesmos dados da aba Insights, reaproveitados) ----------- */
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
interface Insights {
  indices: IndiceAluno[];
  alertas: Alerta[];
}

/** Semanas do gráfico (a rota aceita de 1 a 26). */
const SEMANAS_GRAFICO = 8;
/** Turmas mostradas na tabela da Visão Geral (a lista inteira fica em /turmas). */
const LIMITE_TURMAS = 6;
/** Eventos do mural mostrados (o mural completo fica em /conquistas). */
const LIMITE_EVENTOS = 5;
/** Cores das séries do gráfico semanal (identidade v2: Leitura violeta, Matemática teal).
 *  Matemática em teal-600: o teal-500 (#14B8A6) dava 2,49:1 sobre branco, abaixo dos
 *  3:1 de traço (WCAG 1.4.11); o #0D9488 dá 3,74:1 e o marinho da pílula, 4,91:1. */
const COR_LEITURA = "#6C5CE7";
const COR_MATEMATICA = "#0D9488";
/** Grade "conteúdo largo + cartão lateral" (gráfico × premiação; turmas × destaques). O
 *  cartão lateral nunca fica mais estreito que 340 px, para os nomes do pódio caberem. */
const GRADE_COM_CARTAO_LATERAL = "grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(340px,1fr)]";
/** Cartões de KPI: 2 por linha já no celular (números curtos; um por linha deixava meio
 *  cartão vazio e empurrava o gráfico para a 2ª tela). Com número ímpar de cartões, o
 *  último ocupa a linha inteira no celular. Do sm para cima, o mesmo de antes. */
const GRADE_KPI = "grid grid-cols-2 gap-3 sm:gap-5 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2";
/** Coluna da turma presa à ESQUERDA no celular (< 640 px): ao deslizar a tabela, Leitura,
 *  Matific e Adoção passam ao lado do nome da turma. Do sm para cima, célula comum. */
const PRESA_ESQUERDA_CELULAR = "presa-esquerda-celular"; // index.css (irmã da presa-celular)

/* -------------------------------------------------------------------------- */
/* Formatação (só exibição; nenhum número é recalculado aqui)                 */
/* -------------------------------------------------------------------------- */

function primeiroNome(nome: string | null | undefined): string {
  return (nome ?? "").trim().split(/\s+/)[0] ?? "";
}

/** "2026-10-05" → "05/10/2026" (sem passar por `Date`: nada de fuso num dia). */
function dataDoDia(iso: string): string {
  const [ano, mes, dia] = iso.slice(0, 10).split("-");
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : iso;
}

/** "2026-10-05" → "05/10". */
function diaMes(iso: string): string {
  const [, mes, dia] = iso.slice(0, 10).split("-");
  return mes && dia ? `${dia}/${mes}` : iso;
}

/** "4º bimestre (05/10 a 31/12)" → "4º bimestre" (o rótulo vem do backend). */
function nomeDoPeriodo(rotulo: string): string {
  return rotulo.split(" (")[0].trim() || rotulo;
}

/** Chip do cabeçalho: "4º bimestre · 2026". */
function rotuloDoPeriodo(periodo: PeriodoVisaoGeral): string {
  return `${nomeDoPeriodo(periodo.rotulo)} · ${periodo.inicio.slice(0, 4)}`;
}

/** Percentual com 1 casa no máximo: 45.3 → "45,3%". */
function percentual(valor: number): string {
  return `${valor.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

/**
 * Pílula de variação: SÓ com o valor anterior real e maior que zero (sem ele, nada no
 * canto — nunca uma comparação inventada). O texto para leitor de tela diz contra o
 * quê se compara ("em relação ao mesmo ponto do 3º bimestre").
 */
function pilulaVariacao(
  atual: number | null,
  anterior: number | null,
  comparacao: ComparacaoVisaoGeral | null,
): ReactNode | undefined {
  if (atual == null || anterior == null || anterior <= 0 || !comparacao) return undefined;
  const diferenca = ((atual - anterior) / anterior) * 100;
  const sentido = atual > anterior ? "sobe" : atual < anterior ? "desce" : "igual";
  const absoluto = Math.abs(diferenca);
  const texto = absoluto > 0 && absoluto < 0.05
    ? "<0,1%"
    : `${absoluto.toLocaleString("pt-BR", { maximumFractionDigits: absoluto < 10 ? 1 : 0 })}%`;
  return (
    <Variacao sentido={sentido} descricao={`em relação ao ${comparacao.rotulo}`}>
      {texto}
    </Variacao>
  );
}

/**
 * "há 2 h" a partir do horário da API (UTC sem sufixo: `paraData` do pacote
 * compartilhado), com a data completa em Brasília para o `title`.
 */
function tempoRelativo(iso: string, agora: number): { texto: string; completo: string } | null {
  const data = paraData(iso);
  if (Number.isNaN(data.getTime())) return null;
  const minutos = Math.floor((agora - data.getTime()) / 60000);
  let texto: string;
  if (minutos < 1) texto = "agora há pouco";
  else if (minutos < 60) texto = `há ${minutos} min`;
  else if (minutos < 60 * 24) texto = `há ${Math.floor(minutos / 60)} h`;
  else if (minutos < 60 * 48) texto = "ontem";
  else if (minutos < 60 * 24 * 30) texto = `há ${Math.floor(minutos / (60 * 24))} dias`;
  else texto = data.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
  return { texto, completo: dataHora(iso) };
}

/* -------------------------------------------------------------------------- */
/* Peças de layout                                                            */
/* -------------------------------------------------------------------------- */

/** Cabeçalho de bloco: ícone pastel + título (h2/h3) + subtítulo, ação à direita. */
function CabecalhoBloco({
  id,
  icone,
  tom,
  titulo,
  subtitulo,
  acao,
  nivel = "h2",
}: {
  id?: string;
  icone: LucideIcon;
  tom: TomPastel;
  titulo: ReactNode;
  subtitulo?: ReactNode;
  acao?: ReactNode;
  nivel?: "h2" | "h3";
}) {
  const Titulo = nivel;
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 items-start gap-3">
        <IconePastel icone={icone} tom={tom} />
        <div className="min-w-0">
          <Titulo id={id} className="text-[17px] font-semibold leading-tight tracking-tight text-zinc-900 dark:text-white">
            {titulo}
          </Titulo>
          {subtitulo && <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{subtitulo}</p>}
        </div>
      </div>
      {acao && <div className="shrink-0 pt-1">{acao}</div>}
    </div>
  );
}

/** Link discreto "Ver …  →" dos cabeçalhos de bloco. */
function LinkVerMais({ para, children }: { para: string; children: ReactNode }) {
  return (
    <Link
      to={para}
      className="inline-flex items-center gap-1 rounded-lg text-sm font-semibold text-indigo-600 hover:text-indigo-700 hover:underline dark:text-indigo-300"
    >
      {children} <ArrowRight size={15} aria-hidden />
    </Link>
  );
}

/** "sem dado" — ausência dita por extenso, nunca 0. */
function SemDado({ texto = "sem dado" }: { texto?: string }) {
  return <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">{texto}</span>;
}

/* -------------------------------------------------------------------------- */
/* Despacho por perfil                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Dashboard = aba ÚNICA para todos os perfis; o CONTEÚDO muda pelo perfil:
 *   - Admin Global → Panorama Global (todas as redes);
 *   - SEDUC/Secretaria → Panorama da Rede (a rede no Constela, a participação, todas as
 *     escolas com a situação de uso e os destaques, cada um levando ao detalhe);
 *   - professor/coordenador/admin de escola → painel da ESCOLA (abaixo).
 *     O Painel da Rede (/rede) continua existindo (metas, vitrine, mapa e boletim); no
 *     menu, só no do Admin Global.
 */
export default function Dashboard() {
  const { global, secretaria } = usePerfil();
  if (global) {
    return (
      <Suspense fallback={<Carregando texto="Carregando o panorama global..." />}>
        <PanoramaGlobal />
      </Suspense>
    );
  }
  if (secretaria) {
    // SEMPRE o Panorama da Rede (DESENHO3 §1): a escola escolhida no cartão Contexto não
    // troca mais a página inicial — escolher uma escola leva à ficha dela
    // (/rede/escolas/{id}), que substitui o antigo "Panorama Geral da <escola>".
    return (
      <Suspense fallback={<Carregando texto="Carregando o panorama..." />}>
        <PanoramaSecretaria />
      </Suspense>
    );
  }
  return <DashboardEscola />;
}

/* -------------------------------------------------------------------------- */
/* Painel da escola                                                           */
/* -------------------------------------------------------------------------- */

function DashboardEscola() {
  const { escolaId, escolas, selecionarEscola, usuario } = useApp();
  const { gestor } = usePerfil();
  const { dados, erro, carregando, recarregar } = useApi<DadosDashboard>(
    escolaId ? `/escolas/${escolaId}/dashboard` : null);
  // /insights é mais pesado: carrega em paralelo e independente (a página não
  // trava esperando por ele; cada seção mostra seu próprio estado).
  const insights = useApi<Insights>(
    escolaId ? `/escolas/${escolaId}/insights` : null, { timeoutMs: 45000 });
  // Indicadores do bimestre: alimentam os cartões E o chip de período do cabeçalho.
  const visao = useApi<VisaoGeral>(
    escolaId ? `/escolas/${escolaId}/visao-geral?periodo=bimestre` : null, { timeoutMs: 30000 });

  // Quem opera a escola (admin/coordenador, não Secretaria) e ainda não tem
  // NADA cadastrado vê só o "Comece aqui" (o estado vive na escola).
  const podeConfigurar = (Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "")) &&
    !(!usuario?.is_global && usuario?.rede_id != null);
  const precisaConfigurar = podeConfigurar && dados != null &&
    dados.total_turmas === 0 && dados.total_alunos === 0;

  if (!carregando && precisaConfigurar) {
    return <PrimeiroAcesso escolas={escolas} escolaId={escolaId} selecionar={selecionarEscola} />;
  }

  // Aqui só chegam professor e gestão da escola (Secretaria e global foram despachados).
  const professor = !gestor;

  return (
    <div className="space-y-6">
      <CabecalhoVisaoGeral
        nome={usuario?.nome ?? ""}
        professor={professor}
        periodo={visao.dados?.periodo ?? null}
        escolas={escolas}
        escolaId={escolaId}
        selecionar={selecionarEscola}
      />

      {escolaId == null ? (
        <Card>
          <Vazio
            icone={School}
            titulo="Nenhuma escola selecionada"
            descricao="Escolha uma escola no cartão Escola, no fim do menu lateral, para ver a visão geral dela."
          />
        </Card>
      ) : (
        <>
          <IndicadoresDoBimestre estado={visao} />

          <div className={GRADE_COM_CARTAO_LATERAL}>
            <BlocoAtividadeSemanal escolaId={escolaId} />
            <CartaoPremiacao escolaId={escolaId} />
          </div>

          {professor ? (
            <Inteligencia estado={insights} professor />
          ) : (
            /* items-start: cada cartão na sua altura natural. Esticado para igualar o
               vizinho, o de turmas ficava com um vão branco sob a legenda quando a
               escola tem poucas turmas (revisão visual v2). */
            <div className={`${GRADE_COM_CARTAO_LATERAL} items-start`}>
              <DesempenhoPorTurma escolaId={escolaId} />
              <DestaquesRecentes escolaId={escolaId} />
            </div>
          )}

          <NoAnoLetivo
            dados={dados}
            erro={erro}
            carregando={carregando}
            recarregar={recarregar}
            gestor={gestor}
          >
            {!professor && <Inteligencia estado={insights} professor={false} />}
          </NoAnoLetivo>
        </>
      )}
    </div>
  );
}

/** Escola nova (sem turmas nem alunos), vista por quem a configura: só o "Comece aqui". */
function PrimeiroAcesso({ escolas, escolaId, selecionar }: {
  escolas: { id: number; nome: string }[];
  escolaId: number | null;
  selecionar: (id: number) => void;
}) {
  return (
    <div className="mx-auto flex min-h-[62vh] max-w-lg flex-col items-center justify-center gap-6 text-center">
      {escolas.length > 1 && (
        <select
          aria-label="Selecionar escola"
          className="w-full max-w-xs rounded-full border border-zinc-200/80 bg-white px-4 py-2.5 text-center text-sm font-semibold shadow-cartao dark:border-zinc-700 dark:bg-zinc-900"
          value={escolaId ?? ""}
          onChange={(evento) => selecionar(Number(evento.target.value))}
        >
          {escolas.map((escola) => (
            <option key={escola.id} value={escola.id}>{escola.nome}</option>
          ))}
        </select>
      )}
      <span aria-hidden className="grid h-20 w-20 place-items-center rounded-3xl bg-indigo-50 text-indigo-600 shadow-cartao dark:bg-indigo-500/15 dark:text-indigo-300">
        <Rocket size={38} />
      </span>
      <div className="space-y-2">
        <h1 className="text-[28px] font-bold leading-tight tracking-tight text-zinc-900 dark:text-white">
          Bem-vindo(a) ao Constela Edu
        </h1>
        <p className="text-zinc-500 dark:text-zinc-400">
          Vamos deixar sua escola pronta em poucos minutos: turmas, alunos e as plataformas
          conectadas. É só clicar para começar.
        </p>
      </div>
      <Link
        to="/comecar"
        className={`inline-flex items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.lg} ${ESTILOS_BOTAO.primario}`}
      >
        Comece aqui <ArrowRight size={18} aria-hidden />
      </Link>
    </div>
  );
}

/* --- 1. Cabeçalho ------------------------------------------------------------ */

/** "Olá, <primeiro nome>", o subtítulo do bimestre e o período dos números (chip
 *  INFORMATIVO, não é um seletor). O seletor de escola só aparece com mais de uma. */
function CabecalhoVisaoGeral({ nome, professor, periodo, escolas, escolaId, selecionar }: {
  nome: string;
  professor: boolean;
  periodo: PeriodoVisaoGeral | null;
  escolas: { id: number; nome: string }[];
  escolaId: number | null;
  selecionar: (id: number) => void;
}) {
  const primeiro = primeiroNome(nome);
  const temAcoes = periodo != null || escolas.length > 1;
  return (
    <PageHeader
      titulo={<>{primeiro ? `Olá, ${primeiro}` : "Olá"} <span aria-hidden>👋</span></>}
      descricao={professor
        ? "Acompanhe a leitura e a matemática das suas turmas neste bimestre."
        : "Acompanhe a leitura e a matemática da escola neste bimestre."}
      acoes={temAcoes ? (
        <>
          {periodo && (
            <span
              className="inline-flex items-center gap-2 rounded-full border border-zinc-200/80 bg-white px-4 py-2 text-sm font-semibold text-zinc-800 shadow-cartao dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              title={`Os números desta tela são do período de ${dataDoDia(periodo.inicio)} a ${dataDoDia(periodo.fim)}.`}
            >
              <CalendarDays size={16} aria-hidden className="text-indigo-600 dark:text-indigo-300" />
              <span className="sr-only">Período: </span>
              {rotuloDoPeriodo(periodo)}
            </span>
          )}
          {escolas.length > 1 && (
            <label className="relative inline-flex items-center">
              <School size={15} aria-hidden className="pointer-events-none absolute left-3.5 text-zinc-500" />
              <select
                aria-label="Escola selecionada"
                className="max-w-[240px] truncate rounded-full border border-zinc-200/80 bg-white py-2 pl-9 pr-4 text-sm font-semibold text-zinc-800 shadow-cartao dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                value={escolaId ?? ""}
                onChange={(e) => selecionar(Number(e.target.value))}
              >
                {escolas.map((escola) => (
                  <option key={escola.id} value={escola.id}>{escola.nome}</option>
                ))}
              </select>
            </label>
          )}
        </>
      ) : undefined}
    />
  );
}

/* --- 2. Indicadores do bimestre -------------------------------------------- */

/** Aviso de cobertura sob o detalhe de um cartão (âmbar, com o ícone de informação). */
function NotaCobertura({ children }: { children: ReactNode }) {
  return (
    <span className="mt-0.5 flex items-start gap-1 text-ouro-700 dark:text-ouro-300">
      <Info size={12} aria-hidden className="mt-[3px] shrink-0" />
      <span>{children}</span>
    </span>
  );
}

function IndicadoresDoBimestre({ estado }: { estado: ResultadoUseApi<VisaoGeral> }) {
  const { dados, erro, carregando, recarregar } = estado;
  const idTitulo = useId();

  if (carregando) {
    return (
      <section aria-labelledby={idTitulo}>
        <h2 id={idTitulo} className="sr-only">Números do bimestre</h2>
        <span className="sr-only">Carregando os números do bimestre...</span>
        <div className={`${GRADE_KPI} xl:grid-cols-4`} aria-hidden>
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[156px] rounded-cartao" />)}
        </div>
      </section>
    );
  }
  if (erro) {
    return (
      <section aria-labelledby={idTitulo}>
        <h2 id={idTitulo} className="sr-only">Números do bimestre</h2>
        <Card>
          <Erro
            titulo="Não foi possível carregar os números do bimestre"
            descricao={erro.message}
            aoTentar={recarregar}
          />
        </Card>
      </section>
    );
  }
  if (!dados) return null;

  const { periodo, comparacao, alunos, leitura, matematica } = dados;
  const nome = nomeDoPeriodo(periodo.rotulo);
  const porPlataforma = [
    leitura.contratado && alunos.ativos_leitura != null ? `${numero(alunos.ativos_leitura)} na leitura` : null,
    matematica.contratado && alunos.ativos_matematica != null ? `${numero(alunos.ativos_matematica)} no Matific` : null,
  ].filter(Boolean);
  // Leitura parada no meio do período: o número dos cartões de Leitura conta só até o
  // último dia coletado — a tela diz até quando, para não passar por total do bimestre.
  const leituraParcial = leitura.contratado && leitura.cobertura === "parcial";
  const ateLeitura = leitura.coletado_ate ? diaMes(leitura.coletado_ate) : null;
  const notaParcialLeitura = leituraParcial && (
    <NotaCobertura>
      {ateLeitura
        ? `Cobertura parcial: o Elefante Letrado foi coletado até ${ateLeitura}; o número conta só até essa data.`
        : "Cobertura parcial: parte do período ainda não foi coletada pelo Elefante Letrado."}
    </NotaCobertura>
  );

  const cartoes: ReactNode[] = [
    <StatCard
      key="ativos"
      icone={<Users size={20} />}
      tom="violeta"
      rotulo="Alunos ativos"
      valor={alunos.ativos == null ? "—" : numero(alunos.ativos)}
      detalhe={
        <>
          {alunos.ativos == null && <span className="block">sem coleta no bimestre</span>}
          <span className="block">de {numero(alunos.total)} alunos</span>
          {porPlataforma.length > 0 && <span className="block">{porPlataforma.join(" · ")}</span>}
          {/* Este cartão soma leitores até o último dia coletado da Leitura com ativos do
              Matific até hoje: se a Leitura parou, diz até quando ela conta. */}
          {leituraParcial && alunos.ativos != null && (
            <NotaCobertura>
              {`Cobertura parcial: na leitura, contado até ${ateLeitura ?? "a última coleta"}`}
              {matematica.contratado && matematica.cobertura === "parcial"
                ? "; no Matific, parte do período ou dos alunos ainda não foi coletada."
                : "."}
            </NotaCobertura>
          )}
        </>
      }
      variacao={pilulaVariacao(alunos.ativos, alunos.ativos_anterior, comparacao)}
    />,
  ];
  if (leitura.contratado) {
    cartoes.push(
      <StatCard
        key="livros"
        icone={<BookOpen size={20} />}
        tom="azul"
        rotulo="Livros lidos no bimestre"
        valor={leitura.livros == null ? "—" : numero(leitura.livros)}
        detalhe={leitura.livros == null ? "sem coleta do Elefante Letrado no bimestre" : (
          <>
            <span className="block">livros novos no Elefante Letrado</span>
            {notaParcialLeitura}
          </>
        )}
        variacao={pilulaVariacao(leitura.livros, leitura.livros_anterior, comparacao)}
      />,
      <StatCard
        key="horas"
        icone={<Clock3 size={20} />}
        tom="rosa"
        rotulo="Horas de leitura"
        valor={leitura.tempo_min == null ? "—" : tempoLeitura(leitura.tempo_min)}
        detalhe={leitura.tempo_min == null ? "sem coleta do Elefante Letrado no bimestre" : (
          <>
            <span className="block">tempo registrado no Elefante Letrado</span>
            {notaParcialLeitura}
          </>
        )}
        variacao={pilulaVariacao(leitura.tempo_min, leitura.tempo_min_anterior, comparacao)}
      />,
    );
  }
  if (matematica.contratado) {
    cartoes.push(
      <StatCard
        key="atividades"
        icone={<Calculator size={20} />}
        tom="teal"
        rotulo="Atividades no Matific"
        valor={matematica.atividades == null ? "—" : numero(matematica.atividades)}
        detalhe={
          matematica.atividades == null ? (
            "sem coleta do Matific no bimestre"
          ) : (
            <>
              <span className="block">concluídas no bimestre</span>
              {/* "parcial" tem quatro causas no backend (coleta que começou depois
                  do início, aluno que deixou de ser coletado, coleta parada, base de
                  algum aluno bem anterior ao início): o texto vale para todas, sem
                  afirmar uma só. */}
              {matematica.cobertura === "parcial" && (
                <NotaCobertura>
                  Cobertura parcial: parte do período ou dos alunos ainda não foi coletada pelo Matific.
                </NotaCobertura>
              )}
            </>
          )
        }
        variacao={pilulaVariacao(matematica.atividades, matematica.atividades_anterior, comparacao)}
      />,
    );
  }
  const colunas = cartoes.length >= 4 ? "xl:grid-cols-4" : cartoes.length === 3 ? "xl:grid-cols-3" : "";

  return (
    <section aria-labelledby={idTitulo}>
      <h2 id={idTitulo} className="sr-only">Números do {nome}</h2>
      <div className={`${GRADE_KPI} ${colunas}`} data-testid="indicadores-do-bimestre">{cartoes}</div>
      <p className="mt-3 flex flex-wrap gap-x-2 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
        <span>
          {nome}: dia {numero(periodo.dias_decorridos)} de {numero(periodo.dias_total)} ({diaMes(periodo.inicio)} a{" "}
          {diaMes(periodo.fim)}).
        </span>
        <span>
          {comparacao
            ? `Variação em relação ao ${comparacao.rotulo} (${diaMes(comparacao.inicio)} a ${diaMes(comparacao.fim)}; na Leitura, até o último dia já coletado), quando as duas janelas têm dado.`
            : "Sem comparação com o período anterior."}
        </span>
        {dados.atualizado_em && <span>Coletas consideradas até {dataHora(dados.atualizado_em)}.</span>}
      </p>
    </section>
  );
}

/* --- 3a. Gráfico semanal --------------------------------------------------- */

function BlocoAtividadeSemanal({ escolaId }: { escolaId: number }) {
  const idTitulo = useId();
  const { dados, erro, carregando, recarregar } = useApi<AtividadeSemanal>(
    `/escolas/${escolaId}/atividade-semanal?semanas=${SEMANAS_GRAFICO}`, { timeoutMs: 30000 });

  const series: SerieSemanal[] = [];
  if (dados?.leitura_contratado) {
    series.push({
      nome: "Leitura · Elefante Letrado",
      cor: COR_LEITURA,
      valores: dados.semanas.map((s) => s.leitura_pct),
      alunos: dados.semanas.map((s) => s.leitura_alunos),
      area: true,
    });
  }
  if (dados?.matematica_contratado) {
    series.push({
      nome: "Matemática · Matific",
      cor: COR_MATEMATICA,
      corTexto: "#10122A",
      valores: dados.semanas.map((s) => s.matematica_pct),
      alunos: dados.semanas.map((s) => s.matematica_alunos),
    });
  }
  const temPonto = series.some((serie) => serie.valores.some((v) => v != null));

  let corpo: ReactNode;
  if (carregando) {
    corpo = (
      <>
        <span className="sr-only">Carregando o gráfico...</span>
        <Skeleton className="mt-6 h-[260px] rounded-2xl" />
      </>
    );
  } else if (erro) {
    corpo = <Erro titulo="Não foi possível carregar o gráfico semanal" descricao={erro.message} aoTentar={recarregar} />;
  } else if (!dados) {
    corpo = null;
  } else if (series.length === 0) {
    corpo = (
      <Vazio
        icone={BarChart3}
        titulo="Nenhuma plataforma contratada para medir"
        descricao="O gráfico mostra o Elefante Letrado e o Matific, quando fazem parte do plano."
      />
    );
  } else if (dados.denominador === 0) {
    corpo = (
      <Vazio
        icone={Users}
        titulo="Nenhum aluno ativo matriculado no ano letivo"
        descricao="Sem alunos na base, não há percentual a mostrar."
      />
    );
  } else if (!temPonto) {
    corpo = (
      <Vazio
        icone={BarChart3}
        titulo={`Ainda não há coleta nas últimas ${SEMANAS_GRAFICO} semanas`}
        descricao="Quando o Elefante Letrado ou o Matific forem coletados, a participação de cada semana aparece aqui."
      />
    );
  } else {
    corpo = (
      <div className="mt-5">
        <GraficoSemanal semanas={dados.semanas} series={series} titulo="Alunos ativos por semana" altura={300} />
      </div>
    );
  }

  return (
    <Card className="flex min-w-0 flex-col p-5 sm:p-6">
      <section aria-labelledby={idTitulo} className="flex flex-1 flex-col">
        <CabecalhoBloco
          id={idTitulo}
          icone={TrendingUp}
          tom="violeta"
          titulo="Alunos ativos por semana"
          subtitulo={dados && dados.denominador > 0
            ? `% dos alunos (de ${numero(dados.denominador)}) que usaram cada plataforma`
            : "% dos alunos que usaram cada plataforma"}
          acao={
            <span className="inline-flex items-center rounded-full bg-zinc-100 px-3 py-1 text-xs font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              Últimas {SEMANAS_GRAFICO} semanas
            </span>
          }
        />
        <div className="flex flex-1 flex-col justify-center">{corpo}</div>
        {dados && temPonto && !carregando && !erro && (
          <div className="mt-4 space-y-2 border-t border-zinc-100 pt-3 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            <p>A semana atual ainda está em curso: o número dela pode crescer até domingo.</p>
            <details className="group">
              <summary className="cursor-pointer select-none font-semibold text-indigo-600 hover:text-indigo-700 dark:text-indigo-300">
                Como contamos
              </summary>
              <p className="mt-1.5 leading-relaxed">{dados.observacao}</p>
            </details>
          </div>
        )}
      </section>
    </Card>
  );
}

/* --- 3b. Cartão escuro: fim do bimestre + top 3 + certificados -------------- */

type AbaPremiacao = "leitura" | "matematica";

const ABAS_PREMIACAO: Record<AbaPremiacao, { rotulo: string; categoria: string; modelo: ModeloCertificado }> = {
  leitura: { rotulo: "Leitura", categoria: "melhor_leitor", modelo: "elefante" },
  matematica: { rotulo: "Matemática", categoria: "melhor_matematica", modelo: "matific" },
};

/** Valor do pódio com a UNIDADE real (a mesma formatação da tela de Premiações). */
function valorDoPodio(valor: number | null, unidade: string): { numero: string; unidade: string } {
  if (valor == null) return { numero: "—", unidade: "índice oculto" };
  if (unidade === "min") return { numero: tempoLeitura(valor), unidade: "de leitura" };
  if (unidade === "estrelas/atividade") {
    return {
      numero: valor.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      unidade,
    };
  }
  return { numero: numero(valor), unidade };
}

/** "31/12/2026" a partir do `Date` UTC do calendário oficial. */
function dataDoCalendario(data: Date): string {
  const dois = (n: number) => String(n).padStart(2, "0");
  return `${dois(data.getUTCDate())}/${dois(data.getUTCMonth() + 1)}/${data.getUTCFullYear()}`;
}

/** Abas pequenas sobre o fundo escuro (o mesmo comportamento acessível de `Abas`). */
function AbasNoEscuro<T extends string>({ itens, valor, aoMudar, rotulo, idPainel }: {
  itens: { valor: T; rotulo: string }[];
  valor: T;
  aoMudar: (valor: T) => void;
  rotulo: string;
  idPainel: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const aoTecla = (evento: ReactKeyboardEvent<HTMLButtonElement>, indice: number) => {
    let alvo = -1;
    if (evento.key === "ArrowRight") alvo = (indice + 1) % itens.length;
    else if (evento.key === "ArrowLeft") alvo = (indice - 1 + itens.length) % itens.length;
    else if (evento.key === "Home") alvo = 0;
    else if (evento.key === "End") alvo = itens.length - 1;
    if (alvo < 0) return;
    evento.preventDefault();
    aoMudar(itens[alvo].valor);
    refs.current[alvo]?.focus();
  };
  return (
    <div role="tablist" aria-label={rotulo} className="inline-flex gap-1 rounded-xl bg-white/10 p-1">
      {itens.map((item, i) => {
        const ativa = item.valor === valor;
        return (
          <button
            key={item.valor}
            ref={(el) => {
              refs.current[i] = el;
            }}
            id={`${idPainel}-aba-${item.valor}`}
            type="button"
            role="tab"
            aria-selected={ativa}
            aria-controls={idPainel}
            tabIndex={ativa ? 0 : -1}
            onClick={() => aoMudar(item.valor)}
            onKeyDown={(e) => aoTecla(e, i)}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ouro-300 ${
              ativa ? "bg-white text-marinho-900 shadow" : "text-marinho-200 hover:bg-white/10 hover:text-white"
            }`}
          >
            {item.rotulo}
          </button>
        );
      })}
    </div>
  );
}

function CartaoPremiacao({ escolaId }: { escolaId: number }) {
  const { leitura, matematica } = useModulos();
  const idTitulo = useId();
  const idPainel = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const { dados, erro, carregando, recarregar } = useApi<DadosPremiacoes>(
    `/escolas/${escolaId}/premiacoes?periodo=bimestre&limite=3`, { timeoutMs: 30000 });
  const [abaEscolhida, setAbaEscolhida] = useState<AbaPremiacao>("leitura");
  const [aberto, setAberto] = useState(false);

  const abas = ([leitura ? "leitura" : null, matematica ? "matematica" : null]
    .filter(Boolean)) as AbaPremiacao[];
  const aba: AbaPremiacao | undefined = abas.includes(abaEscolhida) ? abaEscolhida : abas[0];
  const categoria = aba ? dados?.categorias.find((c) => c.chave === ABAS_PREMIACAO[aba].categoria) : undefined;
  const podio = (categoria?.podio ?? []).slice(0, 3);
  const indiceOculto = podio.some((item) => item.valor == null);

  // Calendário oficial do backend: em 2027 (fora da cópia de 2026 da web) a contagem
  // vem do ano cadastrado lá, em vez de sumir.
  const calendario = useCalendarioBimestres(escolaId);
  const bimestre = bimestreEmCurso(new Date(), calendario);
  const contagem = bimestre == null
    ? null
    : bimestre.diasParaOFim === 0
      ? "termina hoje"
      : bimestre.diasParaOFim === 1 ? "em 1 dia" : `em ${numero(bimestre.diasParaOFim)} dias`;
  const nomeBimestre = dados?.periodo?.rotulo
    ? nomeDoPeriodo(dados.periodo.rotulo)
    : bimestre ? `${bimestre.numero}º bimestre` : "bimestre";

  let corpo: ReactNode;
  if (carregando) {
    corpo = (
      <div className="mt-4 space-y-2.5" aria-hidden>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-14 animate-pulse rounded-2xl bg-white/10 motion-reduce:animate-none" />
        ))}
      </div>
    );
  } else if (erro) {
    corpo = (
      <div role="alert" className="mt-4 rounded-2xl bg-white/[0.06] p-4 text-center">
        <p className="text-sm font-semibold text-white">Não foi possível carregar a premiação</p>
        <p className="mt-1 text-xs text-marinho-200">{erro.message}</p>
        <Botao variante="secundario" tamanho="sm" className="mt-3" onClick={recarregar}>
          Tentar de novo
        </Botao>
      </div>
    );
  } else if (!aba) {
    corpo = (
      <p className="mt-4 text-sm text-marinho-200">
        Nenhum módulo de leitura ou matemática no plano desta rede.
      </p>
    );
  } else if (podio.length === 0) {
    corpo = (
      <p className="mt-4 rounded-2xl bg-white/[0.06] px-4 py-5 text-center text-sm text-marinho-200">
        Ninguém pontuou nesta categoria no bimestre até agora.
      </p>
    );
  } else {
    corpo = (
      <>
        <ol aria-label={`Top 3 · ${categoria?.titulo ?? ABAS_PREMIACAO[aba].rotulo}`} className="mt-4 space-y-2.5">
          {podio.map((item) => {
            const valor = valorDoPodio(item.valor, categoria?.unidade ?? "");
            return (
              <li key={item.aluno_id} className="flex items-center gap-3 rounded-2xl bg-white/[0.06] px-3 py-2.5">
                {item.posicao >= 1 && item.posicao <= 3
                  ? <Medalha posicao={item.posicao as 1 | 2 | 3} tamanho={26} />
                  : <PosicaoBolinha posicao={item.posicao} />}
                <Avatar nome={item.nome} chave={item.aluno_id} tamanho="sm" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold leading-snug text-white [overflow-wrap:anywhere]">{item.nome}</p>
                  {item.turma && <p className="truncate text-xs text-marinho-300" title={item.turma}>{item.turma}</p>}
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-[15px] font-bold leading-tight tabular-nums text-ouro-300">{valor.numero}</p>
                  <p className="text-[11px] text-marinho-300">{valor.unidade}</p>
                </div>
              </li>
            );
          })}
        </ol>
        {indiceOculto && (
          <p className="mt-2.5 text-xs leading-relaxed text-marinho-200">
            Índice não exibido: poucos alunos fizeram atividade no bimestre, e com tão poucos ele
            revelaria o resultado de uma criança. A ordem é a mesma.
          </p>
        )}
      </>
    );
  }

  return (
    <>
      <section
        aria-labelledby={idTitulo}
        className="relative isolate flex min-w-0 flex-col overflow-hidden rounded-cartao bg-marinho-900 p-5 shadow-cartao sm:p-6 dark:bg-marinho-950 dark:ring-1 dark:ring-white/10"
      >
        {/* Brilho decorativo (identidade v2): violeta no canto, estrelinhas âmbar. */}
        <span aria-hidden className="pointer-events-none absolute -right-20 -top-24 -z-10 h-56 w-56 rounded-full bg-indigo-600/45 blur-3xl" />
        <span aria-hidden className="pointer-events-none absolute -bottom-24 -left-16 -z-10 h-48 w-48 rounded-full bg-ouro-400/10 blur-3xl" />

        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id={idTitulo} className="text-[11px] font-semibold uppercase tracking-[0.08em] text-marinho-200">
              {bimestre ? `Fim do ${bimestre.numero}º bimestre` : "Premiação do bimestre"}
            </h2>
            {bimestre ? (
              <>
                <p className="mt-2 text-[32px] font-bold leading-none tracking-tight text-white">{contagem}</p>
                <p className="mt-1.5 text-sm text-marinho-200">
                  {dataDoCalendario(bimestre.fim)} · calendário oficial
                </p>
              </>
            ) : (
              <p className="mt-2 text-sm text-marinho-200">Fora do calendário de bimestres: sem data oficial de fim.</p>
            )}
          </div>
          <span aria-hidden className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-ouro-400 text-marinho-900 shadow-ambar">
            <Trophy size={22} />
          </span>
        </div>

        <div className="mt-5 border-t border-white/10 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-white">Top 3 do bimestre</p>
            {abas.length > 1 && aba ? (
              <AbasNoEscuro
                itens={abas.map((valor) => ({ valor, rotulo: ABAS_PREMIACAO[valor].rotulo }))}
                valor={aba}
                aoMudar={setAbaEscolhida}
                rotulo="Categoria da premiação"
                idPainel={idPainel}
              />
            ) : aba ? (
              <span className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-semibold text-marinho-200">
                {ABAS_PREMIACAO[aba].rotulo}
              </span>
            ) : null}
          </div>
          <div
            id={idPainel}
            {...(abas.length > 1 && aba ? { role: "tabpanel", "aria-labelledby": `${idPainel}-aba-${aba}` } : {})}
          >
            {categoria && !carregando && !erro && (
              <p className="mt-2 text-xs text-marinho-300">
                {categoria.titulo} · {categoria.descricao.replace(/ no período$/, "")} no bimestre
              </p>
            )}
            {corpo}
          </div>
        </div>

        <div className="mt-auto pt-5">
          <Botao
            variante="ambar"
            tamanho="lg"
            className="w-full"
            onClick={() => setAberto(true)}
            disabled={!aba || podio.length === 0 || carregando || Boolean(erro)}
          >
            <Award size={18} aria-hidden /> Gerar certificados
          </Botao>
          <div className="mt-3 text-center">
            <Link
              to="/premiacoes"
              className="inline-flex items-center gap-1 rounded-lg text-sm font-semibold text-marinho-200 hover:text-white"
            >
              Ver todas as premiações <ArrowRight size={14} aria-hidden />
            </Link>
          </div>
        </div>
      </section>

      {aba && (
        <GerarCertificados
          escolaId={escolaId}
          alunos={podio.map((item) => ({
            aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
          }))}
          modeloInicial={ABAS_PREMIACAO[aba].modelo}
          contexto={`Visão geral · ${categoria?.titulo ?? ABAS_PREMIACAO[aba].rotulo} · ${nomeBimestre}`}
          aberto={aberto}
          aoFechar={() => setAberto(false)}
        />
      )}
    </>
  );
}

/* --- 4a. Desempenho por turma (gestão) ------------------------------------- */

/** Sem retrato do Elefante na turma: "sem dado", nunca 0 livros / 0 min. */
function semDadoLeitura(turma: ResumoTurmaPainel): boolean {
  if (turma.adocao_leitura != null) return turma.adocao_leitura === 0;
  return turma.n_leitura === 0 && !turma.indicadores.livros_unicos && !turma.indicadores.tempo_leitura_min;
}

/** Estrelas por atividade no ano letivo (as duas somas vêm do backend; aqui só a razão). */
function MatificDaTurma({ turma }: { turma: ResumoTurmaPainel }) {
  const atividades = turma.indicadores.atividades ?? 0;
  const estrelas = turma.indicadores.estrelas ?? 0;
  if (atividades > 0) {
    return (
      <span className="font-semibold text-zinc-800 dark:text-zinc-100">
        {(estrelas / atividades).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </span>
    );
  }
  return <SemDado texto={turma.n_matematica === 0 ? "sem dado" : "sem atividade"} />;
}

function SubTitulo({ children }: { children: ReactNode }) {
  return (
    <span className="mt-0.5 block text-[10px] font-medium normal-case tracking-normal text-zinc-500 dark:text-zinc-400">
      {children}
    </span>
  );
}

function DesempenhoPorTurma({ escolaId }: { escolaId: number }) {
  const idTitulo = useId();
  const { leitura, matematica } = useModulos();
  const { dados, erro, carregando, recarregar } = useApi<ResumoEscolaPainel>(
    `/escolas/${escolaId}/resumo-escola`, { timeoutMs: 30000 });
  const turmas = dados?.turmas ?? [];
  const visiveis = turmas.slice(0, LIMITE_TURMAS);
  const th = classesTabela.th;

  let corpo: ReactNode;
  if (carregando) {
    corpo = (
      <div className="mt-5 space-y-3" aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-10" />)}
      </div>
    );
  } else if (erro) {
    corpo = <Erro titulo="Não foi possível carregar as turmas" descricao={erro.message} aoTentar={recarregar} />;
  } else if (!dados) {
    corpo = null;
  } else if (turmas.length === 0) {
    corpo = <Vazio icone={GraduationCap} titulo="Nenhuma turma no ano letivo ativo" />;
  } else {
    corpo = (
      <>
        {/* No celular a tabela rola de lado dentro do cartão, com o aviso "Deslize..." em
            cima e a turma presa à esquerda: Leitura, Matific e Adoção passam ao lado dela. */}
        <TabelaRolavel rotulo="Desempenho por turma: tabela completa" className="-mx-5 mt-4 sm:-mx-6">
          <table className={`${classesTabela.tabela} tabular-nums`}>
            {/* As turmas são as do ano letivo ativo; os números de leitura, não (ver o
                rodapé): por isso "turma DO ano letivo", e não "desempenho NO ano". */}
            <caption className="sr-only">
              Desempenho por turma do ano letivo{turmas.length > visiveis.length
                ? ` (as ${visiveis.length} primeiras de ${turmas.length})` : ""}
            </caption>
            <thead>
              <tr>
                <th scope="col" className={`${th} pl-5 sm:pl-6 ${PRESA_ESQUERDA_CELULAR}`}>Turma</th>
                <th scope="col" className={`${th} text-right`}>Alunos</th>
                {/* O contador do Elefante é VITALÍCIO (último retrato, sem recorte de
                    ano): "acumulado", nunca "no ano". */}
                {leitura && <th scope="col" className={`${th} text-right`}>Livros<SubTitulo>acumulado</SubTitulo></th>}
                {leitura && <th scope="col" className={`${th} text-right`}>Leitura<SubTitulo>tempo acumulado</SubTitulo></th>}
                {matematica && (
                  <th scope="col" className={`${th} text-right`}>Matific<SubTitulo>estrelas/atividade</SubTitulo></th>
                )}
                <th scope="col" className={`${th} pr-5 sm:pr-6`}>Adoção<SubTitulo>% com dado</SubTitulo></th>
              </tr>
            </thead>
            <tbody>
              {visiveis.map((item) => {
                const semLeitura = semDadoLeitura(item);
                const adocao = item.adocao ?? item.alcance;
                return (
                  <tr key={item.turma.id} className={classesTabela.tr}>
                    <td className={`py-3 pl-5 pr-4 sm:pl-6 ${PRESA_ESQUERDA_CELULAR}`}>
                      <Link
                        to={`/turmas/${item.turma.id}`}
                        className="inline-flex max-w-[11rem] truncate rounded-lg bg-zinc-100 px-2.5 py-1 text-xs font-semibold max-sm:max-w-[8.5rem] text-zinc-800 transition-colors hover:bg-indigo-50 hover:text-indigo-700 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-indigo-500/15 dark:hover:text-indigo-200"
                       title={item.turma.nome}>
                        {item.turma.nome}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-right text-zinc-700 dark:text-zinc-200">{numero(item.total_alunos)}</td>
                    {leitura && (
                      <td className="px-4 py-3 text-right text-zinc-700 dark:text-zinc-200">
                        {semLeitura ? <SemDado /> : numero(item.indicadores.livros_unicos ?? 0)}
                      </td>
                    )}
                    {leitura && (
                      <td className="whitespace-nowrap px-4 py-3 text-right text-zinc-700 dark:text-zinc-200">
                        {semLeitura ? <SemDado /> : tempoLeitura(item.indicadores.tempo_leitura_min ?? 0)}
                      </td>
                    )}
                    {matematica && (
                      <td className="px-4 py-3 text-right"><MatificDaTurma turma={item} /></td>
                    )}
                    <td className="py-3 pl-4 pr-5 sm:pr-6">
                      {adocao == null ? (
                        <SemDado />
                      ) : (
                        <div className="flex min-w-[8.5rem] items-center gap-2.5">
                          <BarraProgresso valor={adocao} className="w-20" />
                          <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">{percentual(adocao)}</span>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TabelaRolavel>
        {/* Cada plataforma com o seu acumulado: o Elefante desde o início (contador
            vitalício), o Matific no ano letivo (contador do ano). */}
        <p className="mt-4 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
          {leitura && "Leitura: acumulado desde o início no Elefante Letrado. "}
          {matematica && "Matific: estrelas ganhas por atividade concluída, acumuladas no ano letivo. "}
          Valores pela última coleta de cada aluno. Adoção: média, entre as plataformas contratadas, da % de
          alunos da turma com dado.
        </p>
      </>
    );
  }

  return (
    <Card className="flex min-w-0 flex-col p-5 sm:p-6">
      <section aria-labelledby={idTitulo}>
        <CabecalhoBloco
          id={idTitulo}
          icone={School}
          tom="azul"
          titulo="Desempenho por turma"
          subtitulo="Leitura e matemática de cada turma do ano letivo"
          acao={turmas.length > 0 && !carregando && !erro
            ? <LinkVerMais para="/turmas">{turmas.length === 1 ? "Ver a turma" : `Ver as ${numero(turmas.length)} turmas`}</LinkVerMais>
            : undefined}
        />
        {corpo}
      </section>
    </Card>
  );
}

/* --- 4b. Destaques recentes (mural da gestão) ------------------------------ */

const TONS_EVENTO = [
  "bg-indigo-50 dark:bg-indigo-500/15",
  "bg-teal-50 dark:bg-teal-500/15",
  "bg-ouro-50 dark:bg-ouro-400/15",
  "bg-rose-50 dark:bg-rose-500/15",
  "bg-sky-50 dark:bg-sky-500/15",
];

function DestaquesRecentes({ escolaId }: { escolaId: number }) {
  const idTitulo = useId();
  const { dados, erro, carregando, recarregar } = useApi<MuralEscola>(
    `/escolas/${escolaId}/gamificacao/mural`, { timeoutMs: 45000 });
  const eventos = (dados?.eventos ?? []).slice(0, LIMITE_EVENTOS);
  const agora = Date.now();

  let corpo: ReactNode;
  if (carregando) {
    corpo = (
      <div className="mt-5 space-y-4" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-xl" />
            <Skeleton className="h-4 flex-1" />
          </div>
        ))}
      </div>
    );
  } else if (erro) {
    corpo = <Erro titulo="Não foi possível carregar os destaques" descricao={erro.message} aoTentar={recarregar} />;
  } else if (!dados) {
    corpo = null;
  } else if (eventos.length === 0) {
    corpo = (
      <Vazio
        icone={Sparkles}
        titulo="Nenhuma conquista nos últimos 30 dias"
        descricao="As conquistas desbloqueadas pelos alunos aparecem aqui depois de cada coleta."
      />
    );
  } else {
    corpo = (
      <>
        <ul className="mt-5 space-y-4">
          {eventos.map((evento, i) => {
            const quando = tempoRelativo(evento.data, agora);
            return (
              <li key={`${evento.data}-${i}`} className="flex items-start gap-3">
                <span aria-hidden className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-lg ${TONS_EVENTO[i % TONS_EVENTO.length]}`}>
                  {evento.icone || "🏅"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium leading-snug text-zinc-800 dark:text-zinc-100">{evento.texto}</p>
                  {quando && (
                    <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                      registrado <time dateTime={evento.data} title={`Dado de ${quando.completo}`}>{quando.texto}</time>
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="mt-auto space-y-3 pt-5">
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            A data é a do dado em que a conquista apareceu (numa coleta por período, o fim do período), não o momento exato na plataforma.
          </p>
          <LinkVerMais para="/conquistas">Ver o mural de conquistas</LinkVerMais>
        </div>
      </>
    );
  }

  return (
    <Card className="flex min-w-0 flex-col p-5 sm:p-6">
      <section aria-labelledby={idTitulo} className="flex flex-1 flex-col">
        <CabecalhoBloco
          id={idTitulo}
          icone={Sparkles}
          tom="ambar"
          titulo="Destaques recentes"
          subtitulo="Conquistas dos últimos 30 dias"
        />
        {corpo}
      </section>
    </Card>
  );
}

/* --- Destaques e alertas (Insights) ----------------------------------------- */

const GRAVIDADE: Record<Alerta["gravidade"], { cor: string; texto: string }> = {
  alta: { cor: "bg-rose-500", texto: "Gravidade alta: " },
  media: { cor: "bg-ouro-500", texto: "Gravidade média: " },
  baixa: { cor: "bg-zinc-400", texto: "Gravidade baixa: " },
};

/** Destaques (maior engajamento) + situações de atenção (alertas) — os MESMOS dados
 *  reais da aba Insights. Falha na busca vira erro com "Tentar de novo" (antes, a
 *  tela dizia "nenhuma situação crítica" mesmo sem ter conseguido olhar). */
function Inteligencia({ estado, professor }: { estado: ResultadoUseApi<Insights>; professor: boolean }) {
  const { dados: intel, erro, carregando, recarregar } = estado;
  const nivel = professor ? "h2" : "h3";
  const destaques = (intel?.indices ?? []).filter((i) => i.engajamento > 0).slice(0, 4);
  const alertas = (intel?.alertas ?? []).slice(0, 4);
  const esperando = carregando && !intel;

  if (erro && !intel) {
    return (
      <Card>
        <Erro
          titulo="Não foi possível carregar os destaques e alertas"
          descricao={erro.message}
          aoTentar={recarregar}
        />
      </Card>
    );
  }

  const esqueleto = (
    <div className="mt-5 space-y-3" aria-hidden>
      {[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}
    </div>
  );

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      {/* Destaques — o índice de engajamento do /insights é dos últimos 30 dias
          (services/insights.py), não do ano letivo. */}
      <Card className="flex flex-col p-5 sm:p-6">
        <CabecalhoBloco
          nivel={nivel}
          icone={Lightbulb}
          tom="ambar"
          titulo={professor ? "Destaques das suas turmas" : "Destaques da escola"}
          subtitulo="Maior engajamento nos últimos 30 dias"
          acao={<LinkVerMais para="/insights">Ver insights</LinkVerMais>}
        />
        {esperando ? esqueleto : destaques.length === 0 ? (
          <p className="mt-5 flex-1 text-sm text-zinc-500 dark:text-zinc-400">
            Ainda não há dados suficientes para gerar destaques.
          </p>
        ) : (
          <ul className="mt-5 space-y-3.5">
            {destaques.map((a) => (
              <li key={a.aluno_id} className="flex items-center gap-3">
                <Avatar nome={a.nome} chave={a.aluno_id} tamanho="sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <Link
                      to={`/alunos/${a.aluno_id}`}
                      className="truncate text-sm font-semibold text-zinc-800 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300"
                     title={a.nome}>
                      {a.nome}
                    </Link>
                    {a.turma && <Chip className="shrink-0">{a.turma}</Chip>}
                  </div>
                  <div className="mt-1.5 flex items-center gap-2.5">
                    <BarraProgresso valor={a.engajamento} className="flex-1" />
                    <span className="w-8 shrink-0 text-right text-xs font-semibold tabular-nums text-zinc-600 dark:text-zinc-300">
                      <span className="sr-only">engajamento </span>
                      {Math.round(a.engajamento)}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Precisa de atenção — cada item é ACIONÁVEL: leva ao perfil do aluno,
          onde dá para ver a linha do tempo e agir (PRD §15). */}
      <Card className="flex flex-col p-5 sm:p-6">
        <CabecalhoBloco
          nivel={nivel}
          icone={AlertTriangle}
          tom="rosa"
          titulo="Precisa de atenção"
          subtitulo="Situações que pedem um olhar mais de perto"
        />
        {esperando ? esqueleto : alertas.length === 0 ? (
          <p className="mt-5 flex flex-1 items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 size={16} aria-hidden /> Nenhuma situação crítica identificada no momento.
          </p>
        ) : (
          <ul className="-mx-2 mt-4 space-y-0.5">
            {alertas.map((a, i) => (
              <li key={`${a.aluno_id}-${i}`}>
                <Link
                  to={`/alunos/${a.aluno_id}`}
                  className="group flex items-start gap-2.5 rounded-xl px-2 py-2 text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                >
                  <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${GRAVIDADE[a.gravidade]?.cor ?? "bg-zinc-400"}`} />
                  <span className="min-w-0 flex-1 text-zinc-700 dark:text-zinc-300">
                    <span className="sr-only">{GRAVIDADE[a.gravidade]?.texto ?? ""}</span>
                    {a.texto}
                    {/* whitespace-nowrap: "· 4º Ano A" vai inteiro para a linha de baixo,
                        sem deixar o "4º" numa linha e o "Ano A" na outra. */}
                    {a.turma && <span className="ml-1 whitespace-nowrap text-xs text-zinc-500 dark:text-zinc-400">· {a.turma}</span>}
                  </span>
                  <ArrowRight
                    size={15}
                    className="mt-0.5 shrink-0 text-zinc-400 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                    aria-hidden
                  />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/* --- 5. No ano letivo (o que o painel já mostrava, compacto) ----------------- */

function NoAnoLetivo({ dados, erro, carregando, recarregar, gestor, children }: {
  dados: DadosDashboard | null;
  erro: ResultadoUseApi<DadosDashboard>["erro"];
  carregando: boolean;
  recarregar: () => void;
  gestor: boolean;
  children?: ReactNode;
}) {
  const idTitulo = useId();
  return (
    <section aria-labelledby={idTitulo} className="space-y-5 border-t border-zinc-200/80 pt-7 dark:border-zinc-800">
      <div>
        <h2 id={idTitulo} className="text-xl font-bold tracking-tight text-zinc-900 dark:text-white">
          No ano letivo{dados ? ` ${dados.escola.ano_letivo_ativo}` : ""}
        </h2>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Retrato acumulado: a última coleta de cada aluno, sem recorte de período.
        </p>
      </div>

      {carregando ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3" aria-hidden>
          <Skeleton className="h-56 rounded-cartao" />
          <Skeleton className="h-56 rounded-cartao lg:col-span-2" />
          <Skeleton className="h-64 rounded-cartao md:col-span-2 lg:col-span-3" />
        </div>
      ) : erro ? (
        <Card>
          <Erro titulo="Não foi possível carregar os indicadores" descricao={erro.message} aoTentar={recarregar} />
        </Card>
      ) : dados ? (
        <>
          {/* DE QUANDO são as médias e o Top 5: o mesmo selo dos rankings
              (`/ranking/frescor`). Falha ao buscar não derruba o painel. */}
          <SeloFrescorDaEscola dimensoes={["leitura", "matematica"]} />
          {/* Média geral + totais na mesma linha e o Top 5 na linha de baixo, com a
              largura toda. Antes, a partir de 1280 px, a média e os totais ficavam
              empilhados numa coluna de um terço: os totais se espremiam ("33h" /
              "53min") e o Top 5 era esticado até a altura dessa coluna, com um vão
              branco entre o 5º colocado e a nota de rodapé. A partir de lg (conteúdo
              de ~960 px) os totais ganham dois terços e três colunas por linha. */}
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            <CartaoMediaGeral dados={dados} />
            <NumerosDoAno dados={dados} gestor={gestor} />
            <TopRanking top={dados.top10} />
          </div>
        </>
      ) : null}

      {children}
    </section>
  );
}

/** Média geral (0–100) com a barra ABSOLUTA, sem cor de julgamento, e a média de cada
 *  dimensão com o seu denominador ("n de N") — o "sem dado" no lugar de um 0 falso. */
function CartaoMediaGeral({ dados }: { dados: DadosDashboard }) {
  const { leitura, matematica } = useModulos();
  const linhas = [
    leitura && dados.media_leitura != null
      ? { chave: "leitura", rotulo: "Leitura", cor: "bg-indigo-600", media: dados.media_leitura, n: dados.alunos_com_dado_leitura }
      : null,
    matematica && dados.media_matematica != null
      ? { chave: "matematica", rotulo: "Matemática", cor: "bg-teal-600", media: dados.media_matematica, n: dados.alunos_com_dado_matematica }
      : null,
  ].filter((l): l is NonNullable<typeof l> => l != null);
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex items-center gap-3">
        <IconePastel icone={Star} tom="violeta" tamanho="sm" />
        <h3 className="text-[15px] font-semibold text-zinc-900 dark:text-white">Média geral</h3>
      </div>
      <p className="mt-4 flex items-baseline gap-2">
        <span className="text-[40px] font-bold leading-none tracking-tight text-indigo-700 tabular-nums dark:text-indigo-200">
          {nota(dados.media_geral)}
        </span>
        <span className="text-xs text-zinc-500 dark:text-zinc-400">escala 0–100</span>
      </p>
      <BarraProgresso valor={dados.media_geral} className="mt-4" />
      {linhas.length > 0 && (
        <ul className="mt-4 space-y-2 text-sm">
          {linhas.map((linha) => (
            <li key={linha.chave} className="flex items-center justify-between gap-3">
              <span className="inline-flex items-center gap-2 text-zinc-600 dark:text-zinc-300">
                <span aria-hidden className={`h-2 w-2 rounded-full ${linha.cor}`} />
                {linha.rotulo}
              </span>
              <span className="text-right">
                {linha.n === 0 ? (
                  <SemDado />
                ) : (
                  <span className="font-semibold tabular-nums text-zinc-900 dark:text-white">{nota(linha.media)}</span>
                )}
                {linha.n != null && (
                  <span className="ml-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                    · {numero(linha.n)} de {numero(dados.total_alunos)}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ItemDoAno({ icone, tom, rotulo, valor, detalhe }: {
  icone: LucideIcon; tom: TomPastel; rotulo: string; valor: string; detalhe?: string;
}) {
  return (
    <div className="flex min-w-0 items-start gap-3">
      <IconePastel icone={icone} tom={tom} tamanho="sm" />
      <div className="min-w-0">
        <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400">{rotulo}</p>
        {/* Sem quebra a partir de lg ("33h 53min" inteiro); abaixo disso a coluna é
            estreita e um tempo de 4 dígitos de horas precisa poder quebrar. */}
        <p className="text-lg font-bold leading-tight tabular-nums text-zinc-900 dark:text-white lg:whitespace-nowrap">{valor}</p>
        {detalhe && <p className="text-[11px] text-zinc-500 dark:text-zinc-400">{detalhe}</p>}
      </div>
    </div>
  );
}

/** Totais da escola (os mesmos do painel antigo), só das plataformas contratadas. Os atalhos
 *  para as telas das plataformas só aparecem para a gestão (o professor seria mandado de
 *  volta pela guarda de rota).
 *
 *  Alunos, turmas e o Matific são do ano letivo (o /dashboard usa a janela do ano no
 *  Matific); livros e tempo de leitura somam o último retrato do Elefante, que é
 *  contador VITALÍCIO — por isso o "desde o início no Elefante". */
function NumerosDoAno({ dados, gestor }: { dados: DadosDashboard; gestor: boolean }) {
  const { leitura, matematica } = useModulos();
  return (
    <Card className="p-5 sm:p-6 lg:col-span-2">
      <h3 className="sr-only">Totais da escola</h3>
      <div className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-2 lg:grid-cols-3">
        <ItemDoAno icone={GraduationCap} tom="violeta" rotulo="Alunos" valor={numero(dados.total_alunos)} />
        <ItemDoAno icone={Users} tom="azul" rotulo="Turmas" valor={numero(dados.total_turmas)} />
        <ItemDoAno icone={School} tom="neutro" rotulo="Professores" valor={numero(dados.total_professores)} />
        {leitura && (
          <ItemDoAno
            icone={BookOpen} tom="azul" rotulo="Livros lidos" valor={numero(dados.total_livros)}
            detalhe="títulos únicos, desde o início no Elefante"
          />
        )}
        {leitura && (
          <ItemDoAno
            icone={Clock3} tom="rosa" rotulo="Tempo de leitura" valor={tempoLeitura(dados.tempo_leitura_min)}
            detalhe="desde o início no Elefante"
          />
        )}
        {matematica && (
          <ItemDoAno icone={Calculator} tom="teal" rotulo="Atividades Matific" valor={numero(dados.total_atividades)} />
        )}
      </div>
      {gestor && (leitura || matematica) && (
        <div className="mt-5 flex flex-wrap gap-x-4 gap-y-2 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          {leitura && <LinkVerMais para="/elefante">Elefante Letrado</LinkVerMais>}
          {matematica && <LinkVerMais para="/matific">Matific</LinkVerMais>}
        </div>
      )}
    </Card>
  );
}

/** Top 5 do Ranking Geral (compacto) — o completo fica na página de ranking. */
function TopRanking({ top }: { top: DadosDashboard["top10"] }) {
  const top5 = top.slice(0, 5);
  return (
    <Card className="flex min-w-0 flex-col overflow-hidden md:col-span-2 lg:col-span-3">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 px-5 py-4 sm:px-6 dark:border-zinc-800">
        <h3 className="inline-flex items-center gap-3 text-[15px] font-semibold text-zinc-900 dark:text-white">
          <IconePastel icone={Trophy} tom="ambar" tamanho="sm" />
          Top 5 — Ranking Geral
        </h3>
        <LinkVerMais para="/ranking">Ver ranking completo</LinkVerMais>
      </div>
      {top5.length === 0 ? (
        <Vazio
          icone={Trophy}
          titulo="Ainda não há notas calculadas"
          descricao="Importe dados das plataformas ou cadastre alunos para começar."
        />
      ) : (
        <ol className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
          {top5.map((item) => (
            <li key={item.aluno_id} className="flex items-center gap-3 px-5 py-3 sm:px-6">
              <span className="grid w-8 shrink-0 place-items-center">
                {item.posicao >= 1 && item.posicao <= 3 ? (
                  <Medalha posicao={item.posicao as 1 | 2 | 3} tamanho={30} semFita />
                ) : (
                  <span className="inline-flex">
                    <PosicaoBolinha posicao={item.posicao} />
                    <span className="sr-only">º lugar</span>
                  </span>
                )}
              </span>
              <Avatar nome={item.nome} chave={item.aluno_id} tamanho="sm" />
              {/* No celular, nome (até duas linhas) e a turma embaixo, em texto pequeno; do
                  sm para cima o invólucro some (`contents`) e fica a linha de antes: nome
                  truncado e o chip da turma ao lado. A turma está UMA vez no DOM. */}
              <div className="flex min-w-0 flex-1 flex-col items-start gap-0.5 sm:contents">
                <Link
                  to={`/alunos/${item.aluno_id}`}
                  className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-800 hover:text-indigo-600 max-sm:max-w-full max-sm:flex-none max-sm:whitespace-normal max-sm:line-clamp-2 dark:text-zinc-100 dark:hover:text-indigo-300"
                 title={item.nome}>
                  {item.nome}
                </Link>
                {item.turma && (
                  <Chip className="shrink-0 max-sm:bg-transparent max-sm:p-0 max-sm:font-medium max-sm:text-zinc-500 dark:max-sm:bg-transparent dark:max-sm:text-zinc-400">
                    {item.turma}
                  </Chip>
                )}
              </div>
              <span className="w-14 shrink-0 text-right text-sm font-bold tabular-nums text-zinc-900 dark:text-white">
                {nota(item.nota_geral)}
              </span>
            </li>
          ))}
        </ol>
      )}
      <p className="mt-auto border-t border-zinc-100 px-5 py-3 text-xs text-zinc-500 sm:px-6 dark:border-zinc-800 dark:text-zinc-400">
        Nota de 0 a 100, acumulada no ano letivo.
      </p>
    </Card>
  );
}
