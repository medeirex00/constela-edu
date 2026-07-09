/**
 * Entrada do astronauta — sem senha (o código é a credencial) e SEM salvar a
 * conta no aparelho (decisão de produto): cada entrada começa pelo código.
 *
 *   1. código do cartão (só letras e números, ex.: SOL1234)
 *   2. "É você?" — botão verde gigante confirma; o cinza volta
 *
 * Cada passo é NARRADO em pt-BR e tem o botão "Ouvir de novo".
 */
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@constela/core";
import { entrar, quemE } from "@constela/quest-core";
import type { Quem, SessaoQuest } from "@constela/quest-core";

import { narrar, tocar } from "../audio/audio";
import { Cosmo } from "../cosmo/Cosmo";
import "./entrada.css";

type Passo = "codigo" | "quem";

const NARRACOES: Record<Passo, string> = {
  codigo: "Digite o código do seu cartão, aquele com as letras e os números grandes. Depois toque em continuar.",
  quem: "Se for você, toque no botão verde!",
};

interface EntradaProps {
  aoEntrar(sessao: SessaoQuest): void;
}

export function Entrada({ aoEntrar }: EntradaProps) {
  const [passo, setPasso] = useState<Passo>("codigo");
  const [codigo, setCodigo] = useState("");
  const [quem, setQuem] = useState<Quem | null>(null);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const campoCodigo = useRef<HTMLInputElement>(null);
  const telaLarga = useRef(window.matchMedia("(min-width: 761px)").matches).current;

  useEffect(() => {
    if (passo === "codigo") campoCodigo.current?.focus();
    narrar(passo === "quem" && quem
      ? `Encontrei! É você, ${quem.nome}? ${NARRACOES.quem}`
      : NARRACOES[passo]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [passo]);

  const falhar = (excecao: unknown, padrao: string) => {
    const mensagem = excecao instanceof ApiError || excecao instanceof Error
      ? excecao.message : padrao;
    setErro(mensagem);
    tocar("erro");
    narrar(mensagem);
  };

  const confirmarCodigo = async () => {
    const alvo = codigo.trim();
    if (!alvo || ocupado) return;
    setOcupado(true);
    setErro("");
    try {
      const resposta = await quemE(alvo);
      setQuem(resposta);
      setPasso("quem");
      tocar("clique");
    } catch (excecao) {
      falhar(excecao, "Não consegui procurar agora. Tente de novo!");
    } finally {
      setOcupado(false);
    }
  };

  const entrarAgora = async () => {
    if (ocupado) return;
    setOcupado(true);
    setErro("");
    try {
      const sessao = await entrar(codigo);
      tocar("fanfarra");
      aoEntrar(sessao);
    } catch (excecao) {
      falhar(excecao, "Não consegui entrar agora. Tente de novo!");
    } finally {
      setOcupado(false);
    }
  };

  const voltar = () => { setPasso("codigo"); setQuem(null); setErro(""); };

  return (
    <div className="entrada">
      {telaLarga && (
        <div className="cosmo-canto"><Cosmo altura="52vh" fisica /></div>
      )}

      <div className="entrada-painel">
        <div className="entrada-marca" aria-hidden>
          <div className="lua" />
          <span>constela</span>
          <small>QUEST</small>
        </div>

        {passo === "codigo" && (
          <div className="painel entrada-passo">
            <h1>🚀 Vamos entrar!</h1>
            <p className="dica">Digite o código do seu cartão de astronauta</p>
            <input
              ref={campoCodigo}
              className="campo-codigo"
              placeholder="SOL1234"
              value={codigo}
              maxLength={12}
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => setCodigo(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
              onKeyDown={(e) => e.key === "Enter" && confirmarCodigo()}
              aria-label="Código do cartão (letras e números)"
            />
            {erro && <div className="entrada-erro" role="alert">{erro}</div>}
            <button className="botao3d sol" onClick={confirmarCodigo}
                    disabled={ocupado || !codigo.trim()}>
              Continuar
            </button>
          </div>
        )}

        {passo === "quem" && quem && (
          <div className="painel entrada-passo">
            <div className="quem-cartao">
              <Cosmo altura="150px" vivo={false} cor={quem.avatar.cor as string}
                     rosto={quem.avatar.rosto as string}
                     chapeu={quem.avatar.chapeu as string} />
              <span className="nome">É você, {quem.nome}?</span>
              <span className="apelido">✨ {quem.apelido}</span>
            </div>
            {erro && <div className="entrada-erro" role="alert">{erro}</div>}
            <div className="quem-botoes">
              <button className="botao3d verde sou-eu" autoFocus disabled={ocupado}
                      onClick={() => { tocar("clique"); void entrarAgora(); }}>
                ✅ Sou eu!
              </button>
              <button className="botao3d fantasma nao-sou-eu"
                      onClick={() => { tocar("clique"); voltar(); }}>
                ↩ Não sou eu
              </button>
            </div>
          </div>
        )}

        <div className="entrada-rodape">
          <button className="botao-ouvir"
                  onClick={() => narrar(passo === "quem" && quem
                    ? `É você, ${quem.nome}? ${NARRACOES.quem}` : NARRACOES[passo])}
                  aria-label="Ouvir a instrução de novo">
            🔊 Ouvir de novo
          </button>
          {passo === "quem" && (
            <button className="botao-ouvir" onClick={voltar}>← Voltar ao começo</button>
          )}
        </div>
      </div>

      <div />
    </div>
  );
}
