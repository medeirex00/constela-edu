/**
 * Importações (PRD §15–§16, §50–§52): envio de PDF ou texto colado,
 * prévia com erros ANTES de gravar e correspondência de nomes.
 *
 * A prévia é AGRUPADA por aluno: o relatório individual do Elefante (uma
 * linha por livro) vira UMA entrada ("N livros lidos"). A turma lida do
 * cabeçalho do PDF é usada para casar/criar o aluno sem intervenção manual.
 */
import {
  AlertTriangle,
  BookMarked,
  CheckCircle2,
  FileUp,
  History,
  Layers,
  Pencil,
  Sparkles,
  UserPlus,
  Users,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import ImportacaoMatriculas from "./ImportacaoMatriculas";
import { identidadeDe, PilulaPlataforma } from "../components/identidadePlataforma";
import { PassosImportacao } from "../components/PassosImportacao";
import SeletorAlunoDrawer from "../components/SeletorAlunoDrawer";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Avatar,
  Badge,
  Botao,
  Campo,
  Card,
  Confirmacao,
  Erro,
  IconePastel,
  Mensagem,
  PageHeader,
  Skeleton,
  Vazio,
  classesAbas,
  classesTabela,
  estiloInput,
  useAbaAtivaVisivel,
  type TomPastel,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useImportacaoLote } from "../context/ImportacaoLoteContext";
import { useApi } from "../hooks/useApi";
import { api, apiUpload } from "../lib/api";
import {
  dataDoRelatorioValida,
  diaPorExtenso,
  exigeDataDoRelatorio,
  hojeEmBrasilia,
  instanteDoRelatorio,
  primeiroDiaDoRelatorio,
  problemaDaDataDoRelatorio,
} from "../lib/dataRelatorio";
import { dataHora, numero } from "../lib/formato";
import { acharTurmaPorNome, etapaDaSala, normalizar } from "../lib/nomes";
import ImportacaoLote from "./ImportacaoLote";
import type { Aluno, Analise, Importacao, LinhaAnalise, ResultadoImportacao, Turma } from "../lib/types";

const ROTULOS_DADOS: Record<string, string> = {
  atividades: "Atividades",
  pontuacao_media: "Média",
  estrelas: "Estrelas",
  livros_unicos: "Livros",
  tempo_leitura_min: "Tempo (min)",
  questoes_tentativas: "Questões",
  questoes_acertos: "Acertos",
  livros_por_nivel: "Níveis",
  livro: "Livro",
  nivel: "Nível",
};

// Fora da coluna Dados também o que é técnico: a conta da plataforma (uuid/studentId —
// contas diferentes com o mesmo nome já aparecem como "conta 1 de 2") e as marcas
// internas do leitor (nome_incompleto, turma_ambigua), que a coluna Correspondência
// explica em linguagem simples.
const OCULTAR_NA_PREVIA = new Set([
  "turma_relatorio", "livro", "nivel", "genero", "data", "tempo_livro_min",
  "matific_uuid", "elefante_student_id", "nome_incompleto", "turma_ambigua",
]);

/** O seletor "Destino de …" da prévia na largura da sua opção mais longa ("Matheus
 *  Cardoso Oliveira — 4º Ano A (100%)"), nunca cortado. Com o "w-full" do campo
 *  padrão, a largura em % não conta na largura mínima da coluna da tabela, e a coluna
 *  ficava no piso de 12rem, cortando o nome do vinculado. Com "w-auto" a coluna
 *  cresce até caber; se a tabela não couber, a moldura rola de lado (como no celular). */
const estiloSeletorDestino = estiloInput.replace("w-full", "w-auto");

/** Número no formato brasileiro ("85,5", "1.234"), como no resto do sistema. */
function valorDoDado(valor: unknown): string {
  return typeof valor === "number" ? numero(valor) : String(valor);
}

/** Como o nome do aluno foi identificado (define ícone, cor e texto do card). */
const METODO_IDENTIFICACAO: Record<
  string,
  { Icone: LucideIcon; tom: TomPastel; corTexto: string; classe: string; texto: string }
> = {
  arquivo: {
    Icone: CheckCircle2,
    tom: "verde",
    corTexto: "text-emerald-700 dark:text-emerald-300",
    classe: "border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/20 dark:bg-emerald-500/5",
    texto: "Aluno identificado pelo nome do arquivo",
  },
  conteudo: {
    Icone: AlertTriangle,
    tom: "ambar",
    corTexto: "text-ouro-700 dark:text-ouro-300",
    classe: "border-ouro-200 bg-ouro-50/70 dark:border-ouro-400/20 dark:bg-ouro-400/5",
    texto: "Aluno identificado pelo conteúdo do PDF",
  },
  nenhum: {
    Icone: XCircle,
    tom: "rosa",
    corTexto: "text-rose-700 dark:text-rose-300",
    classe: "border-rose-200 bg-rose-50/60 dark:border-rose-500/20 dark:bg-rose-500/5",
    texto: "Não foi possível identificar o aluno automaticamente",
  },
};

/** As etapas do envio individual (o passo a passo do topo). */
const PASSOS_INDIVIDUAL = ["Enviar o relatório", "Conferir a prévia", "Confirmar e gravar"] as const;

const MODOS_IMPORTACAO = [
  { valor: "individual", Icone: FileUp, rotulo: "Um por vez" },
  { valor: "lote", Icone: Layers, rotulo: "Em lote" },
  { valor: "matriculas", Icone: Users, rotulo: "Matrículas da escola" },
] as const;

function resumoDados(dados: Record<string, unknown>): string {
  return Object.entries(dados)
    .filter(([chave]) => !OCULTAR_NA_PREVIA.has(chave))
    .map(([chave, valor]) => {
      const rotulo = ROTULOS_DADOS[chave] ?? chave;
      if (chave === "livros_por_nivel" && valor && typeof valor === "object") {
        const pares = Object.entries(valor as Record<string, number>)
          .map(([codigo, qtd]) => `${codigo}:${valorDoDado(qtd)}`)
          .join(" ");
        return `${rotulo}: ${pares || "—"}`;
      }
      return `${rotulo}: ${valorDoDado(valor)}`;
    })
    .join(" · ");
}

type Acao =
  | { tipo: "importar"; alunoId: number; alunoNome?: string; turmaNome?: string; manual?: boolean }
  | { tipo: "criar"; turmaId: number | null }
  // Turma lida do relatório que AINDA NÃO EXISTE: a confirmação a cria e
  // matricula o aluno nela (primeiro import sem cadastrar turmas antes).
  | { tipo: "criar_nova" }
  // "Deixar para a Revisão": a linha vai com ``deixar_para_revisao`` — o backend nunca
  // associa nem cria nela, ainda que o contexto mude desde a prévia (a outra conta de
  // uma disputa ignorada, por exemplo). Antes ia o corpo de um "Criar" (a turma da
  // linha), e o backend criava a ficha quando, sozinho, decidia criar. ``turmaNome``:
  // a turma do relatório, só como contexto da pendência (é a que a prévia leu).
  | { tipo: "revisao"; turmaNome: string | null }
  // ``manual``: o gestor escolheu "Ignorar" (linha de teste, conta de professor…) —
  // "Aplicar a todos" não o desfaz. Sem ele, é o "Ignorar" padrão (aluno novo sem
  // turma, que ninguém escolheu).
  | { tipo: "ignorar"; manual?: boolean };

/** Motivos de revisão (``identidade_aluno.decidir``) em que a confirmação NUNCA cria
 *  a ficha, qualquer que seja a turma escolhida: o motor manda a linha para Revisões
 *  de identidade e um "Criar" seria ignorado. Só a escolha de um aluno da lista
 *  (vínculo explícito) muda o destino — menos na conta de um aluno de outra escola,
 *  em que só o Admin Global confirma o vínculo (``vinculoVaiParaRevisao``). Ficam de
 *  fora os motivos de TURMA
 *  (turma_ambigua, turma_arquivada, turma_fora_do_ano_letivo…): neles a turma
 *  escolhida na tela resolve e a ficha nasce. */
const MOTIVOS_SO_REVISAO = new Set([
  "nome_incompleto",
  "contas_repetidas_no_relatorio",
  "id_externo_duplicado",
  "identidade_de_outra_escola",
  "identidade_de_ficha_inativa",
  "identidade_de_outro_aluno",
  "outra_identidade_na_plataforma",
  "ra_repetido",
  "ficha_inativa",
  "correspondencia_insegura",
  "candidatos_multiplos",
  "homonimo_em_outra_sala",
  "nome_casa_em_outra_sala",
  "criacao_bloqueada_por_politica",
  "deixada_para_revisao",
]);

/** Cada motivo de revisão do backend (``identidade_aluno.MOTIVOS``) em linguagem
 *  simples: um rótulo curto para o selo da coluna Correspondência e uma explicação,
 *  ligada ao "Destino de …" (aria-describedby). Cada um diz o que é — nem todo
 *  motivo é "possível duplicata". O contrato com o backend
 *  (test_importacao_previa_motivo) confere que nenhum motivo fica sem rótulo. */
const MOTIVO_REVISAO: Record<string, { rotulo: string; explicacao: string }> = {
  nome_incompleto: {
    rotulo: "Nome abreviado",
    explicacao:
      "O relatório traz só parte do nome: não dá para saber quem é a criança nem criar a ficha com ele.",
  },
  contas_repetidas_no_relatorio: {
    rotulo: "Duas contas com o mesmo nome",
    explicacao:
      "Duas contas da plataforma vieram com este nome e nenhuma ficha corresponde: podem ser a mesma criança ou duas.",
  },
  correspondencia_insegura: {
    rotulo: "Nome parecido com o de um aluno",
    explicacao:
      "O nome lembra o de um aluno cadastrado, mas não o bastante para vincular sozinho: pode ser a mesma criança ou outra.",
  },
  candidatos_multiplos: {
    rotulo: "Mais de um aluno possível",
    explicacao: "Mais de um aluno cadastrado pode ser esta criança.",
  },
  homonimo_em_outra_sala: {
    rotulo: "Mesmo nome em outra turma",
    explicacao:
      "Há aluno com este nome em outra turma: pode ser a mesma criança, que mudou de sala, ou outra.",
  },
  nome_casa_em_outra_sala: {
    rotulo: "Nome parecido em outra turma",
    explicacao: "O nome corresponde a um aluno de outra turma, não da turma do relatório.",
  },
  ficha_inativa: {
    rotulo: "Aluno com a ficha inativa",
    explicacao:
      "O único aluno que corresponde está com a ficha inativa (arquivada, fora da Lista Piloto ou transferida).",
  },
  identidade_de_ficha_inativa: {
    rotulo: "Conta de um aluno com a ficha inativa",
    explicacao: "A conta da plataforma já está vinculada a um aluno com a ficha inativa.",
  },
  identidade_de_outro_aluno: {
    rotulo: "Conta de outro aluno",
    explicacao: "A conta da plataforma já está vinculada a outro aluno desta escola.",
  },
  // Os três caminhos do motor (``_para_aluno``): a ficha já tem outra conta; outra
  // conta deste relatório leva a ela; ou a leva uma conta que espera numa pendência —
  // nos dois últimos, a ficha pode não ter conta nenhuma.
  outra_identidade_na_plataforma: {
    rotulo: "Outra conta leva ao mesmo aluno",
    explicacao:
      "Outra conta da plataforma também leva a este aluno — já vinculada à ficha, neste relatório ou numa pendência em Revisões de identidade: não dá para saber qual delas é a criança.",
  },
  ra_repetido: {
    rotulo: "RA de mais de um aluno",
    explicacao: "O RA do relatório aponta para mais de um aluno cadastrado.",
  },
  // A disputa pode vir deste relatório ou de um anterior que ainda espera na fila
  // (``ids_em_disputa``): aí a conta vem numa linha só — "mais de uma linha" seria falso.
  id_externo_duplicado: {
    rotulo: "A mesma conta com nomes ou números diferentes",
    explicacao:
      "Esta conta da plataforma veio com nomes ou números diferentes — neste relatório ou num anterior que ainda espera em Revisões de identidade: não dá para saber de qual criança são os números.",
  },
  identidade_de_outra_escola: {
    rotulo: "Conta de um aluno de outra escola",
    explicacao:
      "A conta da plataforma já está vinculada a um aluno de outra escola do Constela: nada é gravado aqui até a Revisão decidir.",
  },
  criacao_bloqueada_por_politica: {
    rotulo: "Criação bloqueada pela política",
    explicacao: "A matrícula desta escola vem da Lista Piloto: a importação não cria ficha.",
  },
  // O pedido de quem confirmou ("Deixar para a Revisão", ``deixar_para_revisao``): o
  // backend o grava quando, sozinho, associaria ou criaria a linha.
  deixada_para_revisao: {
    rotulo: "Deixada para a Revisão",
    explicacao:
      "Quem confirmou a importação deixou esta linha para a Revisão de identidade: nada é associado nem criado.",
  },
  // Motivos de TURMA: a turma escolhida em "Criar aluno novo…" resolve.
  turma_ambigua: {
    rotulo: "Mais de uma turma possível",
    explicacao: "Mais de uma turma cadastrada corresponde à turma do relatório: escolha a turma da ficha nova.",
  },
  turma_arquivada: {
    rotulo: "Turma arquivada",
    explicacao: "A turma do relatório está arquivada e não recebe aluno novo: escolha uma turma ativa.",
  },
  turma_fora_do_ano_letivo: {
    rotulo: "Turma de outro ano letivo",
    explicacao: "A turma não é do ano letivo ativo: escolha uma turma deste ano.",
  },
  turma_de_outra_etapa: {
    rotulo: "Turma de outra etapa",
    explicacao:
      "A turma que corresponde à do relatório é de outra etapa (como Educação Infantil e Fundamental): escolha uma turma da mesma etapa. Se ela ainda não existe, cadastre-a em Turmas com um nome que diga a etapa, como “1º Ano A”.",
  },
  turma_nao_cadastrada: {
    rotulo: "Turma não cadastrada",
    explicacao: "A turma do relatório não existe no cadastro da escola: escolha uma turma existente.",
  },
  sem_turma: {
    rotulo: "Sem turma",
    explicacao: "O relatório não informa a turma e nenhum aluno corresponde ao nome: escolha a turma.",
  },
};

/** "Nome abreviado" → "nome abreviado", sem estragar a sigla ("RA de …"). */
function inicialMinuscula(texto: string): string {
  return /^\p{Lu}{2}/u.test(texto) ? texto : texto.charAt(0).toLowerCase() + texto.slice(1);
}

/** O motivo da linha "revisar", em linguagem simples (undefined fora disso). */
function motivoDaRevisao(c: LinhaAnalise["correspondencia"]) {
  return c?.status === "revisar" ? MOTIVO_REVISAO[c.motivo ?? ""] : undefined;
}

/** A linha vai para Revisões de identidade na confirmação (o backend ignora "Criar"). */
function vaiParaRevisao(c: LinhaAnalise["correspondencia"]): boolean {
  return c?.status === "revisar" && MOTIVOS_SO_REVISAO.has(c.motivo ?? "");
}

/** Motivos de TURMA em que a turma do relatório não recebe a ficha nova e o backend
 *  não escolhe outra (``identidade_aluno._turma_para_criar``): ela está ARQUIVADA, há
 *  MAIS DE UMA turma cadastrada para a sala, ou a da sala é de OUTRA ETAPA (Educação
 *  Infantil × Fundamental). "Criar na turma do relatório" cairia de novo na Revisão;
 *  só uma turma escolhida em "Criar aluno novo…" resolve — até lá, a linha fica na
 *  Revisão. Antes só a arquivada era tratada assim, e a tela pré-escolhia uma turma
 *  (ou "a turma do relatório", que "seria criada") e contava a linha como importada. */
const MOTIVOS_TURMA_SEM_DESTINO = new Set(["turma_arquivada", "turma_ambigua", "turma_de_outra_etapa"]);

function turmaSemDestino(c: LinhaAnalise["correspondencia"]): boolean {
  return c?.status === "revisar" && MOTIVOS_TURMA_SEM_DESTINO.has(c.motivo ?? "");
}

/** A turma do RELATÓRIO de uma linha, como veio: a da própria linha (o Placar da
 *  escola traz uma por aluno) ou a do cabeçalho. É o nome que "Criar na turma do
 *  relatório" manda — dele o backend tira a sala e a etapa. */
function turmaDoRelatorio(a: Analise, linha: LinhaAnalise | undefined): string {
  return String(linha?.dados?.turma_relatorio ?? "") || a.turma_detectada || "";
}

/** O destino padrão do aluno NOVO (status "nao_encontrado"/"bloqueado"): a turma que o
 *  backend decidiu na prévia (``identidade_aluno._turma_para_criar``) — a cadastrada
 *  (``turma_id``) ou a turma do relatório, que a confirmação cria (``turma_nova``).
 *  Sem nenhuma das duas (o relatório não informa turma), a tela não adivinha: a linha
 *  fica em "Ignorar" até o gestor escolher a turma. Antes a tela casava o nome da
 *  turma por pedaço de texto e mandava a criança do "1 ANO A" para a "1º Ano B". */
function destinoDoNovo(c: LinhaAnalise["correspondencia"]): Acao {
  if (c?.turma_id) return { tipo: "criar", turmaId: c.turma_id };
  if (c?.turma_nova) return { tipo: "criar_nova" };
  return { tipo: "ignorar" };
}

/** "Criar aluno novo…" numa turma de OUTRA ETAPA que a turma do relatório: o backend
 *  recusa a ficha mesmo com a turma escolhida e manda a linha para a Revisão
 *  (``identidade_aluno.turma_de_outra_etapa``). A base é a mesma do backend: a turma
 *  do relatório que vai NA LINHA (``dados.turma_relatorio``); sem ela, não há etapa a
 *  comparar. */
function criarEmOutraEtapa(acao: Acao | undefined, linha: LinhaAnalise | undefined,
                           turmas: Turma[]): boolean {
  if (acao?.tipo !== "criar" || acao.turmaId == null) return false;
  const relatorio = String(linha?.dados?.turma_relatorio ?? "").trim();
  const turma = turmas.find((t) => t.id === acao.turmaId);
  return Boolean(relatorio && turma)
    && etapaDaSala(relatorio) !== etapaDaSala(turma!.nome, turma!.ano_escolar ?? "");
}

/** A ficha escolhida para uma conta que já é de um aluno de OUTRA escola do Constela
 *  (a criança que mudou de escola): só o Admin Global confirma esse vínculo (D10,
 *  ``identidade_aluno.decidir`` passo 0). A escolha da gestão da escola vai para
 *  Revisões de identidade, com a ficha escolhida como sugestão — nada é importado. */
function vinculoVaiParaRevisao(acao: Acao | undefined,
                               c: LinhaAnalise["correspondencia"] | undefined,
                               global: boolean): boolean {
  return acao?.tipo === "importar" && !global
    && c?.status === "revisar" && c.motivo === "identidade_de_outra_escola";
}

/** O destino escolhido leva a linha para Revisões de identidade na confirmação:
 *  "Deixar para a Revisão" sempre; "Criar" (turma cadastrada ou a do relatório)
 *  quando a política da escola é "bloquear" — o backend não cria a ficha e abre a
 *  pendência ('criacao_bloqueada_por_politica'); "Criar" numa turma de outra etapa
 *  que a do relatório (``outraEtapa``, de ``criarEmOutraEtapa``); e a ficha escolhida
 *  para a conta de um aluno de outra escola, se quem escolhe não é o Admin Global. */
function vaiParaARevisao(acao: Acao | undefined, criacaoBloqueada: boolean,
                         c?: LinhaAnalise["correspondencia"], global = false,
                         outraEtapa = false): boolean {
  if (acao?.tipo === "revisao") return true;
  if (vinculoVaiParaRevisao(acao, c, global)) return true;
  if (outraEtapa) return true;
  return criacaoBloqueada && (acao?.tipo === "criar" || acao?.tipo === "criar_nova");
}

/** "1 vai" / "N vão" para Revisões de identidade (rodapé e confirmação). */
function vaoParaRevisoes(n: number): string {
  return `${n} ${n === 1 ? "vai" : "vão"} para Revisões de identidade`;
}

/** Quantos alunos esta importação deixou em Revisões de identidade: todas as
 *  pendências gravadas (``qtd_revisoes``), não só as que a política barrou. */
function aguardamRevisao(r: ResultadoImportacao): number {
  return Math.max(r.qtd_revisoes ?? 0, r.criacao_bloqueada ?? 0);
}

interface Grupo {
  chave: string;
  nome: string;
  indices: number[]; // índices das linhas originais deste aluno
  correspondencia: LinhaAnalise["correspondencia"];
  resumo: string;
  totalLivros: number; // > 0 no relatório individual (uma linha por livro)
  todasComErro: boolean;
}

/** A conta da linha na plataforma (uuid do Matific, studentId do Elefante), ou "". */
function contaDaLinha(linha: LinhaAnalise): string {
  const conta = linha.dados.matific_uuid ?? linha.dados.elefante_student_id;
  return conta === undefined || conta === null ? "" : String(conta);
}

/** Agrupa as linhas da análise por aluno: pela CONTA da plataforma + nome, quando a
 *  linha traz conta; sem conta, por nome + turma do relatório. No relatório individual,
 *  as centenas de linhas de livros (todas da mesma conta) viram um único grupo. Sem
 *  conta, a turma entra na chave porque o leaderboard do Matific abrevia os nomes
 *  ("MARIA J") e alunos DIFERENTES de turmas diferentes colidem — num grupo só, o mês
 *  de um deles seria descartado em silêncio. A conta entra porque o backend decide cada
 *  conta por si: duas contas com o mesmo nome na mesma sala abrem uma pendência CADA
 *  (contas_repetidas_no_relatorio), e um grupo só aplicaria a correspondência da
 *  primeira às duas. E, no sentido inverso, a MESMA conta em duas turmas do Placar é uma
 *  criança só: o backend cria uma ficha (a 2ª linha associa pela conta recém-vinculada)
 *  — por isso a turma não entra na chave de quem tem conta. A mesma conta com NOMES
 *  diferentes continua separada (id_externo_duplicado: uma pendência por nome). */
function agrupar(analise: Analise): Grupo[] {
  const mapa = new Map<string, Grupo>();
  const ordem: string[] = [];
  const turmaDe = (linha: LinhaAnalise) => String(linha.dados.turma_relatorio ?? "");
  const chaveAluno = (linha: LinhaAnalise, indice: number) =>
    `${normalizar(linha.nome) || `#${indice}`}|${normalizar(turmaDe(linha))}`;
  const chaveDoGrupo = (linha: LinhaAnalise, indice: number) => {
    const conta = contaDaLinha(linha);
    return conta ? `conta:${conta}|${normalizar(linha.nome) || `#${indice}`}` : chaveAluno(linha, indice);
  };
  // Contas distintas de cada aluno (nome + turma), na ordem do relatório; e as turmas
  // de cada grupo (a mesma conta pode vir em mais de uma).
  const contasDoAluno = new Map<string, string[]>();
  const turmasDoGrupo = new Map<string, string[]>();
  analise.linhas.forEach((linha, indice) => {
    const conta = contaDaLinha(linha);
    const contas = contasDoAluno.get(chaveAluno(linha, indice)) ?? [];
    if (conta && !contas.includes(conta)) contas.push(conta);
    contasDoAluno.set(chaveAluno(linha, indice), contas);
    const turmas = turmasDoGrupo.get(chaveDoGrupo(linha, indice)) ?? [];
    if (turmaDe(linha) && !turmas.includes(turmaDe(linha))) turmas.push(turmaDe(linha));
    turmasDoGrupo.set(chaveDoGrupo(linha, indice), turmas);
  });
  analise.linhas.forEach((linha, indice) => {
    const conta = contaDaLinha(linha);
    const chave = chaveDoGrupo(linha, indice);
    let g = mapa.get(chave);
    if (!g) {
      // Homônimos em turmas diferentes, ou a mesma conta em mais de uma turma: o nome
      // exibido ganha a(s) turma(s) para o usuário saber qual é qual na conferência.
      // Contas diferentes com o mesmo nome na mesma turma: "conta 1 de 2", "conta 2 de 2".
      const turmas = turmasDoGrupo.get(chave) ?? [];
      const repetido = turmas.length > 1 || analise.linhas.some(
        (outra) => normalizar(outra.nome) === normalizar(linha.nome)
          && !turmas.includes(turmaDe(outra)),
      );
      const contas = contasDoAluno.get(chaveAluno(linha, indice)) ?? [];
      const detalhes = [
        ...(repetido && turmas.length > 0 ? [turmas.join(", ")] : []),
        ...(conta && contas.length > 1 ? [`conta ${contas.indexOf(conta) + 1} de ${contas.length}`] : []),
      ];
      g = {
        chave,
        nome: detalhes.length > 0 ? `${linha.nome} (${detalhes.join(", ")})` : linha.nome,
        indices: [],
        correspondencia: linha.correspondencia,
        resumo: "",
        totalLivros: 0,
        todasComErro: true,
      };
      mapa.set(chave, g);
      ordem.push(chave);
    }
    g.indices.push(indice);
    if (linha.erros.length === 0) g.todasComErro = false;
    if (linha.dados.livro) g.totalLivros += 1;
  });
  for (const chave of ordem) {
    const g = mapa.get(chave)!;
    const primeira = analise.linhas[g.indices[0]];
    g.resumo = g.totalLivros > 0
      ? `${g.totalLivros} livro${g.totalLivros === 1 ? "" : "s"} lido${g.totalLivros === 1 ? "" : "s"}`
      : resumoDados(primeira.dados) || "—";
  }
  return ordem.map((c) => mapa.get(c)!);
}

export default function Importacoes() {
  const { escolaId, escolaAtual, usuario } = useApp();
  // Escola VIVA: `analisar()` é assíncrona; se a escola mudar durante o upload,
  // a continuação descarta a resposta (resolvida contra o tenant anterior) em
  // vez de repovoar a prévia sob a nova escola.
  const escolaIdRef = useRef(escolaId);
  escolaIdRef.current = escolaId;
  const podeImportar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  // Só o Admin Global confirma o vínculo da conta de um aluno de outra escola.
  const global = Boolean(usuario?.is_global);

  const [texto, setTexto] = useState("");
  const [plataforma, setPlataforma] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const inputArquivo = useRef<HTMLInputElement | null>(null);

  const [analise, setAnalise] = useState<Analise | null>(null);
  const [acoes, setAcoes] = useState<Acao[]>([]); // uma ação por GRUPO
  // A turma do "Aplicar a todos" — começa VAZIA ("Escolha a turma") a cada prévia:
  // antes começava na 1ª turma da escola, e um clique punha todos os alunos novos
  // numa turma que ninguém escolheu, por cima da turma certa de cada linha.
  const [turmaEmMassa, setTurmaEmMassa] = useState<number | null>(null);
  const [editarGrupo, setEditarGrupo] = useState<number | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [resultado, setResultado] = useState<ResultadoImportacao | null>(null);
  // "Sim, importar" abre a confirmação; só ela grava.
  const [confirmando, setConfirmando] = useState(false);
  // Data em que o relatório foi gerado na plataforma ("AAAA-MM-DD"). Obrigatória
  // no total acumulado; começa VAZIA — nunca presume hoje (um relatório antigo
  // datado de hoje passaria por dado novo e apagaria o que a sincronização trouxe).
  const [dataRelatorio, setDataRelatorio] = useState("");

  // Por padrão a página abre em "Matrículas da escola" — é por onde se importa
  // a Lista Piloto (o fluxo mais comum). Só abre em "Em lote" quando já há um
  // lote em andamento (análise/conferência/importação rodando no contexto).
  const { fase: faseLote } = useImportacaoLote();
  const [modo, setModo] = useState<"individual" | "lote" | "matriculas">(
    faseLote !== "selecao" ? "lote" : "matriculas",
  );
  // No celular os modos são uma linha que rola de lado (como as Abas), com o ativo à vista.
  const { lista: listaModos, abas: botoesModos } = useAbaAtivaVisivel(
    MODOS_IMPORTACAO.findIndex((m) => m.valor === modo));

  const grupos = useMemo(() => (analise ? agrupar(analise) : []), [analise]);

  // Ao TROCAR de escola, descarta a análise/relatório em preparo: ele foi
  // resolvido (aluno_id/turma_id) contra a escola anterior; confirmá-lo já na
  // nova escola gravaria alunos/notas no tenant errado (isolamento por escola).
  useEffect(() => {
    setAnalise(null);
    setAcoes([]);
    setTurmaEmMassa(null);
    setEditarGrupo(null);
    setResultado(null);
    setConfirmando(false);
    setErro("");
    setArquivo(null);
    setTexto("");
    setDataRelatorio("");
    if (inputArquivo.current) inputArquivo.current.value = "";
  }, [escolaId]);

  // Leitura via arquitetura única (useApi): sem escola ainda, a fonte é `null`
  // (ocioso). O hook cuida de cancelamento, timeout e retry. O histórico expõe
  // o erro (exibido no card) em vez de engoli-lo; `recarregar` refaz a busca
  // após uma importação. As turmas alimentam seletores, então caem em [] vazio.
  const {
    dados: historico,
    erro: erroHistorico,
    recarregar: recarregarHistorico,
  } = useApi<Importacao[]>(escolaId ? `/escolas/${escolaId}/importacoes` : null);
  const { dados: turmasApi } = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null);
  const turmas = turmasApi ?? [];

  /** "Deixar para a Revisão": uma instrução ao backend (``deixar_para_revisao``), com
   *  a turma do relatório pelo nome — a da linha, senão a do cabeçalho — como contexto
   *  da pendência. Nunca a turma cadastrada de um "Criar": com ela, o backend criava a
   *  ficha sempre que, sozinho, decidia criar. */
  function acaoRevisao(g: Grupo, a: Analise): Acao {
    const turmaLinha = String(a.linhas[g.indices[0]]?.dados?.turma_relatorio ?? "");
    return { tipo: "revisao", turmaNome: turmaLinha || a.turma_detectada || null };
  }

  async function analisar() {
    if (!escolaId) return;
    const escolaDaAnalise = escolaId;
    setOcupado(true);
    setErro("");
    setResultado(null);
    try {
      const dados = new FormData();
      if (arquivo) dados.append("arquivo", arquivo);
      else dados.append("texto", texto);
      if (plataforma) dados.append("plataforma", plataforma);
      const resposta = await apiUpload<Analise>(`/escolas/${escolaId}/importacoes/analisar`, dados);
      // Trocou de escola durante o upload: descarta (o reset já limpou a tela).
      if (escolaIdRef.current !== escolaDaAnalise) return;
      setAnalise(resposta);
      setDataRelatorio(""); // arquivo novo: a data é dele, informada de novo

      // Ação inicial POR GRUPO, com a turma que a prévia do backend decidiu.
      setTurmaEmMassa(null);
      const gruposIniciais = agrupar(resposta);
      setAcoes(
        gruposIniciais.map((g): Acao => {
          if (g.todasComErro) return { tipo: "ignorar" };
          const c = g.correspondencia;
          // Só a ALTA confiança do motor ("vinculado") e o nome EXATO único
          // pré-selecionam o vínculo. Grafia/similaridade parecida NUNCA vira
          // vínculo por 1 clique.
          if (c?.aluno_id && (c.status === "vinculado" || c.status === "exato")) {
            return { tipo: "importar", alunoId: c.aluno_id, alunoNome: c.aluno_nome ?? g.nome };
          }
          // Linha que a confirmação manda para Revisões de identidade (nome
          // abreviado, duas contas com o mesmo nome, possível duplicata…): o
          // destino é a Revisão — nunca "Criar", que o backend ignoraria.
          if (vaiParaRevisao(c)) return acaoRevisao(g, resposta);
          // Turma do relatório arquivada, ambígua ou de outra etapa: nenhuma turma
          // criável por padrão — a linha fica na Revisão (o que o backend faria) até o
          // gestor escolher uma turma em "Criar aluno novo…".
          if (turmaSemDestino(c)) return acaoRevisao(g, resposta);
          // Aluno novo: a turma DO PRÓPRIO ALUNO que o backend decidiu (o Placar da
          // escola tem alunos de várias turmas) — a cadastrada, ou a do relatório,
          // criada na confirmação.
          return destinoDoNovo(c);
        }),
      );
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao analisar o relatório.");
    } finally {
      setOcupado(false);
    }
  }

  async function confirmar() {
    if (!escolaId || !analise) return;
    const escolaDaConfirmacao = escolaId; // grava e reporta na escola de origem
    setOcupado(true);
    setErro("");
    try {
      // Expande cada grupo de volta para as linhas originais do aluno.
      const linhas = grupos.flatMap((grupo, gi) => {
        const acao = acoes[gi];
        if (!acao || acao.tipo === "ignorar") return [];
        // A turma do relatório do grupo é a da 1ª linha (a que o "Criar na turma do
        // relatório (…)" mostra): a mesma conta em duas turmas é UM aluno, numa turma.
        const turmaDoGrupo = analise.linhas[grupo.indices[0]]?.dados.turma_relatorio;
        return grupo.indices
          .map((i) => analise.linhas[i])
          .filter((linha) => linha.erros.length === 0)
          .map((linha) => ({
            nome: linha.nome,
            dados: linha.dados,
            aluno_id: acao.tipo === "importar" ? acao.alunoId : null,
            criar_em_turma_id: acao.tipo === "criar" ? acao.turmaId : null,
            // Turma inexistente: manda o NOME (da linha ou do cabeçalho) — o
            // backend cria a turma uma única vez e matricula o aluno nela.
            criar_em_turma_nome:
              acao.tipo === "criar_nova"
                ? String(turmaDoGrupo ?? analise.turma_detectada ?? "") || null
                : acao.tipo === "revisao"
                  ? acao.turmaNome
                  : null,
            // "Deixar para a Revisão": o backend nunca associa nem cria nesta linha.
            deixar_para_revisao: acao.tipo === "revisao",
          }));
      });
      if (linhas.length === 0) {
        setErro(
          naoEncontrados.length > 0 && turmas.length === 0
            ? "Os alunos deste relatório ainda não estão cadastrados e não há turmas. Crie uma turma primeiro."
            : "Nenhum aluno marcado para importar. Escolha um destino para cada aluno.",
        );
        return;
      }
      const dataReferencia = exigeData ? instanteDoRelatorio(dataRelatorio) : null;
      if (exigeData && !dataReferencia) {
        setErro("Informe a data do relatório (o dia em que ele foi gerado na plataforma).");
        return;
      }
      const resposta = await api<ResultadoImportacao>(
        `/escolas/${escolaDaConfirmacao}/importacoes/confirmar`,
        {
          method: "POST",
          body: JSON.stringify({
            plataforma: analise.plataforma,
            formato: analise.formato,
            tipo: analise.tipo,
            arquivo_token: analise.arquivo_token,
            arquivo_nome: analise.arquivo_nome,
            // "Intervalo de datas" do relatório: o backend soma os valores ao
            // acumulado e data o snapshot dentro do período.
            periodo_inicio: analise.periodo_inicio || null,
            periodo_fim: analise.periodo_fim || null,
            // Total acumulado: a data do relatório informada (fim daquele dia em
            // Brasília). Sem ela o servidor usaria o relógio de agora.
            data_referencia: dataReferencia,
            linhas,
          }),
        },
      );
      // Trocou de escola durante a gravação: a escrita foi p/ a escola de
      // origem (correto); não sobrepõe a tela da nova escola com o resultado.
      if (escolaIdRef.current !== escolaDaConfirmacao) return;
      setResultado(resposta);
      setAnalise(null);
      setDataRelatorio("");
      setTexto("");
      setArquivo(null);
      if (inputArquivo.current) inputArquivo.current.value = "";
      recarregarHistorico();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao confirmar a importação.");
    } finally {
      setOcupado(false);
      // Fecha a confirmação nos dois casos: o resultado (ou o erro, no rodapé da
      // prévia) aparece na própria tela.
      setConfirmando(false);
    }
  }

  function definirAcao(gi: number, valor: string) {
    setAcoes((atuais) =>
      atuais.map((acao, i) => {
        if (i !== gi) return acao;
        if (valor === "ignorar") return { tipo: "ignorar", manual: true };
        if (valor === "revisao") {
          return grupos[gi] && analise ? acaoRevisao(grupos[gi], analise) : acao;
        }
        // "Criar aluno novo…": a turma que a prévia decidiu para a ficha nova; sem ela,
        // nenhuma — o gestor escolhe (não a 1ª turma da escola).
        if (valor === "criar") {
          return { tipo: "criar", turmaId: grupos[gi]?.correspondencia?.turma_id ?? null };
        }
        if (valor === "criar_nova") return { tipo: "criar_nova" };
        return { tipo: "importar", alunoId: Number(valor) };
      }),
    );
  }

  /** "Aplicar a todos": todo aluno NOVO (sem vínculo com cadastro) recebe a
   *  mesma ação — criar na turma escolhida ou na turma do relatório (nova). A
   *  linha que vai para a Revisão fica onde está: nela "Criar" não vale. Nem a da
   *  turma arquivada, ambígua ou de outra etapa recebe "a turma do relatório" — nela
   *  o backend não cria. Nem a que o gestor marcou "Ignorar": antes ela voltava para
   *  "Criar" e virava ficha de criança. */
  function aplicarATodosOsNovos(acao: Acao) {
    setAcoes((atuais) =>
      atuais.map((atual, i) => {
        const g = grupos[i];
        const ignoradaPeloGestor = atual.tipo === "ignorar" && atual.manual === true;
        if (g && !g.todasComErro && atual.tipo !== "importar" && !ignoradaPeloGestor
            && !vaiParaRevisao(g.correspondencia)
            && !(acao.tipo === "criar_nova" && turmaSemDestino(g.correspondencia))) {
          return acao;
        }
        return atual;
      }),
    );
  }

  /** Vincula o relatório (grupo em edição) ao aluno escolhido no drawer. */
  function vincularAluno(aluno: Aluno, turmaNome: string) {
    if (editarGrupo === null) return;
    setAcoes((atuais) =>
      atuais.map((a, i) =>
        i === editarGrupo
          ? { tipo: "importar", alunoId: aluno.id, alunoNome: aluno.nome, turmaNome, manual: true }
          : a,
      ),
    );
    setEditarGrupo(null);
  }

  /** Como o vínculo do grupo será exibido no card de identificação. */
  function descreverVinculo(gi: number) {
    const g = grupos[gi];
    const acao = acoes[gi];
    if (!g || !acao) return null;
    if (vinculoVaiParaRevisao(acao, g.correspondencia, global)) {
      return {
        tom: "alerta" as const,
        titulo: "Vai para Revisões de identidade",
        nome: g.nome,
        turma: "",
        detalhe: "conta de um aluno de outra escola: a ficha escolhida vai como sugestão, e nada é gravado aqui até a Revisão decidir",
      };
    }
    if (acao.tipo === "importar") {
      const c = g.correspondencia;
      const manual = acao.manual || acao.alunoId !== c?.aluno_id;
      const baixa = !manual && c?.status === "provavel";
      return {
        tom: (manual || !baixa ? "ok" : "alerta") as "ok" | "alerta",
        titulo: manual
          ? "Aluno definido por você"
          : baixa
            ? "Aluno identificado com baixa confiança"
            : "Aluno identificado",
        nome: acao.alunoNome ?? g.nome,
        turma: acao.turmaNome ?? analise?.turma_detectada ?? "",
        detalhe: baixa && c?.similaridade ? `correspondência de ${c.similaridade}%` : "",
      };
    }
    if (acao.tipo === "criar") {
      const turma = turmas.find((t) => t.id === acao.turmaId)?.nome ?? "";
      return {
        tom: "alerta" as const,
        titulo: "Aluno novo — será criado",
        nome: g.nome,
        turma,
        detalhe: "não encontrado no cadastro",
      };
    }
    if (acao.tipo === "criar_nova") {
      return {
        tom: "alerta" as const,
        titulo: "Aluno novo — a turma do relatório será criada",
        nome: g.nome,
        turma: analise ? turmaDoRelatorio(analise, analise.linhas[g.indices[0]]) : "",
        detalhe: "turma ainda não cadastrada — criada automaticamente ao importar",
      };
    }
    if (acao.tipo === "revisao") {
      const motivo = motivoDaRevisao(g.correspondencia);
      return {
        tom: "alerta" as const,
        titulo: "Vai para Revisões de identidade",
        nome: g.nome,
        turma: "",
        detalhe: motivo
          ? `${inicialMinuscula(motivo.rotulo)}: nenhuma ficha é criada; um gestor decide de quem são os dados`
          : "nenhuma ficha é criada; um gestor decide de quem são os dados",
      };
    }
    return {
      tom: "alerta" as const,
      titulo: "Nenhum aluno vinculado",
      nome: g.nome,
      turma: "",
      detalhe: "escolha um aluno para importar",
    };
  }

  const tomCorrespondencia = {
    vinculado: "ok", exato: "ok",
    revisar: "alerta", provavel: "alerta", bloqueado: "destaque",
    nao_encontrado: "neutro",
  } as const;
  const rotuloCorrespondencia = {
    vinculado: "Vinculado automaticamente",
    exato: "Vinculado automaticamente",
    // "revisar" sem motivo conhecido (backend mais novo que a tela): não presume
    // que seja duplicata.
    revisar: "Requer revisão",
    provavel: "Possível duplicata — requer revisão",
    bloqueado: "Bloqueado por conflito de identidade",
    nao_encontrado: "Novo aluno",
  } as const;

  /** O rótulo da correspondência: na linha "revisar", o motivo em linguagem simples
   *  e o que acontece com ela — vai para a Revisão, ou a turma escolhida resolve. */
  function rotuloDe(c: NonNullable<LinhaAnalise["correspondencia"]>): string {
    const motivo = motivoDaRevisao(c);
    if (motivo) {
      return `${motivo.rotulo} — ${vaiParaRevisao(c) ? "vai para Revisões de identidade" : "escolha a turma"}`;
    }
    return rotuloCorrespondencia[c.status];
  }

  // Estatísticas (por grupo) para os controles e a contagem final.
  const gruposValidos = grupos.filter((g) => !g.todasComErro);
  // "Novos" = tudo que NÃO será vinculado automaticamente e que a confirmação pode
  // criar: aluno novo, bloqueado por conflito e revisão de TURMA (a turma escolhida
  // resolve). A linha que vai para a Revisão (nome abreviado, duas contas com o
  // mesmo nome, possível duplicata) não vira ficha — fica fora desta conta.
  const CRIAM = new Set(["nao_encontrado", "bloqueado", "revisar"]);
  const naoEncontrados = grupos.filter(
    (g) => !g.todasComErro && CRIAM.has(g.correspondencia?.status ?? "")
      && !vaiParaRevisao(g.correspondencia),
  );
  // As turmas que a confirmação cria para os alunos novos (``turma_nova`` da prévia: a
  // sala do relatório não tem turma no cadastro), com o nome que elas vão ter.
  const turmasNovas = [...new Set(naoEncontrados
    .map((g) => g.correspondencia?.turma_nova).filter((nome): nome is string => Boolean(nome)))];
  // Todos os alunos novos já têm a turma cadastrada da sua sala (``turma_id``).
  const novosNaTurmaCadastrada = naoEncontrados.length > 0
    && naoEncontrados.every((g) => Boolean(g.correspondencia?.turma_id));
  const totalSelecionados = grupos.filter((g, i) => !g.todasComErro && acoes[i]?.tipo !== "ignorar").length;
  // As linhas ligadas a cada aluno (vínculo escolhido ou da prévia). Só uma linha pode
  // ir para cada aluno: com duas, o /confirmar recusa (422) — antes guardava só os
  // números da última e ligava as duas contas à mesma ficha, sem aviso.
  const linhasPorAluno = new Map<number, number[]>();
  grupos.forEach((g, i) => {
    const acao = acoes[i];
    if (g.todasComErro || acao?.tipo !== "importar") return;
    linhasPorAluno.set(acao.alunoId, [...(linhasPorAluno.get(acao.alunoId) ?? []), i]);
  });
  const escolhidoEmOutraLinha = (alunoId: number, gi: number) =>
    (linhasPorAluno.get(alunoId) ?? []).some((i) => i !== gi);
  /** O nome do aluno de um vínculo, pelo que a prévia mostrou (correspondência ou
   *  alternativas de alguma linha). */
  function nomeDoAluno(alunoId: number): string {
    for (const g of grupos) {
      const c = g.correspondencia;
      if (c?.aluno_id === alunoId && c.aluno_nome) return c.aluno_nome;
      const alternativa = c?.alternativas.find((a) => a.aluno_id === alunoId);
      if (alternativa) return alternativa.nome;
    }
    return "Este aluno";
  }
  // Política "bloquear" (a matrícula vem da Lista Piloto): a confirmação não cria
  // ficha — a linha marcada "Criar" (na turma escolhida ou na do relatório) vai para
  // Revisões de identidade, como a de destino "revisao". O rodapé e a confirmação a
  // contam lá, não entre os importados nem entre os alunos novos.
  const criacaoBloqueada = Boolean(analise?.criacao_bloqueada_por_politica);
  // "Criar" numa turma de outra etapa que a do relatório: o backend recusa (Revisão).
  const emOutraEtapa = (g: Grupo, i: number) =>
    criarEmOutraEtapa(acoes[i], analise?.linhas[g.indices[0]], turmas);
  const totalParaRevisao = grupos.filter(
    (g, i) => !g.todasComErro
      && vaiParaARevisao(acoes[i], criacaoBloqueada, g.correspondencia, global, emOutraEtapa(g, i)),
  ).length;
  // "Criar aluno novo…" ainda sem turma escolhida: "Sim, importar" espera a escolha —
  // sem turma, a confirmação não saberia onde a ficha nasce.
  const criarSemTurma = grupos.some(
    (g, i) => !g.todasComErro && acoes[i]?.tipo === "criar" && !(acoes[i] as { turmaId: number | null }).turmaId);
  // Data do relatório: obrigatória no total acumulado (sem "Intervalo de datas").
  const exigeData = analise ? exigeDataDoRelatorio(analise) : false;
  const hoje = hojeEmBrasilia();
  // Mínimo: 1º de janeiro do ano letivo anterior (a mesma regra do servidor).
  const anoLetivo = escolaAtual?.ano_letivo_ativo ?? null;
  const primeiroDia = primeiroDiaDoRelatorio(anoLetivo);
  const dataOk = !exigeData || dataDoRelatorioValida(dataRelatorio, undefined, anoLetivo);

  // Resumo do que a confirmação vai gravar (só contagem do que já está na tela).
  // ``barradas``: as de "Criar" que a política "bloquear" manda para a Revisão
  // (já somadas em ``revisao``).
  const resumoConfirmacao = useMemo(() => {
    let vincular = 0, criar = 0, criarNova = 0, revisao = 0, barradas = 0, ignorar = 0;
    grupos.forEach((g, i) => {
      const acao = acoes[i];
      if (g.todasComErro || !acao || acao.tipo === "ignorar") { ignorar += 1; return; }
      // A ficha escolhida para a conta de um aluno de outra escola (sem ser o Admin
      // Global) vai para a Revisão como sugestão: não é vínculo.
      if (vinculoVaiParaRevisao(acao, g.correspondencia, global)) revisao += 1;
      else if (acao.tipo === "importar") vincular += 1;
      else if (acao.tipo === "revisao") revisao += 1;
      else if (criarEmOutraEtapa(acao, analise?.linhas[g.indices[0]], turmas)) revisao += 1;
      else if (vaiParaARevisao(acao, criacaoBloqueada)) { revisao += 1; barradas += 1; }
      else if (acao.tipo === "criar") criar += 1;
      else criarNova += 1;
    });
    return { vincular, criar, criarNova, revisao, barradas, ignorar };
  }, [grupos, acoes, criacaoBloqueada, global, analise, turmas]);

  // Etapa do passo a passo (estado REAL do fluxo): 0 envio, 1 conferência, 2
  // confirmação (modal aberto), 3 = tudo feito (resultado na tela, sem prévia).
  const etapa = analise ? (confirmando ? 2 : 1) : resultado ? 3 : 0;
  const identidade = analise ? identidadeDe(analise.plataforma) : null;

  return (
    <div>
      <PageHeader
        titulo="Importações"
        descricao="Use quando a sincronização automática não estiver disponível. O caminho normal é Integrações. Envie o relatório exportado da plataforma (PDF) ou cole o texto — nada é gravado antes da sua confirmação."
      />

      {!podeImportar && (
        <div className="mb-4">
          <Mensagem tipo="erro">Somente administradores e coordenadores podem importar dados.</Mensagem>
        </div>
      )}

      {podeImportar && (
        // Controle segmentado (visual da identidade v2). Continua sendo um grupo de
        // BOTÕES com aria-pressed — não abas: os testes e o E2E procuram o botão
        // "Um por vez", e cada modo é uma ferramenta, não um painel da mesma coisa.
        <div
          ref={listaModos}
          role="group"
          aria-label="Modo de importação"
          className={`mb-6 ${classesAbas.lista}`}
        >
          {MODOS_IMPORTACAO.map(({ valor, Icone, rotulo }, indice) => (
            <button
              key={valor}
              ref={(el) => { botoesModos.current[indice] = el; }}
              type="button"
              aria-pressed={modo === valor}
              onClick={() => setModo(valor)}
              className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${classesAbas.aba} ${
                modo === valor
                  ? "bg-indigo-600 text-white shadow-pilula"
                  : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
              }`}
            >
              <Icone size={16} aria-hidden /> {rotulo}
            </button>
          ))}
        </div>
      )}

      {modo === "lote" && podeImportar && escolaId && (
        <ImportacaoLote aoConcluir={recarregarHistorico} />
      )}

      {modo === "matriculas" && podeImportar && escolaId && (
        <div className="mb-8">
          <ImportacaoMatriculas escolaId={escolaId} aoConcluir={recarregarHistorico} />
        </div>
      )}

      {modo === "individual" && podeImportar && (
        <Card className="mb-5 px-6 py-4">
          <PassosImportacao passos={PASSOS_INDIVIDUAL} atual={etapa} />
        </Card>
      )}

      {modo === "individual" && resultado && (
        <Card className="mb-5 p-6">
          <div className="flex items-start gap-4">
            <IconePastel icone={CheckCircle2} tom="verde" tamanho="lg" />
            <div className="min-w-0">
              <p className="text-[15px] font-semibold text-zinc-900 dark:text-white">{resultado.mensagem}</p>
              {aguardamRevisao(resultado) > 0 && (
                // Tudo o que esta importação deixou na fila (política "bloquear",
                // nome abreviado, duas contas com o mesmo nome, possível duplicata):
                // a mensagem acima pode não contar essas linhas; aqui, o caminho.
                <p className="mt-1.5 text-sm text-ouro-700 dark:text-ouro-300" role="status">
                  {aguardamRevisao(resultado) === 1
                    ? "1 aluno aguarda"
                    : `${aguardamRevisao(resultado)} alunos aguardam`}{" "}
                  a decisão de um gestor.{" "}
                  <Link to="/revisoes-identidade" className="font-semibold underline">
                    Ver revisões de identidade
                  </Link>
                </p>
              )}
              {resultado.avisos.length > 0 && (
                // Marcador fora do texto: o aviso longo quebra em várias linhas e a 2ª
                // alinha com o texto. A chave leva a posição: duas contas com o mesmo
                // nome trazem o MESMO aviso duas vezes (um por conta).
                <ul className="mt-2 list-outside list-disc space-y-0.5 pl-4 text-xs text-ouro-700 dark:text-ouro-300">
                  {resultado.avisos.map((aviso, i) => (
                    <li key={`${i}-${aviso}`}>{aviso}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}

      {modo === "individual" && podeImportar && !analise && (
        <Card className="mb-8 p-6">
          <div className="mb-5 flex items-start gap-4">
            <IconePastel icone={FileUp} tom="violeta" tamanho="lg" />
            <div className="min-w-0">
              <h2 className="text-[17px] font-semibold text-zinc-900 dark:text-white">Enviar o relatório</h2>
              <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">
                Escolha o arquivo exportado da plataforma ou cole o texto. Primeiro vem a prévia.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Campo rotulo="Plataforma">
              <select className={estiloInput} value={plataforma} onChange={(e) => setPlataforma(e.target.value)}>
                <option value="">Detectar automaticamente</option>
                <option value="matific">Matific</option>
                <option value="elefante">Elefante Letrado</option>
              </select>
            </Campo>
            <Campo rotulo="Arquivo (PDF, Excel, TXT ou CSV)">
              <input
                ref={inputArquivo}
                type="file"
                accept=".pdf,.xlsx,.xlsm,.txt,.csv,.tsv,.json"
                className={`${estiloInput} cursor-pointer py-2 file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-indigo-700 hover:file:bg-indigo-100 dark:file:bg-indigo-500/15 dark:file:text-indigo-300`}
                onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
              />
            </Campo>
          </div>
          <div className="mt-4">
            <Campo rotulo="Ou cole aqui o texto copiado do relatório">
              <textarea
                className={`${estiloInput} min-h-[140px] font-mono text-xs`}
                placeholder={"Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas\nAna Beatriz Souza\t42\t85,5\t120"}
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
              />
            </Campo>
          </div>
          {erro && <div className="mt-4"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
            <span className="mr-auto text-xs text-zinc-500 dark:text-zinc-400">
              Nada é gravado nesta etapa.
            </span>
            <Botao onClick={analisar} disabled={ocupado || (!arquivo && !texto.trim())}>
              <Sparkles size={15} aria-hidden /> {ocupado ? "Analisando..." : "Analisar e ver prévia"}
            </Botao>
          </div>
        </Card>
      )}

      {modo === "individual" && analise && (
        <Card className="mb-8 overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 px-6 pb-4 pt-5">
            <IconePastel icone={identidade?.icone ?? FileUp} tom={identidade?.tom ?? "neutro"} />
            <span className="text-[17px] font-semibold text-zinc-900 dark:text-white">Prévia da importação</span>
            <PilulaPlataforma plataforma={analise.plataforma} />
            {analise.formato === "leituras" && <Badge>relatório individual</Badge>}
            {analise.estrategia === "posicional" && <Badge tom="alerta">colunas por posição — confira</Badge>}
          </div>

          <div className="mx-6 mb-4 rounded-2xl bg-indigo-50/70 px-4 py-3 text-sm dark:bg-indigo-500/10">
            <p className="font-semibold text-indigo-800 dark:text-indigo-200">
              {analise.mensagem_deteccao || "Arquivo analisado."}
            </p>
            <p className="mt-0.5 text-zinc-600 dark:text-zinc-300">
              {gruposValidos.length} aluno{gruposValidos.length === 1 ? "" : "s"} ·{" "}
              {analise.total_linhas} registro{analise.total_linhas === 1 ? "" : "s"}
              {analise.turma_detectada && (
                <> · turma <strong>{analise.turma_detectada}</strong></>
              )}
              {analise.total_erros === 0 && analise.total_avisos === 0
                ? " · nenhum problema detectado"
                : ` · ${analise.total_erros} erro(s), ${analise.total_avisos} aviso(s)`}
            </p>
            {analise.aviso_escola && (
              // Só AVISO (nomes de escola variam): não bloqueia a confirmação.
              <p className="mt-1 text-ouro-700 dark:text-ouro-300" role="status">
                {analise.aviso_escola}
              </p>
            )}
            {analise.criacao_bloqueada_por_politica && (
              // Política "bloquear" da escola: avisa ANTES de o gestor escolher
              // "criar" — o backend manda essas linhas para a revisão.
              <p className="mt-1 text-ouro-700 dark:text-ouro-300" role="status">
                A matrícula desta escola vem da Lista Piloto: quem não corresponder a um
                aluno cadastrado não ganha ficha nova nesta importação — vai para
                Revisões de identidade, para um gestor apontar a ficha certa.
              </p>
            )}
          </div>

          {analise.erros_gerais.length > 0 && (
            <div className="space-y-2 px-6 pb-4">
              {analise.erros_gerais.map((mensagem) => (
                <Mensagem key={mensagem} tipo="erro">{mensagem}</Mensagem>
              ))}
            </div>
          )}

          {/* Relatório individual: identificação do aluno em destaque + trocar.
              A cor/ícone refletem COMO o nome foi identificado (arquivo é o
              método preferencial); a linha de vínculo mostra o cadastro. */}
          {analise.formato === "leituras" && grupos.length > 0 && (
            <div className="space-y-3 px-6 pb-5">
              {grupos.map((grupo, gi) => {
                const vinc = descreverVinculo(gi);
                if (!vinc) return null;
                const metodo = METODO_IDENTIFICACAO[analise.origem_nome] ?? METODO_IDENTIFICACAO.conteudo;
                return (
                  <div key={grupo.chave} className={`rounded-2xl border p-4 ${metodo.classe}`}>
                    <div className="flex flex-wrap items-start gap-3">
                      <IconePastel icone={metodo.Icone} tom={metodo.tom} />
                      <div className="min-w-0 flex-1">
                        <p className={`text-[11px] font-semibold uppercase tracking-[0.08em] ${metodo.corTexto}`}>
                          {metodo.texto}
                        </p>
                        <p className="mt-0.5 text-lg font-semibold tracking-tight">{grupo.nome}</p>
                        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                          <span
                            className={
                              vinc.tom === "ok"
                                ? "font-semibold text-emerald-700 dark:text-emerald-300"
                                : "font-semibold text-ouro-700 dark:text-ouro-300"
                            }
                          >
                            {vinc.titulo}
                          </span>
                          {vinc.nome !== grupo.nome && <span>→ {vinc.nome}</span>}
                          {vinc.turma && <span>· Turma: {vinc.turma}</span>}
                          {grupo.totalLivros > 0 && (
                            <span>· {grupo.totalLivros} livro{grupo.totalLivros === 1 ? "" : "s"}</span>
                          )}
                          {vinc.detalhe && <span className="text-zinc-500 dark:text-zinc-400">· {vinc.detalhe}</span>}
                        </p>
                      </div>
                      <Botao variante="secundario" onClick={() => setEditarGrupo(gi)}>
                        <Pencil size={15} aria-hidden /> Alterar aluno
                      </Botao>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Ação em massa: criar de uma vez os alunos ainda não cadastrados */}
          {analise.formato !== "leituras" && naoEncontrados.length > 0 && (
            <div className="mx-6 mb-4 space-y-2.5 rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3 text-sm dark:border-ouro-400/25 dark:bg-ouro-400/10">
              <div className="flex flex-wrap items-center gap-2">
                <UserPlus size={16} aria-hidden className="text-ouro-700 dark:text-ouro-300" />
                <span className="text-zinc-800 dark:text-zinc-100">
                  <strong>{naoEncontrados.length}</strong> aluno(s) novo(s)
                  {analise.turma_detectada && novosNaTurmaCadastrada
                    ? " — já marcados para criar na turma do relatório."
                    : turmasNovas.length === 1
                      ? ` — a turma “${turmasNovas[0]}” será criada automaticamente ao importar.`
                      : turmasNovas.length > 1
                        ? ` — as turmas ${turmasNovas.map((nome) => `“${nome}”`).join(", ")} serão criadas automaticamente ao importar.`
                        : "."}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {turmasNovas.length > 0 && (
                  <Botao variante="secundario" tamanho="sm" onClick={() => aplicarATodosOsNovos({ tipo: "criar_nova" })}>
                    <UserPlus size={14} aria-hidden /> Aplicar a todos: turma do relatório (nova)
                  </Botao>
                )}
                {turmas.length > 0 && (
                  <>
                    <select
                      aria-label="Turma para os novos alunos"
                      className="rounded-lg border border-ouro-200 bg-white px-2.5 py-1.5 text-sm dark:border-ouro-400/30 dark:bg-zinc-900"
                      value={turmaEmMassa ?? ""}
                      onChange={(e) => setTurmaEmMassa(e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">Escolha a turma</option>
                      {turmas.map((turma) => (
                        <option key={turma.id} value={turma.id}>{turma.nome}</option>
                      ))}
                    </select>
                    <Botao variante="secundario" tamanho="sm" disabled={turmaEmMassa === null}
                           onClick={() => turmaEmMassa && aplicarATodosOsNovos({ tipo: "criar", turmaId: turmaEmMassa })}>
                      <UserPlus size={14} aria-hidden /> Aplicar a todos
                    </Botao>
                  </>
                )}
                {turmas.length === 0 && turmasNovas.length === 0 && (
                  <span className="text-zinc-800 dark:text-zinc-100">
                    Crie uma turma primeiro em{" "}
                    <Link to="/turmas" className="font-semibold text-indigo-700 underline dark:text-indigo-300">Turmas</Link>.
                  </span>
                )}
              </div>
            </div>
          )}

          {analise.formato !== "leituras" && grupos.length > 0 && (
            <div className={classesTabela.moldura}>
              <table className={classesTabela.tabela}>
                <thead>
                  <tr>
                    <th className={classesTabela.th}>Aluno no relatório</th>
                    <th className={classesTabela.th}>Dados</th>
                    <th className={classesTabela.th}>Correspondência</th>
                    <th className={classesTabela.th}>Destino</th>
                  </tr>
                </thead>
                <tbody>
                  {grupos.map((grupo, gi) => {
                    const acao = acoes[gi] ?? { tipo: "ignorar" as const };
                    const correspondencia = grupo.correspondencia;
                    const primeira = analise.linhas[grupo.indices[0]];
                    const motivo = motivoDaRevisao(correspondencia);
                    // O selo e a explicação do motivo descrevem o "Destino de …": quem
                    // usa leitor de tela ouve o porquê ao chegar no seletor.
                    const idRotulo = `previa-linha-${gi}-correspondencia`;
                    const idMotivo = `previa-linha-${gi}-motivo`;
                    const descricao = [
                      ...(correspondencia ? [idRotulo] : []),
                      ...(motivo ? [idMotivo] : []),
                    ].join(" ") || undefined;
                    return (
                      <tr key={grupo.chave} className={`${classesTabela.tr} align-top`}>
                        <td className={`${classesTabela.td} font-medium text-zinc-900 dark:text-zinc-100`}>
                          {grupo.nome ? (
                            <span className="flex min-w-[10rem] items-center gap-2.5">
                              <Avatar nome={grupo.nome} tamanho="sm" />
                              <span>{grupo.nome}</span>
                            </span>
                          ) : <em className="text-zinc-500 dark:text-zinc-400">sem nome</em>}
                        </td>
                        <td className={`${classesTabela.td} text-xs text-zinc-600 dark:text-zinc-300`}>
                          {grupo.totalLivros > 0 ? (
                            <span className="inline-flex items-center gap-1">
                              <BookMarked size={12} aria-hidden /> {grupo.resumo}
                            </span>
                          ) : (
                            grupo.resumo
                          )}
                          {primeira.avisos.map((mensagem) => (
                            <p key={mensagem} className="mt-1 text-ouro-700 dark:text-ouro-300">{mensagem}</p>
                          ))}
                        </td>
                        <td className={classesTabela.td}>
                          {correspondencia && (
                            <div className="space-y-1">
                              <Badge tom={tomCorrespondencia[correspondencia.status]}>
                                <span id={idRotulo}>{rotuloDe(correspondencia)}</span>
                              </Badge>
                              {motivo && (
                                <p id={idMotivo} className="max-w-[18rem] text-xs text-zinc-500 dark:text-zinc-400">
                                  {motivo.explicacao}
                                </p>
                              )}
                              {correspondencia.aluno_nome
                               && correspondencia.status !== "nao_encontrado"
                               && correspondencia.status !== "bloqueado" && (
                                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                                  → {correspondencia.aluno_nome}
                                  {correspondencia.similaridade ? ` (${correspondencia.similaridade}%)` : ""}
                                </p>
                              )}
                            </div>
                          )}
                        </td>
                        <td className={classesTabela.td}>
                          {grupo.todasComErro ? (
                            <span className="text-xs text-zinc-500 dark:text-zinc-400">sem dados válidos — não será importado</span>
                          ) : (
                            <div className="flex min-w-[12rem] flex-col gap-1.5">
                              <select
                                aria-label={`Destino de ${grupo.nome}`}
                                aria-describedby={descricao}
                                className={estiloSeletorDestino}
                                value={
                                  acao.tipo === "ignorar" ? "ignorar"
                                  : acao.tipo === "criar" ? "criar"
                                  : acao.tipo === "criar_nova" ? "criar_nova"
                                  : acao.tipo === "revisao" ? "revisao"
                                  : String(acao.alunoId)
                                }
                                onChange={(e) => definirAcao(gi, e.target.value)}
                              >
                                {correspondencia?.alternativas.map((alternativa) => (
                                  <option key={alternativa.aluno_id} value={alternativa.aluno_id}>
                                    {alternativa.nome}
                                    {alternativa.turma ? ` — ${alternativa.turma}` : ""} ({alternativa.similaridade}%)
                                    {vinculoVaiParaRevisao({ tipo: "importar", alunoId: alternativa.aluno_id },
                                      correspondencia, global)
                                      ? " — vai para a Revisão como sugestão" : ""}
                                    {escolhidoEmOutraLinha(alternativa.aluno_id, gi)
                                      ? " — já escolhido em outra linha" : ""}
                                  </option>
                                ))}
                                {vaiParaRevisao(correspondencia) ? (
                                  // A confirmação não cria ficha nesta linha: "Criar"
                                  // seria ignorado. Fica a Revisão (ou ignorar).
                                  <option value="revisao">Deixar para a Revisão</option>
                                ) : turmaSemDestino(correspondencia) ? (
                                  // A turma do relatório está arquivada, é ambígua ou de
                                  // outra etapa: o backend não cria nela. Fica a Revisão,
                                  // ou uma turma escolhida.
                                  <>
                                    <option value="revisao">Deixar para a Revisão</option>
                                    <option value="criar">Criar aluno novo…</option>
                                  </>
                                ) : (
                                  <>
                                    {turmaDoRelatorio(analise, primeira) && (
                                      <option value="criar_nova">
                                        Criar na turma do relatório ({turmaDoRelatorio(analise, primeira)})
                                      </option>
                                    )}
                                    <option value="criar">Criar aluno novo…</option>
                                  </>
                                )}
                                <option value="ignorar">Ignorar</option>
                              </select>
                              {acao.tipo === "criar" && (
                                <select
                                  aria-label={`Turma para ${grupo.nome}`}
                                  className={estiloInput}
                                  value={acao.turmaId ?? ""}
                                  onChange={(e) =>
                                    setAcoes((atuais) =>
                                      atuais.map((a, i) =>
                                        i === gi
                                          ? { tipo: "criar", turmaId: e.target.value ? Number(e.target.value) : null }
                                          : a,
                                      ),
                                    )
                                  }
                                >
                                  <option value="">
                                    {turmas.length === 0 ? "Crie uma turma primeiro" : "Escolha a turma"}
                                  </option>
                                  {turmas.map((turma) => (
                                    <option key={turma.id} value={turma.id}>{turma.nome}</option>
                                  ))}
                                </select>
                              )}
                              {criarEmOutraEtapa(acao, primeira, turmas) && (
                                // O backend recusa a ficha nesta turma (outra etapa): o
                                // rodapé já a conta em Revisões — aqui, o porquê.
                                <p className="max-w-[18rem] text-xs text-ouro-700 dark:text-ouro-300">
                                  Esta turma é de outra etapa que a turma do relatório: a ficha não
                                  nasce nela — a linha vai para Revisões de identidade.
                                </p>
                              )}
                              {acao.tipo === "importar" && escolhidoEmOutraLinha(acao.alunoId, gi) && (
                                // Só uma linha pode ir para cada aluno: o /confirmar recusa
                                // duas (contas ou números diferentes) e nada é gravado.
                                <p className="max-w-[18rem] text-xs font-semibold text-rose-700 dark:text-rose-300">
                                  “{acao.alunoNome ?? nomeDoAluno(acao.alunoId)}” também foi escolhido
                                  para outra linha deste relatório: só uma linha pode ir para cada
                                  aluno — deixe a outra para a Revisão.
                                </p>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {exigeData && (
            // Total acumulado: os números entram NA DATA do relatório. Sem ela, um
            // arquivo antigo viraria "o dado de hoje" (ranking, nota e frescor) e
            // apagaria o retrato que a sincronização gravou.
            <div className="mx-6 mt-4 rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3 dark:border-ouro-400/25 dark:bg-ouro-400/10">
              <div className="max-w-xs">
                <Campo rotulo="Data do relatório (obrigatória)">
                  <input
                    type="date"
                    className={estiloInput}
                    value={dataRelatorio}
                    min={primeiroDia}
                    max={hoje}
                    required
                    aria-describedby="ajuda-data-relatorio"
                    aria-invalid={dataRelatorio !== "" && !dataOk}
                    onChange={(e) => setDataRelatorio(e.target.value)}
                  />
                </Campo>
              </div>
              <p id="ajuda-data-relatorio" className="mt-1.5 text-xs text-zinc-700 dark:text-zinc-200">
                O dia em que o relatório foi gerado na plataforma (costuma estar no rodapé ou
                na capa). Os números entram nessa data: um arquivo antigo não passa por dado
                de hoje nem apaga o que a sincronização já trouxe.
              </p>
              {dataRelatorio !== "" && !dataOk && (
                <p className="mt-1 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
                  {problemaDaDataDoRelatorio(dataRelatorio, undefined, anoLetivo)}
                </p>
              )}
            </div>
          )}

          {erro && <div className="px-6 pt-4"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-2 flex flex-wrap items-center justify-end gap-3 border-t border-zinc-100 bg-zinc-50/60 px-6 py-4 dark:border-zinc-800 dark:bg-zinc-800/30">
            <span className="mr-auto text-sm font-semibold text-zinc-800 dark:text-zinc-100">
              {exigeData && !dataOk
                ? "Informe a data do relatório para importar."
                : criarSemTurma
                  ? "Escolha a turma de cada aluno novo em “Criar aluno novo…” para importar."
                  : totalSelecionados > 0
                    ? `${totalSelecionados - totalParaRevisao} de ${gruposValidos.length} aluno(s) serão importados${
                      totalParaRevisao > 0 ? `; ${vaoParaRevisoes(totalParaRevisao)}` : ""}.`
                    : "Deseja importar estes dados?"}
            </span>
            <Botao variante="secundario" onClick={() => setAnalise(null)} disabled={ocupado}>
              Não, voltar
            </Botao>
            <Botao onClick={() => setConfirmando(true)}
                   disabled={ocupado || totalSelecionados === 0 || !dataOk || criarSemTurma}>
              <CheckCircle2 size={15} aria-hidden />
              {ocupado ? "Importando..." : "Sim, importar"}
            </Botao>
          </div>

          {/* Confirmação ANTES de gravar: o que vai acontecer, em números da prévia. */}
          <Confirmacao
            titulo="Gravar esta importação?"
            aberto={confirmando}
            aoFechar={() => setConfirmando(false)}
            aoConfirmar={() => { void confirmar(); }}
            rotuloConfirmar={ocupado ? "Gravando..." : "Gravar importação"}
            ocupado={ocupado}
          >
            <p>
              {totalSelecionados} de {gruposValidos.length} aluno(s) do relatório{" "}
              {identidade ? `do ${identidade.nome}` : ""} entram nesta importação:
            </p>
            {exigeData && dataOk && (
              <p className="text-sm">
                Data do relatório: <strong>{diaPorExtenso(dataRelatorio)}</strong>
              </p>
            )}
            <ul className="space-y-1.5">
              <li className="flex items-center gap-2">
                <CheckCircle2 size={15} aria-hidden className="shrink-0 text-emerald-600" />
                {resumoConfirmacao.vincular} vinculado(s) a um aluno já cadastrado
              </li>
              {resumoConfirmacao.criar + resumoConfirmacao.criarNova > 0 && (
                <li className="flex items-center gap-2">
                  <UserPlus size={15} aria-hidden className="shrink-0 text-ouro-700 dark:text-ouro-300" />
                  {resumoConfirmacao.criar + resumoConfirmacao.criarNova} aluno(s) novo(s)
                  {resumoConfirmacao.criarNova > 0 ? " (com a turma do relatório criada, se ainda não existir)" : ""}
                </li>
              )}
              {resumoConfirmacao.revisao > 0 && (
                <li className="flex items-center gap-2">
                  <AlertTriangle size={15} aria-hidden className="shrink-0 text-ouro-700 dark:text-ouro-300" />
                  {vaoParaRevisoes(resumoConfirmacao.revisao)} — nenhuma ficha é criada; um gestor
                  decide de quem são os dados
                </li>
              )}
              {resumoConfirmacao.ignorar > 0 && (
                <li className="flex items-center gap-2">
                  <XCircle size={15} aria-hidden className="shrink-0 text-zinc-500" />
                  {resumoConfirmacao.ignorar} ignorado(s) — ficam de fora
                </li>
              )}
            </ul>
            {resumoConfirmacao.barradas > 0 ? (
              <p className="text-xs">
                Pela política desta escola, quem não corresponder a uma ficha vai para Revisões de
                identidade — nenhuma ficha nova é criada por esta importação.
              </p>
            ) : resumoConfirmacao.criar + resumoConfirmacao.criarNova > 0 && (
              <p className="text-xs">Ficha criada por importação não se desfaz sozinha: confira os nomes novos.</p>
            )}
          </Confirmacao>

          {escolaId && (
            <SeletorAlunoDrawer
              escolaId={escolaId}
              aberto={editarGrupo !== null}
              turmas={turmas}
              turmaInicial={(editarGrupo !== null ? grupos[editarGrupo]?.correspondencia?.turma_id : null)
                ?? acharTurmaPorNome(turmas, analise.turma_detectada)}
              nomePdf={editarGrupo !== null ? grupos[editarGrupo]?.nome ?? "" : ""}
              aoFechar={() => setEditarGrupo(null)}
              aoConfirmar={vincularAluno}
            />
          )}
        </Card>
      )}

      {/* Histórico: h2 (a página tem um h1 só — o "Importações" lá em cima). */}
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 pb-3 pt-5">
          <div className="flex min-w-0 items-center gap-3">
            <IconePastel icone={History} tom="azul" />
            <div className="min-w-0">
              <h2 className="text-[17px] font-semibold text-zinc-900 dark:text-white">Histórico</h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Toda importação fica registrada com autor, quantidade e tempo.
              </p>
            </div>
          </div>
        </div>
        {erroHistorico ? (
          <Erro descricao={erroHistorico.message} aoTentar={recarregarHistorico} />
        ) : historico === null ? (
          <div className="space-y-3 px-6 pb-6 pt-2" aria-busy="true">
            <p className="sr-only" role="status">Carregando...</p>
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}
          </div>
        ) : historico.length === 0 ? (
          <Vazio icone={History} titulo="Nenhuma importação ainda" descricao="O histórico aparecerá aqui após a primeira importação." />
        ) : (
          // Celular: rola dentro do cartão com o aviso escrito (Alunos e Erros ficam à direita).
          <TabelaRolavel rotulo="Histórico de importações: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  <th className={classesTabela.th}>Data</th>
                  <th className={classesTabela.th}>Plataforma</th>
                  <th className={classesTabela.th}>Formato</th>
                  <th className={`${classesTabela.th} text-right`}>Alunos</th>
                  <th className={`${classesTabela.th} text-right`}>Erros</th>
                  <th className={`hidden md:table-cell ${classesTabela.th}`}>Por</th>
                </tr>
              </thead>
              <tbody>
                {historico.map((item) => (
                  <tr key={item.id} className={classesTabela.tr}>
                    <td className={`${classesTabela.td} whitespace-nowrap`}>{dataHora(item.created_at)}</td>
                    <td className={classesTabela.td}>
                      <PilulaPlataforma plataforma={item.plataforma} curto />
                    </td>
                    <td className={`${classesTabela.td} text-xs text-zinc-500 dark:text-zinc-400`}>{item.tipo}</td>
                    <td className={`${classesTabela.td} text-right font-semibold tabular-nums text-zinc-900 dark:text-white`}>{item.qtd_alunos}</td>
                    <td className={`${classesTabela.td} text-right tabular-nums`}>
                      {item.qtd_erros ? <Badge tom="erro">{item.qtd_erros}</Badge> : "—"}
                    </td>
                    <td className={`hidden md:table-cell ${classesTabela.td} text-zinc-600 dark:text-zinc-300`}>
                      {item.usuario_nome ? (
                        <span className="flex items-center gap-2">
                          <Avatar nome={item.usuario_nome} tamanho="sm" />
                          <span>{item.usuario_nome}</span>
                        </span>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>
    </div>
  );
}
