import { Check, Copy, Pencil, School, UserPlus, X } from "lucide-react";
import { useState } from "react";

import { Badge, Botao, Campo, Card, Carregando, Mensagem, Modal, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api, ApiError } from "../lib/api";
import type { Professor, Turma } from "../lib/types";

// A gestão de turmas ganhou página própria: pages/Turmas.tsx

interface AcessoCriado {
  email: string;
  senha: string;
}

/** Modal "Adicionar professor": cria o professor, vincula a turma sob a sua
 *  responsabilidade e (opcional) cria a conta de acesso com senha gerada —
 *  mostrada UMA vez aqui (não fica salva; se for perdida, use Usuários →
 *  Redefinir senha para gerar um novo link de acesso). */
function ModalNovoProfessor({ aberto, turmas, aoFechar, aoCriar }: {
  aberto: boolean;
  turmas: Turma[];
  aoFechar: () => void;
  aoCriar: () => void;
}) {
  const { escolaId } = useApp();
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [turmaId, setTurmaId] = useState<string>("");
  const [criarAcesso, setCriarAcesso] = useState(true);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [acesso, setAcesso] = useState<AcessoCriado | null>(null);
  const [criadoSemAcesso, setCriadoSemAcesso] = useState(false);

  function limparEFechar() {
    setNome(""); setEmail(""); setTurmaId(""); setCriarAcesso(true);
    setErro(""); setAcesso(null); setCriadoSemAcesso(false);
    aoFechar();
  }

  async function salvar() {
    if (!escolaId || !nome.trim() || !email.trim()) return;
    setOcupado(true);
    setErro("");
    try {
      const r = await api<{ acesso: AcessoCriado | null }>(
        `/escolas/${escolaId}/professores/completo`,
        {
          method: "POST",
          body: JSON.stringify({
            nome: nome.trim(),
            email: email.trim(),
            turma_id: turmaId ? Number(turmaId) : null,
            criar_acesso: criarAcesso,
          }),
        },
      );
      aoCriar();
      if (r.acesso) setAcesso(r.acesso);
      else setCriadoSemAcesso(true);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Modal titulo="Adicionar professor" aberto={aberto} aoFechar={limparEFechar}>
      {acesso ? (
        <div className="space-y-4">
          <Mensagem tipo="ok">
            Professor cadastrado! Anote e entregue o acesso abaixo. Por
            segurança a senha não fica salva e não poderá ser vista de novo —
            se for perdida, use Usuários → Redefinir senha para gerar um novo link.
          </Mensagem>
          <div className="space-y-2 rounded-lg bg-zinc-100 p-4 text-sm dark:bg-zinc-800">
            <p><span className="text-zinc-500">E-mail:</span> <strong>{acesso.email}</strong></p>
            <p><span className="text-zinc-500">Senha:</span>{" "}
              <strong className="font-mono">{acesso.senha}</strong></p>
          </div>
          <div className="flex gap-2">
            <Botao
              variante="neutro"
              onClick={() => navigator.clipboard.writeText(
                `Acesso ao Constela Edu\nE-mail: ${acesso.email}\nSenha: ${acesso.senha}`)}
            >
              <Copy size={14} /> Copiar acesso
            </Botao>
            <Botao onClick={limparEFechar}>Concluir</Botao>
          </div>
        </div>
      ) : criadoSemAcesso ? (
        <div className="space-y-4">
          <Mensagem tipo="ok">Professor cadastrado (sem conta de acesso).</Mensagem>
          <Botao onClick={limparEFechar}>Concluir</Botao>
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => { e.preventDefault(); salvar(); }}
        >
          <Campo rotulo="Nome do professor">
            <input className={estiloInput} value={nome} required minLength={2}
                   onChange={(e) => setNome(e.target.value)} disabled={ocupado} />
          </Campo>
          <Campo rotulo="E-mail (será o login do professor)">
            <input type="email" className={estiloInput} value={email} required
                   onChange={(e) => setEmail(e.target.value)} disabled={ocupado} />
          </Campo>
          <Campo rotulo="Turma sob responsabilidade">
            <select className={estiloInput} value={turmaId}
                    onChange={(e) => setTurmaId(e.target.value)} disabled={ocupado}>
              <option value="">— escolher depois —</option>
              {turmas.map((t) => (
                <option key={t.id} value={t.id}>{t.nome}</option>
              ))}
            </select>
          </Campo>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-indigo-600"
                   checked={criarAcesso}
                   onChange={(e) => setCriarAcesso(e.target.checked)}
                   disabled={ocupado} />
            Criar conta de acesso (aparece em Usuários, com senha gerada)
          </label>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Com a conta, o professor entra no sistema e vê somente as turmas
            dele — posição e pontos dos alunos, sem os dados de gestão.
          </p>
          {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
          <div className="flex justify-end gap-2">
            <Botao type="button" variante="neutro" onClick={limparEFechar} disabled={ocupado}>
              Cancelar
            </Botao>
            <Botao type="submit" disabled={ocupado || !nome.trim() || !email.trim()}>
              {ocupado ? "Salvando..." : "Adicionar"}
            </Botao>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function Professores() {
  const { escolaId, usuario } = useApp();
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  // Secretaria (rede vinculada, não-global): acompanha a rede, mas NÃO altera
  // dados da escola — some com os controles de escrita (o backend também barra).
  const secretaria = !usuario?.is_global && usuario?.rede_id != null;
  const podeEditar = gestor && !secretaria;
  const { dados: professores, erro, carregando, recarregar: recarregarProfessores } =
    useApi<Professor[]>(escolaId ? `/escolas/${escolaId}/professores` : null);
  const { dados: turmas, recarregar: recarregarTurmas } =
    useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null);
  const [modalAberto, setModalAberto] = useState(false);
  // Edição inline do NOME do professor (ex.: completar um apelido da importação).
  const [editando, setEditando] = useState<number | null>(null);
  const [nomeEdit, setNomeEdit] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erroEdicao, setErroEdicao] = useState("");

  // Refaz as duas buscas após criar um professor (que vincula turma).
  function carregar() {
    recarregarProfessores();
    recarregarTurmas();
  }

  async function salvarNome(prof: Professor) {
    const novo = nomeEdit.trim();
    if (!escolaId || novo.length < 2 || novo === prof.nome) { setEditando(null); return; }
    setSalvando(true);
    setErroEdicao("");
    try {
      await api(`/escolas/${escolaId}/professores/${prof.id}`,
        { method: "PATCH", body: JSON.stringify({ nome: novo }) });
      setEditando(null);
      recarregarProfessores();
    } catch (excecao) {
      // Nunca engolir o erro em silêncio: sem isto, um 403/validação fazia o
      // salvar "não acontecer nada" (era exatamente o sintoma relatado).
      setErroEdicao(excecao instanceof ApiError ? excecao.message : "Não foi possível salvar o nome.");
    } finally {
      setSalvando(false);
    }
  }

  // Turmas de cada professor (Turma.professor_id → nomes), para a coluna.
  const turmasDe = (professorId: number) =>
    (turmas ?? []).filter((t) => t.professor_id === professorId).map((t) => t.nome);

  return (
    <div>
      <PageHeader
        titulo="Professores"
        descricao="Equipe cadastrada nesta escola e as turmas sob responsabilidade de cada um."
        acoes={podeEditar ? (
          <Botao onClick={() => setModalAberto(true)}>
            <UserPlus size={15} /> Adicionar professor
          </Botao>
        ) : undefined}
      />
      {erroEdicao && (
        <div className="mb-4"><Mensagem tipo="erro">{erroEdicao}</Mensagem></div>
      )}
      <Card>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro.message} />
        ) : (professores ?? []).length === 0 ? (
          <Vazio titulo="Nenhum professor cadastrado"
                 descricao="Use “Adicionar professor” para cadastrar o primeiro." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <th className="px-4 py-2 font-medium">Nome</th>
                <th className="px-4 py-2 font-medium">E-mail</th>
                <th className="px-4 py-2 font-medium">Turmas</th>
                {podeEditar && <th className="w-16 px-4 py-2" />}
              </tr>
            </thead>
            <tbody>
              {(professores ?? []).map((professor) => (
                <tr key={professor.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <td className="px-4 py-2.5 font-medium">
                    {editando === professor.id ? (
                      <input
                        className={`${estiloInput} w-64`}
                        value={nomeEdit}
                        autoFocus
                        minLength={2}
                        disabled={salvando}
                        onChange={(e) => setNomeEdit(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") salvarNome(professor);
                          if (e.key === "Escape") setEditando(null);
                        }}
                      />
                    ) : (
                      <span className="inline-flex items-center gap-2">
                        <School size={14} className="text-zinc-300 dark:text-zinc-600" />
                        {professor.nome}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-zinc-500 dark:text-zinc-400">{professor.email ?? "—"}</td>
                  <td className="px-4 py-2.5">
                    <span className="flex flex-wrap gap-1">
                      {turmasDe(professor.id).length === 0
                        ? <span className="text-zinc-400">—</span>
                        : turmasDe(professor.id).map((nome) => (
                            <Badge key={nome} tom="destaque">{nome}</Badge>
                          ))}
                    </span>
                  </td>
                  {podeEditar && (
                    <td className="px-4 py-2.5 text-right">
                      {editando === professor.id ? (
                        <span className="inline-flex gap-1">
                          <button
                            type="button"
                            title="Salvar"
                            disabled={salvando}
                            onClick={() => salvarNome(professor)}
                            className="rounded p-1 text-emerald-600 hover:bg-emerald-50 disabled:opacity-40 dark:hover:bg-emerald-500/10"
                          >
                            <Check size={16} />
                          </button>
                          <button
                            type="button"
                            title="Cancelar"
                            onClick={() => setEditando(null)}
                            className="rounded p-1 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                          >
                            <X size={16} />
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          title="Editar nome"
                          onClick={() => { setEditando(professor.id); setNomeEdit(professor.nome); }}
                          className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-indigo-600 dark:hover:bg-zinc-800 dark:hover:text-indigo-400"
                        >
                          <Pencil size={15} />
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <ModalNovoProfessor
        aberto={modalAberto}
        turmas={turmas ?? []}
        aoFechar={() => setModalAberto(false)}
        aoCriar={carregar}
      />
    </div>
  );
}
