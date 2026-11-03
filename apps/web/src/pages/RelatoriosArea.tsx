/**
 * Relatórios — uma área só, com duas abas:
 *
 *   OFICIAIS    → exportações com a identidade visual da escola (ranking,
 *                 lista de alunos, catálogo, certificados).
 *   POR PERÍODO → o que aconteceu numa janela de datas.
 *
 * POR QUE ISTO EXISTE. "Relatório por Período" é um TIPO de relatório, e estava
 * na barra lateral como se fosse um módulo à parte, ao lado de "Relatórios".
 * Quem procurava um relatório tinha de adivinhar em qual dos dois entrar. Aqui
 * a barra lateral volta a ter uma entrada só e a escolha acontece dentro da
 * página, onde o usuário já está olhando para relatórios.
 *
 * NENHUMA LÓGICA MUDA. Esta tela não busca dado, não filtra, não calcula e não
 * gera PDF: ela só escolhe qual das DUAS páginas existentes renderizar. Os
 * filtros, as métricas, as ressalvas, o botão "Gerar PDF" e as permissões
 * continuam onde sempre estiveram, dentro de cada uma delas.
 *
 * A URL CONTINUA SENDO A MESMA. `/relatorios` abre em Oficiais e
 * `/relatorios/periodo` abre em Por período — a rota que já estava publicada,
 * preservada inteira para não quebrar link salvo, histórico nem atalho. A aba
 * é derivada do caminho a cada render, então voltar/avançar no navegador troca
 * a aba sem remontar nada.
 *
 * SEM TÍTULO PRÓPRIO, de propósito: cada página filha já traz o seu
 * `PageHeader` (e o de "Por período" carrega o botão "Gerar PDF"). Pôr mais um
 * por cima daria dois títulos na mesma tela — o mesmo motivo pelo qual
 * `Rankings.tsx` não desenha cabeçalho na categoria "Escolas".
 *
 * Acessibilidade: o mesmo padrão de `Rankings.tsx` — `role="tablist"`, abas com
 * `aria-controls` apontando para o painel, e o painel (`role="tabpanel"`)
 * rotulado pela aba ativa.
 */
import { CalendarRange, FileText } from "lucide-react";
import { useId } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { AbasLigadas } from "../components/AbasLigadas";
import RelatorioPeriodo from "./RelatorioPeriodo";
import Relatorios from "./Relatorios";

const ABAS = [
  { chave: "oficiais", rotulo: "Relatórios oficiais", caminho: "/relatorios", icone: FileText },
  { chave: "periodo", rotulo: "Por período", caminho: "/relatorios/periodo", icone: CalendarRange },
] as const;
type Aba = (typeof ABAS)[number]["chave"];

export default function RelatoriosArea() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const idBase = useId();
  const idAba = (chave: string) => `${idBase}-aba-${chave}`;
  const idPainel = `${idBase}-painel`;

  // O CAMINHO é a fonte da verdade: a aba é derivada dele a cada render, para
  // que link direto, voltar/avançar e atalho funcionem sem estado paralelo.
  const aba: Aba = pathname.startsWith("/relatorios/periodo") ? "periodo" : "oficiais";

  return (
    <div>
      {/* Controle segmentado da identidade v2 (pílula violeta na ativa), com setas,
          Home e End. `replace` na troca: voltar devolve o usuário à tela de onde ele
          veio, não à outra aba. */}
      <AbasLigadas
        itens={ABAS.map((a) => ({ valor: a.chave, rotulo: a.rotulo, icone: a.icone }))}
        valor={aba}
        aoMudar={(chave) => {
          const destino = ABAS.find((a) => a.chave === chave);
          if (destino) navigate(destino.caminho, { replace: true });
        }}
        rotulo="Tipo de relatório"
        idDaAba={idAba}
        idPainel={idPainel}
        className="mb-6"
      />

      <div role="tabpanel" id={idPainel} aria-labelledby={idAba(aba)}>
        {aba === "periodo" ? <RelatorioPeriodo /> : <Relatorios />}
      </div>
    </div>
  );
}
