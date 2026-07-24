/** Configuração do Painel Público (PRD §104–§128) — admin/coordenador. */
import { Copy, ExternalLink, QrCode, RefreshCcw } from "lucide-react";
import { useState } from "react";

import { Botao, Campo, Card, Carregando, Mensagem, PageHeader, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api, apiDownload } from "../lib/api";

interface ConfigPainel {
  ativo: boolean;
  slides: string[];
  intervalo_s: number;
  max_posicoes: number;
  anonimizar: boolean;
  url: string | null;
}

const SLIDES = [
  { chave: "ranking", rotulo: "Ranking Geral" },
  { chave: "evolucao", rotulo: "Ranking de Evolução" },
  { chave: "destaques", rotulo: "Aluno do Dia/Semana/Mês" },
  { chave: "mural", rotulo: "Mural da escola" },
];

export default function PainelPublicoConfig() {
  const { escolaId, usuario } = useApp();
  const podeEditar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  // Estado local editável: semeado pela busca e depois alterado nos campos e mutações.
  const [config, setConfig] = useState<ConfigPainel | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  // Leitura única da configuração; o hook cuida de cancelamento, timeout e retry.
  const { erro, carregando } = useApi<ConfigPainel>(
    escolaId ? `/escolas/${escolaId}/painel-publico` : null,
    { aoSucesso: setConfig },
  );

  async function salvar(novaConfig: ConfigPainel) {
    if (!escolaId) return;
    setOcupado(true);
    setMensagem(null);
    try {
      const salvo = await api<ConfigPainel>(`/escolas/${escolaId}/painel-publico`, {
        method: "PUT",
        body: JSON.stringify({
          ativo: novaConfig.ativo,
          slides: novaConfig.slides,
          intervalo_s: novaConfig.intervalo_s,
          max_posicoes: novaConfig.max_posicoes,
          anonimizar: novaConfig.anonimizar,
          // Exigido pelo servidor p/ expor nome completo (o clique já avisou).
          confirmar_exposicao: !novaConfig.anonimizar,
        }),
      });
      // Ativar o painel gera um endereço NOVO (o anterior deixa de funcionar).
      const ativou = novaConfig.ativo && !config?.ativo;
      setConfig(salvo);
      setMensagem({
        tipo: "ok",
        texto: ativou
          ? "Painel ativado com um endereço NOVO — o QR code e o link anteriores deixaram de funcionar. Baixe o QR code novo."
          : "Configuração salva.",
      });
    } catch (excecao) {
      setMensagem({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Falha ao salvar." });
    } finally {
      setOcupado(false);
    }
  }

  async function trocarToken() {
    if (!escolaId) return;
    if (!window.confirm("Gerar um novo endereço? O link e o QR code atuais deixarão de funcionar.")) return;
    setOcupado(true);
    try {
      setConfig(await api<ConfigPainel>(`/escolas/${escolaId}/painel-publico/novo-token`, { method: "POST" }));
      setMensagem({ tipo: "ok", texto: "Novo endereço gerado. Atualize o QR code impresso." });
    } catch (excecao) {
      setMensagem({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Falha ao trocar o endereço." });
    } finally {
      setOcupado(false);
    }
  }

  if (!config) {
    // Em vez de engolir o erro, mostramos um estado de erro discreto.
    if (!carregando && erro) {
      return (
        <div>
          <PageHeader
            titulo="Painel Público"
            descricao="Um endereço sem login para o telão da escola e para as famílias. Só dados pedagógicos são exibidos."
          />
          <Mensagem tipo="erro">{erro.message}</Mensagem>
        </div>
      );
    }
    return <Carregando />;
  }

  return (
    <div>
      <PageHeader
        titulo="Painel Público"
        descricao="Um endereço sem login para o telão da escola e para as famílias. Só dados pedagógicos são exibidos."
      />

      <div className="max-w-2xl space-y-6">
        <Card className="p-5">
          <label className="flex items-center gap-3 text-sm font-medium">
            <input
              type="checkbox"
              className="h-4 w-4 accent-indigo-600"
              checked={config.ativo}
              disabled={!podeEditar || ocupado}
              onChange={(evento) => salvar({ ...config, ativo: evento.target.checked })}
            />
            Painel público ativo
          </label>

          {config.ativo && config.url && (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <code className="flex-1 truncate rounded-lg bg-zinc-100 px-3 py-2 text-xs dark:bg-zinc-800">
                {config.url}
              </code>
              <Botao
                variante="neutro"
                onClick={() => {
                  navigator.clipboard.writeText(config.url ?? "");
                  setMensagem({ tipo: "ok", texto: "Endereço copiado." });
                }}
              >
                <Copy size={14} /> Copiar
              </Botao>
              <a
                href={config.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3.5 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
              >
                <ExternalLink size={14} /> Abrir
              </a>
            </div>
          )}

          {config.ativo && podeEditar && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Botao variante="neutro" disabled={ocupado}
                     onClick={() => apiDownload(`/escolas/${escolaId}/painel-publico/qr`)}>
                <QrCode size={14} /> Baixar QR code
              </Botao>
              <Botao variante="neutro" disabled={ocupado} onClick={trocarToken}>
                <RefreshCcw size={14} /> Gerar novo endereço
              </Botao>
            </div>
          )}
        </Card>

        {config.ativo && (
          <Card className="p-5">
            <h3 className="mb-3 text-sm font-semibold">Carrossel de slides</h3>
            <div className="space-y-2">
              {SLIDES.map((slide) => (
                <label key={slide.chave} className="flex items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-indigo-600"
                    checked={config.slides.includes(slide.chave)}
                    disabled={!podeEditar || ocupado}
                    onChange={(evento) => {
                      const slides = evento.target.checked
                        ? [...config.slides, slide.chave]
                        : config.slides.filter((chave) => chave !== slide.chave);
                      if (slides.length === 0) return;
                      salvar({ ...config, slides });
                    }}
                  />
                  {slide.rotulo}
                </label>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <Campo rotulo="Segundos por slide">
                <input
                  type="number" min={4} max={120} className={estiloInput}
                  value={config.intervalo_s}
                  disabled={!podeEditar}
                  onChange={(evento) => setConfig({ ...config, intervalo_s: Number(evento.target.value) })}
                  onBlur={() => salvar(config)}
                />
              </Campo>
              <Campo rotulo="Posições no ranking">
                <input
                  type="number" min={3} max={50} className={estiloInput}
                  value={config.max_posicoes}
                  disabled={!podeEditar}
                  onChange={(evento) => setConfig({ ...config, max_posicoes: Number(evento.target.value) })}
                  onBlur={() => salvar(config)}
                />
              </Campo>
            </div>
          </Card>
        )}

        {/* Visível SEMPRE (mesmo com o painel desativado): o gestor vê a
            proteção padrão antes de ligar o telão, não depois. */}
        <Card className="p-5">
            <h3 className="mb-1 text-sm font-semibold">Privacidade dos alunos</h3>
            <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
              O telão é um endereço público, sem senha. Por proteção, o nome do
              aluno aparece de forma reduzida — só o primeiro nome e a inicial do
              sobrenome (ex.: <strong>Ana B.</strong>). Recomendado para redes
              públicas com dados de crianças.
            </p>
            <label className="flex items-center gap-3 text-sm font-medium">
              <input
                type="checkbox"
                className="h-4 w-4 accent-indigo-600"
                checked={config.anonimizar}
                disabled={!podeEditar || ocupado}
                onChange={(evento) => {
                  const proteger = evento.target.checked;
                  // Desligar a proteção EXPÕE nome completo em link público:
                  // exige confirmação consciente (o QR pode já estar impresso).
                  if (!proteger && !window.confirm(
                    "Atenção: desligar a proteção vai EXIBIR O NOME COMPLETO das crianças no telão público (endereço sem senha). Só faça isso com o consentimento dos responsáveis. Deseja continuar?",
                  )) return;
                  salvar({ ...config, anonimizar: proteger });
                }}
              />
              Proteger o nome dos alunos no telão (recomendado)
            </label>
          </Card>

        {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}
      </div>
    </div>
  );
}
