import { useEffect, useState } from "react";

import { Badge, Botao, Card, Carregando, Mensagem, PageHeader } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { api, ApiError } from "../../lib/api";
import { nota } from "../../lib/formato";
import type { Pesos, Referencias } from "../../lib/types";
import { EditorNiveis, PontuacaoPorTurma } from "./dificuldade";

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
 * Página Métricas. A configuração de dificuldade (níveis + pontuação por turma)
 * vive em ./dificuldade e é reutilizada aqui e no módulo Elefante Letrado.
 * ----------------------------------------------------------------------- */
const ABAS = [
  "Matific",
  "Elefante Letrado",
  "Referências de Normalização",
] as const;
type Aba = (typeof ABAS)[number];

/* -------------------------------------------------------------------------
 * Pontos Extras (Elefante): bônus por livro lido DENTRO do horário da escola,
 * definido pelo TURNO da turma. A regra de horário fica no backend (scoring);
 * aqui só o liga/desliga e o valor por livro.
 * ----------------------------------------------------------------------- */
type ElefanteExtra = { ativo: boolean; pontos_por_livro: number };

function PontosExtrasEditor() {
  const { escolaId, usuario } = useApp();
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const { dados, erro, carregando } = useApi<ElefanteExtra>(
    escolaId ? `/escolas/${escolaId}/configuracoes/elefante-extra` : null,
  );
  const [ativo, setAtivo] = useState(false);
  const [pontos, setPontos] = useState("1");
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    if (!dados) return;
    setAtivo(dados.ativo);
    setPontos(String(dados.pontos_por_livro || 1));
    setMensagem(null);
  }, [dados]);

  if (carregando) return <Carregando />;
  if (erro) return <Mensagem tipo="erro">{erro.message}</Mensagem>;

  async function salvar() {
    if (!escolaId) return;
    const v = Number(pontos);
    if (Number.isNaN(v) || v < 0) {
      setMensagem({ tipo: "erro", texto: "Informe um valor de pontos (0 ou mais)." });
      return;
    }
    setSalvando(true);
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}/configuracoes/elefante-extra`, {
        method: "PUT",
        body: JSON.stringify({ ativo, pontos_por_livro: v }),
      });
      setMensagem({ tipo: "ok", texto: "Pontos extras salvos. Todas as notas foram recalculadas." });
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível salvar." });
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Card className="p-5">
      <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
        Dá pontos extras por cada livro que o aluno lê <strong>dentro do horário da escola</strong>,
        conforme o <strong>turno da turma</strong>: Manhã (7h–13h) ou Tarde (13h–18h), de segunda a
        sexta. Livros lidos fora desse horário — ou em turmas de turno Integral/Noite — contam só a
        pontuação normal. Usa a data e a hora reais de cada leitura (relatório individual do Elefante).
      </p>

      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          className="h-4 w-4 accent-indigo-600"
          checked={ativo}
          disabled={somenteLeitura}
          onChange={(e) => setAtivo(e.target.checked)}
        />
        Ativar pontos extras por livros lidos na escola
      </label>

      <div className={`mt-4 flex items-center gap-3 ${ativo ? "" : "opacity-50"}`}>
        <label className="text-sm" htmlFor="pontos-extras-livro">Pontos extras por livro:</label>
        <input
          id="pontos-extras-livro"
          type="number"
          min={0}
          step="0.5"
          value={pontos}
          disabled={!ativo || somenteLeitura}
          onChange={(e) => setPontos(e.target.value)}
          className="w-24 rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-right text-sm tabular-nums dark:border-zinc-700 dark:bg-zinc-950"
        />
      </div>

      <p className="mt-3 text-xs text-zinc-400 dark:text-zinc-500">
        Ligar/desligar <strong>não apaga nenhuma leitura</strong> — só controla se o bônus entra na
        nota. Os pontos extras somam ao fator “Dificuldade” do Elefante (a nota continua de 0 a 100).
      </p>

      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
      <div className="mt-4 flex justify-end border-t border-zinc-200 pt-4 dark:border-zinc-800">
        <Botao onClick={salvar} disabled={salvando || somenteLeitura}>
          {somenteLeitura ? "Somente leitura" : salvando ? "Salvando e recalculando..." : "Salvar"}
        </Botao>
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------
 * Régua de pontuação da escola: PADRÃO CONSTELA (régua institucional fixa) ×
 * PERSONALIZADO (a config desta tela). A escolha governa SÓ o scoring/ranking
 * INTERNO da escola — o ranking da REDE usa sempre a régua institucional. É o
 * primeiro controle da página porque decide se o resto tem efeito no ranking
 * interno. Backend: GET/PUT /configuracoes/perfil-scoring (dispara recálculo).
 * ----------------------------------------------------------------------- */
type PerfilScoring = { modo: "institucional" | "personalizado" };

function PerfilScoringEditor() {
  const { escolaId, usuario } = useApp();
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const { dados, erro, carregando, recarregar } = useApi<PerfilScoring>(
    escolaId ? `/escolas/${escolaId}/configuracoes/perfil-scoring` : null,
  );
  const [modo, setModo] = useState<"institucional" | "personalizado">("institucional");
  const [salvando, setSalvando] = useState(false);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  useEffect(() => {
    if (dados) {
      setModo(dados.modo);
      setMensagem(null);
    }
  }, [dados]);

  if (carregando) return <Carregando />;
  if (erro) return <Mensagem tipo="erro">{erro.message}</Mensagem>;

  async function escolher(novo: "institucional" | "personalizado") {
    if (!escolaId || novo === modo || somenteLeitura) return;
    const anterior = modo;
    setModo(novo);
    setSalvando(true);
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}/configuracoes/perfil-scoring`, {
        method: "PUT",
        body: JSON.stringify({ modo: novo }),
      });
      setMensagem({
        tipo: "ok",
        texto:
          novo === "personalizado"
            ? "Régua personalizada ativada. O ranking INTERNO da escola foi recalculado com a configuração desta escola. O ranking da rede continua usando a régua institucional."
            : "Régua Padrão Constela ativada. O ranking interno voltou a usar a régua institucional.",
      });
    } catch (e) {
      setModo(anterior);
      setMensagem({ tipo: "erro", texto: e instanceof ApiError ? e.message : "Não foi possível salvar." });
      recarregar();
    } finally {
      setSalvando(false);
    }
  }

  const opcoes = [
    {
      valor: "institucional" as const,
      titulo: "Régua Padrão Constela",
      descricao:
        "A configuração padrão usa a régua institucional da Constela (dificuldade A3 + pesos padrão). É o estado inicial de toda escola.",
    },
    {
      valor: "personalizado" as const,
      titulo: "Personalizado",
      descricao:
        "A configuração personalizada altera apenas o scoring e o ranking INTERNO desta escola. O ranking da rede utiliza sempre a régua institucional da Constela.",
    },
  ];

  return (
    <Card className="p-5">
      <h2 className="mb-1 text-sm font-semibold">Régua de pontuação da escola</h2>
      <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
        Define a régua usada no ranking <strong>interno</strong> desta escola. O ranking da{" "}
        <strong>rede</strong> é sempre padronizado (régua institucional) e não muda com esta escolha.
      </p>

      <div className="space-y-2" role="radiogroup" aria-label="Régua de pontuação da escola">
        {opcoes.map((op) => {
          const ativo = modo === op.valor;
          return (
            <label
              key={op.valor}
              className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors ${
                ativo
                  ? "border-indigo-500 bg-indigo-50 dark:border-indigo-500/60 dark:bg-indigo-500/10"
                  : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-800 dark:hover:border-zinc-700"
              } ${somenteLeitura || salvando ? "cursor-not-allowed opacity-70" : ""}`}
            >
              <input
                type="radio"
                name="perfil-scoring"
                className="mt-1 h-4 w-4 accent-indigo-600"
                checked={ativo}
                disabled={somenteLeitura || salvando}
                onChange={() => escolher(op.valor)}
              />
              <span>
                <span className="block text-sm font-medium text-zinc-900 dark:text-zinc-50">
                  {op.titulo}
                  {op.valor === "institucional" && (
                    <>
                      {" "}
                      <Badge tom="destaque">Padrão</Badge>
                    </>
                  )}
                </span>
                <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                  {op.descricao}
                </span>
              </span>
            </label>
          );
        })}
      </div>

      {modo === "institucional" && !somenteLeitura && (
        <p className="mt-3 text-xs text-zinc-400 dark:text-zinc-500">
          No modo Padrão, as configurações de pesos, dificuldade e normalização abaixo{" "}
          <strong>não afetam o ranking interno</strong> — ative “Personalizado” para usá-las.
        </p>
      )}

      {mensagem && (
        <div className="mt-3">
          <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
        </div>
      )}
      {salvando && (
        <p className="mt-2 text-xs text-zinc-400 dark:text-zinc-500">Salvando e recalculando…</p>
      )}
    </Card>
  );
}

export default function Metricas() {
  const { usuario } = useApp();
  // Secretaria (rede vinculada, não-global): vê os critérios, mas não altera.
  const somenteLeitura = !usuario?.is_global && usuario?.rede_id != null;
  const [aba, setAba] = useState<Aba>("Matific");
  const [subAbaElefante, setSubAbaElefante] =
    useState<"pesos" | "questoes" | "extras" | "niveis" | "dificuldade">("pesos");

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

      <div className="mb-6 max-w-2xl">
        <PerfilScoringEditor />
      </div>

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
        <div>
          {/* Todas as configurações do Elefante ficam agrupadas aqui: pesos,
              questões, pontos extras, os níveis de dificuldade e a pontuação
              de dificuldade por turma. */}
          <div role="tablist" className="mb-4 inline-flex flex-wrap gap-0.5 rounded-lg border border-zinc-300 p-0.5 dark:border-zinc-700">
            {(
              [
                ["pesos", "Pesos da Nota"],
                ["questoes", "Questões"],
                ["extras", "Pontos Extras"],
                ["niveis", "Níveis de dificuldade"],
                ["dificuldade", "Dificuldade por turma"],
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
            <div className="max-w-2xl">
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
            </div>
          ) : subAbaElefante === "questoes" ? (
            <div className="max-w-2xl">
              <PesosEditor
                namespace="questoes"
                rotulos={{ tentativas: "Tentativas", acertos: "Acertos" }}
                descricao="Dentro do fator Questões, o equilíbrio entre tentar e acertar."
              />
            </div>
          ) : subAbaElefante === "extras" ? (
            <div className="max-w-2xl">
              <PontosExtrasEditor />
            </div>
          ) : subAbaElefante === "niveis" ? (
            <div className="max-w-3xl">
              <EditorNiveis />
            </div>
          ) : (
            <PontuacaoPorTurma />
          )}
        </div>
      )}

      {aba === "Referências de Normalização" && <ReferenciasNormalizacao />}
    </div>
  );
}
