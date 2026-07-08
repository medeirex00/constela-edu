/** Perfil público do aluno (PRD §120): somente dados pedagógicos, sem login. */
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../lib/api";
import { nota } from "../../lib/formato";

interface PerfilPublicoDados {
  nome: string;
  turma: string | null;
  posicao: number | null;
  nota_matific: number;
  nota_elefante: number;
  nota_geral: number;
  nivel: number;
  xp: number;
  conquistas: { nome: string; icone: string; descricao: string }[];
  escola: string;
}

export default function PerfilPublico() {
  const { token = "", id } = useParams();
  const [perfil, setPerfil] = useState<PerfilPublicoDados | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    // Cliente compartilhado (base VITE_API_URL): fetch relativo só funciona
    // em dev — na Vercel devolveria o HTML do SPA no lugar do JSON.
    api<PerfilPublicoDados>(`/publico/${token}/alunos/${id}`)
      .then(setPerfil)
      .catch(() => setErro(true));
  }, [token, id]);

  if (erro) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-300">
        <p className="text-xl">Perfil não disponível.</p>
      </div>
    );
  }
  if (!perfil) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-400">
        Carregando...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 px-4 py-10 text-white">
      <div className="mx-auto max-w-2xl">
        <Link
          to={`/p/${token}`}
          className="mb-6 inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-white"
        >
          <ArrowLeft size={15} /> Voltar ao painel
        </Link>

        <div className="rounded-2xl bg-white/5 p-8 text-center">
          <p className="text-sm uppercase tracking-wide text-zinc-400">{perfil.escola}</p>
          <h1 className="mt-2 text-3xl font-bold">{perfil.nome}</h1>
          <p className="mt-1 text-zinc-400">{perfil.turma}</p>
          {perfil.posicao && (
            <p className="mt-3 inline-block rounded-full bg-amber-400/20 px-4 py-1 text-amber-200">
              {perfil.posicao}º no Ranking Geral
            </p>
          )}

          <div className="mt-8 grid grid-cols-3 gap-3">
            {[
              { rotulo: "Matific", valor: perfil.nota_matific },
              { rotulo: "Leitura", valor: perfil.nota_elefante },
              { rotulo: "Geral", valor: perfil.nota_geral },
            ].map((item) => (
              <div key={item.rotulo} className="rounded-xl bg-white/5 p-4">
                <p className="text-xs uppercase tracking-wide text-zinc-400">{item.rotulo}</p>
                <p className="mt-1 text-2xl font-bold tabular-nums">{nota(item.valor)}</p>
              </div>
            ))}
          </div>

          <p className="mt-6 text-sm text-zinc-400">
            Nível <strong className="text-white">{perfil.nivel}</strong> ·{" "}
            {perfil.xp.toLocaleString("pt-BR")} XP
          </p>
        </div>

        {perfil.conquistas.length > 0 && (
          <div className="mt-6 rounded-2xl bg-white/5 p-6">
            <h2 className="mb-4 text-lg font-semibold">Conquistas</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {perfil.conquistas.map((conquista) => (
                <div key={conquista.nome} className="flex items-start gap-3 rounded-xl bg-white/5 p-3">
                  <span className="text-2xl">{conquista.icone}</span>
                  <div>
                    <p className="font-medium">{conquista.nome}</p>
                    <p className="text-sm text-zinc-400">{conquista.descricao}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
