/**
 * "Usuários" dentro das páginas de UMA escola (Comece aqui, Visão da Escola) —
 * exclusivo do Admin Global.
 *
 * É o caminho Escola → Usuários para cadastrar o primeiro acesso (coordenador)
 * de uma escola recém-criada, ANTES de turmas, alunos, Lista Piloto e
 * integrações: não consulta nada do estado acadêmico da escola. A escola é a
 * SELECIONADA no topo — a mesma cujo detalhe está aberto. Coordenador e
 * professor não veem nada aqui (a gestão de usuários deles segue como já era);
 * o backend continua sendo a trava (POST /escolas/{id}/usuarios exige admin).
 */
import { UserCog } from "lucide-react";
import { useEffect, useState } from "react";

import { useApp } from "../context/AppContext";
import { usePerfil } from "../hooks/usePerfil";
import { Botao } from "./ui";
import UsuariosDaEscola from "./UsuariosDaEscola";

export default function AcessoUsuariosDaEscola() {
  const { global } = usePerfil();
  const { escolaId, escolas } = useApp();
  const [aberto, setAberto] = useState(false);

  // Trocou de escola no topo: fecha a seção — nunca a equipe de uma escola sob o
  // detalhe de outra.
  useEffect(() => {
    setAberto(false);
  }, [escolaId]);

  const escola = escolas.find((item) => item.id === escolaId);
  if (!global || !escola) return null;

  if (aberto) {
    return (
      <div className="mb-4">
        <UsuariosDaEscola escola={escola} aoFechar={() => setAberto(false)} />
      </div>
    );
  }
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <Botao variante="neutro" onClick={() => setAberto(true)}>
        <UserCog size={15} /> Usuários
      </Botao>
      <span className="text-xs text-zinc-500 dark:text-zinc-400">
        Contas de acesso desta escola — o coordenador pode ser criado antes de turmas, alunos e Lista Piloto.
      </span>
    </div>
  );
}
