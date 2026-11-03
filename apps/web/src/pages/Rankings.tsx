/**
 * Ranking Geral — tela única com dois níveis de seleção, sem trocar de página:
 *
 *   CATEGORIA  → Alunos | Turmas | Escolas
 *   (Alunos)   → Geral | Leitura | Matemática | Evolução
 *
 * Cada visão é a MESMA tela de antes (filtros de período/turma/série/turno,
 * paginação e comportamento preservados), embutida aqui sem o próprio
 * cabeçalho. A opção fica sincronizada na URL (`?ver=leitura`, `?ver=turmas`,
 * `?ver=escolas`), o que mantém atalhos, redirects (/evolucao, /ranking-leitura)
 * e links diretos funcionando.
 *
 * Identidade visual v2 (referência "Ranking"): cabeçalho com o período e a data
 * do dado no subtítulo e as AÇÕES à direita — cada aba leva os próprios botões
 * (Exportar lista, Gerar certificados, Baixar cartaz) para o espaço de ações do
 * cabeçalho (`alvoAcoes`, por portal), porque é ela quem tem a lista exibida.
 * Abas segmentadas violeta com ícone e a plataforma ao lado ("Leitura · Elefante
 * Letrado"; o complemento é só visual, o nome acessível continua "Leitura").
 *
 * Quem vê o quê (a permissão real continua sendo o backend; aqui só se
 * organiza o que cada perfil já podia abrir):
 *   - professor                → Alunos;
 *   - coordenador/admin        → Alunos, Turmas;
 *   - Admin Global COM escola  → Alunos, Turmas, Escolas;
 *   - Admin Global sem escola  → Escolas;
 *   - Secretaria               → Escolas (os rankings nominais de aluno ficam
 *                                vazios de propósito para a rede — bloqueio de
 *                                PII — então nem os mostramos).
 *
 * ESCOLAS: `RankingRede` traz o PRÓPRIO cabeçalho ("🏆 Ranking da Rede"). Na
 * categoria Escolas esta tela NÃO renderiza o "Ranking Geral" por cima — só a
 * navegação de categorias seguida da página da rede, para haver um único
 * título de página. `/rede/ranking` é roteada para esta mesma tela (dentro da
 * guarda de rede) e, sem `?ver=`, abre em Escolas.
 *
 * Celular (< 640 px): os botões do cabeçalho viram uma coluna de mesma largura, as
 * abas de tipo uma grade 2 × 2 de colunas iguais e as de categoria uma linha de
 * colunas iguais (sem pílulas soltas de larguras diferentes). No desktop nada muda.
 *
 * Acessibilidade: as abas de categoria e de tipo apontam (`aria-controls`) para
 * o painel que controlam, e cada painel (`role="tabpanel"`) é rotulado pela aba
 * ativa (`aria-labelledby`).
 *
 * "Escolar" (dados escolares próprios, em construção) saiu do seletor;
 * `RankingEscolar.tsx` fica no repositório, reservado, sem uso.
 */
import { lazy, Suspense, useId, useState, type ReactNode } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { BookOpen, Calculator, LayoutGrid, School, TrendingUp, Trophy, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  ACOES_CELULAR,
  AbasRanking,
  DescricaoRanking,
  rotuloDoPeriodo,
} from "../components/RankingUi";
import { Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import type { Dimensao } from "../lib/types";
import RankingEvolucao from "./RankingEvolucao";
import RankingGeral from "./RankingGeral";
import RankingLeitura from "./RankingLeitura";
import RankingMatematica from "./RankingMatematica";
import RankingTurmas from "./RankingTurmas";

// Ranking de ESCOLAS (perfis de rede) — a MESMA página da rede (uma só
// implementação), carregada sob demanda.
const RankingRede = lazy(() => import("./rede/RankingRede"));

const CATEGORIAS: readonly { chave: "alunos" | "turmas" | "escolas"; rotulo: string; icone: LucideIcon }[] = [
  { chave: "alunos", rotulo: "Alunos", icone: Users },
  { chave: "turmas", rotulo: "Turmas", icone: LayoutGrid },
  { chave: "escolas", rotulo: "Escolas", icone: School },
];
type Categoria = (typeof CATEGORIAS)[number]["chave"];

// Sub-visões de ALUNOS: uma por FONTE de dados — Geral (ordem única), Leitura
// (Elefante Letrado), Matemática (Matific) e Evolução.
const VISOES_ALUNOS = [
  { chave: "geral", rotulo: "Geral", modulo: null, icone: Trophy, detalhe: undefined },
  { chave: "leitura", rotulo: "Leitura", modulo: "leitura", icone: BookOpen, detalhe: "Elefante Letrado" },
  { chave: "matematica", rotulo: "Matemática", modulo: "matematica", icone: Calculator, detalhe: "Matific" },
  { chave: "evolucao", rotulo: "Evolução", modulo: null, icone: TrendingUp, detalhe: undefined },
] as const;
type VisaoAlunos = (typeof VISOES_ALUNOS)[number]["chave"];

/** Tudo o que `?ver=` pode valer. */
type Ver = VisaoAlunos | "turmas" | "escolas";

export default function Rankings() {
  const { global, secretaria, gestor } = usePerfil();
  const { escolaId, periodo } = useApp();
  const { tem } = useModulos();
  const [params, setParams] = useSearchParams();
  // Espaço de ações do cabeçalho: a aba aberta põe ali os botões dela.
  const [alvoAcoes, setAlvoAcoes] = useState<HTMLElement | null>(null);
  // /rede/ranking é o atalho "Ranking de Escolas" (menu do Admin Global e
  // "Ver ranking completo" do Painel da Rede): sem `?ver=` abre em Escolas.
  const { pathname } = useLocation();
  const atalhoDaRede = pathname === "/rede/ranking";
  // Ids estáveis das abas e painéis (aria-controls / aria-labelledby).
  const idBase = useId();
  const idAbaCategoria = (chave: string) => `${idBase}-categoria-${chave}`;
  const idPainelCategoria = `${idBase}-painel-categoria`;
  const idAbaTipo = (chave: string) => `${idBase}-tipo-${chave}`;
  const idPainelTipo = `${idBase}-painel-tipo`;

  // Categorias disponíveis para este perfil (ver nota no topo).
  const podeAlunos = !secretaria && escolaId != null;
  const podeTurmas = podeAlunos && gestor;
  const podeEscolas = global || secretaria;
  const categorias = CATEGORIAS.filter((c) =>
    c.chave === "alunos" ? podeAlunos : c.chave === "turmas" ? podeTurmas : podeEscolas);

  // Perfis de REDE sem escola selecionada (Secretaria; Admin Global em "Toda a
  // Rede"): o Ranking Geral É o ranking de escolas — a página já traz o próprio
  // cabeçalho (🏆 Ranking da Rede).
  if (!podeAlunos) {
    if (!podeEscolas) {
      return <Vazio icone={Trophy} titulo="Nenhuma escola selecionada" descricao="Escolha uma escola para ver os rankings." />;
    }
    return (
      <Suspense fallback={<Carregando texto="Carregando o ranking da rede..." />}>
        <RankingRede />
      </Suspense>
    );
  }

  // Abas de PRODUTO só existem para quem contratou o módulo (SaaS).
  const visoesAlunos = VISOES_ALUNOS.filter((v) => v.modulo === null || tem(v.modulo));

  // A URL é a ÚNICA fonte da verdade: `visao` é derivada de `?ver=` a cada
  // render. Assim atalhos/deep-links que mudam só a query (Alt+2/Alt+3, o link
  // "Ranking Geral" da barra) trocam a aba mesmo com a tela já montada — o React
  // Router NÃO remonta a rota quando muda apenas a query string.
  //
  // A visão precisa EXISTIR para este perfil/plano: um deep-link ?ver=leitura
  // para uma escola sem o módulo (ou ?ver=turmas para um professor) cairia numa
  // tela em branco — volta para "geral" em vez de renderizar nada.
  const ver = params.get("ver") ?? (atalhoDaRede ? "escolas" : null);
  let categoria: Categoria = "alunos";
  let visao: Ver = "geral";
  if (ver === "turmas" && podeTurmas) {
    categoria = "turmas";
    visao = "turmas";
  } else if (ver === "escolas" && podeEscolas) {
    categoria = "escolas";
    visao = "escolas";
  } else if (visoesAlunos.some((v) => v.chave === ver)) {
    visao = ver as VisaoAlunos;
  }

  function trocar(nova: Ver) {
    // Reflete a escolha na URL (deep-link/atalho) sem empilhar histórico; o
    // render seguinte lê `visao` da própria URL.
    const prox = new URLSearchParams(params);
    if (nova === "geral" && !atalhoDaRede) prox.delete("ver");
    else prox.set("ver", nova);
    setParams(prox, { replace: true });
  }

  const comNavCategorias = categorias.length > 1;

  // 1º nível: CATEGORIA (só quando há mais de uma para o perfil). Pílula clara: é
  // a escolha secundária; a aba violeta é o tipo de ranking.
  const navCategorias = comNavCategorias && (
    <div className="mb-4 flex flex-wrap items-center gap-2.5">
      <span aria-hidden className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
        Classificar
      </span>
      <AbasRanking
        itens={categorias.map((c) => ({ valor: c.chave, rotulo: c.rotulo, icone: c.icone }))}
        valor={categoria}
        aoMudar={(c) => trocar(c === "alunos" ? "geral" : c)}
        rotulo="Categoria do ranking"
        idAba={idAbaCategoria}
        idPainel={idPainelCategoria}
        variante="secundaria"
        celular="linha"
      />
    </div>
  );

  // Painel da categoria: só é `tabpanel` quando existe a aba que o rotula.
  const painelCategoria = (conteudo: ReactNode) => comNavCategorias
    ? (
      <div role="tabpanel" id={idPainelCategoria} aria-labelledby={idAbaCategoria(categoria)}>
        {conteudo}
      </div>
    )
    : conteudo;

  // ESCOLAS: sem o cabeçalho "Ranking Geral" — a página da rede tem o dela.
  if (categoria === "escolas") {
    return (
      <div>
        {navCategorias}
        {painelCategoria(
          <Suspense fallback={<Carregando texto="Carregando o ranking da rede..." />}>
            <RankingRede />
          </Suspense>,
        )}
      </div>
    );
  }

  // Subtítulo: o período que vale para a aba aberta e a data do dado. O Geral e o
  // de Turmas são sempre do ano letivo (notas acumuladas); a Matemática fora do
  // ano letivo é o placar consultado ao vivo no Matific.
  const contratadas = (["leitura", "matematica"] as Dimensao[]).filter((d) => tem(d));
  const rotuloPeriodo = rotuloDoPeriodo(periodo);
  const descricao =
    visao === "geral" ? (
      <DescricaoRanking periodo="Ano letivo · classificação acumulada" dimensoes={contratadas} />
    ) : visao === "turmas" ? (
      <DescricaoRanking periodo="Ano letivo · média das notas oficiais" dimensoes={contratadas} />
    ) : visao === "leitura" ? (
      <DescricaoRanking periodo={rotuloPeriodo} dimensoes={["leitura"]} />
    ) : visao === "matematica" ? (
      <DescricaoRanking
        periodo={rotuloPeriodo}
        dimensoes={["matematica"]}
        aoVivo={periodo.preset !== "ano_letivo"}
      />
    ) : (
      <DescricaoRanking periodo={rotuloPeriodo} dimensoes={contratadas} />
    );

  return (
    <div>
      <PageHeader
        // Em /rede/ranking (Alunos ou Turmas da escola escolhida) o título é o do item
        // do menu e da trilha ("Ranking da Rede"); em /ranking, "Ranking Geral".
        titulo={atalhoDaRede ? "Ranking da Rede" : "Ranking Geral"}
        descricao={descricao}
        acoes={<div ref={setAlvoAcoes} className={`flex flex-wrap items-center gap-2.5 ${ACOES_CELULAR}`} />}
      />

      {navCategorias}

      {painelCategoria(
        categoria === "alunos" ? (
          <>
            {/* 2º nível: TIPO de ranking de alunos (uma aba por fonte de dados). */}
            <AbasRanking
              itens={visoesAlunos.map((v) => ({
                valor: v.chave, rotulo: v.rotulo, icone: v.icone, detalhe: v.detalhe,
              }))}
              valor={visao as VisaoAlunos}
              aoMudar={(v) => trocar(v)}
              rotulo="Tipo de ranking"
              idAba={idAbaTipo}
              idPainel={idPainelTipo}
              celular="grade"
              className="mb-5"
            />

            <div role="tabpanel" id={idPainelTipo} aria-labelledby={idAbaTipo(visao)}>
              {visao === "geral" && <RankingGeral embutido alvoAcoes={alvoAcoes} />}
              {visao === "leitura" && tem("leitura") && <RankingLeitura embutido alvoAcoes={alvoAcoes} />}
              {visao === "matematica" && tem("matematica") && <RankingMatematica embutido alvoAcoes={alvoAcoes} />}
              {visao === "evolucao" && <RankingEvolucao embutido alvoAcoes={alvoAcoes} />}
            </div>
          </>
        ) : (
          <RankingTurmas embutido alvoAcoes={alvoAcoes} />
        ),
      )}
    </div>
  );
}
