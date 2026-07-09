import { Search, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import AcoesAluno from "../components/AcoesAluno";
import { Botao, Campo, Card, Carregando, Mensagem, Modal, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import type { PaginaAlunos, Turma } from "../lib/types";

/** Modal "Adicionar aluno": cadastro completo — dados básicos + ficha
 *  cadastral (RA, responsável, contato, endereço), como na Lista Piloto. */
function ModalNovoAluno({ aberto, turmas, aoFechar, aoCriar }: {
  aberto: boolean;
  turmas: Turma[];
  aoFechar: () => void;
  aoCriar: () => void;
}) {
  const { escolaId } = useApp();
  const [nome, setNome] = useState("");
  const [turmaId, setTurmaId] = useState<string>("");
  const [numero, setNumero] = useState("");
  const [nascimento, setNascimento] = useState("");
  const [ficha, setFicha] = useState<Record<string, string>>({});
  const [observacoes, setObservacoes] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  const CAMPOS_FICHA: Array<[string, string]> = [
    ["ra", "RA"],
    ["rm", "RM"],
    ["responsavel", "Responsável"],
    ["telefone", "Telefone"],
    ["endereco", "Endereço"],
    ["bairro", "Bairro"],
  ];

  function limpar() {
    setNome(""); setTurmaId(""); setNumero(""); setNascimento("");
    setFicha({}); setObservacoes(""); setAviso(null);
  }

  async function salvar(continuar: boolean) {
    if (!escolaId || !nome.trim() || !turmaId) return;
    setOcupado(true);
    setAviso(null);
    try {
      await api(`/escolas/${escolaId}/alunos`, {
        method: "POST",
        body: JSON.stringify({
          nome: nome.trim(),
          turma_id: Number(turmaId),
          numero_chamada: numero ? Number(numero) : null,
          data_nascimento: nascimento || null,
          observacoes: observacoes.trim() || null,
          ficha: Object.fromEntries(
            Object.entries(ficha).filter(([, v]) => v.trim())),
        }),
      });
      aoCriar();
      if (continuar) {
        const turmaMantida = turmaId;
        limpar();
        setTurmaId(turmaMantida);
        setAviso({ tipo: "ok", texto: `${nome.trim()} adicionado(a)! Cadastre o próximo.` });
      } else {
        limpar();
        aoFechar();
      }
    } catch (excecao) {
      setAviso({
        tipo: "erro",
        texto: excecao instanceof Error ? excecao.message : "Não foi possível salvar.",
      });
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Modal titulo="Adicionar aluno" aberto={aberto}
           aoFechar={() => { limpar(); aoFechar(); }}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); salvar(false); }}>
        <Campo rotulo="Nome completo">
          <input className={estiloInput} value={nome} required minLength={2}
                 onChange={(e) => setNome(e.target.value)} disabled={ocupado} />
        </Campo>
        <div className="grid gap-3 sm:grid-cols-3">
          <Campo rotulo="Turma">
            <select className={estiloInput} value={turmaId} required
                    onChange={(e) => setTurmaId(e.target.value)} disabled={ocupado}>
              <option value="">—</option>
              {turmas.map((t) => (
                <option key={t.id} value={t.id}>{t.nome}</option>
              ))}
            </select>
          </Campo>
          <Campo rotulo="Nº chamada">
            <input type="number" min={1} className={estiloInput} value={numero}
                   onChange={(e) => setNumero(e.target.value)} disabled={ocupado} />
          </Campo>
          <Campo rotulo="Nascimento">
            <input type="date" className={estiloInput} value={nascimento}
                   onChange={(e) => setNascimento(e.target.value)} disabled={ocupado} />
          </Campo>
        </div>

        <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">
          Ficha cadastral (opcional)
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {CAMPOS_FICHA.map(([chave, rotulo]) => (
            <Campo key={chave} rotulo={rotulo}>
              <input className={estiloInput} value={ficha[chave] ?? ""}
                     onChange={(e) => setFicha({ ...ficha, [chave]: e.target.value })}
                     disabled={ocupado} />
            </Campo>
          ))}
        </div>
        <Campo rotulo="Observações">
          <textarea className={estiloInput} rows={2} value={observacoes}
                    onChange={(e) => setObservacoes(e.target.value)} disabled={ocupado} />
        </Campo>

        {aviso && <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>}
        <div className="flex flex-wrap justify-end gap-2">
          <Botao type="button" variante="neutro" disabled={ocupado}
                 onClick={() => { limpar(); aoFechar(); }}>
            Cancelar
          </Botao>
          <Botao type="button" variante="neutro"
                 disabled={ocupado || !nome.trim() || !turmaId}
                 onClick={() => salvar(true)}>
            Salvar e adicionar outro
          </Botao>
          <Botao type="submit" disabled={ocupado || !nome.trim() || !turmaId}>
            {ocupado ? "Salvando..." : "Salvar"}
          </Botao>
        </div>
      </form>
    </Modal>
  );
}

export default function Alunos() {
  const { escolaId, usuario } = useApp();
  // Professor não gerencia alunos: sem menu de ações (editar/arquivar/excluir).
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [turmaId, setTurmaId] = useState<string>("");
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [pagina, setPagina] = useState(1);
  const [dados, setDados] = useState<PaginaAlunos | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [modalNovo, setModalNovo] = useState(false);

  useEffect(() => {
    if (!escolaId) return;
    api<Turma[]>(`/escolas/${escolaId}/turmas`).then(setTurmas).catch(() => setTurmas([]));
  }, [escolaId]);

  // Busca com pequeno atraso para não consultar a cada tecla (PRD §23)
  useEffect(() => {
    const temporizador = setTimeout(() => {
      setBuscaAplicada(busca);
      setPagina(1);
    }, 300);
    return () => clearTimeout(temporizador);
  }, [busca]);

  const carregar = useCallback(() => {
    if (!escolaId) return;
    setCarregando(true);
    const parametros = new URLSearchParams({ pagina: String(pagina), por_pagina: "25" });
    if (buscaAplicada) parametros.set("busca", buscaAplicada);
    if (turmaId) parametros.set("turma_id", turmaId);
    api<PaginaAlunos>(`/escolas/${escolaId}/alunos?${parametros}`)
      .then(setDados)
      .catch(() => setDados(null))
      .finally(() => setCarregando(false));
  }, [escolaId, buscaAplicada, turmaId, pagina]);

  useEffect(carregar, [carregar]);

  const totalPaginas = dados ? Math.max(1, Math.ceil(dados.total / dados.por_pagina)) : 1;

  return (
    <div>
      <PageHeader
        titulo="Alunos"
        descricao="Pesquise, filtre e abra o perfil completo de cada aluno."
        acoes={gestor ? (
          <Botao onClick={() => setModalNovo(true)}>
            <UserPlus size={15} /> Adicionar aluno
          </Botao>
        ) : undefined}
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="relative flex-1 basis-56">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            placeholder="Pesquisar por nome..."
            className="w-full rounded-lg border border-zinc-300 bg-white py-2 pl-9 pr-3 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            value={busca}
            onChange={(evento) => setBusca(evento.target.value)}
          />
        </label>
        <select
          aria-label="Filtrar por turma"
          className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          value={turmaId}
          onChange={(evento) => {
            setTurmaId(evento.target.value);
            setPagina(1);
          }}
        >
          <option value="">Todas as turmas</option>
          {turmas.map((turma) => (
            <option key={turma.id} value={turma.id}>
              {turma.nome}
            </option>
          ))}
        </select>
      </div>

      <Card>
        {carregando ? (
          <Carregando />
        ) : !dados || dados.itens.length === 0 ? (
          <Vazio titulo="Nenhum aluno encontrado" descricao="Ajuste a pesquisa ou os filtros." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Nome</th>
                  <th className="px-4 py-2 font-medium">Turma</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Série</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Nº chamada</th>
                  {gestor && <th className="w-12 px-4 py-2"></th>}
                </tr>
              </thead>
              <tbody>
                {dados.itens.map((aluno) => (
                  <tr key={aluno.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${aluno.id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {aluno.nome}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-300">{aluno.turma}</td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 sm:table-cell">{aluno.ano_escolar}</td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 sm:table-cell">{aluno.numero_chamada ?? "—"}</td>
                    {gestor && (
                      <td className="px-4 py-2.5 text-right">
                        {escolaId && (
                          <AcoesAluno aluno={aluno} escolaId={escolaId} aoMudar={carregar} />
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {dados && dados.total > 0 && (
        <div className="mt-3 flex items-center justify-between text-sm text-zinc-500 dark:text-zinc-400">
          <span>
            {dados.total} aluno{dados.total === 1 ? "" : "s"} · página {dados.pagina} de {totalPaginas}
          </span>
          <div className="flex gap-2">
            <Botao variante="neutro" disabled={pagina <= 1} onClick={() => setPagina(pagina - 1)}>
              Anterior
            </Botao>
            <Botao variante="neutro" disabled={pagina >= totalPaginas} onClick={() => setPagina(pagina + 1)}>
              Próxima
            </Botao>
          </div>
        </div>
      )}

      <ModalNovoAluno
        aberto={modalNovo}
        turmas={turmas}
        aoFechar={() => setModalNovo(false)}
        aoCriar={carregar}
      />
    </div>
  );
}
