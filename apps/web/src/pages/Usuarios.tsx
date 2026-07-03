/** CRUD de usuários (PRD §18) — somente administradores. */
import { UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

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
import { api } from "../lib/api";
import type { Usuario } from "../lib/types";

const CARGOS = ["admin", "coordenador", "professor", "visitante"];

interface Formulario {
  id: number | null;
  nome: string;
  email: string;
  senha: string;
  cargo: string;
  status: string;
}

const FORM_VAZIO: Formulario = { id: null, nome: "", email: "", senha: "", cargo: "visitante", status: "ativo" };

interface UsuarioLinha extends Usuario {
  status?: string;
}

export default function Usuarios() {
  const { escolaId, usuario: usuarioLogado } = useApp();
  const [usuarios, setUsuarios] = useState<UsuarioLinha[] | null>(null);
  const [formulario, setFormulario] = useState<Formulario | null>(null);
  const [erro, setErro] = useState("");
  const [erroLista, setErroLista] = useState("");
  const [salvando, setSalvando] = useState(false);

  const carregar = useCallback(() => {
    if (!escolaId) return;
    api<UsuarioLinha[]>(`/escolas/${escolaId}/usuarios`)
      .then(setUsuarios)
      .catch((excecao) => {
        setUsuarios([]);
        setErroLista(excecao instanceof Error ? excecao.message : "Sem acesso.");
      });
  }, [escolaId]);

  useEffect(carregar, [carregar]);

  async function salvar() {
    if (!escolaId || !formulario) return;
    setSalvando(true);
    setErro("");
    try {
      if (formulario.id === null) {
        await api(`/escolas/${escolaId}/usuarios`, {
          method: "POST",
          body: JSON.stringify({
            nome: formulario.nome.trim(),
            email: formulario.email.trim(),
            senha: formulario.senha,
            cargo: formulario.cargo,
          }),
        });
      } else {
        await api(`/escolas/${escolaId}/usuarios/${formulario.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            nome: formulario.nome.trim(),
            cargo: formulario.cargo,
            status: formulario.status,
            ...(formulario.senha ? { senha: formulario.senha } : {}),
          }),
        });
      }
      setFormulario(null);
      carregar();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div>
      <PageHeader
        titulo="Usuários"
        descricao="Contas de acesso desta escola. Toda alteração fica no log de auditoria."
        acoes={
          <Botao onClick={() => { setFormulario(FORM_VAZIO); setErro(""); }}>
            <UserPlus size={15} /> Novo usuário
          </Botao>
        }
      />

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
                  <th className="px-4 py-2 font-medium">E-mail</th>
                  <th className="px-4 py-2 font-medium">Cargo</th>
                  <th className="px-4 py-2 font-medium">Situação</th>
                  <th className="px-4 py-2" />
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
                    </td>
                    <td className="px-4 py-2.5 text-zinc-500 dark:text-zinc-400">{usuario.email}</td>
                    <td className="px-4 py-2.5"><Badge tom="destaque">{usuario.cargo}</Badge></td>
                    <td className="px-4 py-2.5">
                      <Badge tom={usuario.status === "ativo" ? "ok" : "neutro"}>
                        {usuario.status ?? "ativo"}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                        onClick={() => {
                          setFormulario({
                            id: usuario.id,
                            nome: usuario.nome,
                            email: usuario.email,
                            senha: "",
                            cargo: usuario.cargo,
                            status: usuario.status ?? "ativo",
                          });
                          setErro("");
                        }}
                      >
                        editar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        titulo={formulario?.id === null ? "Novo usuário" : "Editar usuário"}
        aberto={formulario !== null}
        aoFechar={() => setFormulario(null)}
      >
        {formulario && (
          <div className="space-y-3">
            <Campo rotulo="Nome">
              <input className={estiloInput} value={formulario.nome}
                     onChange={(e) => setFormulario({ ...formulario, nome: e.target.value })} />
            </Campo>
            <Campo rotulo="E-mail">
              <input
                type="email" className={estiloInput} value={formulario.email}
                disabled={formulario.id !== null}
                onChange={(e) => setFormulario({ ...formulario, email: e.target.value })}
              />
            </Campo>
            <div className="grid grid-cols-2 gap-3">
              <Campo rotulo="Cargo">
                <select className={estiloInput} value={formulario.cargo}
                        onChange={(e) => setFormulario({ ...formulario, cargo: e.target.value })}>
                  {CARGOS.map((cargo) => <option key={cargo} value={cargo}>{cargo}</option>)}
                </select>
              </Campo>
              {formulario.id !== null && (
                <Campo rotulo="Situação">
                  <select className={estiloInput} value={formulario.status}
                          onChange={(e) => setFormulario({ ...formulario, status: e.target.value })}>
                    <option value="ativo">ativo</option>
                    <option value="inativo">inativo</option>
                  </select>
                </Campo>
              )}
            </div>
            <Campo rotulo={formulario.id === null ? "Senha (mínimo 6 caracteres)" : "Nova senha (deixe vazio para manter)"}>
              <input type="password" className={estiloInput} value={formulario.senha}
                     onChange={(e) => setFormulario({ ...formulario, senha: e.target.value })} />
            </Campo>
            {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
            <div className="flex justify-end gap-2 pt-1">
              <Botao variante="neutro" onClick={() => setFormulario(null)} disabled={salvando}>Cancelar</Botao>
              <Botao
                onClick={salvar}
                disabled={
                  salvando || !formulario.nome.trim() || !formulario.email.trim()
                  || (formulario.id === null && formulario.senha.length < 6)
                }
              >
                {salvando ? "Salvando..." : "Salvar"}
              </Botao>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
