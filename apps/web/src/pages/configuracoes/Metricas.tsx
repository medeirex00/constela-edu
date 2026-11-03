/**
 * /metricas — "Critérios de pontuação" (identidade visual v2, referência 3).
 *
 * Duas telas na mesma rota, decididas por `usuario.is_global` (não por cargo):
 *
 *   ESCOLA e SECRETARIA (só leitura) — a régua EFETIVA desta escola em cartões:
 *     barra empilhada dos pesos + critérios com ícone pastel e percentual, lidos de
 *     GET /configuracoes/pontuacao/regra (os pesos que o motor aplica de fato);
 *     as regras FIXAS da premiação; o ranking atual (5 primeiros de cada matéria,
 *     só para a gestão da escola — a Secretaria não recebe nome de criança); e o
 *     "Como funciona?" recolhível com a explicação longa e o exemplo calculado.
 *     Nenhum controle: a escola usa o Constela, não administra a matemática.
 *
 *   ADMIN GLOBAL — os MESMOS cartões, com os editores reais: régua Padrão ×
 *     Personalizada no topo, pesos com controles deslizantes coloridos e "Salvar
 *     pesos" por cartão (cada PUT recalcula a escola), e os ajustes avançados
 *     (pontos extras, níveis, dificuldade por turma, referências) em abas.
 *
 * Sem "prévia ao vivo" com pesos não salvos: não existe cálculo de prévia no
 * backend e uma segunda fórmula no front é proibida (docs/design D9). A barra do
 * editor só desenha as fatias que o Admin Global está digitando.
 */
import {
  BookOpen,
  Calculator,
  Gauge,
  Info,
  MessageCircleQuestion,
  Scale,
  School,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Users,
  Wand2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

import ComoFuncionaPontuacao from "../../components/ComoFuncionaPontuacao";
import {
  BarraPesos,
  CabecalhoCartao,
  CartaoRegua,
  ControleDeslizante,
  LinhaCriterio,
  RegrasPremiacao,
  classesListaCriterios,
  fatiasDosPesos,
  metaDoCriterio,
  ordenarCriterios,
} from "../../components/CriteriosVisuais";
import RankingAtualCriterios from "../../components/RankingAtualCriterios";
import {
  Abas,
  Badge,
  Botao,
  Card,
  Carregando,
  Erro,
  IconePastel,
  Interruptor,
  Mensagem,
  PageHeader,
  RotuloSecao,
  Skeleton,
  Vazio,
  type TomPastel,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi, type ResultadoUseApi } from "../../hooks/useApi";
import { useModulos } from "../../hooks/useModulos";
import { usePerfil } from "../../hooks/usePerfil";
import { api, ApiError } from "../../lib/api";
import { nota } from "../../lib/formato";
import type { ModoRegua, PesosDaRegua, RegraPontuacao } from "../../lib/tiposCriterios";
import type { Pesos, Referencias } from "../../lib/types";
import { EditorNiveis, PontuacaoPorTurma } from "./dificuldade";

/* -------------------------------------------------------------------------
 * Os três grupos de pesos REAIS da nota (scoring.PESOS_PADRAO) e como cada um
 * aparece: mesmo título, ícone e cor na visão da escola e no editor.
 * ----------------------------------------------------------------------- */
const ROTULOS_LEITURA = {
  livros: "Livros únicos concluídos",
  dificuldade: "Dificuldade dos livros",
  questoes: "Questões",
  tempo: "Tempo de leitura",
};
const ROTULOS_MATEMATICA = { atividades: "Atividades finalizadas", media: "Pontuação média", estrelas: "Estrelas" };
const ROTULOS_QUESTOES = { tentativas: "Tentativas", acertos: "Acertos" };

const GRUPOS: Record<
  "leitura" | "matematica" | "questoes",
  { titulo: string; subtitulo: string; icone: LucideIcon; tom: TomPastel }
> = {
  leitura: { titulo: "Leitura", subtitulo: "Elefante Letrado · nota de 0 a 100", icone: BookOpen, tom: "violeta" },
  matematica: { titulo: "Matemática", subtitulo: "Matific · nota de 0 a 100", icone: Calculator, tom: "teal" },
  questoes: {
    titulo: "Questões",
    subtitulo: "Como o critério Questões da Leitura se divide",
    icone: MessageCircleQuestion,
    tom: "azul",
  },
};

/** Esqueleto de um cartão de pesos (enquanto a API responde). */
function EsqueletoPesos({ linhas = 3 }: { linhas?: number }) {
  return (
    <div className="mt-5 space-y-5" aria-hidden>
      <Skeleton className="h-3.5 w-full rounded-full" />
      {Array.from({ length: linhas }, (_, i) => (
        <div key={i} className="flex items-center gap-3.5">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
          <Skeleton className="h-10 w-[4.5rem] rounded-xl" />
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Editor genérico de pesos — reutilizado por Leitura, Matemática, Questões e
 * Ranking Geral (Configurações). Cada indicador vira uma linha com ícone pastel,
 * título, descrição curta, controle deslizante na cor do critério e a caixa com
 * o percentual exato. A barra empilhada acompanha o estado local (só as fatias
 * digitadas, sem conta nenhuma). Envia SEMPRE todas as chaves (o backend recusa
 * chaves diferentes de PESOS_PADRAO) e exige soma 100.
 * ----------------------------------------------------------------------- */
export function PesosEditor({
  namespace,
  rotulos,
  descricao,
  titulo,
  icone = SlidersHorizontal,
  tom = "violeta",
  selo,
  aviso,
  aoSalvar,
  duasColunas = false,
  className = "",
}: {
  namespace: string;
  rotulos: Record<string, string>;
  descricao?: ReactNode;
  /** Com título, o cartão ganha cabeçalho (ícone pastel + h2) e vira uma região nomeada. */
  titulo?: string;
  icone?: LucideIcon;
  tom?: TomPastel;
  /** Selo logo abaixo do título (ex.: "Em uso nesta escola"). */
  selo?: ReactNode;
  /** Aviso logo abaixo do cabeçalho (ex.: qual régua está em uso). */
  aviso?: ReactNode;
  /** Chamado depois de salvar com sucesso (as notas foram recalculadas). */
  aoSalvar?: () => void;
  /** Linhas lado a lado a partir de md (cartão de largura inteira). */
  duasColunas?: boolean;
  className?: string;
}) {
  const { escolaId, usuario } = useApp();
  // GOVERNANÇA: só o Admin Global altera pesos (PUT /pesos/{ns} responde 403
  // para os demais). Coordenador, admin de escola e Secretaria só enxergam.
  const somenteLeitura = !usuario?.is_global;
  const idTitulo = useId();
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

  const soma = valores
    ? Math.round(Object.values(valores).reduce((total, valor) => total + valor, 0) * 100) / 100
    : 0;
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
      aoSalvar?.();
    } catch (excecao) {
      setMensagem({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message : "Não foi possível salvar os pesos.",
      });
    } finally {
      setSalvando(false);
    }
  }

  function mudar(chave: string, valor: number) {
    if (!valores) return;
    setValores({ ...valores, [chave]: valor });
  }

  let corpo: ReactNode;
  if (!escolaId) {
    corpo = <p className="mt-4 text-sm text-zinc-500 dark:text-zinc-400">Selecione uma escola no topo.</p>;
  } else if (erro) {
    corpo = (
      <div className="mt-4">
        <Mensagem tipo="erro">{erro.message}</Mensagem>
      </div>
    );
  } else if (carregando || !valores) {
    corpo = <EsqueletoPesos linhas={Object.keys(rotulos).length} />;
  } else {
    corpo = (
      <>
        <BarraPesos className="mt-5" fatias={fatiasDosPesos(valores, rotulos)} />
        <ul className={classesListaCriterios(duasColunas)}>
          {ordenarCriterios(Object.keys(valores)).map((chave) => {
            const rotulo = rotulos[chave] ?? chave;
            const meta = metaDoCriterio(chave, rotulo);
            const valor = valores[chave];
            return (
              <LinhaCriterio
                key={chave}
                meta={meta}
                direita={
                  <div className="relative">
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={0.5}
                      aria-label={`${rotulo} (valor exato)`}
                      className="w-[5.75rem] rounded-xl border border-zinc-200 bg-zinc-50 py-2 pl-3 pr-7 text-right text-base font-bold tabular-nums text-zinc-900 transition-colors hover:border-zinc-300 focus:border-indigo-500 focus:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white"
                      value={valor}
                      disabled={somenteLeitura}
                      onChange={(evento) => mudar(chave, Number(evento.target.value))}
                    />
                    <span
                      aria-hidden
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm font-semibold text-zinc-500 dark:text-zinc-400"
                    >
                      %
                    </span>
                  </div>
                }
              >
                <div className="mt-3.5 sm:pl-[3.375rem]">
                  <ControleDeslizante
                    rotulo={rotulo}
                    valor={valor}
                    tom={meta.tom}
                    desabilitado={somenteLeitura}
                    aoMudar={(novo) => mudar(chave, novo)}
                  />
                </div>
              </LinhaCriterio>
            );
          })}
        </ul>

        {/* mt-auto: num cartão esticado (mesma altura do vizinho), o rodapé
            fica no pé do cartão, alinhado ao do lado. */}
        <div className="mt-auto pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4 dark:border-zinc-800">
            <Badge tom={valido ? "ok" : "alerta"}>Soma: {nota(soma)}%{valido ? "" : " — precisa ser 100%"}</Badge>
            <Botao onClick={salvar} disabled={!valido || salvando || somenteLeitura}>
              {somenteLeitura ? "Somente leitura" : salvando ? "Salvando e recalculando..." : "Salvar pesos"}
            </Botao>
          </div>
        </div>
        {mensagem && (
          <div className="mt-3">
            <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
          </div>
        )}
      </>
    );
  }

  if (!titulo) {
    return (
      <Card className={`p-5 sm:p-6 ${className}`}>
        {descricao && <p className="text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
        {aviso}
        {corpo}
      </Card>
    );
  }
  return (
    <section aria-labelledby={idTitulo} className={`card flex flex-col p-5 sm:p-6 ${className}`}>
      <CabecalhoCartao id={idTitulo} icone={icone} tom={tom} titulo={titulo} subtitulo={descricao} />
      {/* O selo fica numa linha própria, alinhado ao título: no canto do cabeçalho
          ele espremia o subtítulo ("nota de 0 a 100" quebrava e o "100" ficava
          sozinho embaixo). 3,875rem = ícone (48 px) + espaço (14 px). */}
      {selo && <div className="mt-3 flex flex-wrap items-center gap-2 sm:pl-[3.875rem]">{selo}</div>}
      {aviso}
      {corpo}
    </section>
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
  // GOVERNANÇA: só o Admin Global altera as referências (PUT responde 403 para
  // os demais). Para os demais, nada fica editável.
  const somenteLeitura = !usuario?.is_global;
  const idTitulo = useId();
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
    <section aria-labelledby={idTitulo} className="card p-5 sm:p-6">
      <CabecalhoCartao
        id={idTitulo}
        icone={Scale}
        tom="azul"
        titulo="O que vale 100 em cada indicador"
        subtitulo={
          <>
            As referências definem o que vale <strong>100</strong> em cada indicador. No modo
            automático, o sistema usa os maiores resultados da própria base.
          </>
        }
      />

      <div className="mt-5 inline-flex rounded-2xl border border-zinc-200/80 bg-white p-1 shadow-cartao dark:border-zinc-800 dark:bg-zinc-900">
        {(["auto", "manual"] as const).map((opcao) => (
          <button
            key={opcao}
            type="button"
            aria-pressed={modo === opcao}
            disabled={somenteLeitura}
            onClick={() => setModo(opcao)}
            className={`rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${
              modo === opcao
                ? "bg-indigo-600 text-white shadow-pilula"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
            }`}
          >
            {opcao === "auto" ? "Automático" : "Manual"}
          </button>
        ))}
      </div>

      <ul className="mt-4 grid grid-cols-1 gap-x-8 md:grid-cols-2">
        {Object.entries(ROTULOS_REFERENCIAS).map(([chave, rotulo]) => (
          <li
            key={chave}
            className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 py-3 dark:border-zinc-800"
          >
            <div className="min-w-0">
              <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{rotulo}</p>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Em uso: <span className="tabular-nums">{nota(dados.valores_em_uso[chave] ?? 0)}</span>
              </p>
            </div>
            {modo === "manual" ? (
              <input
                type="number"
                min={0}
                aria-label={rotulo}
                disabled={somenteLeitura}
                className="w-28 rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-right text-sm font-semibold tabular-nums transition-colors focus:border-indigo-500 focus:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-800"
                value={manuais[chave] ?? 0}
                onChange={(evento) => setManuais({ ...manuais, [chave]: Number(evento.target.value) })}
              />
            ) : (
              <Badge>automático</Badge>
            )}
          </li>
        ))}
      </ul>

      <div className="mt-5 flex justify-end">
        <Botao onClick={salvar} disabled={salvando || somenteLeitura}>
          {somenteLeitura ? "Somente leitura" : salvando ? "Salvando e recalculando..." : "Salvar referências"}
        </Botao>
      </div>
      {mensagem && (
        <div className="mt-3">
          <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
        </div>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------
 * Pontos Extras (Elefante): bônus por livro lido DENTRO do horário da escola,
 * definido pelo TURNO da turma. A regra de horário fica no backend (scoring);
 * aqui só o liga/desliga e o valor por livro.
 * ----------------------------------------------------------------------- */
type ElefanteExtra = { ativo: boolean; pontos_por_livro: number };

const ROTULO_ATIVAR_EXTRAS = "Ativar pontos extras por livros lidos na escola";

function PontosExtrasEditor() {
  const { escolaId, usuario } = useApp();
  // GOVERNANÇA: só o Admin Global altera os pontos extras (PUT responde 403
  // para os demais).
  const somenteLeitura = !usuario?.is_global;
  const idTitulo = useId();
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
    <section aria-labelledby={idTitulo} className="card p-5 sm:p-6">
      <CabecalhoCartao
        id={idTitulo}
        icone={Wand2}
        tom="rosa"
        titulo="Pontos extras por leitura na escola"
        subtitulo={
          <>
            Dá pontos extras por cada livro que o aluno lê <strong>dentro do horário da escola</strong>,
            conforme o <strong>turno da turma</strong>: Manhã (7h–13h) ou Tarde (13h–18h), de segunda a
            sexta. Livros lidos fora desse horário — ou em turmas de turno Integral/Noite — contam só a
            pontuação normal. Usa a data e a hora reais de cada leitura (relatório individual do Elefante).
          </>
        }
      />

      <div className="mt-5 flex flex-wrap items-center gap-x-8 gap-y-4 rounded-2xl border border-zinc-200/80 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40">
        <div className="flex items-center gap-3">
          <Interruptor
            ligado={ativo}
            aoMudar={setAtivo}
            rotulo={ROTULO_ATIVAR_EXTRAS}
            desabilitado={somenteLeitura}
          />
          {/* O nome acessível já está no interruptor; o texto visível não se repete no leitor. */}
          <span aria-hidden className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
            {ROTULO_ATIVAR_EXTRAS}
          </span>
        </div>

        <div className={`flex items-center gap-3 ${ativo ? "" : "opacity-50"}`}>
          <label className="text-sm font-medium" htmlFor="pontos-extras-livro">Pontos extras por livro:</label>
          <input
            id="pontos-extras-livro"
            type="number"
            min={0}
            step="0.5"
            value={pontos}
            disabled={!ativo || somenteLeitura}
            onChange={(e) => setPontos(e.target.value)}
            className="w-24 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-right text-sm font-semibold tabular-nums disabled:cursor-not-allowed dark:border-zinc-700 dark:bg-zinc-900"
          />
        </div>
      </div>

      <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
        Ligar/desligar <strong>não apaga nenhuma leitura</strong> — só controla se o bônus entra na
        nota. Os pontos extras somam ao fator “Dificuldade” do Elefante (a nota continua de 0 a 100).
      </p>

      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
      <div className="mt-5 flex justify-end">
        <Botao onClick={salvar} disabled={salvando || somenteLeitura}>
          {somenteLeitura ? "Somente leitura" : salvando ? "Salvando e recalculando..." : "Salvar"}
        </Botao>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------
 * Régua de pontuação da escola: PADRÃO CONSTELA (régua institucional fixa) ×
 * PERSONALIZADO (a config desta tela). A escolha governa SÓ o scoring/ranking
 * INTERNO da escola — o ranking da REDE usa sempre a régua institucional. É o
 * primeiro controle da página porque decide se o resto tem efeito no ranking
 * interno. Backend: GET/PUT /configuracoes/perfil-scoring (dispara recálculo).
 * ----------------------------------------------------------------------- */
type PerfilScoring = { modo: ModoRegua };

function PerfilScoringEditor({
  aoMudar,
  aoTrocar,
}: {
  /** Informa a régua VIGENTE (salva) a cada leitura e a cada troca. */
  aoMudar?: (modo: ModoRegua | null) => void;
  /** Só depois de uma troca salva com sucesso (as notas foram recalculadas). */
  aoTrocar?: () => void;
}) {
  const { escolaId, usuario } = useApp();
  // GOVERNANÇA: só o Admin Global escolhe a régua (PUT /perfil-scoring responde
  // 403 para os demais). A tela mostra a escolha vigente em vez de oferecer um
  // toggle que falharia ao salvar.
  const somenteLeitura = !usuario?.is_global;
  const idTitulo = useId();
  const { dados, erro, carregando, recarregar } = useApi<PerfilScoring>(
    escolaId ? `/escolas/${escolaId}/configuracoes/perfil-scoring` : null,
  );
  const [modo, setModo] = useState<ModoRegua>("institucional");
  const [salvando, setSalvando] = useState(false);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  useEffect(() => {
    if (dados) {
      setModo(dados.modo);
      setMensagem(null);
    }
    // Informa a página da régua VIGENTE (salva), para a explicação "Como
    // funciona?" não mostrar os pesos institucionais numa régua personalizada.
    aoMudar?.(dados ? dados.modo : null);
  }, [dados, erro]); // eslint-disable-line react-hooks/exhaustive-deps

  if (carregando) {
    return (
      <Card className="p-5 sm:p-6">
        <div className="flex items-center gap-3.5" aria-hidden>
          <Skeleton className="h-12 w-12 rounded-2xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        </div>
        <span className="sr-only">Carregando a régua da escola...</span>
      </Card>
    );
  }
  if (erro) return <Mensagem tipo="erro">{erro.message}</Mensagem>;

  async function escolher(novo: ModoRegua) {
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
      aoMudar?.(novo);
      aoTrocar?.();
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

  const opcoes: Array<{ valor: ModoRegua; titulo: string; descricao: string; icone: LucideIcon; tom: TomPastel }> = [
    {
      valor: "institucional",
      titulo: "Régua Padrão Constela",
      descricao:
        "A configuração padrão usa a régua institucional da Constela (dificuldade A3 + pesos padrão). É o estado inicial de toda escola.",
      icone: ShieldCheck,
      tom: "violeta",
    },
    {
      valor: "personalizado",
      titulo: "Personalizado",
      descricao:
        "A configuração personalizada altera apenas o scoring e o ranking INTERNO desta escola. O ranking da rede utiliza sempre a régua institucional da Constela.",
      icone: SlidersHorizontal,
      tom: "rosa",
    },
  ];

  return (
    <section aria-labelledby={idTitulo} className="card p-5 sm:p-6">
      <CabecalhoCartao
        id={idTitulo}
        icone={Gauge}
        tom="violeta"
        titulo="Régua de pontuação da escola"
        subtitulo={
          <>
            Define a régua usada no ranking <strong>interno</strong> desta escola. O ranking da{" "}
            <strong>rede</strong> é sempre padronizado (régua institucional) e não muda com esta escolha.
          </>
        }
      />
      {somenteLeitura && (
        <p className="mt-4 rounded-xl border border-ouro-200 bg-ouro-50 p-3 text-xs text-amber-900 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-ouro-200">
          Somente a administração global da Constela pode alterar a régua da escola. Para
          solicitar uma régua personalizada, fale com o suporte.
        </p>
      )}

      <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2" role="radiogroup" aria-label="Régua de pontuação da escola">
        {opcoes.map((op) => {
          const ativo = modo === op.valor;
          return (
            <label
              key={op.valor}
              className={`flex cursor-pointer items-start gap-3.5 rounded-2xl border-2 p-4 transition-colors ${
                ativo
                  ? "border-indigo-500 bg-indigo-50/70 dark:border-indigo-400/70 dark:bg-indigo-500/10"
                  : "border-zinc-200 bg-white hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700"
              } ${somenteLeitura || salvando ? "cursor-not-allowed opacity-70" : ""}`}
            >
              <IconePastel icone={op.icone} tom={op.tom} />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2 text-[15px] font-semibold text-zinc-900 dark:text-zinc-50">
                  {op.titulo}
                  {op.valor === "institucional" && <Badge tom="destaque">Padrão</Badge>}
                </span>
                <span className="mt-1 block text-[13px] leading-snug text-zinc-500 dark:text-zinc-400">
                  {op.descricao}
                </span>
              </span>
              <input
                type="radio"
                name="perfil-scoring"
                className="mt-1 h-5 w-5 shrink-0 accent-indigo-600"
                checked={ativo}
                disabled={somenteLeitura || salvando}
                onChange={() => escolher(op.valor)}
              />
            </label>
          );
        })}
      </div>

      {modo === "institucional" && !somenteLeitura && (
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
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
        <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">Salvando e recalculando…</p>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------
 * Pesos EFETIVOS para a explicação "Como funciona?": só quando a régua lida em
 * /pontuacao/regra é a MESMA que /perfil-scoring diz estar vigente (sem isso a
 * explicação não cita números) e só das matérias do plano.
 * ----------------------------------------------------------------------- */
function pesosDaRegra(
  regra: RegraPontuacao | null,
  modo: ModoRegua | null,
  tem: (modulo: string) => boolean,
): PesosDaRegua | null {
  if (!regra || !modo || regra.perfil !== modo) return null;
  const da = (dimensao: "leitura" | "matematica") =>
    regra.dimensoes.find((d) => d.dimensao === dimensao && d.contratada && tem(dimensao))?.pesos ?? null;
  return { leitura: da("leitura"), matematica: da("matematica") };
}

/* -------------------------------------------------------------------------
 * Visão da ESCOLA (coordenador, admin de escola e Secretaria): a régua efetiva
 * em cartões, SEM editores. Decisão de produto: a escola usa o Constela; não
 * administra a matemática interna. No perfil institucional (padrão de toda
 * escola) o motor ignora as configurações locais; e as rotas de escrita são só
 * do Admin Global.
 * ----------------------------------------------------------------------- */
const TEXTO_DO_DONO =
  "Os pontos dos livros são calculados automaticamente pelo Constela considerando o nível de leitura, as características do livro e o ano escolar.";

function StatusRegua({
  escolaId,
  dados,
  erro,
  carregando,
}: {
  escolaId: number | null;
  dados: PerfilScoring | null;
  erro: unknown;
  carregando: boolean;
}) {
  if (!escolaId) {
    return (
      <span className="text-xs text-zinc-500 dark:text-zinc-400">
        Selecione uma escola no topo para ver a régua em uso.
      </span>
    );
  }
  if (carregando) {
    return <span className="text-xs text-zinc-500 dark:text-zinc-400">Verificando a régua em uso...</span>;
  }
  if (erro || !dados) {
    return (
      <span className="text-xs text-zinc-500 dark:text-zinc-400">
        Não foi possível verificar a régua em uso agora.
      </span>
    );
  }
  return dados.modo === "personalizado" ? (
    <Badge tom="alerta">Régua personalizada, autorizada pela Constela</Badge>
  ) : (
    <Badge tom="destaque">Régua Padrão Constela — a mesma para toda a rede</Badge>
  );
}

/** Textos que dependem da régua vigente. "Mesma regra para toda a rede" só é
 *  verdade na régua institucional; na personalizada a escola tem régua própria;
 *  sem saber a régua (carregando/erro), não afirma nenhuma das duas. */
function textosDaRegua(modo: ModoRegua | null): { descricao: string; rodape: string } {
  if (modo === "institucional") {
    return {
      descricao:
        "A escola consulta, acompanha e premia. O cálculo é feito pelo Constela, com a mesma regra para toda a rede.",
      rodape: "Esta regra vale para toda a rede e só a Constela pode alterá-la.",
    };
  }
  if (modo === "personalizado") {
    return {
      descricao:
        "A escola consulta, acompanha e premia. O cálculo é feito pelo Constela, com uma régua própria configurada para esta escola.",
      rodape: "Esta régua vale só para esta escola e só a Constela pode alterá-la.",
    };
  }
  return {
    descricao: "A escola consulta, acompanha e premia. O cálculo é feito pelo Constela.",
    rodape: "Só a Constela pode alterar a regra de pontuação.",
  };
}

/** Uma frase curta e verdadeira sobre a régua, ao lado do cartão de abertura. */
function Destaque({ icone, children }: { icone: LucideIcon; children: ReactNode }) {
  return (
    <li className="flex items-center gap-3 rounded-2xl border border-zinc-200/80 bg-zinc-50/70 px-3.5 py-2.5 text-sm font-medium text-zinc-700 dark:border-zinc-800 dark:bg-zinc-800/40 dark:text-zinc-200">
      <IconePastel icone={icone} tom="violeta" tamanho="sm" />
      <span>{children}</span>
    </li>
  );
}

// Como os pesos viram a nota (o mesmo que o Simulador mostra: normalizado × peso).
const RODAPE_CARTAO = "Cada critério é medido de 0 a 100 e entra na nota com o seu peso.";

/** Os cartões da régua EFETIVA (só leitura): Leitura, Matemática e Questões. */
function CartoesDaRegua({ escolaId, regra }: { escolaId: number | null; regra: ResultadoUseApi<RegraPontuacao> }) {
  const { tem } = useModulos();
  if (!escolaId) {
    return (
      <Card>
        <Vazio
          icone={School}
          titulo="Selecione uma escola no topo"
          descricao="Os pesos de cada critério aparecem para a escola escolhida."
        />
      </Card>
    );
  }
  if (regra.carregando) {
    return (
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <Card className="p-5 sm:p-6">
          <EsqueletoPesos linhas={4} />
        </Card>
        <Card className="p-5 sm:p-6">
          <EsqueletoPesos linhas={3} />
        </Card>
        <span className="sr-only">Carregando os pesos em uso...</span>
      </div>
    );
  }
  if (regra.erro || !regra.dados) {
    return (
      <Card>
        <Erro
          titulo="Não foi possível carregar os pesos em uso"
          descricao="A pontuação continua sendo calculada normalmente pelo Constela."
          aoTentar={regra.recarregar}
        />
      </Card>
    );
  }
  const da = (dimensao: "leitura" | "matematica") =>
    regra.dados?.dimensoes.find((d) => d.dimensao === dimensao && d.contratada && tem(dimensao));
  const leitura = da("leitura");
  const matematica = da("matematica");
  if (!leitura && !matematica) {
    return (
      <Card>
        <Vazio
          icone={Info}
          titulo="Nenhuma matéria no plano desta rede"
          descricao="Sem Leitura nem Matemática no plano, não há nota a compor."
        />
      </Card>
    );
  }
  const subQuestoes = leitura?.subpesos_questoes;
  // Leitura e Matemática lado a lado (mesma altura); Questões, de largura
  // inteira, embaixo. Matéria sozinha no plano ocupa a linha toda.
  return (
    <div>
      <RotuloSecao className="mb-3">Peso de cada critério na nota</RotuloSecao>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        {leitura && (
          <CartaoRegua
            {...GRUPOS.leitura}
            pesos={leitura.pesos}
            rodape={RODAPE_CARTAO}
            duasColunas={!matematica}
            className={matematica ? "" : "xl:col-span-2"}
          />
        )}
        {matematica && (
          <CartaoRegua
            {...GRUPOS.matematica}
            pesos={matematica.pesos}
            rodape={RODAPE_CARTAO}
            duasColunas={!leitura}
            className={leitura ? "" : "xl:col-span-2"}
          />
        )}
        {subQuestoes && Object.keys(subQuestoes).length > 0 && (
          <CartaoRegua {...GRUPOS.questoes} pesos={subQuestoes} duasColunas className="xl:col-span-2" />
        )}
      </div>
    </div>
  );
}

function PontuacaoDaEscola() {
  const { escolaId } = useApp();
  const { secretaria, gestor } = usePerfil();
  const { tem } = useModulos();
  const perfil = useApi<PerfilScoring>(
    escolaId ? `/escolas/${escolaId}/configuracoes/perfil-scoring` : null,
  );
  const regra = useApi<RegraPontuacao>(
    escolaId ? `/escolas/${escolaId}/configuracoes/pontuacao/regra` : null,
  );
  const modo = perfil.dados?.modo ?? null;
  const { descricao, rodape } = textosDaRegua(modo);
  const normalizacaoAuto = regra.dados?.normalizacao.modo === "auto";

  return (
    <div>
      <PageHeader titulo="Critérios de pontuação" descricao={descricao} />

      <div className="space-y-6">
        <Card className="bg-gradient-to-br from-white via-white to-indigo-50/80 p-5 dark:from-zinc-900 dark:via-zinc-900 dark:to-indigo-500/10 sm:p-7">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-start gap-4">
              <IconePastel icone={Sparkles} tom="violeta" tamanho="lg" />
              <div className="min-w-0">
                <h2 className="text-lg font-semibold text-zinc-900 dark:text-white">Como a pontuação é calculada</h2>
                <div className="mt-2">
                  <StatusRegua
                    escolaId={escolaId}
                    dados={perfil.dados}
                    erro={perfil.erro}
                    carregando={perfil.carregando}
                  />
                </div>
                <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-zinc-700 dark:text-zinc-300">
                  {TEXTO_DO_DONO}
                </p>
              </div>
            </div>
            <ul className="grid grid-cols-1 shrink-0 gap-2 sm:grid-cols-3 lg:w-80 lg:grid-cols-1">
              <Destaque icone={Gauge}>Uma nota de 0 a 100 em cada matéria</Destaque>
              {normalizacaoAuto && <Destaque icone={Users}>Comparação com os colegas da própria escola</Destaque>}
              <Destaque icone={Info}>Sem dado da plataforma, fica fora do ranking: não entra com zero</Destaque>
            </ul>
          </div>
        </Card>

        <CartoesDaRegua escolaId={escolaId} regra={regra} />

        <RegrasPremiacao mostrarLink={!secretaria} />

        {/* Nome de criança: só a gestão da escola. A Secretaria não recebe. */}
        {escolaId != null && gestor && !secretaria && <RankingAtualCriterios />}

        <ComoFuncionaPontuacao modo={modo} pesos={pesosDaRegra(regra.dados, modo, tem)} />

        <p className="text-xs text-zinc-500 dark:text-zinc-400">{rodape}</p>
      </div>
    </div>
  );
}

export default function Metricas() {
  const { usuario } = useApp();
  if (!usuario) return <Carregando />;
  // A escola (coordenador/admin de escola) e a Secretaria veem a mesma
  // explicação somente leitura; os editores são exclusivos do Admin Global.
  if (!usuario.is_global) return <PontuacaoDaEscola />;
  return <MetricasGlobal />;
}

/* -------------------------------------------------------------------------
 * Visão do ADMIN GLOBAL: régua no topo, os cartões de pesos com os editores
 * reais, os ajustes avançados em abas, as regras da premiação, o ranking atual
 * (régua salva) e a explicação. No perfil Padrão Constela nada do que se edita
 * aqui afeta as notas (AVISO_GLOBAL).
 * ----------------------------------------------------------------------- */
type AbaAvancada = "elefante" | "referencias";
type SubAbaElefante = "extras" | "niveis" | "dificuldade";

function MetricasGlobal() {
  const { escolaId } = useApp();
  const modulos = useModulos();
  // Régua vigente (salva) da escola, informada pelo PerfilScoringEditor.
  const [modoRegua, setModoRegua] = useState<ModoRegua | null>(null);
  // Sobe a cada gravação que recalcula as notas: o ranking atual é buscado de novo.
  const [versao, setVersao] = useState(0);
  const regra = useApi<RegraPontuacao>(
    escolaId ? `/escolas/${escolaId}/configuracoes/pontuacao/regra` : null,
  );
  const [aba, setAba] = useState<AbaAvancada>("elefante");
  const [subAba, setSubAba] = useState<SubAbaElefante>("extras");
  const idPainel = useId();
  const idSubPainel = useId();
  const idAvancado = useId();

  function aposGravar() {
    setVersao((v) => v + 1);
    regra.recarregar();
  }

  const selo =
    modoRegua === "personalizado" ? (
      <Badge tom="ok">Em uso nesta escola</Badge>
    ) : modoRegua === "institucional" ? (
      <Badge tom="alerta">Vale só na régua personalizada</Badge>
    ) : null;

  const abas: Array<{ valor: AbaAvancada; rotulo: string; icone: LucideIcon }> = [
    ...(modulos.leitura ? [{ valor: "elefante" as const, rotulo: "Elefante Letrado", icone: BookOpen }] : []),
    { valor: "referencias", rotulo: "Referências de Normalização", icone: Scale },
  ];
  const abaAtual = abas.some((a) => a.valor === aba) ? aba : abas[0].valor;
  const subAbas: Array<{ valor: SubAbaElefante; rotulo: string }> = [
    { valor: "extras", rotulo: "Pontos Extras" },
    { valor: "niveis", rotulo: "Níveis de dificuldade" },
    { valor: "dificuldade", rotulo: "Dificuldade por turma" },
  ];

  return (
    <div>
      <PageHeader
        titulo="Critérios de pontuação"
        descricao="Régua institucional da rede e configurações da régua personalizada. Alterações recalculam as notas automaticamente."
      />

      <div className="space-y-6">
        <PerfilScoringEditor aoMudar={setModoRegua} aoTrocar={aposGravar} />

        <div
          role="note"
          className="flex items-start gap-3 rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3 text-sm text-amber-900 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-ouro-200"
        >
          <Info size={18} aria-hidden className="mt-0.5 shrink-0" />
          <p>No perfil Padrão Constela estas configurações não afetam as notas; valem só na régua personalizada.</p>
        </div>

        <div>
          <RotuloSecao className="mb-3">Pesos da Nota</RotuloSecao>
          {/* Leitura e Matemática lado a lado (mesma altura, rodapés alinhados);
              Questões, de largura inteira, embaixo. */}
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            {modulos.leitura && (
              <PesosEditor
                namespace="elefante"
                rotulos={ROTULOS_LEITURA}
                titulo={GRUPOS.leitura.titulo}
                icone={GRUPOS.leitura.icone}
                tom={GRUPOS.leitura.tom}
                descricao={GRUPOS.leitura.subtitulo}
                selo={selo}
                aoSalvar={aposGravar}
                duasColunas={!modulos.matematica}
                className={modulos.matematica ? "" : "xl:col-span-2"}
              />
            )}
            {modulos.matematica && (
              <PesosEditor
                namespace="matific"
                rotulos={ROTULOS_MATEMATICA}
                titulo={GRUPOS.matematica.titulo}
                icone={GRUPOS.matematica.icone}
                tom={GRUPOS.matematica.tom}
                descricao={GRUPOS.matematica.subtitulo}
                selo={selo}
                aoSalvar={aposGravar}
                duasColunas={!modulos.leitura}
                className={modulos.leitura ? "" : "xl:col-span-2"}
              />
            )}
            {modulos.leitura && (
              <PesosEditor
                namespace="questoes"
                rotulos={ROTULOS_QUESTOES}
                titulo={GRUPOS.questoes.titulo}
                icone={GRUPOS.questoes.icone}
                tom={GRUPOS.questoes.tom}
                descricao="Dentro do fator Questões, o equilíbrio entre tentar e acertar."
                selo={selo}
                aoSalvar={aposGravar}
                duasColunas
                className="xl:col-span-2"
              />
            )}
          </div>
        </div>

        <section aria-labelledby={idAvancado}>
          <div className="mb-3">
            <h2 id={idAvancado} className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
              Ajustes avançados
            </h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Pontos extras, níveis e pontuação por turma do Elefante Letrado e as referências de normalização.
            </p>
          </div>
          <Abas rotulo="Ajustes avançados" itens={abas} valor={abaAtual} aoMudar={setAba} idPainel={idPainel} />
          <div
            role="tabpanel"
            id={idPainel}
            aria-label={abas.find((a) => a.valor === abaAtual)?.rotulo}
            className="mt-5"
          >
            {abaAtual === "elefante" ? (
              <>
                <Abas
                  rotulo="Ajustes do Elefante Letrado"
                  itens={subAbas}
                  valor={subAba}
                  aoMudar={setSubAba}
                  idPainel={idSubPainel}
                />
                <div
                  role="tabpanel"
                  id={idSubPainel}
                  aria-label={subAbas.find((s) => s.valor === subAba)?.rotulo}
                  className="mt-5"
                >
                  {/* Todas as configurações avançadas do Elefante ficam aqui; os
                      pesos e as questões estão nos cartões acima. */}
                  {subAba === "extras" ? (
                    <PontosExtrasEditor />
                  ) : subAba === "niveis" ? (
                    <EditorNiveis aoMudar={aposGravar} />
                  ) : (
                    <PontuacaoPorTurma />
                  )}
                </div>
              </>
            ) : (
              <ReferenciasNormalizacao />
            )}
          </div>
        </section>

        <RegrasPremiacao />

        {escolaId != null && (
          <RankingAtualCriterios
            versao={versao}
            subtitulo="Os 5 primeiros de cada matéria agora, pela nota oficial (0 a 100) do ano letivo, com a régua SALVA. Muda depois de salvar."
          />
        )}

        <ComoFuncionaPontuacao modo={modoRegua} pesos={pesosDaRegra(regra.dados, modoRegua, modulos.tem)} />
      </div>
    </div>
  );
}
