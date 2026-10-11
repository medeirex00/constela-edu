/**
 * "Quer ver um exemplo?" — a conta REAL de um caso, por plataforma.
 *
 * Uma área só, com uma aba por plataforma contratada (o que a rede não
 * contratou não aparece — `useModulos`):
 *
 *   ELEFANTE LETRADO → escolhe um livro do ACERVO da escola (busca por título)
 *                      ou só o nível, e o ano escolar do aluno; mostra quanto
 *                      UMA leitura vale, separando o que vem DO LIVRO (título,
 *                      nível, palavras, de onde vieram) do que o Constela
 *                      CALCULA (tamanho típico do nível, base, fatores).
 *   MATIFIC          → atividades e estrelas de um aluno no período; mostra o
 *                      índice da premiação "Melhor Matemática" com a régua da
 *                      escola no MESMO período da tela de Premiações.
 *
 * A TELA NÃO FAZ CONTA. Cada número vem de
 * GET /escolas/{id}/configuracoes/pontuacao/exemplo/{elefante|matific}, que
 * chama as mesmas funções que pontuam de verdade. Os fatores aparecem com as
 * casas que a API devolve (até 6), para a conta "base × tamanho × série" fechar
 * exatamente com o valor mostrado; no Matific a divisão é mostrada com "≈".
 * Sem resposta da API, nenhum número aparece.
 *
 * Acessibilidade: o padrão de abas da casa (`RelatoriosArea.tsx`) —
 * `role="tablist"`, `aria-controls` e o painel rotulado pela aba ativa.
 */
import { Search } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { api, ApiError } from "../lib/api";
import type { Livro, PaginaLivros } from "../lib/types";
import { SeletorPeriodo, periodoParaQuery } from "./SeletorPeriodo";
import { Badge, Botao, Mensagem, estiloInput } from "./ui";

/* -------------------------------------------------------------------------
 * Contratos das rotas de exemplo (backend/app/routers/configuracoes.py).
 * ----------------------------------------------------------------------- */

export interface ExemploElefanteResposta {
  plataforma: "elefante";
  regra: string;
  regra_da_rede: string;
  catalogo?: { versao: string | null; n_livros: number };
  entrada: {
    origem: "acervo" | "catalogo" | "nivel";
    livro_id: number | null;
    elefante_id: number | null;
    titulo: string | null;
    nivel: string;
    serie: number;
  };
  serie: number;
  /** `null` só na régua própria da escola, quando o valor muda conforme a turma
   *  (aí vale `por_turma`). */
  valor: number | null;
  valor_exibido: number | null;
  personalizada: boolean;
  /** Só na régua própria: "serie" (vale para todo aluno do ano), "turmas"
   *  (depende da turma) ou "padrao" (a escola não tem turma daquele ano). */
  base_do_valor?: "serie" | "turmas" | "padrao";
  valor_padrao_escola?: number;
  valor_minimo?: number | null;
  valor_maximo?: number | null;
  por_turma?: { turma_id: number; turma: string; valor: number; valor_exibido: number }[];
  livro: {
    titulo: string | null;
    nivel: string;
    palavras?: number | null;
    palavras_status?: string;
    resolvido_por?: string | null;
    encontrado_no_catalogo?: boolean | null;
    elefante_id?: number | null;
    titulo_no_catalogo?: string | null;
    nivel_no_catalogo?: string | null;
  };
  calculo: {
    posicao_nivel: number | null;
    /** A posição em palavras ("6º nível da escada, que começa no AA"; "entre A e B na escada"). */
    posicao_descricao?: string | null;
    base_nivel: number;
    mediana_palavras_nivel: number | null;
    fator_tamanho: number;
    limite_tamanho: "piso" | "teto" | null;
    piso_tamanho: number;
    teto_tamanho: number;
    fator_serie: number;
    valor: number;
  } | null;
  avisos: string[];
}

export interface ExemploMatificResposta {
  plataforma: "matific";
  premiacao: string;
  entrada: { atividades: number; estrelas: number };
  estrelas_consideradas: number;
  teto_estrelas_por_atividade: number;
  regua: {
    modo: string;
    ano_letivo: number | null;
    inicio_efetivo: string | null;
    fim_efetivo: string | null;
    alunos_com_atividade: number;
    minimo_alunos: number;
    fracao_zeros_extras: number;
    k_mediana_atividades: number | null;
    zeros_extras: number | null;
  };
  referencia_disponivel: boolean;
  motivo: string | null;
  mensagem: string | null;
  calculo: {
    zeros_extras: number;
    denominador: number;
    indice_sem_teto: number;
    indice: number | null;
    indice_exibido: number | null;
    teto_indice: number;
    teto_aplicado: boolean;
  } | null;
  avisos: string[];
  periodo: { chave: string; rotulo: string; inicio: string | null; fim: string | null };
}

/* -------------------------------------------------------------------------
 * Formatação (só exibição — nenhum número nasce aqui).
 * ----------------------------------------------------------------------- */

function decimal(valor: number, minimo = 2, maximo = minimo): string {
  return valor.toLocaleString("pt-BR", { minimumFractionDigits: minimo, maximumFractionDigits: maximo });
}

/** Fator com TODAS as casas que a API devolveu (até 6), no mínimo 2. */
function fatorExato(valor: number): string {
  return decimal(valor, 2, 6);
}

/** Número de contagem: inteiro sem casas; com fração, até 2 casas. */
function contagem(valor: number): string {
  return decimal(valor, 0, 2);
}

/** "2026-08-01T00:00:00" → "01/08/2026". */
function dataCurta(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [data] = iso.split("T");
  const partes = data.split("-");
  return partes.length === 3 ? `${partes[2]}/${partes[1]}/${partes[0]}` : null;
}

const MENSAGEM_SEM_CONEXAO =
  "Não foi possível calcular o exemplo agora. Verifique a conexão e tente de novo.";

function mensagemDeErro(excecao: unknown): string {
  if (excecao instanceof ApiError && excecao.status !== 0 && excecao.status < 500 && excecao.message) {
    return excecao.message;
  }
  return MENSAGEM_SEM_CONEXAO;
}

const ROTULO_CAMPO = "mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-300";

function Avisos({ avisos }: { avisos: string[] }) {
  if (avisos.length === 0) return null;
  return (
    <ul className="mt-3 space-y-1 text-xs text-amber-700 dark:text-amber-300">
      {avisos.map((aviso) => (
        <li key={aviso}>{aviso}</li>
      ))}
    </ul>
  );
}

function Linha({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-3 gap-y-0.5 py-1">
      <dt className="text-zinc-500 dark:text-zinc-400">{rotulo}</dt>
      <dd className="text-right font-medium tabular-nums text-zinc-800 dark:text-zinc-100">{children}</dd>
    </div>
  );
}

function Quadro({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{titulo}</p>
      <dl className="mt-1 divide-y divide-zinc-100 text-sm dark:divide-zinc-800">{children}</dl>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Elefante Letrado
 * ----------------------------------------------------------------------- */

/** Vocabulário OFICIAL de níveis do Elefante — o mesmo que o servidor valida
 *  (mesma lista e ordem da tela de Livros). */
const NIVEIS_OFICIAIS = [
  "AA", "BB", "CC", "DD", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
  "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "Z+", "A+",
];
const SERIES = [1, 2, 3, 4, 5];

function fontePalavras(ex: ExemploElefanteResposta): string {
  const livro = ex.livro;
  if (ex.entrada.origem === "nivel" && !ex.entrada.titulo) return "nenhum livro escolhido";
  switch (livro.resolvido_por) {
    case "elefante_id":
      return "catálogo oficial do Elefante, pelo código do livro";
    case "titulo_nivel":
      return "catálogo oficial do Elefante, pelo título e nível";
    case "titulo_unico":
      return "catálogo oficial do Elefante, só pelo título (o nível não bateu)";
    default:
      return "livro não encontrado no catálogo oficial";
  }
}

/** Régua própria da escola (perfil personalizado): só nível e valor existem —
 *  sem fatores. O valor pode mudar por série e por turma, então a frase diz a
 *  quem ele vale: ao ano todo, a cada turma (lista) ou só o padrão da escola. */
function ResultadoReguaPropria({ ex }: { ex: ExemploElefanteResposta }) {
  const sujeito = ex.livro.titulo ? <>“{ex.livro.titulo}”</> : <>Um livro do nível {ex.livro.nivel}</>;
  const porTurma = ex.por_turma ?? [];
  let frase: ReactNode = null;
  if (ex.base_do_valor === "turmas" && typeof ex.valor_minimo === "number" && typeof ex.valor_maximo === "number") {
    frase = (
      <>
        {sujeito} vale de <strong className="tabular-nums">{decimal(ex.valor_minimo, 2, 4)}</strong> a{" "}
        <strong className="tabular-nums">{decimal(ex.valor_maximo, 2, 4)} pontos</strong> para um aluno do{" "}
        {ex.serie}º ano, conforme a turma.
      </>
    );
  } else if (typeof ex.valor_exibido === "number") {
    frase = ex.base_do_valor === "padrao" ? (
      <>
        {sujeito} vale <strong className="tabular-nums">{decimal(ex.valor_exibido)} pontos</strong> pelo valor
        padrão da escola.
      </>
    ) : (
      <>
        {sujeito} vale <strong className="tabular-nums">{decimal(ex.valor_exibido)} pontos</strong> para um aluno
        do {ex.serie}º ano.
      </>
    );
  }
  return (
    <>
      {frase ? <p className="text-base">{frase}</p> : null}
      {porTurma.length > 0 ? (
        <div className="mt-3">
          <Quadro titulo={`Turmas do ${ex.serie}º ano`}>
            {porTurma.map((t) => (
              <Linha key={t.turma_id} rotulo={t.turma}>
                {decimal(t.valor_exibido)} pontos
              </Linha>
            ))}
          </Quadro>
        </div>
      ) : null}
      {typeof ex.valor_padrao_escola === "number" ? (
        <p className="mt-2 text-zinc-600 dark:text-zinc-300">
          Valor padrão da escola para o nível <strong>{ex.livro.nivel}</strong>:{" "}
          <span className="tabular-nums">{decimal(ex.valor_padrao_escola, 2, 4)}</span> pontos.
        </p>
      ) : null}
    </>
  );
}

function ResultadoElefante({ ex }: { ex: ExemploElefanteResposta }) {
  const titulo = ex.livro.titulo;
  const sujeito = titulo ? <>“{titulo}”</> : <>Um livro típico do nível {ex.livro.nivel}</>;
  const calc = ex.calculo;
  return (
    <div className="mt-4 rounded-lg bg-zinc-50 p-4 text-sm dark:bg-zinc-900" aria-live="polite">
      {ex.personalizada || !calc ? (
        <ResultadoReguaPropria ex={ex} />
      ) : (
        <>
          {typeof ex.valor_exibido === "number" ? (
            <p className="text-base">
              {sujeito} vale <strong className="tabular-nums">{decimal(ex.valor_exibido)} pontos</strong> para um
              aluno do {ex.serie}º ano.
            </p>
          ) : null}
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Quadro titulo="Do livro">
              <Linha rotulo="Título">{titulo ?? "—"}</Linha>
              <Linha rotulo="Nível">{ex.livro.nivel}</Linha>
              <Linha rotulo="Palavras">
                {typeof ex.livro.palavras === "number"
                  ? ex.livro.palavras.toLocaleString("pt-BR")
                  : "sem contagem"}
              </Linha>
              <Linha rotulo="De onde vieram">{fontePalavras(ex)}</Linha>
            </Quadro>
            <Quadro titulo="Calculado pelo Constela">
              <Linha rotulo={`Tamanho típico do nível ${ex.livro.nivel}`}>
                {typeof calc.mediana_palavras_nivel === "number"
                  ? `${calc.mediana_palavras_nivel.toLocaleString("pt-BR")} palavras`
                  : "—"}
              </Linha>
              <Linha rotulo={`Base do nível ${ex.livro.nivel}`}>
                {fatorExato(calc.base_nivel)}
                {calc.posicao_descricao ? (
                  <span className="ml-1 font-normal text-zinc-500 dark:text-zinc-400">
                    ({calc.posicao_descricao})
                  </span>
                ) : null}
              </Linha>
              <Linha rotulo="Fator de tamanho">
                ×{fatorExato(calc.fator_tamanho)}
                {calc.limite_tamanho === "teto" ? (
                  <span className="ml-1 font-normal text-zinc-500 dark:text-zinc-400">(no máximo)</span>
                ) : calc.limite_tamanho === "piso" ? (
                  <span className="ml-1 font-normal text-zinc-500 dark:text-zinc-400">(no mínimo)</span>
                ) : null}
              </Linha>
              <Linha rotulo={`Fator do ${ex.serie}º ano`}>×{fatorExato(calc.fator_serie)}</Linha>
            </Quadro>
          </div>

          <p className="mt-3">
            <span className="text-zinc-500 dark:text-zinc-400">Conta: </span>
            <span className="tabular-nums" data-testid="conta-elefante">
              {fatorExato(calc.base_nivel)} (nível) × {fatorExato(calc.fator_tamanho)} (tamanho) ×{" "}
              {fatorExato(calc.fator_serie)} (série) = <strong>{decimal(calc.valor, 4)} pontos</strong>
            </span>
          </p>
          {typeof ex.valor_exibido === "number" ? (
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              Nas premiações e nos rankings o valor aparece com 2 casas ({decimal(ex.valor_exibido)}); a ordem usa o
              valor completo.
            </p>
          ) : null}
        </>
      )}

      <Avisos avisos={ex.avisos} />
      <p className="mt-3 text-xs text-zinc-400 dark:text-zinc-500">
        Regra: {ex.regra}
        {ex.catalogo?.versao ? (
          <> · catálogo {ex.catalogo.versao} ({ex.catalogo.n_livros.toLocaleString("pt-BR")} livros)</>
        ) : null}
      </p>
    </div>
  );
}

function ExemploElefante({ escolaId }: { escolaId: number }) {
  const [soNivel, setSoNivel] = useState(false);
  const [busca, setBusca] = useState("");
  const [buscaAtrasada, setBuscaAtrasada] = useState("");
  const [livro, setLivro] = useState<Livro | null>(null);
  const [nivel, setNivel] = useState("");
  const [serie, setSerie] = useState("");
  const [resultado, setResultado] = useState<ExemploElefanteResposta | null>(null);
  const [erro, setErro] = useState("");
  const [calculando, setCalculando] = useState(false);
  const idBusca = useId();

  // Espera o usuário parar de digitar (250 ms) antes de consultar a API.
  useEffect(() => {
    const t = window.setTimeout(() => setBuscaAtrasada(busca.trim()), 250);
    return () => window.clearTimeout(t);
  }, [busca]);

  const buscaAtiva = !soNivel && !livro && buscaAtrasada.length >= 2;
  const { dados: pagina, erro: erroBusca, carregando: carregandoBusca } = useApi<PaginaLivros>(
    buscaAtiva
      ? `/escolas/${escolaId}/livros?busca=${encodeURIComponent(buscaAtrasada)}&por_pagina=8`
      : null,
  );
  const encontrados = buscaAtiva ? (pagina?.itens ?? []) : [];

  function limparResultado() {
    setResultado(null);
    setErro("");
  }

  async function calcular() {
    if (!soNivel && !livro) {
      setErro("Escolha um livro do acervo (ou marque a opção de informar só o nível).");
      setResultado(null);
      return;
    }
    if (soNivel && !nivel) {
      setErro("Escolha o nível do livro.");
      setResultado(null);
      return;
    }
    if (!serie) {
      setErro("Escolha o ano escolar do aluno.");
      setResultado(null);
      return;
    }
    const query = new URLSearchParams();
    if (soNivel) query.set("nivel", nivel);
    else if (livro) query.set("livro_id", String(livro.id));
    query.set("serie", serie);
    setCalculando(true);
    limparResultado();
    try {
      setResultado(
        await api<ExemploElefanteResposta>(
          `/escolas/${escolaId}/configuracoes/pontuacao/exemplo/elefante?${query.toString()}`,
        ),
      );
    } catch (excecao) {
      setErro(mensagemDeErro(excecao));
    } finally {
      setCalculando(false);
    }
  }

  return (
    <div>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Escolha um livro do acervo da escola e o ano escolar do aluno. O Constela mostra quanto uma leitura desse
        livro vale nas premiações e no ranking de leitura.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_12rem]">
        <div>
          {soNivel ? (
            <label className="block text-sm">
              <span className={ROTULO_CAMPO}>Nível</span>
              <select
                className={estiloInput}
                value={nivel}
                onChange={(e) => {
                  setNivel(e.target.value);
                  limparResultado();
                }}
              >
                <option value="">Escolha o nível</option>
                {NIVEIS_OFICIAIS.map((codigo) => (
                  <option key={codigo} value={codigo}>{codigo}</option>
                ))}
              </select>
            </label>
          ) : livro ? (
            <div className="text-sm">
              <span className={ROTULO_CAMPO}>Livro escolhido</span>
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-700">
                <span className="font-medium">{livro.titulo}</span>
                <Badge tom="destaque">nível {livro.nivel_codigo}</Badge>
                <button
                  type="button"
                  className="ml-auto text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                  onClick={() => {
                    setLivro(null);
                    limparResultado();
                  }}
                >
                  Trocar livro
                </button>
              </div>
            </div>
          ) : (
            <div className="text-sm">
              <label htmlFor={idBusca} className={ROTULO_CAMPO}>Livro do acervo</label>
              <div className="relative">
                <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
                <input
                  id={idBusca}
                  className={`${estiloInput} pl-8`}
                  placeholder="Digite parte do título..."
                  value={busca}
                  onChange={(e) => setBusca(e.target.value)}
                  autoComplete="off"
                />
              </div>
              {encontrados.length > 0 && (
                <ul
                  aria-label="Livros encontrados"
                  className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-700"
                >
                  {encontrados.map((l) => (
                    <li key={l.id}>
                      <button
                        type="button"
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
                        onClick={() => {
                          setLivro(l);
                          limparResultado();
                        }}
                      >
                        <span className="font-medium">{l.titulo}</span>
                        <span className="shrink-0 text-xs text-zinc-400">nível {l.nivel_codigo}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {erroBusca && (
                <div className="mt-2">
                  <Mensagem tipo="erro">Não foi possível buscar livros: {erroBusca.message}</Mensagem>
                </div>
              )}
              {buscaAtiva && !carregandoBusca && !erroBusca && encontrados.length === 0 && (
                <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                  Nenhum livro do acervo encontrado com esse título. Confira os acentos ou informe só o nível.
                </p>
              )}
            </div>
          )}
          <label className="mt-2 flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300">
            <input
              type="checkbox"
              checked={soNivel}
              onChange={(e) => {
                setSoNivel(e.target.checked);
                limparResultado();
              }}
            />
            Informar só o nível (ver o livro típico do nível)
          </label>
        </div>

        <label className="block text-sm">
          <span className={ROTULO_CAMPO}>Ano escolar do aluno</span>
          <select
            className={estiloInput}
            value={serie}
            onChange={(e) => {
              setSerie(e.target.value);
              limparResultado();
            }}
          >
            <option value="">Escolha o ano</option>
            {SERIES.map((n) => (
              <option key={n} value={String(n)}>{n}º ano</option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-3">
        <Botao variante="neutro" onClick={calcular} disabled={calculando}>
          {calculando ? "Calculando..." : "Ver exemplo"}
        </Botao>
      </div>
      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      {resultado && <ResultadoElefante ex={resultado} />}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Matific — premiação "Melhor Matemática"
 * ----------------------------------------------------------------------- */

function ResultadoMatific({ ex }: { ex: ExemploMatificResposta }) {
  const { regua, calculo } = ex;
  const inicio = dataCurta(regua.inicio_efetivo);
  const fim = dataCurta(regua.fim_efetivo);
  const pctZeros = Math.round(regua.fracao_zeros_extras * 100);
  const teto = contagem(ex.teto_estrelas_por_atividade);
  const consideradas = contagem(ex.estrelas_consideradas);
  const atividades = contagem(ex.entrada.atividades);
  return (
    <div className="mt-4 rounded-lg bg-zinc-50 p-4 text-sm dark:bg-zinc-900" aria-live="polite">
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Período: {ex.periodo.rotulo}
        {inicio && fim ? <> (medido de {inicio} a {fim})</> : null}
      </p>

      {ex.referencia_disponivel && calculo && typeof calculo.indice_exibido === "number"
        && typeof regua.k_mediana_atividades === "number" ? (
        <>
          <p className="mt-2 text-base">
            Com estes dados, o Constela chegou a{" "}
            <strong className="tabular-nums">{decimal(calculo.indice_exibido)}</strong> porque as {consideradas}{" "}
            estrelas que contam foram divididas pelas {atividades} atividades mais{" "}
            {contagem(calculo.zeros_extras)} atividades extras sem estrela ({pctZeros}% da mediana de atividades da
            escola, {contagem(regua.k_mediana_atividades)}).
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Quadro titulo="Dados informados">
              <Linha rotulo="Atividades no período">{atividades}</Linha>
              <Linha rotulo="Estrelas no período">{contagem(ex.entrada.estrelas)}</Linha>
              <Linha rotulo={`Estrelas que contam (até ${teto} por atividade)`}>{consideradas}</Linha>
            </Quadro>
            <Quadro titulo="Referência da escola no período">
              <Linha rotulo="Alunos com atividade (1º ao 5º ano)">{contagem(regua.alunos_com_atividade)}</Linha>
              <Linha rotulo="Mediana de atividades (k)">{contagem(regua.k_mediana_atividades)}</Linha>
              <Linha rotulo={`Atividades extras sem estrela (${pctZeros}% de k)`}>{contagem(calculo.zeros_extras)}</Linha>
            </Quadro>
          </div>
          <p className="mt-3">
            <span className="text-zinc-500 dark:text-zinc-400">Conta: </span>
            <span className="tabular-nums" data-testid="conta-matific">
              {consideradas} ÷ ({atividades} + {contagem(calculo.zeros_extras)}) = {consideradas} ÷{" "}
              {contagem(calculo.denominador)} ≈ <strong>{decimal(calculo.indice_exibido)}</strong>
            </span>
          </p>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            O resultado vai de 0 a {contagem(calculo.teto_indice)}
            {calculo.teto_aplicado ? <> e, aqui, parou no máximo</> : null}. No pódio aparece com 2 casas; a ordem
            usa o valor completo.
          </p>
        </>
      ) : (
        <>
          <p className="mt-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200">
            {ex.mensagem ?? "Não há referência da escola para comparar neste período."}
          </p>
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            Estrelas que contam: <span className="tabular-nums">{consideradas}</span> (até {teto} por atividade).
          </p>
        </>
      )}

      <Avisos avisos={ex.avisos} />
    </div>
  );
}

function ExemploMatific({ escolaId }: { escolaId: number }) {
  const { periodo, definirPeriodo } = useApp();
  const [atividades, setAtividades] = useState("");
  const [estrelas, setEstrelas] = useState("");
  const [resultado, setResultado] = useState<ExemploMatificResposta | null>(null);
  const [erro, setErro] = useState("");
  const [calculando, setCalculando] = useState(false);

  async function calcular() {
    const a = Number(atividades);
    const e = Number(estrelas);
    if (atividades.trim() === "" || !Number.isInteger(a) || a < 1) {
      setErro("Informe pelo menos 1 atividade (número inteiro).");
      setResultado(null);
      return;
    }
    if (estrelas.trim() === "" || !Number.isInteger(e) || e < 0) {
      setErro("Informe as estrelas (número inteiro, 0 ou mais).");
      setResultado(null);
      return;
    }
    setCalculando(true);
    setErro("");
    setResultado(null);
    try {
      setResultado(
        await api<ExemploMatificResposta>(
          `/escolas/${escolaId}/configuracoes/pontuacao/exemplo/matific?atividades=${a}&estrelas=${e}&${periodoParaQuery(periodo)}`,
        ),
      );
    } catch (excecao) {
      setErro(mensagemDeErro(excecao));
    } finally {
      setCalculando(false);
    }
  }

  return (
    <div>
      <p className="text-sm font-medium">Premiação Melhor Matemática</p>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        Informe as atividades e as estrelas de um aluno no período. O Constela usa a régua da escola no mesmo período
        da tela de Premiações. Não é a nota de Matemática nem o placar por estrelas.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className={ROTULO_CAMPO}>Atividades no período</span>
          <input
            className={estiloInput}
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder="Ex.: 20"
            value={atividades}
            onChange={(e) => {
              setAtividades(e.target.value);
              setResultado(null);
            }}
          />
        </label>
        <label className="block text-sm">
          <span className={ROTULO_CAMPO}>Estrelas no período</span>
          <input
            className={estiloInput}
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            placeholder="Ex.: 70"
            value={estrelas}
            onChange={(e) => {
              setEstrelas(e.target.value);
              setResultado(null);
            }}
          />
        </label>
      </div>
      <div className="mt-3">
        <span className={ROTULO_CAMPO}>Período (o mesmo das Premiações)</span>
        <SeletorPeriodo
          valor={periodo}
          onChange={(p) => {
            definirPeriodo(p);
            setResultado(null);
          }}
        />
      </div>
      <div className="mt-3">
        <Botao variante="neutro" onClick={calcular} disabled={calculando}>
          {calculando ? "Calculando..." : "Ver exemplo"}
        </Botao>
      </div>
      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      {resultado && <ResultadoMatific ex={resultado} />}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * A área com as abas.
 * ----------------------------------------------------------------------- */

type AbaExemplo = "elefante" | "matific";

// Mesmo estilo de aba de `RelatoriosArea.tsx` / `Rankings.tsx`.
const estiloAba = (ativa: boolean) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    ativa
      ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
      : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
  }`;

export default function ExemploPontuacao({ escolaId }: { escolaId: number }) {
  const modulos = useModulos();
  const [escolhida, setEscolhida] = useState<AbaExemplo>("elefante");
  const idBase = useId();
  const idAba = (chave: string) => `${idBase}-aba-${chave}`;
  const idPainel = `${idBase}-painel`;

  const abas: Array<{ chave: AbaExemplo; rotulo: string }> = [];
  if (modulos.leitura) abas.push({ chave: "elefante", rotulo: "Elefante Letrado" });
  if (modulos.matematica) abas.push({ chave: "matific", rotulo: "Matific" });
  // Nenhuma plataforma contratada: não há exemplo a dar.
  if (abas.length === 0) return null;
  const aba = abas.some((a) => a.chave === escolhida) ? escolhida : abas[0].chave;

  return (
    <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <p className="text-sm font-medium">Quer ver um exemplo?</p>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        A conta é feita pelo Constela, com a mesma regra das premiações. Nenhum dado de aluno aparece aqui.
      </p>

      <div
        role="tablist"
        aria-label="Exemplo por plataforma"
        className="mt-3 flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60 sm:inline-flex"
      >
        {abas.map((a) => (
          <button
            key={a.chave}
            id={idAba(a.chave)}
            type="button"
            role="tab"
            aria-selected={aba === a.chave}
            aria-controls={idPainel}
            onClick={() => setEscolhida(a.chave)}
            className={estiloAba(aba === a.chave)}
          >
            {a.rotulo}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={idPainel} aria-labelledby={idAba(aba)} className="mt-4">
        {aba === "elefante" ? <ExemploElefante escolaId={escolaId} /> : <ExemploMatific escolaId={escolaId} />}
      </div>
    </section>
  );
}
