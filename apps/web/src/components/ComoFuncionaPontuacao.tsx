/**
 * "Como funciona?" — a explicação, em linguagem simples, de como o Constela
 * calcula os pontos dos livros e as notas de Leitura e Matemática.
 *
 * É SOMENTE LEITURA por definição: só a Constela (Admin Global) pode alterar a
 * regra. Na régua institucional ela é a mesma para a rede inteira; na régua
 * PERSONALIZADA (perfil-scoring "personalizado") a escola tem régua própria e a
 * lista de pesos NÃO é afirmada aqui (os cartões da página mostram os pesos
 * efetivos). Sem saber a régua (``modo`` null), também não mostra os pesos.
 *
 * DE ONDE VÊM OS NÚMEROS — nada é inventado na tela:
 *   * fatores do livro (tamanho, série, catálogo): GET
 *     /escolas/{id}/configuracoes/dificuldade-livro (parâmetros congelados da
 *     versão vigente), buscado só quando o bloco é aberto;
 *   * pesos das notas: a página passa ``pesos`` lidos de GET
 *     /escolas/{id}/configuracoes/pontuacao/regra — os pesos EFETIVOS que o
 *     motor aplica (``scoring.pesos_efetivos``). Antes eles ficavam espelhados
 *     em constantes aqui, que podiam divergir do backend; sem a resposta da rota,
 *     a explicação diz só que os pesos são definidos pela Constela.
 * Se a API dos fatores falhar, o bloco mostra uma mensagem amigável em vez de
 * números fixos.
 *
 * "Quer ver um exemplo?" (`ExemploPontuacao`) fica FORA do trecho que depende
 * de /dificuldade-livro: ele tem as próprias rotas, uma aba por plataforma
 * contratada, e não pode sumir numa rede sem Leitura (a aba do Matific segue).
 */
import { ChevronDown, HelpCircle } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import type { PesosDaRegua } from "../lib/tiposCriterios";
import { ordenarCriterios } from "./CriteriosVisuais";
import ExemploPontuacao from "./ExemploPontuacao";
import { Card, Carregando, IconePastel, Mensagem } from "./ui";

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
}

/** Régua de pontuação da escola (GET /configuracoes/perfil-scoring → modo). */
export type ModoReguaPontuacao = "institucional" | "personalizado";

export const TEXTO_REGUA_PERSONALIZADA =
  "A Constela configurou uma régua própria para esta escola; os pesos podem diferir do padrão da rede.";

const MENSAGEM_FALHA =
  "Não foi possível carregar os detalhes da regra agora. A pontuação continua sendo calculada normalmente pelo Constela; tente de novo mais tarde.";

// Nome de cada indicador no meio da frase ("livros únicos 35%, ...").
const NOME_NA_FRASE: Record<string, string> = {
  livros: "livros únicos",
  dificuldade: "dificuldade dos livros",
  questoes: "questões",
  tempo: "tempo de leitura",
  atividades: "atividades finalizadas",
  media: "pontuação média",
  estrelas: "estrelas",
};

const FORMATO_PESO = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

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

/** {livros: 35, ...} (da API) → "livros únicos 35%, dificuldade dos livros 30%, ..." */
function listaPesos(pesos: Record<string, number>): string {
  return ordenarCriterios(Object.keys(pesos))
    .map((chave) => `${NOME_NA_FRASE[chave] ?? chave} ${FORMATO_PESO.format(pesos[chave])}%`)
    .join(", ");
}

/** Um passo numerado da explicação (o número é decorativo; a lista é um <ol>). */
function Passo({ numero, children }: { numero: number; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden
        className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-indigo-50 text-xs font-bold text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300"
      >
        {numero}
      </span>
      <div className="min-w-0 flex-1 leading-relaxed">{children}</div>
    </li>
  );
}

/* -------------------------------------------------------------------------
 * O bloco recolhível "Como funciona?".
 * ----------------------------------------------------------------------- */
export default function ComoFuncionaPontuacao({
  inicialAberto = false,
  modo = null,
  pesos = null,
}: {
  inicialAberto?: boolean;
  /** Régua vigente da escola; null = ainda não se sabe (carregando/erro). */
  modo?: ModoReguaPontuacao | null;
  /** Pesos EFETIVOS por matéria (GET /pontuacao/regra), só das matérias do
   *  plano. Ausentes = a explicação não cita números de peso. */
  pesos?: PesosDaRegua | null;
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

  const pesosLeitura = modo === "institucional" ? pesos?.leitura ?? null : null;
  const pesosMatematica = modo === "institucional" ? pesos?.matematica ?? null : null;
  const temPesos = Boolean(pesosLeitura || pesosMatematica);

  return (
    <Card className="p-5 sm:p-6">
      <div className="flex items-center gap-3.5">
        <IconePastel icone={HelpCircle} tom="violeta" />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => setAberto((a) => !a)}
            aria-expanded={aberto}
            aria-controls={idConteudo}
            className="-m-1 flex w-full items-center gap-2 rounded-xl p-1 text-left text-[17px] font-semibold text-zinc-900 transition-colors hover:text-indigo-600 dark:text-zinc-50 dark:hover:text-indigo-300"
          >
            <span>Como funciona?</span>
            <ChevronDown
              size={18}
              aria-hidden
              className={`ml-auto shrink-0 text-zinc-400 transition-transform duration-200 ${aberto ? "rotate-180" : ""}`}
            />
          </button>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            O passo a passo da conta e um exemplo calculado pelo Constela.
          </p>
        </div>
      </div>

      {aberto && (
        <div id={idConteudo} className="mt-5 space-y-5 border-t border-zinc-100 pt-5 text-sm text-zinc-700 dark:border-zinc-800 dark:text-zinc-300">
          {!escolaId ? (
            <p className="text-zinc-500 dark:text-zinc-400">
              Selecione uma escola no topo para ver os detalhes da regra.
            </p>
          ) : (
            <>
              {carregando ? (
                <Carregando texto="Carregando a regra..." />
              ) : erro?.status === 403 ? (
                // Fora do plano (ex.: rede sem Leitura): explicar, não pedir que
                // "tente de novo mais tarde".
                <p className="text-zinc-500 dark:text-zinc-400">{erro.message}</p>
              ) : erro || !dados ? (
                <Mensagem tipo="erro">{MENSAGEM_FALHA}</Mensagem>
              ) : (
                <>
                  <ol className="space-y-4">
                    <Passo numero={1}>
                      <strong>Nível do livro.</strong> Cada livro do Elefante Letrado tem um nível de
                      leitura, de AA a Z. Quanto mais alto o nível, mais pontos o livro vale.
                    </Passo>
                    <Passo numero={2}>
                      <strong>Tamanho do livro.</strong> Dentro do mesmo nível, um livro maior que o
                      típico vale um pouco mais
                      {maisPct != null ? <> (até +{maisPct}%)</> : null} e um livro menor vale um pouco
                      menos{menosPct != null ? <> (no mínimo −{menosPct}%)</> : null}. O nível continua
                      sendo o que mais pesa.
                    </Passo>
                    <Passo numero={3}>
                      <strong>Série do aluno.</strong> O mesmo livro vale mais para quem está no começo
                      da alfabetização.
                      {fatores.length > 0 ? (
                        <ul className="mt-2 flex flex-wrap gap-1.5">
                          {fatores.map(([serie, valor]) => (
                            <li
                              key={serie}
                              className="rounded-lg bg-zinc-100 px-2 py-1 text-xs font-semibold tabular-nums text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
                            >
                              {serie}: {fator(valor)}
                            </li>
                          ))}
                          {typeof parametros?.fator_serie_padrao === "number" && (
                            <li className="rounded-lg bg-zinc-100 px-2 py-1 text-xs font-semibold tabular-nums text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                              Outras séries: {fator(parametros.fator_serie_padrao)}
                            </li>
                          )}
                        </ul>
                      ) : null}
                    </Passo>
                    <Passo numero={4}>
                      <strong>Cada livro conta uma vez.</strong> Reler um livro não soma pontos de novo.
                    </Passo>
                    {temPesos ? (
                      <>
                        {pesosLeitura && (
                          <Passo numero={5}>
                            <strong>Nota de Leitura (0 a 100).</strong> Combina{" "}
                            {Object.keys(pesosLeitura).length === 4 ? "quatro indicadores" : "os indicadores"}:{" "}
                            {listaPesos(pesosLeitura)}. Em cada um, o aluno é comparado com os colegas da
                            própria escola.
                          </Passo>
                        )}
                        {pesosMatematica && (
                          <Passo numero={pesosLeitura ? 6 : 5}>
                            <strong>Nota de Matemática (0 a 100).</strong> Combina{" "}
                            {Object.keys(pesosMatematica).length === 3 ? "três indicadores do Matific" : "os indicadores do Matific"}:{" "}
                            {listaPesos(pesosMatematica)}. Também comparando com os colegas da própria escola.
                          </Passo>
                        )}
                      </>
                    ) : (
                      <Passo numero={5}>
                        <strong>Notas de Leitura e de Matemática (0 a 100).</strong>{" "}
                        {modo === "personalizado"
                          ? TEXTO_REGUA_PERSONALIZADA
                          : "Os pesos de cada nota são definidos pela Constela."}{" "}
                        Em cada indicador, o aluno é comparado com os colegas da própria escola.
                      </Passo>
                    )}
                  </ol>

                  <p className="rounded-xl bg-zinc-50 px-3.5 py-2.5 text-xs text-zinc-500 dark:bg-zinc-800/60 dark:text-zinc-400">
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
              {/* Fora do trecho que depende de /dificuldade-livro: sem Leitura, a aba
                  do Matific continua. */}
              <ExemploPontuacao escolaId={escolaId} />
            </>
          )}
        </div>
      )}
    </Card>
  );
}
