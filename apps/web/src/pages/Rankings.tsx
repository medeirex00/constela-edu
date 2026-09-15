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
 * Acessibilidade: as abas de categoria e de tipo apontam (`aria-controls`) para
 * o painel que controlam, e cada painel (`role="tabpanel"`) é rotulado pela aba
 * ativa (`aria-labelledby`).
 *
 * "Escolar" (dados escolares próprios, em construção) saiu do seletor;
 * `RankingEscolar.tsx` fica no repositório, reservado, sem uso.
 */
import { lazy, Suspense, useId, type ReactNode } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import RankingEvolucao from "./RankingEvolucao";
import RankingGeral from "./RankingGeral";
import RankingLeitura from "./RankingLeitura";
import RankingMatematica from "./RankingMatematica";
import RankingTurmas from "./RankingTurmas";

// Ranking de ESCOLAS (perfis de rede) — a MESMA página da rede (uma só
// implementação), carregada sob demanda.
const RankingRede = lazy(() => import("./rede/RankingRede"));

const CATEGORIAS = [
  { chave: "alunos", rotulo: "Alunos" },
  { chave: "turmas", rotulo: "Turmas" },
  { chave: "escolas", rotulo: "Escolas" },
] as const;
type Categoria = (typeof CATEGORIAS)[number]["chave"];

// Sub-visões de ALUNOS: uma por FONTE de dados — Geral (ordem única), Leitura
// (Elefante Letrado), Matemática (Matific) e Evolução.
const VISOES_ALUNOS = [
  { chave: "geral", rotulo: "Geral", modulo: null },
  { chave: "leitura", rotulo: "Leitura", modulo: "leitura" },
  { chave: "matematica", rotulo: "Matemática", modulo: "matematica" },
  { chave: "evolucao", rotulo: "Evolução", modulo: null },
] as const;
type VisaoAlunos = (typeof VISOES_ALUNOS)[number]["chave"];

/** Tudo o que `?ver=` pode valer. */
type Ver = VisaoAlunos | "turmas" | "escolas";

const estiloAba = (ativa: boolean) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    ativa
      ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
      : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
  }`;

export default function Rankings() {
  const { global, secretaria, gestor } = usePerfil();
  const { escolaId } = useApp();
  const { tem } = useModulos();
  const [params, setParams] = useSearchParams();
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
      return <Vazio titulo="Nenhuma escola selecionada" descricao="Escolha uma escola para ver os rankings." />;
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

  // 1º nível: CATEGORIA (só quando há mais de uma para o perfil).
  const navCategorias = comNavCategorias && (
    <div
      role="tablist"
      aria-label="Categoria do ranking"
      className="mb-3 inline-flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60"
    >
      {categorias.map((c) => (
        <button
          key={c.chave}
          id={idAbaCategoria(c.chave)}
          type="button"
          role="tab"
          aria-selected={categoria === c.chave}
          aria-controls={idPainelCategoria}
          onClick={() => trocar(c.chave === "alunos" ? "geral" : c.chave)}
          className={estiloAba(categoria === c.chave)}
        >
          {c.rotulo}
        </button>
      ))}
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

  return (
    <div>
      <PageHeader
        titulo="Ranking Geral"
        descricao="Escolha o que classificar: alunos, turmas ou escolas. Os filtros de período, turma, série e turno ficam dentro de cada ranking."
      />

      {navCategorias}

      {painelCategoria(
        categoria === "alunos" ? (
          <>
            {/* 2º nível: TIPO de ranking de alunos (uma aba por fonte de dados). */}
            <div
              role="tablist"
              aria-label="Tipo de ranking"
              className="mb-4 flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60 sm:inline-flex"
            >
              {visoesAlunos.map((v) => (
                <button
                  key={v.chave}
                  id={idAbaTipo(v.chave)}
                  type="button"
                  role="tab"
                  aria-selected={visao === v.chave}
                  aria-controls={idPainelTipo}
                  onClick={() => trocar(v.chave)}
                  className={estiloAba(visao === v.chave)}
                >
                  {v.rotulo}
                </button>
              ))}
            </div>

            <div role="tabpanel" id={idPainelTipo} aria-labelledby={idAbaTipo(visao)}>
              {visao === "geral" && <RankingGeral embutido />}
              {visao === "leitura" && tem("leitura") && <RankingLeitura embutido />}
              {visao === "matematica" && tem("matematica") && <RankingMatematica embutido />}
              {visao === "evolucao" && <RankingEvolucao embutido />}
            </div>
          </>
        ) : (
          <RankingTurmas embutido />
        ),
      )}
    </div>
  );
}
