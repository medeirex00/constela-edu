/**
 * Minha conta (autoatendimento) — QUALQUER usuário autenticado vê os dados da
 * PRÓPRIA conta. Reusa o que o backend já entrega em `/auth/me` (disponível no
 * AppContext), sem nenhuma permissão nova e sem depender de escola selecionada.
 *
 * NÃO confundir com "Usuários" (/usuarios), que é a GESTÃO de usuários da escola
 * (criar/editar/excluir), exclusiva de admin/coordenador. Aqui é só a leitura da
 * própria conta — por isso funciona também para a Secretaria (que opera no
 * contexto "Toda a Rede", sem escola própria).
 *
 * Identidade v2: cabeçalho de perfil (avatar com iniciais, nome e o perfil numa
 * pílula) e as linhas com ícone em quadrado pastel. Cada dado aparece UMA vez (o
 * nome no cabeçalho, o perfil na pílula). Não há edição nem troca de senha aqui:
 * não existe autoatendimento para isso (a política é o link de redefinição).
 */
import { AtSign, Clock, KeyRound, Mail } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Avatar, Card, IconePastel, PageHeader, type TomPastel } from "../components/ui";
import { useApp } from "../context/AppContext";
import { dataHora } from "../lib/formato";

function rotuloPerfil(u: {
  is_global: boolean; rede_id?: number | null; cargo: string;
}): string {
  if (u.is_global) return "Administrador Global";
  if (u.rede_id != null) return "Secretaria de Educação";
  if (u.cargo === "coordenador") return "Coordenação";
  if (u.cargo === "admin") return "Administração da escola";
  return "Professor(a)";
}

/** Cor da pílula do perfil (o texto sempre diz o perfil; a cor só reforça). */
function estiloPerfil(u: { is_global: boolean; rede_id?: number | null; cargo: string }): string {
  if (u.is_global) return "bg-indigo-600 text-white";
  if (u.rede_id != null) return "bg-teal-50 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300";
  if (u.cargo === "coordenador" || u.cargo === "admin") {
    return "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300";
  }
  return "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300";
}

/** A quem pedir o link de redefinição de senha. É a MESMA régua do backend
 *  (`admin._usuario_alvo` e `deps.negar_secretaria`): conta da Secretaria (rede) ou
 *  global só o Admin Global da plataforma administra — o administrador da escola
 *  recebe 403 e a própria Secretaria não gera link. Os demais perfis pedem à escola. */
function orientacaoSenha(u: { is_global: boolean; rede_id?: number | null }): string {
  if (u.is_global) {
    return "A senha de uma conta global só pode ser redefinida por outro Administrador " +
      "Global da plataforma: peça a ele um link de redefinição (uso único). Precisa " +
      "corrigir algum dado desta conta? Fale também com ele.";
  }
  if (u.rede_id != null) {
    return "Por segurança, a senha da conta da Secretaria só pode ser redefinida pelo " +
      "Administrador Global da plataforma (a equipe do Constela Edu): peça a ele um link " +
      "de redefinição (uso único). O administrador da escola não tem acesso a esta conta. " +
      "Precisa corrigir algum dado? Fale também com o Administrador Global.";
  }
  return "Para trocar a sua senha, peça ao administrador da escola um link de " +
    "redefinição (uso único). Precisa corrigir algum dado desta conta? Fale " +
    "também com o administrador.";
}

/** No fuso de Brasília (a API manda UTC sem marca de fuso; `new Date` adiantava 3 h). */
function dataLegivel(iso: string | null | undefined): string {
  return iso ? dataHora(iso) : "—";
}

function Linha({ icone, tom, rotulo, valor }: {
  icone: LucideIcon; tom: TomPastel; rotulo: string; valor: string;
}) {
  return (
    <div className="flex items-center gap-4 py-4">
      <IconePastel icone={icone} tom={tom} />
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">{rotulo}</p>
        <p className="mt-0.5 break-words text-[15px] font-medium text-zinc-900 dark:text-zinc-100">{valor}</p>
      </div>
    </div>
  );
}

export default function MinhaConta() {
  const { usuario } = useApp();
  if (!usuario) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader
        titulo="Minha conta"
        descricao="Os dados da sua conta no Constela Edu."
      />

      {/* Cabeçalho de perfil: faixa violeta, avatar e o perfil de acesso. Só o avatar
          sobe sobre a faixa; o nome e a pílula começam abaixo dela, no branco (o nome
          escuro sobre o degradê ficava sem contraste e "colado" na emenda). O avatar usa
          a mesma chave de cor (o id) da barra lateral, de Usuários e de Sessões. */}
      <Card className="overflow-hidden">
        <div aria-hidden className="h-20 bg-gradient-to-r from-indigo-600 via-indigo-500 to-marinho-800" />
        <div className="flex items-start gap-4 px-6 pb-6">
          <Avatar nome={usuario.nome} chave={usuario.id} tamanho="xl" className="-mt-9 ring-4" />
          <div className="min-w-0 flex-1 pt-3">
            <h2 className="truncate text-xl font-bold tracking-tight text-zinc-900 dark:text-white" title={usuario.nome}>{usuario.nome}</h2>
            <span className={`mt-1.5 inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${estiloPerfil(usuario)}`}>
              <span className="sr-only">Perfil de acesso: </span>
              {rotuloPerfil(usuario)}
            </span>
          </div>
        </div>
      </Card>

      <Card className="divide-y divide-zinc-100 px-6 dark:divide-zinc-800/60">
        <Linha icone={Mail} tom="violeta" rotulo="E-mail" valor={usuario.email} />
        {usuario.username && (
          <Linha icone={AtSign} tom="teal" rotulo="Nome de usuário" valor={`@${usuario.username}`} />
        )}
        <Linha icone={Clock} tom="azul" rotulo="Último acesso" valor={dataLegivel(usuario.ultimo_acesso)} />
      </Card>

      {/* Informativo (sem fluxo novo): troca de senha e correção de dados são com quem
          administra a conta — e a pessoa certa depende do perfil (orientacaoSenha). */}
      <div className="flex items-start gap-4 rounded-cartao border border-ouro-200 bg-ouro-50 p-5 dark:border-ouro-400/25 dark:bg-ouro-400/10">
        <IconePastel icone={KeyRound} tom="ambar" />
        <div className="text-sm">
          <p className="font-semibold text-zinc-900 dark:text-zinc-100">Senha e dados da conta</p>
          <p className="mt-1 text-zinc-700 dark:text-zinc-300">{orientacaoSenha(usuario)}</p>
        </div>
      </div>
    </div>
  );
}
