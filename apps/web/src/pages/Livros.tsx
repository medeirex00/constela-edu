/** Catálogo de Livros (PRD §57): busca, filtros e governança do acervo OFICIAL.
 *
 *  O catálogo vem do Elefante Letrado e é SOMENTE LEITURA para a escola. Só o
 *  Admin Global cria, corrige nível/título ou exclui livros.
 *
 *  O QUE UMA CORREÇÃO DE NÍVEL MUDA: ela vale para as PRÓXIMAS leituras. Cada
 *  leitura já registrada guarda o nível congelado do dia em que foi lida, então
 *  o histórico, as notas gravadas e os rankings do passado NÃO mudam — por isso
 *  a tela não fala mais em "recálculo pendente".
 *
 *  Aplicar ao HISTÓRICO é uma opção explícita do Admin Global (com confirmação):
 *  reescreve o nível congelado das leituras daquele livro, fica na auditoria e
 *  recalcula a escola. A única ressalva — leituras anteriores ao congelamento,
 *  que ainda seguem o nível atual do livro — vem contada do servidor
 *  (`leituras_sem_nivel_congelado`) e é o único caso em que a tela oferece o
 *  recálculo. O texto exibido é o do servidor (`aviso_correcao`), para a tela e
 *  a API dizerem a mesma coisa. */
import { BookOpen, BookPlus, CheckCircle2, ChevronLeft, ChevronRight, Library, Lock, Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  BarraFiltros,
  CabecalhoCartao,
  CampoBusca,
  ChipNivel,
  EsqueletoLista,
  SelectNativo,
} from "../components/PessoasUi";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Badge,
  Botao,
  Campo,
  Card,
  Confirmacao,
  Erro,
  Interruptor,
  Mensagem,
  Modal,
  PageHeader,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { numero } from "../lib/formato";
import type { Livro, PaginaLivros } from "../lib/types";

/** Vocabulário OFICIAL de níveis do Elefante — o mesmo que o servidor valida. */
const NIVEIS_OFICIAIS = [
  "AA", "BB", "CC", "DD", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
  "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "Z+", "A+",
];

const MOTIVO_MINIMO = 5;
/** Os mesmos limites do servidor (colunas do livro): acima deles, 422. */
const AUTOR_MAXIMO = 200;
const CATEGORIA_MAXIMA = 100;
const PAGINAS_MAXIMAS = 100_000;

/** Usado quando a resposta do PATCH não traz `aviso_correcao` (servidor antigo):
 *  o MESMO conteúdo honesto, para a tela nunca prometer efeito retroativo. */
const AVISO_CORRECAO_PADRAO =
  "Correção registrada — ela vale para as PRÓXIMAS leituras. As leituras já registradas " +
  "guardam o nível que valia quando o aluno leu o livro, então o histórico, as notas " +
  "gravadas e os rankings do passado continuam como estão.";

/** Resposta do PATCH: a tela só exibe o que o servidor apurou. Os campos ainda
 *  não existem em packages/core (ver pendências), então são tipados aqui. */
type LivroSalvo = Livro & {
  aviso_correcao?: string | null;
  vale_para_proximas_leituras?: boolean;
  historico_preservado?: boolean;
  leituras_atualizadas?: number;
  leituras_sem_nivel_congelado?: number;
};

interface FormularioLivro {
  id: number | null;
  titulo: string;
  autor: string;
  nivel_codigo: string;
  /** Nível ao abrir a edição: mudá-lo exige motivo. */
  nivel_original: string;
  nivel_oficial: string | null;
  categoria: string;
  paginas: string;
  motivo: string;
  /** Ação RETROATIVA explícita: reescreve o nível congelado das leituras deste
   *  livro. Nasce desmarcada — o padrão é não mexer no passado. */
  aplicar_ao_historico: boolean;
}

const FORM_VAZIO: FormularioLivro = {
  id: null, titulo: "", autor: "", nivel_codigo: "", nivel_original: "", nivel_oficial: null,
  categoria: "", paginas: "", motivo: "", aplicar_ao_historico: false,
};

// No celular (< 640 px) os botões da linha ganham 40 px (alvo de toque).
const estiloAcao =
  "grid h-9 w-9 place-items-center rounded-full text-zinc-500 transition-colors max-sm:h-10 max-sm:w-10 dark:text-zinc-400";

// Tabela do acervo no celular (< 640 px): células mais justas.
const th = `${classesTabela.th} max-sm:px-3`;
const td = `${classesTabela.td} max-sm:px-3`;

export default function Livros() {
  const { escolaId, usuario } = useApp();
  // Governança: só o Admin Global administra o catálogo oficial.
  const podeEditar = usuario?.is_global === true;

  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [nivel, setNivel] = useState("");
  const [soDivergentes, setSoDivergentes] = useState(false);
  const [numeroPagina, setNumeroPagina] = useState(1);
  const [formulario, setFormulario] = useState<FormularioLivro | null>(null);
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);
  // "Aplicar ao histórico" reescreve o passado: pede confirmação explícita antes do envio.
  const [confirmandoHistorico, setConfirmandoHistorico] = useState(false);
  const [paraExcluir, setParaExcluir] = useState<Livro | null>(null);
  const [excluindo, setExcluindo] = useState(false);
  // Resultado da última correção: o texto vem do servidor (fonte única) e o
  // recálculo só é oferecido quando há leitura ANTIGA sem nível congelado — o
  // único caso em que a correção ainda move algum número já gravado.
  const [resultado, setResultado] = useState<{ texto: string; ofereceRecalculo: boolean } | null>(null);
  const [recalculando, setRecalculando] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  // A busca espera a pessoa parar de digitar (300 ms) — não consulta a cada tecla.
  useEffect(() => {
    const temporizador = window.setTimeout(() => {
      setBuscaAplicada(busca);
      setNumeroPagina(1);
    }, 300);
    return () => window.clearTimeout(temporizador);
  }, [busca]);

  // Página atual do catálogo — refeita quando busca/nível/página mudam.
  const parametros = new URLSearchParams({ pagina: String(numeroPagina) });
  if (buscaAplicada) parametros.set("busca", buscaAplicada);
  if (nivel) parametros.set("nivel", nivel);
  if (podeEditar && soDivergentes) parametros.set("divergentes", "true");
  const {
    dados: pagina,
    erro: erroLivros,
    carregando,
    recarregar: carregar,
  } = useApi<PaginaLivros>(escolaId ? `/escolas/${escolaId}/livros?${parametros}` : null);

  const nivelMudou =
    formulario !== null && formulario.id !== null && formulario.nivel_codigo !== formulario.nivel_original;

  /** Valida e, se for reescrever o histórico, pede a confirmação antes de enviar. */
  function salvar() {
    if (!escolaId || !formulario) return;
    if (formulario.paginas) {
      const paginas = Number(formulario.paginas);
      if (!Number.isInteger(paginas) || paginas < 1 || paginas > PAGINAS_MAXIMAS) {
        setErro(`As páginas vão de 1 a ${numero(PAGINAS_MAXIMAS)}. Confira o valor digitado.`);
        return;
      }
    }
    if (formulario.autor.trim().length > AUTOR_MAXIMO) {
      setErro(`O autor pode ter até ${AUTOR_MAXIMO} caracteres.`);
      return;
    }
    if (formulario.categoria.trim().length > CATEGORIA_MAXIMA) {
      setErro(`A categoria pode ter até ${CATEGORIA_MAXIMA} caracteres.`);
      return;
    }
    const exigeMotivo = nivelMudou || formulario.aplicar_ao_historico;
    if (exigeMotivo && formulario.motivo.trim().length < MOTIVO_MINIMO) {
      setErro(`Informe o motivo da correção de nível (pelo menos ${MOTIVO_MINIMO} caracteres).`);
      return;
    }
    // Reescrever o passado é irreversível pela tela: confirma antes de enviar.
    if (formulario.aplicar_ao_historico) {
      setConfirmandoHistorico(true);
      return;
    }
    void enviar();
  }

  async function enviar() {
    if (!escolaId || !formulario) return;
    setConfirmandoHistorico(false);
    setSalvando(true);
    setErro("");
    try {
      const corpo = {
        titulo: formulario.titulo.trim(),
        autor: formulario.autor.trim() || null,
        nivel_codigo: formulario.nivel_codigo,
        categoria: formulario.categoria.trim() || null,
        paginas: formulario.paginas ? Number(formulario.paginas) : null,
        motivo: formulario.motivo.trim() || null,
      };
      if (formulario.id === null) {
        await api(`/escolas/${escolaId}/livros`, { method: "POST", body: JSON.stringify(corpo) });
      } else {
        const salvo = await api<LivroSalvo>(`/escolas/${escolaId}/livros/${formulario.id}`, {
          method: "PATCH",
          body: JSON.stringify({ ...corpo, aplicar_ao_historico: formulario.aplicar_ao_historico }),
        });
        const antigas = salvo?.leituras_sem_nivel_congelado ?? 0;
        const mudouAlgo =
          Boolean(salvo?.aviso_correcao) ||
          salvo?.vale_para_proximas_leituras === true ||
          salvo?.historico_preservado === false;
        if (mudouAlgo) {
          setResultado({
            texto: salvo.aviso_correcao ?? AVISO_CORRECAO_PADRAO,
            // Recalcular só faz sentido pelas leituras ANTIGAS (sem nível
            // congelado). Aplicando ao histórico, o servidor já recalculou.
            ofereceRecalculo: antigas > 0 && salvo.historico_preservado !== false,
          });
          setAviso(null);
        }
      }
      setFormulario(null);
      carregar();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar o livro.");
    } finally {
      setSalvando(false);
    }
  }

  async function recalcular() {
    if (!escolaId) return;
    setRecalculando(true);
    try {
      const resposta = await api<{ mensagem?: string }>(`/escolas/${escolaId}/recalcular`, { method: "POST" });
      setResultado(null);
      setAviso({ tipo: "ok", texto: resposta?.mensagem ?? "Notas recalculadas." });
    } catch (excecao) {
      setAviso({
        tipo: "erro",
        texto: excecao instanceof Error ? excecao.message : "Não foi possível recalcular as notas.",
      });
    } finally {
      setRecalculando(false);
    }
  }

  async function excluir() {
    if (!escolaId || !paraExcluir) return;
    setExcluindo(true);
    try {
      await api(`/escolas/${escolaId}/livros/${paraExcluir.id}`, { method: "DELETE" });
      setAviso({ tipo: "ok", texto: `“${paraExcluir.titulo}” foi excluído do catálogo.` });
      setParaExcluir(null);
      carregar();
    } catch (excecao) {
      // O erro aparece na própria tela (antes era um window.alert).
      setAviso({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Não foi possível excluir." });
      setParaExcluir(null);
    } finally {
      setExcluindo(false);
    }
  }

  const totalPaginas = pagina ? Math.max(1, Math.ceil(pagina.total / pagina.por_pagina)) : 1;
  const opcoesNivel =
    formulario?.nivel_codigo && !NIVEIS_OFICIAIS.includes(formulario.nivel_codigo)
      ? [formulario.nivel_codigo, ...NIVEIS_OFICIAIS]
      : NIVEIS_OFICIAIS;
  const comFiltro = Boolean(buscaAplicada || nivel || (podeEditar && soDivergentes));

  return (
    <div>
      <PageHeader
        titulo="Catálogo de Livros"
        descricao="Títulos, níveis e pontuação de cada livro do catálogo oficial do Elefante Letrado."
        acoes={
          podeEditar ? (
            <Botao onClick={() => { setFormulario({ ...FORM_VAZIO }); setErro(""); }}>
              <BookPlus size={16} aria-hidden /> Novo livro
            </Botao>
          ) : undefined
        }
      />

      {!podeEditar && (
        <div
          role="note"
          className="mb-5 flex items-start gap-3 rounded-2xl border border-zinc-200/80 bg-white px-4 py-3.5 text-sm text-zinc-600 shadow-cartao dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
        >
          <Lock size={17} aria-hidden className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-300" />
          <p>
            <strong className="text-zinc-900 dark:text-white">Catálogo oficial — somente leitura.</strong> Os níveis vêm do Elefante Letrado;
            correções de nível ou título são feitas pela Constela.
          </p>
        </div>
      )}

      {podeEditar && resultado && (
        <div
          role="status"
          className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3.5 text-sm text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200"
        >
          <span className="flex min-w-0 flex-1 items-start gap-2.5">
            <CheckCircle2 size={17} aria-hidden className="mt-0.5 shrink-0" />
            <span>{resultado.texto}</span>
          </span>
          {resultado.ofereceRecalculo && (
            <Botao onClick={recalcular} disabled={recalculando}>
              {recalculando ? "Recalculando..." : "Recalcular a escola agora"}
            </Botao>
          )}
        </div>
      )}
      {aviso && (
        <div className="mb-5">
          <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>
        </div>
      )}

      <BarraFiltros>
        <CampoBusca
          rotulo="Buscar por título ou autor"
          placeholder="Buscar título ou autor..."
          className="flex-1 basis-60"
          value={busca}
          onChange={(evento) => setBusca(evento.target.value)}
        />
        <SelectNativo
          aria-label="Filtrar por nível"
          className="w-full sm:w-48"
          value={nivel}
          onChange={(evento) => { setNivel(evento.target.value); setNumeroPagina(1); }}
        >
          <option value="">Todos os níveis</option>
          {NIVEIS_OFICIAIS.map((codigo) => (
            <option key={codigo} value={codigo}>{codigo}</option>
          ))}
        </SelectNativo>
        {podeEditar && (
          <span className="inline-flex items-center gap-2.5 text-sm text-zinc-600 dark:text-zinc-300">
            <Interruptor
              ligado={soDivergentes}
              aoMudar={(ligado) => { setSoDivergentes(ligado); setNumeroPagina(1); }}
              rotulo="Só divergentes do oficial"
            />
            {/* O nome acessível está no interruptor; o texto ao lado é só visual. */}
            <span aria-hidden className="cursor-pointer select-none"
                  onClick={() => { setSoDivergentes((v) => !v); setNumeroPagina(1); }}>
              Só divergentes do oficial
            </span>
          </span>
        )}
      </BarraFiltros>

      <Card className="overflow-hidden">
        <CabecalhoCartao
          titulo={comFiltro ? "Resultado da busca" : "Acervo"}
          contagem={pagina ? `${numero(pagina.total)} livro${pagina.total === 1 ? "" : "s"}` : undefined}
        />
        {carregando && pagina === null ? (
          <EsqueletoLista texto="Carregando livros..." />
        ) : !carregando && erroLivros ? (
          <Erro descricao={erroLivros.message} aoTentar={carregar} />
        ) : pagina === null || pagina.itens.length === 0 ? (
          <Vazio icone={Library} titulo="Nenhum livro encontrado" descricao="Ajuste a busca ou os filtros." />
        ) : (
          // Celular (< 640 px): a tabela rola de lado dentro do cartão, com o aviso em
          // texto acima dela. O Autor agora vem também no celular (antes sumia abaixo de
          // 768 px e a busca "título ou autor" casava livros sem mostrar o autor); de 640 a
          // 767 px segue fora como antes. As ações de quem edita ficam presas à direita
          // (`presa-celular`); para quem só consulta, presas ficam as Leituras. Título e autor
          // com base mínima: não uma palavra por linha.
          <TabelaRolavel rotulo="Acervo: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  <th className={th}>Título</th>
                  <th className={`hidden max-sm:table-cell md:table-cell ${th}`}>Autor</th>
                  <th className={th}>Nível</th>
                  {podeEditar && <th className={th}>Nível oficial</th>}
                  <th className={`text-right ${th} ${podeEditar ? "" : "presa-celular"}`}>Leituras</th>
                  {podeEditar && <th className={`w-24 ${classesTabela.th} presa-celular max-sm:px-2`}><span className="sr-only">Ações</span></th>}
                </tr>
              </thead>
              <tbody>
                {pagina.itens.map((livro) => (
                  <tr key={livro.id} className={classesTabela.tr}>
                    <td className={td}>
                      <div className="flex items-center gap-3">
                        <span aria-hidden className="hidden h-9 w-9 shrink-0 place-items-center rounded-xl bg-indigo-50 text-indigo-600 sm:grid dark:bg-indigo-500/15 dark:text-indigo-300">
                          <BookOpen size={17} />
                        </span>
                        <div className="min-w-0 max-sm:min-w-[8rem]">
                          <span className="block font-semibold text-zinc-900 dark:text-zinc-100">{livro.titulo}</span>
                          {livro.categoria && (
                            <span className="block text-xs text-zinc-500 dark:text-zinc-400">{livro.categoria}</span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className={`hidden text-zinc-500 max-sm:table-cell md:table-cell dark:text-zinc-400 ${td}`}>
                      <span className="block max-sm:min-w-[6rem]">{livro.autor ?? "—"}</span>
                    </td>
                    <td className={td}>
                      <span className="inline-flex flex-wrap items-center gap-1.5">
                        <ChipNivel>{livro.nivel_codigo}</ChipNivel>
                        {podeEditar && livro.divergente && <Badge tom="alerta">Divergente</Badge>}
                      </span>
                    </td>
                    {podeEditar && (
                      <td className={`text-zinc-600 dark:text-zinc-300 ${td}`}>
                        {livro.nivel_oficial ? (
                          <span className="font-semibold">{livro.nivel_oficial}</span>
                        ) : (
                          <span className="text-xs text-zinc-500 dark:text-zinc-400">
                            fora do catálogo
                            {/* Sem nível oficial, o que existe é o nível do
                                RELATÓRIO da escola — dito com esse nome, nunca
                                como se fosse do Elefante. */}
                            {livro.nivel_fonte && ` · relatório: ${livro.nivel_fonte}`}
                          </span>
                        )}
                      </td>
                    )}
                    <td className={`text-right font-bold tabular-nums text-zinc-900 dark:text-zinc-100 ${td} ${podeEditar ? "" : "presa-celular"}`}>
                      {numero(livro.leituras)}
                    </td>
                    {podeEditar && (
                      <td className="presa-celular px-4 py-2 text-right max-sm:px-2">
                        <span className="inline-flex gap-0.5">
                          <button
                            type="button"
                            aria-label={`Editar ${livro.titulo}`}
                            title="Editar"
                            className={`${estiloAcao} hover:bg-indigo-50 hover:text-indigo-600 dark:hover:bg-zinc-800 dark:hover:text-indigo-300`}
                            onClick={() => {
                              setFormulario({
                                id: livro.id,
                                titulo: livro.titulo,
                                autor: livro.autor ?? "",
                                nivel_codigo: livro.nivel_codigo,
                                nivel_original: livro.nivel_codigo,
                                nivel_oficial: livro.nivel_oficial ?? null,
                                categoria: livro.categoria ?? "",
                                paginas: livro.paginas ? String(livro.paginas) : "",
                                motivo: "",
                                aplicar_ao_historico: false,
                              });
                              setErro("");
                            }}
                          >
                            <Pencil size={16} aria-hidden />
                          </button>
                          <button
                            type="button"
                            aria-label={`Excluir ${livro.titulo}`}
                            title="Excluir"
                            className={`${estiloAcao} hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-500/10 dark:hover:text-rose-300`}
                            onClick={() => setParaExcluir(livro)}
                          >
                            <Trash2 size={16} aria-hidden />
                          </button>
                        </span>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
        {pagina && pagina.total > pagina.por_pagina && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 px-5 py-3.5 text-sm dark:border-zinc-800">
            <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
              {numero(pagina.total)} livros · página {pagina.pagina} de {totalPaginas}
            </span>
            <div className="flex gap-2">
              <Botao variante="secundario" tamanho="sm" disabled={numeroPagina <= 1} onClick={() => setNumeroPagina(numeroPagina - 1)}>
                <ChevronLeft size={14} aria-hidden /> Anterior
              </Botao>
              <Botao variante="secundario" tamanho="sm" disabled={numeroPagina >= totalPaginas} onClick={() => setNumeroPagina(numeroPagina + 1)}>
                Próxima <ChevronRight size={14} aria-hidden />
              </Botao>
            </div>
          </div>
        )}
      </Card>

      {podeEditar && (
        <Modal
          titulo={formulario?.id === null ? "Novo livro" : "Editar livro"}
          aberto={formulario !== null}
          // Com a confirmação do histórico aberta, o Esc fecha só a confirmação.
          aoFechar={() => { if (!confirmandoHistorico) setFormulario(null); }}
        >
          {formulario && (
            <div className="space-y-3">
              <Campo rotulo="Título">
                <input className={estiloInput} value={formulario.titulo}
                       onChange={(e) => setFormulario({ ...formulario, titulo: e.target.value })} />
              </Campo>
              <Campo rotulo="Autor">
                <input className={estiloInput} maxLength={AUTOR_MAXIMO} value={formulario.autor}
                       onChange={(e) => setFormulario({ ...formulario, autor: e.target.value })} />
              </Campo>
              <div className="grid grid-cols-2 gap-3">
                <Campo rotulo="Nível">
                  <select className={estiloInput} value={formulario.nivel_codigo}
                          onChange={(e) => setFormulario({ ...formulario, nivel_codigo: e.target.value })}>
                    <option value="">Selecione…</option>
                    {opcoesNivel.map((codigo) => (
                      <option key={codigo} value={codigo}>{codigo}</option>
                    ))}
                  </select>
                </Campo>
                <Campo rotulo="Páginas (opcional)">
                  <input type="number" min={1} max={PAGINAS_MAXIMAS} className={estiloInput} value={formulario.paginas}
                         onChange={(e) => setFormulario({ ...formulario, paginas: e.target.value })} />
                </Campo>
              </div>
              <Campo rotulo="Categoria (opcional)">
                <input className={estiloInput} maxLength={CATEGORIA_MAXIMA} value={formulario.categoria}
                       onChange={(e) => setFormulario({ ...formulario, categoria: e.target.value })} />
              </Campo>
              {formulario.id !== null && (
                <>
                  <Campo rotulo="Motivo da correção (obrigatório ao mudar o nível — fica na auditoria)">
                    <input className={estiloInput} placeholder="Ex.: nível conferido no catálogo oficial"
                           value={formulario.motivo}
                           onChange={(e) => setFormulario({ ...formulario, motivo: e.target.value })} />
                  </Campo>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    {formulario.nivel_oficial ? `Nível oficial do Elefante: ${formulario.nivel_oficial}. ` : ""}
                    A correção vale para as próximas leituras. As leituras já registradas guardam o
                    nível que valia quando o aluno leu o livro, então o histórico e as notas gravadas
                    não mudam.
                  </p>
                  <label className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-xs text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 shrink-0 accent-amber-600"
                      checked={formulario.aplicar_ao_historico}
                      onChange={(e) =>
                        setFormulario({ ...formulario, aplicar_ao_historico: e.target.checked })
                      }
                    />
                    <span>
                      <strong>Aplicar também ao histórico.</strong> Reescreve o nível congelado das
                      leituras já registradas deste livro, recalcula a escola e fica no histórico
                      de alterações. Pede confirmação antes de salvar.
                    </span>
                  </label>
                </>
              )}
              {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
              <div className="flex justify-end gap-2.5 pt-2">
                <Botao variante="secundario" onClick={() => setFormulario(null)} disabled={salvando}>Cancelar</Botao>
                <Botao onClick={salvar} disabled={salvando || !formulario.titulo.trim() || !formulario.nivel_codigo}>
                  {salvando ? "Salvando..." : "Salvar"}
                </Botao>
              </div>
            </div>
          )}
        </Modal>
      )}

      {podeEditar && formulario && (
        <Confirmacao
          titulo="Aplicar a correção ao histórico?"
          aberto={confirmandoHistorico}
          aoFechar={() => setConfirmandoHistorico(false)}
          aoConfirmar={() => void enviar()}
          rotuloConfirmar="Aplicar ao histórico"
          variante="ambar"
          ocupado={salvando}
        >
          <p>
            As leituras já registradas de <strong>“{formulario.titulo.trim()}”</strong> passam a
            valer o nível <strong>{formulario.nivel_codigo}</strong>, a escola é recalculada e a
            mudança fica no histórico de alterações.
          </p>
        </Confirmacao>
      )}

      <Confirmacao
        titulo="Excluir livro do catálogo"
        aberto={paraExcluir !== null}
        aoFechar={() => setParaExcluir(null)}
        aoConfirmar={() => void excluir()}
        rotuloConfirmar={excluindo ? "Excluindo..." : "Excluir"}
        variante="perigo"
        ocupado={excluindo}
      >
        {paraExcluir && <p>Excluir <strong>“{paraExcluir.titulo}”</strong> do catálogo?</p>}
      </Confirmacao>
    </div>
  );
}
