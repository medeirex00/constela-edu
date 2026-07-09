/**
 * Entrada do astronauta — 3 passos, um por tela (docs/quest/04):
 *
 *   1. código do cartão ("SOL-1234", tolerante a como a criança digita)
 *   2. "É você?" — mostra nome/apelido/avatar antes de pedir o segredo
 *   3. PIN: tocar as 4 figuras na ordem do cartão
 *
 * Erro nunca culpa: mensagem gentil + narração, e o Cosmo continua sorrindo.
 */
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@constela/core";
import { entrar, obterFiguras, quemE } from "@constela/quest-core";
import type { Figura, Quem, SessaoQuest } from "@constela/quest-core";

import { narrar, tocar } from "../audio/audio";
import { Cosmo } from "../cosmo/Cosmo";
import "./entrada.css";

type Passo = "codigo" | "quem" | "pin";

interface EntradaProps {
  aoEntrar(sessao: SessaoQuest): void;
}

export function Entrada({ aoEntrar }: EntradaProps) {
  const [passo, setPasso] = useState<Passo>("codigo");
  const [codigo, setCodigo] = useState("");
  const [quem, setQuem] = useState<Quem | null>(null);
  const [figuras, setFiguras] = useState<Figura[]>([]);
  const [pin, setPin] = useState<string[]>([]);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const campoCodigo = useRef<HTMLInputElement>(null);

  useEffect(() => {
    obterFiguras().then(setFiguras).catch(() => setFiguras([]));
  }, []);

  useEffect(() => {
    if (passo === "codigo") campoCodigo.current?.focus();
    if (passo === "pin") narrar("Agora toque nas suas quatro figuras secretas, na ordem do cartão.");
  }, [passo]);

  const falhar = (mensagem: string) => {
    setErro(mensagem);
    tocar("erro");
    narrar(mensagem);
  };

  const confirmarCodigo = async () => {
    if (!codigo.trim() || ocupado) return;
    setOcupado(true);
    setErro("");
    try {
      const resposta = await quemE(codigo);
      setQuem(resposta);
      setPasso("quem");
      tocar("clique");
      narrar(`Encontrei! É você, ${resposta.primeiro_nome}?`);
    } catch (excecao) {
      falhar(excecao instanceof ApiError ? excecao.message
        : "Não consegui procurar agora. Tente de novo!");
    } finally {
      setOcupado(false);
    }
  };

  const tocarFigura = async (slug: string) => {
    if (ocupado || pin.includes(slug)) return;
    tocar("clique");
    const novo = [...pin, slug];
    setPin(novo);
    if (novo.length < 4) return;

    setOcupado(true);
    setErro("");
    try {
      const sessao = await entrar(codigo, novo);
      tocar("fanfarra");
      narrar(`Bem-vindo a bordo, ${sessao.perfil.primeiro_nome}!`);
      aoEntrar(sessao);
    } catch (excecao) {
      setPin([]);
      falhar(excecao instanceof ApiError ? excecao.message
        : "As figuras não bateram. Tente de novo!");
    } finally {
      setOcupado(false);
    }
  };

  const voltarAoInicio = () => {
    setPasso("codigo");
    setQuem(null);
    setPin([]);
    setErro("");
  };

  return (
    <div className="entrada">
      <div className="cosmo-canto">
        <Cosmo altura="52vh" />
      </div>

      <div className="entrada-painel">
        <div className="entrada-marca" aria-hidden>
          <div className="lua" />
          <span>constela</span>
          <small>QUEST</small>
        </div>

        {passo === "codigo" && (
          <div className="painel entrada-painel" style={{ gap: 14 }}>
            <h1>🚀 Vamos entrar!</h1>
            <p className="dica">Digite o código do seu cartão de astronauta</p>
            <input
              ref={campoCodigo}
              className="campo-codigo"
              placeholder="SOL-1234"
              value={codigo}
              maxLength={12}
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              onChange={(evento) => setCodigo(evento.target.value.toUpperCase())}
              onKeyDown={(evento) => evento.key === "Enter" && confirmarCodigo()}
              aria-label="Código do cartão"
            />
            {erro && <div className="entrada-erro" role="alert">{erro}</div>}
            <button className="botao3d sol" onClick={confirmarCodigo}
                    disabled={ocupado || !codigo.trim()}>
              Continuar
            </button>
          </div>
        )}

        {passo === "quem" && quem && (
          <div className="painel entrada-painel" style={{ gap: 14 }}>
            <div className="quem-cartao">
              <Cosmo altura="140px" vivo={false} cor={quem.avatar.cor} />
              <span className="nome">É você, {quem.primeiro_nome}?</span>
              <span className="apelido">✨ {quem.apelido}</span>
            </div>
            <div className="quem-botoes">
              <button className="botao3d fantasma" onClick={voltarAoInicio}>
                Não sou eu
              </button>
              <button className="botao3d" autoFocus
                      onClick={() => { tocar("clique"); setPasso("pin"); }}>
                Sou eu!
              </button>
            </div>
          </div>
        )}

        {passo === "pin" && (
          <div className="painel entrada-painel" style={{ gap: 14 }}>
            <h1>🔒 Suas figuras secretas</h1>
            <p className="dica">Toque nas 4 figuras, na ordem do seu cartão</p>
            <div className="pin-vagas" aria-label="Figuras escolhidas">
              {[0, 1, 2, 3].map((posicao) => {
                const slug = pin[posicao];
                const figura = figuras.find((f) => f.slug === slug);
                return (
                  <div key={posicao}
                       className={`pin-vaga${slug ? " cheia" : ""}`}>
                    {figura?.emoji ?? ""}
                  </div>
                );
              })}
            </div>
            {erro && <div className="entrada-erro" role="alert">{erro}</div>}
            <div className="pin-grade">
              {figuras.map((figura) => (
                <button
                  key={figura.slug}
                  className="pin-figura"
                  disabled={ocupado || pin.includes(figura.slug)}
                  onClick={() => tocarFigura(figura.slug)}
                  aria-label={figura.nome}
                >
                  <span className="desenho" aria-hidden>{figura.emoji}</span>
                  {figura.nome}
                </button>
              ))}
            </div>
            <button className="botao3d fantasma"
                    onClick={() => { setPin([]); setErro(""); }}
                    disabled={ocupado || pin.length === 0}>
              🧽 Apagar e recomeçar
            </button>
          </div>
        )}

        {passo !== "codigo" && (
          <button className="botao-voltar" onClick={voltarAoInicio}>
            ← Voltar ao começo
          </button>
        )}
      </div>

      <div />
    </div>
  );
}
