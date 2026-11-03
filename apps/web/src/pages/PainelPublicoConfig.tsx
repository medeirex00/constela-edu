/** Configuração do Painel Público (PRD §104–§128) — admin/coordenador.
 *
 * Identidade v2: chaves liga/desliga (visual de interruptor sobre um checkbox de
 * verdade — os testes e o leitor de tela continuam vendo "checkbox"), slides como
 * cartões selecionáveis, o link do telão no cartão escuro de destaque e a
 * privacidade num cartão próprio, SEMPRE visível. O retorno de cada ação aparece
 * no cartão que a disparou (antes ia para o rodapé da página).
 *
 * Nada muda na regra de privacidade: `confirmar_exposicao=true` só sai do clique
 * na proteção do nome, depois do aviso aceito; salvar segue no blur (agora só
 * quando o número mudou — antes cada foco perdido gravava e auditava de novo).
 */
import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  Image,
  Lock,
  Monitor,
  MonitorPlay,
  QrCode,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Trophy,
  TrendingUp,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  Botao,
  Campo,
  Card,
  Carregando,
  Confirmacao,
  Erro,
  IconePastel,
  Mensagem,
  PageHeader,
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import { api, apiDownload } from "../lib/api";
import { comOrigemLocal, linkSoNestaMaquina } from "../lib/linkPublico";

interface ConfigPainel {
  ativo: boolean;
  slides: string[];
  intervalo_s: number;
  max_posicoes: number;
  anonimizar: boolean;
  url: string | null;
}

type Origem = "painel" | "slides" | "privacidade";

// O mesmo desenho dos links de ação das telas da rede (analise/RelatoriosRede.tsx).
const CLASSE_LINK = "inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-3.5 py-2 text-sm "
  + "font-semibold text-zinc-800 transition-colors hover:border-indigo-300 hover:text-indigo-700 dark:border-zinc-700 "
  + "dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-indigo-500/50 dark:hover:text-indigo-300";

const SLIDES: { chave: string; rotulo: string; descricao: string; icone: LucideIcon }[] = [
  { chave: "ranking", rotulo: "Ranking Geral", descricao: "Os primeiros colocados da escola", icone: Trophy },
  { chave: "evolucao", rotulo: "Ranking de Evolução", descricao: "Quem mais cresceu no período", icone: TrendingUp },
  { chave: "destaques", rotulo: "Aluno do Dia/Semana/Mês", descricao: "Os destaques recentes", icone: Sparkles },
  { chave: "mural", rotulo: "Mural da escola", descricao: "Recados e conquistas", icone: Image },
];

const DESCRICAO = "Um endereço sem login para o telão da escola e para as famílias. Só dados pedagógicos são exibidos.";

/** Interruptor visual sobre um <input type="checkbox"> real (rótulo = o texto). */
function ChaveCheckbox({ checked, disabled, onChange, children }: {
  checked: boolean;
  disabled?: boolean;
  onChange: (marcado: boolean) => void;
  children: ReactNode;
}) {
  return (
    <label className={`flex items-center justify-between gap-4 ${disabled ? "cursor-not-allowed" : "cursor-pointer"}`}>
      <span className="min-w-0 text-sm font-semibold text-zinc-900 dark:text-zinc-100">{children}</span>
      <span className="relative inline-flex shrink-0">
        <input
          type="checkbox"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(evento) => onChange(evento.target.checked)}
        />
        <span
          aria-hidden
          className="h-7 w-12 rounded-full bg-zinc-300 transition-colors peer-checked:bg-indigo-600 peer-checked:shadow-pilula peer-focus-visible:ring-2 peer-focus-visible:ring-indigo-500 peer-focus-visible:ring-offset-2 peer-disabled:opacity-60 dark:bg-zinc-700 dark:peer-focus-visible:ring-offset-zinc-900"
        />
        <span
          aria-hidden
          className="pointer-events-none absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-5"
        />
      </span>
    </label>
  );
}

/** O link do servidor é do próprio computador (localhost): só abre aqui. Fica junto do
 *  endereço, no cartão escuro. */
function AvisoLinkLocal() {
  return (
    <p className="mt-2 flex items-start gap-2 text-xs leading-relaxed text-ouro-200" data-testid="aviso-link-local">
      <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0 text-ouro-300" />
      <span>
        Este link usa localhost: só abre no computador onde o Constela está instalado. Para o telão, o celular
        ou o QR code lido em outro aparelho, o servidor precisa ter configurado o endereço dele na rede
        (variável PUBLIC_BASE_URL).
      </span>
    </p>
  );
}

export default function PainelPublicoConfig() {
  const { escolaId, usuario } = useApp();
  // A Secretaria opera a REDE (o backend recusa este painel a ela): não busca nada aqui e é
  // levada à vitrine da rede, no Panorama da Rede (a página inicial dela, DESENHO3 §5).
  const { secretaria } = usePerfil();
  const podeEditar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  // Estado local editável: semeado pela busca e depois alterado nos campos e mutações.
  const [config, setConfig] = useState<ConfigPainel | null>(null);
  // O que o SERVIDOR tem agora: o blur só grava se o número mudou em relação a isto.
  const salvoRef = useRef<ConfigPainel | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string; origem: Origem } | null>(null);
  const [ocupado, setOcupado] = useState(false);
  // Diálogos de confirmação: trocar o endereço do telão e desligar a proteção do nome.
  const [confirmandoToken, setConfirmandoToken] = useState(false);
  const [confirmandoExposicao, setConfirmandoExposicao] = useState(false);
  // O endereço do telão é o que o SERVIDOR devolve (ele decide a base: lib/linkPublico). A
  // tela só informa a própria origem em loopback e mostra, copia e abre o link como veio.
  const endereco = config?.url ?? null;

  // Leitura única da configuração; o hook cuida de cancelamento, timeout e retry.
  const { erro, carregando, recarregar } = useApi<ConfigPainel>(
    usuario && escolaId && !secretaria ? comOrigemLocal(`/escolas/${escolaId}/painel-publico`) : null,
    { aoSucesso: (c) => { salvoRef.current = c; setConfig(c); } },
  );

  /**
   * `confirmarExposicao` só é `true` quando ESTE salvamento vem do clique no
   * checkbox de privacidade, depois do aviso aceito. O servidor exige a flag
   * para passar de protegido para nome completo; mandar `true` em todo
   * salvamento (slides, intervalo, ligar o painel) anulava essa barreira: uma
   * aba aberta antes de outra pessoa ligar a proteção, ao salvar só o
   * intervalo, reexpunha os nomes sem aviso nenhum. Agora essa aba recebe o
   * 400 do servidor. Editar uma config que JÁ está com nome completo continua
   * passando: o servidor olha o estado anterior.
   */
  async function salvar(novaConfig: ConfigPainel, confirmarExposicao = false, origem: Origem = "painel") {
    if (!escolaId) return;
    setOcupado(true);
    setMensagem(null);
    try {
      const salvo = await api<ConfigPainel>(comOrigemLocal(`/escolas/${escolaId}/painel-publico`), {
        method: "PUT",
        body: JSON.stringify({
          ativo: novaConfig.ativo,
          slides: novaConfig.slides,
          intervalo_s: novaConfig.intervalo_s,
          max_posicoes: novaConfig.max_posicoes,
          anonimizar: novaConfig.anonimizar,
          confirmar_exposicao: confirmarExposicao,
        }),
      });
      // Ativar o painel gera um endereço NOVO (o anterior deixa de funcionar).
      const ativou = novaConfig.ativo && !config?.ativo;
      salvoRef.current = salvo;
      setConfig(salvo);
      setMensagem({
        tipo: "ok",
        origem,
        texto: ativou
          ? "Painel ativado com um endereço NOVO — o QR code e o link anteriores deixaram de funcionar. Baixe o QR code novo."
          : "Configuração salva.",
      });
    } catch (excecao) {
      setMensagem({ tipo: "erro", origem, texto: excecao instanceof Error ? excecao.message : "Falha ao salvar." });
    } finally {
      setOcupado(false);
    }
  }

  /** Blur dos números: grava só se mudou desde o último salvo (o servidor valida a faixa). */
  function salvarNumerosSeMudou(atual: ConfigPainel) {
    const salvo = salvoRef.current;
    if (salvo && salvo.intervalo_s === atual.intervalo_s && salvo.max_posicoes === atual.max_posicoes) return;
    void salvar(atual, false, "slides");
  }

  async function trocarToken() {
    if (!escolaId) return;
    setOcupado(true);
    try {
      const novo = await api<ConfigPainel>(comOrigemLocal(`/escolas/${escolaId}/painel-publico/novo-token`), { method: "POST" });
      salvoRef.current = novo;
      setConfig(novo);
      setMensagem({ tipo: "ok", origem: "painel", texto: "Novo endereço gerado. Atualize o QR code impresso." });
    } catch (excecao) {
      setMensagem({ tipo: "erro", origem: "painel", texto: excecao instanceof Error ? excecao.message : "Falha ao trocar o endereço." });
    } finally {
      setOcupado(false);
      setConfirmandoToken(false);
    }
  }

  /** Aviso aceito no diálogo: desliga a proteção e confirma a exposição. */
  async function exporNomeCompleto() {
    if (!config) return;
    // Único lugar que confirma a exposição: o aviso do diálogo foi aceito.
    await salvar({ ...config, anonimizar: false }, true, "privacidade");
    setConfirmandoExposicao(false);
  }

  async function copiar(url: string) {
    // Antes dizia "copiado" mesmo quando a área de transferência recusava.
    try {
      await navigator.clipboard.writeText(url);
      setMensagem({ tipo: "ok", origem: "painel", texto: "Endereço copiado." });
    } catch {
      setMensagem({ tipo: "erro", origem: "painel", texto: "Não foi possível copiar: selecione o endereço e copie à mão." });
    }
  }

  async function baixarQr() {
    try {
      // O QR leva o MESMO link que a tela mostra: o servidor decide a base (a tela só informa
      // a própria origem em loopback).
      await apiDownload(comOrigemLocal(`/escolas/${escolaId}/painel-publico/qr`));
    } catch (excecao) {
      setMensagem({ tipo: "erro", origem: "painel", texto: excecao instanceof Error ? excecao.message : "Não foi possível baixar o QR code." });
    }
  }

  const retorno = (origem: Origem) =>
    mensagem && mensagem.origem === origem ? <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem> : null;

  // Sem escola não há o que buscar: antes a tela ficava em "Carregando..." para sempre (a
  // espera pela sessão, com `usuario` ainda nulo, continua no "Carregando..." abaixo).
  if (usuario && (secretaria || !escolaId)) {
    return (
      <div>
        <PageHeader titulo="Painel Público" descricao={DESCRICAO} />
        <Card>
          {secretaria ? (
            <Vazio
              icone={MonitorPlay}
              titulo="A vitrine da rede fica no Panorama da Rede"
              descricao="O painel público de cada escola é ligado pela coordenação ou pela administração da escola. A vitrine pública da rede é ligada e aberta no Panorama da Rede, em “Reconhecimento público”."
              acao={
                <Link to="/" className={CLASSE_LINK}>
                  <MonitorPlay size={15} aria-hidden /> Ir para a vitrine da rede
                </Link>
              }
            />
          ) : (
            // Fora da Secretaria a escola só falta com a lista VAZIA — e aí nem o seletor do menu
            // lateral aparece: nada de mandar escolher num controle que não está na tela.
            <Vazio
              icone={MonitorPlay}
              titulo="Nenhuma escola disponível"
              descricao="Esta conta ainda não tem escola vinculada. Peça à administração o cadastro ou o vínculo da escola para configurar o painel público."
            />
          )}
        </Card>
      </div>
    );
  }

  if (!config) {
    // Em vez de engolir o erro, mostramos o estado de erro com "Tentar de novo".
    if (!carregando && erro) {
      return (
        <div>
          <PageHeader titulo="Painel Público" descricao={DESCRICAO} />
          <Card><Erro titulo="Não foi possível carregar o painel" descricao={erro.message} aoTentar={recarregar} /></Card>
        </div>
      );
    }
    return (
      <div>
        <PageHeader titulo="Painel Público" descricao={DESCRICAO} />
        <Carregando />
      </div>
    );
  }

  return (
    <div>
      <PageHeader titulo="Painel Público" descricao={DESCRICAO} />

      {/* Duas colunas só com o painel LIGADO (endereço + carrossel à esquerda, a
          privacidade ao lado) e só a partir de 1280 px: em 1024 a coluna da
          privacidade ficava com ~270 px (título partido, aviso em 9 linhas). Com o
          painel desligado os dois cartões são curtos: um embaixo do outro, na mesma
          largura, sem o vão sob o cartão menor. */}
      <div className={`grid items-start gap-6 ${
        config.ativo ? "xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]" : "max-w-3xl"}`}>
        <div className="space-y-6">
          <Card className="space-y-5 p-5 sm:p-6">
            <div className="flex items-start gap-3">
              <IconePastel icone={Monitor} tom="violeta" />
              <div className="min-w-0 flex-1">
                <ChaveCheckbox
                  checked={config.ativo}
                  disabled={!podeEditar || ocupado}
                  onChange={(marcado) => salvar({ ...config, ativo: marcado })}
                >
                  Painel público ativo
                </ChaveCheckbox>
                <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                  {config.ativo
                    ? "No ar: qualquer pessoa com o link ou o QR code vê o telão."
                    : "Desligado: o link não abre nada. Ligar gera um endereço novo."}
                </p>
              </div>
            </div>

            {config.ativo && endereco && (
              // O link do telão no cartão escuro de destaque.
              <div className="relative overflow-hidden rounded-2xl bg-marinho-900 p-5 text-white">
                <span aria-hidden className="pointer-events-none absolute -right-10 -top-10 h-36 w-36 rounded-full bg-indigo-600/30 blur-2xl" />
                <div className="relative">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-marinho-200">Endereço do telão</p>
                  <code className="mt-2 block truncate rounded-xl bg-white/10 px-3 py-2 text-xs text-white">{endereco}</code>
                  {linkSoNestaMaquina(endereco) && <AvisoLinkLocal />}
                  <div className="mt-4 flex flex-wrap gap-2.5">
                    <Botao variante="ambar" onClick={() => copiar(endereco)}>
                      <Copy size={14} aria-hidden /> Copiar
                    </Botao>
                    <a
                      href={endereco}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 rounded-xl border border-white/25 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-white/10"
                    >
                      <ExternalLink size={14} aria-hidden /> Abrir
                    </a>
                    {podeEditar && (
                      <>
                        <button type="button" disabled={ocupado} onClick={baixarQr}
                                className="inline-flex items-center gap-2 rounded-xl border border-white/25 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-white/10 disabled:opacity-60">
                          <QrCode size={14} aria-hidden /> Baixar QR code
                        </button>
                        <button type="button" disabled={ocupado} onClick={() => setConfirmandoToken(true)}
                                className="inline-flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-semibold text-marinho-200 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-60">
                          <RefreshCcw size={14} aria-hidden /> Gerar novo endereço
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}
            {retorno("painel")}
          </Card>

          {config.ativo && (
            <Card className="p-5 sm:p-6">
              <h2 className="mb-1 flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
                <IconePastel icone={Sparkles} tom="ambar" tamanho="sm" />
                Carrossel de slides
              </h2>
              <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">
                O que o telão mostra, em rodízio. Pelo menos um slide fica ligado.
              </p>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {SLIDES.map((slide) => {
                  const marcado = config.slides.includes(slide.chave);
                  const Icone = slide.icone;
                  return (
                    <label key={slide.chave} className={`relative block ${!podeEditar || ocupado ? "cursor-not-allowed" : "cursor-pointer"}`}>
                      <input
                        type="checkbox"
                        className="peer sr-only"
                        checked={marcado}
                        disabled={!podeEditar || ocupado}
                        onChange={(evento) => {
                          const slides = evento.target.checked
                            ? [...config.slides, slide.chave]
                            : config.slides.filter((chave) => chave !== slide.chave);
                          if (slides.length === 0) return;
                          salvar({ ...config, slides }, false, "slides");
                        }}
                      />
                      <span className="flex items-center gap-3 rounded-2xl border border-zinc-200 bg-white px-3.5 py-3 transition-colors hover:border-indigo-200 peer-checked:border-indigo-500 peer-checked:bg-indigo-50/70 peer-focus-visible:ring-2 peer-focus-visible:ring-indigo-500 peer-disabled:opacity-70 dark:border-zinc-700 dark:bg-zinc-900 dark:peer-checked:bg-indigo-500/10">
                        <span aria-hidden className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${
                          marcado ? "bg-indigo-600 text-white" : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-300"}`}>
                          <Icone size={17} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-semibold text-zinc-900 dark:text-zinc-100">{slide.rotulo}</span>
                          <span className="block text-xs text-zinc-500 dark:text-zinc-400">{slide.descricao}</span>
                        </span>
                        {marcado && <Check size={16} aria-hidden className="shrink-0 text-indigo-600 dark:text-indigo-300" />}
                      </span>
                    </label>
                  );
                })}
              </div>
              <div className="mt-5 grid grid-cols-2 gap-4">
                <Campo rotulo="Segundos por slide">
                  <input
                    type="number" min={4} max={120} className={estiloInput}
                    value={config.intervalo_s}
                    disabled={!podeEditar}
                    onChange={(evento) => setConfig({ ...config, intervalo_s: Number(evento.target.value) })}
                    onBlur={() => salvarNumerosSeMudou(config)}
                  />
                </Campo>
                <Campo rotulo="Posições no ranking">
                  <input
                    type="number" min={3} max={50} className={estiloInput}
                    value={config.max_posicoes}
                    disabled={!podeEditar}
                    onChange={(evento) => setConfig({ ...config, max_posicoes: Number(evento.target.value) })}
                    onBlur={() => salvarNumerosSeMudou(config)}
                  />
                </Campo>
              </div>
              <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">De 4 a 120 segundos; de 3 a 50 posições. Salva ao sair do campo.</p>
              <div className="mt-4">{retorno("slides")}</div>
            </Card>
          )}
        </div>

        {/* Visível SEMPRE (mesmo com o painel desativado): o gestor vê a
            proteção padrão antes de ligar o telão, não depois. */}
        <Card className="space-y-4 p-5 sm:p-6">
          <h2 className="flex items-center gap-3 text-base font-semibold tracking-tight text-zinc-900 dark:text-white">
            <IconePastel icone={ShieldCheck} tom="verde" tamanho="sm" />
            Privacidade dos alunos
          </h2>
          <div className="flex items-start gap-3 rounded-2xl border border-ouro-200 bg-ouro-50 p-4 text-xs leading-relaxed text-zinc-700 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-zinc-200">
            <Lock size={16} aria-hidden className="mt-0.5 shrink-0 text-ouro-700 dark:text-ouro-300" />
            <p>
              O telão é um endereço público, sem senha. Por proteção, o nome do
              aluno aparece de forma reduzida — só o primeiro nome e a inicial do
              sobrenome (ex.: <strong>Ana B.</strong>). Recomendado para redes
              públicas com dados de crianças.
            </p>
          </div>
          <ChaveCheckbox
            checked={config.anonimizar}
            disabled={!podeEditar || ocupado}
            onChange={(proteger) => {
              // Desligar a proteção EXPÕE nome completo em link público:
              // exige confirmação consciente (o QR pode já estar impresso).
              if (!proteger) {
                setConfirmandoExposicao(true);
                return;
              }
              // Religar a proteção não expõe nada: grava sem confirmar.
              salvar({ ...config, anonimizar: true }, false, "privacidade");
            }}
          >
            Proteger o nome dos alunos no telão (recomendado)
          </ChaveCheckbox>
          <p className={`text-xs font-semibold ${config.anonimizar ? "text-emerald-700 dark:text-emerald-300" : "text-rose-700 dark:text-rose-300"}`}>
            {config.anonimizar ? "Nomes reduzidos no telão." : "Atenção: o telão mostra o nome completo."}
          </p>
          {retorno("privacidade")}
        </Card>
      </div>

      <Confirmacao
        titulo="Gerar um novo endereço?"
        aberto={confirmandoToken}
        aoFechar={() => setConfirmandoToken(false)}
        aoConfirmar={() => void trocarToken()}
        rotuloConfirmar={ocupado ? "Gerando..." : "Gerar novo endereço"}
        variante="perigo"
        ocupado={ocupado}
      >
        <p>O link e o QR code atuais deixarão de funcionar.</p>
      </Confirmacao>

      <Confirmacao
        titulo="Exibir o nome completo no telão?"
        aberto={confirmandoExposicao}
        aoFechar={() => setConfirmandoExposicao(false)}
        aoConfirmar={() => void exporNomeCompleto()}
        rotuloConfirmar={ocupado ? "Salvando..." : "Exibir o nome completo"}
        variante="perigo"
        ocupado={ocupado}
      >
        <p>
          <strong className="text-zinc-800 dark:text-zinc-100">Atenção:</strong> desligar a proteção
          vai EXIBIR O NOME COMPLETO das crianças no telão público (endereço sem senha).
        </p>
        <p>Só faça isso com o consentimento dos responsáveis.</p>
      </Confirmacao>
    </div>
  );
}
