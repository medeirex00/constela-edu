/**
 * Suporte — a ajuda do Constela DENTRO do sistema (antes o item do menu só
 * abria a pasta dos guias no Google Drive).
 *
 * Para o perfil de quem abre: o guia em PDF do perfil, as dúvidas mais comuns,
 * a regra da nota COMO O MOTOR A APLICA nesta escola (lida de
 * `GET /configuracoes/pontuacao/regra` — nenhum número da fórmula mora aqui), o
 * exemplo interativo da conta (o mesmo da Pontuação, calculado pelo servidor) e
 * o que fazer quando os dados parecem desatualizados. Os parâmetros da fórmula
 * são da gestão (admin, coordenação, Secretaria); o professor vê a explicação
 * sem os números.
 */
import {
  ArrowRight,
  BookOpen,
  Calculator,
  ChevronDown,
  CircleHelp,
  ExternalLink,
  FileText,
  LifeBuoy,
  RefreshCw,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { COR_TOM, metaDoCriterio } from "../components/CriteriosVisuais";
import ExemploPontuacao from "../components/ExemploPontuacao";
import {
  Card,
  Carregando,
  ESTILOS_BOTAO,
  IconePastel,
  Mensagem,
  PageHeader,
  TAMANHOS_BOTAO,
  type TomPastel,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
// Versões da regra em linguagem de gente (fonte única com o "Como funciona?" dos
// Critérios); o identificador técnico fica só na dica (title), para quem precisa conferir.
import { nomeDaVersaoDaRegra } from "../lib/regraPontuacao";
import {
  FAQ_PROFESSOR,
  SINCRONIZACAO_LEITURA,
  faqDaGestao,
  faqDaSecretaria,
  sincronizacaoDaGestao,
  type Pergunta,
} from "./suporteConteudo";

// Guias em PDF: pastas da pasta "Constela Edu" do Google Drive (a mesma que o
// item Suporte abria). Link de PASTA, não de arquivo: o guia atualizado entra no
// lugar do anterior sem mudar o link.
const DRIVE = "https://drive.google.com/drive/folders/";
export const PASTAS_GUIAS = {
  todos: `${DRIVE}1kbDGPRSsh7TOb6nk6smwXNyAJPkySk-i`,
  coordenacao: `${DRIVE}166WOuY7cdPfZc2_9-AMPpOUgfHGxJADg`,
  professor: `${DRIVE}16rRU9rSohX2Ky4sjvM0mknQPrTBcl4Ge`,
  secretaria: `${DRIVE}1MugoOUvDf9G2rOiUjQOpv9zagqbYp6yf`,
} as const;

/** A regra da nota desta escola, como o servidor a devolve. */
export interface RegraPontuacao {
  perfil: "institucional" | "personalizado";
  versoes: { composicao: string; dificuldade: string; dificuldade_da_rede: string };
  dimensoes: Array<{
    dimensao: "leitura" | "matematica";
    plataforma: string;
    contratada: boolean;
    pesos: Record<string, number>;
    subpesos_questoes?: Record<string, number>;
  }>;
  nota_geral: { pesos: Record<string, number> };
  normalizacao: {
    modo: "auto" | "manual";
    percentil_referencia: number;
    minimo_alunos_percentil: number;
    indicadores_volume: string[];
  };
}

// Nome de cada indicador como a tela "Como funciona?" já o chama.
const NOME_INDICADOR: Record<string, string> = {
  livros: "livros únicos",
  dificuldade: "dificuldade dos livros",
  questoes: "questões",
  tempo: "tempo de leitura",
  tentativas: "questões respondidas",
  acertos: "acertos",
  atividades: "atividades finalizadas",
  media: "pontuação média",
  estrelas: "estrelas",
  elefante: "Leitura (Elefante Letrado)",
  matific: "Matemática (Matific)",
};

const NOME_DIMENSAO: Record<string, string> = {
  leitura: "Leitura (Elefante Letrado)",
  matematica: "Matemática (Matific)",
};

const formatoPeso = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

// Cor de cada peso: a MESMA da tela Critérios (/metricas) para o mesmo critério — a cor
// vem do critério (META_CRITERIOS → COR_TOM, D22), não da posição na lista. Antes era
// pela posição: Dificuldade saía teal aqui e rosa lá, Questões laranja aqui e azul lá, e
// o teal (cor da Matemática) caía num critério de Leitura.
// Parcela que É uma matéria (os pesos da Nota Geral): a cor vem da matéria — Leitura
// #6C5CE7 e Matemática #0D9488 (D18), como nos ícones (elefante/matific já estão em
// META_CRITERIOS com essas cores; leitura/matematica são o nome da dimensão).
const COR_MATERIA: Record<string, string> = {
  leitura: COR_TOM.violeta.barra,
  matematica: COR_TOM.teal.barra,
};

const corDoPeso = (chave: string) => COR_MATERIA[chave] ?? COR_TOM[metaDoCriterio(chave).tom].barra;

/** Os pesos COMO A API DEVOLVE: barra colorida (decorativa) + legenda com o número.
 *  O número fica só na legenda (um elemento por peso) — a barra não repete texto. */
function Pesos({ pesos }: { pesos: Record<string, number> }) {
  const itens = Object.entries(pesos);
  const total = itens.reduce((acc, [, v]) => acc + (Number(v) || 0), 0) || 1;
  return (
    <div className="mt-2">
      <div aria-hidden className="flex h-3 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
        {itens.map(([chave, valor]) => (
          <span key={chave} className={`h-full ${corDoPeso(chave)}`}
                style={{ width: `${(Math.max(0, Number(valor) || 0) / total) * 100}%` }} />
        ))}
      </div>
      <ul className="mt-3 space-y-1.5">
        {itens.map(([chave, valor]) => (
          <li key={chave} className="flex items-center justify-between gap-4 tabular-nums">
            <span className="flex min-w-0 items-center gap-2">
              <span aria-hidden className={`h-2.5 w-2.5 shrink-0 rounded-full ${corDoPeso(chave)}`} />
              <span className="truncate" title={NOME_INDICADOR[chave] ?? chave}>{NOME_INDICADOR[chave] ?? chave}</span>
            </span>
            <span className="font-semibold text-zinc-900 dark:text-zinc-50">{formatoPeso.format(valor)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Paragrafo({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5 rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/40">
      <p className="font-semibold text-zinc-900 dark:text-zinc-100">{titulo}</p>
      {children}
    </div>
  );
}

function RegraDaNota({ escolaId, daSecretaria }: { escolaId: number; daSecretaria: boolean }) {
  const { dados, erro, carregando } = useApi<RegraPontuacao>(
    `/escolas/${escolaId}/configuracoes/pontuacao/regra`);
  if (carregando) return <Carregando texto="Carregando a regra desta escola..." />;
  if (erro || !dados) {
    return <Mensagem tipo="erro">Não foi possível carregar a regra da nota agora. Tente de novo em instantes.</Mensagem>;
  }
  const { normalizacao: n } = dados;
  const volume = n.indicadores_volume.map((i) => NOME_INDICADOR[i] ?? i).join(", ");
  const contratadas = dados.dimensoes.filter((d) => d.contratada).length;
  return (
    <div className="space-y-4 text-sm text-zinc-700 dark:text-zinc-300">
      <p>
        Cada aluno tem uma nota de 0 a 100 <strong>por matéria</strong>, calculada pelo Constela a
        partir do que as plataformas enviam, a cada atualização dos dados. A nota de uma matéria só usa
        dados da plataforma dela.
        {dados.perfil === "institucional"
          ? " Esta escola usa a régua da rede: os mesmos pesos e as mesmas regras de todas as escolas."
          : " Esta escola usa uma régua própria, autorizada pela administração do Constela; por isso os pesos abaixo podem ser diferentes dos de outras escolas."}
      </p>
      {daSecretaria && dados.perfil === "personalizado" && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Nos números da rede, as notas desta escola são recalculadas com a régua da rede (os mesmos pesos
          e regras de todas as escolas), para que a configuração local não mude os números da rede. Para
          comparar escolas, use o Índice.
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {dados.dimensoes.map((d) => (
          <div key={d.dimensao} className="rounded-2xl border border-zinc-200 p-4 dark:border-zinc-800">
            <p className="flex items-center gap-2.5 font-semibold text-zinc-900 dark:text-zinc-100">
              <IconePastel icone={d.dimensao === "leitura" ? BookOpen : Calculator}
                           tom={d.dimensao === "leitura" ? "violeta" : "teal"} tamanho="sm" />
              {NOME_DIMENSAO[d.dimensao]}
            </p>
            {d.contratada ? (
              <>
                <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">Quanto cada indicador pesa:</p>
                <Pesos pesos={d.pesos} />
                {d.subpesos_questoes && (
                  <>
                    <p className="mt-4 text-xs text-zinc-500 dark:text-zinc-400">Dentro de “questões”:</p>
                    <Pesos pesos={d.subpesos_questoes} />
                  </>
                )}
              </>
            ) : (
              <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
                Esta matéria não faz parte do plano da rede: não há nota dela.
              </p>
            )}
          </div>
        ))}
      </div>

      <Paragrafo titulo="Como o aluno é comparado">
        {n.modo === "auto" ? (
          <p>
            Cada indicador vira um número de 0 a 100 comparando o aluno com os colegas da{" "}
            <strong>própria escola</strong>. Quando a matéria tem pelo menos {n.minimo_alunos_percentil}{" "}
            alunos com dado, o 100 é o valor de quem está no percentil {n.percentil_referencia} — assim um
            único aluno muito acima dos outros não define a régua sozinho — e, em {volume}, cada unidade a
            mais vale um pouco menos que a anterior: dobrar a quantidade não dobra a nota. Com menos alunos,
            o 100 é o maior valor da escola e a conta é proporcional.
          </p>
        ) : (
          <p>
            Esta escola usa referências fixas definidas pela administração do Constela (modo manual): o 100
            de cada indicador é o valor dessa referência.
          </p>
        )}
      </Paragrafo>

      <Paragrafo titulo="Quando falta dado">
        <p>
          Aluno sem dado de uma plataforma fica <strong>fora do ranking daquela matéria</strong> — não
          entra com zero. Quem já tem dado da plataforma, mas ainda não fez nada, entra com 0 e aparece no
          fim da lista daquela matéria.
          {dados.perfil === "institucional"
            ? " Livro sem nível de dificuldade conhecido conta como livro lido, mas não soma pontos de dificuldade."
            : null}
        </p>
      </Paragrafo>

      {contratadas > 1 && (
        <Paragrafo titulo="E a Nota Geral?">
          <p>
            A Nota Geral junta as matérias com dado do aluno, com estes pesos (quem tem só uma matéria
            fica com a nota dela). Ela ainda ordena o Ranking Geral, o certificado “Geral” e as vitrines;
            quem não tem dado de nenhuma plataforma aparece com 0,0 na coluna Geral.
          </p>
          <Pesos pesos={dados.nota_geral.pesos} />
        </Paragrafo>
      )}

      {/* O identificador técnico da versão fica só na dica (title), para quem precisa
          conferir com a equipe; na tela, a versão em linguagem comum. */}
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Versão da regra:{" "}
        <span title={`Identificador da versão: ${dados.versoes.composicao}`}>
          {nomeDaVersaoDaRegra(dados.versoes.composicao)}
        </span>
        ;{" "}
        <span title={`Identificador da versão: ${dados.versoes.dificuldade}`}>
          {nomeDaVersaoDaRegra(dados.versoes.dificuldade)}
        </span>
        .
      </p>
    </div>
  );
}

/** Para o professor: a explicação, sem os parâmetros da fórmula (que são da
 *  gestão desde a Onda 2). */
function ExplicacaoSemNumeros() {
  return (
    <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
      <p>
        Cada aluno tem uma nota de 0 a 100 <strong>por matéria</strong> (Leitura e Matemática),
        calculada pelo Constela a partir do que as plataformas enviam, comparando o aluno com os
        colegas da própria escola.
      </p>
      <p>
        Aluno sem dado de uma plataforma fica fora do ranking daquela matéria e aparece com “—”, não
        com zero. A aba Geral do Ranking usa a Nota Geral, que junta as matérias com dado do aluno;
        quem ainda não tem dado de nenhuma plataforma aparece ali com 0,0. Os pesos e a régua de cada
        matéria ficam com a coordenação, em Regras de pontuação › Critérios; só a administração do
        Constela os altera.
      </p>
    </div>
  );
}

/** Dúvidas em acordeão NATIVO (<details>): fechado por padrão, teclado e leitor de
 *  tela de graça, e a resposta continua no DOM (busca do navegador, testes). */
function ListaPerguntas({ perguntas }: { perguntas: Pergunta[] }) {
  return (
    <div className="divide-y divide-zinc-100 overflow-hidden rounded-2xl border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
      {perguntas.map((p) => (
        <details key={p.pergunta} className="group bg-white open:bg-zinc-50/60 dark:bg-zinc-900 dark:open:bg-zinc-800/40">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3.5 text-sm font-semibold text-zinc-900 transition-colors hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300 [&::-webkit-details-marker]:hidden">
            <span>{p.pergunta}</span>
            <ChevronDown size={16} aria-hidden className="shrink-0 text-zinc-400 transition-transform group-open:rotate-180" />
          </summary>
          <p className="px-4 pb-4 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{p.resposta}</p>
        </details>
      ))}
    </div>
  );
}

/** Seção da central de ajuda: cartão com ícone pastel e título (h2). */
function Secao({ id, icone, tom = "violeta", titulo, descricao, children }: {
  id: string; icone: LucideIcon; tom?: TomPastel; titulo: string; descricao?: string; children: ReactNode;
}) {
  return (
    <Card className="scroll-mt-24 p-5 sm:p-6">
      <section aria-labelledby={`${id}-titulo`} id={id}>
        <div className="mb-4 flex items-start gap-3">
          <IconePastel icone={icone} tom={tom} />
          <div className="min-w-0">
            <h2 id={`${id}-titulo`} className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-white">{titulo}</h2>
            {descricao && <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
          </div>
        </div>
        {children}
      </section>
    </Card>
  );
}

const ATALHOS: { id: string; titulo: string; texto: string; icone: LucideIcon; tom: TomPastel }[] = [
  { id: "ajuda-guia", titulo: "Guia em PDF", texto: "O passo a passo de cada tela", icone: FileText, tom: "violeta" },
  { id: "ajuda-duvidas", titulo: "Dúvidas comuns", texto: "Respostas rápidas do dia a dia", icone: CircleHelp, tom: "azul" },
  { id: "ajuda-nota", titulo: "Como a nota funciona", texto: "A régua da escola", icone: Calculator, tom: "teal" },
  { id: "ajuda-dados", titulo: "Dados em dia?", texto: "Quando parecem parados", icone: RefreshCw, tom: "ambar" },
  { id: "ajuda-contato", titulo: "Ainda com dúvida", texto: "Quem procurar", icone: LifeBuoy, tom: "rosa" },
];

/** Leva à seção (rolagem respeitando reduced-motion) e põe o foco no título dela. */
function irPara(id: string) {
  const alvo = document.getElementById(id);
  if (!alvo) return;
  const reduzir = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  alvo.scrollIntoView?.({ behavior: reduzir ? "auto" : "smooth", block: "start" });
  const titulo = document.getElementById(`${id}-titulo`);
  if (titulo) {
    titulo.setAttribute("tabindex", "-1");
    titulo.focus({ preventScroll: true });
  }
}

export default function Suporte() {
  const { escolaId } = useApp();
  const { global, secretaria, gestor, admin } = usePerfil();
  const { modulos } = useModulos();
  // Perfil para o conteúdo: o Admin Global vê o da gestão (opera escolas).
  const perfil = secretaria ? "secretaria" : gestor || global ? "coordenacao" : "professor";
  // Secretaria: as plataformas com o nome que o menu dela dá (só as contratadas).
  const perguntas = perfil === "secretaria" ? faqDaSecretaria(modulos)
    : perfil === "coordenacao" ? faqDaGestao({ admin, global }) : FAQ_PROFESSOR;
  const guia = perfil === "secretaria" ? "Guia da Secretaria"
    : perfil === "coordenacao" ? "Guia da Coordenação" : "Guia do Professor";

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Suporte"
        descricao="Respostas rápidas, como a nota é calculada e o guia completo do seu perfil."
      />

      {/* Atalhos da central de ajuda: levam à seção (rolagem + foco no título).
          Cinco numa linha só a partir de 1536 px; antes disso, 3 + 2 (grade de 6),
          porque em ~180 px por cartão os títulos e as legendas quebravam palavra a
          palavra. */}
      <nav aria-label="Atalhos do suporte" className="grid grid-cols-2 gap-3 sm:grid-cols-6 min-[1440px]:grid-cols-5">
        {ATALHOS.map((a, i) => (
          <button
            key={a.id}
            type="button"
            onClick={() => irPara(a.id)}
            className={`group flex flex-col items-start gap-3 ${i < 3 ? "sm:col-span-2" : "sm:col-span-3"} min-[1440px]:col-span-1 rounded-cartao border border-zinc-200/80 bg-white p-4 text-left shadow-cartao transition-all hover:-translate-y-0.5 hover:border-indigo-200 motion-reduce:transform-none dark:border-zinc-800 dark:bg-zinc-900`}
          >
            <IconePastel icone={a.icone} tom={a.tom} />
            <span>
              <span className="block text-sm font-semibold text-zinc-900 dark:text-white">{a.titulo}</span>
              <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">{a.texto}</span>
            </span>
            <ArrowRight size={15} aria-hidden className="mt-auto text-zinc-400 transition-colors group-hover:text-indigo-600" />
          </button>
        ))}
      </nav>

      {/* Guia em PDF: o cartão escuro de destaque, com a ação principal em âmbar. */}
      <section
        id="ajuda-guia"
        aria-labelledby="ajuda-guia-titulo"
        className="relative scroll-mt-24 overflow-hidden rounded-cartao bg-marinho-900 p-6 text-white shadow-cartao sm:p-7"
      >
        <span aria-hidden className="pointer-events-none absolute -right-12 -top-12 h-48 w-48 rounded-full bg-indigo-600/30 blur-2xl" />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-4">
            <span aria-hidden className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-white/10 text-ouro-300">
              <FileText size={22} />
            </span>
            <div className="min-w-0">
              <h2 id="ajuda-guia-titulo" className="text-lg font-semibold tracking-tight">Guia completo em PDF</h2>
              <p className="mt-1 max-w-xl text-sm text-marinho-200">
                O <strong className="text-white">{guia}</strong> explica cada tela passo a passo. Ele fica numa pasta do Google
                Drive e abre em outra aba.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2.5 lg:shrink-0">
            <a href={PASTAS_GUIAS[perfil]} target="_blank" rel="noopener noreferrer"
               className={`inline-flex items-center justify-center font-semibold transition-colors sm:whitespace-nowrap ${TAMANHOS_BOTAO.md} ${ESTILOS_BOTAO.ambar}`}>
              Abrir o {guia}
              <ExternalLink size={15} aria-hidden />
            </a>
            <a href={PASTAS_GUIAS.todos} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center justify-center rounded-xl border border-white/25 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-white/10 sm:whitespace-nowrap">
              Ver todos os guias
            </a>
          </div>
        </div>
      </section>

      <Secao id="ajuda-duvidas" icone={CircleHelp} tom="azul" titulo="Perguntas frequentes"
             descricao="Toque numa pergunta para ver a resposta.">
        <ListaPerguntas perguntas={perguntas} />
      </Secao>

      <Secao id="ajuda-nota" icone={Calculator} tom="teal" titulo="Como a nota é calculada"
             descricao={perfil === "professor" ? undefined : "A regra que o Constela aplica na escola selecionada."}>
        {perfil === "professor" ? (
          <ExplicacaoSemNumeros />
        ) : escolaId != null ? (
          <div className="space-y-6">
            <RegraDaNota escolaId={escolaId} daSecretaria={perfil === "secretaria"} />
            {/* O exemplo da conta é das telas de gestão (o servidor libera
                admin, coordenação e Secretaria). */}
            <ExemploPontuacao escolaId={escolaId} />
          </div>
        ) : (
          // Desde a v2 o seletor não fica no topo: é o cartão do fim do menu lateral, que
          // se chama "Contexto" para a Secretaria (com "Toda a Rede Municipal") e "Escola"
          // para os demais — o mesmo texto do Dashboard e do FAQ da Secretaria. Nas outras
          // telas, a escola escolhida pela Secretaria abre a ficha dela (DESENHO3 §1); aqui no
          // Suporte o cartão só grava o contexto (Layout: LEEM_O_CONTEXTO_NO_LUGAR) e a regra
          // aparece nesta mesma página.
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {perfil === "secretaria"
              ? "Escolha uma escola no cartão Contexto, no fim do menu lateral (no tablet e no celular, dentro do menu), para ver aqui a regra da nota dela."
              : "Escolha uma escola no cartão Escola, no fim do menu lateral, para ver a regra da nota dela."}
          </p>
        )}
      </Secao>

      <Secao id="ajuda-dados" icone={RefreshCw} tom="ambar" titulo="Os dados estão atualizados?">
        <ListaPerguntas perguntas={perfil === "coordenacao" ? sincronizacaoDaGestao({ admin, global }) : SINCRONIZACAO_LEITURA} />
        {perfil === "coordenacao" && (
          <p className="mt-4">
            <Link to="/sincronizacao"
                  className={`inline-flex items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.md} ${ESTILOS_BOTAO.primario}`}>
              Abrir Integrações
            </Link>
          </p>
        )}
      </Secao>

      <Secao id="ajuda-contato" icone={LifeBuoy} tom="rosa" titulo="Ainda precisa de ajuda?">
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {perfil === "professor"
            ? "Fale com a coordenação da sua escola: ela acompanha as integrações e as revisões de identidade."
            : perfil === "coordenacao"
              ? "Fale com a Secretaria de Educação ou com a equipe que implantou o Constela na rede. Conte o que tentou, a tela e o horário — isso agiliza a resposta."
              : "Fale com a equipe que implantou o Constela na rede. Conte o que tentou, a tela e o horário — isso agiliza a resposta."}
        </p>
        <p className="mt-3 flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          <BookOpen size={14} aria-hidden /> O guia em PDF tem o passo a passo de cada tela.
        </p>
      </Secao>
    </div>
  );
}
