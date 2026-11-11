/**
 * Estado GLOBAL da importação em lote.
 *
 * A análise e a importação rodam neste contexto (acima das rotas), então o
 * usuário pode navegar livremente pelo sistema enquanto os arquivos são
 * processados — um indicador flutuante (no Layout) mostra o progresso e leva
 * de volta à tela de Importações. Nada se perde ao trocar de página.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, apiUpload } from "../lib/api";
import { exigeDataDoRelatorio, instanteDoRelatorio } from "../lib/dataRelatorio";
import { acharTurmaPorNome } from "../lib/nomes";
import type { Aluno, Analise, LinhaAnalise, ResultadoImportacao, Turma } from "../lib/types";
import { useApp } from "./AppContext";

export type FaseLote = "selecao" | "analisando" | "conferencia" | "importando" | "relatorio";
export type StatusItem = "ok" | "alerta" | "pendente" | "erro";

export type AcaoItem =
  | { tipo: "importar"; alunoId: number }
  | { tipo: "criar"; turmaId: number }
  // A confirmação manda o arquivo para Revisões de identidade (nome só parecido, mais
  // de um aluno possível, turma sem destino…): vai com ``deixar_para_revisao`` — o
  // backend nunca associa nem cria — e a turma do relatório só como contexto da
  // pendência. Antes ia como "criar", com "Aluno novo — será criado nesta turma.".
  | { tipo: "revisao"; turmaNome: string | null }
  | { tipo: "corrigir" };

export interface ItemLote {
  id: string;
  nome: string;
  arquivo: File;
  analise: Analise | null;
  status: StatusItem;
  origem: string;
  alunoNome: string;
  turmaNome: string;
  totalLivros: number;
  acao: AcaoItem;
  detalhe: string;
  corrigido: boolean;
  ignorado: boolean;
  /** Por que o arquivo já vem ignorado da análise: a confirmação o ignoraria (conta de
   *  aluno excluído permanentemente, conta aposentada — ``LINHA_IGNORADA``). */
  motivoIgnorado?: string;
  /** "revisao": o servidor gravou o arquivo como pendência em Revisões de identidade
   *  (``qtd_revisoes``) sem aplicar dado a nenhum aluno (``qtd_alunos`` 0). */
  resultado?: "importado" | "revisao" | "erro" | "ignorado" | "pendente";
  /** O motivo que o servidor deu ao recusar este arquivo no /confirmar (resultado
   *  "erro"). Antes a recusa era descartada e o relatório mostrava, como motivo, o
   *  ``detalhe`` da ANÁLISE ("Aluno novo — será criado nesta turma."). */
  erroImportacao?: string;
}

/** Resultado do recálculo final do lote (POST /recalcular). ``null`` = ainda
 *  não rodou. A falha NÃO é engolida: os arquivos já estão gravados, mas as
 *  notas e os rankings ficam com o valor antigo até recalcular. */
export type EstadoRecalculo =
  | { estado: "ok"; mensagem: string | null }
  | { estado: "falhou"; erro: string }
  | null;

/** A mensagem de uma falha da API (o ApiError já vem em linguagem simples). */
function mensagemDoErro(erro: unknown, padrao: string): string {
  return erro instanceof Error && erro.message ? erro.message : padrao;
}

/** Motivos de revisão (``identidade_aluno.decidir``) em que a confirmação NUNCA cria
 *  a ficha, qualquer que seja a turma escolhida: o motor manda a linha para Revisões
 *  de identidade e um "Criar" seria ignorado. Só a escolha de um aluno da lista
 *  (vínculo explícito) muda o destino — menos na conta de um aluno de outra escola,
 *  em que só o Admin Global confirma o vínculo. Ficam de fora os motivos de TURMA
 *  (turma_ambigua, turma_arquivada, turma_fora_do_ano_letivo…): neles a turma
 *  escolhida resolve e a ficha nasce. Vale para a prévia de um arquivo por vez
 *  (Importacoes.tsx) e para o lote. */
export const MOTIVOS_SO_REVISAO = new Set([
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

/** Por que a confirmação IGNORA a linha (status "ignorado" da prévia, o motivo do
 *  IGNORAR de ``identidade_aluno.decidir``): o rótulo e o que fazer. Antes a prévia
 *  mostrava "Novo aluno" (e o lote, "Aluno novo — será criado nesta turma.") e a
 *  confirmação ignorava a linha. Vale para a prévia de um arquivo por vez e para o lote. */
export const LINHA_IGNORADA: Record<string, { rotulo: string; explicacao: string }> = {
  conta_esquecida: {
    rotulo: "Conta de aluno excluído permanentemente: será ignorada",
    explicacao: "A conta continua ativa na plataforma: peça o encerramento lá.",
  },
  identidade_aposentada: {
    rotulo: "Conta aposentada: será ignorada",
    explicacao: "A escola escolheu outra conta desta criança nesta plataforma; o histórico "
      + "desta continua guardado.",
  },
};

/** Motivos de TURMA em que a turma do relatório não recebe a ficha nova e o backend
 *  não escolhe outra (``identidade_aluno._turma_para_criar``): ela está ARQUIVADA, há
 *  MAIS DE UMA turma cadastrada para a sala, ou a da sala é de OUTRA ETAPA (Educação
 *  Infantil × Fundamental). Só uma turma escolhida para a ficha nova resolve — o que
 *  o lote não faz: nele, a linha vai para a Revisão. */
export const MOTIVOS_TURMA_SEM_DESTINO = new Set([
  "turma_arquivada", "turma_ambigua", "turma_de_outra_etapa",
]);

/** O porquê da Revisão, em linguagem simples, para os motivos de um relatório
 *  individual (sem conta da plataforma). O texto completo do motivo aparece em
 *  Revisões de identidade. */
const RAZAO_DA_REVISAO: Record<string, string> = {
  nome_incompleto: "o relatório traz só parte do nome",
  candidatos_multiplos: "mais de um aluno cadastrado pode ser esta criança",
  homonimo_em_outra_sala: "há aluno com este nome em outra turma",
  nome_casa_em_outra_sala: "o nome corresponde a um aluno de outra turma",
  ficha_inativa: "o único aluno que corresponde está com a ficha inativa",
  turma_arquivada: "a turma do relatório está arquivada e não recebe aluno novo",
  turma_ambigua: "mais de uma turma cadastrada corresponde à turma do relatório",
  turma_de_outra_etapa: "a turma que corresponde à do relatório é de outra etapa",
};

function razaoDaRevisao(c: NonNullable<LinhaAnalise["correspondencia"]>): string {
  if (c.motivo === "correspondencia_insegura") {
    return `o nome lembra o de ${c.aluno_nome || "um aluno cadastrado"}, mas não o bastante para vincular sozinho`;
  }
  return RAZAO_DA_REVISAO[c.motivo ?? ""] ?? "a importação não decide sozinha quem é este aluno";
}

/** A confirmação manda o arquivo para Revisões de identidade: o destino "revisao", ou
 *  "criar" numa escola de política "bloquear" (a matrícula vem da Lista Piloto: o
 *  backend não cria a ficha e abre a pendência). */
export function arquivoVaiParaRevisao(item: ItemLote): boolean {
  return item.acao.tipo === "revisao"
    || (item.acao.tipo === "criar" && Boolean(item.analise?.criacao_bloqueada_por_politica));
}

/** O resultado de um arquivo pela RESPOSTA do /confirmar — não basta o 200: com
 *  ``qtd_alunos`` 0, nenhum aluno recebeu os dados; com pendência gravada, o arquivo
 *  está em Revisões de identidade; sem nenhuma das duas, nada foi gravado. */
function resultadoDaResposta(r: ResultadoImportacao): Pick<ItemLote, "resultado" | "erroImportacao"> {
  if ((r.qtd_alunos ?? 0) > 0) return { resultado: "importado" };
  if ((r.qtd_revisoes ?? 0) > 0 || (r.criacao_bloqueada ?? 0) > 0) return { resultado: "revisao" };
  const avisos = (r.avisos ?? []).join(" ");
  return {
    resultado: "erro",
    erroImportacao: `Nada foi gravado deste arquivo.${avisos ? ` ${avisos}` : ""}`,
  };
}

/** true quando o arquivo tem um destino resolvido e será enviado ao confirmar. */
export function importavel(item: ItemLote): boolean {
  return !item.ignorado
    && (item.acao.tipo === "importar" || item.acao.tipo === "criar" || item.acao.tipo === "revisao");
}

/** Lê a análise de um PDF e decide status + ação, sem intervenção do usuário. */
function montarItem(arquivo: File, indice: number, analise: Analise, turmas: Turma[]): ItemLote {
  const base = { id: `${indice}-${arquivo.name}`, nome: arquivo.name, arquivo, analise, corrigido: false, ignorado: false };
  const linhasValidas = analise.linhas.filter((l) => l.erros.length === 0);
  const nome = analise.linhas.find((l) => l.nome)?.nome ?? "";
  const origem = analise.origem_nome || "nenhum";
  const corresp = analise.linhas.find((l) => l.correspondencia)?.correspondencia ?? null;
  const totalLivros = analise.linhas.filter((l) => l.dados?.livro).length;
  // A turma do aluno NOVO é a que o backend decidiu na prévia (``turma_id``): sem ela —
  // a sala do relatório não tem turma no cadastro (``turma_nova``) ou não há turma — o
  // lote não adivinha uma pelo nome (antes a criança do "1 ANO A" ia para a "1º Ano B").
  const novo = corresp?.status === "nao_encontrado" || corresp?.status === "bloqueado";
  const turmaId = novo ? corresp?.turma_id ?? null : acharTurmaPorNome(turmas, analise.turma_detectada);
  const turmaNome = (novo ? corresp?.turma_nome : null)
    ?? turmas.find((t) => t.id === turmaId)?.nome ?? analise.turma_detectada ?? "";
  // A turma do RELATÓRIO, como veio (a da linha, senão a do cabeçalho): só o contexto
  // da pendência quando o arquivo vai para a Revisão.
  const turmaRelatorio = String(analise.linhas.find((l) => l.dados?.turma_relatorio)?.dados
    ?.turma_relatorio ?? "") || analise.turma_detectada || "";

  if (!nome || origem === "nenhum") {
    return {
      ...base, status: "erro", origem, alunoNome: nome, turmaNome, totalLivros,
      acao: { tipo: "corrigir" },
      detalhe: "Não foi possível identificar o aluno pelo nome do arquivo nem pelo conteúdo.",
    };
  }
  if (linhasValidas.length === 0) {
    return {
      ...base, status: "erro", origem, alunoNome: nome, turmaNome, totalLivros,
      acao: { tipo: "corrigir" },
      detalhe: "Nenhum registro de leitura válido neste arquivo.",
    };
  }
  // A confirmação IGNORA o arquivo (conta de aluno excluído para sempre, conta
  // aposentada): ele já vem ignorado, com o porquê.
  if (corresp?.status === "ignorado") {
    const porque = LINHA_IGNORADA[corresp.motivo ?? ""];
    const motivoIgnorado = porque ? `${porque.rotulo}. ${porque.explicacao}`
      : "A confirmação ignora este arquivo.";
    return {
      ...base, ignorado: true, motivoIgnorado, status: "alerta", origem, alunoNome: nome,
      turmaNome: "", totalLivros, acao: { tipo: "corrigir" }, detalhe: motivoIgnorado,
    };
  }
  // Só a ALTA confiança do motor ("vinculado") e o nome EXATO único auto-importam
  // no lote. Grafia/similaridade parecida nunca vira vínculo automático.
  if (corresp?.aluno_id
      && (corresp.status === "vinculado" || corresp.status === "exato")) {
    return {
      ...base, status: "ok", origem, totalLivros,
      alunoNome: corresp.aluno_nome ?? nome, turmaNome,
      acao: { tipo: "importar", alunoId: corresp.aluno_id },
      detalhe: "",
    };
  }
  // Linha que a confirmação manda para Revisões de identidade — o mesmo critério da
  // prévia de um arquivo por vez. Antes caía em "criar" com "Aluno novo — será criado
  // nesta turma.", e o backend não criava nem importava nada.
  const motivo = corresp?.motivo ?? "";
  if (corresp?.status === "revisar"
      && (MOTIVOS_SO_REVISAO.has(motivo) || MOTIVOS_TURMA_SEM_DESTINO.has(motivo))) {
    return {
      ...base, status: "alerta", origem, alunoNome: nome, turmaNome, totalLivros,
      acao: { tipo: "revisao", turmaNome: turmaRelatorio || null },
      detalhe: `Vai para Revisões de identidade: ${razaoDaRevisao(corresp)}. Nada é criado `
        + "nem vinculado — se você já sabe quem é o aluno, use “Corrigir”.",
    };
  }
  if (turmaId) {
    // Política "bloquear": o "criar" vai como sempre (a pendência nasce com a turma
    // resolvida e o motivo da política), mas a ficha não nasce — diz isso.
    if (analise.criacao_bloqueada_por_politica) {
      return {
        ...base, status: "alerta", origem, alunoNome: nome, turmaNome, totalLivros,
        acao: { tipo: "criar", turmaId },
        detalhe: "Vai para Revisões de identidade: a matrícula desta escola vem da Lista Piloto e "
          + "a importação não cria ficha. Se a criança já tem ficha, use “Corrigir”.",
      };
    }
    return {
      ...base, status: "ok", origem, alunoNome: nome, turmaNome, totalLivros,
      acao: { tipo: "criar", turmaId },
      detalhe: "Aluno novo — será criado nesta turma.",
    };
  }
  return {
    ...base, status: "pendente", origem, alunoNome: nome, turmaNome: "", totalLivros,
    acao: { tipo: "corrigir" },
    detalhe: "Aluno não encontrado. Escolha a turma e o aluno em “Corrigir”.",
  };
}

interface LoteContexto {
  fase: FaseLote;
  arquivos: File[];
  itens: ItemLote[];
  progresso: { atual: number; total: number };
  tempoMs: number;
  turmas: Turma[];
  /** O GET das turmas da escola falhou (a mensagem): sem elas, o "Corrigir" não lista
   *  turmas (o aluno novo segue com a turma da prévia, ``correspondencia.turma_id``) —
   *  a conferência avisa e deixa tentar de novo. */
  erroTurmas: string | null;
  recarregandoTurmas: boolean;
  /** Rebusca as turmas e refaz o destino dos arquivos que ninguém corrigiu à mão. */
  recarregarTurmas: () => Promise<void>;
  emAndamento: boolean;
  /** Resultado do recálculo final do lote (null = não rodou). */
  recalculo: EstadoRecalculo;
  recalculando: boolean;
  /** Refaz o POST /recalcular do lote (depois de uma falha). */
  refazerRecalculo: () => Promise<void>;
  adicionar: (novos: FileList | File[]) => void;
  removerArquivo: (indice: number) => void;
  limparArquivos: () => void;
  analisarTodos: () => Promise<void>;
  /** `dataRelatorio` ("AAAA-MM-DD"): obrigatória quando algum arquivo é total
   *  acumulado (formato "resumo" sem "Intervalo de datas") — ver `lib/dataRelatorio`. */
  importarTodos: (dataRelatorio?: string) => Promise<void>;
  alternarIgnorar: (id: string) => void;
  vincular: (id: string, aluno: Aluno, turmaNome: string) => void;
  recomecar: () => void;
}

const Contexto = createContext<LoteContexto | null>(null);

/** POST /recalcular do lote: devolve o resultado em vez de lançar. */
async function recalcularEscola(escolaId: number): Promise<EstadoRecalculo> {
  try {
    const r = await api<{ mensagem?: string } | null>(
      `/escolas/${escolaId}/importacoes/recalcular`, { method: "POST" });
    return { estado: "ok", mensagem: r && typeof r.mensagem === "string" ? r.mensagem : null };
  } catch (e) {
    return {
      estado: "falhou",
      erro: e instanceof Error && e.message ? e.message : "Falha ao recalcular as notas.",
    };
  }
}

export function ImportacaoLoteProvider({ children }: { children: ReactNode }) {
  const { escolaId } = useApp();
  const [fase, setFase] = useState<FaseLote>("selecao");
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [itens, setItens] = useState<ItemLote[]>([]);
  const [progresso, setProgresso] = useState({ atual: 0, total: 0 });
  const [tempoMs, setTempoMs] = useState(0);
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [erroTurmas, setErroTurmas] = useState<string | null>(null);
  const [recarregandoTurmas, setRecarregandoTurmas] = useState(false);
  const [recalculo, setRecalculo] = useState<EstadoRecalculo>(null);
  const [recalculando, setRecalculando] = useState(false);
  // Escola em que o lote foi importado (o recálculo refeito vale para ela).
  const escolaDoLoteRef = useRef<number | null>(null);
  // Snapshot dos itens para o loop de importação (evita estado obsoleto).
  const itensRef = useRef<ItemLote[]>([]);
  itensRef.current = itens;
  // Escola VIVA: os loops assíncronos (análise/importação) comparam a escola em
  // que começaram com esta ref para abortar o setState se o usuário trocar de
  // escola no meio — a escrita já em curso continua na escola de origem (o
  // escolaId fica capturado no closure), mas a UI não repovoa dados de A em B.
  const escolaIdRef = useRef(escolaId);
  escolaIdRef.current = escolaId;

  const adicionar = useCallback((novos: FileList | File[]) => {
    const pdfs = Array.from(novos).filter(
      (f) => f.name.toLowerCase().endsWith(".pdf") || f.type === "application/pdf",
    );
    setArquivos((atuais) => {
      const chaves = new Set(atuais.map((f) => `${f.name}:${f.size}`));
      const mesclados = [...atuais];
      for (const f of pdfs) {
        const chave = `${f.name}:${f.size}`;
        if (!chaves.has(chave)) {
          chaves.add(chave);
          mesclados.push(f);
        }
      }
      return mesclados;
    });
  }, []);

  const removerArquivo = useCallback((indice: number) => {
    setArquivos((atuais) => atuais.filter((_, i) => i !== indice));
  }, []);

  const limparArquivos = useCallback(() => setArquivos([]), []);

  const analisarTodos = useCallback(async () => {
    if (!escolaId || arquivos.length === 0) return;
    const escolaDaAnalise = escolaId; // aborta se o usuário trocar de escola
    setFase("analisando");
    setItens([]);
    let listaTurmas: Turma[] = [];
    let falhaTurmas: string | null = null;
    try {
      listaTurmas = await api<Turma[]>(`/escolas/${escolaId}/turmas`);
    } catch (e) {
      // A análise segue (cada arquivo é lido por si), mas a falha não é engolida: a
      // conferência a mostra e deixa tentar de novo.
      listaTurmas = [];
      falhaTurmas = mensagemDoErro(e, "Falha ao carregar as turmas.");
    }
    if (escolaIdRef.current !== escolaDaAnalise) return;
    setTurmas(listaTurmas);
    setErroTurmas(falhaTurmas);

    const total = arquivos.length;
    const acumulados: ItemLote[] = [];
    for (let i = 0; i < total; i++) {
      if (escolaIdRef.current !== escolaDaAnalise) return; // trocou de escola
      const arquivo = arquivos[i];
      setProgresso({ atual: i, total });
      let item: ItemLote;
      try {
        const dados = new FormData();
        dados.append("arquivo", arquivo);
        const analise = await apiUpload<Analise>(`/escolas/${escolaId}/importacoes/analisar`, dados);
        item = montarItem(arquivo, i, analise, listaTurmas);
      } catch (e) {
        item = {
          id: `${i}-${arquivo.name}`, nome: arquivo.name, arquivo, analise: null,
          status: "erro", origem: "nenhum", alunoNome: "", turmaNome: "", totalLivros: 0,
          acao: { tipo: "corrigir" }, corrigido: false, ignorado: false,
          detalhe: e instanceof Error ? e.message : "Falha ao ler o PDF.",
        };
      }
      acumulados.push(item);
      setItens([...acumulados]);
    }
    if (escolaIdRef.current !== escolaDaAnalise) return;
    setProgresso({ atual: total, total });
    setFase("conferencia");
  }, [escolaId, arquivos]);

  const importarTodos = useCallback(async (dataRelatorio = "") => {
    if (!escolaId) return;
    // A importação PERTENCE à escola em que começou: as gravações vão para ela
    // (URL explícita) mesmo que o usuário troque de escola no meio — o que NÃO
    // pode é a UI da nova escola repovoar com o progresso/itens da anterior.
    const escolaDaImportacao = escolaId;
    const naEscola = () => escolaIdRef.current === escolaDaImportacao;
    const alvo = itensRef.current.filter(importavel);
    if (alvo.length === 0) return;
    setFase("importando");
    setRecalculo(null);
    escolaDoLoteRef.current = escolaDaImportacao;
    const inicio = Date.now();
    const total = alvo.length;
    const mapa = new Map(itensRef.current.map((it) => [it.id, { ...it }] as [string, ItemLote]));
    let feitos = 0;
    for (const it of alvo) {
      if (naEscola()) setProgresso({ atual: feitos, total });
      try {
        const linhas = it
          .analise!.linhas.filter((l) => l.erros.length === 0)
          .map((l) => ({
            nome: l.nome,
            dados: l.dados,
            aluno_id: it.acao.tipo === "importar" ? it.acao.alunoId : null,
            criar_em_turma_id: it.acao.tipo === "criar" ? it.acao.turmaId : null,
            criar_em_turma_nome: it.acao.tipo === "revisao" ? it.acao.turmaNome : null,
            // "Revisão": o backend nunca associa nem cria nesta linha.
            deixar_para_revisao: it.acao.tipo === "revisao",
          }));
        // Total acumulado: vai com a data do relatório (a tela a exige antes de
        // gravar); sem ela, o servidor recusa em vez de datar com o relógio de agora.
        const dataReferencia = exigeDataDoRelatorio(it.analise!)
          ? instanteDoRelatorio(dataRelatorio)
          : null;
        const resposta = await api<ResultadoImportacao>(`/escolas/${escolaDaImportacao}/importacoes/confirmar`, {
          method: "POST",
          body: JSON.stringify({
            plataforma: it.analise!.plataforma,
            formato: it.analise!.formato,
            tipo: it.analise!.tipo,
            arquivo_token: it.analise!.arquivo_token,
            arquivo_nome: it.analise!.arquivo_nome,
            // "Intervalo de datas" do relatório (Matific): data os dados no período
            periodo_inicio: it.analise!.periodo_inicio || null,
            periodo_fim: it.analise!.periodo_fim || null,
            data_referencia: dataReferencia,
            linhas,
            recalcular: false,
          }),
        });
        // A resposta diz o que aconteceu: um 200 não é "importado" quando o arquivo
        // foi para Revisões de identidade ou quando nada foi gravado.
        Object.assign(mapa.get(it.id)!, resultadoDaResposta(resposta));
      } catch (e) {
        // O motivo da recusa (409, 400, 403, 500, sem conexão) vai para o relatório.
        const item = mapa.get(it.id)!;
        item.resultado = "erro";
        item.erroImportacao = mensagemDoErro(e, "Falha ao gravar este arquivo.");
      }
      feitos += 1;
      if (naEscola()) {
        setProgresso({ atual: feitos, total });
        setItens([...mapa.values()]);
      }
    }
    for (const it of mapa.values()) {
      if (it.resultado) continue;
      it.resultado = it.ignorado ? "ignorado" : "pendente";
    }
    // Os arquivos já estão gravados; o recálculo é o que leva os dados às notas
    // e aos rankings. Se ele falhar, o relatório DIZ isso e oferece refazer —
    // antes o erro era engolido e o lote aparecia como concluído por inteiro.
    const resultadoRecalculo = await recalcularEscola(escolaDaImportacao);
    if (naEscola()) {
      setRecalculo(resultadoRecalculo);
      setTempoMs(Date.now() - inicio);
      setItens([...mapa.values()]);
      setFase("relatorio");
    }
  }, [escolaId]);

  const refazerRecalculo = useCallback(async () => {
    const escolaDoLote = escolaDoLoteRef.current;
    if (escolaDoLote === null || escolaIdRef.current !== escolaDoLote) return;
    setRecalculando(true);
    const resultado = await recalcularEscola(escolaDoLote);
    if (escolaIdRef.current === escolaDoLote) setRecalculo(resultado);
    setRecalculando(false);
  }, []);

  const recarregarTurmas = useCallback(async () => {
    if (!escolaId) return;
    const escolaDaBusca = escolaId;
    setRecarregandoTurmas(true);
    try {
      const lista = await api<Turma[]>(`/escolas/${escolaDaBusca}/turmas`);
      if (escolaIdRef.current !== escolaDaBusca) return;
      setTurmas(lista);
      setErroTurmas(null);
      // Refaz o destino com as turmas: só o que ninguém corrigiu à mão (o "Ignorar"
      // escolhido continua).
      setItens((atuais) => atuais.map((it, i) => (it.analise && !it.corrigido
        ? { ...montarItem(it.arquivo, i, it.analise, lista), id: it.id, ignorado: it.ignorado }
        : it)));
    } catch (e) {
      if (escolaIdRef.current === escolaDaBusca) {
        setErroTurmas(mensagemDoErro(e, "Falha ao carregar as turmas."));
      }
    } finally {
      setRecarregandoTurmas(false);
    }
  }, [escolaId]);

  const alternarIgnorar = useCallback((id: string) => {
    setItens((atuais) => atuais.map((it) => (it.id === id ? { ...it, ignorado: !it.ignorado } : it)));
  }, []);

  const vincular = useCallback((id: string, aluno: Aluno, turmaNome: string) => {
    setItens((atuais) =>
      atuais.map((it) =>
        it.id === id
          ? {
              ...it, status: "ok" as const, alunoNome: aluno.nome, turmaNome,
              acao: { tipo: "importar" as const, alunoId: aluno.id },
              corrigido: true, ignorado: false,
              detalhe: "Aluno definido manualmente.",
            }
          : it,
      ),
    );
  }, []);

  const recomecar = useCallback(() => {
    setArquivos([]);
    setItens([]);
    setProgresso({ atual: 0, total: 0 });
    setTempoMs(0);
    setRecalculo(null);
    escolaDoLoteRef.current = null;
    setTurmas([]); // turmas foram resolvidas contra o tenant anterior
    setErroTurmas(null);
    setFase("selecao");
  }, []);

  // Ao TROCAR de escola, zera o lote em preparo: os itens foram resolvidos
  // (aluno_id/turma_id) contra a escola anterior; importá-los já na nova escola
  // gravaria alunos/notas no tenant errado (isolamento por escola). Uma
  // importação já em curso continua na escola em que começou (escolaId fica
  // capturado no closure de importarTodos); aqui só descartamos a prévia.
  useEffect(() => {
    recomecar();
  }, [escolaId, recomecar]);

  const emAndamento = fase === "analisando" || fase === "importando";

  return (
    <Contexto.Provider value={{
      fase, arquivos, itens, progresso, tempoMs, turmas, emAndamento,
      erroTurmas, recarregandoTurmas, recarregarTurmas,
      recalculo, recalculando, refazerRecalculo,
      adicionar, removerArquivo, limparArquivos, analisarTodos, importarTodos,
      alternarIgnorar, vincular, recomecar,
    }}>
      {children}
    </Contexto.Provider>
  );
}

export function useImportacaoLote(): LoteContexto {
  const contexto = useContext(Contexto);
  if (!contexto) throw new Error("useImportacaoLote requer ImportacaoLoteProvider");
  return contexto;
}
