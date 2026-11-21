/**
 * Configurações → Conquistas — nada de critério fixo no código.
 *
 * A gestão da escola (administrador ou coordenação — o backend libera as
 * definições para `admin` e `coordenador`) cria, edita, reordena,
 * ativa/desativa e remove conquistas. Ao salvar, as regras passam a valer imediatamente para
 * todos os alunos: XP, mural, biblioteca, perfil e painel público.
 *
 * Identidade visual v2 (docs/design/IDENTIDADE-VISUAL-V2.md), no padrão da tela de
 * Critérios: cada conquista é uma linha-cartão (emoji em quadrado pastel na cor da
 * raridade, selos, critério e XP em "caixas", interruptor de ativa com a semântica
 * de checkbox) e o "Salvar alterações" fica numa barra grudada na base. O contrato
 * com o backend é o mesmo: o PUT manda a lista INTEIRA, a ordem do array é a ordem
 * de exibição, `codigo` vazio cria conquista nova (o servidor gera o código),
 * trocar o critério zera a plataforma (o servidor deduz) e trocar a raridade aplica
 * o XP sugerido. Não existe "restaurar padrão" (não há rota para isso).
 */
import { ArrowDown, ArrowLeft, ArrowUp, CheckCircle2, CircleAlert, Medal, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { BadgeRaridade, ChipPlataforma, NOME_PLATAFORMA, PilulaXp, QuadradoEmoji } from "../../components/ConquistasUi";
import {
  Botao,
  BotaoIcone,
  Campo,
  Card,
  Confirmacao,
  Erro,
  Mensagem,
  Modal,
  PageHeader,
  RotuloSecao,
  Skeleton,
  Vazio,
  estiloInput,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { usePerfil } from "../../hooks/usePerfil";
import { ApiError, api } from "../../lib/api";

interface Definicao {
  codigo: string;
  nome: string;
  icone: string;
  descricao: string;
  objetivo: string;
  indicador: string;
  limite: number;
  plataforma: string;
  xp: number;
  raridade: string;
  ativa: boolean;
  criada_em: string;
}

interface InfoIndicador {
  rotulo: string;
  plataforma: string;
  unidade: string;
}

interface Definicoes {
  conquistas: Definicao[];
  indicadores: Record<string, InfoIndicador>;
  /** Plataformas de módulo que a rede desta escola NÃO contratou (ausente em API
   *  antiga = nenhuma). As conquistas delas vêm na lista e voltam no PUT — senão
   *  salvar as apagaria —, mas não aparecem nem são oferecidas aqui. */
  plataformas_fora_do_plano?: string[];
  raridades: Record<string, string>;
  xp_sugerido: Record<string, number>;
}

const NOVA: Definicao = {
  codigo: "", nome: "", icone: "🏅", descricao: "", objetivo: "",
  indicador: "livros_unicos", limite: 10, plataforma: "", xp: 100,
  raridade: "comum", ativa: true, criada_em: "",
};

/** Atalhos de ícone (os emojis das conquistas padrão e alguns de celebração). O
 *  campo continua livre: qualquer emoji de até 8 caracteres vale. */
const SUGESTOES_ICONE = ["🏅", "📖", "📚", "🥉", "🥈", "🥇", "⏱️", "🎯", "🧩", "🧮", "✖️", "🏆", "⭐", "🌌", "🚀", "🔥"];

/** Setas de reordenar: 28 px no tablet e no desktop; 40 px no celular (alvo de toque). */
const CLASSE_SETA =
  "grid h-7 w-7 place-items-center rounded-lg text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 disabled:opacity-30 max-sm:h-10 max-sm:w-10 dark:hover:bg-zinc-800 dark:hover:text-zinc-100";

/** Interruptor visual sobre um checkbox NATIVO (a semântica e o rótulo continuam os
 *  de checkbox: "Ativar {nome}"); o estado também aparece em texto. */
function InterruptorAtiva({ ligado, rotulo, aoMudar }: {
  ligado: boolean; rotulo: string; aoMudar: (ligado: boolean) => void;
}) {
  return (
    <label className="inline-flex cursor-pointer select-none items-center gap-2.5">
      <span className="relative inline-flex shrink-0">
        <input
          type="checkbox"
          aria-label={rotulo}
          className="peer sr-only"
          checked={ligado}
          onChange={(e) => aoMudar(e.target.checked)}
        />
        <span
          aria-hidden
          className="h-7 w-12 rounded-full bg-zinc-400 transition-colors peer-checked:bg-indigo-600 peer-checked:shadow-pilula peer-focus-visible:ring-2 peer-focus-visible:ring-indigo-500 peer-focus-visible:ring-offset-2 dark:bg-zinc-500 dark:peer-focus-visible:ring-offset-zinc-900"
        />
        <span
          aria-hidden
          className="pointer-events-none absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-5 motion-reduce:transition-none"
        />
      </span>
      <span aria-hidden className={`w-12 text-xs font-semibold ${ligado ? "text-indigo-700 dark:text-indigo-300" : "text-zinc-500 dark:text-zinc-400"}`}>
        {ligado ? "Ativa" : "Inativa"}
      </span>
    </label>
  );
}

function EsqueletoLista() {
  return (
    <div aria-hidden className="space-y-3">
      {[0, 1, 2, 3].map((i) => (
        <Card key={i} className="flex items-center gap-4 p-5">
          <Skeleton className="h-14 w-14 rounded-2xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-2/3" />
          </div>
          <Skeleton className="hidden h-12 w-40 rounded-xl sm:block" />
        </Card>
      ))}
    </div>
  );
}

export default function ConfigConquistas() {
  const { escolaId } = useApp();
  // O caminho de volta é o de quem CHEGOU aqui: o administrador vem do cartão
  // dentro de Configurações Gerais; a coordenação — que não abre aquela tela
  // (RotaAdmin) — vem do grupo "Regras de pontuação" do menu (Gestão), cuja
  // primeira página é Critérios (/metricas). O mural (/conquistas) mora em outro
  // grupo (Escola › Reconhecimento): voltar para ele levava a coordenação a uma
  // seção por onde ela não passou.
  const { admin } = usePerfil();
  const volta = admin
    ? { para: "/configuracoes", rotulo: "Configurações" }
    : { para: "/metricas", rotulo: "Critérios" };
  const [lista, setLista] = useState<Definicao[]>([]);
  const [alterado, setAlterado] = useState(false);
  const [emEdicao, setEmEdicao] = useState<{ indice: number | null; item: Definicao } | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);
  // Remoção pede confirmação (só vale de verdade depois de "Salvar alterações").
  const [removendo, setRemovendo] = useState<number | null>(null);

  // Leitura única das definições — o hook cuida de cancelamento, timeout e retry.
  const { dados, erro, recarregar } = useApi<Definicoes>(
    escolaId ? `/escolas/${escolaId}/gamificacao/conquistas/definicoes` : null,
    {
      // Semeia a lista editável a cada busca bem-sucedida.
      aoSucesso: (resposta) => {
        setLista(resposta.conquistas);
        setAlterado(false);
      },
    },
  );

  // Alterações pendentes: o navegador avisa antes de fechar ou recarregar a aba.
  useEffect(() => {
    if (!alterado) return;
    const aoSair = (evento: BeforeUnloadEvent) => {
      evento.preventDefault();
      evento.returnValue = "";
    };
    window.addEventListener("beforeunload", aoSair);
    return () => window.removeEventListener("beforeunload", aoSair);
  }, [alterado]);

  function alterar(nova: Definicao[]) {
    setLista(nova);
    setAlterado(true);
    setMensagem(null);
  }

  // CONTRATO: conquista de módulo fora do plano da rede fica guardada na lista
  // (o PUT a devolve), mas não aparece, não se reordena e o critério dela não é
  // oferecido no editor.
  const fora = new Set(dados?.plataformas_fora_do_plano ?? []);
  const foraDoPlano = (c: Definicao) =>
    fora.has(c.plataforma) || fora.has(dados?.indicadores[c.indicador]?.plataforma ?? "");
  const visiveis = lista.flatMap((c, i) => (foraDoPlano(c) ? [] : [i]));
  const guardadas = lista.length - visiveis.length;
  const indicadoresNoPlano = Object.entries(dados?.indicadores ?? {})
    .filter(([, info]) => !fora.has(info.plataforma));

  /** Troca a conquista de lugar com a VIZINHA VISÍVEL (as guardadas não contam). */
  function mover(indice: number, direcao: -1 | 1) {
    const posicao = visiveis.indexOf(indice);
    const destino = visiveis[posicao + direcao];
    if (posicao < 0 || destino === undefined) return;
    const nova = [...lista];
    [nova[indice], nova[destino]] = [nova[destino], nova[indice]];
    alterar(nova);
  }

  async function salvar() {
    if (!escolaId) return;
    setSalvando(true);
    setMensagem(null);
    try {
      const resposta = await api<{ mensagem: string; conquistas: Definicao[] }>(
        `/escolas/${escolaId}/gamificacao/conquistas/definicoes`,
        { method: "PUT", body: JSON.stringify({ conquistas: lista }) },
      );
      setLista(resposta.conquistas);
      setAlterado(false);
      setMensagem({ tipo: "ok", texto: resposta.mensagem });
    } catch (excecao) {
      setMensagem({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message : "Não foi possível salvar.",
      });
    } finally {
      setSalvando(false);
    }
  }

  const edicao = emEdicao?.item ?? null;
  const infoIndicador = edicao ? dados?.indicadores[edicao.indicador] : null;
  const edicaoValida =
    edicao !== null && edicao.nome.trim().length >= 2 && edicao.limite > 0 && edicao.xp >= 0;

  function confirmarEdicao() {
    if (!emEdicao || !edicaoValida || !edicao) return;
    const item = { ...edicao, nome: edicao.nome.trim() };
    if (emEdicao.indice === null) alterar([...lista, item]);
    else alterar(lista.map((atual, i) => (i === emEdicao.indice ? item : atual)));
    setEmEdicao(null);
  }

  /** Atualiza um campo do item em edição. */
  function editar(campos: Partial<Definicao>) {
    if (!emEdicao || !edicao) return;
    setEmEdicao({ ...emEdicao, item: { ...edicao, ...campos } });
  }

  // A conquista nova começa no primeiro critério que a rede contratou.
  const novaConquista = () => setEmEdicao({
    indice: null,
    item: { ...NOVA, indicador: indicadoresNoPlano.some(([chave]) => chave === NOVA.indicador)
      ? NOVA.indicador : indicadoresNoPlano[0]?.[0] ?? NOVA.indicador },
  });
  const aRemover = removendo != null ? lista[removendo] : null;
  // Plataforma exibida: a gravada ou, vazia, a que o servidor deduz do critério.
  const plataformaDe = (c: Definicao) =>
    c.plataforma || dados?.indicadores[c.indicador]?.plataforma || "geral";

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={volta.para}
          className="mb-3 inline-flex items-center gap-1.5 rounded-lg text-sm font-medium text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
        >
          <ArrowLeft size={15} aria-hidden /> {volta.rotulo}
        </Link>
        {/* O MESMO nome do item de menu que abre esta tela (Regras de pontuação →
            "Editar conquistas"): "Conquistas" sozinho é o mural (/conquistas). */}
        <PageHeader
          titulo="Editar conquistas"
          descricao="Crie e ajuste as medalhas da escola — critérios, XP, raridade e ordem — sem tocar no código. Novas conquistas valem na hora."
          acoes={
            <Botao variante="secundario" onClick={novaConquista} disabled={!dados}>
              <Plus size={15} aria-hidden /> Nova conquista
            </Botao>
          }
        />
      </div>

      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}

      {erro ? (
        <Card className="p-6">
          <Erro descricao={erro.message} aoTentar={recarregar} />
        </Card>
      ) : dados === null ? (
        <EsqueletoLista />
      ) : visiveis.length === 0 ? (
        <Card className="p-6">
          <Vazio
            icone={Medal}
            titulo="Nenhuma conquista na lista"
            descricao="Crie a primeira com “Nova conquista”. Ela só passa a valer depois de salvar."
            acao={<Botao onClick={novaConquista}><Plus size={15} aria-hidden /> Nova conquista</Botao>}
          />
        </Card>
      ) : (
        <ol aria-label="Conquistas da escola, na ordem de exibição" className="space-y-3">
          {visiveis.map((indice, posicao) => {
            const conquista = lista[indice];
            return (
            <li
              key={`${conquista.codigo}-${indice}`}
              className={`card flex flex-col gap-4 p-4 sm:p-5 lg:flex-row lg:items-center ${
                conquista.ativa ? "" : "bg-zinc-50 dark:bg-zinc-900/60"
              }`}
            >
              <div className="flex min-w-0 flex-1 items-start gap-3 sm:gap-4">
                {/* Setas de ordem: no celular 40 px e 8 px entre elas (com 28 px coladas era
                    fácil tocar "Descer" querendo "Subir"). */}
                <div className="flex shrink-0 flex-col gap-1 max-sm:gap-2">
                  <button
                    type="button"
                    aria-label={`Subir ${conquista.nome}`}
                    className={CLASSE_SETA}
                    disabled={posicao === 0}
                    onClick={() => mover(indice, -1)}
                  >
                    <ArrowUp size={15} aria-hidden />
                  </button>
                  <button
                    type="button"
                    aria-label={`Descer ${conquista.nome}`}
                    className={CLASSE_SETA}
                    disabled={posicao === visiveis.length - 1}
                    onClick={() => mover(indice, 1)}
                  >
                    <ArrowDown size={15} aria-hidden />
                  </button>
                </div>
                <QuadradoEmoji
                  emoji={conquista.icone} raridade={conquista.ativa ? conquista.raridade : "comum"} tamanho="lg"
                  className={conquista.ativa ? "" : "grayscale"}
                />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold leading-snug text-zinc-900 dark:text-white">{conquista.nome}</p>
                  {conquista.descricao && (
                    <p className="mt-0.5 line-clamp-2 text-sm text-zinc-500 dark:text-zinc-400" title={conquista.descricao}>
                      {conquista.descricao}
                    </p>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <BadgeRaridade raridade={conquista.raridade} rotulo={dados.raridades[conquista.raridade]} />
                    <ChipPlataforma plataforma={plataformaDe(conquista)} />
                  </div>
                </div>
              </div>

              {/* Caixas de critério e de XP com LARGURA FIXA: o XP, o interruptor e as
                  ações ficam em colunas alinhadas de um cartão para o outro (antes a
                  borda da caixa de critério variava ~150 px e a lista ficava serrilhada).
                  Na linha única (≥ 1024 px) o bloco não encolhe: quem cede espaço é o
                  texto da conquista, que quebra linha. */}
              <div className="flex flex-wrap items-center gap-3 pl-[3.25rem] sm:pl-11 lg:shrink-0 lg:flex-nowrap lg:pl-0">
                <div className="w-60 max-w-full shrink-0 rounded-xl bg-zinc-50 px-3.5 py-2 ring-1 ring-zinc-100 dark:bg-zinc-800/60 dark:ring-zinc-800">
                  <RotuloSecao>Critério</RotuloSecao>
                  <p className="break-words text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                    {dados.indicadores[conquista.indicador]?.rotulo ?? conquista.indicador} ≥ {conquista.limite}
                  </p>
                </div>
                <div className="min-w-[4.5rem] shrink-0 rounded-xl bg-ouro-50 px-3.5 py-2 ring-1 ring-ouro-100 dark:bg-ouro-400/10 dark:ring-ouro-400/20">
                  <RotuloSecao>XP</RotuloSecao>
                  <p className="text-sm font-bold tabular-nums text-marinho-900 dark:text-ouro-200">{conquista.xp}</p>
                </div>
                <InterruptorAtiva
                  ligado={conquista.ativa}
                  rotulo={`Ativar ${conquista.nome}`}
                  aoMudar={(ativa) => alterar(lista.map((atual, i) => (i === indice ? { ...atual, ativa } : atual)))}
                />
                <div className="flex items-center gap-2">
                  <BotaoIcone rotulo={`Editar ${conquista.nome}`} onClick={() => setEmEdicao({ indice, item: { ...conquista } })}>
                    <Pencil size={16} aria-hidden />
                  </BotaoIcone>
                  <BotaoIcone
                    rotulo={`Remover ${conquista.nome}`}
                    className="hover:!text-rose-600 dark:hover:!text-rose-300"
                    onClick={() => setRemovendo(indice)}
                  >
                    <Trash2 size={16} aria-hidden />
                  </BotaoIcone>
                </div>
              </div>
            </li>
            );
          })}
        </ol>
      )}

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Desativar esconde a conquista dos alunos sem apagar a regra. Remover exclui a
        definição da lista (o histórico de auditoria permanece). A ordem da tabela é a
        ordem de exibição em todo o sistema.
      </p>
      {guardadas > 0 && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {guardadas === 1
            ? "1 conquista de um módulo que não faz parte do plano da rede fica guardada: ela não aparece para os alunos e volta se a rede contratar o módulo."
            : `${guardadas} conquistas de um módulo que não faz parte do plano da rede ficam guardadas: elas não aparecem para os alunos e voltam se a rede contratar o módulo.`}
        </p>
      )}

      {/* Barra grudada na base: o estado do que foi editado e o "Salvar". */}
      {dados && (
        <div className="sticky bottom-4 z-10">
          <Card className="flex flex-wrap items-center gap-3 px-4 py-3 shadow-flutuante sm:px-5">
            {alterado ? (
              <p role="status" className="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium text-amber-800 dark:text-amber-300">
                <CircleAlert size={16} aria-hidden className="shrink-0" />
                <span>Há alterações não salvas — clique em “Salvar alterações” para aplicá-las.</span>
              </p>
            ) : (
              <p className="flex min-w-0 flex-1 items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
                <CheckCircle2 size={16} aria-hidden className="shrink-0 text-emerald-600 dark:text-emerald-400" />
                <span>Nenhuma alteração pendente.</span>
              </p>
            )}
            <Botao onClick={salvar} disabled={!alterado || salvando} aria-busy={salvando}>
              {salvando ? "Salvando..." : "Salvar alterações"}
            </Botao>
          </Card>
        </div>
      )}

      {/* --- Remover (confirmação) --- */}
      <Confirmacao
        titulo="Remover conquista?"
        aberto={aRemover != null}
        aoFechar={() => setRemovendo(null)}
        aoConfirmar={() => {
          if (removendo != null) alterar(lista.filter((_, i) => i !== removendo));
          setRemovendo(null);
        }}
        rotuloConfirmar="Remover"
        variante="perigo"
      >
        <p>
          “{aRemover?.nome}” sai da lista. A remoção só vale para os alunos depois de
          “Salvar alterações”.
        </p>
      </Confirmacao>

      {/* --- Editor --- */}
      <Modal
        titulo={emEdicao?.indice === null ? "Nova conquista" : `Editar ${edicao?.nome ?? ""}`}
        aberto={emEdicao !== null}
        aoFechar={() => setEmEdicao(null)}
        largura="max-w-2xl"
      >
        {edicao && dados && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Prévia do cartão com o que está no formulário. */}
            <div className="flex items-center gap-4 rounded-2xl bg-zinc-50 p-4 ring-1 ring-zinc-100 dark:bg-zinc-800/60 dark:ring-zinc-800 sm:col-span-2">
              <QuadradoEmoji emoji={edicao.icone} raridade={edicao.raridade} tamanho="lg" />
              <div className="min-w-0">
                <RotuloSecao>Prévia</RotuloSecao>
                <p className="truncate font-semibold text-zinc-900 dark:text-white" title={edicao.nome.trim() || "Sem nome ainda"}>
                  {edicao.nome.trim() || "Sem nome ainda"}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <BadgeRaridade raridade={edicao.raridade} rotulo={dados.raridades[edicao.raridade]} />
                  <ChipPlataforma plataforma={infoIndicador?.plataforma ?? "geral"} />
                  <PilulaXp>+{edicao.xp} XP</PilulaXp>
                </div>
              </div>
            </div>
            <div className="sm:col-span-2">
              <Campo rotulo="Nome *">
                <input className={estiloInput} value={edicao.nome} autoFocus
                       onChange={(e) => editar({ nome: e.target.value })} />
              </Campo>
            </div>
            <div>
              <Campo rotulo="Ícone (emoji)">
                <input className={estiloInput} value={edicao.icone} maxLength={8}
                       onChange={(e) => editar({ icone: e.target.value })} />
              </Campo>
              <div className="mt-2 flex flex-wrap gap-1" role="group" aria-label="Sugestões de ícone">
                {SUGESTOES_ICONE.map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    aria-label={`Usar o ícone ${emoji}`}
                    aria-pressed={edicao.icone === emoji}
                    onClick={() => editar({ icone: emoji })}
                    className={`grid h-8 w-8 place-items-center rounded-lg text-base transition-colors ${
                      edicao.icone === emoji
                        ? "bg-indigo-50 ring-2 ring-indigo-500 dark:bg-indigo-500/20"
                        : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    }`}
                  >
                    <span aria-hidden>{emoji}</span>
                  </button>
                ))}
              </div>
            </div>
            <Campo rotulo="Raridade">
              <select
                className={estiloInput}
                value={edicao.raridade}
                onChange={(e) => {
                  const raridade = e.target.value;
                  editar({ raridade, xp: dados.xp_sugerido[raridade] ?? edicao.xp });
                }}
              >
                {Object.entries(dados.raridades).map(([chave, rotulo]) => (
                  <option key={chave} value={chave}>{rotulo}</option>
                ))}
              </select>
            </Campo>
            <div className="sm:col-span-2">
              <Campo rotulo="Descrição (aparece no cartão da conquista)">
                <input className={estiloInput} value={edicao.descricao} maxLength={300}
                       onChange={(e) => editar({ descricao: e.target.value })} />
              </Campo>
            </div>
            <div className="sm:col-span-2">
              <Campo rotulo="Objetivo pedagógico (opcional)">
                <input className={estiloInput} value={edicao.objetivo} maxLength={300}
                       onChange={(e) => editar({ objetivo: e.target.value })} />
              </Campo>
            </div>
            <Campo rotulo="Critério (o que é medido)">
              <select
                className={estiloInput}
                value={edicao.indicador}
                onChange={(e) => editar({ indicador: e.target.value, plataforma: "" })}
              >
                {indicadoresNoPlano.map(([chave, info]) => (
                  <option key={chave} value={chave}>{info.rotulo}</option>
                ))}
              </select>
            </Campo>
            <Campo rotulo={`Quantidade necessária${infoIndicador ? ` (${infoIndicador.unidade})` : ""}`}>
              <input className={estiloInput} type="number" min={1} value={edicao.limite}
                     aria-invalid={!(edicao.limite > 0)}
                     onChange={(e) => editar({ limite: Number(e.target.value) })} />
            </Campo>
            <Campo rotulo="XP concedido">
              <input className={estiloInput} type="number" min={0} value={edicao.xp}
                     aria-invalid={!(edicao.xp >= 0)}
                     onChange={(e) => editar({ xp: Number(e.target.value) })} />
            </Campo>
            <div className="flex items-end pb-1">
              <InterruptorAtiva
                ligado={edicao.ativa}
                rotulo="Conquista ativa"
                aoMudar={(ativa) => editar({ ativa })}
              />
            </div>
            <div className="sm:col-span-2">
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Plataforma: <span className="font-semibold text-zinc-700 dark:text-zinc-200">{NOME_PLATAFORMA[infoIndicador?.plataforma ?? "geral"]}</span>{" "}
                (definida pelo critério escolhido)
              </p>
            </div>
            {!edicaoValida && (
              <p className="text-xs text-amber-800 dark:text-amber-300 sm:col-span-2">
                Para continuar: nome com pelo menos 2 letras, quantidade maior que zero e XP de zero para cima.
              </p>
            )}
            <div className="flex justify-end gap-2.5 border-t border-zinc-100 pt-4 dark:border-zinc-800 sm:col-span-2">
              <Botao variante="secundario" onClick={() => setEmEdicao(null)}>Cancelar</Botao>
              <Botao disabled={!edicaoValida} onClick={confirmarEdicao}>
                {emEdicao?.indice === null ? "Adicionar" : "Aplicar"}
              </Botao>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
