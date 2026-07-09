/**
 * Carreira — o histórico do astronauta: estatísticas, conquistas e as
 * atividades feitas. Na Q0 as conquistas se derivam do estado do perfil e o
 * histórico de missões é um estado vazio acolhedor (os planetas abrem na Q1).
 */
import type { PerfilQuest } from "@constela/quest-core";

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
          <h2>Minhas conquistas <small>{obtidas}/{lista.length}</small></h2>
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
