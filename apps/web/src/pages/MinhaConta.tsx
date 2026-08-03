/**
 * Minha conta (autoatendimento) — QUALQUER usuário autenticado vê os dados da
 * PRÓPRIA conta. Reusa o que o backend já entrega em `/auth/me` (disponível no
 * AppContext), sem nenhuma permissão nova e sem depender de escola selecionada.
 *
 * NÃO confundir com "Usuários" (/usuarios), que é a GESTÃO de usuários da escola
 * (criar/editar/excluir), exclusiva de admin/coordenador. Aqui é só a leitura da
 * própria conta — por isso funciona também para a Secretaria (que opera no
 * contexto "Toda a Rede", sem escola própria).
 */
import { AtSign, IdCard, Mail, ShieldCheck, User } from "lucide-react";

import { Card, PageHeader } from "../components/ui";
import { useApp } from "../context/AppContext";

function rotuloPerfil(u: {
  is_global: boolean; rede_id?: number | null; cargo: string;
}): string {
  if (u.is_global) return "Administrador Global";
  if (u.rede_id != null) return "Secretaria de Educação";
  if (u.cargo === "coordenador") return "Coordenação";
  if (u.cargo === "admin") return "Administração da escola";
  return "Professor(a)";
}

function dataLegivel(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function Linha({ icone: Icone, rotulo, valor }: {
  icone: typeof User; rotulo: string; valor: string;
}) {
  return (
    <div className="flex items-start gap-3 py-3">
      <Icone size={18} className="mt-0.5 shrink-0 text-zinc-400" aria-hidden />
      <div className="min-w-0">
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">{rotulo}</p>
        <p className="break-words text-sm text-zinc-800 dark:text-zinc-100">{valor}</p>
      </div>
    </div>
  );
}

export default function MinhaConta() {
  const { usuario } = useApp();
  if (!usuario) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <PageHeader
        titulo="Minha conta"
        descricao="Os dados da sua conta no Constela Edu."
      />

      <Card className="divide-y divide-zinc-100 px-5 dark:divide-zinc-800/60">
        <Linha icone={User} rotulo="Nome" valor={usuario.nome} />
        <Linha icone={Mail} rotulo="E-mail" valor={usuario.email} />
        {usuario.username && (
          <Linha icone={AtSign} rotulo="Nome de usuário" valor={`@${usuario.username}`} />
        )}
        <Linha icone={ShieldCheck} rotulo="Perfil de acesso" valor={rotuloPerfil(usuario)} />
        <Linha icone={IdCard} rotulo="Último acesso" valor={dataLegivel(usuario.ultimo_acesso)} />
      </Card>

      <p className="px-1 text-xs text-zinc-500 dark:text-zinc-400">
        Para trocar a sua senha, peça ao administrador da escola um link de
        redefinição (uso único). Precisa corrigir algum dado desta conta? Fale
        também com o administrador.
      </p>
    </div>
  );
}
