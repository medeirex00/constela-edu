/** Catálogo de Livros (PRD §57): busca, filtros e manutenção do acervo. */
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
import type { Livro, Nivel, PaginaLivros } from "../lib/types";

interface FormularioLivro {
  id: number | null;
  titulo: string;
  autor: string;
  nivel_codigo: string;
  categoria: string;
  paginas: string;
}

const FORM_VAZIO: FormularioLivro = { id: null, titulo: "", autor: "", nivel_codigo: "", categoria: "", paginas: "" };

export default function Livros() {
  const { escolaId, usuario } = useApp();
  const podeEditar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const [busca, setBusca] = useState("");
  const [nivel, setNivel] = useState("");
  const [numeroPagina, setNumeroPagina] = useState(1);
  const [formulario, setFormulario] = useState<FormularioLivro | null>(null);
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  // Códigos de nível para o filtro e o formulário (derivados da configuração de dificuldade).
  const { dados: dificuldade } = useApi<{ niveis: Nivel[] }>(
    escolaId ? `/escolas/${escolaId}/configuracoes/dificuldade` : null,
  );
  const codigos = dificuldade?.niveis.flatMap((n) => n.codigos) ?? [];

  // Página atual do catálogo — refeita quando busca/nível/página mudam.
  const parametros = new URLSearchParams({ pagina: String(numeroPagina) });
  if (busca) parametros.set("busca", busca);
  if (nivel) parametros.set("nivel", nivel);
  const {
    dados: pagina,
    erro: erroLivros,
    carregando,
    recarregar: carregar,
  } = useApi<PaginaLivros>(escolaId ? `/escolas/${escolaId}/livros?${parametros}` : null);

  async function salvar() {
    if (!escolaId || !formulario) return;
    setSalvando(true);
    setErro("");
    try {
      const corpo = {
        titulo: formulario.titulo.trim(),
        autor: formulario.autor.trim() || null,
        nivel_codigo: formulario.nivel_codigo,
        categoria: formulario.categoria.trim() || null,
        paginas: formulario.paginas ? Number(formulario.paginas) : null,
      };
      if (formulario.id === null) {
        await api(`/escolas/${escolaId}/livros`, { method: "POST", body: JSON.stringify(corpo) });
      } else {
        await api(`/escolas/${escolaId}/livros/${formulario.id}`, { method: "PATCH", body: JSON.stringify(corpo) });
      }
      setFormulario(null);
      carregar();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar o livro.");
    } finally {
      setSalvando(false);
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

  return (
    <div>
      <PageHeader
        titulo="Catálogo de Livros"
        descricao="Títulos, níveis e pontuação atual de cada livro do Elefante Letrado."
        acoes={
          podeEditar ? (
            <Botao onClick={() => { setFormulario({ ...FORM_VAZIO, nivel_codigo: codigos[0] ?? "" }); setErro(""); }}>
              <BookPlus size={15} /> Novo livro
            </Botao>
          ) : undefined
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
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
          {codigos.map((codigo) => (
            <option key={codigo} value={codigo}>{codigo}</option>
          ))}
        </select>
      </div>

      <Card>
        {carregando && pagina === null ? (
          <Carregando />
        ) : !carregando && erroLivros ? (
          <Vazio titulo="Não foi possível carregar" descricao={erroLivros.message} />
        ) : pagina === null || pagina.itens.length === 0 ? (
          <Vazio titulo="Nenhum livro encontrado" descricao="Ajuste a busca ou cadastre o primeiro livro do acervo." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Título</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Autor</th>
                  <th className="px-4 py-2 font-medium">Nível</th>
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
                    <td className="px-4 py-2.5"><Badge tom="destaque">{livro.nivel_codigo}</Badge></td>
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
                              categoria: livro.categoria ?? "",
                              paginas: livro.paginas ? String(livro.paginas) : "",
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
                  {codigos.map((codigo) => (
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
    </div>
  );
}
