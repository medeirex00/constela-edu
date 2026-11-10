import {
  ArrowLeft,
  BookOpen,
  Calculator,
  Clock,
  Flame,
  History,
  IdCard,
  LineChart,
  Sigma,
  Sparkles,
  Star,
  Trophy,
  TrendingUp,
  UserRound,
} from "lucide-react";
import { useId, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import AcoesAluno from "../components/AcoesAluno";
import EvolucaoAlunoAba from "../components/EvolucaoAlunoAba";
import HistoricoLeituras from "../components/HistoricoLeituras";
import LinhaDoTempoAluno from "../components/LinhaDoTempoAluno";
import { AvatarAluno, PilulaSituacao } from "../components/PessoasUi";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Abas,
  Badge,
  BarraProgresso,
  Card,
  Chip,
  ESTILOS_BOTAO,
  Erro,
  IconePastel,
  SecaoRecolhivel,
  Skeleton,
  StatCard,
  TAMANHOS_BOTAO,
  Vazio,
  classesTabela,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { dataHora, nota, notaDaMateria, numero } from "../lib/formato";
import type { LeituraNiveis, LinhaCalculo, PerfilAluno as Perfil } from "../lib/types";

// Ficha cadastral MINIMIZADA (LGPD): o produto guarda só o RA como identidade.
// Nome e nº de chamada aparecem no topo do perfil (não aqui). Nada de dados
// sensíveis (raça/cor, SUS) ou documentos (CPF/RG) — nem são coletados.
const ROTULOS_FICHA: Record<string, string> = {
  ra: "RA",
};

/** Situação da ficha que merece aviso no topo (ativo não leva pílula). */
const SITUACAO_FICHA: Record<string, { tom: "neutro" | "alerta" | "erro"; texto: string }> = {
  arquivado: { tom: "neutro", texto: "Arquivado" },
  excluido: { tom: "erro", texto: "Na lixeira" },
  fora_lista_piloto: { tom: "alerta", texto: "Fora da lista piloto" },
  transferido: { tom: "neutro", texto: "Transferido" },
};

/** Cores das posições 1–3 (medalhas); da 4ª em diante, pílula neutra. */
const COR_POSICAO: Record<number, string> = {
  1: "bg-medalha-ouro text-[#5B3B00]",
  2: "bg-medalha-prata text-[#2B3350]",
  3: "bg-medalha-bronze text-[#4A2306]",
};

/** Campos da ficha que podem aparecer (rótulo, valor). */
function itensDaFicha(ficha: Record<string, string> | null | undefined): Array<readonly [string, string]> {
  const itens: Array<readonly [string, string]> = [];
  if (!ficha) return itens;
  // Só campos EXPLICITAMENTE permitidos aparecem — sem fallback que exibiria
  // qualquer chave residual da ficha (defesa em profundidade de privacidade).
  for (const chave of Object.keys(ROTULOS_FICHA)) {
    if (ficha[chave]) itens.push([ROTULOS_FICHA[chave], ficha[chave]] as const);
  }
  return itens;
}

/** Dados cadastrais do aluno (minimizados: só o RA). */
function FichaCadastral({ itens }: { itens: Array<readonly [string, string]> }) {
  if (itens.length === 0) return null;
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center gap-3">
        <IconePastel icone={IdCard} tom="azul" />
        <h2 className="text-base font-semibold tracking-tight">Ficha cadastral</h2>
      </div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
        {itens.map(([rotulo, valor]) => (
          <div key={rotulo} className="min-w-0 rounded-xl bg-zinc-50 px-3.5 py-2.5 dark:bg-zinc-800/50">
            <dt className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">{rotulo}</dt>
            <dd className="mt-0.5 break-words text-sm font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">{valor}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/** Barras horizontais dos livros concluídos por faixa de dificuldade (PRD §38). */
function LeituraPorNivel({ dados }: { dados: LeituraNiveis }) {
  const maxQtd = Math.max(1, ...dados.faixas.map((f) => f.quantidade));
  return (
    <Card className="p-5">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <IconePastel icone={BookOpen} tom="violeta" />
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight">Leitura por nível</h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {numero(dados.total_livros)} livro{dados.total_livros === 1 ? "" : "s"} ·{" "}
            <span className="font-semibold text-indigo-700 dark:text-indigo-300">
              {numero(dados.pontos_dificuldade)} pontos de dificuldade
            </span>
          </p>
        </div>
        {dados.faixa_predominante && (
          <span className="ml-auto">
            <Badge tom="destaque">Predominante: {dados.faixa_predominante}</Badge>
          </span>
        )}
      </div>

      {dados.total_livros === 0 ? (
        <p className="rounded-xl bg-zinc-50 px-4 py-6 text-center text-sm text-zinc-500 dark:bg-zinc-800/40 dark:text-zinc-400">
          Nenhum livro registrado ainda. Informe os livros por nível na tela Elefante Letrado
          ou importe um relatório.
        </p>
      ) : (
        <div className="space-y-3">
          {/* Celular (< 640 px): rótulo e valor na 1ª linha e a barra na linha inteira
              de baixo (antes ficava com ~60 px, espremida entre os dois, e barras de 1 e 2
              livros quase não se distinguiam). Do sm em diante, uma linha só, como antes. */}
          {dados.faixas.map((faixa) => (
            <div key={faixa.codigo} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5 text-sm sm:grid-cols-[6.5rem_1fr_auto]">
              <span className="truncate font-medium text-zinc-700 dark:text-zinc-200" title={faixa.nome}>{faixa.nome}</span>
              <div className="h-6 overflow-hidden rounded-lg bg-zinc-100 max-sm:order-last max-sm:col-span-2 dark:bg-zinc-800">
                <div
                  className="flex h-full items-center justify-end rounded-lg bg-gradient-to-r from-indigo-400 to-indigo-600 px-2 text-xs font-semibold text-white transition-all"
                  style={{ width: `${Math.max(faixa.quantidade ? 8 : 0, (faixa.quantidade / maxQtd) * 100)}%` }}
                >
                  {faixa.quantidade > 0 ? faixa.quantidade : ""}
                </div>
              </div>
              <span className="w-28 shrink-0 text-right text-xs tabular-nums text-zinc-500 max-sm:w-auto dark:text-zinc-400">
                {faixa.percentual}% · {numero(faixa.pontos)} pts
              </span>
            </div>
          ))}
          <p className="pt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Pontos por livro: {dados.faixas.map((f) => `${f.nome} = ${numero(f.pontos_por_livro)}`).join(" · ")}.
            Configuráveis em Critérios.
          </p>
        </div>
      )}
    </Card>
  );
}

function TabelaCalculo({ titulo, linhas, notaFinal }: { titulo: string; linhas: LinhaCalculo[]; notaFinal: number }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-zinc-200/80 dark:border-zinc-800">
      <div className="flex items-center justify-between bg-zinc-50 px-4 py-3 dark:bg-zinc-800/40">
        <h3 className="text-sm font-semibold">{titulo}</h3>
        <span className="text-sm font-bold tabular-nums">{nota(notaFinal)}</span>
      </div>
      {/* Celular (< 640 px): rola de lado com o aviso em texto acima da tabela, e a
          Contribuição (o que soma na nota) fica presa à direita (`presa-celular`). */}
      <TabelaRolavel rotulo={`${titulo}: tabela do cálculo`}>
        <table className={`${classesTabela.tabela} tabular-nums`}>
          <thead>
            <tr>
              <th className={classesTabela.th}>Indicador</th>
              <th className={`text-right ${classesTabela.th}`}>Valor</th>
              <th className={`text-right ${classesTabela.th}`}>Referência</th>
              <th className={`text-right ${classesTabela.th}`}>Normalizado</th>
              <th className={`text-right ${classesTabela.th}`}>Peso</th>
              <th className={`text-right ${classesTabela.th} presa-celular`}>Contribuição</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((linha) => (
              <tr key={linha.indicador} className={classesTabela.tr}>
                <td className={`${classesTabela.td} font-medium`}>{linha.indicador}</td>
                <td className={`${classesTabela.td} text-right`}>{nota(linha.valor)}</td>
                <td className={`${classesTabela.td} text-right text-zinc-500 dark:text-zinc-400`}>{nota(linha.referencia)}</td>
                <td className={`${classesTabela.td} text-right`}>{nota(linha.normalizado)}</td>
                <td className={`${classesTabela.td} text-right text-zinc-500 dark:text-zinc-400`}>{linha.peso}%</td>
                <td className={`${classesTabela.td} presa-celular text-right font-semibold text-zinc-900 dark:text-zinc-100`}>{nota(linha.contribuicao)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TabelaRolavel>
    </div>
  );
}

/** No lugar da tabela do cálculo de uma plataforma sem dado da criança. */
function SemDadoDaPlataforma({ plataforma }: { plataforma: string }) {
  return (
    <div className="rounded-2xl border border-zinc-200/80 px-4 py-3 text-sm dark:border-zinc-800">
      <h3 className="font-semibold">{plataforma}</h3>
      <p className="mt-1 text-zinc-600 dark:text-zinc-300">
        Ainda não há dados desta criança nesta plataforma, por isso não há nota (“—”).
      </p>
    </div>
  );
}

interface ConquistaAluno {
  codigo: string;
  nome: string;
  icone: string;
  descricao: string;
  criterio: string;
  unidade: string;
  xp: number;
  raridade: string;
  limite: number;
  progresso: number;
  pct: number;
  faltam: number;
  atingida: boolean;
}

interface Gamificacao {
  xp: number;
  xp_conquistas: number;
  nivel: number;
  xp_para_proximo: number;
  sequencia_semanas: number;
  total_conquistas: number;
  conquistas: ConquistaAluno[];
}

function valorCurto(valor: number): string {
  return Number.isInteger(valor) ? String(valor) : nota(valor);
}

/** "Faltam apenas 7 livros para desbloquear esta conquista." */
function textoFaltam(conquista: ConquistaAluno): string {
  const quanto = valorCurto(conquista.faltam);
  if (conquista.unidade === "%") {
    return `Faltam ${quanto} pontos percentuais para desbloquear esta conquista.`;
  }
  return `Faltam apenas ${quanto} ${conquista.unidade} para desbloquear esta conquista.`;
}

/** Bloco "Conquistas": nível, XP, sequência, as mais próximas e a grade completa. */
function Conquistas({ gamificacao }: { gamificacao: Gamificacao }) {
  const atingidas = gamificacao.conquistas.filter((c) => c.atingida).length;
  const proximas = gamificacao.conquistas
    .filter((c) => !c.atingida && c.progresso > 0)
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 3);
  return (
    <Card className="p-5">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <IconePastel icone={Trophy} tom="ambar" />
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight">Conquistas</h2>
          <p className="text-sm tabular-nums text-zinc-500 dark:text-zinc-400">
            {atingidas} de {gamificacao.conquistas.length} desbloqueada{gamificacao.conquistas.length === 1 ? "" : "s"}
          </p>
        </div>
        <Link
          to="/conquistas/biblioteca"
          className="ml-auto text-sm font-semibold text-indigo-600 hover:underline dark:text-indigo-300"
        >
          Ver a Biblioteca de Conquistas →
        </Link>
      </div>

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="flex items-center gap-3 rounded-2xl bg-indigo-50 px-4 py-3 dark:bg-indigo-500/10">
          <IconePastel icone={Star} tom="violeta" tamanho="sm" className="bg-white dark:bg-zinc-900" />
          <div>
            <p className="text-lg font-bold leading-tight tabular-nums text-indigo-800 dark:text-indigo-200">Nível {gamificacao.nivel}</p>
            <p className="text-xs text-indigo-800/80 dark:text-indigo-200/80">faltam {gamificacao.xp_para_proximo} XP para o próximo nível</p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-2xl bg-ouro-50 px-4 py-3 dark:bg-ouro-400/10">
          <IconePastel icone={Sparkles} tom="ambar" tamanho="sm" className="bg-white dark:bg-zinc-900" />
          <div>
            <p className="text-lg font-bold leading-tight tabular-nums text-marinho-900 dark:text-ouro-200">
              {gamificacao.xp.toLocaleString("pt-BR")} XP
            </p>
            <p className="text-xs text-ouro-700 dark:text-ouro-300">
              {gamificacao.xp_conquistas > 0
                ? `${gamificacao.xp_conquistas.toLocaleString("pt-BR")} de conquistas`
                : "pontos de experiência acumulados"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-2xl bg-rose-50 px-4 py-3 dark:bg-rose-500/10">
          <IconePastel icone={Flame} tom="rosa" tamanho="sm" className="bg-white dark:bg-zinc-900" />
          <div>
            <p className="text-lg font-bold leading-tight tabular-nums text-rose-800 dark:text-rose-200">
              {gamificacao.sequencia_semanas} semana{gamificacao.sequencia_semanas === 1 ? "" : "s"}
            </p>
            <p className="text-xs text-rose-800/80 dark:text-rose-200/80">
              {gamificacao.sequencia_semanas === 1
                ? "seguida com atividade"
                : gamificacao.sequencia_semanas > 1
                  ? "seguidas com atividade"
                  : "sem sequência ativa agora"}
            </p>
          </div>
        </div>
      </div>

      {/* Próximas conquistas: as mais perto de desbloquear (§ progresso) */}
      {proximas.length > 0 && (
        <div className="mb-5">
          <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
            Próximas conquistas
          </p>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            {proximas.map((conquista) => (
              <div key={conquista.codigo} className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4 dark:border-indigo-500/20 dark:bg-indigo-500/5">
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 break-words text-sm font-semibold leading-snug" title={conquista.nome}>
                    <span aria-hidden>{conquista.icone}</span> {conquista.nome}
                  </p>
                  <span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-xs font-bold tabular-nums text-indigo-700 dark:bg-zinc-900 dark:text-indigo-300">
                    {Math.round(conquista.pct)}%
                  </span>
                </div>
                <p className="mb-2 mt-0.5 text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                  {valorCurto(conquista.progresso)} de {valorCurto(conquista.limite)} {conquista.unidade}
                </p>
                <BarraProgresso valor={conquista.pct} />
                <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">{textoFaltam(conquista)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {gamificacao.conquistas.map((conquista) => (
          <div
            key={conquista.codigo}
            className={`flex items-start gap-3 rounded-2xl border p-3 ${
              conquista.atingida
                ? "border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/20 dark:bg-emerald-500/5"
                : "border-zinc-200/80 dark:border-zinc-800"
            }`}
          >
            <span
              aria-hidden
              className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl text-lg leading-none ${
                conquista.atingida ? "bg-white dark:bg-zinc-900" : "bg-zinc-100 opacity-60 dark:bg-zinc-800"
              }`}
            >
              {conquista.icone}
            </span>
            <div className="min-w-0 flex-1">
              {/* Nome e "+N XP" na mesma linha quando cabem; se não, o selo desce
                  (antes o selo espremia o nome, uma palavra por linha). */}
              <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                <p className={`text-sm font-semibold ${conquista.atingida ? "" : "text-zinc-600 dark:text-zinc-300"}`}>
                  {conquista.nome}
                </p>
                <span className="shrink-0 whitespace-nowrap text-xs font-bold text-ouro-700 dark:text-ouro-300">
                  +{conquista.xp} XP
                </span>
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">{conquista.descricao}</p>
              {!conquista.atingida && (
                <div className="mt-2">
                  <BarraProgresso valor={conquista.pct} />
                  <p className="mt-1 text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                    {valorCurto(conquista.progresso)} / {valorCurto(conquista.limite)} {conquista.unidade}
                  </p>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Esqueleto do perfil enquanto carrega. */
function EsqueletoPerfil() {
  return (
    <div role="status" className="space-y-6">
      <span className="sr-only">Carregando...</span>
      <Skeleton className="h-4 w-20" />
      <Card className="flex items-center gap-5 p-6">
        <Skeleton className="h-[72px] w-[72px] rounded-full" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-7 w-64 max-w-full" />
          <Skeleton className="h-5 w-40" />
        </div>
      </Card>
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-36 rounded-cartao" />)}
      </div>
    </div>
  );
}

type Aba = "perfil" | "linha_do_tempo" | "historico" | "evolucao";

const ABAS: { valor: Aba; rotulo: string; icone: typeof UserRound }[] = [
  { valor: "perfil", rotulo: "Perfil", icone: UserRound },
  { valor: "linha_do_tempo", rotulo: "Linha do tempo", icone: Clock },
  { valor: "historico", rotulo: "Histórico de Leituras", icone: History },
  { valor: "evolucao", rotulo: "Evolução", icone: LineChart },
];

export default function PerfilAluno() {
  const { id } = useParams();
  const { escolaId, usuario } = useApp();
  const navegar = useNavigate();
  const idPainel = useId();
  // Professor vê a versão SUPERFICIAL: notas, posição e gamificação — sem
  // histórico de leituras, evolução detalhada nem ações de gestão.
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  // O Histórico de Leituras é do Elefante Letrado: sem o módulo de leitura no
  // plano da rede, a aba não aparece (módulo fora do plano não aparece nem vazio).
  const { leitura } = useModulos();
  const [aba, setAba] = useState<Aba>("perfil");

  // Leitura via hook único: cuida de cancelamento, timeout e retry. Fica
  // ocioso (null) enquanto escolaId/id não existirem.
  const podeBuscar = Boolean(escolaId && id);
  const {
    dados: perfil,
    erro: erroPerfil,
    carregando,
    recarregar: recarregarPerfil,
  } = useApi<Perfil>(podeBuscar ? `/escolas/${escolaId}/alunos/${id}/perfil` : null);
  const { dados: gamificacao, recarregar: recarregarGamificacao } = useApi<Gamificacao>(
    podeBuscar ? `/escolas/${escolaId}/gamificacao/alunos/${id}` : null,
  );

  // Refaz as duas buscas após uma ação de gestão (editar, trocar turma…).
  const recarregar = () => {
    recarregarPerfil();
    recarregarGamificacao();
  };

  if (carregando) return <EsqueletoPerfil />;
  // Não engole o erro: mostra o motivo e deixa tentar de novo.
  if (erroPerfil) {
    return (
      <Card>
        <Erro descricao={erroPerfil.message} aoTentar={recarregar} />
      </Card>
    );
  }
  if (!perfil) {
    return (
      <Card>
        <Vazio icone={UserRound} titulo="Aluno não encontrado"
               descricao="Volte à lista de alunos e abra o perfil de novo." />
      </Card>
    );
  }

  const { aluno, detalhes } = perfil;
  // As parcelas da Nota Geral saem do que o MOTOR de fato usou (detalhes.geral.
  // pesos), não de uma lista fixa de plataformas: numa rede que só contratou a
  // Leitura, a conta é "Elefante 70 × 100% = 70" — escrever "Matific × 0% +
  // Elefante × 50%" mostraria uma equação que não fecha com a própria nota.
  const pesosGerais: Record<string, number> = detalhes.geral?.pesos ?? {};
  const ROTULO_PLATAFORMA: Record<string, string> = {
    matific: "Matific",
    elefante: "Elefante",
  };
  const parcelasGerais = Object.entries(pesosGerais)
    .filter(([, peso]) => Number(peso) > 0)
    .map(([chave, peso]) => ({
      chave,
      rotulo: ROTULO_PLATAFORMA[chave] ?? chave,
      peso: Number(peso),
      valor: chave === "matific" ? perfil.nota_matific : perfil.nota_elefante,
    }));
  // Quando o servidor manda o desempenho por dimensão, o `aferido` decide o "—"
  // (sem snapshot ≠ zero). Sem o campo, mostra o número que veio (notaDaMateria).
  const aferidoDe = (dimensao: string) =>
    perfil.dimensoes?.find((d) => d.dimensao === dimensao)?.aferido;
  // Sem dado em NENHUMA dimensão contratada, a Nota Geral (composição das duas)
  // chega 0,0 e o motor grava o passo a passo de cada plataforma com nota 0 — a
  // ficha mostrava "—" nos cartões e afirmava zero logo abaixo. Aqui ela também é
  // "—", e o cálculo dá lugar ao aviso de que ainda não há dados.
  const semDadoNenhum = Boolean(perfil.dimensoes?.length)
    && (perfil.dimensoes ?? []).every((d) => !d.aferido);
  const temCalculo = Boolean(detalhes.matific || detalhes.elefante) && !semDadoNenhum;
  const situacao = SITUACAO_FICHA[aluno.status];
  const itensFicha = itensDaFicha(perfil.ficha);
  const temFicha = itensFicha.length > 0;
  const abasVisiveis = ABAS.filter((item) =>
    (gestor || item.valor === "perfil") && (leitura || item.valor !== "historico"));
  const rotuloAba = abasVisiveis.find((item) => item.valor === aba)?.rotulo ?? "Perfil";

  const conteudo = (
    <>
      {gestor && aba === "linha_do_tempo" && escolaId && id && (
        <LinhaDoTempoAluno escolaId={escolaId} alunoId={id} />
      )}

      {gestor && leitura && aba === "historico" && escolaId && id && (
        <HistoricoLeituras escolaId={escolaId} alunoId={id} />
      )}

      {gestor && aba === "evolucao" && escolaId && id && (
        <EvolucaoAlunoAba escolaId={escolaId} alunoId={id} />
      )}

      {aba === "perfil" && (
        <div className="space-y-6">
          <div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-5 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2">
              <StatCard
                icone={<BookOpen size={20} />}
                tom="violeta"
                rotulo="Nota Elefante Letrado"
                valor={notaDaMateria(perfil.nota_elefante, aferidoDe("leitura"))}
                detalhe="Leitura · de 0 a 100"
              />
              <StatCard
                icone={<Calculator size={20} />}
                tom="teal"
                rotulo="Nota Matific"
                /* `null` = Matemática fora do plano da rede: "—", nunca um 0,0 falso. */
                valor={notaDaMateria(perfil.nota_matific, aferidoDe("matematica"))}
                detalhe="Matemática · de 0 a 100"
              />
              <StatCard
                icone={<Trophy size={20} />}
                tom="ambar"
                rotulo="Nota Geral"
                valor={semDadoNenhum ? "—" : nota(perfil.nota_geral)}
                detalhe="Composição das plataformas · veja o cálculo abaixo"
              />
            </div>
            {perfil.calculada_em && (
              <p className="mt-2.5 text-xs text-zinc-500 dark:text-zinc-400">
                Notas calculadas em {dataHora(perfil.calculada_em)}.
              </p>
            )}
          </div>

          {gamificacao && <Conquistas gamificacao={gamificacao} />}

          {(perfil.leitura_niveis || temFicha) && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              {/* Sem ficha para mostrar, a Leitura por nível ocupa a largura toda
                  (antes reservava a 3ª coluna e deixava um buraco ao lado). */}
              {perfil.leitura_niveis && (
                <div className={temFicha ? "lg:col-span-2" : "lg:col-span-3"}>
                  <LeituraPorNivel dados={perfil.leitura_niveis} />
                </div>
              )}
              {temFicha && (
                <div className={perfil.leitura_niveis ? "" : "lg:col-span-3"}>
                  <FichaCadastral itens={itensFicha} />
                </div>
              )}
            </div>
          )}

          {/* Transparência total do cálculo (PRD §45, §54). O professor também vê o
              passo a passo (das crianças da turma dele); o backend só envia o
              `detalhes` de quem ele pode acessar. Recolhível para a ficha não
              parecer um relatório técnico — nada foi removido. */}
          <SecaoRecolhivel
            titulo="Como esta nota foi calculada"
            icone={<IconePastel icone={Sigma} tom="neutro" tamanho="sm" />}
            inicialAberto={!temCalculo}
          >
            <div className="space-y-4">
              {detalhes.modo_normalizacao && (
                <p className="text-sm text-zinc-600 dark:text-zinc-300">
                  Normalização dos indicadores:{" "}
                  <strong>{detalhes.modo_normalizacao === "auto" ? "automática" : "manual"}</strong>.
                </p>
              )}
              {/* Plataforma sem dado da criança: o motor grava o passo a passo com
                  nota 0, mas não houve o que medir — a tabela afirmaria um zero. */}
              {!semDadoNenhum && detalhes.matific && (aferidoDe("matematica") === false
                ? <SemDadoDaPlataforma plataforma="Matific" />
                : <TabelaCalculo titulo="Matific" linhas={detalhes.matific.indicadores} notaFinal={detalhes.matific.nota} />
              )}
              {!semDadoNenhum && detalhes.elefante && (aferidoDe("leitura") === false
                ? <SemDadoDaPlataforma plataforma="Elefante Letrado" />
                : <TabelaCalculo titulo="Elefante Letrado" linhas={detalhes.elefante.indicadores} notaFinal={detalhes.elefante.nota} />
              )}
              {!semDadoNenhum && detalhes.geral && parcelasGerais.length > 0 && (
                <div className="rounded-2xl bg-ouro-50 p-4 text-sm dark:bg-ouro-400/10">
                  <p className="font-semibold text-marinho-900 dark:text-ouro-200">Nota Geral</p>
                  <p className="mt-1 tabular-nums text-zinc-700 dark:text-zinc-200">
                    {parcelasGerais.map((p, i) => (
                      <span key={p.chave}>
                        {i > 0 && " + "}
                        {p.rotulo} {notaDaMateria(p.valor)} × {p.peso}%
                      </span>
                    ))}
                    {" = "}
                    <span className="font-bold text-zinc-900 dark:text-zinc-100">{nota(perfil.nota_geral)}</span>
                  </p>
                </div>
              )}
              {!temCalculo && (semDadoNenhum ? (
                <Vazio
                  icone={Calculator}
                  titulo="Ainda não há dados desta criança nas plataformas"
                  descricao="A nota aparece aqui depois que ela usar as plataformas e os dados forem importados."
                />
              ) : (
                <Vazio
                  icone={Calculator}
                  titulo="Ainda não há nota calculada para este aluno"
                  descricao="Importe dados das plataformas para gerar a primeira nota."
                />
              ))}
            </div>
          </SecaoRecolhivel>
        </div>
      )}
    </>
  );

  return (
    <div className="space-y-6">
      <Link
        to="/alunos"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-500 transition-colors hover:text-indigo-600 dark:text-zinc-400 dark:hover:text-indigo-300"
      >
        <ArrowLeft size={15} aria-hidden /> Alunos
      </Link>

      {/* Cabeçalho do aluno: avatar grande, nome, turma em chip e as ações. */}
      <Card className="relative overflow-hidden p-6">
        <span
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-indigo-100/70 blur-2xl dark:bg-indigo-500/10"
        />
        <div className="relative flex flex-wrap items-center gap-5">
          <AvatarAluno nome={aluno.nome} chave={aluno.id} foto={aluno.foto_url} tamanho="xl" />
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold leading-tight tracking-tight text-zinc-900 dark:text-white sm:text-[28px]">
              {aluno.nome}
            </h1>
            <div className="mt-2.5 flex flex-wrap items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
              {aluno.turma && <Chip>{aluno.turma}</Chip>}
              {aluno.ano_escolar && <span>{aluno.ano_escolar}</span>}
              {aluno.numero_chamada != null && (
                <span className="tabular-nums">· Nº {aluno.numero_chamada}</span>
              )}
              {situacao && <PilulaSituacao tom={situacao.tom}>{situacao.texto}</PilulaSituacao>}
              {perfil.posicao != null && perfil.posicao > 0 && (
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold tabular-nums ${
                    COR_POSICAO[perfil.posicao] ?? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300"
                  }`}
                >
                  {perfil.posicao}º no ranking
                </span>
              )}
            </div>
          </div>
          {gestor && (
            <div className="flex items-center gap-2">
              <Link
                to={`/alunos/${aluno.id}/evolucao`}
                className={`inline-flex items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.md} ${ESTILOS_BOTAO.secundario}`}
              >
                <TrendingUp size={16} aria-hidden /> Ver evolução
              </Link>
              {escolaId && (
                // Editar dados, trocar turma, arquivar, excluir — direto da ficha
                <AcoesAluno
                  aluno={aluno}
                  escolaId={escolaId}
                  aoMudar={recarregar}
                  aoExcluir={() => navegar("/alunos")}
                  mostrarVisualizar={false}
                />
              )}
            </div>
          )}
        </div>
      </Card>

      {/* Professor: só a aba Perfil (histórico e evolução detalhada são de gestão) */}
      {abasVisiveis.length > 1 ? (
        <>
          <Abas
            itens={abasVisiveis.map(({ valor, rotulo, icone }) => ({ valor, rotulo, icone }))}
            valor={aba}
            aoMudar={setAba}
            rotulo="Seções do perfil do aluno"
            idPainel={idPainel}
          />
          <div role="tabpanel" id={idPainel} aria-label={rotuloAba}>
            {conteudo}
          </div>
        </>
      ) : (
        conteudo
      )}
    </div>
  );
}
