/**
 * Gestão de usuários (PRD §18) — somente administradores.
 *
 * Cada usuário tem um menu de ações: Visualizar, Editar, Alterar senha,
 * Alterar permissões, Desativar/Reativar, Excluir (lógica, preserva o
 * histórico) e — apenas para administradores globais — Excluir
 * Permanentemente, com confirmação extra digitando o e-mail.
 * As regras duras (própria conta, último admin) vivem no backend; a
 * interface apenas exibe as mensagens e evita oferecer o que será negado.
 */
import {
  Eye,
  KeyRound,
  Pencil,
  RotateCcw,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  UserCheck,
  UserPlus,
  UserX,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import MenuSuspenso, { ItemMenu } from "../components/MenuSuspenso";
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
import { ApiError, api } from "../lib/api";
import type { Usuario } from "../lib/types";

const CARGOS = [
  { valor: "admin", rotulo: "Administrador", descricao: "Acesso total: usuários, configurações, importações e exclusões." },
  { valor: "coordenador", rotulo: "Coordenador", descricao: "Acesso a tudo da escola, exceto usuários e configurações de sistema." },
  { valor: "professor", rotulo: "Professor", descricao: "Vê apenas as turmas designadas a ele, com dados resumidos." },
] as const;

function rotuloCargo(valor: string): string {
  return CARGOS.find((c) => c.valor === valor)?.rotulo ?? valor;
}

function dataLegivel(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

/** Copia com fallback: em http na rede local (celular) o clipboard moderno
 *  não existe — sem o fallback o botão falharia em silêncio e o usuário
 *  fecharia o modal achando que copiou uma senha de uso único. */
function copiarTexto(texto: string, aoCopiar: () => void) {
  const legado = () => {
    const area = document.createElement("textarea");
    area.value = texto;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      if (document.execCommand("copy")) aoCopiar();
    } finally {
      document.body.removeChild(area);
    }
  };
  if (navigator.clipboard) {
    navigator.clipboard.writeText(texto).then(aoCopiar).catch(legado);
  } else {
    legado();
  }
}

type Acao =
  | "visualizar"
  | "editar"
  | "senha"
  | "versenha"
  | "permissoes"
  | "situacao"
  | "excluir"
  | "permanente";

// --- Menu de ações por usuário ----------------------------------------------

function MenuAcoes({
  usuario,
  souEu,
  souGlobal,
  souAdmin,
  podeVerSenha,
  aoEscolher,
}: {
  usuario: Usuario;
  souEu: boolean;
  souGlobal: boolean;
  /** Ações de GESTÃO (editar, permissões, excluir) — só admin. */
  souAdmin: boolean;
  /** Matriz: admin→todos; coordenador→ele e professores; professor→só ele. */
  podeVerSenha: boolean;
  aoEscolher: (acao: Acao) => void;
}) {
  const excluido = usuario.status === "excluido";

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
            {!excluido && podeVerSenha && (
              <ItemMenu icone={<Eye size={15} />} rotulo="Ver senha (gerar nova)" onClick={() => escolher("versenha")} />
            )}
            {!excluido && souAdmin && (
              <>
                <ItemMenu icone={<Pencil size={15} />} rotulo="Editar" onClick={() => escolher("editar")} />
                <ItemMenu icone={<KeyRound size={15} />} rotulo="Alterar senha" onClick={() => escolher("senha")} />
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
                    <div className="my-1 border-t border-zinc-100 dark:border-zinc-800" />
                    <ItemMenu icone={<Trash2 size={15} />} rotulo="Excluir Usuário" destrutiva onClick={() => escolher("excluir")} />
                  </>
                )}
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

// --- Página -------------------------------------------------------------------

export default function Usuarios() {
  const { escolaId, usuario: usuarioLogado } = useApp();
  const [usuarios, setUsuarios] = useState<Usuario[] | null>(null);
  const [mostrarExcluidos, setMostrarExcluidos] = useState(false);
  const [erroLista, setErroLista] = useState("");
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const temporizador = useRef<number | null>(null);

  // ação em andamento: qual modal está aberto e para quem
  const [acao, setAcao] = useState<{ tipo: Acao; alvo: Usuario } | null>(null);
  const [novo, setNovo] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [erroAcao, setErroAcao] = useState("");

  // campos dos formulários
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [senha, setSenha] = useState("");
  const [senha2, setSenha2] = useState("");
  const [cargo, setCargo] = useState("professor");
  const [confirmacao, setConfirmacao] = useState("");
  const [senhaGerada, setSenhaGerada] = useState<string | null>(null);
  const [copiada, setCopiada] = useState(false);

  const souGlobal = usuarioLogado?.is_global ?? false;
  const souAdmin = souGlobal || usuarioLogado?.cargo === "admin";
  const souCoordenador = usuarioLogado?.cargo === "coordenador";
  // Matriz do "ver senha": admin→todos; coordenador→ele e professores;
  // professor→apenas ele. O backend aplica a mesma regra.
  const podeVerSenha = (alvo: Usuario) =>
    souAdmin || alvo.id === usuarioLogado?.id ||
    (souCoordenador && alvo.cargo === "professor");

  const carregar = useCallback(() => {
    if (!escolaId) return;
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
    setSenha2("");
    setConfirmacao("");
    setNome(alvo.nome);
    setEmail(alvo.email);
    setUsername(alvo.username ?? "");
    setCargo(alvo.cargo);
    setSenhaGerada(null);
    setCopiada(false);
    setAcao({ tipo, alvo });
  }

  function abrirNovo() {
    setErroAcao("");
    setNome("");
    setEmail("");
    setUsername("");
    setSenha("");
    setSenha2("");
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
        descricao="Contas de acesso desta escola. Toda alteração fica no log de auditoria."
        acoes={
          souAdmin ? (
            <Botao onClick={abrirNovo}>
              <UserPlus size={15} /> Novo usuário
            </Botao>
          ) : undefined
        }
      />

      {mensagem && (
        <div className="mb-4">
          <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
        </div>
      )}

      {souAdmin && (
        <label className="mb-3 flex w-fit cursor-pointer items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
            checked={mostrarExcluidos}
            onChange={(e) => setMostrarExcluidos(e.target.checked)}
          />
          Mostrar usuários excluídos
        </label>
      )}

      <Card>
        {usuarios === null ? (
          <Carregando />
        ) : usuarios.length === 0 ? (
          <Vazio titulo="Sem acesso ou nenhum usuário" descricao={erroLista} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Nome</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">E-mail</th>
                  <th className="px-4 py-2 font-medium">Cargo</th>
                  <th className="px-4 py-2 font-medium">Situação</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Último acesso</th>
                  <th className="px-4 py-2 text-right font-medium">Ações</th>
                </tr>
              </thead>
              <tbody>
                {usuarios.map((usuario) => (
                  <tr key={usuario.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5 font-medium">
                      {usuario.nome}
                      {usuario.id === usuarioLogado?.id && (
                        <span className="ml-2 text-xs text-zinc-400">(você)</span>
                      )}
                      {usuario.is_global && (
                        <span className="ml-2 text-xs text-indigo-500">global</span>
                      )}
                      {usuario.username && (
                        <span className="block text-xs font-normal text-zinc-400">@{usuario.username}</span>
                      )}
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 sm:table-cell">
                      {usuario.email}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tom="destaque">{rotuloCargo(usuario.cargo)}</Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge
                        tom={usuario.status === "ativo" ? "ok" : usuario.status === "excluido" ? "alerta" : "neutro"}
                      >
                        {usuario.status === "excluido" ? "excluído" : usuario.status ?? "ativo"}
                      </Badge>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">
                      {dataLegivel(usuario.ultimo_acesso)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <MenuAcoes
                        usuario={usuario}
                        souEu={usuario.id === usuarioLogado?.id}
                        souGlobal={souGlobal}
                        souAdmin={souAdmin}
                        podeVerSenha={podeVerSenha(usuario)}
                        aoEscolher={(tipo) => abrir(tipo, usuario)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* --- Novo usuário --- */}
      <Modal titulo="Novo usuário" aberto={novo} aoFechar={() => setNovo(false)}>
        <div className="space-y-3">
          <Campo rotulo="Nome">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} autoFocus />
          </Campo>
          <Campo rotulo="E-mail">
            <input type="email" className={estiloInput} value={email} onChange={(e) => setEmail(e.target.value)} />
          </Campo>
          <Campo rotulo="Nome de usuário (opcional — para entrar sem digitar o e-mail)">
            <input
              className={estiloInput}
              placeholder="ex.: maria.souza"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </Campo>
          <Campo rotulo="Cargo">
            <select className={estiloInput} value={cargo} onChange={(e) => setCargo(e.target.value)}>
              {CARGOS.map((c) => <option key={c.valor} value={c.valor}>{c.rotulo}</option>)}
            </select>
          </Campo>
          <Campo rotulo="Senha (mínimo 6 caracteres)">
            <input type="password" className={estiloInput} value={senha} onChange={(e) => setSenha(e.target.value)} />
          </Campo>
          {erroAcao && <Mensagem tipo="erro">{erroAcao}</Mensagem>}
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="neutro" onClick={() => setNovo(false)} disabled={ocupado}>Cancelar</Botao>
            <Botao
              disabled={ocupado || nome.trim().length < 2 || !email.includes("@") || senha.length < 6}
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
              ["Situação", alvo.status === "excluido" ? "excluído" : alvo.status ?? "ativo"],
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
            <Botao variante="neutro" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
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

      {/* --- Ver senha (gera uma nova e mostra UMA vez) --- */}
      <Modal titulo={`Senha de ${alvo?.nome ?? ""}`} aberto={acao?.tipo === "versenha"} aoFechar={() => setAcao(null)}>
        {senhaGerada === null ? (
          <>
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              Por proteção, as senhas ficam guardadas de forma <strong>embaralhada e
              irreversível</strong> — nem o sistema conhece a senha atual de{" "}
              <strong>{alvo?.nome}</strong>. Para “ver a senha”, o sistema gera uma{" "}
              <strong>senha nova</strong> e mostra aqui, uma única vez.
            </p>
            <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              A senha antiga deixa de funcionar na hora
              {alvo?.id === usuarioLogado?.id ? " (sua sessão atual continua aberta)" : ""}.
            </p>
            {alvo?.id === usuarioLogado?.id && (
              <div className="mt-3">
                <Campo rotulo="Confirme a sua senha atual">
                  <input
                    type="password"
                    className={estiloInput}
                    value={confirmacao}
                    onChange={(e) => setConfirmacao(e.target.value)}
                    autoFocus
                  />
                </Campo>
              </div>
            )}
            {erroAcao && <div className="mt-3"><Mensagem tipo="erro">{erroAcao}</Mensagem></div>}
            <div className="mt-4 flex justify-end gap-2">
              <Botao variante="neutro" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
              <Botao
                disabled={ocupado || (alvo?.id === usuarioLogado?.id && !confirmacao)}
                onClick={async () => {
                  setOcupado(true);
                  setErroAcao("");
                  try {
                    const resposta = await api<{ senha: string }>(
                      `${base}/${alvo?.id}/senha`, {
                        method: "POST",
                        body: JSON.stringify({ senha_atual: confirmacao || null }),
                      });
                    setSenhaGerada(resposta.senha);
                  } catch (excecao) {
                    setErroAcao(excecao instanceof ApiError ? excecao.message
                      : "Não foi possível gerar a senha.");
                  } finally {
                    setOcupado(false);
                  }
                }}
              >
                <Eye size={15} /> {ocupado ? "Gerando..." : "Gerar e mostrar senha"}
              </Botao>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              Nova senha de <strong>{alvo?.nome}</strong> — anote agora, ela não
              poderá ser vista de novo:
            </p>
            <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-500/20 dark:bg-emerald-500/10">
              <code className="select-all text-lg font-semibold tracking-wide text-emerald-800 dark:text-emerald-200">
                {senhaGerada}
              </code>
              <Botao variante="neutro" onClick={() => copiarTexto(senhaGerada, () => setCopiada(true))}>
                {copiada ? "Copiada!" : "Copiar"}
              </Botao>
            </div>
            <div className="mt-4 flex justify-end">
              <Botao onClick={() => setAcao(null)}>Fechar</Botao>
            </div>
          </>
        )}
      </Modal>

      {/* --- Alterar senha --- */}
      <Modal titulo={`Alterar senha de ${alvo?.nome ?? ""}`} aberto={acao?.tipo === "senha"} aoFechar={() => setAcao(null)}>
        <div className="space-y-3">
          <Campo rotulo="Nova senha (mínimo 6 caracteres)">
            <input type="password" className={estiloInput} value={senha} onChange={(e) => setSenha(e.target.value)} autoFocus />
          </Campo>
          <Campo rotulo="Repita a nova senha">
            <input type="password" className={estiloInput} value={senha2} onChange={(e) => setSenha2(e.target.value)} />
          </Campo>
          {senha2 && senha !== senha2 && (
            <p className="text-xs text-red-600 dark:text-red-400">As senhas não coincidem.</p>
          )}
          {erroAcao && <Mensagem tipo="erro">{erroAcao}</Mensagem>}
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="neutro" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
            <Botao
              disabled={ocupado || senha.length < 6 || senha !== senha2}
              onClick={() =>
                executar(`${base}/${alvo?.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ senha }),
                }, "Senha redefinida.")
              }
            >
              {ocupado ? "Salvando..." : "Alterar senha"}
            </Botao>
          </div>
        </div>
      </Modal>

      {/* --- Alterar permissões --- */}
      <Modal titulo={`Permissões de ${alvo?.nome ?? ""}`} aberto={acao?.tipo === "permissoes"} aoFechar={() => setAcao(null)}>
        <div className="space-y-2">
          {CARGOS.map((c) => (
            <label
              key={c.valor}
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                cargo === c.valor
                  ? "border-indigo-400 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-500/10"
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
            <Botao variante="neutro" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
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
          <Botao variante="neutro" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
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
          <Botao variante="neutro" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
          <Botao
            className="!bg-red-600 hover:!bg-red-500"
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
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-200">
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
          <Botao variante="neutro" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
          <Botao
            className="!bg-red-600 hover:!bg-red-500"
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
