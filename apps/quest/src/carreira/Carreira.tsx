/**
 * Carreira — o histórico do astronauta: estatísticas, conquistas e as
 * atividades feitas. Na Q0 as conquistas se derivam do estado do perfil e o
 * histórico de missões é um estado vazio acolhedor (os planetas abrem na Q1).
 */
import { useEffect, useState } from "react";

import { minhasConquistas } from "@constela/quest-core";
import type { ConquistaAluno, PerfilQuest } from "@constela/quest-core";

import { useSessao } from "../estado/sessao";
import "./carreira.css";

interface Conquista {
  icone: string;
  nome: string;
  descricao: string;
  obtida: boolean;
}

function conquistas(perfil: PerfilQuest): Conquista[] {
  const avatar = perfil.avatar;
  const mudouVisual = avatar.rosto !== "sorriso" || avatar.chapeu !== "nenhum"
    || avatar.cor !== "#FF4D9D";
  return [
    { icone: "🚀", nome: "Bem-vindo a bordo!", descricao: "Entrou no Constela Quest", obtida: true },
    { icone: "✏️", nome: "Esse é meu nome", descricao: "Escolheu como quer ser chamado", obtida: !!perfil.nome_exibicao },
    { icone: "👕", nome: "Estilista espacial", descricao: "Trocou o visual no vestiário", obtida: mudouVisual },
    { icone: "🛹", nome: "Skatista das estrelas", descricao: "Equipou o skate voador", obtida: avatar.veiculo === "skate" },
    { icone: "🎯", nome: "Primeira missão", descricao: "Complete sua primeira missão", obtida: false },
    { icone: "⭐", nome: "Colecionador de estrelas", descricao: "Junte 100 estrelas", obtida: false },
    { icone: "🪐", nome: "Explorador de planetas", descricao: "Visite 3 planetas", obtida: false },
    { icone: "🔥", nome: "Chama de 7 dias", descricao: "Jogue 7 dias seguidos", obtida: false },
  ];
}

function dataCurta(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** Conquistas de APRENDIZADO (Matific/Elefante) — o backend é a fonte da
 *  verdade (resolve o aluno pela sessão); o app só LÊ e mostra. */
function PainelAprendizado() {
  const [itens, setItens] = useState<ConquistaAluno[] | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    let vivo = true;
    minhasConquistas()
      .then((r) => { if (vivo) setItens(r.conquistas); })
      .catch(() => { if (vivo) setItens([]); })   // erro → estado vazio acolhedor
      .finally(() => { if (vivo) setCarregando(false); });
    return () => { vivo = false; };
  }, []);

  if (carregando) {
    return (
      <div className="painel">
        <h2>Conquistas de aprendizado</h2>
        <p className="conquistas-carregando">Buscando suas conquistas… ✨</p>
      </div>
    );
  }
  const lista = itens ?? [];
  const desbloqueadas = lista.filter((c) => c.atingida).length;

  return (
    <div className="painel">
      <h2>Conquistas de aprendizado <small>{desbloqueadas}/{lista.length}</small></h2>
      {lista.length === 0 ? (
        <p className="conquistas-carregando">
          Suas conquistas de leitura e matemática vão aparecer aqui assim que você
          praticar! 🚀
        </p>
      ) : (
        <div className="conquistas-grade">
          {lista.map((c) => (
            <div key={c.codigo}
                 className={`conquista${c.atingida ? "" : " bloqueada"}`}>
              <span className="conquista-icone" aria-hidden>{c.atingida ? c.icone : "🔒"}</span>
              <b>{c.nome}</b>
              {/* Desbloqueada → descrição; em andamento → o critério ("Leia 100 livros"). */}
              <span className="conquista-desc">{c.atingida ? c.descricao : c.criterio}</span>
              {c.atingida ? (
                <span className="conquista-status ok">
                  ✓ Conquistada{c.data ? ` em ${dataCurta(c.data)}` : ""}
                </span>
              ) : (
                <div className="conquista-progresso">
                  <div className="barra" role="progressbar"
                       aria-valuenow={Math.round(c.pct)} aria-valuemin={0} aria-valuemax={100}>
                    <div className="barra-cheia" style={{ width: `${Math.min(100, Math.max(0, c.pct))}%` }} />
                  </div>
                  <span className="conquista-progresso-txt">
                    {Math.round(c.progresso)} / {Math.round(c.limite)}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Carreira() {
  const { perfil } = useSessao();
  if (!perfil) return null;
  const lista = conquistas(perfil);
  const obtidas = lista.filter((c) => c.obtida).length;

  return (
    <section className="view carreira">
      <div className="carreira-wrap">
        <div className="painel">
          <h1>🏆 Minha Carreira</h1>
          <div className="stats-linha">
            <div className="stat"><b>{perfil.nivel}</b><span>Nível</span></div>
            <div className="stat"><b>{perfil.xp_total}</b><span>XP total</span></div>
            <div className="stat"><b>{perfil.moedas}</b><span>🪙 Moedas</span></div>
            <div className="stat"><b>{perfil.estrelas_total}</b><span>⭐ Estrelas</span></div>
            <div className="stat"><b>{perfil.sequencia_dias}</b><span>🔥 Dias seguidos</span></div>
          </div>
        </div>

        <div className="painel">
          <h2>Sua jornada no Quest <small>{obtidas}/{lista.length}</small></h2>
          <div className="conquistas-grade">
            {lista.map((c) => (
              <div key={c.nome} className={`conquista${c.obtida ? "" : " bloqueada"}`}>
                <span className="conquista-icone" aria-hidden>{c.obtida ? c.icone : "🔒"}</span>
                <b>{c.nome}</b>
                <span className="conquista-desc">{c.descricao}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Conquistas REAIS de aprendizado (leitura/matemática) — do backend. */}
        <PainelAprendizado />

        <div className="painel">
          <h2>Minhas aventuras</h2>
          <div className="historico-vazio">
            <span aria-hidden>🗺️</span>
            <b>Suas missões vão aparecer aqui!</b>
            <p>Quando os planetas abrirem, cada missão que você fizer entra na
              sua história — com pontos, estrelas e o dia que você jogou.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
