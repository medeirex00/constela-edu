/**
 * Vitrine PÚBLICA da Secretaria (sem login) — as MELHORES ESCOLAS da rede em
 * leitura e matemática, no tema "noite Constela" (mesmo do painel da escola),
 * mas com TOP 5 ESCOLAS (não top 3 alunos). Só agregado por escola: nunca
 * expõe nome de criança. Decisão de produto do dono.
 *
 * Responsiva por CSS (classes `vitrine-*` em index.css): no celular os cartões
 * ficam um embaixo do outro e o nome da escola aparece INTEIRO (quebra linha);
 * numa TV/projetor em paisagem os dois cartões ficam lado a lado e tudo escala
 * pela altura da tela para as 5 + 5 escolas caberem sem rolar — do projetor
 * 800×600 e do painel 854×480 a 3840×2160 (4K); num totem (tela grande em
 * retrato) fica 1 coluna larga com a tipografia escalada pela largura.
 */
import { BookOpen, Calculator } from "lucide-react";
import { useEffect, useId } from "react";
import type { LucideIcon } from "lucide-react";
import { useParams } from "react-router-dom";

import { FundoConstela, MEDALHAS, OURO, useTelaPublica } from "../../components/FundoConstela";
import { useApi } from "../../hooks/useApi";
import { useSemIndexacao } from "../../hooks/useSemIndexacao";
import { ApiError } from "../../lib/api";
import { nota } from "../../lib/formato";

interface TopEscola {
  nome: string;
  valor: number;
  /** Colocação calculada pelo BACKEND (fonte da verdade, a mesma do Ranking da Rede). */
  posicao?: number;
}
interface PainelPublico {
  rede_nome: string;
  top_leitura: TopEscola[];
  top_matematica: TopEscola[];
  // O que o número significa. A vitrine ordena por PER CAPITA (livros ÷ alunos,
  // estrelas ÷ alunos) — comparável entre escolas de tamanhos diferentes. Pela
  // média 0–100 (régua interna de cada escola), o município coroaria em praça
  // pública a escola de distribuição mais homogênea, que pode ser a que menos lê.
  unidade_leitura?: string;
  unidade_matematica?: string;
  /** Módulos que a rede contratou ("leitura", "matematica"). Ausente = backend
   *  anterior ao campo: a tela mostra os dois cartões, como antes. */
  modulos?: string[];
}

const FONTE = "Poppins, Inter, sans-serif";

/** Falha que se resolve sozinha (rede, timeout, sobrecarga, servidor) — a mesma
 *  definição do telão da escola. 404 = vitrine desligada / token inválido. */
function ehTransitorio(erro: ApiError | null): boolean {
  return !(erro instanceof ApiError)
    || erro.status === 0 || erro.status === 408 || erro.status === 429 || erro.status >= 500;
}

/**
 * A colocação que a vitrine mostra. A fonte da verdade é o BACKEND: quando o item
 * traz `posicao`, a tela só exibe — a vitrine e o Ranking da Rede não podem dar
 * medalhas diferentes à mesma escola (a tela recalculando empate sozinha dava ouro
 * às duas empatadas enquanto o Ranking da Rede, com o desempate dele, punha uma em 2º).
 *
 * Sem `posicao` (o backend de hoje ainda não manda), fica a regra que já estava no
 * ar, para não mudar a medalha pública antes de o dono decidir a regra de empate:
 * EMPATE (1º, 1º, 3º…) = quantas escolas têm valor ESTRITAMENTE maior, mais um. O
 * backend ordena os empates pelo nome só para a lista ser estável; numerar pela
 * ordem daria a medalha pela ordem alfabética. O valor comparado é o que a tela
 * mostra (o backend já arredonda a 1 casa).
 */
function posicaoExibida(escolas: TopEscola[], indice: number): number {
  const doBackend = escolas[indice].posicao;
  if (typeof doBackend === "number" && Number.isInteger(doBackend) && doBackend > 0) return doBackend;
  const valor = escolas[indice].valor;
  return 1 + escolas.filter((e) => e.valor > valor).length;
}

/**
 * O cartão da matéria só aparece se o módulo está no plano da rede. O que a rede
 * não contratou não existe para ela, nem na interface (services/modulos.py):
 * não é "Sem dados ainda.", que fica para a matéria CONTRATADA que ainda não tem
 * escola com dado. Sem `modulos` (backend anterior ao campo), mostra o cartão.
 */
function moduloNoPlano(modulos: string[] | undefined, modulo: string): boolean {
  return !Array.isArray(modulos) || modulos.includes(modulo);
}

/** Uma linha de escola no ranking (pódio para top 3, barra relativa ao 1º). */
function LinhaEscola({ pos, escola, topo }: { pos: number; escola: TopEscola; topo: number }) {
  const medalha = MEDALHAS[pos];
  const top3 = pos <= 3;
  const largura = Math.max(8, (escola.valor / topo) * 100);
  return (
    // `isolate`: a barra relativa (-z-10) é pintada DENTRO da linha, por cima do
    // fundo dela — sem isso ela ia para trás do fundo opaco da página e sumia.
    <li
      className={`vitrine-linha relative isolate flex items-center overflow-hidden rounded-2xl ring-1 ring-inset ${
        top3 ? "bg-white/[0.09] ring-white/15" : "bg-white/[0.04] ring-white/[0.07]"}`}
      style={top3 ? { boxShadow: `inset 4px 0 0 0 ${medalha?.cor ?? OURO}` } : undefined}
    >
      <span aria-hidden data-barra className="absolute inset-y-0 left-0 -z-10 rounded-2xl opacity-[0.10]"
        style={{ width: `${largura}%`, background: medalha?.cor ?? "#6B7DE4" }} />
      <span className="vitrine-medalha flex shrink-0 items-center justify-center">
        {medalha ? (
          <>
            <span aria-hidden>{medalha.emoji}</span>
            <span className="sr-only">{pos}º lugar</span>
          </>
        ) : (
          <span className="font-bold tabular-nums text-white/70">
            {pos}º<span className="sr-only"> lugar</span>
          </span>
        )}
      </span>
      {/* Nome INTEIRO: quebra linha no celular; na TV até 2 linhas (o texto
          completo continua no DOM para o leitor de tela e no title). */}
      <span className="vitrine-nome min-w-0 flex-1 font-semibold text-white" title={escola.nome}
        style={{ fontFamily: FONTE }}>
        {escola.nome}
      </span>
      <span className="vitrine-valor shrink-0 text-right font-bold tabular-nums text-white"
        style={top3 ? { color: medalha?.cor } : undefined}>
        {Number.isFinite(escola.valor)
          ? nota(escola.valor)
          : <><span aria-hidden>—</span><span className="sr-only">sem dado</span></>}
      </span>
    </li>
  );
}

/** Cartão de uma matéria (Leitura/Matemática) com as 5 melhores escolas. */
function Cartao({ titulo, icone: Icone, escolas, unidade }: {
  titulo: string; icone: LucideIcon; escolas: TopEscola[]; unidade?: string;
}) {
  const idTitulo = useId();
  const topo = Math.max(...escolas.map((e) => e.valor), 0) || 1;
  return (
    <section aria-labelledby={idTitulo}
      className="vitrine-cartao rounded-3xl ring-1 ring-inset ring-white/10">
      <h2 id={idTitulo} className="vitrine-cartao-titulo flex items-center justify-center font-extrabold text-white"
        style={{ fontFamily: FONTE }}>
        <Icone aria-hidden className="vitrine-icone shrink-0" style={{ color: OURO }} strokeWidth={2.3} />
        {titulo}
      </h2>
      {unidade && (
        <p className="vitrine-unidade text-center uppercase text-white/70">{unidade}</p>
      )}
      {escolas.length === 0 ? (
        <p className="vitrine-vazio text-center text-white/70">Sem dados ainda.</p>
      ) : (
        // role="list": sem ele o Safari/VoiceOver não anuncia "lista, 5 itens"
        // num <ol> com list-style none (preflight do Tailwind).
        <ol className="vitrine-lista" role="list">
          {escolas.slice(0, 5).map((e, i) => (
            <LinhaEscola key={`${i}-${e.nome}`} pos={posicaoExibida(escolas, i)} escola={e} topo={topo} />
          ))}
        </ol>
      )}
    </section>
  );
}

function Moldura({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center bg-[#0F1626] px-6 text-center text-white/80"
      style={{ minHeight: "100dvh" }}>
      <FundoConstela cor="#5B6EE1" />
      <div className="relative">{children}</div>
    </div>
  );
}

export default function PainelPublicoRede() {
  useTelaPublica();
  // Link sem login feito para circular: buscador não indexa nem arquiva.
  useSemIndexacao();
  const { token } = useParams<{ token: string }>();
  const { dados, erro, carregando, recarregar } = useApi<PainelPublico>(
    token ? `/publico/rede/${token}` : null);

  // Telão: revalida a cada 60s (pega quando a vitrine é desligada e some).
  useEffect(() => {
    const t = window.setInterval(recarregar, 60_000);
    return () => window.clearInterval(t);
  }, [recarregar]);

  // Uma falha TRANSITÓRIA da recarga (rede caiu, servidor reiniciando) NÃO troca
  // a vitrine por "Reconectando…": fica o último quadro bom e o ciclo de 60s
  // recupera sozinho (mesmo comportamento do telão da escola). Só um erro
  // definitivo (404: vitrine desligada ou token inválido) tira a vitrine do ar.
  const definitivo = erro !== null && !ehTransitorio(erro);
  if (!dados || definitivo) {
    if (!erro && carregando) {
      return <Moldura><p className="flex items-center gap-3 text-lg" role="status">
        <span aria-hidden
          className="h-5 w-5 rounded-full border-2 border-white/20 border-t-white/80 motion-safe:animate-spin" />
        Carregando a vitrine...
      </p></Moldura>;
    }
    return <Moldura><p className="text-xl" role="status">
      {erro && !definitivo ? "Reconectando à vitrine..." : "Vitrine não encontrada ou desativada."}
    </p></Moldura>;
  }

  const leitura = moduloNoPlano(dados.modulos, "leitura");
  const matematica = moduloNoPlano(dados.modulos, "matematica");

  return (
    <div className="vitrine relative flex min-h-screen flex-col justify-center bg-[#0F1626] text-white"
      style={{ minHeight: "100dvh" }}>
      <FundoConstela cor="#5B6EE1" />
      <div className="vitrine-conteudo relative mx-auto w-full">
        <header className="vitrine-cabecalho text-center">
          <img src="/simbolo-escuro.svg" alt="Constela Edu" width={40} height={40}
            className="vitrine-logo block" />
          <p className="vitrine-sobretitulo font-semibold uppercase text-amber-300">
            Secretaria de Educação
          </p>
          <h1 className="vitrine-titulo font-extrabold text-white" style={{ fontFamily: FONTE }}>
            {dados.rede_nome}
          </h1>
          <p className="vitrine-subtitulo text-white/80">As escolas em destaque da nossa rede</p>
        </header>

        {/* Com UM módulo no plano, `vitrine-cartoes-um` centraliza o cartão no
            modo TV (que, com dois, fixa duas colunas). */}
        <div className={leitura && matematica ? "vitrine-cartoes" : "vitrine-cartoes vitrine-cartoes-um"}>
          {leitura && (
            <Cartao titulo="Leitura" icone={BookOpen} escolas={dados.top_leitura}
              unidade={dados.unidade_leitura} />
          )}
          {matematica && (
            <Cartao titulo="Matemática" icone={Calculator} escolas={dados.top_matematica}
              unidade={dados.unidade_matematica} />
          )}
        </div>

        <footer className="vitrine-rodape flex flex-wrap items-center justify-center text-center text-white/70">
          <img src="/simbolo-escuro.svg" alt="" aria-hidden width={16} height={16}
            className="vitrine-rodape-logo opacity-70" />
          <span style={{ fontFamily: FONTE }}>
            constela<span className="text-amber-300">edu</span>
          </span>
          {/* Separadores em span próprio, só a partir de sm: no celular os blocos
              quebram em linhas sem começar com "·". */}
          <span aria-hidden className="hidden sm:inline">·</span>
          <span>celebrando o esforço de cada escola</span>
          <span aria-hidden className="hidden sm:inline">·</span>
          <span>sem dados individuais de estudantes</span>
        </footer>
      </div>
    </div>
  );
}
