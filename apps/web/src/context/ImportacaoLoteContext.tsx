/**
 * Estado GLOBAL da importação em lote.
 *
 * A análise e a importação rodam neste contexto (acima das rotas), então o
 * usuário pode navegar livremente pelo sistema enquanto os arquivos são
 * processados — um indicador flutuante (no Layout) mostra o progresso e leva
 * de volta à tela de Importações. Nada se perde ao trocar de página.
 */
import { createContext, useCallback, useContext, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, apiUpload } from "../lib/api";
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
  const turmaId = acharTurmaPorNome(turmas, analise.turma_detectada);
  const turmaNome = turmas.find((t) => t.id === turmaId)?.nome ?? analise.turma_detectada ?? "";

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
  if (corresp?.aluno_id && (corresp.status === "exato" || corresp.status === "provavel")) {
    const baixa = corresp.status === "provavel";
    return {
      ...base, status: baixa ? "alerta" : "ok", origem, totalLivros,
      alunoNome: corresp.aluno_nome ?? nome, turmaNome,
      acao: { tipo: "importar", alunoId: corresp.aluno_id },
      detalhe: baixa ? `Correspondência provável (${corresp.similaridade ?? "?"}%). Confira o aluno.` : "",
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
  emAndamento: boolean;
  adicionar: (novos: FileList | File[]) => void;
  removerArquivo: (indice: number) => void;
  limparArquivos: () => void;
  analisarTodos: () => Promise<void>;
  importarTodos: () => Promise<void>;
  alternarIgnorar: (id: string) => void;
  vincular: (id: string, aluno: Aluno, turmaNome: string) => void;
  recomecar: () => void;
}

const Contexto = createContext<LoteContexto | null>(null);

export function ImportacaoLoteProvider({ children }: { children: ReactNode }) {
  const { escolaId } = useApp();
  const [fase, setFase] = useState<FaseLote>("selecao");
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [itens, setItens] = useState<ItemLote[]>([]);
  const [progresso, setProgresso] = useState({ atual: 0, total: 0 });
  const [tempoMs, setTempoMs] = useState(0);
  const [turmas, setTurmas] = useState<Turma[]>([]);
  // Snapshot dos itens para o loop de importação (evita estado obsoleto).
  const itensRef = useRef<ItemLote[]>([]);
  itensRef.current = itens;

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
    setFase("analisando");
    setItens([]);
    let listaTurmas: Turma[] = [];
    try {
      listaTurmas = await api<Turma[]>(`/escolas/${escolaId}/turmas`);
    } catch {
      listaTurmas = [];
    }
    setTurmas(listaTurmas);

    const total = arquivos.length;
    const acumulados: ItemLote[] = [];
    for (let i = 0; i < total; i++) {
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
    setProgresso({ atual: total, total });
    setFase("conferencia");
  }, [escolaId, arquivos]);

  const importarTodos = useCallback(async () => {
    if (!escolaId) return;
    const alvo = itensRef.current.filter(importavel);
    if (alvo.length === 0) return;
    setFase("importando");
    const inicio = Date.now();
    const total = alvo.length;
    const mapa = new Map(itensRef.current.map((it) => [it.id, { ...it }] as [string, ItemLote]));
    let feitos = 0;
    for (const it of alvo) {
      setProgresso({ atual: feitos, total });
      try {
        const linhas = it
          .analise!.linhas.filter((l) => l.erros.length === 0)
          .map((l) => ({
            nome: l.nome,
            dados: l.dados,
            aluno_id: it.acao.tipo === "importar" ? it.acao.alunoId : null,
            criar_em_turma_id: it.acao.tipo === "criar" ? it.acao.turmaId : null,
          }));
        await api(`/escolas/${escolaId}/importacoes/confirmar`, {
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
            linhas,
            recalcular: false,
          }),
        });
        mapa.get(it.id)!.resultado = "importado";
      } catch {
        mapa.get(it.id)!.resultado = "erro";
      }
      feitos += 1;
      setProgresso({ atual: feitos, total });
      setItens([...mapa.values()]);
    }
    for (const it of mapa.values()) {
      if (it.resultado) continue;
      it.resultado = it.ignorado ? "ignorado" : "pendente";
    }
    try {
      await api(`/escolas/${escolaId}/importacoes/recalcular`, { method: "POST" });
    } catch {
      /* dados já gravados; o recálculo pode ser refeito na próxima importação */
    }
    setTempoMs(Date.now() - inicio);
    setItens([...mapa.values()]);
    setFase("relatorio");
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
    setFase("selecao");
  }, []);

  const emAndamento = fase === "analisando" || fase === "importando";

  return (
    <Contexto.Provider value={{
      fase, arquivos, itens, progresso, tempoMs, turmas, emAndamento,
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
