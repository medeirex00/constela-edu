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
import { BookPlus, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  Modal,
  PageHeader,
  Vazio,
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

export default function Livros() {
  const { escolaId, usuario } = useApp();
  // Governança: só o Admin Global administra o catálogo oficial.
  const podeEditar = usuario?.is_global === true;

  const [busca, setBusca] = useState("");
  const [nivel, setNivel] = useState("");
  const [soDivergentes, setSoDivergentes] = useState(false);
  const [numeroPagina, setNumeroPagina] = useState(1);
  const [formulario, setFormulario] = useState<FormularioLivro | null>(null);
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);
  // Resultado da última correção: o texto vem do servidor (fonte única) e o
  // recálculo só é oferecido quando há leitura ANTIGA sem nível congelado — o
  // único caso em que a correção ainda move algum número já gravado.
  const [resultado, setResultado] = useState<{ texto: string; ofereceRecalculo: boolean } | null>(null);
  const [recalculando, setRecalculando] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  // Página atual do catálogo — refeita quando busca/nível/página mudam.
  const parametros = new URLSearchParams({ pagina: String(numeroPagina) });
  if (busca) parametros.set("busca", busca);
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

  async function salvar() {
    if (!escolaId || !formulario) return;
    const exigeMotivo = nivelMudou || formulario.aplicar_ao_historico;
    if (exigeMotivo && formulario.motivo.trim().length < MOTIVO_MINIMO) {
      setErro(`Informe o motivo da correção de nível (pelo menos ${MOTIVO_MINIMO} caracteres).`);
      return;
    }
    // Reescrever o passado é irreversível pela tela: confirma antes de enviar.
    if (
      formulario.aplicar_ao_historico &&
      !window.confirm(
        `Aplicar a correção ao HISTÓRICO de “${formulario.titulo.trim()}”? As leituras já ` +
          `registradas deste livro passam a valer o nível ${formulario.nivel_codigo}, a escola é ` +
          "recalculada e a mudança fica no log de auditoria.",
      )
    ) {
      return;
    }
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

  async function excluir(livro: Livro) {
    if (!escolaId) return;
    if (!window.confirm(`Excluir “${livro.titulo}” do catálogo?`)) return;
    try {
      await api(`/escolas/${escolaId}/livros/${livro.id}`, { method: "DELETE" });
      carregar();
    } catch (excecao) {
      window.alert(excecao instanceof Error ? excecao.message : "Não foi possível excluir.");
    }
  }

  const totalPaginas = pagina ? Math.max(1, Math.ceil(pagina.total / pagina.por_pagina)) : 1;
  const opcoesNivel =
    formulario?.nivel_codigo && !NIVEIS_OFICIAIS.includes(formulario.nivel_codigo)
      ? [formulario.nivel_codigo, ...NIVEIS_OFICIAIS]
      : NIVEIS_OFICIAIS;

  return (
    <div>
      <PageHeader
        titulo="Catálogo de Livros"
        descricao="Títulos, níveis e pontuação de cada livro do catálogo oficial do Elefante Letrado."
        acoes={
          podeEditar ? (
            <Botao onClick={() => { setFormulario({ ...FORM_VAZIO }); setErro(""); }}>
              <BookPlus size={15} /> Novo livro
            </Botao>
          ) : undefined
        }
      />

      {!podeEditar && (
        <div
          role="note"
          className="mb-4 rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300"
        >
          <strong>Catálogo oficial — somente leitura.</strong> Os níveis vêm do Elefante Letrado;
          correções de nível ou título são feitas pela Constela.
        </div>
      )}

      {podeEditar && resultado && (
        <div
          role="status"
          className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200"
        >
          <span>{resultado.texto}</span>
          {resultado.ofereceRecalculo && (
            <Botao onClick={recalcular} disabled={recalculando}>
              {recalculando ? "Recalculando..." : "Recalcular a escola agora"}
            </Botao>
          )}
        </div>
      )}
      {aviso && (
        <div className="mb-4">
          <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          aria-label="Buscar por título ou autor"
          className="w-64 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          placeholder="Buscar título ou autor..."
          value={busca}
          onChange={(evento) => { setBusca(evento.target.value); setNumeroPagina(1); }}
        />
        <select
          aria-label="Filtrar por nível"
          className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          value={nivel}
          onChange={(evento) => { setNivel(evento.target.value); setNumeroPagina(1); }}
        >
          <option value="">Todos os níveis</option>
          {NIVEIS_OFICIAIS.map((codigo) => (
            <option key={codigo} value={codigo}>{codigo}</option>
          ))}
        </select>
        {podeEditar && (
          <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
            <input
              type="checkbox"
              checked={soDivergentes}
              onChange={(evento) => { setSoDivergentes(evento.target.checked); setNumeroPagina(1); }}
            />
            Só divergentes do oficial
          </label>
        )}
      </div>

      <Card>
        {carregando && pagina === null ? (
          <Carregando />
        ) : !carregando && erroLivros ? (
          <Vazio titulo="Não foi possível carregar" descricao={erroLivros.message} />
        ) : pagina === null || pagina.itens.length === 0 ? (
          <Vazio titulo="Nenhum livro encontrado" descricao="Ajuste a busca ou os filtros." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Título</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Autor</th>
                  <th className="px-4 py-2 font-medium">Nível</th>
                  {podeEditar && <th className="px-4 py-2 font-medium">Nível oficial</th>}
                  <th className="px-4 py-2 text-right font-medium">Leituras</th>
                  {podeEditar && <th className="px-4 py-2" />}
                </tr>
              </thead>
              <tbody>
                {pagina.itens.map((livro) => (
                  <tr key={livro.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      <span className="font-medium">{livro.titulo}</span>
                      {livro.categoria && (
                        <span className="ml-2 text-xs text-zinc-400">{livro.categoria}</span>
                      )}
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{livro.autor ?? "—"}</td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex flex-wrap items-center gap-1.5">
                        <Badge tom="destaque">{livro.nivel_codigo}</Badge>
                        {podeEditar && livro.divergente && <Badge tom="alerta">Divergente</Badge>}
                      </span>
                    </td>
                    {podeEditar && (
                      <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-300">
                        {livro.nivel_oficial ?? (
                          <span className="text-xs text-zinc-400">
                            fora do catálogo
                            {/* Sem nível oficial, o que existe é o nível do
                                RELATÓRIO da escola — dito com esse nome, nunca
                                como se fosse do Elefante. */}
                            {livro.nivel_fonte && ` · relatório: ${livro.nivel_fonte}`}
                          </span>
                        )}
                      </td>
                    )}
                    <td className="px-4 py-2.5 text-right tabular-nums">{numero(livro.leituras)}</td>
                    {podeEditar && (
                      <td className="px-4 py-2.5 text-right">
                        <button
                          aria-label={`Editar ${livro.titulo}`}
                          className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
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
                          <Pencil size={15} />
                        </button>
                        <button
                          aria-label={`Excluir ${livro.titulo}`}
                          className="rounded-lg p-1.5 text-zinc-500 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10 dark:hover:text-red-400"
                          onClick={() => excluir(livro)}
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pagina && pagina.total > pagina.por_pagina && (
          <div className="flex items-center justify-between border-t border-zinc-200 px-4 py-3 text-sm dark:border-zinc-800">
            <span className="text-zinc-500 dark:text-zinc-400">
              {numero(pagina.total)} livros · página {pagina.pagina} de {totalPaginas}
            </span>
            <div className="flex gap-2">
              <Botao variante="neutro" disabled={numeroPagina <= 1} onClick={() => setNumeroPagina(numeroPagina - 1)}>
                Anterior
              </Botao>
              <Botao variante="neutro" disabled={numeroPagina >= totalPaginas} onClick={() => setNumeroPagina(numeroPagina + 1)}>
                Próxima
              </Botao>
            </div>
          </div>
        )}
      </Card>

      {podeEditar && (
        <Modal
          titulo={formulario?.id === null ? "Novo livro" : "Editar livro"}
          aberto={formulario !== null}
          aoFechar={() => setFormulario(null)}
        >
          {formulario && (
            <div className="space-y-3">
              <Campo rotulo="Título">
                <input className={estiloInput} value={formulario.titulo}
                       onChange={(e) => setFormulario({ ...formulario, titulo: e.target.value })} />
              </Campo>
              <Campo rotulo="Autor">
                <input className={estiloInput} value={formulario.autor}
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
                  <input type="number" min={1} className={estiloInput} value={formulario.paginas}
                         onChange={(e) => setFormulario({ ...formulario, paginas: e.target.value })} />
                </Campo>
              </div>
              <Campo rotulo="Categoria (opcional)">
                <input className={estiloInput} value={formulario.categoria}
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
                  <label className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={formulario.aplicar_ao_historico}
                      onChange={(e) =>
                        setFormulario({ ...formulario, aplicar_ao_historico: e.target.checked })
                      }
                    />
                    <span>
                      <strong>Aplicar também ao histórico.</strong> Reescreve o nível congelado das
                      leituras já registradas deste livro, recalcula a escola e fica no log de
                      auditoria. Pede confirmação antes de salvar.
                    </span>
                  </label>
                </>
              )}
              {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
              <div className="flex justify-end gap-2 pt-1">
                <Botao variante="neutro" onClick={() => setFormulario(null)} disabled={salvando}>Cancelar</Botao>
                <Botao onClick={salvar} disabled={salvando || !formulario.titulo.trim() || !formulario.nivel_codigo}>
                  {salvando ? "Salvando..." : "Salvar"}
                </Botao>
              </div>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
