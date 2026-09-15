/**
 * "Como funciona?" — a explicação, em linguagem simples, de como o Constela
 * calcula os pontos dos livros e as notas de Leitura e Matemática.
 *
 * É SOMENTE LEITURA por definição: só a Constela (Admin Global) pode alterar a
 * regra. Na régua institucional ela é a mesma para a rede inteira; na régua
 * PERSONALIZADA (perfil-scoring "personalizado") a escola tem régua própria e os
 * pesos institucionais abaixo NÃO são mostrados — podem não ser os que valem
 * nela. Sem saber a régua (``modo`` null), também não mostra os pesos. Os
 * números que aparecem aqui vêm de
 * GET /escolas/{id}/configuracoes/dificuldade-livro (parâmetros congelados da
 * versão vigente) — nada é inventado na tela. Se a API falhar, o bloco mostra
 * uma mensagem amigável em vez de números fixos.
 *
 * Os pesos das notas (Leitura 35/30/30/5, Matemática 40/35/25) são os pesos
 * INSTITUCIONAIS de backend/app/services/scoring.py (PESOS_PADRAO). Não existe
 * endpoint que os exponha — são constantes de código, iguais para toda a rede —
 * por isso ficam espelhados aqui. Se um dia mudarem no backend, este espelho
 * precisa acompanhar.
 */
import { ChevronDown, HelpCircle } from "lucide-react";
import { useId, useState } from "react";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api, ApiError } from "../lib/api";
import { Botao, Card, Carregando, Mensagem, estiloInput } from "./ui";

/** Resposta de GET /escolas/{id}/configuracoes/dificuldade-livro. */
export interface DificuldadeLivroInfo {
  versao_vigente: string;
  regra_da_escola: string;
  parametros: {
    posicoes_extra?: Record<string, number>;
    posicoes_faixa?: Record<string, number>;
    medianas_wordcount?: Record<string, number>;
    alpha?: number;
    razao_log?: number;
    piso?: number;
    teto?: number;
    fator_serie?: Record<string, number>;
    fator_serie_padrao?: number;
    calibracao?: { n_livros?: number; catalogo_de?: string; fonte?: string };
  };
  catalogo?: { n?: number; gerado_em?: string };
  /** Só vem quando a consulta leva ?nivel= (e, opcionalmente, titulo e ano_escolar). */
  exemplo?: ExemploDificuldade;
}

/** Decomposição de UMA leitura (regra vigente). Na régua legada (perfil
 *  personalizado) só ``nivel`` e ``valor`` existem. */
export interface ExemploDificuldade {
  versao?: string;
  nivel: string;
  titulo?: string | null;
  base_nivel?: number;
  ajuste_intrinseco?: number;
  fator_serie?: number;
  serie?: number | null;
  word_count?: number | null;
  mediana_nivel?: number | null;
  valor: number;
  encontrado_no_catalogo?: boolean | null;
}

// Pesos INSTITUCIONAIS (scoring.PESOS_PADRAO) — ver o comentário do topo.
const PESOS_LEITURA: Array<[string, number]> = [
  ["livros únicos", 35],
  ["dificuldade dos livros", 30],
  ["questões", 30],
  ["tempo de leitura", 5],
];
const PESOS_MATEMATICA: Array<[string, number]> = [
  ["atividades finalizadas", 40],
  ["pontuação média", 35],
  ["estrelas", 25],
];

/** Régua de pontuação da escola (GET /configuracoes/perfil-scoring → modo). */
export type ModoReguaPontuacao = "institucional" | "personalizado";

export const TEXTO_REGUA_PERSONALIZADA =
  "A Constela configurou uma régua própria para esta escola; os pesos podem diferir do padrão da rede.";

const MENSAGEM_FALHA =
  "Não foi possível carregar os detalhes da regra agora. A pontuação continua sendo calculada normalmente pelo Constela; tente de novo mais tarde.";

function decimal(valor: number, casas = 2): string {
  return valor.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

/** 1,40 → "×1,40" */
function fator(valor: number): string {
  return `×${decimal(valor)}`;
}

/** Lista "1º ano ×1,40 … 5º ano ×1,00" a partir de ``fator_serie`` (chaves
 *  numéricas em string), na ordem das séries. */
function fatoresPorSerie(fatores: Record<string, number> | undefined): Array<[string, number]> {
  if (!fatores) return [];
  return Object.entries(fatores)
    .map(([serie, valor]) => [Number(serie), Number(valor)] as [number, number])
    .filter(([serie, valor]) => Number.isFinite(serie) && Number.isFinite(valor))
    .sort((a, b) => a[0] - b[0])
    .map(([serie, valor]) => [`${serie}º ano`, valor]);
}

function listaPesos(pesos: Array<[string, number]>): string {
  return pesos.map(([nome, peso]) => `${nome} ${peso}%`).join(", ");
}

/* -------------------------------------------------------------------------
 * Exemplo opcional: pede a decomposição de UMA leitura à própria API
 * (?nivel=&titulo=&ano_escolar=). Só mostra o que a API devolver.
 * ----------------------------------------------------------------------- */
function ExemploDeLivro({ escolaId }: { escolaId: number }) {
  const [nivel, setNivel] = useState("");
  const [titulo, setTitulo] = useState("");
  const [anoEscolar, setAnoEscolar] = useState("");
  const [exemplo, setExemplo] = useState<ExemploDificuldade | null>(null);
  const [erro, setErro] = useState("");
  const [calculando, setCalculando] = useState(false);

  async function calcular() {
    const codigo = nivel.trim().toUpperCase();
    if (!codigo) {
      setErro("Informe o nível do livro (ex.: D).");
      return;
    }
    setCalculando(true);
    setErro("");
    setExemplo(null);
    const query = new URLSearchParams({ nivel: codigo });
    if (titulo.trim()) query.set("titulo", titulo.trim());
    if (anoEscolar.trim()) query.set("ano_escolar", anoEscolar.trim());
    try {
      const resposta = await api<DificuldadeLivroInfo>(
        `/escolas/${escolaId}/configuracoes/dificuldade-livro?${query.toString()}`,
      );
      if (resposta.exemplo && typeof resposta.exemplo.valor === "number") {
        setExemplo(resposta.exemplo);
      } else {
        setErro("A regra não devolveu um exemplo para esses dados.");
      }
    } catch (excecao) {
      setErro(excecao instanceof ApiError ? excecao.message : "Não foi possível calcular o exemplo.");
    } finally {
      setCalculando(false);
    }
  }

  const completo =
    exemplo != null &&
    typeof exemplo.base_nivel === "number" &&
    typeof exemplo.ajuste_intrinseco === "number" &&
    typeof exemplo.fator_serie === "number";

  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <p className="text-sm font-medium">Quer ver um exemplo?</p>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        Informe o nível do livro e, se quiser, o título e o ano escolar do aluno. O valor vem da
        mesma regra que calcula as notas.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-300">Nível do livro</span>
          <input
            className={estiloInput}
            placeholder="Ex.: D"
            value={nivel}
            onChange={(e) => setNivel(e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-300">Título (opcional)</span>
          <input
            className={estiloInput}
            placeholder="Ex.: O que é o que é?"
            value={titulo}
            onChange={(e) => setTitulo(e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-300">Ano escolar (opcional)</span>
          <input
            className={estiloInput}
            placeholder="Ex.: 3º Ano"
            value={anoEscolar}
            onChange={(e) => setAnoEscolar(e.target.value)}
          />
        </label>
      </div>
      <div className="mt-3">
        <Botao variante="neutro" onClick={calcular} disabled={calculando}>
          {calculando ? "Calculando..." : "Ver exemplo"}
        </Botao>
      </div>
      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      {exemplo && (
        <div className="mt-3 rounded-lg bg-zinc-50 p-3 text-sm dark:bg-zinc-900">
          {completo ? (
            <p>
              Nível <strong>{exemplo.nivel}</strong>
              {exemplo.titulo ? <> — “{exemplo.titulo}”</> : null}
              {typeof exemplo.serie === "number" ? <> — {exemplo.serie}º ano</> : null}:{" "}
              <span className="tabular-nums">
                {decimal(exemplo.base_nivel as number)} (nível) × {decimal(exemplo.ajuste_intrinseco as number)}{" "}
                (tamanho) × {decimal(exemplo.fator_serie as number)} (série) ={" "}
                <strong>{decimal(exemplo.valor)} pontos</strong>
              </span>
            </p>
          ) : (
            <p>
              Nível <strong>{exemplo.nivel}</strong>: <strong>{decimal(exemplo.valor)} pontos</strong>
            </p>
          )}
          {typeof exemplo.word_count === "number" && typeof exemplo.mediana_nivel === "number" && (
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              Palavras do livro: {exemplo.word_count.toLocaleString("pt-BR")} (livro típico do nível:{" "}
              {exemplo.mediana_nivel.toLocaleString("pt-BR")}).
            </p>
          )}
          {exemplo.titulo && exemplo.encontrado_no_catalogo === false && (
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              Título não encontrado no catálogo: o cálculo usou o livro típico do nível.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * O bloco recolhível "Como funciona?".
 * ----------------------------------------------------------------------- */
export default function ComoFuncionaPontuacao({
  inicialAberto = false,
  modo = null,
}: {
  inicialAberto?: boolean;
  /** Régua vigente da escola; null = ainda não se sabe (carregando/erro). */
  modo?: ModoReguaPontuacao | null;
}) {
  const { escolaId } = useApp();
  const [aberto, setAberto] = useState(inicialAberto);
  const idConteudo = useId();
  // Só busca quando o bloco é aberto (quem não abre não gasta uma requisição).
  const { dados, erro, carregando } = useApi<DificuldadeLivroInfo>(
    escolaId && aberto ? `/escolas/${escolaId}/configuracoes/dificuldade-livro` : null,
  );

  const parametros = dados?.parametros;
  const fatores = fatoresPorSerie(parametros?.fator_serie);
  const maisPct = typeof parametros?.teto === "number" ? Math.round((parametros.teto - 1) * 100) : null;
  const menosPct = typeof parametros?.piso === "number" ? Math.round((1 - parametros.piso) * 100) : null;
  const catalogoN = dados?.catalogo?.n ?? parametros?.calibracao?.n_livros;
  const catalogoDe = parametros?.calibracao?.catalogo_de ?? dados?.catalogo?.gerado_em;

  return (
    <Card className="p-5">
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        aria-expanded={aberto}
        aria-controls={idConteudo}
        className="-m-1 flex w-full items-center gap-2 rounded-lg p-1 text-left text-sm font-semibold text-zinc-800 transition-colors hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-400"
      >
        <HelpCircle size={16} aria-hidden className="shrink-0" />
        <span>Como funciona?</span>
        <ChevronDown
          size={16}
          aria-hidden
          className={`ml-auto shrink-0 text-zinc-400 transition-transform duration-200 ${aberto ? "rotate-180" : ""}`}
        />
      </button>

      {aberto && (
        <div id={idConteudo} className="mt-4 space-y-4 text-sm text-zinc-700 dark:text-zinc-300">
          {!escolaId ? (
            <p className="text-zinc-500 dark:text-zinc-400">
              Selecione uma escola no topo para ver os detalhes da regra.
            </p>
          ) : carregando ? (
            <Carregando texto="Carregando a regra..." />
          ) : erro || !dados ? (
            <Mensagem tipo="erro">{MENSAGEM_FALHA}</Mensagem>
          ) : (
            <>
              <ol className="list-decimal space-y-3 pl-5">
                <li>
                  <strong>Nível do livro.</strong> Cada livro do Elefante Letrado tem um nível de
                  leitura, de AA a Z. Quanto mais alto o nível, mais pontos o livro vale.
                </li>
                <li>
                  <strong>Tamanho do livro.</strong> Dentro do mesmo nível, um livro maior que o
                  típico vale um pouco mais
                  {maisPct != null ? <> (até +{maisPct}%)</> : null} e um livro menor vale um pouco
                  menos{menosPct != null ? <> (no mínimo −{menosPct}%)</> : null}. O nível continua
                  sendo o que mais pesa.
                </li>
                <li>
                  <strong>Série do aluno.</strong> O mesmo livro vale mais para quem está no começo
                  da alfabetização.
                  {fatores.length > 0 ? (
                    <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-zinc-600 dark:text-zinc-400">
                      {fatores.map(([serie, valor]) => (
                        <li key={serie} className="tabular-nums">
                          {serie}: {fator(valor)}
                        </li>
                      ))}
                      {typeof parametros?.fator_serie_padrao === "number" && (
                        <li className="tabular-nums">
                          Outras séries: {fator(parametros.fator_serie_padrao)}
                        </li>
                      )}
                    </ul>
                  ) : null}
                </li>
                <li>
                  <strong>Cada livro conta uma vez.</strong> Reler um livro não soma pontos de novo.
                </li>
                {modo === "institucional" ? (
                  <>
                    <li>
                      <strong>Nota de Leitura (0 a 100).</strong> Combina quatro indicadores:{" "}
                      {listaPesos(PESOS_LEITURA)}. Em cada um, o aluno é comparado com os colegas da
                      própria escola.
                    </li>
                    <li>
                      <strong>Nota de Matemática (0 a 100).</strong> Combina três indicadores do Matific:{" "}
                      {listaPesos(PESOS_MATEMATICA)}. Também comparando com os colegas da própria escola.
                    </li>
                  </>
                ) : (
                  <li>
                    <strong>Notas de Leitura e de Matemática (0 a 100).</strong>{" "}
                    {modo === "personalizado"
                      ? TEXTO_REGUA_PERSONALIZADA
                      : "Os pesos de cada nota são definidos pela Constela."}{" "}
                    Em cada indicador, o aluno é comparado com os colegas da própria escola.
                  </li>
                )}
              </ol>

              <ExemploDeLivro escolaId={escolaId} />

              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Regra em uso nesta escola: {dados.regra_da_escola}
                {dados.regra_da_escola !== dados.versao_vigente ? (
                  <> (regra da rede: {dados.versao_vigente})</>
                ) : null}
                {typeof catalogoN === "number" ? (
                  <>
                    . Catálogo de referência: {catalogoN.toLocaleString("pt-BR")} livros
                    {catalogoDe ? <> ({catalogoDe})</> : null}
                  </>
                ) : null}
                .
              </p>
            </>
          )}
        </div>
      )}
    </Card>
  );
}
