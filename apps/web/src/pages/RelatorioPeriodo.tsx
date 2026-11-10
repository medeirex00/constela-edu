/**
 * Relatório por PERÍODO — "o que aconteceu em setembro", por plataforma e por
 * escopo (escola, turma, aluno).
 *
 * O que esta tela NÃO faz: calcular. Todo número chega pronto de
 * `/escolas/{id}/relatorios/periodo`, que reusa o serviço OFICIAL de períodos
 * (`periodos.resolver`) — então "setembro" aqui é o mesmo "setembro" do pódio.
 * Mérito, nota, ranking e certificado não passam por aqui.
 *
 * O que ela faz de propósito, e é o ponto da tela: DIZER DE QUAL DATA CADA
 * NÚMERO VEM. O Elefante entrega dois fatos diferentes e somá-los contaria o
 * mesmo livro duas vezes:
 *
 *   • "livros novos" e "tempo" vêm de `Leitura.data` — o MESMO campo da
 *     premiação oficial. É o número que bate com a cerimônia.
 *   • "livros com atividade" e "relidos" vêm de `EventoAluno.ocorrido_em` — o
 *     único campo que vê a releitura (a §35 nunca atualiza `Leitura.data`).
 *
 * E o que o sistema NÃO sabe responder aparece como "—" com o motivo visível,
 * nunca como zero: questões do Matific (não existe o contador) e tempo por
 * evento no Elefante (o campo é acumulado por livro; medição em produção
 * refutou tanto a soma quanto a diferença). Um zero silencioso num relatório
 * de gestão é pior que uma lacuna declarada — a diretora agiria sobre ele.
 */
import {
  BookOpen, CalendarRange, Clock, FileDown, Info, Layers, Loader2, RefreshCw, School, Sigma, SlidersHorizontal, Star,
  UserRound, Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { IconePlataforma } from "../components/identidadePlataforma";
import { SeletorPeriodo, periodoParaQuery } from "../components/SeletorPeriodo";
import { MolduraPilula, estiloSelectPilula } from "../components/SeletorPilula";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Avatar, Badge, Botao, Card, Chip, Erro, IconePastel, Mensagem, PageHeader, RotuloSecao, SecaoRecolhivel, Skeleton,
  StatCard, Vazio, classesTabela,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { apiDownload } from "../lib/api";
import { dataHora, numero, tempoLeitura } from "../lib/formato";
import type { Turma } from "../lib/types";

type Classificacao = "SUPORTADO" | "SUPORTADO COM RESSALVA" | "NÃO SUPORTADO";

interface Suporte {
  campo?: string;
  classificacao: Classificacao;
  por_que: string;
  ressalva?: string;
}

interface JanelaEfetiva {
  data_base_mais_antiga: string | null;
  data_base_mais_recente: string | null;
  data_atual_mais_antiga: string;
  data_atual_mais_recente: string;
  observacao: string;
}

/** PERÍODO PEDIDO × COBERTURA DAS COLETAS (backend `_cobertura`). Datas do
 *  período em dias de Brasília ("AAAA-MM-DD"); instantes de coleta em UTC sem
 *  fuso (como todo `data_referencia`, convertidos por `dataHora`). */
interface Cobertura {
  periodo_inicio: string | null;
  periodo_fim: string | null;
  periodo_fim_efetivo: string | null;
  coleta_inicio: string | null;
  coleta_inicio_mais_tardio: string | null;
  coleta_fim: string | null;
  coleta_fim_mais_cedo: string | null;
  inicio_coberto: boolean;
  fim_coberto: boolean;
  inclui_antes_do_inicio: boolean;
  inicio_do_contador_anual?: boolean;
  antecedencia_max_horas: number | null;
  /** `diferenca_de_coletas` (Elefante) ou `oficial_matific` (a regra das
   *  premiações: as bordas não são verificadas, "completa" nunca é afirmado). */
  regra: "diferenca_de_coletas" | "oficial_matific";
  em_andamento: boolean;
  status: "completa" | "ampliada" | "parcial" | "regra_oficial" | "sem_intervalo";
  completa: boolean;
  alunos_cobertura_completa: number;
  alunos_cobertura_parcial: number;
  alunos_sem_inicio: number;
  alunos_sem_fim: number;
  alunos_ampliados: number;
  alunos_sem_intervalo: number;
  /** Dos "sem intervalo": a única coleta do período é a que mede o INÍCIO. */
  alunos_sem_intervalo_so_inicio?: number;
  /** Contador que diminuiu (contas misturadas na ficha): fora da conta. */
  alunos_contador_regrediu?: number;
  /** Coletados antes e depois do período, mas não dentro dele: lacuna. */
  alunos_sem_coleta_no_periodo?: number;
  /** Coletados ANTES do período e sem coleta que entre na conta: a coleta
   *  parou ou falhou para eles (o número é parcial, nunca "completo"). */
  alunos_coleta_interrompida?: number;
  /** Turmas (já coletadas alguma vez) sem nenhuma coleta na janela. */
  turmas_sem_coleta?: { turma_id: number; turma: string | null; alunos: number }[];
  /** Denominador de "para N aluno(s)": quem tem intervalo medido. */
  alunos_medidos?: number;
  /** (Elefante) contador vitalício que a primeira coleta já trazia, para quem
   *  não tem coleta no início: histórico SEM data, fora da conta. */
  acumulado_na_primeira_coleta?: number | null;
  /** (Elefante) alunos cuja coleta no período veio SEM as questões (a plataforma
   *  deixou de mandá-las): ela não mede a borda, e a conta deles vai só até a
   *  coleta anterior — ou fica sem número. Ausente em API anterior. */
  alunos_questoes_nao_vieram?: number;
}

interface BlocoElefante {
  livros_novos: number;
  tempo_min: number;
  alunos_com_livro_novo: number;
  livros_com_atividade: number;
  livros_relidos: number;
  eventos_leitura: number;
  tempo_min_por_evento: null;
  alunos_com_atividade: number;
  questoes_tentativas: number | null;
  questoes_acertos: number | null;
  alunos_sem_retrato: number;
  janela_efetiva_questoes: JanelaEfetiva | null;
  /** Ausente em API anterior a esta versão: a tela cai no aviso antigo. */
  cobertura_questoes?: Cobertura | null;
  sem_atividade: number;
  primeiro_evento_da_escola: string | null;
  suporte: Record<string, Suporte>;
}

interface BlocoMatific {
  atividades: number;
  estrelas: number;
  alunos_com_atividade: number;
  alunos_sem_retrato: number;
  questoes: null;
  janela_efetiva: JanelaEfetiva | null;
  cobertura?: Cobertura | null;
  sem_atividade: number;
  /** O bloco do Matific tem UM suporte (atividades/estrelas) e, dentro dele, o
   *  de `questoes` — que é a métrica inexistente. Daí o tipo não ser um mapa. */
  suporte: Suporte & { questoes: Suporte };
}

interface LinhaTurma {
  turma_id: number;
  turma: string;
  ano_escolar: string;
  turno: string | null;
  alunos: number;
  com_atividade: number;
  elefante: { livros_novos: number; tempo_min: number; livros_com_atividade: number; livros_relidos: number; eventos_leitura: number };
  matific: { atividades: number; estrelas: number };
}

interface LinhaAluno {
  aluno_id: number;
  nome: string;
  turma: string;
  turma_id: number;
  ano_escolar: string;
  elefante: { livros_novos: number; tempo_min: number; livros_com_atividade: number; livros_relidos: number; eventos_leitura: number } | null;
  matific: { atividades: number; estrelas: number } | null;
  sem_atividade: boolean;
}

interface RelatorioPeriodoT {
  escola: { id: number; nome: string; ano_letivo: number };
  periodo: { preset: string; rotulo: string; inicio: string | null; fim: string | null; inclusivo: boolean };
  escopo: { tipo: string; turma_id: number | null; aluno_id: number | null; restrito_a_turmas: number[] | null };
  plataformas: string[];
  plataformas_rotulo: string;
  alunos: { considerados: number; com_atividade: number; sem_atividade: number };
  nao_suportado: { plataforma: string; metrica: string; por_que: string }[];
  elefante?: BlocoElefante;
  matific?: BlocoMatific;
  por_turma?: LinhaTurma[];
  por_aluno: LinhaAluno[];
}

interface PaginaAlunos {
  itens: { id: number; nome: string; turma_id: number | null }[];
}

const PLATAFORMAS = [
  { valor: "elefante,matific", rotulo: "Elefante Letrado + Matific" },
  { valor: "elefante", rotulo: "Somente Elefante Letrado" },
  { valor: "matific", rotulo: "Somente Matific" },
] as const;

const TOM_CLASSIFICACAO: Record<Classificacao, "ok" | "alerta" | "neutro"> = {
  SUPORTADO: "ok",
  "SUPORTADO COM RESSALVA": "alerta",
  "NÃO SUPORTADO": "neutro",
};

/** Etiqueta da classificação, na língua de quem lê o relatório (a classificação
 *  vem do backend; "SUPORTADO COM RESSALVA" não diz nada a uma professora). */
const ROTULO_CLASSIFICACAO: Record<Classificacao, string> = {
  SUPORTADO: "Confiável",
  "SUPORTADO COM RESSALVA": "Confiável, com um cuidado",
  "NÃO SUPORTADO": "Não calculado",
};

function Selo({ classificacao }: { classificacao: Classificacao }) {
  return (
    <Badge tom={TOM_CLASSIFICACAO[classificacao]}>{ROTULO_CLASSIFICACAO[classificacao] ?? classificacao}</Badge>
  );
}

/** "Como ler estes números" em linguagem de professor. Diz o MESMO que o backend
 *  manda em `suporte` e `nao_suportado` (`services/relatorios_periodo.py`) — o que
 *  cada número conta, por que dá (ou não dá) para confiar nele e o cuidado ao ler —,
 *  sem nome de campo, de tabela ou de seção da especificação. Chave que esta lista
 *  não conhece cai no texto do backend. */
interface ExplicacaoNumero { nome: string; explicacao: string; cuidado?: string }

const EXPLICACAO_ELEFANTE: Record<string, ExplicacaoNumero> = {
  livros_novos: {
    nome: "“Livros novos”",
    // A data do livro é a que a plataforma mostrava na PRIMEIRA importação dele (a
    // leitura mais recente naquele dia), não a da primeira leitura — e não muda.
    explicacao: "Conta cada livro que apareceu pela primeira vez no relatório da plataforma dentro do período. É "
      + "a mesma conta da premiação “Mais livros”: o relatório e o pódio mostram o mesmo número.",
    cuidado: "Vale a data em que o livro apareceu pela primeira vez no relatório da plataforma, e ela não muda "
      + "depois. Por isso um livro lido de novo não entra aqui — ele aparece em “Livros com atividade”, como relido.",
  },
  tempo_min: {
    nome: "“Tempo de leitura”",
    explicacao: "Soma o tempo dos livros novos do período. É a mesma conta da premiação “Mais tempo”.",
    cuidado: "A plataforma nem sempre informa o tempo de um livro; quando não informa, ele entra como zero. Por "
      + "isso o total é o mínimo lido no período — o tempo real pode ser maior.",
  },
  livros_com_atividade: {
    nome: "“Livros com atividade”",
    explicacao: "Conta os livros diferentes que o aluno abriu no período, inclusive os que ele releu, pela data "
      + "e hora que a plataforma registra em cada leitura.",
    // Sem "cuidado": o que colapsa no mesmo minuto é a contagem de VEZES que o livro
    // foi lido (que a tela não mostra); o número de livros diferentes não muda.
  },
  tempo_min_por_evento: {
    nome: "Tempo de cada leitura",
    explicacao: "Não dá para saber quanto durou cada leitura: a plataforma informa o tempo somado de cada livro, "
      + "não o de cada vez que o aluno o abriu, e esses totais às vezes até diminuem — o que um total somado não "
      + "faria. O tempo do período vem do tempo dos livros novos, o mesmo da premiação “Mais tempo”.",
  },
  questoes: {
    nome: "“Questões”",
    explicacao: "A plataforma só informa o total de questões que o aluno já respondeu desde que começou, sem a "
      + "data de cada uma. O número do período é a diferença entre a coleta do fim e a do início.",
    cuidado: "Só entra quem tem coleta no período; quem não tem fica fora da conta (não conta como zero). Sem "
      + "coleta no começo do período, a conta começa na primeira coleta; sem coleta no fim, termina na última — "
      + "nos dois casos o número não cobre o período inteiro, e o aviso de “Questões”, acima, diz quanto falta.",
  },
};

const EXPLICACAO_MATIFIC: ExplicacaoNumero = {
  nome: "“Atividades” e “Estrelas”",
  explicacao: "O Matific informa o total do ano (atividades e estrelas somadas), não a data de cada atividade. "
    + "O número do período é o total no fim menos o de antes do início — a mesma regra das premiações.",
  cuidado: "Sem coleta dentro do período, o aluno fica fora da conta (falta de dado não é zero) e é contado em "
    + "“Sem coleta na janela”.",
};

/** O que o relatório não responde, pela chave `plataforma.metrica` do backend. */
const EXPLICACAO_NAO_RESPONDE: Record<string, ExplicacaoNumero> = {
  "elefante.tempo_min_por_evento": {
    nome: "Tempo de cada leitura (Elefante Letrado)",
    explicacao: EXPLICACAO_ELEFANTE.tempo_min_por_evento.explicacao,
  },
  "matific.questoes": {
    nome: "Questões (Matific)",
    explicacao: "O Matific guarda atividades, estrelas e pontuação média, mas não conta questões. Mostrar esse "
      + "número para um período seria inventá-lo.",
  },
  "elefante.pontos_de_dificuldade": {
    nome: "Pontos de dificuldade (Elefante Letrado)",
    explicacao: "Quem se destaca pela dificuldade dos livros é decidido em Premiações, com a régua oficial. "
      + "Calcular de novo aqui criaria uma segunda régua, que poderia discordar do pódio: para mérito, use "
      + "Premiações.",
  },
};

/** A explicação de um número; sem entrada na lista, o texto que o backend mandou. */
function explicacaoDe(lista: Record<string, ExplicacaoNumero>, chave: string,
                      s: { por_que: string; ressalva?: string }): ExplicacaoNumero {
  return lista[chave] ?? { nome: chave.replace(/[._]/g, " "), explicacao: s.por_que, cuidado: s.ressalva };
}

function CartaoComoLer({ explicacao: e, classificacao }: { explicacao: ExplicacaoNumero; classificacao: Classificacao }) {
  return (
    <div className="rounded-2xl border border-zinc-200 p-4 dark:border-zinc-800">
      <p className="flex flex-wrap items-center gap-2">
        <strong className="text-zinc-800 dark:text-zinc-100">{e.nome}</strong>
        <Selo classificacao={classificacao} />
      </p>
      <p className="mt-1.5 text-xs text-zinc-600 dark:text-zinc-300">{e.explicacao}</p>
      {e.cuidado && (
        <p className="mt-1 text-xs text-ouro-700 dark:text-ouro-300">Cuidado ao ler: {e.cuidado}</p>
      )}
    </div>
  );
}

/* Caixas dos avisos de cobertura (a FORMA mudou; o texto é o mesmo de antes). */
const CAIXA_ALERTA =
  "rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3 text-xs text-zinc-800 dark:border-ouro-400/25 dark:bg-ouro-400/10 dark:text-zinc-100";
const CAIXA_INFO =
  "rounded-2xl border border-zinc-200 bg-zinc-50 px-4 py-3 text-xs text-zinc-700 dark:border-zinc-800 dark:bg-zinc-800/40 dark:text-zinc-200";
const ICONE_ALERTA = "mt-0.5 shrink-0 text-ouro-700 dark:text-ouro-300";
const ICONE_INFO = "mt-0.5 shrink-0 text-sky-600 dark:text-sky-300";

/** Intervalo REAL que um número vindo de retratos cobre. Só aparece quando o
 *  backend o devolve — e ele só devolve quando houve retrato na janela. */
function AvisoJanelaEfetiva({ janela, titulo }: { janela: JanelaEfetiva; titulo: string }) {
  return (
    <p className={`flex gap-2 ${CAIXA_ALERTA}`}>
      <Info size={14} aria-hidden className={ICONE_ALERTA} />
      <span>
        <strong>{titulo}:</strong> a conta vai de{" "}
        {dataHora(janela.data_base_mais_antiga)} a {dataHora(janela.data_atual_mais_recente)} —{" "}
        {janela.observacao}.
      </span>
    </p>
  );
}

/** "2026-09-01" → "01/09/2026". Data do PERÍODO, já em dias de Brasília: não
 *  passa por conversão de fuso (um `new Date` a puxaria para 31/08). */
function diaDoPeriodo(iso: string | null): string {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return d && m && a ? `${d}/${m}/${a}` : iso;
}

/** O período PEDIDO é a referência; o que as coletas cobrem vem ao lado. Se
 *  não cobrem exatamente, a tela diz o que falta (ou sobra) e por quê — nunca
 *  troca uma coisa pela outra. Mesma regra do PDF (`_avisos_cobertura`). */
function AvisoCobertura({ cobertura: c, titulo }: { cobertura: Cobertura; titulo: string }) {
  const oficial = c.regra === "oficial_matific";
  const periodo = c.periodo_inicio
    ? `${diaDoPeriodo(c.periodo_inicio)} a ${diaDoPeriodo(c.periodo_fim)}`
    : `todo o histórico${c.periodo_fim_efetivo ? ` (até ${diaDoPeriodo(c.periodo_fim_efetivo)})` : ""}`;
  const emAndamento = !!(c.periodo_inicio && c.periodo_fim_efetivo && c.periodo_fim
    && c.periodo_fim_efetivo < c.periodo_fim);
  const pedido = emAndamento ? `${periodo} (em andamento, até hoje ${diaDoPeriodo(c.periodo_fim_efetivo)})` : periodo;
  // Sem coleta-base, a conta parte do início do contador da plataforma: "desde o
  // início do contador até …" (montar "de" + "o início" dava "de o início").
  const ate = dataHora(c.coleta_fim);
  const disponivel = c.coleta_inicio
    ? `${dataHora(c.coleta_inicio)} a ${ate}`
    : `desde o início do contador até ${ate}`;
  const medidoPelasColetas = c.coleta_inicio ? `de ${disponivel}` : disponivel;
  const coletaBase = c.coleta_inicio ? `a coleta-base, de ${dataHora(c.coleta_inicio)},` : "o início do contador";
  const medidos = c.alunos_medidos
    ?? c.alunos_cobertura_completa + c.alunos_cobertura_parcial + c.alunos_ampliados;
  const soInicio = c.alunos_sem_intervalo > 0
    && (c.alunos_sem_intervalo_so_inicio ?? 0) >= c.alunos_sem_intervalo;
  const naoVieram = c.alunos_questoes_nao_vieram ?? 0;
  const para = (n: number) => (n && n < medidos ? ` para ${numero(n)} aluno(s)` : "");

  if (c.status === "sem_intervalo") {
    return (
      <div role="status" className={`flex gap-2 ${CAIXA_ALERTA}`}>
        <Info size={14} aria-hidden className={ICONE_ALERTA} />
        <span>
          {oficial ? (
            <>
              <strong>{titulo}: sem intervalo medido para {pedido}.</strong> O 0 da regra oficial (a mesma das
              premiações) vem de uma única coleta por aluno no período e nenhuma antes — ele NÃO quer dizer que
              não houve atividade.
            </>
          ) : naoVieram > 0 ? (
            <>
              <strong>{titulo}: sem número para {pedido}.</strong> A plataforma não mandou as questões nas
              coletas do período (a equipe do Constela precisa ajustar a coleta dessa plataforma): sem elas,
              não há diferença a medir (não é zero).
            </>
          ) : soInicio ? (
            <>
              <strong>{titulo}: sem número para {pedido} ainda.</strong> A única coleta do período é a que mede
              o início; a próxima medirá o que veio depois (não é zero).
            </>
          ) : (
            <>
              <strong>{titulo}: sem número para {pedido}.</strong> Há uma única coleta por aluno no período e
              nenhuma antes — não existe diferença a medir (não é zero).
            </>
          )}
        </span>
      </div>
    );
  }
  if (c.status === "completa") {
    return (
      <p className={`flex gap-2 ${CAIXA_INFO}`}>
        <Info size={14} aria-hidden className={ICONE_INFO} />
        <span>
          <strong>{titulo}:</strong> período solicitado {pedido}, medido pelas coletas {medidoPelasColetas}.
          {c.em_andamento && ` Em andamento: os dados vão até a coleta de ${dataHora(c.coleta_fim)}.`}
        </span>
      </p>
    );
  }
  if (c.status === "regra_oficial") {
    return (
      <p className={`flex gap-2 ${CAIXA_INFO}`}>
        <Info size={14} aria-hidden className={ICONE_INFO} />
        <span>
          <strong>{titulo}:</strong> período solicitado {pedido}. O número segue a regra oficial do Matific (a
          mesma das premiações): diferença entre {coletaBase} e a última coleta considerada, de {ate} — as
          bordas do período não são verificadas aqui.
        </span>
      </p>
    );
  }
  const ampliada = c.status === "ampliada";
  const antecedencia = c.antecedencia_max_horas == null ? ""
    : c.antecedencia_max_horas < 48 ? `${c.antecedencia_max_horas} h` : `${Math.floor(c.antecedencia_max_horas / 24)} dias`;
  return (
    <div role="status" className={CAIXA_ALERTA}>
      <p className="flex gap-2 font-semibold">
        <Info size={14} aria-hidden className={ICONE_ALERTA} />
        {ampliada
          ? `${titulo}: o valor INCLUI atividade de antes do período — não é só o período pedido.`
          : `${titulo}: cobertura parcial — o valor NÃO representa o período completo.`}
      </p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-xl bg-white/70 px-3 py-2 dark:bg-zinc-900/40">
        <dt className="font-medium">Período solicitado</dt>
        <dd>{pedido}</dd>
        <dt className="font-medium">Intervalo medido pelas coletas</dt>
        <dd>{disponivel}</dd>
      </dl>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {!c.inicio_coberto && c.alunos_sem_inicio > 0 && (
          c.inicio_do_contador_anual && !c.coleta_inicio_mais_tardio ? (
            <li>O contador do Matific é do ano letivo: o que veio antes de 01/01 não entra na conta.</li>
          ) : (
            <li>
              Sem coleta no início do período{para(c.alunos_sem_inicio)}: o que foi feito de{" "}
              {diaDoPeriodo(c.periodo_inicio)} até a primeira coleta
              {c.coleta_inicio_mais_tardio ? ` (até ${dataHora(c.coleta_inicio_mais_tardio)})` : ""} não está na
              conta: o contador que o Constela coleta é acumulado desde o início da conta e não diz quando cada
              questão foi respondida, então esse trecho não sai das coletas
              {c.acumulado_na_primeira_coleta
                ? ` (a primeira coleta já trazia ${numero(c.acumulado_na_primeira_coleta)} questões acumuladas, de datas que o contador não informa)`
                : ""}.
              {!oficial && " O Elefante guarda o histórico datado por aluno (Questões Respondidas), que o Constela ainda não coleta."}
            </li>
          )
        )}
        {!c.fim_coberto && c.alunos_sem_fim > 0 && (
          <li>
            A última coleta{para(c.alunos_sem_fim)} é de {dataHora(c.coleta_fim_mais_cedo ?? c.coleta_fim)}: o que
            veio depois, até {diaDoPeriodo(c.periodo_fim_efetivo ?? c.periodo_fim)}, não está na conta.
          </li>
        )}
        {c.inclui_antes_do_inicio && (
          <li>
            Não há coleta perto do início{para(c.alunos_ampliados)}:{" "}
            {c.coleta_inicio ? `a coleta-base é de ${dataHora(c.coleta_inicio)}` : "a conta parte do início do contador"}
            {antecedencia ? `, ${antecedencia} antes de ${diaDoPeriodo(c.periodo_inicio)}` : ""} — o número INCLUI
            a atividade desse intervalo.
          </li>
        )}
        {c.alunos_sem_intervalo > 0 && (
          <li>
            {oficial
              ? `${numero(c.alunos_sem_intervalo)} aluno(s) com uma única coleta no período entram com 0 pela regra oficial (a mesma das premiações): esse 0 não mede o período.`
              : soInicio
                ? `${numero(c.alunos_sem_intervalo)} aluno(s) só têm a coleta que mede o início do período — a próxima medirá o que veio depois; até lá ficam fora da conta (não contam como zero).`
                : `${numero(c.alunos_sem_intervalo)} aluno(s) com uma única coleta no período ficam fora da conta (não contam como zero).`}
          </li>
        )}
        {(c.alunos_contador_regrediu ?? 0) > 0 && (
          <li>
            {numero(c.alunos_contador_regrediu ?? 0)} aluno(s) com o contador da plataforma DIMINUINDO no período
            (contas trocadas ou fundidas na mesma ficha) ficam fora da conta.
          </li>
        )}
        {(c.alunos_sem_coleta_no_periodo ?? 0) > 0 && (
          <li>
            {numero(c.alunos_sem_coleta_no_periodo ?? 0)} aluno(s) coletados antes e depois do período, mas sem
            nenhuma coleta dentro dele, ficam fora da conta.
          </li>
        )}
        {(c.alunos_coleta_interrompida ?? 0) > 0 && (
          <li>
            {numero(c.alunos_coleta_interrompida ?? 0)} aluno(s) coletados antes do período e sem nenhuma coleta
            que entre na conta (a coleta parou ou falhou para eles) ficam fora da conta.
          </li>
        )}
        {(c.turmas_sem_coleta?.length ?? 0) > 0 && (
          <li>
            Turma(s) sem nenhuma coleta no período, fora da conta:{" "}
            {c.turmas_sem_coleta!.map((t) => t.turma ?? `#${t.turma_id}`).join(", ")}.
          </li>
        )}
        {naoVieram > 0 && (
          <li>
            {numero(naoVieram)} aluno(s) com coleta no período em que a plataforma não mandou as questões (a
            equipe do Constela precisa ajustar a coleta dessa plataforma): essa coleta não mede as questões, e a
            conta deles vai só até a coleta anterior, ou fica fora dela.
          </li>
        )}
      </ul>
    </div>
  );
}

/** Os cartões de indicador (4 do Elefante e 4 do Matific): 2 por linha já no celular,
 *  com recuo e espaço menores abaixo de 640 px (em uma coluna eram ~1.600 px de rolagem
 *  antes das tabelas). O recuo vem pelo filho direto: o StatCard não recebe classe. */
const GRADE_INDICADORES = "grid grid-cols-2 gap-3 sm:gap-5 xl:grid-cols-4 max-sm:[&>*]:p-4";

/* Tabelas "Por turma" e "Por aluno" (até oito colunas). Mais compactas que a
 * `classesTabela` padrão para as colunas do Matific (Atividades, Estrelas) caberem
 * inteiras já a partir de 768 px:
 *   - menos espaço entre colunas e cabeçalho sem espaçamento extra entre as letras
 *     abaixo de 1024 px;
 *   - o cabeçalho de duas palavras pode quebrar ("Livros / novos") quando falta
 *     largura — com largura sobrando ele fica numa linha só, como antes;
 *   - número nunca se parte (whitespace-nowrap), sempre alinhado à direita.
 * A primeira e a última coluna mantêm a margem de 16 px da borda do cartão. */
const TH_TABELA =
  "px-2.5 py-3 text-left align-bottom text-[11px] font-semibold uppercase leading-snug tracking-normal text-zinc-500 first:pl-4 last:pr-4 lg:px-3 lg:tracking-[0.08em] dark:text-zinc-400";
const TD_TABELA = "px-2.5 py-3.5 text-zinc-700 first:pl-4 last:pr-4 lg:px-3 dark:text-zinc-200";

export default function RelatorioPeriodo() {
  // O PERÍODO é global (AppContext): o recorte que o gestor escolheu aqui
  // continua valendo nos rankings e nas premiações, e vice-versa — é a mesma
  // pergunta ("qual janela?") e seria ruído pedi-la de novo em cada tela.
  const { escolaId, periodo, definirPeriodo } = useApp();
  const [plataformas, setPlataformas] = useState<string>("elefante,matific");
  const [turmaId, setTurmaId] = useState<number | null>(null);
  const [alunoId, setAlunoId] = useState<number | null>(null);

  const { dados: turmas } = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const { dados: paginaAlunos } = useApi<PaginaAlunos>(
    escolaId && turmaId ? `/escolas/${escolaId}/alunos?por_pagina=500&turma_id=${turmaId}` : null,
  );

  const escopo = alunoId ? "aluno" : turmaId ? "turma" : "escola";
  // Personalizado sem as DUAS datas devolveria 422: a tela espera o gestor
  // terminar de escolher em vez de mostrar um erro que ele já sabe.
  const personalizadoIncompleto =
    periodo.preset === "personalizado" && !(periodo.inicio && periodo.fim);

  // UMA query para os DOIS formatos. A tela e o PDF não podem divergir de
  // filtro: se o botão montasse a própria URL, bastaria alguém mexer num
  // seletor para o papel sair de um recorte e a tela mostrar outro.
  const consulta = useMemo(() => {
    if (!escolaId || personalizadoIncompleto) return null;
    const q = new URLSearchParams(periodoParaQuery(periodo));
    for (const p of plataformas.split(",")) q.append("plataformas", p);
    q.set("escopo", escopo);
    if (turmaId) q.set("turma_id", String(turmaId));
    if (alunoId) q.set("aluno_id", String(alunoId));
    return q.toString();
  }, [escolaId, periodo, plataformas, escopo, turmaId, alunoId, personalizadoIncompleto]);

  const url = consulta ? `/escolas/${escolaId}/relatorios/periodo?${consulta}` : null;
  const urlPdf = consulta ? `/escolas/${escolaId}/relatorios/periodo.pdf?${consulta}` : null;

  const { dados, erro, carregando, recarregar } = useApi<RelatorioPeriodoT>(url);

  // O PDF é gerado sob demanda e devolvido na resposta — nada é guardado no
  // servidor. Quem nomeia o arquivo é o backend (Content-Disposition).
  const [gerandoPdf, setGerandoPdf] = useState(false);
  const [erroPdf, setErroPdf] = useState("");
  // Mudou o recorte? O erro do recorte anterior deixou de valer.
  useEffect(() => { setErroPdf(""); }, [consulta]);

  async function gerarPdf() {
    if (!urlPdf || gerandoPdf) return;
    setGerandoPdf(true);
    setErroPdf("");
    try {
      await apiDownload(urlPdf);
    } catch (excecao) {
      setErroPdf(excecao instanceof Error ? excecao.message
                                          : "Não foi possível gerar o PDF.");
    } finally {
      setGerandoPdf(false);
    }
  }

  const ele = dados?.elefante;
  const mat = dados?.matific;
  // Uma coleta só por aluno: a regra oficial dá 0, mas esse 0 não mede o período.
  const matSemMedida = mat?.cobertura?.status === "sem_intervalo";
  // O espelho de eventos nasceu na migração 0010: janela anterior a ele devolve
  // zero por FALTA DE HISTÓRICO, não por inatividade. Dizer isso é o que separa
  // "ninguém leu" de "o sistema ainda não registrava".
  const antesDoHistorico =
    ele?.primeiro_evento_da_escola && dados?.periodo.inicio
      ? dados.periodo.inicio < ele.primeiro_evento_da_escola
      : false;

  // Ao trocar o recorte, o relatório anterior fica na tela até o novo chegar: o aviso
  // "Atualizando" diz que os números ainda são do recorte de antes.
  const atualizando = carregando && Boolean(dados);
  const rotuloFiltro = "mb-1.5 block text-xs font-semibold text-zinc-600 dark:text-zinc-300";
  // Coluna flex: o campo vira item de flex (sem a folga de linha de um elemento
  // inline embaixo), então os quatro rótulos ficam na mesma altura.
  const campoFiltro = "flex min-w-0 max-w-full flex-col items-start";
  const th = (direita = false) => `${TH_TABELA} ${direita ? "text-right" : ""}`;
  const td = (direita = false) => `${TD_TABELA} ${direita ? "whitespace-nowrap text-right tabular-nums" : ""}`;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Relatório por Período"
        descricao="O que aconteceu numa janela de datas — do mês fechado ao intervalo que você escolher."
        acoes={
          <Botao
            onClick={gerarPdf}
            disabled={!urlPdf || gerandoPdf || carregando}
            aria-busy={gerandoPdf}
          >
            <FileDown size={15} aria-hidden />
            {gerandoPdf ? "Gerando PDF..." : "Gerar PDF"}
          </Botao>
        }
      />
      {erroPdf && <Mensagem tipo="erro">{erroPdf}</Mensagem>}

      <Card className="p-5">
        <div className="mb-4 flex items-center gap-2.5">
          <IconePastel icone={SlidersHorizontal} tom="violeta" tamanho="sm" />
          <RotuloSecao>Recorte do relatório</RotuloSecao>
        </div>
        {/* Os quatro filtros com a MESMA pílula da v2 (ícone, chevron, 40 px de altura):
            antes só o Período tinha esse estilo e os outros três usavam a seta nativa,
            com outra borda e outra altura, desalinhando a linha. Continuam <select>
            nativos (mesmos ids, rótulos e opções). */}
        <div className="flex flex-wrap items-end gap-4">
          <div className={campoFiltro}>
            <label className={rotuloFiltro}>Período</label>
            <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
          </div>
          <div className={campoFiltro}>
            <label htmlFor="rp-plataformas" className={rotuloFiltro}>
              Plataforma
            </label>
            <MolduraPilula icone={Layers}>
              <select
                id="rp-plataformas"
                className={estiloSelectPilula}
                value={plataformas}
                onChange={(e) => setPlataformas(e.target.value)}
              >
                {PLATAFORMAS.map((p) => (
                  <option key={p.valor} value={p.valor}>{p.rotulo}</option>
                ))}
              </select>
            </MolduraPilula>
          </div>
          <div className={campoFiltro}>
            <label htmlFor="rp-turma" className={rotuloFiltro}>
              Turma
            </label>
            <MolduraPilula icone={Users}>
              <select
                id="rp-turma"
                className={estiloSelectPilula}
                value={turmaId ?? ""}
                onChange={(e) => {
                  setTurmaId(e.target.value ? Number(e.target.value) : null);
                  setAlunoId(null);
                }}
              >
                <option value="">Toda a escola</option>
                {(turmas ?? []).map((t) => (
                  <option key={t.id} value={t.id}>{t.nome}</option>
                ))}
              </select>
            </MolduraPilula>
          </div>
          <div className={campoFiltro}>
            <label htmlFor="rp-aluno" className={rotuloFiltro}>
              Aluno
            </label>
            <MolduraPilula icone={UserRound}>
              <select
                id="rp-aluno"
                className={estiloSelectPilula}
                value={alunoId ?? ""}
                disabled={!turmaId}
                onChange={(e) => setAlunoId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Toda a turma</option>
                {(paginaAlunos?.itens ?? []).map((a) => (
                  <option key={a.id} value={a.id}>{a.nome}</option>
                ))}
              </select>
            </MolduraPilula>
          </div>
        </div>
        {personalizadoIncompleto && (
          <p className="mt-4 flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300">
            <CalendarRange size={14} aria-hidden className="shrink-0 text-indigo-500" />
            Escolha a data inicial e a final para gerar o relatório personalizado.
          </p>
        )}
      </Card>

      {erro && !dados && (
        <Card className="p-2">
          <Erro titulo="Não foi possível montar o relatório" descricao={erro.message} aoTentar={recarregar} />
        </Card>
      )}
      {erro && dados && <Mensagem tipo="erro">{erro.message}</Mensagem>}
      {carregando && !dados && (
        <div className="space-y-5" aria-busy="true">
          <p className="sr-only" role="status">Montando o relatório...</p>
          <Skeleton className="h-28 rounded-cartao" />
          <div className={GRADE_INDICADORES}>
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36 rounded-cartao" />)}
          </div>
        </div>
      )}

      {dados && (
        <>
          <Card className="p-6">
            <div className="flex flex-wrap items-center justify-between gap-5">
              <div className="flex min-w-0 items-start gap-4">
                <IconePastel icone={CalendarRange} tom="violeta" tamanho="lg" />
                <div className="min-w-0">
                  <p className="flex flex-wrap items-baseline gap-x-2 text-lg font-bold tracking-tight text-zinc-900 dark:text-white">
                    <span>{dados.periodo.rotulo}</span>
                    {/* No celular a data vai para a linha própria, sem o "·" na frente
                        (antes a linha quebrada começava pelo separador). */}
                    {dados.periodo.inicio && (
                      <span className="text-sm font-medium text-zinc-500 max-sm:basis-full dark:text-zinc-400">
                        <span className="max-sm:hidden">· </span>{diaDoPeriodo(dados.periodo.inicio)} a {diaDoPeriodo(dados.periodo.fim)}
                      </span>
                    )}
                  </p>
                  {/* Ícone e texto lado a lado, sem quebra entre eles: com flex-wrap o
                      texto longo descia inteiro e o ícone ficava sozinho na linha de cima. */}
                  <p className="mt-1 flex items-start gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                    <School size={13} aria-hidden className="mt-px shrink-0" />
                    <span className="min-w-0">
                      {dados.plataformas_rotulo} · {dados.escola.nome} · ano letivo {dados.escola.ano_letivo}
                      {dados.periodo.inclusivo && " · intervalo inclusivo nas duas datas"}
                    </span>
                  </p>
                  {atualizando && (
                    <p role="status" className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
                      <Loader2 size={13} aria-hidden className="animate-spin motion-reduce:animate-none" />
                      Atualizando o relatório…
                    </p>
                  )}
                </div>
              </div>
              <p className="rounded-2xl bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-300">
                <strong className="mr-0.5 text-2xl font-bold tabular-nums text-zinc-900 dark:text-white">
                  {numero(dados.alunos.considerados)}
                </strong>{" "}
                {dados.alunos.considerados === 1 ? "aluno ativo" : "alunos ativos"} no recorte ·{" "}
                {numero(dados.alunos.com_atividade)} com atividade
              </p>
            </div>
            {dados.escopo.restrito_a_turmas && (
              <p className="mt-4 text-xs text-zinc-500 dark:text-zinc-400">
                Você vê as turmas vinculadas ao seu cadastro ({dados.escopo.restrito_a_turmas.length}).
              </p>
            )}
            {antesDoHistorico && (
              <p className={`mt-4 flex gap-2 ${CAIXA_ALERTA}`}>
                <Info size={14} aria-hidden className={ICONE_ALERTA} />
                <span>
                  O histórico de atividade desta escola começa em{" "}
                  {dataHora(ele?.primeiro_evento_da_escola ?? null)}. Antes disso o relatório
                  mostra zero por <strong>falta de registro</strong>, não por inatividade.
                </span>
              </p>
            )}
          </Card>

          {ele && (
            <section className="space-y-4">
              <div className="flex items-center gap-3">
                <IconePlataforma plataforma="elefante" />
                <div>
                  <h2 className="text-lg font-bold tracking-tight text-zinc-900 dark:text-white">Elefante Letrado</h2>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">Leitura</p>
                </div>
              </div>
              <div className={GRADE_INDICADORES}>
                <StatCard
                  tom="violeta"
                  icone={<BookOpen size={20} />}
                  rotulo="Livros novos"
                  valor={numero(ele.livros_novos)}
                  detalhe={`${numero(ele.alunos_com_livro_novo)} aluno(s) · mesmo número da premiação`}
                />
                <StatCard
                  tom="violeta"
                  icone={<Clock size={20} />}
                  rotulo="Tempo de leitura"
                  valor={tempoLeitura(ele.tempo_min)}
                  detalhe="tempo informado por livro novo"
                />
                <StatCard
                  tom="violeta"
                  icone={<RefreshCw size={20} />}
                  rotulo="Livros com atividade"
                  valor={numero(ele.livros_com_atividade)}
                  detalhe={`${numero(ele.livros_relidos)} relido(s) · inclui releitura`}
                />
                <StatCard
                  tom="violeta"
                  icone={<Sigma size={20} />}
                  rotulo="Questões"
                  valor={
                    ele.questoes_tentativas === null
                      ? "—"
                      // Espaço de largura zero depois da barra: no cartão estreito do
                      // celular "1.234/2.345" quebra depois da barra em vez de vazar.
                      : `${numero(ele.questoes_acertos ?? 0)}/\u200B${numero(ele.questoes_tentativas)}`
                  }
                  detalhe={[
                    ele.cobertura_questoes?.status === "parcial" && "cobertura parcial do período — veja o aviso",
                    ele.cobertura_questoes?.status === "ampliada" && "inclui antes do período — veja o aviso",
                    ele.alunos_sem_retrato > 0
                      && `${numero(ele.alunos_sem_retrato)} sem coleta na janela (não contam como zero)`,
                  ].filter(Boolean).join(" · ") || "acertos sobre tentativas"}
                />
              </div>
              {ele.cobertura_questoes ? (
                <AvisoCobertura cobertura={ele.cobertura_questoes} titulo="Questões" />
              ) : ele.janela_efetiva_questoes && (
                <AvisoJanelaEfetiva janela={ele.janela_efetiva_questoes} titulo="Questões" />
              )}
            </section>
          )}

          {mat && (
            <section className="space-y-4">
              <div className="flex items-center gap-3">
                <IconePlataforma plataforma="matific" />
                <div>
                  <h2 className="text-lg font-bold tracking-tight text-zinc-900 dark:text-white">Matific</h2>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">Matemática</p>
                </div>
              </div>
              <div className={GRADE_INDICADORES}>
                <StatCard
                  tom="teal"
                  icone={<Sigma size={20} />}
                  rotulo="Atividades"
                  valor={matSemMedida ? "—" : numero(mat.atividades)}
                  detalhe={matSemMedida
                    ? "sem intervalo medido — veja o aviso"
                    : mat.cobertura?.status === "parcial"
                      ? "cobertura parcial do período — veja o aviso"
                      : `${numero(mat.alunos_com_atividade)} aluno(s) com ganho no período`}
                />
                <StatCard
                  tom="teal"
                  icone={<Star size={20} />}
                  rotulo="Estrelas"
                  valor={matSemMedida ? "—" : numero(mat.estrelas)}
                  detalhe={matSemMedida ? "sem intervalo medido — veja o aviso" : "ganho entre coletas"}
                />
                <StatCard
                  tom="neutro"
                  icone={<Info size={20} />}
                  rotulo="Sem coleta na janela"
                  valor={numero(mat.alunos_sem_retrato)}
                  detalhe="ausência de dado, não zero"
                />
                <StatCard
                  tom="neutro"
                  icone={<Sigma size={20} />}
                  rotulo="Questões"
                  valor="—"
                  detalhe="não existe este contador no Matific"
                />
              </div>
              {mat.cobertura ? (
                <AvisoCobertura cobertura={mat.cobertura} titulo="Matific" />
              ) : mat.janela_efetiva && (
                <AvisoJanelaEfetiva janela={mat.janela_efetiva} titulo="Matific" />
              )}
            </section>
          )}

          <SecaoRecolhivel
            titulo="Como ler estes números"
            icone={<IconePastel icone={Info} tom="azul" tamanho="sm" />}
            inicialAberto={false}
          >
            <div className="space-y-5 text-sm">
              {ele && (
                <div className="space-y-2.5">
                  <RotuloSecao>Elefante Letrado</RotuloSecao>
                  {Object.entries(ele.suporte).map(([chave, s]) => (
                    <CartaoComoLer key={chave} explicacao={explicacaoDe(EXPLICACAO_ELEFANTE, chave, s)}
                                   classificacao={s.classificacao} />
                  ))}
                </div>
              )}
              {mat && (
                <div className="space-y-2.5">
                  <RotuloSecao>Matific</RotuloSecao>
                  <CartaoComoLer explicacao={EXPLICACAO_MATIFIC} classificacao={mat.suporte.classificacao} />
                </div>
              )}
              {dados.nao_suportado.length > 0 && (
                <div className="space-y-2.5">
                  <RotuloSecao>O que este relatório NÃO responde</RotuloSecao>
                  {dados.nao_suportado.map((n) => {
                    const e = explicacaoDe(EXPLICACAO_NAO_RESPONDE, `${n.plataforma}.${n.metrica}`, n);
                    return (
                      <div key={`${n.plataforma}-${n.metrica}`} className="rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/50">
                        <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">{e.nome}</p>
                        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">{e.explicacao}</p>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </SecaoRecolhivel>

          {dados.por_turma && dados.por_turma.length > 0 && (
            <Card className="overflow-hidden">
              <div className="flex items-center gap-3 px-6 pb-2 pt-5">
                <IconePastel icone={Users} tom="azul" tamanho="sm" />
                <h2 className="text-[17px] font-semibold text-zinc-900 dark:text-white">Por turma</h2>
              </div>
              <TabelaRolavel rotulo="Tabela por turma">
                <table className={classesTabela.tabela}>
                  <thead>
                    <tr>
                      <th className={th()}>Turma</th>
                      <th className={th(true)}>Alunos</th>
                      <th className={th(true)}>Com atividade</th>
                      {ele && <th className={th(true)}>Livros novos</th>}
                      {ele && <th className={th(true)}>Tempo</th>}
                      {ele && <th className={th(true)}>Relidos</th>}
                      {mat && <th className={th(true)}>Atividades</th>}
                      {mat && <th className={th(true)}>Estrelas</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {dados.por_turma.map((t) => (
                      <tr key={t.turma_id} className={classesTabela.tr}>
                        <td className={td()}>
                          {/* O turno desce para baixo do chip quando falta largura. */}
                          <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                            <Chip className="whitespace-nowrap">{t.turma}</Chip>
                            <span className="text-xs text-zinc-500 dark:text-zinc-400">{t.turno ?? ""}</span>
                          </span>
                        </td>
                        <td className={td(true)}>{numero(t.alunos)}</td>
                        <td className={td(true)}>{numero(t.com_atividade)}</td>
                        {ele && <td className={td(true)}>{numero(t.elefante.livros_novos)}</td>}
                        {ele && <td className={td(true)}>{tempoLeitura(t.elefante.tempo_min)}</td>}
                        {ele && <td className={td(true)}>{numero(t.elefante.livros_relidos)}</td>}
                        {mat && <td className={td(true)}>{numero(t.matific.atividades)}</td>}
                        {mat && <td className={td(true)}>{numero(t.matific.estrelas)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TabelaRolavel>
            </Card>
          )}

          <Card className="overflow-hidden">
            <div className="flex items-center gap-3 px-6 pb-2 pt-5">
              <IconePastel icone={Users} tom="violeta" tamanho="sm" />
              <h2 className="text-[17px] font-semibold text-zinc-900 dark:text-white">Por aluno</h2>
            </div>
            {dados.por_aluno.length === 0 ? (
              <Vazio icone={Users} titulo="Nenhum aluno no recorte" descricao="Confira a turma escolhida e o ano letivo." />
            ) : (
              <TabelaRolavel rotulo="Tabela por aluno">
                <table className={classesTabela.tabela}>
                  <thead>
                    <tr>
                      {/* A turma vai no chip sob o nome (era uma coluna à parte): a coluna a
                          menos é o que deixa Atividades e Estrelas caberem a partir de 768 px. */}
                      <th className={th()}>Aluno</th>
                      {ele && <th className={th(true)}>Livros novos</th>}
                      {ele && <th className={th(true)}>Tempo</th>}
                      {ele && <th className={th(true)}>Com atividade</th>}
                      {ele && <th className={th(true)}>Relidos</th>}
                      {mat && <th className={th(true)}>Atividades</th>}
                      {mat && <th className={th(true)}>Estrelas</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {dados.por_aluno.map((a) => (
                      <tr key={a.aluno_id} className={classesTabela.tr}>
                        <td className={td()}>
                          {/* No celular o avatar decorativo sai e o nome fica mais estreito
                              (até duas linhas): cabe mais uma coluna numérica à vista. */}
                          <span className="flex min-w-[10rem] items-center gap-2.5 max-sm:min-w-[8.5rem]">
                            <Avatar nome={a.nome} chave={a.aluno_id} tamanho="sm" className="max-sm:hidden" />
                            <span className="min-w-0">
                              <span className={`block font-medium ${a.sem_atividade ? "text-zinc-500 dark:text-zinc-400" : "text-zinc-900 dark:text-zinc-100"}`}>{a.nome}</span>
                              <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                                <Chip className="whitespace-nowrap">{a.turma}</Chip>
                                {a.sem_atividade && (
                                  <span className="text-[11px] text-zinc-500 dark:text-zinc-400">sem atividade no período</span>
                                )}
                              </span>
                            </span>
                          </span>
                        </td>
                        {ele && <td className={td(true)}>{numero(a.elefante?.livros_novos ?? 0)}</td>}
                        {ele && <td className={td(true)}>{tempoLeitura(a.elefante?.tempo_min ?? 0)}</td>}
                        {ele && <td className={td(true)}>{numero(a.elefante?.livros_com_atividade ?? 0)}</td>}
                        {ele && <td className={td(true)}>{numero(a.elefante?.livros_relidos ?? 0)}</td>}
                        {mat && <td className={td(true)}>{numero(a.matific?.atividades ?? 0)}</td>}
                        {mat && <td className={td(true)}>{numero(a.matific?.estrelas ?? 0)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TabelaRolavel>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
