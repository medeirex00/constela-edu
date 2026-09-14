/**
 * Usuários de UMA escola, dentro da gestão de escolas do administrador GLOBAL.
 *
 * Existe para o primeiro acesso: a escola recém-criada (0 turmas, 0 alunos,
 * Lista Piloto não iniciada) precisa de um coordenador/diretor ANTES de
 * qualquer dado acadêmico. A escola vem por prop — nunca do seletor do topo —
 * então a conta nasce vinculada à escola aberta. Reusa os endpoints
 * `/escolas/{id}/usuarios`: o backend decide permissão (só admin/global),
 * unicidade de e-mail/@, força da senha, escopo (o `escola_id` é o da URL;
 * `is_global`/`rede_id` nunca vêm do corpo) e auditoria.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { ApiError, api } from "../lib/api";
import { CARGOS, rotuloCargo } from "../lib/cargos";
import type { Escola, Usuario } from "../lib/types";
import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  Modal,
  Vazio,
  estiloInput,
} from "./ui";

export default function UsuariosDaEscola({
  escola,
  aoFechar,
}: {
  escola: Escola;
  aoFechar?: () => void;
}) {
  const base = `/escolas/${escola.id}/usuarios`;
  const navigate = useNavigate();
  const { selecionarEscola } = useApp();

  const [usuarios, setUsuarios] = useState<Usuario[] | null>(null);
  const [erroLista, setErroLista] = useState("");
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  // formulário "Adicionar usuário"
  const [novo, setNovo] = useState(false);
  const [erroAcao, setErroAcao] = useState("");
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [senha, setSenha] = useState("");
  const [cargo, setCargo] = useState<string>("coordenador");

  // Contador de pedidos: uma resposta atrasada da escola ANTERIOR (o gestor
  // trocou de escola antes de ela chegar) é descartada — nunca mostra a
  // equipe de uma escola sob o cabeçalho de outra.
  const pedido = useRef(0);
  const carregar = useCallback(() => {
    const meu = ++pedido.current;
    setErroLista("");
    api<Usuario[]>(base)
      .then((lista) => {
        if (meu === pedido.current) setUsuarios(lista);
      })
      .catch((excecao) => {
        if (meu !== pedido.current) return;
        setUsuarios([]);
        setErroLista(excecao instanceof Error ? excecao.message : "Sem acesso.");
      });
  }, [base]);

  // Trocar de escola zera a lista (não mostra a equipe da escola anterior).
  useEffect(() => {
    setUsuarios(null);
    setMensagem(null);
    carregar();
  }, [carregar]);

  // A seção nasce ABAIXO da lista de escolas: rola até ela e leva o foco ao
  // título ao abrir/trocar de escola (senão o clique parece não fazer nada
  // numa rede com muitas escolas).
  const titulo = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const el = titulo.current;
    if (!el) return;
    if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "start", behavior: "smooth" });
    el.focus({ preventScroll: true });
  }, [escola.id]);

  function abrirNovo() {
    setErroAcao("");
    setNome("");
    setEmail("");
    setUsername("");
    setSenha("");
    setCargo("coordenador");
    setNovo(true);
  }

  async function criar() {
    setOcupado(true);
    setErroAcao("");
    try {
      await api<Usuario>(base, {
        method: "POST",
        body: JSON.stringify({
          nome: nome.trim(),
          email: email.trim(),
          username: username.trim() || null,
          senha,
          cargo,
        }),
      });
      setMensagem({
        tipo: "ok",
        texto: `Usuário “${nome.trim()}” criado como ${rotuloCargo(cargo).toLowerCase()} em ${escola.nome}.`,
      });
      setNovo(false);
      carregar();
    } catch (excecao) {
      setErroAcao(excecao instanceof ApiError ? excecao.message : "Não foi possível criar o usuário.");
    } finally {
      setOcupado(false);
    }
  }

  async function alternarStatus(alvo: Usuario) {
    const novoStatus = alvo.status === "ativo" ? "inativo" : "ativo";
    setOcupado(true);
    try {
      await api(`${base}/${alvo.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: novoStatus }),
      });
      setMensagem({ tipo: "ok", texto: novoStatus === "ativo" ? "Usuário reativado." : "Usuário desativado." });
      carregar();
    } catch (excecao) {
      setMensagem({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message : "Não foi possível alterar o usuário.",
      });
    } finally {
      setOcupado(false);
    }
  }

  function gestaoCompleta() {
    // A página /usuarios opera sobre a escola do seletor do topo: alinha o
    // seletor a ESTA escola antes de navegar (redefinir senha, turmas, @ etc.).
    selecionarEscola(escola.id);
    navigate("/usuarios");
  }

  const podeCriar = nome.trim().length >= 2 && email.includes("@") && senha.length >= 8;

  return (
    <Card className="mt-6">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div>
          <h2 ref={titulo} tabIndex={-1} className="text-base font-semibold tracking-tight outline-none">
            Usuários de {escola.nome}
          </h2>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            Contas de acesso desta escola. Podem ser criadas antes de turmas, alunos, Lista Piloto e integrações.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Botao onClick={abrirNovo} disabled={ocupado}>+ Adicionar usuário</Botao>
          <Botao variante="neutro" onClick={gestaoCompleta}>Gestão completa</Botao>
          {aoFechar && <Botao variante="neutro" onClick={aoFechar}>Fechar</Botao>}
        </div>
      </div>

      {mensagem && (
        <div className="px-4 pt-3">
          <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
        </div>
      )}

      {usuarios === null ? (
        <Carregando />
      ) : erroLista ? (
        <Vazio
          titulo="Não foi possível carregar os usuários"
          descricao={erroLista}
          acao={<Botao variante="neutro" onClick={carregar}>Tentar de novo</Botao>}
        />
      ) : usuarios.length === 0 ? (
        <Vazio
          titulo="Esta escola ainda não possui usuários."
          descricao="Crie o primeiro acesso — normalmente o coordenador ou diretor — para a escola poder ser configurada (turmas, alunos, integrações e Lista Piloto vêm depois)."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <th className="px-4 py-2 font-medium">Nome</th>
                <th className="px-4 py-2 font-medium">E-mail / login</th>
                <th className="px-4 py-2 font-medium">Cargo</th>
                <th className="px-4 py-2 font-medium">Situação</th>
                <th className="px-4 py-2 text-right font-medium">Ações</th>
              </tr>
            </thead>
            <tbody>
              {usuarios.map((u) => (
                <tr key={u.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <td className="px-4 py-2.5 font-medium">
                    {u.nome}
                    {u.is_global && <span className="ml-2 text-xs text-zinc-500">(global)</span>}
                  </td>
                  <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-300">
                    <div>{u.email}</div>
                    {u.username && <div className="text-xs text-zinc-500 dark:text-zinc-400">@{u.username}</div>}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tom="destaque">{rotuloCargo(u.cargo)}</Badge>
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tom={(u.status ?? "ativo") === "ativo" ? "ok" : "neutro"}>{u.status ?? "ativo"}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {!u.is_global && (
                      <Botao
                        variante="neutro"
                        className="px-2 py-1 text-xs"
                        disabled={ocupado}
                        onClick={() => alternarStatus(u)}
                        aria-label={`${u.status === "ativo" ? "Desativar" : "Reativar"} ${u.nome}`}
                      >
                        {u.status === "ativo" ? "Desativar" : "Reativar"}
                      </Botao>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal titulo={`Adicionar usuário em ${escola.nome}`} aberto={novo} aoFechar={() => setNovo(false)}>
        <div className="space-y-3">
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            A conta fica vinculada somente a <strong>{escola.nome}</strong>. Ela não recebe acesso global nem de rede.
          </p>
          {/* autoComplete: o gestor está criando a conta de OUTRA pessoa — o
              navegador não deve preencher o e-mail/senha do próprio gestor
              nem guardar a senha inicial no cofre dele (mesma convenção de
              CredenciaisForm/RedefinirSenha). */}
          <Campo rotulo="Nome">
            <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} autoFocus autoComplete="off" />
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
              {CARGOS.map((c) => (
                <option key={c.valor} value={c.valor}>{c.rotulo}</option>
              ))}
            </select>
          </Campo>
          <p className="-mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            {CARGOS.find((c) => c.valor === cargo)?.descricao}
          </p>
          <Campo rotulo="Senha inicial (mínimo 8 caracteres; não use senhas comuns nem o próprio e-mail)">
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
            <Botao variante="neutro" onClick={() => setNovo(false)} disabled={ocupado}>Cancelar</Botao>
            <Botao disabled={ocupado || !podeCriar} onClick={criar}>
              {ocupado ? "Salvando..." : "Criar usuário"}
            </Botao>
          </div>
        </div>
      </Modal>
    </Card>
  );
}
