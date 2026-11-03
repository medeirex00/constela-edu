import { ChevronLeft, ChevronRight, GraduationCap, UserPlus, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import AcoesAluno from "../components/AcoesAluno";
import ModalAlunosDuplicados from "../components/ModalAlunosDuplicados";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  AvatarAluno,
  BarraFiltros,
  CabecalhoCartao,
  CampoBusca,
  EsqueletoLista,
  SelectNativo,
} from "../components/PessoasUi";
import {
  Botao,
  Campo,
  Card,
  Chip,
  Erro,
  Mensagem,
  Modal,
  PageHeader,
  RotuloSecao,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { numero as fmtNumero } from "../lib/formato";
import type { PaginaAlunos, Turma } from "../lib/types";

// Tabela no celular (< 640 px): células mais justas.
const th = `${classesTabela.th} max-sm:px-3`;
const td = `${classesTabela.td} max-sm:px-3`;

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
    <Modal titulo="Adicionar aluno" aberto={aberto} largura="max-w-2xl"
           aoFechar={() => { limpar(); aoFechar(); }}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); salvar(false); }}>
        <Campo rotulo="Nome completo">
          <input className={estiloInput} value={nome} required minLength={2}
                 onChange={(e) => setNome(e.target.value)} disabled={ocupado} />
        </Campo>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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

        <div className="rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/40">
          <RotuloSecao className="mb-3">Ficha cadastral (opcional)</RotuloSecao>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {CAMPOS_FICHA.map(([chave, rotulo]) => (
              <Campo key={chave} rotulo={rotulo}>
                <input className={estiloInput} value={ficha[chave] ?? ""}
                       onChange={(e) => setFicha({ ...ficha, [chave]: e.target.value })}
                       disabled={ocupado} />
              </Campo>
            ))}
          </div>
        </div>
        <Campo rotulo="Observações">
          <textarea className={estiloInput} rows={2} value={observacoes}
                    onChange={(e) => setObservacoes(e.target.value)} disabled={ocupado} />
        </Campo>

        {aviso && <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>}
        <div className="flex flex-wrap justify-end gap-2.5 pt-1">
          <Botao type="button" variante="secundario" disabled={ocupado}
                 onClick={() => { limpar(); aoFechar(); }}>
            Cancelar
          </Botao>
          <Botao type="button" variante="secundario"
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
  // Secretaria (rede vinculada, não-global) acompanha mas não opera a escola.
  const secretaria = !usuario?.is_global && usuario?.rede_id != null;
  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [turmaId, setTurmaId] = useState<string>("");
  const [pagina, setPagina] = useState(1);
  const [modalNovo, setModalNovo] = useState(false);
  const [modalDup, setModalDup] = useState(false);

  // Turmas para o filtro e o modal de cadastro (array sempre pronto para render).
  const { dados: turmasDados } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null,
  );
  const turmas = turmasDados ?? [];

  // Busca com pequeno atraso para não consultar a cada tecla (PRD §23)
  useEffect(() => {
    const temporizador = setTimeout(() => {
      setBuscaAplicada(busca);
      setPagina(1);
    }, 300);
    return () => clearTimeout(temporizador);
  }, [busca]);

  // Lista paginada: a URL muda com página/busca/turma e o hook rebusca sozinho.
  const parametros = new URLSearchParams({ pagina: String(pagina), por_pagina: "25" });
  if (buscaAplicada) parametros.set("busca", buscaAplicada);
  if (turmaId) parametros.set("turma_id", turmaId);
  const { dados, erro, carregando, recarregar } = useApi<PaginaAlunos>(
    escolaId ? `/escolas/${escolaId}/alunos?${parametros}` : null,
  );

  const totalPaginas = dados ? Math.max(1, Math.ceil(dados.total / dados.por_pagina)) : 1;
  const comFiltro = Boolean(buscaAplicada || turmaId);
  const inicio = dados && dados.total > 0 ? (dados.pagina - 1) * dados.por_pagina + 1 : 0;
  const fim = dados ? Math.min(dados.total, inicio + dados.itens.length - 1) : 0;

  return (
    <div>
      <PageHeader
        titulo="Alunos"
        descricao="Pesquise, filtre e abra o perfil completo de cada aluno."
        acoes={gestor ? (
          <>
            {!secretaria && (
              <Botao variante="secundario" onClick={() => setModalDup(true)}>
                <UsersRound size={16} aria-hidden /> Fundir duplicatas
              </Botao>
            )}
            <Botao onClick={() => setModalNovo(true)}>
              <UserPlus size={16} aria-hidden /> Adicionar aluno
            </Botao>
          </>
        ) : undefined}
      />

      <BarraFiltros>
        <CampoBusca
          rotulo="Pesquisar aluno pelo nome"
          placeholder="Pesquisar por nome..."
          className="flex-1 basis-60"
          value={busca}
          onChange={(evento) => setBusca(evento.target.value)}
        />
        <SelectNativo
          aria-label="Filtrar por turma"
          className="w-full sm:w-56"
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
        </SelectNativo>
      </BarraFiltros>

      <Card className="overflow-hidden">
        <CabecalhoCartao
          titulo={comFiltro ? "Resultado da pesquisa" : "Alunos ativos"}
          contagem={dados ? `${fmtNumero(dados.total)} aluno${dados.total === 1 ? "" : "s"}` : undefined}
        />
        {!escolaId ? (
          <Vazio icone={GraduationCap} titulo="Selecione uma escola"
                 descricao="Escolha a escola no cartão Escola, no fim do menu lateral, para ver os alunos dela." />
        ) : carregando ? (
          <EsqueletoLista texto="Carregando alunos..." />
        ) : erro ? (
          <Erro descricao={erro.message} aoTentar={recarregar} />
        ) : !dados || dados.itens.length === 0 ? (
          comFiltro ? (
            <Vazio icone={GraduationCap} titulo="Nenhum aluno encontrado"
                   descricao="Ajuste a pesquisa ou os filtros." />
          ) : (
            <Vazio icone={GraduationCap} titulo="Nenhum aluno ativo nesta escola"
                   descricao="Os alunos aparecem aqui depois do cadastro ou da importação da Lista Piloto." />
          )
        ) : (
          // Celular (< 640 px): a tabela rola de lado dentro do cartão, com o aviso em
          // texto acima dela, e o menu ⋮ fica preso à direita (`presa-celular`). O avatar
          // (decorativo) some e o nome tem base de 8,5rem (duas linhas, não uma palavra por
          // linha). O Nº de chamada vem também no celular (o cabeçalho quebra em duas
          // linhas); a Série segue fora abaixo de 640 px porque já está no chip da turma.
          <TabelaRolavel rotulo="Alunos: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  <th className={th}>Aluno</th>
                  <th className={th}>Turma</th>
                  <th className={`hidden sm:table-cell ${th}`}>Série</th>
                  <th className={`text-right max-sm:whitespace-normal ${th}`}>Nº chamada</th>
                  {gestor && <th className={`w-14 ${classesTabela.th} presa-celular max-sm:px-2`}><span className="sr-only">Ações</span></th>}
                </tr>
              </thead>
              <tbody>
                {dados.itens.map((aluno) => (
                  <tr key={aluno.id} className={classesTabela.tr}>
                    <td className={td}>
                      <div className="flex items-center gap-3">
                        <span className="hidden shrink-0 sm:flex">
                          <AvatarAluno nome={aluno.nome} chave={aluno.id} foto={aluno.foto_url} />
                        </span>
                        <Link
                          to={`/alunos/${aluno.id}`}
                          className="min-w-0 font-semibold text-zinc-900 transition-colors hover:text-indigo-600 max-sm:min-w-[8.5rem] dark:text-zinc-100 dark:hover:text-indigo-300"
                        >
                          {aluno.nome}
                        </Link>
                      </div>
                    </td>
                    <td className={td}>
                      {aluno.turma ? <Chip>{aluno.turma}</Chip> : <span className="text-zinc-500">—</span>}
                    </td>
                    <td className={`hidden text-zinc-500 sm:table-cell dark:text-zinc-400 ${td}`}>
                      {aluno.ano_escolar}
                    </td>
                    <td className={`text-right tabular-nums text-zinc-500 dark:text-zinc-400 ${td}`}>
                      {aluno.numero_chamada ?? "—"}
                    </td>
                    {gestor && (
                      <td className={`text-right ${classesTabela.td} presa-celular max-sm:px-2`}>
                        {escolaId && (
                          <AcoesAluno aluno={aluno} escolaId={escolaId} aoMudar={recarregar} />
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}

        {dados && dados.total > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 px-5 py-3.5 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            <span className="tabular-nums">
              Mostrando {fmtNumero(inicio)}–{fmtNumero(fim)} de {fmtNumero(dados.total)} · página {dados.pagina} de {totalPaginas}
            </span>
            <div className="flex gap-2">
              <Botao variante="secundario" tamanho="sm" disabled={pagina <= 1} onClick={() => setPagina(pagina - 1)}>
                <ChevronLeft size={14} aria-hidden /> Anterior
              </Botao>
              <Botao variante="secundario" tamanho="sm" disabled={pagina >= totalPaginas} onClick={() => setPagina(pagina + 1)}>
                Próxima <ChevronRight size={14} aria-hidden />
              </Botao>
            </div>
          </div>
        )}
      </Card>

      <ModalNovoAluno
        aberto={modalNovo}
        turmas={turmas}
        aoFechar={() => setModalNovo(false)}
        aoCriar={recarregar}
      />

      {modalDup && escolaId && (
        <ModalAlunosDuplicados
          escolaId={escolaId}
          aoFechar={() => setModalDup(false)}
          aoConcluir={recarregar}
        />
      )}
    </div>
  );
}
