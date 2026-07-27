import { useEffect, useMemo, useState } from "react";

import { Badge, Botao, Card, Carregando, Mensagem, PageHeader } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { api, ApiError } from "../../lib/api";
import { nota } from "../../lib/formato";
import type { Pesos, Referencias } from "../../lib/types";

/* -------------------------------------------------------------------------
 * Editor genérico de pesos — reutilizado por Matific, Elefante, Questões
 * e Ranking Geral (PRD §25: componentes reutilizáveis; §29: nada fixo).
 * ----------------------------------------------------------------------- */
export function PesosEditor({
  namespace,
  rotulos,
  descricao,
}: {
  namespace: string;
  rotulos: Record<string, string>;
  descricao?: string;
}) {
  const { escolaId, usuario } = useApp();
  // Secretaria (rede vinculada, não-global) enxerga as métricas, mas não altera.
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const { dados, erro, carregando } = useApi<Pesos>(
    escolaId ? `/escolas/${escolaId}/configuracoes/pesos/${namespace}` : null,
  );
  const [valores, setValores] = useState<Record<string, number> | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  // Semeia o formulário editável a partir dos pesos carregados.
  useEffect(() => {
    if (dados) {
      setValores(dados.valores);
      setMensagem(null);
    }
  }, [dados]);

  if (carregando) return <Carregando />;
  if (erro) return <Mensagem tipo="erro">{erro.message}</Mensagem>;
  if (!valores) return <Carregando />;

  const soma = Math.round(Object.values(valores).reduce((total, valor) => total + valor, 0) * 100) / 100;
  const valido = Math.abs(soma - 100) < 0.01;

  async function salvar() {
    if (!escolaId || !valores) return;
    setSalvando(true);
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}/configuracoes/pesos/${namespace}`, {
        method: "PUT",
        body: JSON.stringify({ valores }),
      });
      setMensagem({ tipo: "ok", texto: "Pesos salvos. Todas as notas foram recalculadas." });
    } catch (excecao) {
      setMensagem({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message : "Não foi possível salvar os pesos.",
      });
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Card className="p-5">
      {descricao && <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
      <div className="space-y-4">
        {Object.entries(valores).map(([chave, valor]) => (
          <div key={chave} className="grid grid-cols-[1fr_auto] items-center gap-4">
            <div>
              <div className="mb-1 flex items-center justify-between text-sm">
                <span className="font-medium">{rotulos[chave] ?? chave}</span>
                <span className="tabular-nums text-zinc-500 dark:text-zinc-400">{valor}%</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                aria-label={rotulos[chave] ?? chave}
                className="w-full accent-indigo-600"
                value={valor}
                onChange={(evento) =>
                  setValores({ ...valores, [chave]: Number(evento.target.value) })
                }
              />
            </div>
            <input
              type="number"
              min={0}
              max={100}
              step={0.5}
              aria-label={`${rotulos[chave] ?? chave} (valor exato)`}
              className="w-20 rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-right text-sm tabular-nums dark:border-zinc-700 dark:bg-zinc-950"
              value={valor}
              onChange={(evento) =>
                setValores({ ...valores, [chave]: Number(evento.target.value) })
              }
            />
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-200 pt-4 dark:border-zinc-800">
        <Badge tom={valido ? "ok" : "alerta"}>Soma: {nota(soma)}%{valido ? "" : " — precisa ser 100%"}</Badge>
        <Botao onClick={salvar} disabled={!valido || salvando || somenteLeitura}>
          {somenteLeitura ? "Somente leitura" : salvando ? "Salvando e recalculando..." : "Salvar pesos"}
        </Botao>
      </div>
      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
    </Card>
  );
}

/* -------------------------------------------------------------------------
 * Referências de Normalização (PRD §31, §62): modo automático ou manual.
 * ----------------------------------------------------------------------- */
const ROTULOS_REFERENCIAS: Record<string, string> = {
  max_atividades: "Maior quantidade de atividades",
  max_media: "Maior pontuação média",
  max_estrelas: "Maior quantidade de estrelas",
  max_livros: "Maior quantidade de livros",
  max_pontos_dificuldade: "Maior pontuação de dificuldade",
  max_tentativas: "Maior nº de questões tentadas",
  max_acertos: "Maior nº de questões acertadas",
  max_tempo: "Maior tempo de leitura (min)",
};

function ReferenciasNormalizacao() {
  const { escolaId, usuario } = useApp();
  // Secretaria (rede vinculada, não-global) enxerga as métricas, mas não altera.
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const { dados: dadosApi, erro, carregando } = useApi<Referencias>(
    escolaId ? `/escolas/${escolaId}/configuracoes/referencias` : null,
  );
  // `dados` é semeado da busca e também atualizado após salvar (retorno do PUT).
  const [dados, setDados] = useState<Referencias | null>(null);
  const [modo, setModo] = useState<"auto" | "manual">("auto");
  const [manuais, setManuais] = useState<Record<string, number>>({});
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  // Semeia o formulário editável a partir das referências carregadas.
  useEffect(() => {
    if (!dadosApi) return;
    setDados(dadosApi);
    setModo(dadosApi.modo);
    const iniciais: Record<string, number> = {};
    for (const chave of Object.keys(ROTULOS_REFERENCIAS)) {
      iniciais[chave] = dadosApi.valores_manuais[chave] ?? dadosApi.valores_em_uso[chave] ?? 0;
    }
    setManuais(iniciais);
    setMensagem(null);
  }, [dadosApi]);

  if (carregando) return <Carregando />;
  if (erro) return <Mensagem tipo="erro">{erro.message}</Mensagem>;
  if (!dados) return <Carregando />;

  async function salvar() {
    if (!escolaId) return;
    setSalvando(true);
    setMensagem(null);
    try {
      const resposta = await api<Referencias>(`/escolas/${escolaId}/configuracoes/referencias`, {
        method: "PUT",
        body: JSON.stringify({ modo, valores_manuais: modo === "manual" ? manuais : {} }),
      });
      setDados(resposta);
      setMensagem({ tipo: "ok", texto: "Referências salvas. Todas as notas foram recalculadas." });
    } catch (excecao) {
      setMensagem({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message : "Não foi possível salvar.",
      });
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Card className="p-5">
      <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
        As referências definem o que vale <strong>100</strong> em cada indicador. No modo
        automático, o sistema usa os maiores resultados da própria base.
      </p>

      <div className="mb-5 inline-flex rounded-lg border border-zinc-300 p-0.5 dark:border-zinc-700">
        {(["auto", "manual"] as const).map((opcao) => (
          <button
            key={opcao}
            onClick={() => setModo(opcao)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              modo === opcao
                ? "bg-indigo-600 text-white"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
            }`}
          >
            {opcao === "auto" ? "Automático" : "Manual"}
          </button>
        ))}
      </div>

      <div className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
        {Object.entries(ROTULOS_REFERENCIAS).map(([chave, rotulo]) => (
          <div key={chave} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
            <div>
              <p className="text-sm font-medium">{rotulo}</p>
              <p className="text-xs text-zinc-400 dark:text-zinc-500">
                Em uso: {nota(dados.valores_em_uso[chave] ?? 0)}
              </p>
            </div>
            {modo === "manual" ? (
              <input
                type="number"
                min={0}
                aria-label={rotulo}
                className="w-28 rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-right text-sm tabular-nums dark:border-zinc-700 dark:bg-zinc-950"
                value={manuais[chave] ?? 0}
                onChange={(evento) => setManuais({ ...manuais, [chave]: Number(evento.target.value) })}
              />
            ) : (
              <Badge>automático</Badge>
            )}
          </div>
        ))}
      </div>

      <div className="mt-4 flex justify-end border-t border-zinc-200 pt-4 dark:border-zinc-800">
        <Botao onClick={salvar} disabled={salvando || somenteLeitura}>
          {somenteLeitura ? "Somente leitura" : salvando ? "Salvando e recalculando..." : "Salvar referências"}
        </Botao>
      </div>
      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
    </Card>
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

function PontuacaoPorTurma() {
  const { escolaId, usuario } = useApp();
  // Secretaria (rede vinculada, não-global) enxerga as métricas, mas não altera.
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const { dados, erro, carregando, recarregar } = useApi<PontuacaoResp>(
    escolaId ? `/escolas/${escolaId}/configuracoes/pontuacao-turma` : null,
  );
  const [turmaId, setTurmaId] = useState<number | null>(null);
  const [edit, setEdit] = useState<Record<string, number>>({});
  const [aplicarTodos, setAplicarTodos] = useState("");
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
    setMensagem(null);
  }, [turmaId, dados]); // eslint-disable-line react-hooks/exhaustive-deps

  if (carregando) return <Carregando />;
  if (erro) return <Mensagem tipo="erro">{erro.message}</Mensagem>;
  if (!dados) return <Carregando />;
  if (dados.turmas.length === 0)
    return (
      <Card className="p-6 text-sm text-zinc-500 dark:text-zinc-400">
        Cadastre turmas para configurar a pontuação por nível.
      </Card>
    );
  if (dados.catalogo.length === 0)
    return (
      <Card className="p-6 text-sm text-zinc-500 dark:text-zinc-400">
        Cadastre os níveis de dificuldade (na aba anterior) para poder pontuá-los.
      </Card>
    );

  const alterados = Object.keys(edit).filter((c) => edit[c] !== padrao[c]).length;

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
        { method: "PUT", body: JSON.stringify({ turma_id: turmaId, pontos }) },
      );
      setMensagem({ tipo: "ok", texto: r.mensagem });
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

      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}
      <div className="flex items-center gap-3">
        <Botao onClick={salvar} disabled={salvando || somenteLeitura}>
          {somenteLeitura ? "Somente leitura" : salvando ? "Salvando e recalculando..." : `Salvar pontuação da turma`}
        </Botao>
        <span className="text-sm text-zinc-500 dark:text-zinc-400">
          {alterados > 0 ? `${alterados} nível(is) diferente(s) do padrão.` : "Usando o padrão da escola."}
        </span>
      </div>
    </div>
  );
}


/* -------------------------------------------------------------------------
 * Página Métricas — exatamente os 4 módulos definidos no PRD §58.
 * ----------------------------------------------------------------------- */
const ABAS = ["Matific", "Elefante Letrado", "Dificuldade por Turma", "Referências de Normalização"] as const;
type Aba = (typeof ABAS)[number];

export default function Metricas() {
  const { usuario } = useApp();
  // Secretaria (rede vinculada, não-global): vê os critérios, mas não altera.
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const [aba, setAba] = useState<Aba>("Matific");
  const [subAbaElefante, setSubAbaElefante] = useState<"pesos" | "questoes">("pesos");

  return (
    <div>
      <PageHeader
        titulo="Métricas"
        descricao="Todos os critérios de avaliação são configuráveis. Alterações recalculam as notas automaticamente."
      />

      {somenteLeitura && (
        <div className="mb-5 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
          Você está vendo as métricas em <b>modo leitura</b>. Só o coordenador da escola e o
          administrador geral podem alterar os critérios de avaliação.
        </div>
      )}

      <div role="tablist" className="mb-5 flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {ABAS.map((nome) => (
          <button
            key={nome}
            role="tab"
            aria-selected={aba === nome}
            onClick={() => setAba(nome)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              aba === nome
                ? "border-indigo-600 text-zinc-900 dark:text-zinc-50"
                : "border-transparent text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            }`}
          >
            {nome}
          </button>
        ))}
      </div>

      {aba === "Matific" && (
        <div className="max-w-2xl">
          <h2 className="mb-3 text-sm font-semibold">Pesos da Nota</h2>
          <PesosEditor
            namespace="matific"
            rotulos={{ atividades: "Atividades finalizadas", media: "Pontuação média", estrelas: "Estrelas" }}
            descricao="Como os três indicadores da Matific compõem a nota do módulo."
          />
        </div>
      )}

      {aba === "Elefante Letrado" && (
        <div className="max-w-2xl">
          <div role="tablist" className="mb-4 inline-flex rounded-lg border border-zinc-300 p-0.5 dark:border-zinc-700">
            {(
              [
                ["pesos", "Pesos da Nota"],
                ["questoes", "Questões"],
              ] as const
            ).map(([chave, rotulo]) => (
              <button
                key={chave}
                role="tab"
                aria-selected={subAbaElefante === chave}
                onClick={() => setSubAbaElefante(chave)}
                className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                  subAbaElefante === chave
                    ? "bg-indigo-600 text-white"
                    : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
                }`}
              >
                {rotulo}
              </button>
            ))}
          </div>
          {subAbaElefante === "pesos" ? (
            <PesosEditor
              namespace="elefante"
              rotulos={{
                livros: "Livros únicos concluídos",
                dificuldade: "Dificuldade dos livros",
                questoes: "Questões",
                tempo: "Tempo de leitura",
              }}
              descricao="Como os quatro fatores de leitura compõem a nota do módulo."
            />
          ) : (
            <PesosEditor
              namespace="questoes"
              rotulos={{ tentativas: "Tentativas", acertos: "Acertos" }}
              descricao="Dentro do fator Questões, o equilíbrio entre tentar e acertar."
            />
          )}
        </div>
      )}

      {aba === "Dificuldade por Turma" && <PontuacaoPorTurma />}
      {aba === "Referências de Normalização" && <ReferenciasNormalizacao />}
    </div>
  );
}
