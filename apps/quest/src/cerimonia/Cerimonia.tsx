/**
 * Cerimônia da primeira vez — o momento de POSSE do astronauta:
 *
 *   1. "Como você quer ser chamado?" — a criança escreve (ou mantém o
 *      nome sugerido do cadastro); o Quest passa a chamá-la assim
 *   2. "Escolha a cor do seu traje!" — o Cosmo muda de cor na hora
 *   3. Festa: "Tudo pronto, {nome}!" e o lobby abre
 *
 * Dispara enquanto o perfil não tem nome_exibicao (funciona em qualquer
 * aparelho, mesmo que o primeiro login tenha sido em outro).
 */
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@constela/core";
import { escolherNome, trocarCorDoTraje } from "@constela/quest-core";

import { narrar, tocar } from "../audio/audio";
import { Cosmo } from "../cosmo/Cosmo";
import { useSessao } from "../estado/sessao";
import { CORES_TRAJE } from "../lobby/cores";
import "./cerimonia.css";

type Passo = "nome" | "cor" | "pronto";

interface CerimoniaProps {
  /** Fecha a cerimônia (o App segura a tela aberta até aqui — salvar o
   * nome no meio do caminho não pode pular a escolha da cor). */
  aoConcluir(): void;
}

export function Cerimonia({ aoConcluir }: CerimoniaProps) {
  const { perfil, atualizarPerfil } = useSessao();
  const [passo, setPasso] = useState<Passo>("nome");
  const [nome, setNome] = useState(perfil?.nome ?? "");
  const [corEscolhida, setCorEscolhida] = useState(
    (perfil?.avatar.cor as string) ?? "#FF4D9D",
  );
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const campoNome = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (passo === "nome") {
      campoNome.current?.focus();
      narrar("Oba, você chegou! Como você quer ser chamado aqui no Quest?");
    }
    if (passo === "cor") {
      narrar("Agora escolha a cor do seu traje de astronauta! Toque nas cores para experimentar.");
    }
  }, [passo]);

  const confirmarNome = async () => {
    if (ocupado || !nome.trim()) return;
    setOcupado(true);
    setErro("");
    try {
      atualizarPerfil(await escolherNome(nome));
      tocar("sucesso");
      setPasso("cor");
    } catch (excecao) {
      const mensagem = excecao instanceof ApiError || excecao instanceof Error
        ? excecao.message : "Não consegui guardar. Tente de novo!";
      setErro(mensagem);
      tocar("erro");
      narrar(mensagem);
    } finally {
      setOcupado(false);
    }
  };

  const experimentarCor = (cor: string) => {
    setCorEscolhida(cor);
    tocar("clique");
  };

  const confirmarCor = async () => {
    if (ocupado) return;
    setOcupado(true);
    try {
      atualizarPerfil(await trocarCorDoTraje(corEscolhida));
    } catch {
      /* cor padrão já vale — não trava a festa por isso */
    } finally {
      setOcupado(false);
    }
    tocar("fanfarra");
    narrar(`Tudo pronto, ${nome.trim() || "astronauta"}! Sua aventura vai começar!`);
    setPasso("pronto");
    window.setTimeout(() => aoConcluir(), 2600);
  };

  return (
    <div className="cerimonia">
      <div className="cerimonia-palco">
        <Cosmo
          altura={passo === "nome" ? "34vh" : "44vh"}
          cor={corEscolhida}
          vivo={passo !== "pronto"}
        />
      </div>

      {passo === "nome" && (
        <div className="painel cerimonia-painel">
          <h1>🌟 Como você quer ser chamado?</h1>
          <p className="dica">Pode ser seu nome ou seu apelido preferido</p>
          <input
            ref={campoNome}
            className="campo-nome"
            value={nome}
            maxLength={20}
            autoComplete="off"
            spellCheck={false}
            onChange={(evento) => setNome(
              evento.target.value.replace(/[^\p{L} ]/gu, ""),
            )}
            onKeyDown={(evento) => evento.key === "Enter" && confirmarNome()}
            aria-label="Como você quer ser chamado"
          />
          {erro && <div className="entrada-erro" role="alert">{erro}</div>}
          <button className="botao3d verde" onClick={confirmarNome}
                  disabled={ocupado || nome.trim().length < 2}>
            ✅ É assim que eu quero!
          </button>
        </div>
      )}

      {passo === "cor" && (
        <div className="painel cerimonia-painel">
          <h1>🎨 Escolha a cor do seu traje!</h1>
          <p className="dica">Toque nas cores para experimentar</p>
          <div className="cerimonia-cores">
            {CORES_TRAJE.map((cor) => (
              <button
                key={cor}
                className={`amostra grande${cor === corEscolhida ? " escolhida" : ""}`}
                style={{ background: cor }}
                onClick={() => experimentarCor(cor)}
                aria-label={cor === corEscolhida ? "Cor escolhida" : "Experimentar cor"}
              >
                {cor === corEscolhida ? "✓" : ""}
              </button>
            ))}
          </div>
          <button className="botao3d sol" onClick={confirmarCor} disabled={ocupado}>
            🚀 Pronto!
          </button>
        </div>
      )}

      {passo === "pronto" && (
        <div className="painel cerimonia-painel festa">
          <h1>🎉 Tudo pronto, {nome.trim()}!</h1>
          <p className="dica">Sua aventura vai começar…</p>
        </div>
      )}
    </div>
  );
}
