import { Check, Copy, GraduationCap, Pencil, Trash2, UserPlus, X } from "lucide-react";
import { useState } from "react";

import { CabecalhoCartao, EsqueletoLista, copiarTexto, estiloCheckbox } from "../components/PessoasUi";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Avatar,
  Botao,
  Campo,
  Card,
  Chip,
  Confirmacao,
  EmailQuebravel,
  Erro,
  Mensagem,
  Modal,
  PageHeader,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api, ApiError } from "../lib/api";
import type { Professor, Turma } from "../lib/types";

// A gestão de turmas ganhou página própria: pages/Turmas.tsx

interface AcessoCriado {
  email: string;
  senha: string;
}

// No celular (< 640 px) os botões da linha ganham 40 px (alvo de toque).
const estiloBotaoLinha =
  "grid h-9 w-9 place-items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40 max-sm:h-10 max-sm:w-10";

// Celular (< 640 px): células mais justas na tabela da equipe.
const th = `${classesTabela.th} max-sm:px-3`;
const td = `${classesTabela.td} max-sm:px-3`;

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
  const [copiado, setCopiado] = useState(false);

  function limparEFechar() {
    setNome(""); setEmail(""); setTurmaId(""); setCriarAcesso(true);
    setErro(""); setAcesso(null); setCriadoSemAcesso(false); setCopiado(false);
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
          <div className="space-y-2 rounded-2xl border border-indigo-100 bg-indigo-50 p-4 text-sm dark:border-indigo-500/20 dark:bg-indigo-500/10">
            <p><span className="text-zinc-600 dark:text-zinc-300">E-mail:</span> <strong>{acesso.email}</strong></p>
            <p><span className="text-zinc-600 dark:text-zinc-300">Senha:</span>{" "}
              <strong className="select-all font-mono">{acesso.senha}</strong></p>
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Botao
              variante="secundario"
              onClick={() => copiarTexto(
                `Acesso ao Constela Edu\nE-mail: ${acesso.email}\nSenha: ${acesso.senha}`,
                () => setCopiado(true))}
            >
              {copiado ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />}
              {copiado ? "Copiado!" : "Copiar acesso"}
            </Botao>
            <Botao onClick={limparEFechar}>Concluir</Botao>
          </div>
          <p role="status" aria-live="polite" className="sr-only">{copiado ? "Acesso copiado." : ""}</p>
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
          <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-zinc-200/80 p-3.5 text-sm transition-colors hover:border-indigo-200 dark:border-zinc-700">
            <input type="checkbox" className={`mt-0.5 ${estiloCheckbox}`}
                   checked={criarAcesso}
                   onChange={(e) => setCriarAcesso(e.target.checked)}
                   disabled={ocupado} />
            <span>
              <span className="font-medium">Criar conta de acesso (aparece em Usuários, com senha gerada)</span>
              <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                Com a conta, o professor entra no sistema e vê somente as turmas
                dele — posição e pontos dos alunos, sem os dados de gestão.
              </span>
            </span>
          </label>
          {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
          <div className="flex justify-end gap-2.5 pt-1">
            <Botao type="button" variante="secundario" onClick={limparEFechar} disabled={ocupado}>
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
  // Edição inline do NOME e do E-MAIL do professor (ex.: completar um apelido
  // ou corrigir o e-mail vindos da importação).
  const [editando, setEditando] = useState<number | null>(null);
  const [nomeEdit, setNomeEdit] = useState("");
  const [emailEdit, setEmailEdit] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erroEdicao, setErroEdicao] = useState("");
  // Exclusão: professor pendente de confirmação + estado do request + aviso.
  const [excluir, setExcluir] = useState<Professor | null>(null);
  const [removendo, setRemovendo] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  function abrirEdicao(prof: Professor) {
    setEditando(prof.id);
    setNomeEdit(prof.nome);
    setEmailEdit(prof.email ?? "");
    setErroEdicao("");
  }

  // Refaz as duas buscas após criar um professor (que vincula turma).
  function carregar() {
    recarregarProfessores();
    recarregarTurmas();
  }

  async function salvarEdicao(prof: Professor) {
    if (!escolaId) return;
    const novoNome = nomeEdit.trim();
    const novoEmail = emailEdit.trim();
    if (novoNome.length < 2) { setErroEdicao("O nome precisa ter ao menos 2 letras."); return; }
    const mudouNome = novoNome !== prof.nome;
    // Só troca o e-mail se preenchido e diferente (esta tela não apaga e-mail).
    const mudouEmail = novoEmail !== "" && novoEmail.toLowerCase() !== (prof.email ?? "").toLowerCase();
    if (!mudouNome && !mudouEmail) { setEditando(null); return; }
    const corpo: { nome?: string; email?: string } = {};
    if (mudouNome) corpo.nome = novoNome;
    if (mudouEmail) corpo.email = novoEmail;
    setSalvando(true);
    setErroEdicao("");
    try {
      await api(`/escolas/${escolaId}/professores/${prof.id}`,
        { method: "PATCH", body: JSON.stringify(corpo) });
      setEditando(null);
      recarregarProfessores();
    } catch (excecao) {
      // Nunca engolir o erro em silêncio: sem isto, um 403/validação fazia o
      // salvar "não acontecer nada" (era exatamente o sintoma relatado).
      setErroEdicao(excecao instanceof ApiError ? excecao.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  async function confirmarExclusao() {
    if (!escolaId || !excluir) return;
    setRemovendo(true);
    try {
      const r = await api<{ mensagem?: string }>(
        `/escolas/${escolaId}/professores/${excluir.id}`, { method: "DELETE" });
      setAviso({ tipo: "ok", texto: r.mensagem ?? "Professor removido." });
      setExcluir(null);
      carregar();                       // refaz professores + turmas
    } catch (excecao) {
      setAviso({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message
          : "Não foi possível concluir a exclusão. Tente de novo.",
      });
    } finally {
      setRemovendo(false);
    }
  }

  // Turmas de cada professor (Turma.professor_id → nomes), para a coluna.
  const turmasDe = (professorId: number) =>
    (turmas ?? []).filter((t) => t.professor_id === professorId).map((t) => t.nome);
  const lista = professores ?? [];

  return (
    <div>
      <PageHeader
        titulo="Professores"
        descricao="Equipe cadastrada nesta escola e as turmas sob responsabilidade de cada um."
        acoes={podeEditar ? (
          <Botao onClick={() => setModalAberto(true)}>
            <UserPlus size={16} aria-hidden /> Adicionar professor
          </Botao>
        ) : undefined}
      />
      {erroEdicao && (
        <div className="mb-4"><Mensagem tipo="erro">{erroEdicao}</Mensagem></div>
      )}
      {aviso && (
        <div className="mb-4"><Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem></div>
      )}
      <Card className="overflow-hidden">
        <CabecalhoCartao
          titulo="Equipe docente"
          contagem={professores ? `${lista.length} professor${lista.length === 1 ? "" : "es"}` : undefined}
        />
        {carregando ? (
          <EsqueletoLista texto="Carregando professores..." />
        ) : erro ? (
          <Erro descricao={erro.message} aoTentar={carregar} />
        ) : lista.length === 0 ? (
          <Vazio icone={GraduationCap} titulo="Nenhum professor cadastrado"
                 descricao={podeEditar ? "Use “Adicionar professor” para cadastrar o primeiro." : undefined} />
        ) : (
          // Celular (< 640 px): a tabela rola de lado dentro do cartão, com o aviso em
          // texto acima dela, e a coluna de ações (editar, excluir) fica presa à direita
          // (`presa-celular`). O avatar (decorativo) some no celular para dar espaço ao
          // nome; o e-mail só quebra no "@" (antes: `break-all`, letra a letra).
          <TabelaRolavel rotulo="Equipe docente: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  <th className={th}>Professor</th>
                  <th className={th}>E-mail</th>
                  <th className={th}>Turmas</th>
                  {podeEditar && <th className={`w-28 ${classesTabela.th} presa-celular max-sm:px-2`}><span className="sr-only">Ações</span></th>}
                </tr>
              </thead>
              <tbody>
                {lista.map((professor) => {
                  const suasTurmas = turmasDe(professor.id);
                  return (
                    <tr key={professor.id} className={classesTabela.tr}>
                      <td className={td}>
                        {editando === professor.id ? (
                          <input
                            className={`${estiloInput} min-w-[12rem]`}
                            value={nomeEdit}
                            autoFocus
                            minLength={2}
                            disabled={salvando}
                            aria-label="Nome do professor"
                            onChange={(e) => setNomeEdit(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") salvarEdicao(professor);
                              if (e.key === "Escape") setEditando(null);
                            }}
                          />
                        ) : (
                          <span className="flex items-center gap-3">
                            <Avatar nome={professor.nome} chave={`prof-${professor.id}`} className="hidden sm:grid" />
                            {/* Celular: até duas linhas (base de 8rem), não uma palavra por linha. */}
                            <span className="font-semibold text-zinc-900 max-sm:min-w-[8rem] dark:text-zinc-100">{professor.nome}</span>
                          </span>
                        )}
                      </td>
                      <td className={`text-zinc-500 dark:text-zinc-400 ${td}`}>
                        {editando === professor.id ? (
                          <input
                            type="email"
                            className={`${estiloInput} min-w-[12rem]`}
                            value={emailEdit}
                            placeholder="email@escola.com"
                            disabled={salvando}
                            aria-label="E-mail do professor"
                            onChange={(e) => setEmailEdit(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") salvarEdicao(professor);
                              if (e.key === "Escape") setEditando(null);
                            }}
                          />
                        ) : (
                          <span>{professor.email ? <EmailQuebravel email={professor.email} /> : "—"}</span>
                        )}
                      </td>
                      <td className={td}>
                        <span className="flex flex-wrap gap-1.5">
                          {suasTurmas.length === 0
                            ? <span className="text-zinc-500 dark:text-zinc-400">—</span>
                            : suasTurmas.map((nome) => <Chip key={nome}>{nome}</Chip>)}
                        </span>
                      </td>
                      {podeEditar && (
                        <td className="presa-celular px-4 py-2 text-right max-sm:px-2">
                          {editando === professor.id ? (
                            <span className="inline-flex gap-1">
                              <button
                                type="button"
                                title="Salvar"
                                aria-label={`Salvar nome e e-mail de ${professor.nome}`}
                                disabled={salvando}
                                onClick={() => salvarEdicao(professor)}
                                className={`${estiloBotaoLinha} text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/10`}
                              >
                                <Check size={17} aria-hidden />
                              </button>
                              <button
                                type="button"
                                title="Cancelar"
                                aria-label="Cancelar a edição"
                                onClick={() => setEditando(null)}
                                className={`${estiloBotaoLinha} text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800`}
                              >
                                <X size={17} aria-hidden />
                              </button>
                            </span>
                          ) : (
                            <span className="inline-flex gap-1">
                              <button
                                type="button"
                                title="Editar nome e e-mail"
                                aria-label={`Editar nome e e-mail de ${professor.nome}`}
                                onClick={() => abrirEdicao(professor)}
                                className={`${estiloBotaoLinha} text-zinc-500 hover:bg-indigo-50 hover:text-indigo-600 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-indigo-300`}
                              >
                                <Pencil size={16} aria-hidden />
                              </button>
                              <button
                                type="button"
                                title="Excluir professor"
                                aria-label={`Excluir ${professor.nome}`}
                                onClick={() => { setAviso(null); setExcluir(professor); }}
                                className={`${estiloBotaoLinha} text-zinc-500 hover:bg-rose-50 hover:text-rose-600 dark:text-zinc-400 dark:hover:bg-rose-500/10 dark:hover:text-rose-300`}
                              >
                                <Trash2 size={16} aria-hidden />
                              </button>
                            </span>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>

      <ModalNovoProfessor
        aberto={modalAberto}
        turmas={turmas ?? []}
        aoFechar={() => setModalAberto(false)}
        aoCriar={carregar}
      />

      <Confirmacao
        titulo="Excluir professor"
        aberto={excluir != null}
        aoFechar={() => setExcluir(null)}
        aoConfirmar={confirmarExclusao}
        rotuloConfirmar={removendo ? "Excluindo..." : "Excluir definitivamente"}
        variante="perigo"
        ocupado={removendo}
      >
        {excluir && (
          <p>
            Esta ação é{" "}
            <strong className="text-rose-600 dark:text-rose-400">irreversível</strong>. O professor{" "}
            <strong>{excluir.nome}</strong> será removido da equipe. As turmas dele{" "}
            <strong>não</strong> serão apagadas — apenas ficarão sem titular, para você revincular.
            A conta de acesso (login) continua em <strong>Usuários</strong>.
          </p>
        )}
      </Confirmacao>
    </div>
  );
}
