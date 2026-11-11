/**
 * Análises avançadas — `/rede/analise` (Secretaria e admin global; guarda `RotaRede`).
 * É a ÁREA TÉCNICA da rede: as leituras exploratórias e estatísticas para quem quer
 * aprofundar, fora do fluxo principal (Panorama, Avaliações externas, Elefante e Matific,
 * Comparar escolas e Relatórios têm páginas próprias, em linguagem simples). A faixa do
 * topo diz isso; termos técnicos (coorte, Spearman, TPS...) só aparecem aqui. Três abas,
 * com os nomes dos itens do menu (grupo "Análises avançadas"):
 *
 *   (sem ?ver=)    Diagnóstico exploratório — por escola, avaliação oficial × uso das
 *                  plataformas em LP e MT, níveis, sinais, critérios e o CSV
 *                  (`?ver=diagnostico`, dos links de antes, abre a mesma aba);
 *   ?ver=relacao   Relação com as plataformas — calculável ou os motivos, sempre lado a lado;
 *   ?ver=escola    Análise detalhada por escola — indicadores oficiais e plataformas por série.
 *
 * Cada aba só monta (e só lê da API) quando está aberta. Os FILTROS (período, escola,
 * série) moram só aqui; cada bloco diz quais valem para ele.
 *
 * A antiga "Visão geral" saiu, sem perder nada e sem repetir nada: destaques oficiais, avisos
 * do catálogo, Estimativa × sem registro e a metodologia foram para Avaliações externas;
 * cartões, cobertura e lacunas por série, para Elefante e Matific; as escolas por nível ficam
 * no Diagnóstico (chips); "o que dá para relacionar hoje" abre a aba Relação.
 *
 * LINKS ANTIGOS (favoritos, atalhos, telas de antes): as abas que viraram páginas próprias
 * redirecionam, com `replace` (o voltar do navegador não cai de novo no redirecionamento),
 * SEMPRE levando o `rede=` do admin global:
 *   ?ver=visao                 → "/" (o Panorama da Secretaria) ou `/rede/visao` (global);
 *   ?ver=avaliacoes|indicador  → `/rede/avaliacoes-externas`, com os mesmos parâmetros do
 *                                indicador (indicador, etapa, componente, visão, edição...);
 *   ?ver=plataformas           → `/rede/plataformas`, com a escola e a série (o recorte da
 *                                evolução lá);
 *   ?ver=relatorios            → `/rede/relatorios`.
 *
 * O filtro Escola e o seletor de contexto do menu lateral (AppContext) são o MESMO: mudar um
 * muda o outro. Para a Secretaria, "Toda a rede" é o "Toda a Rede Municipal" do menu
 * (escolaId nulo). Ao abrir, um link com `?escola=` manda; sem ele, a Secretaria chega na
 * escola que já estava no menu. O admin global (cujo menu sempre tem uma escola) abre em
 * "Toda a rede"; escolher uma escola aqui a leva para o menu, e trocar a escola do menu traz
 * o filtro junto.
 *
 * A fonte documental fica fora daqui: em "Detalhes e fontes" e em "Fontes e arquivos
 * oficiais" (`/rede/avaliacoes`). Só leitura: nada aqui grava.
 */
import { FileSearch, FlaskConical, Landmark, School, ScatterChart, Settings2, Stethoscope } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useId, useRef } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { AbasLigadas } from "../../components/AbasLigadas";
import { DatasDoPeriodo } from "../../components/SeletorPeriodo";
import { Botao, Card, Carregando, Erro, Mensagem, PageHeader, Vazio, estiloInput } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { usePerfil } from "../../hooks/usePerfil";
import Diagnostico from "./Diagnostico";
import PorEscola from "./PorEscola";
import RelacaoPlataformas from "./RelacaoPlataformas";
import {
  FiltrosAplicados, OpcoesDePeriodo, Seletor, TEXTO_PERIODO_DA_REDE, useApiExata, usePeriodoDaAnalise,
} from "./comum";
import { porNome, rotuloSerie } from "./formato";
import type { RespostaIndicadoresRede } from "./tipos";

/** O título da página (h1): o nome do grupo do menu. */
export const TITULO_ANALISES_AVANCADAS = "Análises avançadas";

/** As abas. Os rótulos são os dos itens do menu (a trilha usa o rótulo do item daquele `ver`). */
export const ABAS_ANALISE = [
  { chave: "diagnostico", rotulo: "Diagnóstico exploratório" },
  { chave: "relacao", rotulo: "Relação com as plataformas" },
  { chave: "escola", rotulo: "Análise detalhada por escola" },
] as const;
export type AbaAnalise = (typeof ABAS_ANALISE)[number]["chave"];
type Aba = AbaAnalise;
/** Os mesmos ícones dos itens do menu (sem repetição). */
const ICONE_ABA: Record<Aba, LucideIcon> = {
  diagnostico: Stethoscope,
  relacao: ScatterChart,
  escola: School,
};

/** A aba de um `?ver=`; sem valor, desconhecido ou `diagnostico` = Diagnóstico exploratório. */
export function abaDaUrl(ver: string | null): AbaAnalise {
  return ver === "relacao" || ver === "escola" ? ver : "diagnostico";
}

/** O que um link antigo de "Avaliações externas"/"Por indicador" levava (o detalhe do indicador). */
const PARAMETROS_DO_INDICADOR = [
  "indicador", "etapa", "componente", "abrangencia", "de", "ate", "visao", "edicao", "escola",
] as const;
/** O recorte que a antiga aba "Elefante e Matific" levava na URL (a página nova lê os mesmos). */
const RECORTE_DAS_PLATAFORMAS = ["escola", "serie"] as const;

/**
 * Para onde vai um link antigo (`?ver=` de uma aba que virou página própria) — ou null, se a
 * aba continua aqui. O `rede=` vai sempre junto (a rede que o admin global escolheu); os
 * links de indicador levam também os parâmetros dele, para abrir o MESMO detalhe.
 */
export function destinoDoLinkAntigo(params: URLSearchParams, global: boolean): string | null {
  const com = (caminho: string, chaves: readonly string[] = []) => {
    const q = new URLSearchParams();
    for (const chave of [...chaves, "rede"]) {
      const valor = params.get(chave);
      if (valor) q.set(chave, valor);
    }
    const texto = q.toString();
    return texto ? `${caminho}?${texto}` : caminho;
  };
  switch (params.get("ver")) {
    case "visao": return global ? com("/rede/visao") : com("/");
    case "avaliacoes":
    case "indicador": return com("/rede/avaliacoes-externas", PARAMETROS_DO_INDICADOR);
    // A escola e a série da aba antiga são o recorte da evolução na página nova (mesmos nomes).
    case "plataformas": return com("/rede/plataformas", RECORTE_DAS_PLATAFORMAS);
    // A série vale para a planilha das plataformas dos Relatórios (o mesmo nome na URL).
    case "relatorios": return com("/rede/relatorios", ["serie"]);
    default: return null;
  }
}

const SERIES = [1, 2, 3, 4, 5];

const numeroOuNull = (v: string | null): number | null => {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Destino de um atalho para outra página da rede: o admin global leva a rede aberta junto. */
function comRede(caminho: string, redeId: number, global: boolean): string {
  return global ? `${caminho}?rede=${redeId}` : caminho;
}

/**
 * A faixa fixa da área técnica: diz o que esta página é (e o que não é) e devolve quem caiu
 * aqui por engano às páginas do dia a dia.
 */
function FaixaAreaTecnica({ redeId, global }: { redeId: number; global: boolean }) {
  const link = "font-semibold text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300";
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-indigo-200 bg-indigo-50/70 px-4 py-3.5 text-sm text-zinc-800 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-zinc-100"
         data-testid="faixa-area-tecnica">
      <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white text-indigo-600 shadow-sm dark:bg-zinc-900/70 dark:text-indigo-300">
        <FlaskConical size={16} />
      </span>
      <div className="min-w-0 space-y-1 break-words">
        <p>
          <b>Área técnica:</b> análises exploratórias e estatísticas para quem quer aprofundar. Não são conclusões
          sobre as escolas.
        </p>
        <p className="text-xs text-zinc-600 dark:text-zinc-300">
          O resumo para o dia a dia está no{" "}
          <Link to={global ? comRede("/rede/visao", redeId, true) : "/"} className={link}>
            {global ? "Visão da rede" : "Panorama da Rede"}
          </Link>
          , em{" "}
          <Link to={comRede("/rede/avaliacoes-externas", redeId, global)} className={link}>Avaliações externas</Link>
          {" "}e em{" "}
          <Link to={comRede("/rede/escolas", redeId, global)} className={link}>Escolas</Link>.
        </p>
      </div>
    </div>
  );
}

function FiltrosCompartilhados({ base, escolaId, serie, atualizar, aoMudarEscola }: {
  base: RespostaIndicadoresRede;
  escolaId: number | null;
  serie: number | null;
  atualizar: (m: Record<string, string | null>) => void;
  aoMudarEscola: (v: string) => void;
}) {
  const { secretaria } = usePerfil();
  return (
    <Card className="space-y-3 p-5" >
      <div className="flex flex-wrap items-end gap-4" data-testid="filtros-compartilhados">
        <CampoPeriodo />
        <Seletor rotulo="Escola" valor={escolaId == null ? "" : String(escolaId)} aoMudar={aoMudarEscola}>
          <option value="">Toda a rede</option>
          {porNome(base.escolas).map((e) => (
            <option key={e.id} value={e.id}>
              {e.nome}{e.pendencia === "sem_codigo_inep" ? " (sem código INEP)" : ""}
            </option>
          ))}
        </Seletor>
        <Seletor rotulo="Série" valor={serie == null ? "" : String(serie)}
                 aoMudar={(v) => atualizar({ serie: v || null })}>
          <option value="">1º ao 5º ano</option>
          {SERIES.map((s) => <option key={s} value={s}>{rotuloSerie(s)}</option>)}
        </Seletor>
      </div>
      <FiltrosAplicados testId="onde-valem-os-filtros">
        O período vale para o lado das plataformas (Elefante e Matific); as avaliações oficiais têm edição própria.
        A série vale para a análise detalhada por escola. A escola abre a análise detalhada dela e a linha dela no
        diagnóstico — e é a mesma do seletor de escola do menu lateral.
        {secretaria && <> {TEXTO_PERIODO_DA_REDE}</>}
      </FiltrosAplicados>
    </Card>
  );
}

/**
 * O PERÍODO global do sistema (o mesmo do SeletorPeriodo: mesmos presets, mesmo
 * `definirPeriodo`, as mesmas datas do personalizado e do dia) no MESMO campo dos
 * vizinhos Escola e Série — rótulo ligado ao <select>, estiloInput e a seta nativa.
 * A pílula do SeletorPeriodo, com o ícone e o chevron escondidos para caber aqui,
 * ficava sem seta (não parecia uma lista), com um recuo vazio e 4 px abaixo dos vizinhos.
 */
function CampoPeriodo() {
  const { definirPeriodo } = useApp();
  // A Secretaria: só o ano letivo ou um bimestre inteiro (o período global de outra tela que não
  // vale aqui aparece — e é pedido — como o ano letivo).
  const periodo = usePeriodoDaAnalise();
  // `basis-*` manda na largura do item flex (o `w-full` do estiloInput venceria um `w-*`).
  const estiloData = `${estiloInput} min-w-0 shrink-0 basis-44 dark:[color-scheme:dark]`;
  return (
    <>
      <Seletor rotulo="Período" valor={periodo.preset}
               aoMudar={(v) => definirPeriodo({ ...periodo, preset: v })}>
        <OpcoesDePeriodo />
      </Seletor>
      <DatasDoPeriodo valor={periodo} onChange={definirPeriodo} estilo={estiloData}
                      classeAte="pb-3 text-sm text-zinc-500 dark:text-zinc-400" />
    </>
  );
}

function Painel({ redeId, redesDoGlobal }: {
  redeId: number;
  redesDoGlobal: { id: number; nome: string }[] | null;
}) {
  const [params, setParams] = useSearchParams();
  const { escolaId: escolaContexto, selecionarEscola } = useApp();
  const { secretaria, global } = usePerfil();
  const idBase = useId();
  const atualizar = useCallback((mudancas: Record<string, string | null>) => {
    const prox = new URLSearchParams(params);
    for (const [k, v] of Object.entries(mudancas)) {
      if (v == null || v === "") prox.delete(k);
      else prox.set(k, v);
    }
    setParams(prox, { replace: true });
  }, [params, setParams]);

  const base = useApiExata<RespostaIndicadoresRede>(`/redes/${redeId}/analise/indicadores`);
  const dados = base.dados && base.dados.rede.id === redeId ? base.dados : null;

  const ver: Aba = abaDaUrl(params.get("ver"));
  const escolaUrl = numeroOuNull(params.get("escola"));
  // Só vale escola DESTA rede (um link antigo de outra rede não filtra nada).
  const daRede = (id: number | null): id is number =>
    id != null && dados != null && dados.escolas.some((e) => e.id === id);
  const escolaId = daRede(escolaUrl) ? escolaUrl : null;
  const serieUrl = numeroOuNull(params.get("serie"));
  const serie = serieUrl != null && SERIES.includes(serieUrl) ? serieUrl : null;
  const idAba = (chave: string) => `${idBase}-aba-${chave}`;
  const idPainel = `${idBase}-painel`;

  // --- Filtro Escola ↔ seletor de contexto do menu lateral (o MESMO) ------------------
  // Os efeitos leem os valores mais recentes por ref (rodam só quando o gatilho muda).
  const atual = useRef({ escolaUrl, escolaContexto, atualizar, selecionarEscola, secretaria, daRede });
  atual.current = { escolaUrl, escolaContexto, atualizar, selecionarEscola, secretaria, daRede };
  // 1) Ao abrir (quando o catálogo da rede chega): o link (?escola=) manda; sem ele, a
  //    Secretaria herda a escola do menu. O global abre em "Toda a rede".
  const abriu = useRef(false);
  useEffect(() => {
    if (!dados || abriu.current) return;
    abriu.current = true;
    const a = atual.current;
    if (a.daRede(a.escolaUrl)) {
      if (a.escolaContexto !== a.escolaUrl) a.selecionarEscola(a.escolaUrl);
    } else if (a.secretaria && a.daRede(a.escolaContexto)) {
      a.atualizar({ escola: String(a.escolaContexto) });
    }
  }, [dados]);
  // 2) Trocar a escola no MENU traz o filtro junto (para a Secretaria, "Toda a Rede
  //    Municipal" = "Toda a rede"; para o global, só escola desta rede).
  const contextoAnterior = useRef(escolaContexto);
  useEffect(() => {
    if (contextoAnterior.current === escolaContexto) return;
    contextoAnterior.current = escolaContexto;
    const a = atual.current;
    if (!abriu.current) return;               // o passo 1 ainda vai decidir
    const alvo = a.daRede(escolaContexto) ? escolaContexto : null;
    if (alvo === a.escolaUrl) return;
    if (a.secretaria || alvo != null) a.atualizar({ escola: alvo == null ? null : String(alvo) });
  }, [escolaContexto]);
  // 2b) Os itens do grupo "Análises avançadas" são abas desta página (`/rede/analise` e
  //     `?ver=X`). Clicados DENTRO dela, levam os filtros da URL (Layout: destinoDoItem); mas
  //     a pesquisa global e os atalhos chegam sem o `?escola=`: a página continua montada, a
  //     URL perde a escola e o filtro cairia em "Toda a rede" com o menu ainda na escola. Para
  //     a Secretaria os dois andam sempre juntos (o passo 3 troca os dois de uma vez), então
  //     URL sem escola com o menu numa escola desta rede só acontece por um link assim: a
  //     escola do menu volta para a URL. O global fica de fora (o menu dele nunca fica vazio,
  //     e "Toda a rede" com uma escola no menu é escolha legítima dele).
  useEffect(() => {
    const a = atual.current;
    if (!abriu.current || !a.secretaria || a.escolaUrl != null || !a.daRede(a.escolaContexto)) return;
    a.atualizar({ escola: String(a.escolaContexto) });
  }, [escolaUrl]);
  // 3) Trocar a escola AQUI leva o menu junto (o global nunca fica sem escola no menu).
  function aoMudarEscola(v: string) {
    atualizar({ escola: v || null });
    const id = numeroOuNull(v);
    if (secretaria) selecionarEscola(id);
    else if (id != null) selecionarEscola(id);
  }

  function trocarAba(chave: Aba) {
    atualizar({ ver: chave === "diagnostico" ? null : chave });
  }

  const seletorRede = redesDoGlobal && redesDoGlobal.length > 1 && (
    <Seletor rotulo="Rede analisada" valor={String(redeId)}
             aoMudar={(v) => atualizar({ rede: v, escola: null })}>
      {porNome(redesDoGlobal).map((r) => <option key={r.id} value={r.id}>{r.nome}</option>)}
    </Seletor>
  );

  return (
    <div className="min-w-0 space-y-5">
      <PageHeader
        titulo={TITULO_ANALISES_AVANCADAS}
        descricao="O diagnóstico exploratório, a relação entre as avaliações oficiais e as plataformas e a análise detalhada de cada escola — cada leitura com os critérios e as limitações dela."
        acoes={seletorRede || undefined}
      />
      {dados && (
        <p className="-mt-3 flex items-center gap-2 text-sm font-medium text-zinc-600 dark:text-zinc-300" data-testid="analise-rede-nome">
          <Landmark size={15} aria-hidden className="shrink-0 text-indigo-500" />{dados.rede.nome}
        </p>
      )}

      <FaixaAreaTecnica redeId={redeId} global={global} />

      {/* Controle segmentado (setas, Home e End trocam de aba e levam o foco). */}
      <AbasLigadas
        itens={ABAS_ANALISE.map((a) => ({ valor: a.chave, rotulo: a.rotulo, icone: ICONE_ABA[a.chave] }))}
        valor={ver}
        aoMudar={trocarAba}
        rotulo="Partes da análise"
        idDaAba={idAba}
        idPainel={idPainel}
      />

      {dados && (
        <FiltrosCompartilhados base={dados} escolaId={escolaId} serie={serie} atualizar={atualizar}
                               aoMudarEscola={aoMudarEscola} />
      )}
      {/* O painel existe sempre (o aria-controls das abas aponta para ele), com o
          carregamento ou o erro dentro. */}
      <div role="tabpanel" id={idPainel} aria-labelledby={idAba(ver)} className="min-w-0">
        {base.erro && !dados ? (
          <Mensagem tipo="erro">Não foi possível carregar a análise da rede: {base.erro.message}</Mensagem>
        ) : !dados ? (
          <Carregando texto="Carregando a análise da rede..." />
        ) : (
          <>
            {ver === "diagnostico" && <Diagnostico redeId={redeId} base={dados} escolaId={escolaId} />}
            {ver === "relacao" && (
              <RelacaoPlataformas redeId={redeId} base={dados} params={params} atualizar={atualizar} />
            )}
            {ver === "escola" && <PorEscola base={dados} escolaId={escolaId} serie={serie} />}
          </>
        )}
      </div>

      <p className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-400">
        <FileSearch size={14} className="shrink-0 text-indigo-500" aria-hidden />
        <span>
          Cada número oficial com a cobertura e o arquivo de origem:{" "}
          <Link to="/rede/avaliacoes" className="font-medium text-indigo-700 hover:underline dark:text-indigo-400">
            {global ? "importações e fontes" : "fontes e arquivos oficiais"}
          </Link>.
        </span>
      </p>
    </div>
  );
}

/** A página das abas (o link antigo já foi desviado em `AnaliseEducacional`). */
function AnalisesAvancadas() {
  const { usuario } = useApp();
  const { global } = usePerfil();
  const navegar = useNavigate();
  const [params] = useSearchParams();
  // O admin global escolhe a rede (GET /redes devolve todas); a Secretaria usa a dela.
  const { dados: redes, carregando, erro } = useApi<{ id: number; nome: string }[]>(global ? "/redes" : null);
  const redeUrl = numeroOuNull(params.get("rede"));
  const redeId = global
    ? (redes?.find((r) => r.id === redeUrl)?.id
      ?? redes?.find((r) => r.id === usuario?.rede_id)?.id
      ?? (redes ? porNome(redes)[0]?.id : undefined)
      ?? null)
    : usuario?.rede_id ?? null;

  if (redeId == null) {
    // Sessão ainda abrindo: não dá para dizer que "não há rede" (o perfil decide).
    if (!usuario) return <Carregando texto="Carregando..." />;
    // Sem a lista ainda (inclusive no 1º render, antes do pedido sair) é carregando:
    // um h1 de "sem rede" aqui seria trocado logo depois pelo do painel.
    if (global && (carregando || (!redes && !erro))) return <Carregando texto="Carregando as redes..." />;
    // Erro e "sem rede" também têm o h1 da página (uma página, um título), como
    // o EnvolucroRede das outras páginas da rede.
    if (global && erro) {
      return (
        <div className="space-y-4">
          <PageHeader titulo={TITULO_ANALISES_AVANCADAS} />
          <Card className="p-2"><Erro titulo="Não foi possível carregar as redes" descricao={erro.message} /></Card>
        </div>
      );
    }
    // No mesmo cartão das telas irmãs (/rede, /rede/ranking): o estado vazio solto sobre
    // a lavanda sumia (o círculo pastel do ícone quase não aparecia) e o botão ficava
    // longe do texto. Agora o botão é a ação do próprio estado vazio.
    return (
      <div className="space-y-4">
        <PageHeader titulo={TITULO_ANALISES_AVANCADAS} />
        <Card>
          <Vazio
            icone={Landmark}
            titulo="Nenhuma rede disponível"
            descricao={global
              ? "Ainda não há redes cadastradas. Crie a primeira para habilitar a análise da rede."
              : "Sua conta não está vinculada a uma rede/Secretaria."}
            acao={global ? (
              <Botao onClick={() => navegar("/rede/gerenciar")}>
                <Settings2 size={15} aria-hidden /> Gerenciar redes
              </Botao>
            ) : undefined}
          />
        </Card>
      </div>
    );
  }
  return <Painel key={redeId} redeId={redeId} redesDoGlobal={global ? redes : null} />;
}

export default function AnaliseEducacional() {
  const { usuario } = useApp();
  const { global } = usePerfil();
  const [params] = useSearchParams();
  const destino = destinoDoLinkAntigo(params, global);
  if (destino) {
    // O destino do `?ver=visao` depende do perfil: espera a sessão dizer quem é.
    if (!usuario) return <Carregando texto="Carregando..." />;
    return <Navigate to={destino} replace />;
  }
  return <AnalisesAvancadas />;
}
