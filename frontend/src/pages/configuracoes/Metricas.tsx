import { useCallback, useEffect, useState } from "react";

import { Badge, Botao, Card, Carregando, Mensagem, PageHeader } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { api, ApiError } from "../../lib/api";
import { nota } from "../../lib/formato";
import type { Dificuldade, Pesos, Referencias } from "../../lib/types";

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
  const { escolaId } = useApp();
  const [valores, setValores] = useState<Record<string, number> | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    if (!escolaId) return;
    setValores(null);
    setMensagem(null);
    api<Pesos>(`/escolas/${escolaId}/configuracoes/pesos/${namespace}`)
      .then((dados) => setValores(dados.valores))
      .catch(() => setValores(null));
  }, [escolaId, namespace]);

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
        <Botao onClick={salvar} disabled={!valido || salvando}>
          {salvando ? "Salvando e recalculando..." : "Salvar pesos"}
        </Botao>
      </div>
      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
    </Card>
  );
}

/* -------------------------------------------------------------------------
 * Dificuldade por Turma (PRD §39, §61): uma tabela editável por série.
 * ----------------------------------------------------------------------- */
function DificuldadePorTurma() {
  const { escolaId } = useApp();
  const [dados, setDados] = useState<Dificuldade | null>(null);
  const [pontos, setPontos] = useState<Record<string, Record<number, number>>>({});
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  const carregar = useCallback(() => {
    if (!escolaId) return;
    setDados(null);
    setMensagem(null);
    api<Dificuldade>(`/escolas/${escolaId}/configuracoes/dificuldade`)
      .then((resposta) => {
        setDados(resposta);
        const inicial: Record<string, Record<number, number>> = {};
        for (const serie of resposta.series) inicial[serie.ano_escolar] = { ...serie.pontos };
        setPontos(inicial);
      })
      .catch(() => setDados(null));
  }, [escolaId]);

  useEffect(carregar, [carregar]);

  if (!dados) return <Carregando />;
  if (dados.series.length === 0) {
    return (
      <Card className="p-6 text-sm text-zinc-500 dark:text-zinc-400">
        Cadastre turmas para configurar a pontuação por série.
      </Card>
    );
  }

  async function salvar() {
    if (!escolaId) return;
    const alteracoes = Object.entries(pontos).flatMap(([serie, porNivel]) =>
      Object.entries(porNivel).map(([nivelId, valor]) => ({
        ano_escolar: serie,
        nivel_id: Number(nivelId),
        pontos: valor,
      })),
    );
    setSalvando(true);
    setMensagem(null);
    try {
      const resposta = await api<{ mensagem: string }>(
        `/escolas/${escolaId}/configuracoes/dificuldade`,
        { method: "PUT", body: JSON.stringify(alteracoes) },
      );
      setMensagem({ tipo: "ok", texto: resposta.mensagem });
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
    <div className="space-y-4">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Defina quantos pontos cada nível de livro vale em cada série. Isso equilibra a
        competição: um livro simples pode valer mais para o 1º Ano do que para o 5º Ano.
      </p>
      {dados.series.map((serie) => (
        <Card key={serie.ano_escolar}>
          <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <h3 className="text-sm font-semibold">{serie.ano_escolar}</h3>
          </div>
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {dados.niveis.map((nivel) => (
              <div key={nivel.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{nivel.nome}</span>
                  <span className="text-xs text-zinc-400 dark:text-zinc-500">{nivel.codigos.join(" · ")}</span>
                </div>
                <label className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    aria-label={`Pontos de ${nivel.nome} no ${serie.ano_escolar}`}
                    className="w-20 rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-right text-sm tabular-nums dark:border-zinc-700 dark:bg-zinc-950"
                    value={pontos[serie.ano_escolar]?.[nivel.id] ?? nivel.pontos_padrao}
                    onChange={(evento) =>
                      setPontos({
                        ...pontos,
                        [serie.ano_escolar]: {
                          ...pontos[serie.ano_escolar],
                          [nivel.id]: Number(evento.target.value),
                        },
                      })
                    }
                  />
                  pontos
                </label>
              </div>
            ))}
          </div>
        </Card>
      ))}
      <div className="flex items-center justify-end gap-3">
        <Botao onClick={salvar} disabled={salvando}>
          {salvando ? "Salvando e recalculando..." : "Salvar todas as tabelas"}
        </Botao>
      </div>
      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}
    </div>
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
  const { escolaId } = useApp();
  const [dados, setDados] = useState<Referencias | null>(null);
  const [modo, setModo] = useState<"auto" | "manual">("auto");
  const [manuais, setManuais] = useState<Record<string, number>>({});
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    if (!escolaId) return;
    setDados(null);
    setMensagem(null);
    api<Referencias>(`/escolas/${escolaId}/configuracoes/referencias`)
      .then((resposta) => {
        setDados(resposta);
        setModo(resposta.modo);
        const iniciais: Record<string, number> = {};
        for (const chave of Object.keys(ROTULOS_REFERENCIAS)) {
          iniciais[chave] = resposta.valores_manuais[chave] ?? resposta.valores_em_uso[chave] ?? 0;
        }
        setManuais(iniciais);
      })
      .catch(() => setDados(null));
  }, [escolaId]);

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
        <Botao onClick={salvar} disabled={salvando}>
          {salvando ? "Salvando e recalculando..." : "Salvar referências"}
        </Botao>
      </div>
      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
    </Card>
  );
}

/* -------------------------------------------------------------------------
 * Página Métricas — exatamente os 4 módulos definidos no PRD §58.
 * ----------------------------------------------------------------------- */
const ABAS = ["Matific", "Elefante Letrado", "Dificuldade por Turma", "Referências de Normalização"] as const;
type Aba = (typeof ABAS)[number];

export default function Metricas() {
  const [aba, setAba] = useState<Aba>("Matific");
  const [subAbaElefante, setSubAbaElefante] = useState<"pesos" | "questoes">("pesos");

  return (
    <div>
      <PageHeader
        titulo="Métricas"
        descricao="Todos os critérios de avaliação são configuráveis. Alterações recalculam as notas automaticamente."
      />

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

      {aba === "Dificuldade por Turma" && <DificuldadePorTurma />}
      {aba === "Referências de Normalização" && <ReferenciasNormalizacao />}
    </div>
  );
}
