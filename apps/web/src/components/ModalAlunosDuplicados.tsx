/**
 * "Fundir duplicatas" de alunos — detecção automática + revisão + fusão em lote.
 *
 * Nada funde sozinho: o sistema PROPÕE pares (nome idêntico/subconjunto/
 * abreviação, sempre da MESMA turma) e o gestor confirma por caixa de seleção.
 * Três faixas para o gestor não precisar olhar centenas uma a uma:
 *   🟢 alta      — cópia de plataforma do MESMO aluno da lista → vem MARCADA;
 *   🟡 provável  — abreviação de um único aluno da lista → DESMARCADA, mas o
 *                  "Selecionar todos" une o grupo num clique (confira a lista);
 *   🔴 revisar   — nome parecido/gêmeo → DESMARCADA, com aviso ⚠ (olho a olho).
 * A regra do dono continua: pior fundir errado do que deixar duplicado — por
 * isso só a 🟢 é pré-marcada e há uma confirmação explícita antes de aplicar.
 */
import { AlertTriangle, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError, api } from "../lib/api";
import {
  type BimestrePremiacao, nomeBimestrePremiacao, type ResumoLeiturasRepetidas, textoBimestres,
} from "./LeiturasRepetidas";
import { estiloCheckbox } from "./PessoasUi";
import { Botao, Carregando, Mensagem, Modal, Vazio } from "./ui";

type TomFaixa = "alta" | "provavel" | "revisar";

/** Selo de cor da faixa (verde/âmbar/vermelho). É reforço visual: o nome da faixa
 *  sempre vem escrito ao lado (a cor nunca é o único portador da informação). */
const COR_FAIXA: Record<TomFaixa, string> = {
  alta: "bg-emerald-500",
  provavel: "bg-amber-400",
  revisar: "bg-rose-500",
};

function SeloFaixa({ tom }: { tom: TomFaixa }) {
  return <span aria-hidden className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${COR_FAIXA[tom]}`} />;
}

interface Impacto {
  leituras: number;
  snapshots_matific: number;
  snapshots_elefante: number;
  eventos: number;
  notas: number;
  plataformas: string[];
}
type Confianca = "alta" | "provavel" | "revisar";
/** O que a fusão faz com o Constela Quest do par (``alunos_fusao.plano_quest``):
 *  fica o progresso e o cartão que a criança usa; as duas fichas com progresso,
 *  o servidor recusa o par (``conflito``). ``texto`` já vem em português. */
interface PlanoQuest {
  tem_quest: boolean;
  conflito: boolean;
  texto: string | null;
}
interface CandidatoAluno {
  loser_id: number;
  manter_id: number;
  apagar: string;
  manter: string;
  turma: string;
  confianca: Confianca;
  motivo: "nome_identico" | "subconjunto" | "abreviacao" | "variante";
  impacto: Impacto;
  /** Livros que estão nas duas fichas: fica a data do principal (A7). */
  leituras?: ResumoLeiturasRepetidas;
  quest?: PlanoQuest;
  /** Por que o servidor vai recusar este par (contas diferentes da mesma plataforma,
   *  ou as duas fichas com progresso no Constela Quest); null = não recusa. */
  recusa?: string | null;
}
interface PreviaAlunos {
  candidatos: CandidatoAluno[];
  total: number;
  alta?: number;
  provavel?: number;
  revisar: number;
}
interface ResultadoFusao {
  fundidos: number;
  falhas: { loser_id: number; motivo: string }[];
  mensagem: string;
}

const NOME_PLATAFORMA: Record<string, string> = {
  matific: "Matific",
  elefante: "Elefante Letrado",
};

// Fusões por requisição. Fundir centenas num único POST estourava o tempo do
// gateway; lotes pequenos que commitam sozinhos evitam o timeout e salvam o
// progresso mesmo se a conexão cair no meio.
const TAM_LOTE = 20;

/** Resumo do que será movido do duplicado para o principal. */
function resumoImpacto(i: Impacto): string {
  const partes: string[] = [];
  if (i.plataformas.length) {
    partes.push(i.plataformas.map((p) => NOME_PLATAFORMA[p] ?? p).join(" + "));
  }
  if (i.leituras) partes.push(`${i.leituras} leitura(s)`);
  const registros = i.snapshots_matific + i.snapshots_elefante;
  if (registros) partes.push(`${registros} registro(s) de plataforma`);
  if (i.notas) partes.push(`${i.notas} nota(s)`);
  return partes.length ? partes.join(" · ") : "sem dados vinculados";
}

/** Linha de aviso do par: só quando há livro repetido com data diferente. */
function avisoLeituras(c: CandidatoAluno): string | null {
  const l = c.leituras;
  if (!l || l.com_data_diferente === 0) return null;
  const base = `${l.com_data_diferente} livro(s) nas duas fichas com data diferente: fica a data de “${c.manter}”`;
  return l.por_bimestre.length ? `${base}; deixam de contar ${textoBimestres(l)}.` : `${base}.`;
}

/** Soma do que os pares SELECIONADOS fazem com as datas (vai no painel de confirmação). */
function somaLeituras(cands: CandidatoAluno[]) {
  let diferentes = 0;
  let noBimestre = 0;
  let bimestre: BimestrePremiacao | null = null;
  for (const c of cands) {
    const l = c.leituras;
    if (!l) continue;
    diferentes += l.com_data_diferente;
    noBimestre += l.no_bimestre ?? 0;
    bimestre = bimestre ?? l.bimestre ?? null;
  }
  return { diferentes, noBimestre, bimestre };
}

function motivoTexto(c: CandidatoAluno): string {
  if (c.motivo === "nome_identico") return "nome idêntico, mesma turma";
  if (c.motivo === "abreviacao") return "nome abreviado do mais completo";
  if (c.motivo === "variante") return "variação de grafia do mesmo nome";
  return "nome contido no nome mais completo";
}

export default function ModalAlunosDuplicados({ escolaId, aoFechar, aoConcluir }: {
  escolaId: number;
  aoFechar: () => void;
  aoConcluir: () => void;
}) {
  const [previa, setPrevia] = useState<PreviaAlunos | null>(null);
  const [selecionados, setSelecionados] = useState<Set<number>>(new Set());
  const [resultado, setResultado] = useState<ResultadoFusao | null>(null);
  const [confirmando, setConfirmando] = useState(false);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [progresso, setProgresso] = useState<{ feitos: number; total: number } | null>(null);

  useEffect(() => {
    let vivo = true;
    api<PreviaAlunos>(`/escolas/${escolaId}/alunos/duplicados`)
      .then((r) => {
        if (!vivo) return;
        setPrevia(r);
        // "alta" já vem marcada; "revisar" DESMARCADA (o gestor confirma). O par
        // que o servidor vai recusar (`recusa`) nunca vem marcado.
        setSelecionados(new Set(
          r.candidatos.filter((c) => c.confianca === "alta" && !c.recusa)
            .map((c) => c.loser_id)));
      })
      .catch((e) => {
        if (vivo) setErro(e instanceof ApiError ? e.message : "Não foi possível carregar.");
      });
    return () => { vivo = false; };
  }, [escolaId]);

  function alternar(id: number) {
    setConfirmando(false);
    setSelecionados((atual) => {
      const nova = new Set(atual);
      if (nova.has(id)) nova.delete(id);
      else nova.add(id);
      return nova;
    });
  }

  /** Marca (ou desmarca) TODOS os pares de uma lista de uma vez — o "selecionar
   *  todos" que evita clicar um a um numa escola com muitas duplicatas. */
  function marcarVarios(ids: number[], marcar: boolean) {
    setConfirmando(false);
    setSelecionados((atual) => {
      const nova = new Set(atual);
      for (const id of ids) {
        if (marcar) nova.add(id);
        else nova.delete(id);
      }
      return nova;
    });
  }

  /** Agrupa os loser_ids selecionados em COMPONENTES conexos (un par liga seu
   *  loser ao seu manter). Fundir 300+ num único POST estourava o tempo do
   *  gateway ("Não foi possível conectar") — então enviamos em lotes pequenos que
   *  commitam sozinhos. Mas um lote NUNCA pode partir uma cadeia/leque: a proteção
   *  de cadeia do servidor (recusa A→B→C) só funciona se ele vir o componente
   *  inteiro num mesmo POST. Por isso o corte é por componente, nunca no meio. */
  function lotesPorComponente(tam: number): number[][] {
    const porLoser = new Map((previa?.candidatos ?? []).map((c) => [c.loser_id, c]));
    const pai = new Map<number, number>();
    const raiz = (x: number): number => {
      let r = x;
      while (pai.get(r) !== r) r = pai.get(r) as number;
      return r;
    };
    const unir = (a: number, b: number) => {
      if (!pai.has(a)) pai.set(a, a);
      if (!pai.has(b)) pai.set(b, b);
      pai.set(raiz(a), raiz(b));
    };
    const sel = [...selecionados].filter((id) => porLoser.has(id));
    for (const id of sel) {
      const c = porLoser.get(id) as CandidatoAluno;
      unir(c.loser_id, c.manter_id);   // liga loser↔manter (cadeia e leque)
    }
    const porRaiz = new Map<number, number[]>();
    for (const id of sel) {
      const r = raiz(id);
      (porRaiz.get(r) ?? porRaiz.set(r, []).get(r)!).push(id);
    }
    // Empacota COMPONENTES inteiros em lotes de até `tam` (um componente maior que
    // `tam` — raro, um leque grande — vai sozinho, sem ser partido).
    const lotes: number[][] = [];
    let atual: number[] = [];
    for (const comp of porRaiz.values()) {
      if (atual.length && atual.length + comp.length > tam) {
        lotes.push(atual);
        atual = [];
      }
      atual.push(...comp);
    }
    if (atual.length) lotes.push(atual);
    return lotes;
  }

  async function fundir() {
    setOcupado(true);
    setErro("");
    const lotes = lotesPorComponente(TAM_LOTE);
    const total = lotes.reduce((n, l) => n + l.length, 0);
    let fundidos = 0;
    const falhas: ResultadoFusao["falhas"] = [];
    let feitos = 0;
    setProgresso({ feitos: 0, total });
    try {
      for (const lote of lotes) {
        const r = await api<ResultadoFusao>(
          `/escolas/${escolaId}/alunos/duplicados/corrigir`,
          {
            method: "POST",
            body: JSON.stringify({ loser_ids: lote, confirmacao: "FUNDIR" }),
          },
        );
        fundidos += r.fundidos;
        falhas.push(...r.falhas);
        feitos += lote.length;
        setProgresso({ feitos, total });
      }
      setResultado({
        fundidos, falhas,
        mensagem: `${fundidos} fusão(ões) aplicada(s).`,
      });
      aoConcluir();   // recarrega a lista de alunos por trás
    } catch (e) {
      // Cada lote commita sozinho: o que já entrou está SALVO. Reporta o parcial e
      // orienta a recarregar e continuar (a detecção reencontra só o que sobrou).
      const base = e instanceof ApiError ? e.message : "Não foi possível fundir.";
      setErro(fundidos > 0
        ? `${base} Mas ${fundidos} já foram unidas com sucesso — feche, recarregue a tela e repita para o restante.`
        : `${base} Nenhuma foi unida. Tente de novo (a tela envia em lotes menores agora).`);
      setConfirmando(false);
      if (fundidos > 0) aoConcluir();
    } finally {
      setOcupado(false);
      setProgresso(null);
    }
  }

  const conta = (c: Confianca) =>
    previa?.candidatos.filter((x) => x.confianca === c).length ?? 0;
  const contaAlta = conta("alta");
  const contaProvavel = conta("provavel");
  const contaRevisar = conta("revisar");

  // Grupos gerados dinamicamente. A faixa 🔴 "revisar" é SUB-DIVIDIDA por motivo
  // só para ORGANIZAR a leitura (casos parecidos juntos) — mas SEM "Selecionar
  // todos": cada par 🔴 exige decisão individual (o backend diz que a semelhança
  // de nome "não distingue LUÍS/LUIZ de MARIA/MARTA — só um humano decide"). O
  // atalho de lote (`lote: true`) fica só em 🟢 (já marcada) e 🟡 (ancorada num
  // único aluno da Lista Piloto). Nada 🔴 vem pré-marcado. O último filtro é um
  // CATCH-ALL: garante que nenhum "revisar" de motivo novo/desconhecido suma da
  // tela. Isto é só apresentação: não muda o que o backend sugere.
  const cands = previa?.candidatos ?? [];
  const marcados = cands.filter((c) => selecionados.has(c.loser_id));
  const datas = somaLeituras(marcados);
  const recusados = marcados.filter((c) => c.recusa).length;
  const questMovidos = marcados.some((c) => !c.recusa && c.quest?.tem_quest);
  const MOTIVOS_REV = ["variante", "nome_identico", "subconjunto", "abreviacao"];
  const especifica: {
    chave: string; rotulo: string; dica: string; lote: boolean; tom: TomFaixa;
    filtro: (c: CandidatoAluno) => boolean;
  }[] = [
    {
      chave: "alta",
      rotulo: "Alta confiança — versão de plataforma do mesmo aluno",
      tom: "alta",
      dica: "Já vêm marcadas. É a ficha do Matific/Elefante do mesmo aluno da sua lista.",
      lote: true,
      filtro: (c) => c.confianca === "alta",
    },
    {
      chave: "provavel",
      rotulo: "Provável — abreviação de um aluno da sua lista",
      tom: "provavel",
      dica: "O jeito rápido: clique em “Selecionar todos” e una o grupo de uma vez (confira antes se sua Lista Piloto está completa).",
      lote: true,
      filtro: (c) => c.confianca === "provavel",
    },
    {
      chave: "rev-variante",
      rotulo: "Variação de grafia — confira par a par",
      tom: "revisar",
      dica: "São os MAIS arriscados: “LUÍS/LUIZ” é a mesma criança, mas “MARIA/MARTA” são crianças diferentes e se parecem igual. Leia cada par e marque só os que você confirma serem a mesma pessoa.",
      lote: false,
      filtro: (c) => c.confianca === "revisar" && c.motivo === "variante",
    },
    {
      chave: "rev-identico",
      rotulo: "Nome idêntico — pode ser gêmeo/homônimo",
      tom: "revisar",
      dica: "Mesmo nome exato, sem nascimento para corroborar. Confira nº de chamada/nascimento e marque só os confirmados.",
      lote: false,
      filtro: (c) => c.confianca === "revisar" && c.motivo === "nome_identico",
    },
    {
      chave: "rev-abreviacao",
      rotulo: "Abreviação sem correspondência na sua lista",
      tom: "revisar",
      dica: "Um nome curto que não achei na Lista Piloto. Confira quem é o cadastro certo e marque só os confirmados.",
      lote: false,
      filtro: (c) => c.confianca === "revisar"
        && (c.motivo === "subconjunto" || c.motivo === "abreviacao"),
    },
    {
      chave: "rev-outros",
      rotulo: "Outros — conferir um a um",
      tom: "revisar",
      dica: "Casos que não se encaixam nas categorias acima. Confira cada par antes de marcar.",
      lote: false,
      filtro: (c) => c.confianca === "revisar" && !MOTIVOS_REV.includes(c.motivo),
    },
  ];
  const grupos = especifica
    .map((g) => ({ ...g, itens: cands.filter(g.filtro) }))
    .filter((g) => g.itens.length > 0);

  return (
    <Modal titulo="Fundir duplicatas de alunos" aberto aoFechar={aoFechar} largura="max-w-2xl">
      {resultado !== null ? (
        // --- Resultado ---
        <>
          <Mensagem tipo="ok">
            {resultado.fundidos} aluno(s) unificado(s).
            {resultado.falhas.length > 0
              && ` ${resultado.falhas.length} não pôde(ram) ser fundido(s).`}
          </Mensagem>
          {resultado.falhas.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-amber-800 dark:text-amber-300">
              {resultado.falhas.map((f) => (
                <li key={f.loser_id}>• Cadastro {f.loser_id}: {f.motivo}</li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex justify-end">
            <Botao onClick={aoFechar}>Fechar</Botao>
          </div>
        </>
      ) : previa === null && !erro ? (
        <div className="mt-2"><Carregando /></div>
      ) : previa === null ? (
        // A detecção falhou: só o erro — nada de "Encontrei  possível(is)…" com a
        // contagem vazia (era o que aparecia antes).
        <>
          <Mensagem tipo="erro">{erro}</Mensagem>
          <div className="mt-4 flex justify-end">
            <Botao variante="secundario" onClick={aoFechar}>Fechar</Botao>
          </div>
        </>
      ) : previa.total === 0 ? (
        <Vazio icone={UsersRound} titulo="Nenhuma duplicata encontrada"
               descricao="Não achei alunos duplicados (mesmo nome/começo de nome na mesma turma)." />
      ) : (
        // --- Prévia + confirmação ---
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Encontrei <strong>{previa?.total}</strong> possível(is) duplicata(s).{" "}
            {contaAlta > 0 && (
              <>As <SeloFaixa tom="alta" /> <strong>{contaAlta}</strong> de alta confiança já vêm marcadas. </>
            )}
            As <SeloFaixa tom="provavel" /> <strong>{contaProvavel}</strong> prováveis você une <strong>em lote</strong>{" "}
            com um clique em “Selecionar todos” — é o seu atalho grande. As <SeloFaixa tom="revisar" />{" "}
            <strong>{contaRevisar}</strong> de revisão você <strong>confere par a par</strong> (organizei
            por tipo pra ficar mais rápido de ler). Ao unir, mantenho o cadastro principal e
            junto nele todos os dados (Matific, Elefante, leituras, histórico), sem perder nada.
          </p>
          {contaAlta === 0 && contaProvavel > 0 && (
            <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              A faixa de alta confiança está vazia porque nada foi pré-marcado com segurança suficiente: o
              Matific/Elefante costumam guardar o nome <strong>abreviado</strong> (“ANA J”,
              “PEDRO L”) e não trazem data de nascimento — e eu só pré-marco quando há um nome
              completo idêntico <em>ou</em> nascimento igual para corroborar. No seu caso, os
              pares seguros caem todos em “Provável” (abreviação que bate com um único aluno da lista).
            </p>
          )}

          <div className="mt-4 max-h-[50vh] space-y-3 overflow-y-auto pr-1">
            {grupos.filter((g) => g.itens.length > 0).map((grupo) => {
              // "Selecionar todos" deixa de fora o par que o servidor vai recusar.
              const ids = grupo.itens.filter((c) => !c.recusa).map((c) => c.loser_id);
              const todosMarcados = ids.every((id) => selecionados.has(id));
              return (
              <div key={grupo.chave} className="rounded-2xl border border-zinc-200/80 p-3 dark:border-zinc-800">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                      <SeloFaixa tom={grupo.tom} />
                      <span>{grupo.rotulo} ({grupo.itens.length})</span>
                    </p>
                    <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{grupo.dica}</p>
                  </div>
                  {grupo.lote && (
                    <button
                      type="button"
                      onClick={() => marcarVarios(ids, !todosMarcados)}
                      className="shrink-0 rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700 transition-colors hover:bg-indigo-100 dark:bg-indigo-500/15 dark:text-indigo-300"
                    >
                      {todosMarcados ? "Desmarcar todos" : "Selecionar todos"}
                    </button>
                  )}
                </div>
                <div className="space-y-1.5">
                  {grupo.itens.map((c) => {
                    const marcado = selecionados.has(c.loser_id);
                    return (
                      <label
                        key={c.loser_id}
                        className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${
                          marcado
                            ? "border-indigo-300 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-500/10"
                            : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-700 dark:hover:border-zinc-600"
                        }`}
                      >
                        <input
                          type="checkbox"
                          className={`mt-0.5 ${estiloCheckbox}`}
                          checked={marcado}
                          onChange={() => alternar(c.loser_id)}
                        />
                        <span className="min-w-0 flex-1 text-sm">
                          <span>
                            Unir <strong>{c.apagar}</strong> → <strong>{c.manter}</strong>{" "}
                            <span className="text-xs text-zinc-500 dark:text-zinc-400">
                              · {c.turma}
                            </span>
                          </span>
                          {c.confianca === "revisar" && (
                            <span className="mt-0.5 block text-xs font-medium text-amber-800 dark:text-amber-300">
                              ⚠ confira: “{c.apagar}” pode ser outra criança ({motivoTexto(c)})
                            </span>
                          )}
                          <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                            Será movido: {resumoImpacto(c.impacto)}
                          </span>
                          {avisoLeituras(c) && (
                            <span className="mt-0.5 block text-xs font-medium text-amber-800 dark:text-amber-300">
                              ⚠ {avisoLeituras(c)}
                            </span>
                          )}
                          {c.recusa ? (
                            <span className="mt-0.5 block text-xs font-medium text-amber-800 dark:text-amber-300">
                              ⚠ {c.recusa}
                            </span>
                          ) : c.quest?.texto && (
                            <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                              {c.quest.texto}
                            </span>
                          )}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
              );
            })}
          </div>

          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}

          {confirmando ? (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4 dark:border-rose-500/40 dark:bg-rose-500/10">
              <p className="flex items-start gap-2 text-sm text-rose-800 dark:text-rose-200">
                <AlertTriangle size={16} aria-hidden className="mt-0.5 shrink-0" />
                <span>
                  Isto vai fundir <strong>{selecionados.size}</strong> par(es) de cadastros
                  num único aluno cada. Os dados são consolidados no principal.
                  <strong> Esta ação é irreversível.</strong>
                  {questMovidos && (
                    <span className="mt-1 block">
                      No Constela Quest, ficam o progresso e o cartão que a criança usa; o outro
                      cartão deixa de entrar.
                    </span>
                  )}
                  {recusados > 0 && (
                    <span className="mt-1 block">
                      {recusados} par(es) marcado(s) não será(ão) unido(s): o motivo está
                      escrito em cada um.
                    </span>
                  )}
                  {datas.diferentes > 0 && (
                    <span className="mt-1 block">
                      Nos pares marcados, {datas.diferentes} livro(s) estão nas duas fichas com data
                      diferente: fica sempre a data do cadastro principal
                      {datas.bimestre && datas.noBimestre > 0
                        ? `, e ${datas.noBimestre} deixa(m) de contar no ${nomeBimestrePremiacao(datas.bimestre)}`
                        : ""}
                      . Para manter a outra data, desmarque o par e faça a fusão pela ficha do aluno
                      (⋮ › Fundir com outro aluno), escolhendo a ficha principal.
                    </span>
                  )}
                  {selecionados.size > TAM_LOTE && (
                    <span className="mt-1 block text-xs font-normal">
                      Vou enviar em lotes de {TAM_LOTE} para não travar — pode levar alguns
                      segundos. Não feche a janela.
                    </span>
                  )}
                </span>
              </p>
              {ocupado && progresso && (
                <div className="mt-3">
                  <div className="mb-1.5 flex justify-between text-xs font-medium text-rose-800 dark:text-rose-200">
                    <span>Unindo…</span>
                    <span className="tabular-nums">{progresso.feitos} de {progresso.total}</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-rose-100 dark:bg-rose-500/20">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-rose-400 to-rose-600 transition-all"
                      style={{ width: `${progresso.total ? (progresso.feitos / progresso.total) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              )}
              <div className="mt-3 flex justify-end gap-2">
                <Botao variante="secundario" onClick={() => setConfirmando(false)} disabled={ocupado}>
                  Voltar
                </Botao>
                <Botao variante="perigo" onClick={fundir} disabled={ocupado}>
                  <UsersRound size={15} aria-hidden />{" "}
                  {ocupado
                    ? (progresso ? `Unindo ${progresso.feitos}/${progresso.total}…` : "Fundindo…")
                    : "Confirmar fusão"}
                </Botao>
              </div>
            </div>
          ) : (
            <div className="mt-4 flex justify-end gap-2">
              <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
              <Botao
                variante="perigo"
                disabled={ocupado || selecionados.size === 0}
                onClick={() => setConfirmando(true)}
              >
                <UsersRound size={15} aria-hidden /> Unir {selecionados.size} selecionada(s)
              </Botao>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
