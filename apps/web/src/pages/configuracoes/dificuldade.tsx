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
import { Info, Lock, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge, Botao, Card, Carregando, Confirmacao, Mensagem, classesTabela, estiloInput } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { api, ApiError } from "../../lib/api";
import type { Nivel } from "../../lib/types";

/** `estiloInput` sem a largura total: para campos curtos (pontos, turma). */
const inputCurto = estiloInput.replace("w-full ", "");

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
  // Níveis de dificuldade são REFERÊNCIA/base da premiação: só o administrador
  // geral (global) cria/edita. Coordenador/escola/Secretaria só visualizam.
  const somenteLeitura = !usuario?.is_global;
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
      {somenteLeitura ? (
        // A escola não administra a régua: nada de níveis, pontos ou pontuação
        // por turma — só o que aconteceu e com quem falar.
        <p className="text-zinc-600 dark:text-zinc-300">
          A régua desta escola ainda não foi preparada pela Constela. Fale com o suporte.
        </p>
      ) : (
        <p className="text-zinc-600 dark:text-zinc-300">
          Nenhum <strong>nível de dificuldade</strong> cadastrado ainda. Os níveis (Pré-Leitor,
          Nível 1, Nível 2…) definem quantos pontos cada livro vale e são a base da pontuação por
          turma e do “livros por nível”.
        </p>
      )}
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
  // Só o administrador geral (global) edita os níveis — para todos os demais
  // (coordenador, escola, Secretaria) a tela é somente leitura. O backend também
  // exige admin global nas rotas de escrita de níveis.
  const somenteLeitura = !usuario?.is_global;
  const { dados, erro, carregando, recarregar } = useApi<{ niveis: Nivel[] }>(
    escolaId ? `/escolas/${escolaId}/configuracoes/dificuldade` : null,
  );
  const niveis = useMemo(() => dados?.niveis ?? [], [dados]);

  const [linhas, setLinhas] = useState<LinhaNivel[]>([]);
  const [novo, setNovo] = useState<{ nome: string; codigos: string; pontos: string } | null>(null);
  const [ocupado, setOcupado] = useState<number | "novo" | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  // Nível à espera da confirmação de remoção.
  const [paraRemover, setParaRemover] = useState<LinhaNivel | null>(null);

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
      setParaRemover(null);
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
      {/* Legenda: deixa claro que estes são valores de REFERÊNCIA (base) da
          premiação — não a pontuação final — e que a edição é do admin geral. */}
      <div className="flex items-start gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/70 px-4 py-3.5 text-sm text-indigo-900 dark:border-indigo-500/25 dark:bg-indigo-500/10 dark:text-indigo-100">
        <Info size={18} aria-hidden className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-300" />
        <p>
          Estes números são valores de <strong>referência</strong> (base) para a premiação:
          representam a <strong>faixa de pontos</strong> de cada nível de dificuldade — do mínimo ao
          máximo. Eles <strong>não são a pontuação final</strong> que o aluno recebe; servem de base
          para você configurar a pontuação real em <strong>Dificuldade por turma</strong>.
          <span className="mt-1.5 flex items-center gap-1.5 font-medium">
            <Lock size={13} aria-hidden /> A edição destes valores é exclusiva do administrador geral.
          </span>
        </p>
      </div>

      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Cada faixa (Pré-Leitor, Nível 1, Nível 2…) reúne os códigos de nível dos livros (ex.:
        <span className="mx-1 rounded-md bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">AA, BB</span>) e define quantos pontos cada livro daquela
        faixa vale como referência.
      </p>

      {linhas.length === 0 && !novo ? (
        <Card className="p-6">
          <AvisoSemNiveis aoCriar={() => { recarregar(); aoMudar?.(); }} />
          {!somenteLeitura && (
            <div className="mt-4 border-t border-zinc-200 pt-4 dark:border-zinc-800">
              <Botao variante="neutro" onClick={() => setNovo({ nome: "", codigos: "", pontos: "1" })}>
                <Plus size={15} aria-hidden /> Adicionar nível manualmente
              </Botao>
            </div>
          )}
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className={classesTabela.moldura}>
          <table className={`${classesTabela.tabela} min-w-[36rem]`}>
            <thead>
              <tr>
                <th className={classesTabela.th}>Nível</th>
                <th className={classesTabela.th}>Códigos de nível</th>
                <th className={`${classesTabela.th} text-right`}>Pontos/livro</th>
                {!somenteLeitura && <th className={`${classesTabela.th} w-28`} />}
              </tr>
            </thead>
            <tbody>
              {linhas.map((l) => (
                <tr key={l.id} className={classesTabela.tr}>
                  <td className="px-4 py-2.5 align-middle">
                    <input
                      className={`${estiloInput} min-w-[9rem]`}
                      value={l.nome}
                      disabled={somenteLeitura || ocupado === l.id}
                      onChange={(e) => alterar(l.id, "nome", e.target.value)}
                    />
                  </td>
                  <td className="px-4 py-2.5">
                    <input
                      className={`${estiloInput} w-full font-mono`}
                      placeholder="AA, BB, CC"
                      value={l.codigos}
                      disabled={somenteLeitura || ocupado === l.id}
                      onChange={(e) => alterar(l.id, "codigos", e.target.value)}
                    />
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <input
                      type="number"
                      min={0}
                      step="0.5"
                      className={`${inputCurto} w-24 text-right font-semibold tabular-nums`}
                      value={l.pontos}
                      disabled={somenteLeitura || ocupado === l.id}
                      onChange={(e) => alterar(l.id, "pontos", e.target.value)}
                    />
                  </td>
                  {!somenteLeitura && (
                    <td className="px-4 py-2.5">
                      <div className="flex justify-end gap-1">
                        <Botao
                          tamanho="sm"
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
                          onClick={() => setParaRemover(l)}
                          className="grid h-9 w-9 place-items-center rounded-full text-zinc-500 transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40 dark:text-zinc-400 dark:hover:bg-rose-500/10"
                        >
                          <Trash2 size={15} aria-hidden />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}

              {novo && (
                <tr className="border-t border-zinc-100 bg-indigo-50/40 dark:border-zinc-800 dark:bg-indigo-500/5">
                  <td className="px-4 py-2.5">
                    <input
                      className={`${estiloInput} min-w-[9rem]`}
                      placeholder="Nome (ex.: Nível 6)"
                      autoFocus
                      value={novo.nome}
                      onChange={(e) => setNovo({ ...novo, nome: e.target.value })}
                    />
                  </td>
                  <td className="px-4 py-2.5">
                    <input
                      className={`${estiloInput} w-full font-mono`}
                      placeholder="AA, BB, CC"
                      value={novo.codigos}
                      onChange={(e) => setNovo({ ...novo, codigos: e.target.value })}
                    />
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <input
                      type="number"
                      min={0}
                      step="0.5"
                      className={`${inputCurto} w-24 text-right font-semibold tabular-nums`}
                      value={novo.pontos}
                      onChange={(e) => setNovo({ ...novo, pontos: e.target.value })}
                    />
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex justify-end gap-1">
                      <Botao tamanho="sm" onClick={criar} disabled={ocupado === "novo"}>
                        {ocupado === "novo" ? "…" : "Criar"}
                      </Botao>
                      <Botao variante="neutro" tamanho="sm" onClick={() => setNovo(null)} disabled={ocupado === "novo"}>
                        Cancelar
                      </Botao>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          </div>
        </Card>
      )}

      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}

      {!somenteLeitura && linhas.length > 0 && !novo && (
        <Botao variante="neutro" onClick={() => setNovo({ nome: "", codigos: "", pontos: "1" })}>
          <Plus size={15} aria-hidden /> Adicionar nível
        </Botao>
      )}

      {!somenteLeitura && (
        <Confirmacao
          titulo="Remover este nível?"
          aberto={paraRemover !== null}
          aoFechar={() => setParaRemover(null)}
          aoConfirmar={() => {
            if (paraRemover) void excluir(paraRemover);
          }}
          rotuloConfirmar={paraRemover && ocupado === paraRemover.id ? "Removendo..." : "Remover nível"}
          variante="perigo"
          ocupado={paraRemover !== null && ocupado === paraRemover.id}
        >
          {paraRemover && (
            <p>
              Remover o nível <strong className="text-zinc-800 dark:text-zinc-100">“{paraRemover.nome}”</strong>?
              As pontuações que dependem dele serão recalculadas.
            </p>
          )}
        </Confirmacao>
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
type TurmaPontos = {
  turma_id: number; nome: string; ano_escolar: string; ano_letivo?: number;
  pontos: Record<string, number>;
};
// A API manda só as turmas do ano letivo ATIVO da escola (a pontuação é por turma e as
// turmas de um ano novo são outras): ``ano_letivo`` diz de que ano são.
type PontuacaoResp = { catalogo: CatalogoNivel[]; ano_letivo?: number; turmas: TurmaPontos[] };

export function PontuacaoPorTurma() {
  const { escolaId, usuario } = useApp();
  // GOVERNANÇA: só o Admin Global altera a pontuação por turma (PUT responde
  // 403 para os demais). A tela só é alcançável por ele, mas a trava fica aqui
  // para nunca oferecer um botão que falharia ao salvar.
  const somenteLeitura = !usuario?.is_global;
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
        {dados.ano_letivo
          ? `Nenhuma turma ativa no ano letivo ${dados.ano_letivo}. Cadastre as turmas deste ano para configurar a pontuação por nível.`
          : "Cadastre turmas para configurar a pontuação por nível."}
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

      <Card className="flex flex-wrap items-center gap-3 p-4 sm:p-5">
        <label className="text-sm font-semibold" htmlFor="pontuacao-turma-escolhida">
          {dados.ano_letivo ? `Turma do ano letivo ${dados.ano_letivo}` : "Turma"}
        </label>
        <select
          id="pontuacao-turma-escolhida"
          className={`${inputCurto} w-auto min-w-[12rem]`}
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
            aria-label="Pontos para aplicar a todos os níveis"
            value={aplicarTodos}
            disabled={somenteLeitura}
            onChange={(e) => setAplicarTodos(e.target.value)}
            className={`${inputCurto} w-24 text-right tabular-nums disabled:cursor-not-allowed disabled:opacity-60`}
          />
          <Botao
            variante="neutro"
            disabled={somenteLeitura}
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
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 p-4 sm:grid-cols-3 sm:p-5 lg:grid-cols-4">
          {dados.catalogo.map((c) => {
            const val = edit[c.codigo] ?? c.pontos_padrao;
            const custom = val !== c.pontos_padrao;
            return (
              <div key={c.codigo} className="flex items-center justify-between gap-2 py-1">
                <span className="flex items-center gap-1.5 text-sm">
                  <span className="inline-flex min-w-[2.25rem] justify-center rounded-lg bg-zinc-100 px-1.5 py-1 text-xs font-bold tabular-nums text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                    {c.codigo}
                  </span>
                  {custom && <Badge tom="destaque">alterado</Badge>}
                </span>
                <input
                  type="number"
                  min={0}
                  step="0.5"
                  aria-label={`Pontos do nível ${c.codigo}`}
                  value={val}
                  disabled={somenteLeitura}
                  onChange={(e) =>
                    setEdit((prev) => ({ ...prev, [c.codigo]: Number(e.target.value) }))
                  }
                  className="w-20 rounded-xl border border-zinc-200 bg-zinc-50 px-2 py-1.5 text-right text-sm font-semibold tabular-nums transition-colors focus:border-indigo-500 focus:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-800"
                />
              </div>
            );
          })}
        </div>
      </Card>

      {/* Replicar a MESMA config para outras turmas ANTES de salvar. Cada uma
          continua editável depois (basta trocar no seletor de turma). */}
      {!somenteLeitura && outrasTurmas.length > 0 && (
        <Card className="p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold">
              Aplicar estes mesmos níveis a outras turmas?{" "}
              <span className="font-normal text-zinc-500 dark:text-zinc-400">(opcional)</span>
            </p>
            {replicar.size > 0 && (
              <button
                type="button"
                className="text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-300"
                onClick={() => setReplicar(new Set())}
              >
                limpar seleção
              </button>
            )}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {outrasTurmas.map((t) => (
              <label
                key={t.turma_id}
                className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-sm transition-colors ${
                  replicar.has(t.turma_id)
                    ? "border-indigo-300 bg-indigo-50 text-indigo-900 dark:border-indigo-500/40 dark:bg-indigo-500/10 dark:text-indigo-100"
                    : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-700"
                }`}
              >
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                  checked={replicar.has(t.turma_id)}
                  onChange={() => alternarReplicar(t.turma_id)}
                />
                <span className="truncate" title={t.nome}>{t.nome}</span>
              </label>
            ))}
          </div>
          {replicar.size > 0 && (
            <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">
              A configuração atual vai <strong>sobrescrever</strong> a das {replicar.size} turma(s)
              marcada(s). Você pode ajustar cada uma depois.
            </p>
          )}
        </Card>
      )}

      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}
      <div className="flex flex-wrap items-center gap-3">
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
