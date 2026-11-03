/**
 * Configurações gerais da escola (Admin Global e admin de escola — RotaAdmin).
 *
 * Identidade visual v2: cada bloco é um cartão branco com cabeçalho de ícone
 * pastel. Os pesos da Nota Geral usam o MESMO editor da tela de Critérios
 * (PesosEditor: só o Admin Global grava) e dizem qual régua está em uso — no
 * perfil Padrão Constela o motor usa os pesos fixos da rede e ignora os valores
 * gravados aqui (GET /configuracoes/pontuacao/regra).
 */
import {
  Award,
  Bot,
  DatabaseBackup,
  Download,
  ListChecks,
  Palette,
  Scale,
  School,
  UploadCloud,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";

import ConfigAssistenteIA from "../../components/ConfigAssistenteIA";
import { CabecalhoCartao, META_CRITERIOS, formatarPeso, ordenarCriterios } from "../../components/CriteriosVisuais";
import { Botao, Confirmacao, IconePastel, Mensagem, PageHeader, Skeleton, estiloInput, type TomPastel } from "../../components/ui";
import { PesosEditor } from "./Metricas";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { useModulos } from "../../hooks/useModulos";
import { api, ApiError, apiDownload, apiUpload } from "../../lib/api";
import type { RegraPontuacao } from "../../lib/tiposCriterios";

interface AparenciaDados {
  cor_primaria: string;
  brasao_data_uri?: string;
  prefeitura_data_uri?: string;
}

/** Cartão de seção com cabeçalho (ícone pastel + h2), região nomeada pelo título. */
function Secao({
  icone,
  tom,
  titulo,
  subtitulo,
  children,
  className = "",
}: {
  icone: LucideIcon;
  tom: TomPastel;
  titulo: string;
  subtitulo?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={`card p-5 sm:p-6 ${className}`}>
      <CabecalhoCartao id={id} icone={icone} tom={tom} titulo={titulo} subtitulo={subtitulo} />
      <div className="mt-5">{children}</div>
    </section>
  );
}

/** Um "slot" de logo da cidade (brasão ou prefeitura): prévia + enviar + remover.
 * A imagem sobe para a escola e passa a aparecer no topo dos PDFs (certificado,
 * cartaz, lista de alunos, catálogo). Sem envio, o PDF usa o logo padrão. */
function LogoUploader({
  escolaId, tipo, titulo, atual, onMudou, editavel,
}: {
  escolaId: number;
  tipo: "brasao" | "prefeitura";
  titulo: string;
  atual?: string;
  onMudou: () => Promise<unknown> | void;
  editavel: boolean;
}) {
  const arquivoRef = useRef<HTMLInputElement | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  async function enviar(arquivo: File) {
    setOcupado(true);
    setErro("");
    try {
      const dados = new FormData();
      dados.append("arquivo", arquivo);
      await apiUpload(`/escolas/${escolaId}/aparencia/logo?tipo=${tipo}`, dados);
      await onMudou();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao enviar a imagem.");
    } finally {
      setOcupado(false);
      if (arquivoRef.current) arquivoRef.current.value = "";
    }
  }

  async function remover() {
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/aparencia/logo?tipo=${tipo}`, { method: "DELETE" });
      await onMudou();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao remover.");
    } finally {
      setOcupado(false);
    }
  }

  // Celular (< 640 px): as ações descem para a linha de baixo, alinhadas ao texto (o
  // texto não fica espremido entre a miniatura e o botão), e os botões têm 40 px.
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-zinc-200/80 bg-zinc-50/60 p-3 sm:flex-nowrap dark:border-zinc-800 dark:bg-zinc-800/40">
      <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-zinc-200/80 bg-white dark:border-zinc-700 dark:bg-zinc-900">
        {atual ? (
          <img src={atual} alt={titulo} className="max-h-14 max-w-[3.5rem] object-contain" />
        ) : (
          <span className="text-[11px] text-zinc-500 dark:text-zinc-400">padrão</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{titulo}</p>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {atual ? "Enviado por esta escola." : "Usando o logo padrão do sistema."}
        </p>
        {erro && <p className="mt-1 text-xs text-rose-600 dark:text-rose-300">{erro}</p>}
      </div>
      {editavel && (
        <div className="flex shrink-0 flex-col items-end gap-1 max-sm:w-full max-sm:flex-row max-sm:items-center max-sm:gap-3 max-sm:pl-[4.75rem]">
          <Botao
            variante="secundario"
            tamanho="sm"
            className="max-sm:min-h-10 max-sm:px-4 max-sm:text-sm"
            disabled={ocupado}
            onClick={() => arquivoRef.current?.click()}
          >
            <UploadCloud size={14} aria-hidden /> {atual ? "Trocar" : "Enviar"}
          </Botao>
          {atual && (
            <button
              type="button"
              onClick={remover}
              disabled={ocupado}
              className="text-xs text-zinc-500 hover:text-rose-600 disabled:opacity-50 max-sm:min-h-10 max-sm:px-2 max-sm:text-sm dark:text-zinc-400"
            >
              Remover
            </button>
          )}
          <input
            ref={arquivoRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(evento) => {
              const arquivo = evento.target.files?.[0];
              if (arquivo) enviar(arquivo);
            }}
          />
        </div>
      )}
    </div>
  );
}

/** Aparência (PRD §18): cor primária e logos da cidade usados nos PDFs. */
function Aparencia() {
  const { escolaId, usuario } = useApp();
  const ehAdmin = usuario?.is_global || usuario?.cargo === "admin";
  const [cor, setCor] = useState("#1B2A4A");
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  // A cor é estado editável (color picker + PUT); buscamos a salva e semeamos o input.
  const { dados: aparencia, erro: erroAparencia, recarregar } = useApi<AparenciaDados>(
    escolaId ? `/escolas/${escolaId}/aparencia` : null,
  );

  useEffect(() => {
    if (aparencia) setCor(aparencia.cor_primaria);
  }, [aparencia]);

  async function salvar() {
    if (!escolaId) return;
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}/aparencia`, {
        method: "PUT",
        body: JSON.stringify({ cor_primaria: cor, mostrar_fotos: true }),
      });
      setMensagem({ tipo: "ok", texto: "Aparência salva. Relatórios e certificados usarão a nova cor." });
    } catch (excecao) {
      setMensagem({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Falha ao salvar." });
    }
  }

  return (
    <Secao
      icone={Palette}
      tom="rosa"
      titulo="Aparência"
      subtitulo="Cor e logos que aparecem nos relatórios em PDF/Excel e nos certificados."
    >
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-3 text-sm">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">Cor primária da escola</span>
          <input
            type="color"
            aria-label="Cor primária"
            className="h-10 w-14 cursor-pointer rounded-xl border border-zinc-200 bg-transparent p-1 dark:border-zinc-700"
            value={cor}
            onChange={(evento) => setCor(evento.target.value.toUpperCase())}
            disabled={!ehAdmin}
          />
          <code className="rounded-lg bg-zinc-100 px-2 py-1 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">{cor}</code>
        </label>
        {ehAdmin && <Botao onClick={salvar}>Salvar aparência</Botao>}
      </div>

      {escolaId && (
        <div className="mt-5 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Logos da cidade nos documentos</p>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Aparecem no topo dos certificados e relatórios em PDF, ao lado da marca
            Constela (brasão à esquerda, prefeitura à direita). PNG com fundo
            transparente fica melhor. Sem envio, o sistema usa o logo padrão.
          </p>
          <div className="mt-3 grid gap-3">
            <LogoUploader
              escolaId={escolaId}
              tipo="brasao"
              titulo="Brasão da cidade"
              atual={aparencia?.brasao_data_uri}
              onMudou={recarregar}
              editavel={!!ehAdmin}
            />
            <LogoUploader
              escolaId={escolaId}
              tipo="prefeitura"
              titulo="Logo da prefeitura"
              atual={aparencia?.prefeitura_data_uri}
              onMudou={recarregar}
              editavel={!!ehAdmin}
            />
          </div>
        </div>
      )}

      {erroAparencia && (
        <div className="mt-3">
          <Mensagem tipo="erro">Não foi possível carregar a aparência salva: {erroAparencia.message}</Mensagem>
        </div>
      )}
      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
    </Secao>
  );
}

/** Backup e restauração por escola (PRD §18). */
function Backup() {
  const { escolaId, usuario } = useApp();
  const ehAdmin = usuario?.is_global || usuario?.cargo === "admin";
  // GOVERNANÇA: restaurar SUBSTITUI livros, leituras, faixas, pesos e parâmetros
  // de pontuação da escola — exclusivo do Admin Global (o backend responde 403
  // aos demais). Baixar o backup continua com o admin da escola.
  const podeRestaurar = Boolean(usuario?.is_global);
  const arquivoRef = useRef<HTMLInputElement | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  // Avisos da restauração (D10): conta da plataforma restaurada que passou a valer
  // também aqui sendo a identidade de um aluno de OUTRA escola. Ficam na tela até
  // a próxima ação — o Admin Global precisa ler antes de seguir.
  const [avisos, setAvisos] = useState<string[]>([]);
  const [ocupado, setOcupado] = useState(false);
  // Arquivo escolhido à espera da confirmação (a restauração substitui os dados).
  const [arquivoPendente, setArquivoPendente] = useState<File | null>(null);

  if (!ehAdmin) return null;

  async function baixar() {
    if (!escolaId) return;
    setOcupado(true);
    setMensagem(null);
    setAvisos([]);
    try {
      await apiDownload(`/escolas/${escolaId}/backup`);
      setMensagem({ tipo: "ok", texto: "Backup gerado. Guarde o arquivo em local seguro." });
    } catch (excecao) {
      setMensagem({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Falha no backup." });
    } finally {
      setOcupado(false);
    }
  }

  /** Desistiu da restauração: esquece o arquivo (escolher o mesmo de novo reabre). */
  function cancelarRestauracao() {
    setArquivoPendente(null);
    if (arquivoRef.current) arquivoRef.current.value = "";
  }

  async function restaurar(arquivo: File) {
    if (!escolaId) return;
    setOcupado(true);
    setMensagem(null);
    setAvisos([]);
    try {
      const dados = new FormData();
      dados.append("arquivo", arquivo);
      const resposta = await apiUpload<{ mensagem: string; avisos?: string[] }>(
        `/escolas/${escolaId}/restaurar`, dados);
      setMensagem({ tipo: "ok", texto: resposta.mensagem });
      setAvisos(resposta.avisos ?? []);
    } catch (excecao) {
      setMensagem({ tipo: "erro", texto: excecao instanceof Error ? excecao.message : "Falha na restauração." });
    } finally {
      setOcupado(false);
      setArquivoPendente(null);
      if (arquivoRef.current) arquivoRef.current.value = "";
    }
  }

  return (
    <Secao
      icone={DatabaseBackup}
      tom="azul"
      titulo="Backup e restauração"
      subtitulo="Uma cópia de segurança com os dados pedagógicos desta escola."
    >
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-300">
        O backup é um arquivo JSON com todos os dados pedagógicos desta escola
        (funciona em SQLite e PostgreSQL). Usuários e senhas ficam de fora, por segurança.
      </p>
      <div className="flex flex-wrap gap-2.5">
        <Botao onClick={baixar} disabled={ocupado}>
          <Download size={15} aria-hidden /> Baixar backup
        </Botao>
        {podeRestaurar && (
          <>
            <Botao
              variante="secundario"
              disabled={ocupado}
              onClick={() => arquivoRef.current?.click()}
            >
              <UploadCloud size={15} aria-hidden /> Restaurar de um arquivo…
            </Botao>
            <input
              ref={arquivoRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={(evento) => {
                const arquivo = evento.target.files?.[0];
                if (arquivo) setArquivoPendente(arquivo);
              }}
            />
          </>
        )}
      </div>
      {!podeRestaurar && (
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
          Restaurar um backup substitui livros, leituras, faixas, pesos e parâmetros
          de pontuação: só o Admin Global pode fazer isso.
        </p>
      )}
      {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
      {avisos.length > 0 && (
        <div
          role="alert"
          aria-label="Avisos da restauração"
          className="mt-3 space-y-1 rounded-xl border border-ouro-200 bg-ouro-50 px-3.5 py-2.5 text-sm text-amber-900 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-ouro-100"
        >
          {avisos.map((aviso) => <p key={aviso}>{aviso}</p>)}
        </div>
      )}
      {podeRestaurar && (
        <Confirmacao
          titulo="Restaurar este backup?"
          aberto={arquivoPendente !== null}
          aoFechar={cancelarRestauracao}
          aoConfirmar={() => {
            if (arquivoPendente) void restaurar(arquivoPendente);
          }}
          rotuloConfirmar={ocupado ? "Restaurando..." : "Substituir os dados"}
          variante="perigo"
          ocupado={ocupado}
        >
          {arquivoPendente && (
            <p>
              Arquivo: <strong className="break-all">{arquivoPendente.name}</strong>
            </p>
          )}
          <p>
            <strong className="text-zinc-800 dark:text-zinc-100">Atenção:</strong> a restauração
            SUBSTITUI todos os dados pedagógicos desta escola pelos do arquivo (alunos, turmas,
            notas, importações, configurações).
          </p>
          <p>
            Usuários e senhas não são alterados, nem a política de criação de alunos e o vínculo
            da escola externa da sincronização.
          </p>
        </Confirmacao>
      )}
    </Secao>
  );
}

/**
 * Qual régua decide a Nota Geral NESTA escola (GET /configuracoes/pontuacao/regra).
 * No perfil Padrão Constela o motor usa os pesos fixos da rede (com o contrato de
 * módulos) e ignora os valores gravados no editor — a mesma ilusão de controle
 * que a tela de Critérios evita com o aviso do perfil Padrão.
 */
function AvisoNotaGeral() {
  const { escolaId } = useApp();
  const { unico } = useModulos();
  const { dados, erro, carregando } = useApi<RegraPontuacao>(
    escolaId ? `/escolas/${escolaId}/configuracoes/pontuacao/regra` : null,
  );
  if (!escolaId) return null;
  if (carregando) {
    return (
      <div className="mt-4" aria-hidden>
        <Skeleton className="h-12 w-full rounded-xl" />
      </div>
    );
  }
  let regua: string;
  if (erro || !dados) {
    regua = "Não foi possível verificar a régua em uso agora.";
  } else if (dados.perfil === "institucional") {
    const emUso = ordenarCriterios(Object.keys(dados.nota_geral.pesos))
      .map((chave) => `${META_CRITERIOS[chave]?.titulo ?? chave} ${formatarPeso(dados.nota_geral.pesos[chave])}%`)
      .join(" · ");
    regua =
      `Esta escola usa a Régua Padrão Constela: a Nota Geral segue os pesos fixos da rede (em uso: ${emUso}). ` +
      "Os valores abaixo só passam a valer numa régua personalizada.";
  } else {
    regua = "Esta escola usa uma régua personalizada: os pesos abaixo estão em uso na Nota Geral.";
  }
  return (
    <div className="mt-4 space-y-1 rounded-xl border border-ouro-200 bg-ouro-50 px-3.5 py-2.5 text-[13px] leading-snug text-amber-900 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-ouro-200">
      <p>{regua}</p>
      <p>
        A Nota Geral é legado: ordena só o Ranking Geral, o certificado “Geral” e as vitrines.
        {unico ? " Com uma só matéria no plano, ela é a própria nota dessa matéria." : ""}
      </p>
    </div>
  );
}

/** Cartão de atalho para outra tela (o link fica no texto, com nome curto). */
function Atalho({
  icone,
  tom,
  titulo,
  children,
}: {
  icone: LucideIcon;
  tom: TomPastel;
  titulo: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="card p-5 sm:p-6">
      <div className="flex items-start gap-4">
        <IconePastel icone={icone} tom={tom} tamanho="lg" />
        <div className="min-w-0 flex-1 text-sm text-zinc-600 dark:text-zinc-300">
          <h2 id={id} className="text-[17px] font-semibold text-zinc-900 dark:text-white">{titulo}</h2>
          <p className="mt-1">{children}</p>
        </div>
      </div>
    </section>
  );
}

const ESTILO_LINK = "font-semibold text-indigo-600 hover:underline dark:text-indigo-300";

export default function Configuracoes() {
  const { escolaAtual, escolaId, recarregarEscolas, usuario } = useApp();
  const ehAdminIA = Boolean(usuario?.is_global) || usuario?.cargo === "admin";
  const idIA = useId();
  const [nome, setNome] = useState("");
  const [cidade, setCidade] = useState("");
  const [estado, setEstado] = useState("");
  const [anoLetivo, setAnoLetivo] = useState(2026);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    if (!escolaAtual) return;
    setNome(escolaAtual.nome);
    setCidade(escolaAtual.cidade ?? "");
    setEstado(escolaAtual.estado ?? "");
    setAnoLetivo(escolaAtual.ano_letivo_ativo);
    setMensagem(null);
  }, [escolaAtual]);

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    if (!escolaId) return;
    setSalvando(true);
    setMensagem(null);
    try {
      await api(`/escolas/${escolaId}`, {
        method: "PATCH",
        body: JSON.stringify({
          nome,
          cidade: cidade || null,
          estado: estado || null,
          ano_letivo_ativo: anoLetivo,
        }),
      });
      await recarregarEscolas();
      setMensagem({ tipo: "ok", texto: "Dados da escola atualizados." });
    } catch (excecao) {
      setMensagem({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message : "Não foi possível salvar.",
      });
    } finally {
      setSalvando(false);
    }
  }

  const rotuloCampo = "mb-1.5 block font-medium text-zinc-700 dark:text-zinc-300";

  return (
    <div>
      <PageHeader
        titulo="Configurações"
        descricao="Dados da escola, aparência dos documentos, backup e os atalhos para as regras do sistema."
      />

      {/* Duas colunas independentes no desktop (sem buracos de altura entre os
          cartões); no tablet, uma coluna só, na mesma ordem. */}
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <div className="space-y-6">
          <Secao icone={School} tom="violeta" titulo="Escola" subtitulo="Nome, cidade e o ano letivo em uso.">
            <form onSubmit={salvar} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="block text-sm sm:col-span-2">
                <span className={rotuloCampo}>Nome</span>
                <input
                  required
                  className={estiloInput}
                  value={nome}
                  onChange={(evento) => setNome(evento.target.value)}
                />
              </label>
              <label className="block text-sm">
                <span className={rotuloCampo}>Cidade</span>
                <input
                  className={estiloInput}
                  value={cidade}
                  onChange={(evento) => setCidade(evento.target.value)}
                />
              </label>
              <label className="block text-sm">
                <span className={rotuloCampo}>Estado (UF)</span>
                <input
                  maxLength={2}
                  className={`${estiloInput} uppercase`}
                  value={estado}
                  onChange={(evento) => setEstado(evento.target.value.toUpperCase())}
                />
              </label>
              <label className="block text-sm">
                <span className={rotuloCampo}>Ano letivo ativo</span>
                <input
                  type="number"
                  min={2024}
                  max={2100}
                  className={`${estiloInput} tabular-nums`}
                  value={anoLetivo}
                  onChange={(evento) => setAnoLetivo(Number(evento.target.value))}
                />
              </label>
              <div className="flex items-end sm:col-span-2">
                <Botao type="submit" disabled={salvando}>
                  {salvando ? "Salvando..." : "Salvar dados da escola"}
                </Botao>
              </div>
            </form>
            {mensagem && <div className="mt-3"><Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem></div>}
          </Secao>

          <PesosEditor
            namespace="geral"
            rotulos={{ matific: "Matific", elefante: "Elefante Letrado" }}
            titulo="Pesos do Ranking Geral"
            icone={Scale}
            tom="teal"
            descricao="Como as notas de Leitura e de Matemática se combinam na Nota Geral."
            aviso={<AvisoNotaGeral />}
          />
        </div>

        <div className="space-y-6">
          <Aparencia />

          <Backup />

          <Atalho icone={Award} tom="ambar" titulo="Conquistas">
            Crie e ajuste as medalhas da escola — critérios, XP, raridade, ordem e ativação — na tela{" "}
            <Link to="/configuracoes/conquistas" className={ESTILO_LINK}>
              Configurações → Conquistas
            </Link>
            . As mudanças valem imediatamente para todos os alunos.
          </Atalho>

          <Atalho icone={ListChecks} tom="azul" titulo="Critérios de avaliação">
            Os pesos em uso, as regras da premiação e um exemplo calculado ficam na tela{" "}
            <Link to="/metricas" className={ESTILO_LINK}>
              Critérios de pontuação
            </Link>
            . Contas de acesso ficam na tela{" "}
            <Link to="/usuarios" className={ESTILO_LINK}>
              Usuários
            </Link>
            .
          </Atalho>
        </div>
      </div>

      {/* Assistente de IA no mesmo padrão dos outros blocos: ícone pastel, título e
          descrição DENTRO do cartão (antes o título ficava fora e o robô se repetia). */}
      {ehAdminIA && (
        <section aria-labelledby={idIA} className="mt-6">
          <ConfigAssistenteIA
            cabecalho={
              <CabecalhoCartao
                id={idIA}
                icone={Bot}
                tom="violeta"
                titulo="Assistente de IA"
                subtitulo="Quem responde no Assistente Pedagógico: o modo local ou uma IA externa."
              />
            }
          />
        </section>
      )}
    </div>
  );
}
