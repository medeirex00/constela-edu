/**
 * Peças COMPARTILHADAS das telas de rede (Secretaria / Admin Global).
 *
 * Vive fora de `RedeDashboard.tsx` de propósito: aquele módulo importa o Leaflet
 * no topo (mapa das escolas), então qualquer tela que reusasse o envelope da rede
 * arrastaria o mapa junto — chunk maior e jsdom quebrando nos testes. Aqui há os
 * tipos, o resolvedor de `redeId` e os cartões que o Painel da Rede (`/rede`) e o
 * Panorama da Rede (`/`, DESENHO3 §2) dividem — as METAS (progresso + cadastro) e a
 * VITRINE PÚBLICA —, sem dependência pesada (o `RedeDashboard` os reexporta).
 */
import { AlertTriangle, Copy, ExternalLink, Globe, Landmark, Power, Settings2, Target, Trash2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import {
  Botao, Card, Carregando, Confirmacao, Erro, IconePastel, Mensagem, PageHeader, Skeleton, Vazio, estiloInput,
  type TomPastel,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi, type ResultadoUseApi } from "../../hooks/useApi";
import { api } from "../../lib/api";
import { nota } from "../../lib/formato";
import { comOrigemLocal, linkSoNestaMaquina } from "../../lib/linkPublico";

export const MEDALHAS = ["🥇", "🥈", "🥉"];

/** Matéria escondida da Secretaria numa escola (grupo pequeno: 1 ou 2 alunos com dado
 *  nesta matéria). `parcial` = só os totais de todos os matriculados saíram (a média e
 *  os números de quem concorre continuam). O texto vem do backend. */
export interface BlocoOculto {
  motivo: "grupo_pequeno" | "complementar";
  texto: string;
  parcial?: boolean;
}
export type OcultoPorMateria = { leitura?: BlocoOculto | null; matematica?: BlocoOculto | null };

/** Cartão AGREGADO de uma escola da rede (nunca PII de criança). */
export interface EscolaCartao {
  escola_id: number;
  nome: string;
  cidade: string | null;
  status: string;
  /** O ano letivo em que a escola é medida (o ano ativo DELA: coorte, notas e Matific). Na
   *  virada do ano, as escolas da rede podem estar em anos diferentes. Ausente = API anterior. */
  ano_letivo?: number;
  latitude: number | null;
  longitude: number | null;
  total_turmas: number;
  total_professores: number;
  total_alunos: number;
  // DESEMPENHO (0–100): média SÓ dos alunos que têm dado da plataforma — ausência
  // de dado não vira zero. `media_geral` é a média das dimensões disponíveis.
  // `null` só para a Secretaria, na matéria escondida (ver `oculto`).
  media_geral: number | null;
  media_matific: number | null;
  media_elefante: number | null;
  dimensoes_com_dados: string[];
  alunos_com_nota_elefante: number;
  alunos_com_nota_matific: number;
  // ENGAJAMENTO/COBERTURA: quantos alunos de fato usam (conceito SEPARADO).
  alunos_com_dados: number;
  /** Entra na comparação entre escolas (= algum aluno do 1º ao 5º ano com dado das
   *  plataformas contratadas; para a Secretaria, com matéria visível). Do /dashboard. */
  comparada?: boolean;
  adocao: number;
  adocao_elefante: number;
  adocao_matific: number;
  /** Módulos contratados pela rede desta escola (SaaS). */
  modulos?: string[];
  // Totais brutos das plataformas (snapshot atual de cada aluno). `null` = escondido
  // da Secretaria (grupo pequeno).
  livros: number | null;
  tempo_leitura_min: number | null;
  atividades: number | null;
  estrelas: number | null;
  ativos_matific: number;
  ativos_elefante: number;
  livros_por_aluno: number | null;
  // Per capita por MATRÍCULA (÷ total de alunos) — critério de ranking JUSTO entre
  // escolas de tamanhos diferentes (não favorece a escola grande pelo volume bruto).
  // Arredondados para EXIBIR; para ordenar, `valorParaOrdenar` (a conta exata).
  livros_por_matricula: number | null;
  estrelas_por_matricula: number | null;
  atividades_por_matricula: number | null;
  tempo_por_matricula_min: number | null;
  // Numerador e denominador do per capita (só quem concorre, 1º–5º ano).
  alunos_premiaveis?: number;
  livros_premiaveis?: number | null;
  estrelas_premiaveis?: number | null;
  atividades_premiaveis?: number | null;
  tempo_premiaveis_min?: number | null;
  // Índice da REDE (0–1000): o per capita normalizado na régua da rede (melhor
  // escola = 1000). Comparável ENTRE escolas — ao contrário de media_* (0–100),
  // que é normalizada dentro da própria escola e serve ao ranking interno.
  pontuacao_leitura: number | null;
  pontuacao_matematica: number | null;
  pontuacao_geral: number | null;
  dimensoes_pontuadas: string[];
  // Só no Panorama Global: o mesmo índice recalculado com a coorte TODAS AS
  // REDES. O índice de rede acima não serve para comparar escolas de redes
  // diferentes (cada uma foi normalizada contra a melhor da própria rede).
  pontuacao_geral_global?: number;
  precisa_atencao: boolean;
  motivo_atencao: string | null;
  posicao?: number;
  /** Só para a Secretaria: alguma matéria saiu inteira por grupo pequeno. */
  grupo_pequeno?: boolean;
  oculto?: OcultoPorMateria;
}

/** Uma escola em destaque (`GET /redes/{id}/destaques`): só o agregado da escola. */
export interface EscolaEmDestaque {
  escola_id: number;
  nome: string;
  /** Livros por aluno (leitura) ou estrelas por aluno (matemática), arredondado como na vitrine. */
  valor: number;
}

/** A lista de UMA matéria contratada; `fora_por_protecao` = quantas saíram para a
 *  Secretaria porque o número delas fica escondido no cartão (grupo pequeno). */
export interface ListaDeDestaques {
  escolas: EscolaEmDestaque[];
  fora_por_protecao: number;
}

/** ESCOLAS EM DESTAQUE da rede (DESENHO3 §6): as mesmas da vitrine pública, pelo mesmo
 *  critério, com o `escola_id`. A matéria não contratada vem `null`. */
export interface DestaquesRede {
  modulos: string[];
  limite: number;
  k_minimo: number;
  leitura: ListaDeDestaques | null;
  matematica: ListaDeDestaques | null;
}

export interface DashboardRede {
  rede_id: number;
  /** Módulos CONTRATADOS pela rede — a interface se adapta a partir daqui. */
  modulos?: string[];
  /** Os anos letivos em que as escolas da rede estão (cada cartão traz o seu `ano_letivo`).
   *  Mais de um = a virada do ano em andamento. Ausente = API anterior. */
  anos_letivos?: number[];
  totais: {
    escolas: number;
    escolas_ativas: number;
    alunos: number;
    turmas: number;
    professores: number;
    alunos_com_dados: number;
    adocao: number;
    // `null` só para a Secretaria quando TODA escola com dado na matéria está escondida.
    media_geral: number | null;
    media_matific: number | null;
    media_elefante: number | null;
    /** Índice 0–1000 da rede (média ponderada do índice das escolas). */
    pontuacao_geral: number | null;
    escolas_em_atencao: number;
    livros: number | null;
    tempo_leitura_min: number | null;
    atividades: number | null;
    estrelas: number | null;
    ativos_matific: number;
    ativos_elefante: number;
    livros_por_aluno: number | null;
    melhor_escola: { nome: string; pontuacao_geral: number | null; media_geral: number | null } | null;
    /** Só para a Secretaria: quantas escolas ficaram fora dos totais de cada matéria. */
    grupo_pequeno?: { leitura: number; matematica: number; texto: string };
  };
  equidade: {
    // EQUIDADE é comparação ENTRE escolas: os campos `*_indice` (0–1000, per
    // capita) são os que a tela mostra. Os `*_media` (0–100) continuam no
    // payload, mas são régua INTERNA de cada escola e não comparam nada.
    gap_indice: number;
    escola_maior_indice: number;
    escola_menor_indice: number;
    escolas_abaixo_do_indice_medio: number;
    gap_media: number;
    escola_maior_media: number;
    escola_menor_media: number;
    escolas_abaixo_da_media: number;
  };
  escolas: EscolaCartao[];
  atencao: EscolaCartao[];
  /** Só para a Secretaria: escolas com alguma matéria escondida (grupo pequeno). */
  ocultas?: { escola_id: number; nome: string; grupo_pequeno: boolean; oculto: OcultoPorMateria }[];
}

/** Numerador de cada per capita do cartão (o denominador é `alunos_premiaveis`). */
const NUMERADOR_DO_PER_CAPITA: Record<string, string> = {
  livros_por_matricula: "livros_premiaveis",
  estrelas_por_matricula: "estrelas_premiaveis",
  atividades_por_matricula: "atividades_premiaveis",
  tempo_por_matricula_min: "tempo_premiaveis_min",
};

/** O valor de `chave` para ORDENAR cartões (de escola ou de rede). O per capita do cartão
 *  vem arredondado para exibir (1 casa): ordenando por ele, 12,24 e 12,2 livros por aluno
 *  empatavam e o desempate escolhia. Aqui ele é refeito pela conta exata (numerador ÷
 *  `alunos_premiaveis`), a mesma ordem do Ranking da Rede no backend. Outra chave, ou
 *  cartão sem o numerador (API anterior), = o próprio valor; ausente = 0. */
export function valorParaOrdenar(cartao: object, chave: string): number {
  const c = cartao as Record<string, unknown>;
  const total = NUMERADOR_DO_PER_CAPITA[chave] ? c[NUMERADOR_DO_PER_CAPITA[chave]] : undefined;
  const alunos = Number(c.alunos_premiaveis ?? 0);
  if (typeof total === "number" && c[chave] !== null && alunos > 0) return total / alunos;
  return Number(c[chave] ?? 0);
}

/** Os totais da rede vistos pela Secretaria deixam escolas de fora numa matéria (grupo
 *  pequeno): a tela diz isso junto dos números, com o texto do backend. */
export function AvisoTotaisParciais({ totais }: { totais: DashboardRede["totais"] }) {
  const g = totais.grupo_pequeno;
  if (!g || (g.leitura <= 0 && g.matematica <= 0)) return null;
  return (
    <p className="flex items-start gap-1.5 rounded-xl bg-ouro-50 px-3 py-2 text-xs text-ouro-800 dark:bg-ouro-400/10 dark:text-ouro-200">
      <span aria-hidden>ⓘ</span>
      <span>{g.texto}</span>
    </p>
  );
}

/** Os anos letivos da rede quando há MAIS DE UM (a virada do ano em andamento: cada escola é
 *  medida no ano letivo dela); `null` com a rede num ano só ou sem a informação (API anterior). */
export function anosLetivosMistos(dados: Pick<DashboardRede, "anos_letivos"> | null | undefined): number[] | null {
  const anos = dados?.anos_letivos ?? [];
  return anos.length > 1 ? anos : null;
}

/** Rede com escolas em anos letivos DIFERENTES (`anosLetivosMistos`): a comparação entre elas
 *  junta anos diferentes, e a tela diz isso junto dos números (o mesmo que a análise de
 *  plataformas e o Boletim dizem). `escolas` (opcional): diz quem está em cada ano — sem elas,
 *  quem chama marca o ano de cada escola na própria lista. Num ano só, nada. */
export function AvisoAnosLetivos({ anos, escolas }: { anos: number[] | null; escolas?: EscolaCartao[] }) {
  if (!anos) return null;
  const porAno = escolas
    ? anos.map((ano) => ({ ano, nomes: escolas.filter((e) => e.ano_letivo === ano).map((e) => e.nome) }))
      .filter((grupo) => grupo.nomes.length > 0)
    : [];
  return (
    <p data-testid="aviso-anos-letivos"
       className="flex items-start gap-1.5 rounded-xl bg-ouro-50 px-3 py-2 text-xs text-ouro-800 dark:bg-ouro-400/10 dark:text-ouro-200">
      <span aria-hidden>ⓘ</span>
      <span>
        As escolas da rede estão em anos letivos diferentes ({anos.join(", ")}): cada escola é medida no ano letivo
        dela, e a comparação junta anos diferentes até todas passarem para o mesmo ano.
        {porAno.map(({ ano, nomes }) => ` Em ${ano}: ${nomes.join(", ")}.`).join("")}
      </span>
    </p>
  );
}

/** Rótulo curto de uma matéria escondida numa escola: "—" com o motivo no leitor de tela
 *  e na dica. Nunca 0. */
export function ValorProtegido({ bloco }: { bloco: BlocoOculto }) {
  return (
    <span title={bloco.texto} className="text-zinc-500 dark:text-zinc-400">
      <span aria-hidden>— protegido</span>
      <span className="sr-only">{bloco.texto}</span>
    </span>
  );
}

/** Resolve a rede do usuário (Secretaria = a própria; Admin Global = a 1ª) e só
 *  então renderiza o conteúdo. Trata carregamento, a falha ao listar as redes e o
 *  caso "sem rede".
 *
 *  `titulo` (opcional): o h1 da página nesses estados intermediários — sem ele, a
 *  tela de "sem rede" ficava sem título nenhum (a11y: uma página, um h1). Quem usa
 *  o envelope numa ROTA própria (/rede, /rede/ranking) deve passá-lo. */
export function EnvolucroRede({ children, titulo, descricao }: {
  children: (redeId: number) => ReactNode;
  titulo?: string;
  descricao?: string;
}) {
  const { usuario } = useApp();
  const navegar = useNavigate();
  const redeDoUsuario = usuario?.rede_id ?? null;
  const { dados: redes, carregando, erro, recarregar } = useApi<{ id: number; nome: string }[]>(
    redeDoUsuario == null ? "/redes" : null,
  );
  const redeId = redeDoUsuario ?? redes?.[0]?.id ?? null;

  if (redeId == null) {
    const cabecalho = titulo ? <PageHeader titulo={titulo} descricao={descricao} /> : null;
    // Carregando: sem o h1 de propósito — a página de destino traz o próprio, e um
    // h1 provisório seria trocado por outro nó logo em seguida.
    if (carregando && !redes) return <Carregando texto="Carregando as redes..." />;
    // Falha ao LISTAR as redes não é "nenhuma rede": antes o erro era engolido e a
    // tela afirmava que não havia rede cadastrada.
    if (erro && !redes) {
      return (
        <>
          {cabecalho}
          <Card>
            <Erro titulo="Não foi possível carregar as redes" descricao={erro.message} aoTentar={recarregar} />
          </Card>
        </>
      );
    }
    // Admin global sem nenhuma rede: oferece criar a primeira (bootstrap).
    return (
      <div className="space-y-4">
        {cabecalho}
        <Card>
          <Vazio
            icone={Landmark}
            titulo="Nenhuma rede disponível"
            descricao={usuario?.is_global
              ? "Ainda não há redes cadastradas. Crie a primeira para habilitar o painel da rede."
              : "Sua conta não está vinculada a uma rede/Secretaria."}
            acao={usuario?.is_global ? (
              <Botao onClick={() => navegar("/rede/gerenciar")}>
                <Settings2 size={15} aria-hidden /> Gerenciar redes
              </Botao>
            ) : undefined}
          />
        </Card>
      </div>
    );
  }
  return <>{children(redeId)}</>;
}

// --- Cartões que o Painel da Rede e o Panorama da Rede dividem -----------------------------

/** A página inicial do admin global (onde ele abre o Panorama de uma rede). */
export const INICIO_GLOBAL = "Visão Global";

/** Título de cartão com o ícone em quadrado pastel DENTRO do título (o texto próprio do
 *  título continua sendo só ele — é por ele que os testes e o leitor de tela o acham).
 *  `nivel`: h2 no Painel da Rede; h3 quando o cartão fica dentro de uma seção (Panorama). */
export function TituloCartao({ icone, tom = "violeta", nivel = 2, children, className = "" }: {
  icone: LucideIcon; tom?: TomPastel; nivel?: 2 | 3; children: ReactNode; className?: string;
}) {
  const Titulo = nivel === 3 ? "h3" : "h2";
  return (
    <Titulo className={`flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 ${className}`}>
      <IconePastel icone={icone} tom={tom} tamanho="sm" />
      {children}
    </Titulo>
  );
}

export interface MetaProgresso {
  id: number;
  metrica: string;
  rotulo: string;
  sufixo: string;
  alvo: number;
  atual: number;
  progresso: number;
  atingida: boolean;
  descricao: string | null;
  escolas_atingiram: number | null;
  escolas_total: number | null;
  /** A métrica compara escolas entre si? Só as comparáveis produzem a contagem
   *  "X de Y escolas atingiram" (a média 0–100 é régua interna de cada escola). */
  comparavel?: boolean;
  /** Há dado MEDIDO? `false` = nenhum aluno aferido, ou o número está protegido da
   *  Secretaria (grupo pequeno): o backend manda `atual` 0, que NÃO é resultado. Ausente =
   *  medida (o comportamento de antes). */
  medida?: boolean;
}

/** Os indicadores que aceitam meta. `modulo`: só aparece na rede que contratou a plataforma
 *  (o cadastro não oferece meta de um produto fora do plano — quando a tela informa os módulos). */
const METRICAS_META_UI: { metrica: string; rotulo: string; modulo?: string }[] = [
  { metrica: "pontuacao_geral", rotulo: "Índice da rede (0–1000)" },
  { metrica: "adocao", rotulo: "Engajamento (adoção %)" },
  { metrica: "media_geral", rotulo: "Média geral da rede" },
  { metrica: "media_elefante", rotulo: "Leitura (Elefante Letrado)", modulo: "leitura" },
  { metrica: "media_matific", rotulo: "Matemática (Matific)", modulo: "matematica" },
  { metrica: "livros", rotulo: "Livros lidos na rede", modulo: "leitura" },
  { metrica: "atividades", rotulo: "Atividades Matific na rede", modulo: "matematica" },
];

/** A leitura das metas (`GET /redes/{id}/metas`). O progresso e o cadastro usam a MESMA
 *  leitura: salvar ou remover uma meta atualiza os dois cartões. */
export type LeituraMetas = ResultadoUseApi<MetaProgresso[]>;

/** Metas da rede com PROGRESSO real (dado real, sem número fictício). Sem meta = convite
 *  (`semMeta` diz onde cadastrar, com o nome que quem lê vê na tela ou no menu).
 *  `notaDaMetrica` (opcional, por `metrica`): uma nota curta abaixo de cada meta — o Panorama a
 *  usa para dizer de quando é cada número (as metas não seguem todas o ano letivo); sem ela, o
 *  cartão fica como sempre (o Painel da Rede não passa nada). */
export function ProgressoMetas({ leitura, titulo, semMeta, nivel = 2, notaDaMetrica }: {
  leitura: LeituraMetas; titulo: string; semMeta: ReactNode; nivel?: 2 | 3;
  notaDaMetrica?: Record<string, string>;
}) {
  const { dados: metas, erro, carregando, recarregar } = leitura;
  // A meta sem dado medido não entra na conta (nem como "não atingida"): é dita à parte.
  const medidas = metas ? metas.filter((m) => m.medida !== false) : [];
  const atingidas = medidas.filter((m) => m.atingida).length;
  const semDado = (metas?.length ?? 0) - medidas.length;
  return (
    <Card className="p-5 sm:p-6">
      <TituloCartao icone={Target} nivel={nivel} className="mb-4">{titulo}</TituloCartao>
      {/* Conclusão primeiro: quantas metas a rede já atingiu (o detalhe vem embaixo). */}
      {metas && metas.length > 0 && (
        <p className="-mt-2 mb-4 text-sm text-zinc-600 dark:text-zinc-300" data-testid="resumo-metas">
          {medidas.length > 0 ? (
            <>
              <b className="tabular-nums text-zinc-900 dark:text-white">{atingidas} de {medidas.length}</b>{" "}
              {medidas.length === 1 ? "meta atingida" : "metas atingidas"}
              {semDado > 0 && <> · <span className="tabular-nums">{semDado}</span> sem dado</>} — progresso calculado com o
              dado real.
            </>
          ) : (
            // Nenhuma medida: "0 de 0 metas atingidas" não diz nada.
            <>
              <b className="tabular-nums text-zinc-900 dark:text-white">{semDado}</b>{" "}
              {semDado === 1 ? "meta sem dado medido" : "metas sem dado medido"} ainda.
            </>
          )}
        </p>
      )}
      {carregando && !metas ? (
        <div className="space-y-3" aria-hidden>
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-2.5 w-full" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-2.5 w-full" />
        </div>
      ) : erro && !metas ? (
        // Antes o erro era engolido e a tela dizia "Nenhuma meta definida".
        <Erro titulo="Não foi possível carregar as metas" descricao={erro.message} aoTentar={recarregar} />
      ) : !metas || metas.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">{semMeta}</p>
      ) : (
        <div className="space-y-5">
          {metas.map((m) => m.medida === false ? (
            // Sem dado medido: nada de "0,0 / alvo", barra nem "0,0%" — ausência não é zero.
            <div key={m.id} data-testid="meta-sem-dado">
              <div className="mb-1.5 flex items-center justify-between gap-2 text-sm">
                <span className="min-w-0 truncate font-semibold text-zinc-800 dark:text-zinc-100"
                      title={m.descricao || m.rotulo}>
                  {m.descricao || m.rotulo}
                </span>
                <span className="shrink-0 tabular-nums text-zinc-600 dark:text-zinc-300">
                  <b className="font-semibold text-zinc-700 dark:text-zinc-200">sem dado medido</b> / {nota(m.alvo)}{m.sufixo}
                </span>
              </div>
              <div className="h-2.5 rounded-full bg-zinc-100 dark:bg-zinc-800" aria-hidden />
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                Sem aluno aferido ou número protegido (grupo pequeno).
              </p>
              <NotaDaMeta texto={notaDaMetrica?.[m.metrica]} />
            </div>
          ) : (
            <div key={m.id}>
              <div className="mb-1.5 flex items-center justify-between gap-2 text-sm">
                <span className="min-w-0 truncate font-semibold text-zinc-800 dark:text-zinc-100">
                  {m.descricao || m.rotulo}
                  {m.atingida && (
                    <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                      ✓ atingida
                    </span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums text-zinc-600 dark:text-zinc-300">
                  <b className="text-zinc-900 dark:text-white">{nota(m.atual)}{m.sufixo}</b> / {nota(m.alvo)}{m.sufixo}
                </span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800" aria-hidden>
                <div
                  className={`h-full rounded-full bg-gradient-to-r transition-all ${
                    m.atingida ? "from-emerald-400 to-emerald-600" : "from-indigo-500 to-indigo-600"}`}
                  style={{ width: `${Math.max(0, Math.min(100, m.progresso))}%` }}
                />
              </div>
              <div className="mt-1 flex justify-between gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                <span className="shrink-0 tabular-nums">{nota(m.progresso)}%</span>
                {m.escolas_total != null ? (
                  <span>{m.escolas_atingiram} de {m.escolas_total} escolas atingiram</span>
                ) : m.comparavel === false ? (
                  // Sem a contagem por escola, e dizendo por quê: confrontar a
                  // média 0–100 de escolas diferentes com o mesmo alvo compara
                  // réguas distintas (cada escola é normalizada contra si mesma).
                  <span className="truncate text-right">progresso da rede · não comparável entre escolas</span>
                ) : null}
              </div>
              <NotaDaMeta texto={notaDaMetrica?.[m.metrica]} />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** A nota de uma meta (de quando é o número, o que ele é) — só quando quem chama a passa. */
function NotaDaMeta({ texto }: { texto: string | undefined }) {
  if (!texto) return null;
  return <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400" data-testid="nota-da-meta">{texto}</p>;
}

/**
 * As METAS da rede, reaproveitáveis: o PROGRESSO (a conclusão) ao lado do CADASTRO — uma
 * leitura só para os dois. No Painel da Rede (`/rede`) com os padrões; no Panorama da Rede
 * dentro de uma seção (`nivel` 3, o cadastro com outro título para não repetir o da seção, os
 * `modulos` da rede: só metas das plataformas contratadas, e a `notaDaMetrica` de cada meta).
 */
export function MetasDaRede({ redeId, nivel = 2, tituloCadastro = "Metas da rede", modulos, notaDaMetrica }: {
  redeId: number;
  nivel?: 2 | 3;
  tituloCadastro?: string;
  /** Módulos contratados ("leitura", "matematica"); sem eles, todas as metas. */
  modulos?: string[];
  /** A nota de cada métrica no progresso (ver `ProgressoMetas`); sem ela, nada a mais. */
  notaDaMetrica?: Record<string, string>;
}) {
  const leitura = useApi<MetaProgresso[]>(`/redes/${redeId}/metas`);
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <ProgressoMetas
        leitura={leitura}
        titulo="Progresso das metas"
        nivel={nivel}
        notaDaMetrica={notaDaMetrica}
        semMeta={`Nenhuma meta definida ainda. Cadastre a primeira em “${tituloCadastro}”, nesta página — o progresso (dado real, sem número fictício) aparece aqui.`}
      />
      <GestaoMetas redeId={redeId} leitura={leitura} titulo={tituloCadastro} nivel={nivel} modulos={modulos} />
    </div>
  );
}

/** Cadastro de metas da rede — definir alvo por indicador. */
function GestaoMetas({ redeId, leitura, titulo, nivel, modulos }: {
  redeId: number; leitura: LeituraMetas; titulo: string; nivel: 2 | 3; modulos?: string[];
}) {
  const { usuario } = useApp();
  // Onde o progresso aparece: nesta página, no cartão ao lado; o admin global também o vê
  // na Visão Global, ao abrir esta rede (o nome do menu dele).
  const global = Boolean(usuario?.is_global);
  const ondeAparece = global
    ? `em “Progresso das metas”, nesta página, e na ${INICIO_GLOBAL}, ao abrir esta rede`
    : "em “Progresso das metas”, nesta página";
  const opcoes = METRICAS_META_UI.filter((o) => !o.modulo || !modulos || modulos.includes(o.modulo));
  const { dados: metas, erro, recarregar } = leitura;
  const [metrica, setMetrica] = useState(opcoes[0]?.metrica ?? "pontuacao_geral");
  const [alvo, setAlvo] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  /** A meta cujo "remover" foi pedido: abre a confirmação (antes removia num clique). */
  const [paraRemover, setParaRemover] = useState<MetaProgresso | null>(null);

  async function salvar() {
    const valor = Number(alvo);
    if (!valor || valor <= 0) return;
    setSalvando(true);
    setAviso(null);
    try {
      await api(`/redes/${redeId}/metas`, {
        method: "PUT",
        body: JSON.stringify({ metrica, alvo: valor }),
      });
      setAlvo("");
      setAviso({ tipo: "ok", texto: `Meta salva. O progresso aparece ${ondeAparece}.` });
      recarregar();
    } catch (e) {
      // Antes a falha virava um erro solto no console, sem nada na tela.
      setAviso({ tipo: "erro", texto: e instanceof Error ? e.message : "Não foi possível salvar a meta." });
    } finally {
      setSalvando(false);
    }
  }
  /** Só depois do "Remover meta" da confirmação. O resultado (ou a falha) fica na tela. */
  async function remover() {
    const meta = paraRemover;
    if (!meta) return;
    setSalvando(true);
    setAviso(null);
    try {
      await api(`/redes/${redeId}/metas/${meta.metrica}`, { method: "DELETE" });
      setAviso({ tipo: "ok", texto: `Meta “${meta.rotulo}” removida.` });
      recarregar();
    } catch (e) {
      setAviso({ tipo: "erro", texto: e instanceof Error ? e.message : "Não foi possível remover a meta." });
    } finally {
      setSalvando(false);
      setParaRemover(null);
    }
  }

  return (
    <Card className="p-5 sm:p-6">
      <TituloCartao icone={Target} nivel={nivel} className="mb-1">{titulo}</TituloCartao>
      <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
        Defina o alvo de cada indicador. O progresso é calculado com o dado real e aparece {ondeAparece}.
      </p>
      {/* Indicador, alvo e botão na MESMA linha (como antes da v2): o `w-28` do alvo
          perdia para o `w-full` do estiloInput e cada campo ia para uma linha, deixando o
          cartão bem mais alto que a Vitrine ao lado. `basis-*` manda na largura do item
          flex; o `min-w-0` tira o mínimo intrínseco do <input>. Em tela estreita quebra.
          No celular o indicador ocupa a linha toda (dividindo a linha com o alvo, o
          select cortava a escala: "Índice da rede (0–10"); alvo e "Salvar meta" descem
          juntos para a linha de baixo. Do `sm` para cima, a linha única de sempre. */}
      <div className="mb-4 flex flex-wrap items-end gap-2.5">
        <select
          aria-label="Indicador da meta"
          value={metrica}
          onChange={(e) => setMetrica(e.target.value)}
          className={`${estiloInput} min-w-[11rem] flex-1 max-sm:basis-full`}
        >
          {opcoes.map((o) => (
            <option key={o.metrica} value={o.metrica}>{o.rotulo}</option>
          ))}
        </select>
        <input
          type="number"
          min="0"
          step="0.1"
          value={alvo}
          onChange={(e) => setAlvo(e.target.value)}
          placeholder="alvo"
          aria-label="Valor-alvo da meta"
          className={`${estiloInput} min-w-0 shrink-0 basis-28 max-sm:flex-1`}
        />
        <Botao onClick={salvar} disabled={salvando || !alvo}>Salvar meta</Botao>
      </div>
      {aviso && <div className="mb-3"><Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem></div>}
      {erro && !metas ? (
        <Erro titulo="Não foi possível carregar as metas" descricao={erro.message} aoTentar={recarregar} />
      ) : metas && metas.length > 0 && (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
          {metas.map((m) => (
            <li key={m.id} className="flex items-center gap-3 py-2.5 text-sm">
              <span className="min-w-0 flex-1 truncate text-zinc-700 dark:text-zinc-200" title={m.rotulo}>{m.rotulo}</span>
              <span className="font-bold tabular-nums text-zinc-900 dark:text-white">{nota(m.alvo)}{m.sufixo}</span>
              <button
                type="button"
                onClick={() => setParaRemover(m)}
                disabled={salvando}
                aria-label={`Remover a meta ${m.rotulo}`}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-rose-600 transition-colors hover:bg-rose-50 disabled:opacity-50 max-sm:min-h-10 dark:text-rose-400 dark:hover:bg-rose-500/10"
              >
                <Trash2 size={13} aria-hidden /> remover
              </button>
            </li>
          ))}
        </ul>
      )}
      <Confirmacao
        titulo="Remover esta meta?"
        aberto={paraRemover !== null}
        aoFechar={() => setParaRemover(null)}
        aoConfirmar={() => void remover()}
        rotuloConfirmar={salvando ? "Removendo..." : "Remover meta"}
        variante="perigo"
        ocupado={salvando}
      >
        {paraRemover && (
          <p>
            A meta <strong>{paraRemover.rotulo}</strong> (alvo{" "}
            <strong className="tabular-nums">{nota(paraRemover.alvo)}{paraRemover.sufixo}</strong>) sai da rede e o
            progresso dela deixa de aparecer {ondeAparece}. Para voltar, cadastre a meta de novo.
          </p>
        )}
      </Confirmacao>
    </Card>
  );
}

/** As matérias que a vitrine publica, pelos módulos contratados (sem eles, as duas). */
function materiasDaVitrine(modulos?: string[]): string {
  if (!modulos) return "leitura e matemática";
  const leitura = modulos.includes("leitura");
  const matematica = modulos.includes("matematica");
  if (leitura && !matematica) return "leitura";
  if (matematica && !leitura) return "matemática";
  return "leitura e matemática";
}

/**
 * Vitrine pública da rede, no estilo do cartão escuro de destaque: ligar/desligar, copiar e
 * abrir o link. No Painel da Rede com os padrões; no Panorama da Rede, dentro da seção
 * "Reconhecimento público" (`nivel` 3) e com os `modulos` da rede (o texto não cita matéria
 * fora do plano).
 */
export function VitrinePublica({ redeId, nivel = 2, modulos }: { redeId: number; nivel?: 2 | 3; modulos?: string[] }) {
  const { dados, erro, recarregar } = useApi<{ ativo: boolean; token: string | null; url: string | null }>(
    comOrigemLocal(`/redes/${redeId}/publico`));
  const [ocupado, setOcupado] = useState(false);
  const [copiado, setCopiado] = useState(false);
  const [falha, setFalha] = useState("");
  const Titulo = nivel === 3 ? "h3" : "h2";
  // O link é o que o SERVIDOR devolve (ele decide a base: lib/linkPublico). A tela só informa
  // a própria origem em loopback e mostra, copia e abre o link como veio.
  const endereco = dados?.url ?? null;

  async function alternar(ativo: boolean) {
    setOcupado(true);
    setFalha("");
    try {
      await api(comOrigemLocal(`/redes/${redeId}/publico`), { method: "PUT", body: JSON.stringify({ ativo }) });
      recarregar();
    } catch (e) {
      setFalha(e instanceof Error ? e.message : "Não foi possível alterar a vitrine.");
    } finally {
      setOcupado(false);
    }
  }
  async function copiar() {
    if (!endereco) return;
    try {
      await navigator.clipboard.writeText(endereco);
      setCopiado(true);
      window.setTimeout(() => setCopiado(false), 1500);
    } catch { /* clipboard indisponível: o link fica visível para copiar à mão */ }
  }

  return (
    <section
      aria-labelledby="titulo-vitrine"
      className="relative overflow-hidden rounded-cartao bg-marinho-900 p-5 text-white shadow-cartao sm:p-6"
    >
      <span aria-hidden className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-indigo-600/30 blur-2xl" />
      <div className="relative">
        <Titulo id="titulo-vitrine" className="flex items-center gap-3 text-base font-semibold tracking-tight">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-ouro-300">
            <Globe size={16} />
          </span>
          Vitrine pública
          {dados && (
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
              dados.ativo ? "bg-emerald-400/20 text-emerald-200" : "bg-white/10 text-marinho-200"}`}>
              {dados.ativo ? "No ar" : "Desligada"}
            </span>
          )}
        </Titulo>
        {erro && !dados ? (
          // Com o GET falhando, NÃO oferecer "Ligar" como se estivesse desligada.
          <div className="mt-4 space-y-3 text-sm text-marinho-200">
            <p role="alert">Não foi possível ver o estado da vitrine: {erro.message}</p>
            <Botao variante="secundario" tamanho="sm" onClick={recarregar}>Tentar de novo</Botao>
          </div>
        ) : !dados ? (
          <div className="mt-4 space-y-2" aria-hidden>
            <Skeleton className="h-4 w-3/4 bg-white/10" />
            <Skeleton className="h-9 w-40 bg-white/10" />
          </div>
        ) : dados.ativo ? (
          <>
            <p className="mt-3 text-sm text-marinho-200">Link aberto (sem login) com as melhores escolas:</p>
            <code className="mt-2 block truncate rounded-xl bg-white/10 px-3 py-2 text-xs text-white">{endereco}</code>
            {linkSoNestaMaquina(endereco) && (
              // O link do servidor é do próprio computador (o mesmo aviso do Painel Público da escola).
              <p className="mt-2 flex items-start gap-2 text-xs leading-relaxed text-ouro-200" data-testid="aviso-link-local">
                <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0 text-ouro-300" />
                <span>
                  Este link usa localhost: só abre no computador onde o Constela está instalado. Para o telão
                  ou o celular, o servidor precisa ter configurado o endereço dele na rede (variável
                  PUBLIC_BASE_URL).
                </span>
              </p>
            )}
            <div className="mt-4 flex flex-wrap gap-2.5">
              <Botao variante="ambar" onClick={copiar}>
                <Copy size={15} aria-hidden /> {copiado ? "Copiado!" : "Copiar link"}
              </Botao>
              {/* Antes só havia "Copiar link": para conferir a vitrine era preciso colar o
                  link noutra aba. */}
              {endereco && (
                <a
                  href={endereco}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 rounded-xl border border-white/20 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-white/10"
                >
                  <ExternalLink size={15} aria-hidden /> Abrir vitrine
                </a>
              )}
              <button
                type="button"
                onClick={() => alternar(false)}
                disabled={ocupado}
                className="inline-flex items-center gap-2 rounded-xl border border-white/20 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-white/10 disabled:opacity-60"
              >
                <Power size={15} aria-hidden /> Desligar
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="mt-3 text-sm text-marinho-200">
              Publique um link aberto com as 5 melhores escolas em {materiasDaVitrine(modulos)} — sem nome de criança.
            </p>
            <div className="mt-4">
              <Botao variante="ambar" onClick={() => alternar(true)} disabled={ocupado}>Ligar vitrine pública</Botao>
            </div>
          </>
        )}
        {falha && <p role="alert" className="mt-3 rounded-xl bg-rose-500/20 px-3 py-2 text-sm text-rose-100">{falha}</p>}
      </div>
    </section>
  );
}
