/**
 * Gestão de usuários (PRD §18) — somente administradores.
 *
 * Cada usuário tem um menu de ações: Visualizar, Editar, Redefinir senha,
 * Alterar permissões, Desativar/Reativar, Excluir (lógica, preserva o
 * histórico) e — apenas para administradores globais — Excluir
 * Permanentemente, com confirmação extra digitando o e-mail.
 * As regras duras (própria conta, último admin) vivem no backend; a
 * interface apenas exibe as mensagens e evita oferecer o que será negado.
 */
import {
  AtSign,
  Check,
  Copy,
  Eye,
  GraduationCap,
  KeyRound,
  Pencil,
  RotateCcw,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  UserCheck,
  UserPlus,
  UsersRound,
  UserX,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import MenuSuspenso, { ItemMenu } from "../components/MenuSuspenso";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  AvatarAluno,
  CabecalhoCartao,
  ChipCargo,
  EsqueletoLista,
  PilulaSituacao,
  copiarTexto,
  estiloCheckbox,
  situacaoDaConta,
  tempoRelativo,
} from "../components/PessoasUi";
import {
  Botao,
  Campo,
  Card,
  Carregando,
  EmailQuebravel,
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
import { ApiError, api } from "../lib/api";
import { CARGOS, rotuloCargo } from "../lib/cargos";
import { dataHora } from "../lib/formato";
import type { Turma, Usuario } from "../lib/types";

// Tabela "Contas de acesso" no celular (< 640 px): células mais justas.
const th = `${classesTabela.th} max-sm:px-3`;
const td = `${classesTabela.td} max-sm:px-3`;

/** Data e hora no horário de Brasília (a API manda UTC sem sufixo — mesma regra
 *  do `dataHora` compartilhado, usada também no "há X dias" da tabela). */
function dataLegivel(iso: string | null | undefined): string {
  return dataHora(iso ?? null);
}

type Acao =
  | "visualizar"
  | "editar"
  | "redefinir"
  | "permissoes"
  | "turmas"
  | "situacao"
  | "excluir"
  | "permanente";

// --- Menu de ações por usuário ----------------------------------------------

function MenuAcoes({
  usuario,
  souEu,
  souGlobal,
  souAdmin,
  podeGerirTurmas,
  podeRedefinir,
  podeExcluir,
  aoEscolher,
}: {
  usuario: Usuario;
  souEu: boolean;
  souGlobal: boolean;
  /** Ações de GESTÃO (editar, permissões, excluir) — só admin. */
  souAdmin: boolean;
  /** Vincular turmas ao professor — admin OU coordenador da própria escola. */
  podeGerirTurmas: boolean;
  /** Matriz da redefinição de senha: admin→todos; coordenador→ele e
   *  professores; professor→só ele. */
  podeRedefinir: boolean;
  /** Excluir (lógica): admin exclui qualquer conta; coordenador exclui a
   *  própria equipe (não admins nem globais). */
  podeExcluir: boolean;
  aoEscolher: (acao: Acao) => void;
}) {
  const excluido = usuario.status === "excluido";
  // Conta desativada: o backend recusa gerar o link (400 "reative a conta
  // antes") e o link de conta inativa não vale no consumo. A ação fica visível,
  // mas inerte, dizendo o que fazer.
  const inativa = !excluido && (usuario.status ?? "ativo") !== "ativo";

  return (
    <MenuSuspenso ariaLabel={`Ações do usuário ${usuario.nome}`}>
      {(fechar) => {
        const escolher = (acao: Acao) => {
          fechar();
          aoEscolher(acao);
        };
        return (
          <>
            <ItemMenu icone={<Eye size={15} />} rotulo="Visualizar" onClick={() => escolher("visualizar")} />
            {!excluido && podeRedefinir && (
              <ItemMenu
                icone={<KeyRound size={15} />}
                rotulo="Redefinir senha"
                desabilitado={inativa}
                dica={inativa ? "Conta inativa: reative a conta antes" : undefined}
                onClick={() => escolher("redefinir")}
              />
            )}
            {/* Vincular turmas: admin OU coordenador (o professor pode ter várias). */}
            {!excluido && podeGerirTurmas && usuario.cargo === "professor" && (
              <ItemMenu
                icone={<GraduationCap size={15} />}
                rotulo="Vincular turmas"
                onClick={() => escolher("turmas")}
              />
            )}
            {!excluido && souAdmin && (
              <>
                <ItemMenu icone={<Pencil size={15} />} rotulo="Editar" onClick={() => escolher("editar")} />
                {!souEu && (
                  <>
                    <ItemMenu
                      icone={<ShieldCheck size={15} />}
                      rotulo="Alterar permissões"
                      onClick={() => escolher("permissoes")}
                    />
                    <ItemMenu
                      icone={usuario.status === "ativo" ? <UserX size={15} /> : <UserCheck size={15} />}
                      rotulo={usuario.status === "ativo" ? "Desativar" : "Reativar"}
                      onClick={() => escolher("situacao")}
                    />
                  </>
                )}
              </>
            )}
            {/* Excluir (lógica): admin exclui qualquer conta; coordenador exclui
                a própria equipe (não admins/globais — o backend também barra). */}
            {!excluido && !souEu && podeExcluir && (
              <>
                <div className="my-1 border-t border-zinc-100 dark:border-zinc-800" />
                <ItemMenu icone={<Trash2 size={15} />} rotulo="Excluir Usuário" destrutiva onClick={() => escolher("excluir")} />
              </>
            )}
            {excluido && !souEu && souAdmin && (
              <ItemMenu icone={<RotateCcw size={15} />} rotulo="Restaurar" onClick={() => escolher("situacao")} />
            )}
            {souGlobal && !souEu && (
              <ItemMenu
                icone={<TriangleAlert size={15} />}
                rotulo="Excluir Permanentemente"
                destrutiva
                onClick={() => escolher("permanente")}
              />
            )}
          </>
        );
      }}
    </MenuSuspenso>
  );
}

// --- Redefinir senha ----------------------------------------------------------

/** Gera um LINK de redefinição (uso único, com validade) e o mostra UMA vez
 *  para o gestor entregar ao usuário. Nenhuma senha é exibida ou recuperada:
 *  a própria pessoa escolhe a nova senha ao abrir o link.
 *
 *  Para a PRÓPRIA conta (`proprio`), o backend exige a senha atual: uma sessão
 *  esquecida aberta não pode virar troca de senha (posse permanente da conta). */
function ModalRedefinirSenha({ alvo, base, proprio, aoFechar }: {
  alvo: Usuario;
  base: string;
  proprio: boolean;
  aoFechar: () => void;
}) {
  const [dados, setDados] = useState<{ link: string; validade_min: number } | null>(null);
  const [copiado, setCopiado] = useState(false);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [senhaAtual, setSenhaAtual] = useState("");

  async function gerar() {
    setOcupado(true);
    setErro("");
    try {
      const r = await api<{ link: string; validade_min: number }>(
        `${base}/${alvo.id}/redefinir-senha`,
        proprio
          ? { method: "POST", body: JSON.stringify({ senha_atual: senhaAtual }) }
          : { method: "POST" });
      setDados(r);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível gerar o link.");
    } finally {
      setOcupado(false);
      setSenhaAtual("");   // a senha digitada não fica na memória da tela
    }
  }

  return (
    <Modal titulo={`Redefinir senha de ${alvo.nome}`} aberto aoFechar={aoFechar}>
      {dados === null ? (
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Vamos gerar um <strong>link seguro</strong> para <strong>{alvo.nome}</strong> criar
            uma senha nova. Ninguém — nem o sistema — vê a senha: só a própria pessoa a
            define. O link vale <strong>uma única vez</strong> e expira.
          </p>
          {proprio && (
            <div className="mt-3">
              <Campo rotulo="Sua senha atual (para confirmar que é você)">
                {/* current-password: é a conta de quem está logado. */}
                <input
                  type="password"
                  className={estiloInput}
                  value={senhaAtual}
                  onChange={(e) => setSenhaAtual(e.target.value)}
                  autoComplete="current-password"
                  autoFocus
                />
              </Campo>
            </div>
          )}
          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-4 flex justify-end gap-2">
            <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
            <Botao disabled={ocupado || (proprio && senhaAtual.length === 0)} onClick={gerar}>
              <KeyRound size={15} /> {ocupado ? "Gerando..." : "Gerar link de redefinição"}
            </Botao>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            {proprio ? (
              <>Abra este link para escolher a sua nova senha.</>
            ) : (
              <>Entregue este link a <strong>{alvo.nome}</strong> (WhatsApp, e-mail ou pessoalmente).</>
            )}{" "}
            Vale <strong>uma única vez</strong> e expira em {dados.validade_min} minutos.
          </p>
          <div className="mt-3 flex items-center justify-between gap-3 rounded-2xl border border-indigo-100 bg-indigo-50 px-4 py-3 dark:border-indigo-500/20 dark:bg-indigo-500/10">
            <code className="select-all break-all text-xs font-medium text-indigo-800 dark:text-indigo-200">
              {dados.link}
            </code>
            <Botao variante="secundario" tamanho="sm" onClick={() => copiarTexto(dados.link, () => setCopiado(true))}>
              {copiado ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
              {copiado ? "Copiado!" : "Copiar"}
            </Botao>
          </div>
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            Gerar um novo link invalida este. A ação fica no histórico de alterações (sem a senha).
          </p>
          <div className="mt-4 flex justify-end">
            <Botao onClick={aoFechar}>Fechar</Botao>
          </div>
        </>
      )}
    </Modal>
  );
}


// --- Vincular turmas ao professor --------------------------------------------

/** Marca quais turmas o professor acompanha (o vínculo do RBAC por turma). Uma
 *  turma tem um titular por vez; marcar uma que era de outro professor a
 *  transfere. Um professor pode ter várias turmas. */
function ModalTurmasProfessor({ alvo, escolaId, aoFechar, aoSalvar }: {
  alvo: Usuario;
  escolaId: number;
  aoFechar: () => void;
  aoSalvar: (mensagem: string) => void;
}) {
  // `lista` = turmas exibidas (as designáveis do ano ativo + as que a professora
  // já tem fora dele, para poder removê-las). `iniciais` = as que já eram dela
  // ao abrir — é a régua da dica de transferência (nunca o estado ao vivo, senão
  // desmarcar uma turma dela mesma acusaria "passar para ela mesma").
  const [lista, setLista] = useState<Turma[] | null>(null);
  const [foraDoAno, setForaDoAno] = useState<Set<number>>(new Set());
  const [iniciais, setIniciais] = useState<Set<number>>(new Set());
  const [selecionadas, setSelecionadas] = useState<Set<number>>(new Set());
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    let vivo = true;
    Promise.all([
      api<Turma[]>(`/escolas/${escolaId}/turmas`),               // designáveis (ano ativo, ativas)
      api<Turma[]>(`/escolas/${escolaId}/turmas?todas=true`),    // inclui arquivadas/outros anos
      api<{ turma_ids: number[] }>(`/escolas/${escolaId}/usuarios/${alvo.id}/turmas`),
    ])
      .then(([ativas, todas, atuais]) => {
        if (!vivo) return;
        const donas = new Set(atuais.turma_ids);
        const idsAtivas = new Set(ativas.map((t) => t.id));
        // Turmas que ela JÁ tem mas que não estão na lista normal (ano/arquivo):
        // aparecem só para poder ser removidas, com etiqueta do porquê.
        const extras = todas.filter((t) => donas.has(t.id) && !idsAtivas.has(t.id));
        setLista([...ativas, ...extras]);
        setForaDoAno(new Set(extras.map((t) => t.id)));
        setIniciais(donas);
        setSelecionadas(new Set(donas));
      })
      .catch((e) => {
        if (vivo) setErro(e instanceof ApiError ? e.message : "Não foi possível carregar as turmas.");
      });
    return () => { vivo = false; };
  }, [escolaId, alvo.id]);

  function alternar(id: number) {
    setSelecionadas((atual) => {
      const nova = new Set(atual);
      if (nova.has(id)) nova.delete(id);
      else nova.add(id);
      return nova;
    });
  }

  async function salvar() {
    setOcupado(true);
    setErro("");
    try {
      const r = await api<{ mensagem?: string }>(
        `/escolas/${escolaId}/usuarios/${alvo.id}/turmas`,
        { method: "PUT", body: JSON.stringify({ turma_ids: [...selecionadas] }) },
      );
      aoSalvar(r?.mensagem ?? "Turmas atualizadas.");
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível salvar.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Modal titulo={`Turmas de ${alvo.nome}`} aberto aoFechar={aoFechar}>
      <p className="text-sm text-zinc-600 dark:text-zinc-300">
        Marque as turmas que <strong>{alvo.nome}</strong> acompanha. O professor passa a ver
        apenas os alunos dessas turmas — e pode ter <strong>várias</strong>.
      </p>
      {lista === null && !erro ? (
        <div className="mt-4"><Carregando /></div>
      ) : lista && lista.length === 0 ? (
        <div className="mt-4">
          <Vazio titulo="Nenhuma turma" descricao="Cadastre turmas antes de vinculá-las a um professor." />
        </div>
      ) : (
        <div className="mt-3 max-h-72 space-y-1 overflow-y-auto pr-1">
          {(lista ?? []).map((t) => {
            const marcada = selecionadas.has(t.id);
            // "de outro professor" pela régua INICIAL: uma turma que já era dela
            // nunca acusa transferência, mesmo desmarcada.
            const deOutro = t.professor_id !== null && !iniciais.has(t.id) && t.professor_nome;
            const antiga = foraDoAno.has(t.id);
            return (
              <label
                key={t.id}
                className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition-colors ${
                  marcada
                    ? "border-indigo-300 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-500/10"
                    : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-700 dark:hover:border-zinc-600"
                }`}
              >
                <input
                  type="checkbox"
                  className={estiloCheckbox}
                  checked={marcada}
                  onChange={() => alternar(t.id)}
                />
                <span className="text-sm">
                  <span className="font-semibold">{t.nome}</span>
                  <span className="ml-2 text-xs text-zinc-500 dark:text-zinc-400">{t.ano_escolar}</span>
                  {antiga && (
                    <span className="ml-2 rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                      {t.ano_letivo}{t.status !== "ativa" ? " · arquivada" : ""}
                    </span>
                  )}
                  {deOutro && (
                    <span className="mt-0.5 block text-xs text-amber-600 dark:text-amber-400">
                      hoje com {t.professor_nome} — marcar passa a turma para {alvo.nome}
                    </span>
                  )}
                </span>
              </label>
            );
          })}
        </div>
      )}
      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado || lista === null} onClick={salvar}>
          <GraduationCap size={15} /> {ocupado ? "Salvando..." : "Salvar turmas"}
        </Botao>
      </div>
    </Modal>
  );
}


// --- Corrigir professores duplicados -----------------------------------------

interface CandidatoDup {
  loser_id: number;
  apagar: string;          // nome que sai
  manter: string;          // nome que fica
  confianca: "alta" | "revisar";
  usuario_novo: string | null;
  senha_nova: string | null;
  turmas_movidas: string[];
}
interface PreviaDuplicados {
  candidatos: CandidatoDup[];
  total: number;
  revisar: number;
}
interface CredencialProf {
  nome: string;
  usuario: string | null;
  senha: string | null;
}

/** Propõe fusões de contas de professor duplicadas (nome curto do Matific +
 *  nome completo da Lista Piloto = a MESMA pessoa). Cada fusão tem sua CAIXA:
 *  as de confiança "revisar" (nome composto, ex.: "Ivone Celia" → "Ivone Celia
 *  Fortunelli de Ficticio") podem ser outra pessoa e o gestor confirma. Ao aplicar,
 *  devolve a folha de credenciais (@/senha) para entregar. */
function ModalProfessoresDuplicados({ escolaId, aoFechar, aoConcluir }: {
  escolaId: number;
  aoFechar: () => void;
  aoConcluir: () => void;
}) {
  const [previa, setPrevia] = useState<PreviaDuplicados | null>(null);
  const [selecionados, setSelecionados] = useState<Set<number>>(new Set());
  const [folha, setFolha] = useState<CredencialProf[] | null>(null);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [copiado, setCopiado] = useState(false);

  useEffect(() => {
    let vivo = true;
    api<PreviaDuplicados>(`/escolas/${escolaId}/professores/duplicados`)
      .then((r) => {
        if (!vivo) return;
        setPrevia(r);
        // Todas marcadas por padrão; o gestor DESMARCA as que não são a mesma pessoa.
        setSelecionados(new Set(r.candidatos.map((c) => c.loser_id)));
      })
      .catch((e) => { if (vivo) setErro(e instanceof ApiError ? e.message : "Não foi possível carregar."); });
    return () => { vivo = false; };
  }, [escolaId]);

  function alternar(id: number) {
    setSelecionados((atual) => {
      const nova = new Set(atual);
      if (nova.has(id)) nova.delete(id);
      else nova.add(id);
      return nova;
    });
  }

  async function corrigir() {
    setOcupado(true);
    setErro("");
    try {
      const r = await api<{ folha: CredencialProf[] }>(
        `/escolas/${escolaId}/professores/duplicados/corrigir`,
        { method: "POST", body: JSON.stringify({ loser_ids: [...selecionados] }) },
      );
      setFolha(r.folha);
      aoConcluir();   // recarrega a lista de usuários por trás
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível corrigir.");
    } finally {
      setOcupado(false);
    }
  }

  const textoFolha = (folha ?? [])
    .map((c) => `${c.nome}\t@${c.usuario ?? "—"}\tsenha: ${c.senha ?? "mantida"}`)
    .join("\n");

  return (
    <Modal titulo="Corrigir professores duplicados" aberto aoFechar={aoFechar}>
      {folha !== null ? (
        // --- Resultado: folha de credenciais para entregar ---
        <>
          <Mensagem tipo="ok">
            {folha.length} professor(es) unificado(s). Entregue as credenciais abaixo — no
            primeiro acesso, cada uma pode trocar a senha.
          </Mensagem>
          <div className="mt-3 max-h-72 overflow-y-auto rounded-2xl border border-zinc-200/80 dark:border-zinc-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase text-zinc-500 dark:border-zinc-800">
                  <th className="px-3 py-2 font-medium">Professora</th>
                  <th className="px-3 py-2 font-medium">Usuário</th>
                  <th className="px-3 py-2 font-medium">Senha</th>
                </tr>
              </thead>
              <tbody>
                {folha.map((c) => (
                  <tr key={c.nome} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-3 py-2">{c.nome}</td>
                    <td className="px-3 py-2 font-mono text-xs">@{c.usuario ?? "—"}</td>
                    <td className="px-3 py-2 select-all font-mono text-xs">
                      {c.senha ?? <span className="text-zinc-500 dark:text-zinc-400">senha mantida</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Botao variante="secundario" onClick={() => copiarTexto(textoFolha, () => setCopiado(true))}>
              <Copy size={15} /> {copiado ? "Copiado!" : "Copiar lista"}
            </Botao>
            <Botao onClick={aoFechar}>Fechar</Botao>
          </div>
        </>
      ) : previa === null && !erro ? (
        <div className="mt-2"><Carregando /></div>
      ) : previa === null ? (
        // A prévia não carregou: só o erro (sem "Encontrei  possível(is)…" com a contagem vazia).
        <>
          <Mensagem tipo="erro">{erro}</Mensagem>
          <div className="mt-4 flex justify-end">
            <Botao variante="secundario" onClick={aoFechar}>Fechar</Botao>
          </div>
        </>
      ) : previa.total === 0 ? (
        <Vazio icone={UsersRound} titulo="Nenhuma duplicata" descricao="As contas de professor já estão únicas." />
      ) : (
        // --- Prévia: MARQUE as fusões a aplicar ---
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Encontrei <strong>{previa?.total}</strong> possível(is) duplicata(s). Marque as que
            são a <strong>mesma pessoa</strong> — vou manter o nome completo, mover as turmas e
            apagar a conta curta.
            {previa?.revisar ? " As marcadas com ⚠ podem ser pessoas diferentes: confira." : ""}
          </p>
          <div className="mt-3 max-h-72 space-y-1.5 overflow-y-auto pr-1">
            {previa?.candidatos.map((c) => {
              const marcado = selecionados.has(c.loser_id);
              return (
                <label
                  key={c.loser_id}
                  className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${
                    marcado
                      ? "border-indigo-300 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-500/10"
                      : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-700 dark:hover:border-zinc-600"
                  }`}
                >
                  <input
                    type="checkbox"
                    className={`mt-0.5 ${estiloCheckbox}`}
                    checked={marcado}
                    onChange={() => alternar(c.loser_id)}
                  />
                  <span className="min-w-0 flex-1 text-sm">
                    <span>
                      Unir <strong>{c.apagar}</strong> → <strong>{c.manter}</strong>{" "}
                      <span className="font-mono text-xs text-indigo-600 dark:text-indigo-400">@{c.usuario_novo}</span>
                      {c.senha_nova === null && (
                        <span className="text-xs text-zinc-500 dark:text-zinc-400"> (já ativa — senha mantida)</span>
                      )}
                    </span>
                    {c.confianca === "revisar" && (
                      <span className="mt-0.5 block text-xs text-amber-600 dark:text-amber-400">
                        ⚠ confira: “{c.apagar}” pode ser outra pessoa
                      </span>
                    )}
                    {c.turmas_movidas.length > 0 && (
                      <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                        Turmas movidas: {c.turmas_movidas.join(", ")}
                      </span>
                    )}
                  </span>
                </label>
              );
            })}
          </div>
          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-4 flex justify-end gap-2">
            <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
            <Botao
              variante="perigo"
              disabled={ocupado || selecionados.size === 0}
              onClick={corrigir}
            >
              <UsersRound size={15} /> {ocupado ? "Unindo..." : `Unir ${selecionados.size} selecionada(s)`}
            </Botao>
          </div>
        </>
      )}
    </Modal>
  );
}


// --- Padronizar o @ de todas as professoras ----------------------------------

/** Coloca o @ de TODA conta de professor no padrão CamelCase (PrimeiroÚltimo).
 *  As contas antigas nasceram minúsculas (@telmatestelli); esta ação arruma
 *  todas. Quem já entrou mantém a senha (só o @ muda de caixa). */
function ModalPadronizarUsuarios({ escolaId, aoFechar, aoConcluir }: {
  escolaId: number;
  aoFechar: () => void;
  aoConcluir: () => void;
}) {
  const [folha, setFolha] = useState<CredencialProf[] | null>(null);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [copiado, setCopiado] = useState(false);

  async function padronizar() {
    setOcupado(true);
    setErro("");
    try {
      const r = await api<{ folha: CredencialProf[] }>(
        `/escolas/${escolaId}/professores/padronizar-usuarios`, { method: "POST" });
      setFolha(r.folha);
      aoConcluir();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível padronizar.");
    } finally {
      setOcupado(false);
    }
  }

  const textoFolha = (folha ?? [])
    .map((c) => `${c.nome}\t@${c.usuario ?? "—"}\tsenha: ${c.senha ?? "mantida"}`)
    .join("\n");

  return (
    <Modal titulo="Padronizar @ das professoras" aberto aoFechar={aoFechar}>
      {folha !== null ? (
        <>
          <Mensagem tipo="ok">
            {folha.length === 0
              ? "Todos os @ já estavam no padrão."
              : `${folha.length} conta(s) ajustada(s). As com senha nova estão abaixo — entregue às professoras.`}
          </Mensagem>
          {folha.length > 0 && (
            <div className="mt-3 max-h-72 overflow-y-auto rounded-2xl border border-zinc-200/80 dark:border-zinc-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 text-left text-xs uppercase text-zinc-500 dark:border-zinc-800">
                    <th className="px-3 py-2 font-medium">Professora</th>
                    <th className="px-3 py-2 font-medium">Usuário</th>
                    <th className="px-3 py-2 font-medium">Senha</th>
                  </tr>
                </thead>
                <tbody>
                  {folha.map((c) => (
                    <tr key={c.nome} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                      <td className="px-3 py-2">{c.nome}</td>
                      <td className="px-3 py-2 font-mono text-xs">@{c.usuario ?? "—"}</td>
                      <td className="px-3 py-2 select-all font-mono text-xs">
                        {c.senha ?? <span className="text-zinc-500 dark:text-zinc-400">senha mantida</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-4 flex justify-end gap-2">
            {folha.length > 0 && (
              <Botao variante="secundario" onClick={() => copiarTexto(textoFolha, () => setCopiado(true))}>
                <Copy size={15} /> {copiado ? "Copiado!" : "Copiar lista"}
              </Botao>
            )}
            <Botao onClick={aoFechar}>Fechar</Botao>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Coloca o <strong>@</strong> de todas as professoras no padrão{" "}
            <strong>PrimeiroÚltimo</strong> com maiúsculas (ex.: <code>@TelmaTestelli</code>).
            Quem <strong>já entrou</strong> mantém a senha (muda só a caixa do @, o login aceita
            qualquer caixa); quem <strong>nunca entrou</strong> recebe @ e senha novos, que
            aparecem numa lista para você entregar.
          </p>
          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-4 flex justify-end gap-2">
            <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
            <Botao disabled={ocupado} onClick={padronizar}>
              <AtSign size={15} /> {ocupado ? "Padronizando..." : "Padronizar agora"}
            </Botao>
          </div>
        </>
      )}
    </Modal>
  );
}


// --- Página -------------------------------------------------------------------

export default function Usuarios() {
  const { escolaId, usuario: usuarioLogado, escolaAtual } = useApp();
  const [usuarios, setUsuarios] = useState<Usuario[] | null>(null);
  const [mostrarExcluidos, setMostrarExcluidos] = useState(false);
  const [erroLista, setErroLista] = useState("");
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const temporizador = useRef<number | null>(null);

  // ação em andamento: qual modal está aberto e para quem
  const [acao, setAcao] = useState<{ tipo: Acao; alvo: Usuario } | null>(null);
  const [novo, setNovo] = useState(false);
  const [verDuplicados, setVerDuplicados] = useState(false);
  const [verPadronizar, setVerPadronizar] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [erroAcao, setErroAcao] = useState("");

  // campos dos formulários
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [senha, setSenha] = useState("");
  const [cargo, setCargo] = useState("professor");
  const [confirmacao, setConfirmacao] = useState("");

  const souGlobal = usuarioLogado?.is_global ?? false;
  const souAdmin = souGlobal || usuarioLogado?.cargo === "admin";
  const souCoordenador = usuarioLogado?.cargo === "coordenador";
  // Matriz da redefinição de senha: admin→todos; coordenador→ele e
  // professores; professor→apenas ele. O backend aplica a mesma regra.
  const podeRedefinir = (alvo: Usuario) =>
    souAdmin || alvo.id === usuarioLogado?.id ||
    (souCoordenador && alvo.cargo === "professor");
  // Excluir (lógica): admin exclui qualquer conta; coordenador exclui a própria
  // equipe — nunca admins nem contas globais (o backend confirma a regra).
  const podeExcluir = (alvo: Usuario) =>
    souAdmin || (souCoordenador && alvo.cargo !== "admin" && !alvo.is_global);

  const carregar = useCallback(() => {
    if (!escolaId) return;
    setErroLista("");   // limpa o erro anterior: sucesso não deve manter o aviso
    const sufixo = mostrarExcluidos ? "?incluir_excluidos=true" : "";
    api<Usuario[]>(`/escolas/${escolaId}/usuarios${sufixo}`)
      .then(setUsuarios)
      .catch((excecao) => {
        setUsuarios([]);
        setErroLista(excecao instanceof Error ? excecao.message : "Sem acesso.");
      });
  }, [escolaId, mostrarExcluidos]);

  useEffect(carregar, [carregar]);

  function avisar(tipo: "ok" | "erro", texto: string) {
    setMensagem({ tipo, texto });
    if (temporizador.current) window.clearTimeout(temporizador.current);
    temporizador.current = window.setTimeout(() => setMensagem(null), 6000);
  }

  function abrir(tipo: Acao, alvo: Usuario) {
    setErroAcao("");
    setSenha("");
    setConfirmacao("");
    setNome(alvo.nome);
    setEmail(alvo.email);
    setUsername(alvo.username ?? "");
    setCargo(alvo.cargo);
    setAcao({ tipo, alvo });
  }

  function abrirNovo() {
    setErroAcao("");
    setNome("");
    setEmail("");
    setUsername("");
    setSenha("");
    setCargo("professor");
    setNovo(true);
  }

  async function executar(caminho: string, opcoes: RequestInit, sucesso: string) {
    if (!escolaId) return;
    setOcupado(true);
    setErroAcao("");
    try {
      const resposta = await api<{ mensagem?: string }>(caminho, opcoes);
      avisar("ok", resposta?.mensagem ?? sucesso);
      setAcao(null);
      setNovo(false);
      carregar();               // a lista atualiza sem recarregar a página
    } catch (excecao) {
      setErroAcao(excecao instanceof ApiError ? excecao.message : "Não foi possível concluir a ação.");
    } finally {
      setOcupado(false);
    }
  }

  const alvo = acao?.alvo ?? null;
  const base = `/escolas/${escolaId}/usuarios`;

  return (
    <div>
      <PageHeader
        titulo="Usuários"
        descricao={
          // O Admin Global opera várias escolas: deixa explícito QUAL escola
          // recebe a conta (o seletor do topo define a escola desta tela).
          (escolaAtual ? `Contas de acesso de ${escolaAtual.nome}. ` : "Contas de acesso desta escola. ")
          + "Toda alteração fica no histórico de alterações."
        }
        acoes={
          souAdmin ? (
            <div className="flex flex-wrap gap-2">
              <Botao variante="secundario" onClick={() => setVerPadronizar(true)}>
                <AtSign size={15} /> Padronizar @
              </Botao>
              <Botao variante="secundario" onClick={() => setVerDuplicados(true)}>
                <UsersRound size={15} /> Professores duplicados
              </Botao>
              <Botao onClick={abrirNovo}>
                <UserPlus size={15} /> Novo usuário
              </Botao>
            </div>
          ) : undefined
        }
      />

      {/* --- Corrigir professores duplicados --- */}
      {verDuplicados && escolaId && (
        <ModalProfessoresDuplicados
          escolaId={escolaId}
          aoFechar={() => setVerDuplicados(false)}
          aoConcluir={carregar}
        />
      )}

      {/* --- Padronizar o @ de todas as professoras --- */}
      {verPadronizar && escolaId && (
        <ModalPadronizarUsuarios
          escolaId={escolaId}
          aoFechar={() => setVerPadronizar(false)}
          aoConcluir={carregar}
        />
      )}

      {mensagem && (
        <div className="mb-4">
          <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
        </div>
      )}

      <Card className="overflow-hidden">
        <CabecalhoCartao
          titulo="Contas de acesso"
          contagem={usuarios && !erroLista
            ? `${usuarios.length} conta${usuarios.length === 1 ? "" : "s"}`
            : undefined}
          acoes={souAdmin ? (
            <span className="inline-flex items-center gap-2.5 text-sm text-zinc-600 dark:text-zinc-300">
              {/* O nome acessível está no interruptor; o texto ao lado é só visual. */}
              <span aria-hidden className="cursor-pointer select-none" onClick={() => setMostrarExcluidos((v) => !v)}>
                Mostrar usuários excluídos
              </span>
              <Interruptor
                ligado={mostrarExcluidos}
                aoMudar={setMostrarExcluidos}
                rotulo="Mostrar usuários excluídos"
              />
            </span>
          ) : undefined}
        />
        {usuarios === null ? (
          <EsqueletoLista texto="Carregando usuários..." />
        ) : erroLista ? (
          // A lista falhou: o motivo e "Tentar de novo" (o título é o de sempre).
          <Erro titulo="Sem acesso ou nenhum usuário" descricao={erroLista} aoTentar={carregar} />
        ) : usuarios.length === 0 ? (
          <Vazio icone={UsersRound} titulo="Sem acesso ou nenhum usuário"
                 descricao="Nenhuma conta de acesso visível para o seu perfil nesta escola." />
        ) : (
          // O e-mail fica sob o nome (era uma coluna própria, escondida no celular e que,
          // espremida no tablet, quebrava o endereço letra a letra): sem quebra, com o
          // endereço inteiro no title, e a tabela cabe até 768 px com as Ações à vista.
          // Celular (< 640 px): a tabela rola de lado dentro do cartão, com o aviso em
          // texto acima dela; o menu ⋮ (único caminho para gerir a conta) fica preso à
          // direita (`presa-celular`) e o "Último acesso" vem com a rolagem (antes sumia
          // abaixo de 768 px). De 640 a 767 px o menu não fica preso, então a coluna segue
          // fora como antes, para as Ações caberem. O avatar (decorativo) some no celular.
          <TabelaRolavel rotulo="Contas de acesso: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  <th className={th}>Nome</th>
                  <th className={th}>Cargo</th>
                  <th className={th}>Situação</th>
                  <th className={`hidden max-sm:table-cell md:table-cell ${th}`}>Último acesso</th>
                  <th className={`text-right ${th} presa-celular`}>Ações</th>
                </tr>
              </thead>
              <tbody>
                {usuarios.map((usuario) => {
                  const situacao = situacaoDaConta(usuario.status);
                  const acesso = tempoRelativo(usuario.ultimo_acesso);
                  return (
                    <tr key={usuario.id} className={classesTabela.tr}>
                      <td className={td}>
                        <div className="flex items-center gap-3">
                          {/* Chave de cor = o id, a mesma da barra lateral, de Minha conta e de
                              Sessões (era `usuario-${id}` e a pessoa mudava de cor entre as telas). */}
                          <span className="hidden shrink-0 sm:flex">
                            <AvatarAluno nome={usuario.nome} chave={usuario.id} />
                          </span>
                          {/* Celular: base de 9rem — o nome não vira uma palavra por linha, os
                              selos "(você)"/"global" seguem juntos e o e-mail cabe sem quebrar. */}
                          <div className="min-w-0 max-sm:min-w-[9rem]">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-semibold text-zinc-900 dark:text-zinc-100">{usuario.nome}</span>
                              {usuario.id === usuarioLogado?.id && (
                                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">(você)</span>
                              )}
                              {usuario.is_global && (
                                <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">global</span>
                              )}
                            </div>
                            <span className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-zinc-500 dark:text-zinc-400">
                              <span className="max-w-[11rem] [overflow-wrap:anywhere] xl:max-w-[15rem]"><EmailQuebravel email={usuario.email} /></span>
                              {usuario.username && (
                                <span className="whitespace-nowrap">@{usuario.username}</span>
                              )}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className={td}>
                        <ChipCargo cargo={usuario.cargo}>{rotuloCargo(usuario.cargo)}</ChipCargo>
                      </td>
                      <td className={td}>
                        <PilulaSituacao tom={situacao.tom}>{situacao.texto}</PilulaSituacao>
                      </td>
                      <td className={`hidden whitespace-nowrap text-zinc-500 max-sm:table-cell md:table-cell dark:text-zinc-400 ${td}`}>
                        {acesso ? (
                          <span title={acesso.completo}>{acesso.texto}</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className={`text-right ${td} presa-celular`}>
                        <MenuAcoes
                          usuario={usuario}
                          souEu={usuario.id === usuarioLogado?.id}
                          souGlobal={souGlobal}
                          souAdmin={souAdmin}
                          podeGerirTurmas={souAdmin || souCoordenador}
                          podeRedefinir={podeRedefinir(usuario)}
                          podeExcluir={podeExcluir(usuario)}
                          aoEscolher={(tipo) => abrir(tipo, usuario)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>

      {/* --- Novo usuário --- */}
      <Modal titulo="Novo usuário" aberto={novo} aoFechar={() => setNovo(false)}>
        <div className="space-y-3">
          <Campo rotulo="Nome">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} autoFocus />
          </Campo>
          <Campo rotulo="E-mail">
            <input
              type="email"
              className={estiloInput}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="off"
            />
          </Campo>
          <Campo rotulo="Nome de usuário (opcional — para entrar sem digitar o e-mail)">
            <input
              className={estiloInput}
              placeholder="ex.: maria.souza"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
            />
          </Campo>
          <Campo rotulo="Cargo">
            <select className={estiloInput} value={cargo} onChange={(e) => setCargo(e.target.value)}>
              {CARGOS.map((c) => <option key={c.valor} value={c.valor}>{c.rotulo}</option>)}
            </select>
          </Campo>
          <Campo rotulo="Senha (mínimo 8 caracteres)">
            {/* new-password: é a conta de OUTRA pessoa — o navegador não deve
                preencher a senha do gestor nem guardar esta no cofre dele. */}
            <input
              type="password"
              className={estiloInput}
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              autoComplete="new-password"
            />
          </Campo>
          {erroAcao && <Mensagem tipo="erro">{erroAcao}</Mensagem>}
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="secundario" onClick={() => setNovo(false)} disabled={ocupado}>Cancelar</Botao>
            <Botao
              disabled={ocupado || nome.trim().length < 2 || !email.includes("@") || senha.length < 8}
              onClick={() =>
                executar(base, {
                  method: "POST",
                  body: JSON.stringify({
                    nome: nome.trim(), email: email.trim(),
                    username: username.trim() || null, senha, cargo,
                  }),
                }, "Usuário criado.")
              }
            >
              {ocupado ? "Salvando..." : "Criar usuário"}
            </Botao>
          </div>
        </div>
      </Modal>

      {/* --- Visualizar --- */}
      <Modal titulo="Dados do usuário" aberto={acao?.tipo === "visualizar"} aoFechar={() => setAcao(null)}>
        {alvo && (
          <dl className="space-y-2 text-sm">
            {[
              ["Nome", alvo.nome],
              ["E-mail", alvo.email],
              ["Cargo", rotuloCargo(alvo.cargo)],
              ["Conta global", alvo.is_global ? "Sim" : "Não"],
              ["Situação", situacaoDaConta(alvo.status).texto],
              ["Último acesso", dataLegivel(alvo.ultimo_acesso)],
              ["Criado em", dataLegivel(alvo.created_at)],
            ].map(([rotulo, valor]) => (
              <div key={rotulo as string} className="flex justify-between gap-4 border-b border-zinc-100 pb-2 last:border-0 dark:border-zinc-800/60">
                <dt className="text-zinc-500 dark:text-zinc-400">{rotulo}</dt>
                <dd className="text-right font-medium">{valor}</dd>
              </div>
            ))}
          </dl>
        )}
      </Modal>

      {/* --- Editar (nome e nome de usuário) --- */}
      <Modal titulo={`Editar ${alvo?.nome ?? ""}`} aberto={acao?.tipo === "editar"} aoFechar={() => setAcao(null)}>
        <div className="space-y-3">
          <Campo rotulo="Nome">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} autoFocus />
          </Campo>
          <Campo rotulo="E-mail (identidade da conta — não muda)">
            <input className={`${estiloInput} opacity-70`} value={email} disabled />
          </Campo>
          <Campo rotulo="Nome de usuário (para entrar sem digitar o e-mail)">
            <input
              className={estiloInput}
              placeholder="ex.: maria.souza"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </Campo>
          {erroAcao && <Mensagem tipo="erro">{erroAcao}</Mensagem>}
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="secundario" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
            <Botao
              disabled={ocupado || nome.trim().length < 2}
              onClick={() =>
                executar(`${base}/${alvo?.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({
                    nome: nome.trim(),
                    username: username.trim() || null,
                  }),
                }, "Usuário atualizado.")
              }
            >
              {ocupado ? "Salvando..." : "Salvar"}
            </Botao>
          </div>
        </div>
      </Modal>

      {/* --- Redefinir senha: gera um link de uso único --- */}
      {acao?.tipo === "redefinir" && alvo && (
        <ModalRedefinirSenha
          alvo={alvo}
          base={base}
          proprio={alvo.id === usuarioLogado?.id}
          aoFechar={() => setAcao(null)}
        />
      )}

      {/* --- Alterar permissões --- */}
      <Modal titulo={`Permissões de ${alvo?.nome ?? ""}`} aberto={acao?.tipo === "permissoes"} aoFechar={() => setAcao(null)}>
        <div className="space-y-2">
          {CARGOS.map((c) => (
            <label
              key={c.valor}
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors ${
                cargo === c.valor
                  ? "border-indigo-300 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-500/10"
                  : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-700 dark:hover:border-zinc-600"
              }`}
            >
              <input
                type="radio"
                name="cargo"
                className="mt-0.5 accent-indigo-600"
                checked={cargo === c.valor}
                onChange={() => setCargo(c.valor)}
              />
              <span className="text-sm">
                <span className="font-medium">{c.rotulo}</span>
                <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">{c.descricao}</span>
              </span>
            </label>
          ))}
          {erroAcao && <Mensagem tipo="erro">{erroAcao}</Mensagem>}
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="secundario" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
            <Botao
              disabled={ocupado || cargo === alvo?.cargo}
              onClick={() =>
                executar(`${base}/${alvo?.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ cargo }),
                }, "Permissões atualizadas.")
              }
            >
              {ocupado ? "Salvando..." : "Salvar permissões"}
            </Botao>
          </div>
        </div>
      </Modal>

      {/* --- Vincular turmas ao professor --- */}
      {acao?.tipo === "turmas" && alvo && escolaId && (
        <ModalTurmasProfessor
          alvo={alvo}
          escolaId={escolaId}
          aoFechar={() => setAcao(null)}
          aoSalvar={(msg) => {
            avisar("ok", msg);
            setAcao(null);
            carregar();
          }}
        />
      )}

      {/* --- Desativar / Reativar / Restaurar --- */}
      <Modal
        titulo={alvo?.status === "ativo" ? "Desativar usuário" : alvo?.status === "excluido" ? "Restaurar usuário" : "Reativar usuário"}
        aberto={acao?.tipo === "situacao"}
        aoFechar={() => setAcao(null)}
      >
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          {alvo?.status === "ativo" ? (
            <>Desativar <strong>{alvo?.nome}</strong>? A pessoa perde o acesso imediatamente, mas a conta pode ser reativada a qualquer momento.</>
          ) : (
            <>Devolver o acesso de <strong>{alvo?.nome}</strong>? A conta volta à situação “ativo”.</>
          )}
        </p>
        {erroAcao && <div className="mt-3"><Mensagem tipo="erro">{erroAcao}</Mensagem></div>}
        <div className="mt-4 flex justify-end gap-2">
          <Botao variante="secundario" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
          <Botao
            disabled={ocupado}
            onClick={() =>
              executar(`${base}/${alvo?.id}`, {
                method: "PATCH",
                body: JSON.stringify({ status: alvo?.status === "ativo" ? "inativo" : "ativo" }),
              }, alvo?.status === "ativo" ? "Usuário desativado." : "Usuário reativado.")
            }
          >
            {ocupado ? "Aplicando..." : "Confirmar"}
          </Botao>
        </div>
      </Modal>

      {/* --- Excluir (lógica) --- */}
      <Modal titulo="Excluir usuário" aberto={acao?.tipo === "excluir"} aoFechar={() => setAcao(null)}>
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          Tem certeza de que deseja excluir <strong>{alvo?.nome}</strong>? Essa ação não
          poderá ser desfeita.
        </p>
        <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
          O histórico de ações, logs e importações do usuário é preservado — apenas o
          acesso é encerrado em definitivo.
        </p>
        {erroAcao && <div className="mt-3"><Mensagem tipo="erro">{erroAcao}</Mensagem></div>}
        <div className="mt-4 flex justify-end gap-2">
          <Botao variante="secundario" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
          <Botao
            variante="perigo"
            disabled={ocupado}
            onClick={() =>
              executar(`${base}/${alvo?.id}`, { method: "DELETE" }, "Usuário excluído.")
            }
          >
            <Trash2 size={15} /> {ocupado ? "Excluindo..." : "Sim, excluir"}
          </Botao>
        </div>
      </Modal>

      {/* --- Excluir Permanentemente (admin global) --- */}
      <Modal titulo="Excluir permanentemente" aberto={acao?.tipo === "permanente"} aoFechar={() => setAcao(null)}>
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
          <p className="flex items-center gap-2 font-medium">
            <TriangleAlert size={16} /> Ação definitiva e irreversível
          </p>
          <p className="mt-1 text-xs">
            O registro de <strong>{alvo?.nome}</strong> será removido do banco de dados.
            Importações e logs são preservados, mas ficam sem autoria.
          </p>
        </div>
        <div className="mt-3">
          <Campo rotulo={`Para confirmar, digite o e-mail do usuário (${alvo?.email})`}>
            <input
              className={estiloInput}
              value={confirmacao}
              onChange={(e) => setConfirmacao(e.target.value)}
              placeholder="e-mail exato do usuário"
              autoFocus
            />
          </Campo>
        </div>
        {erroAcao && <div className="mt-3"><Mensagem tipo="erro">{erroAcao}</Mensagem></div>}
        <div className="mt-4 flex justify-end gap-2">
          <Botao variante="secundario" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
          <Botao
            variante="perigo"
            disabled={ocupado || confirmacao.trim().toLowerCase() !== alvo?.email}
            onClick={() =>
              executar(
                `${base}/${alvo?.id}/permanente?confirmacao=${encodeURIComponent(confirmacao.trim())}`,
                { method: "DELETE" },
                "Usuário removido permanentemente.",
              )
            }
          >
            <TriangleAlert size={15} /> {ocupado ? "Removendo..." : "Excluir permanentemente"}
          </Botao>
        </div>
      </Modal>
    </div>
  );
}
