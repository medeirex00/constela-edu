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
import type { Aluno, Analise, Turma } from "../lib/types";
import { useApp } from "./AppContext";

export type FaseLote = "selecao" | "analisando" | "conferencia" | "importando" | "relatorio";
export type StatusItem = "ok" | "alerta" | "pendente" | "erro";

export type AcaoItem =
  | { tipo: "importar"; alunoId: number }
  | { tipo: "criar"; turmaId: number }
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
  resultado?: "importado" | "erro" | "ignorado" | "pendente";
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

/** true quando o arquivo tem um destino resolvido e será enviado ao confirmar. */
export function importavel(item: ItemLote): boolean {
  return !item.ignorado && (item.acao.tipo === "importar" || item.acao.tipo === "criar");
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
  // Só a ALTA confiança do motor ("vinculado") e o nome EXATO único auto-importam
  // no lote. "revisar"/"provavel" (possível duplicata) e "bloqueado" caem em criar
  // e passam pelo motor seguro na confirmação — grafia/similaridade parecida nunca
  // vira vínculo automático (a detecção surfaça depois p/ fusão manual).
  if (corresp?.aluno_id
      && (corresp.status === "vinculado" || corresp.status === "exato")) {
    return {
      ...base, status: "ok", origem, totalLivros,
      alunoNome: corresp.aluno_nome ?? nome, turmaNome,
      acao: { tipo: "importar", alunoId: corresp.aluno_id },
      detalhe: "",
    };
  }
  if (turmaId) {
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
  /** O GET das turmas da escola falhou (a mensagem): sem elas, o aluno novo fica sem
   *  turma e o "Corrigir" não lista turmas — a conferência avisa e deixa tentar de novo. */
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
          }));
        // Total acumulado: vai com a data do relatório (a tela a exige antes de
        // gravar); sem ela, o servidor recusa em vez de datar com o relógio de agora.
        const dataReferencia = exigeDataDoRelatorio(it.analise!)
          ? instanteDoRelatorio(dataRelatorio)
          : null;
        await api(`/escolas/${escolaDaImportacao}/importacoes/confirmar`, {
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
        mapa.get(it.id)!.resultado = "importado";
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
