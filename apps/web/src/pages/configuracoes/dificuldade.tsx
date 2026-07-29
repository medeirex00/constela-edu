/* -------------------------------------------------------------------------
 * Configuração de dificuldade do Elefante Letrado, reutilizada em dois lugares:
 * a página Métricas (Configurações) e o módulo Elefante Letrado.
 *
 *   • EditorNiveis        — CADASTRA as faixas (Pré-Leitor, Nível 1…): nome,
 *                           códigos de letra e pontos por livro. É o passo que
 *                           vem ANTES de pontuar (sem faixas, não há o que pontuar).
 *   • PontuacaoPorTurma   — pontua livremente cada código de nível por turma.
 *   • AvisoSemNiveis      — estado "sem faixas" com atalho de 1 clique para os
 *                           níveis padrão (fim do beco "cadastre na aba anterior").
 * ----------------------------------------------------------------------- */
import { GripVertical, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge, Botao, Card, Carregando, Mensagem, estiloInput } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { api, ApiError } from "../../lib/api";
import type { Nivel } from "../../lib/types";

/** Códigos de letra digitados ("aa, bb  cc") → lista limpa (maiúsculo, únicos). */
function parseCodigos(texto: string): string[] {
  const vistos = new Set<string>();
  const limpos: string[] = [];
  for (const bruto of texto.split(/[\s,;]+/)) {
    const cod = bruto.trim().toUpperCase();
    if (cod && !vistos.has(cod)) {
      vistos.add(cod);
      limpos.push(cod);
    }
  }
  return limpos;
}

/* -------------------------------------------------------------------------
 * Aviso "sem níveis" — mensagem clara + atalho para os níveis padrão.
 * Usado no vazio da pontuação por turma e do "livros por nível" do Elefante.
 * ----------------------------------------------------------------------- */
export function AvisoSemNiveis({ aoCriar }: { aoCriar?: () => void }) {
  const { escolaId, usuario } = useApp();
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const [criando, setCriando] = useState(false);
  const [erro, setErro] = useState("");

  async function usarPadrao() {
    if (!escolaId) return;
    setCriando(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/configuracoes/niveis/padrao`, { method: "POST" });
      aoCriar?.();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível criar os níveis.");
    } finally {
      setCriando(false);
    }
  }

  return (
    <div className="space-y-3 text-sm">
      <p className="text-zinc-600 dark:text-zinc-300">
        Nenhum <strong>nível de dificuldade</strong> cadastrado ainda. Os níveis (Pré-Leitor,
        Nível 1, Nível 2…) definem quantos pontos cada livro vale e são a base da pontuação por
        turma e do “livros por nível”.
      </p>
      {!somenteLeitura && (
        <div>
          <Botao onClick={usarPadrao} disabled={criando}>
            {criando ? "Criando níveis…" : "Usar níveis padrão do Elefante Letrado"}
          </Botao>
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            Cria as faixas padrão (Pré-Leitor a Nível 5). Você pode ajustá-las depois na aba
            <strong> Níveis de dificuldade</strong>.
          </p>
        </div>
      )}
      {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * EditorNiveis (PRD §38): cadastro das faixas de dificuldade. Criar, editar
 * (nome, códigos, pontos por livro) e excluir. Toda alteração recalcula as notas.
 * ----------------------------------------------------------------------- */
type LinhaNivel = { id: number; nome: string; codigos: string; pontos: string };

export function EditorNiveis({ aoMudar }: { aoMudar?: () => void }) {
  const { escolaId, usuario } = useApp();
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const { dados, erro, carregando, recarregar } = useApi<{ niveis: Nivel[] }>(
    escolaId ? `/escolas/${escolaId}/configuracoes/dificuldade` : null,
  );
  const niveis = useMemo(() => dados?.niveis ?? [], [dados]);

  const [linhas, setLinhas] = useState<LinhaNivel[]>([]);
  const [novo, setNovo] = useState<{ nome: string; codigos: string; pontos: string } | null>(null);
  const [ocupado, setOcupado] = useState<number | "novo" | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  // Semeia (e ressemeia) o formulário editável a partir dos níveis carregados.
  useEffect(() => {
    setLinhas(niveis.map((n) => ({
      id: n.id, nome: n.nome, codigos: (n.codigos ?? []).join(", "), pontos: String(n.pontos_padrao),
    })));
  }, [niveis]);

  function alterar(id: number, campo: keyof Omit<LinhaNivel, "id">, valor: string) {
    setLinhas((prev) => prev.map((l) => (l.id === id ? { ...l, [campo]: valor } : l)));
  }

  function mudou(l: LinhaNivel): boolean {
    const orig = niveis.find((n) => n.id === l.id);
    if (!orig) return false;
    return (
      l.nome.trim() !== orig.nome ||
      Number(l.pontos) !== orig.pontos_padrao ||
      parseCodigos(l.codigos).join(",") !== (orig.codigos ?? []).join(",")
    );
  }

  function validar(nome: string, pontosTexto: string): number | null {
    const pontos = Number(pontosTexto);
    if (!nome.trim() || Number.isNaN(pontos) || pontos < 0) {
      setMensagem({ tipo: "erro", texto: "Informe um nome e os pontos por livro (0 ou mais)." });
      return null;
    }
    return pontos;
  }

  async function salvarLinha(l: LinhaNivel) {
    if (!escolaId) return;
    const pontos = validar(l.nome, l.pontos);
    if (pontos === null) return;
    setOcupado(l.id);
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}/configuracoes/niveis/${l.id}`, {
        method: "PUT",
        body: JSON.stringify({ nome: l.nome.trim(), codigos: parseCodigos(l.codigos), pontos_padrao: pontos }),
      });
      setMensagem({ tipo: "ok", texto: "Nível salvo. Notas recalculadas." });
      recarregar();
      aoMudar?.();
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível salvar." });
    } finally {
      setOcupado(null);
    }
  }

  async function excluir(l: LinhaNivel) {
    if (!escolaId) return;
    if (!window.confirm(`Remover o nível “${l.nome}”? As pontuações que dependem dele serão recalculadas.`)) return;
    setOcupado(l.id);
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}/configuracoes/niveis/${l.id}`, { method: "DELETE" });
      setMensagem({ tipo: "ok", texto: `Nível “${l.nome}” removido. Notas recalculadas.` });
      recarregar();
      aoMudar?.();
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível remover." });
    } finally {
      setOcupado(null);
    }
  }

  async function criar() {
    if (!escolaId || !novo) return;
    const pontos = validar(novo.nome, novo.pontos);
    if (pontos === null) return;
    setOcupado("novo");
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}/configuracoes/niveis`, {
        method: "POST",
        body: JSON.stringify({ nome: novo.nome.trim(), codigos: parseCodigos(novo.codigos), pontos_padrao: pontos }),
      });
      setMensagem({ tipo: "ok", texto: "Nível criado. Notas recalculadas." });
      setNovo(null);
      recarregar();
      aoMudar?.();
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível criar." });
    } finally {
      setOcupado(null);
    }
  }

  if (carregando) return <Carregando />;
  if (erro) return <Mensagem tipo="erro">{erro.message}</Mensagem>;

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Cadastre as faixas de dificuldade dos livros. Cada faixa reúne os códigos de nível (ex.:
        <span className="mx-1 font-mono">AA, BB</span>) e define quantos pontos cada livro vale.
        É o primeiro passo — depois você pontua por turma.
      </p>

      {linhas.length === 0 && !novo ? (
        <Card className="p-6">
          <AvisoSemNiveis aoCriar={() => { recarregar(); aoMudar?.(); }} />
          {!somenteLeitura && (
            <div className="mt-4 border-t border-zinc-200 pt-4 dark:border-zinc-800">
              <Botao variante="neutro" onClick={() => setNovo({ nome: "", codigos: "", pontos: "1" })}>
                <Plus size={15} /> Adicionar nível manualmente
              </Botao>
            </div>
          )}
        </Card>
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <th className="px-4 py-2 font-medium">Nível</th>
                <th className="px-4 py-2 font-medium">Códigos de nível</th>
                <th className="px-4 py-2 text-right font-medium">Pontos/livro</th>
                {!somenteLeitura && <th className="w-28 px-4 py-2" />}
              </tr>
            </thead>
            <tbody>
              {linhas.map((l) => (
                <tr key={l.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <td className="px-4 py-2 align-middle">
                    <span className="flex items-center gap-2">
                      <GripVertical size={14} className="shrink-0 text-zinc-300 dark:text-zinc-600" />
                      <input
                        className={`${estiloInput} min-w-[9rem]`}
                        value={l.nome}
                        disabled={somenteLeitura || ocupado === l.id}
                        onChange={(e) => alterar(l.id, "nome", e.target.value)}
                      />
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <input
                      className={`${estiloInput} w-full font-mono`}
                      placeholder="AA, BB, CC"
                      value={l.codigos}
                      disabled={somenteLeitura || ocupado === l.id}
                      onChange={(e) => alterar(l.id, "codigos", e.target.value)}
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <input
                      type="number"
                      min={0}
                      step="0.5"
                      className={`${estiloInput} w-20 text-right tabular-nums`}
                      value={l.pontos}
                      disabled={somenteLeitura || ocupado === l.id}
                      onChange={(e) => alterar(l.id, "pontos", e.target.value)}
                    />
                  </td>
                  {!somenteLeitura && (
                    <td className="px-4 py-2">
                      <div className="flex justify-end gap-1">
                        <Botao
                          onClick={() => salvarLinha(l)}
                          disabled={ocupado === l.id || !mudou(l)}
                        >
                          {ocupado === l.id ? "…" : "Salvar"}
                        </Botao>
                        <button
                          type="button"
                          title="Remover nível"
                          aria-label={`Remover nível ${l.nome}`}
                          disabled={ocupado === l.id}
                          onClick={() => excluir(l)}
                          className="rounded-lg p-2 text-zinc-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40 dark:hover:bg-red-500/10"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}

              {novo && (
                <tr className="border-b border-zinc-100 bg-indigo-50/40 last:border-0 dark:border-zinc-800/60 dark:bg-indigo-500/5">
                  <td className="px-4 py-2">
                    <input
                      className={`${estiloInput} min-w-[9rem]`}
                      placeholder="Nome (ex.: Nível 6)"
                      autoFocus
                      value={novo.nome}
                      onChange={(e) => setNovo({ ...novo, nome: e.target.value })}
                    />
                  </td>
                  <td className="px-4 py-2">
                    <input
                      className={`${estiloInput} w-full font-mono`}
                      placeholder="AA, BB, CC"
                      value={novo.codigos}
                      onChange={(e) => setNovo({ ...novo, codigos: e.target.value })}
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <input
                      type="number"
                      min={0}
                      step="0.5"
                      className={`${estiloInput} w-20 text-right tabular-nums`}
                      value={novo.pontos}
                      onChange={(e) => setNovo({ ...novo, pontos: e.target.value })}
                    />
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex justify-end gap-1">
                      <Botao onClick={criar} disabled={ocupado === "novo"}>
                        {ocupado === "novo" ? "…" : "Criar"}
                      </Botao>
                      <Botao variante="neutro" onClick={() => setNovo(null)} disabled={ocupado === "novo"}>
                        Cancelar
                      </Botao>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      )}

      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}

      {!somenteLeitura && linhas.length > 0 && !novo && (
        <Botao variante="neutro" onClick={() => setNovo({ nome: "", codigos: "", pontos: "1" })}>
          <Plus size={15} /> Adicionar nível
        </Botao>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Dificuldade por Turma (PRD §39): pontuação LIVRE por nível, para CADA turma.
 * Sem faixas fixas — o gestor define quantos pontos cada nível (AA..Z) vale na
 * turma escolhida. Turmas sem config usam o padrão da escola.
 * ----------------------------------------------------------------------- */
type CatalogoNivel = { codigo: string; pontos_padrao: number; faixa: string };
type TurmaPontos = { turma_id: number; nome: string; ano_escolar: string; pontos: Record<string, number> };
type PontuacaoResp = { catalogo: CatalogoNivel[]; turmas: TurmaPontos[] };

export function PontuacaoPorTurma() {
  const { escolaId, usuario } = useApp();
  // Secretaria (rede vinculada, não-global) enxerga as métricas, mas não altera.
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const { dados, erro, carregando, recarregar } = useApi<PontuacaoResp>(
    escolaId ? `/escolas/${escolaId}/configuracoes/pontuacao-turma` : null,
  );
  const [turmaId, setTurmaId] = useState<number | null>(null);
  const [edit, setEdit] = useState<Record<string, number>>({});
  const [aplicarTodos, setAplicarTodos] = useState("");
  // Replicar esta MESMA config para outras turmas (marcadas antes de salvar).
  const [replicar, setReplicar] = useState<Set<number>>(new Set());
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  const padrao = useMemo(
    () => Object.fromEntries((dados?.catalogo ?? []).map((c) => [c.codigo, c.pontos_padrao])),
    [dados],
  );
  const turma = (dados?.turmas ?? []).find((t) => t.turma_id === turmaId) ?? null;

  // Seleciona a 1ª turma quando os dados chegam.
  useEffect(() => {
    if (dados && turmaId === null && dados.turmas.length) setTurmaId(dados.turmas[0].turma_id);
  }, [dados, turmaId]);

  // Semeia a tabela editável da turma escolhida (override sobre o padrão).
  useEffect(() => {
    if (!dados || !turma) return;
    const seed: Record<string, number> = {};
    for (const c of dados.catalogo) seed[c.codigo] = turma.pontos[c.codigo] ?? c.pontos_padrao;
    setEdit(seed);
    setReplicar(new Set());   // troca de turma zera a seleção de replicação
    setMensagem(null);
  }, [turmaId, dados]); // eslint-disable-line react-hooks/exhaustive-deps

  if (carregando) return <Carregando />;
  if (erro) return <Mensagem tipo="erro">{erro.message}</Mensagem>;
  if (!dados) return <Carregando />;
  if (dados.catalogo.length === 0)
    return (
      <Card className="p-6">
        <AvisoSemNiveis aoCriar={recarregar} />
      </Card>
    );
  if (dados.turmas.length === 0)
    return (
      <Card className="p-6 text-sm text-zinc-500 dark:text-zinc-400">
        Cadastre turmas para configurar a pontuação por nível.
      </Card>
    );

  const alterados = Object.keys(edit).filter((c) => edit[c] !== padrao[c]).length;
  const outrasTurmas = (dados.turmas ?? []).filter((t) => t.turma_id !== turmaId);

  function alternarReplicar(id: number) {
    setReplicar((atuais) => {
      const prox = new Set(atuais);
      if (prox.has(id)) prox.delete(id);
      else prox.add(id);
      return prox;
    });
  }

  async function salvar() {
    if (!escolaId || turmaId === null) return;
    // Envia só o que DIFERE do padrão (config esparsa).
    const pontos: Record<string, number> = {};
    for (const [cod, val] of Object.entries(edit)) if (val !== padrao[cod]) pontos[cod] = val;
    setSalvando(true);
    setMensagem(null);
    try {
      const r = await api<{ mensagem: string }>(
        `/escolas/${escolaId}/configuracoes/pontuacao-turma`,
        { method: "PUT", body: JSON.stringify({
          turma_id: turmaId, pontos, aplicar_em: Array.from(replicar),
        }) },
      );
      setMensagem({ tipo: "ok", texto: r.mensagem });
      setReplicar(new Set());
      recarregar();
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível salvar." });
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Defina livremente quantos pontos cada nível de livro vale <strong>nesta turma</strong>. Cada
        turma pode ter a sua tabela; níveis não alterados usam o padrão da escola.
      </p>

      <Card className="flex flex-wrap items-center gap-3 p-4">
        <label className="text-sm font-medium">Turma</label>
        <select
          className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950"
          value={turmaId ?? ""}
          onChange={(e) => setTurmaId(Number(e.target.value))}
        >
          {dados.turmas.map((t) => (
            <option key={t.turma_id} value={t.turma_id}>
              {t.nome} · {t.ano_escolar}
            </option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-sm text-zinc-500 dark:text-zinc-400">Aplicar a todos:</span>
          <input
            type="number"
            min={0}
            step="0.5"
            value={aplicarTodos}
            onChange={(e) => setAplicarTodos(e.target.value)}
            className="w-20 rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-right text-sm tabular-nums dark:border-zinc-700 dark:bg-zinc-950"
          />
          <Botao
            variante="neutro"
            onClick={() => {
              const v = Number(aplicarTodos);
              if (aplicarTodos === "" || Number.isNaN(v) || v < 0) return;
              setEdit(Object.fromEntries(Object.keys(edit).map((c) => [c, v])));
            }}
          >
            Aplicar
          </Botao>
        </div>
      </Card>

      <Card>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 p-4 sm:grid-cols-3 lg:grid-cols-4">
          {dados.catalogo.map((c) => {
            const val = edit[c.codigo] ?? c.pontos_padrao;
            const custom = val !== c.pontos_padrao;
            return (
              <div key={c.codigo} className="flex items-center justify-between gap-2 py-1">
                <span className="flex items-center gap-1.5 text-sm">
                  <span className="font-medium tabular-nums">{c.codigo}</span>
                  {custom && <Badge tom="destaque">alterado</Badge>}
                </span>
                <input
                  type="number"
                  min={0}
                  step="0.5"
                  value={val}
                  onChange={(e) =>
                    setEdit((prev) => ({ ...prev, [c.codigo]: Number(e.target.value) }))
                  }
                  className="w-16 rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-right text-sm tabular-nums dark:border-zinc-700 dark:bg-zinc-950"
                />
              </div>
            );
          })}
        </div>
      </Card>

      {/* Replicar a MESMA config para outras turmas ANTES de salvar. Cada uma
          continua editável depois (basta trocar no seletor de turma). */}
      {!somenteLeitura && outrasTurmas.length > 0 && (
        <Card className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium">
              Aplicar estes mesmos níveis a outras turmas?{" "}
              <span className="font-normal text-zinc-500 dark:text-zinc-400">(opcional)</span>
            </p>
            {replicar.size > 0 && (
              <button
                type="button"
                className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                onClick={() => setReplicar(new Set())}
              >
                limpar seleção
              </button>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3 lg:grid-cols-4">
            {outrasTurmas.map((t) => (
              <label key={t.turma_id} className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                  checked={replicar.has(t.turma_id)}
                  onChange={() => alternarReplicar(t.turma_id)}
                />
                <span className="truncate">{t.nome}</span>
              </label>
            ))}
          </div>
          {replicar.size > 0 && (
            <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
              A configuração atual vai <strong>sobrescrever</strong> a das {replicar.size} turma(s)
              marcada(s). Você pode ajustar cada uma depois.
            </p>
          )}
        </Card>
      )}

      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}
      <div className="flex items-center gap-3">
        <Botao onClick={salvar} disabled={salvando || somenteLeitura}>
          {somenteLeitura ? "Somente leitura"
            : salvando ? "Salvando e recalculando..."
            : replicar.size > 0 ? `Salvar e aplicar a ${replicar.size + 1} turmas`
            : "Salvar pontuação da turma"}
        </Botao>
        <span className="text-sm text-zinc-500 dark:text-zinc-400">
          {alterados > 0 ? `${alterados} nível(is) diferente(s) do padrão.` : "Usando o padrão da escola."}
        </span>
      </div>
    </div>
  );
}
