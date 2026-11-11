/** Relatórios (PRD §86–§103): exportação CSV/Excel/PDF e certificados. */
import {
  Award,
  BookOpen,
  Calculator,
  ChevronDown,
  FileDown,
  FileSpreadsheet,
  FileText,
  Library,
  Search,
  Trophy,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useId, useState } from "react";

import { Botao, Campo, Card, IconePastel, Mensagem, PageHeader, estiloInput, type TomPastel } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { apiDownload } from "../lib/api";
import type { PaginaAlunos } from "../lib/types";

const RELATORIOS: { tipo: string; nome: string; descricao: string; icone: LucideIcon; tom: TomPastel }[] = [
  { tipo: "ranking", nome: "Ranking Geral", descricao: "Posição e notas de todos os alunos do ano letivo.", icone: Trophy, tom: "ambar" },
  { tipo: "alunos", nome: "Lista de Alunos", descricao: "Alunos ativos com turma, série e número de chamada.", icone: Users, tom: "azul" },
  { tipo: "livros", nome: "Catálogo de Livros", descricao: "Acervo com níveis e total de leituras registradas.", icone: Library, tom: "violeta" },
];

const FORMATOS = [
  { formato: "pdf", rotulo: "PDF", icone: FileText },
  { formato: "xlsx", rotulo: "Excel", icone: FileSpreadsheet },
  { formato: "csv", rotulo: "CSV", icone: FileDown },
];

// Calendário oficial dos bimestres e elegibilidade às premiações: a cópia única fica em
// lib/calendarioBimestres.ts (o menu, o Ranking e a Visão Geral também usam). Os nomes
// continuam exportados daqui para quem já importava desta página.
import {
  bimestreDeHoje, participaDePremiacao, semCalendarioOficial, useCalendarioBimestres,
} from "../lib/calendarioBimestres";

export { bimestreDeHoje, participaDePremiacao };

/** Sem acento e em minúsculas, para a busca pelo nome no seletor. */
const semAcento = (texto: string) => texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** <select> nativo com a seta da v2: sem a seta do navegador e com espaço à direita
 *  para o texto não invadir o ícone. O select continua nativo (testes usam selectOptions). */
const ESTILO_SELECT = `${estiloInput} cursor-pointer appearance-none truncate pr-10 disabled:cursor-not-allowed`;

function SetaSelect() {
  return (
    <ChevronDown
      size={16}
      aria-hidden
      className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-zinc-500 dark:text-zinc-400"
    />
  );
}

/** O item de /escolas com o plano da escola (`modulos`, os da rede dela). Opcional: a API
 *  antiga não o manda. */
type EscolaComPlano = { modulos?: string[] };

export default function Relatorios() {
  const { escolaId, escolaAtual, usuario } = useApp();
  const idExportacoes = useId();
  const idCertificados = useId();
  // Professor exporta só o superficial (ranking e alunos das turmas dele);
  // o backend também recusa os demais tipos.
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  // Módulo fora do plano da rede: o Catálogo de Livros (Leitura) e os certificados da
  // plataforma não aparecem — o backend responderia 403 (o lote de certificados já
  // filtrava assim). Vale o plano da ESCOLA selecionada (item de /escolas): o admin
  // global recebe em /auth/me o catálogo inteiro, e numa escola de rede com um módulo
  // só a tela oferecia o que a rede não contratou. Sem o plano na resposta, o do usuário.
  const doUsuario = useModulos();
  const planoDaEscola = (escolaAtual as EscolaComPlano | null)?.modulos;
  const leitura = planoDaEscola?.length ? planoDaEscola.includes("leitura") : doUsuario.leitura;
  const matematica = planoDaEscola?.length
    ? planoDaEscola.includes("matematica")
    : doUsuario.matematica;
  const relatorios = (gestor
    ? RELATORIOS
    : RELATORIOS.filter((r) => r.tipo === "ranking" || r.tipo === "alunos"))
    .filter((r) => r.tipo !== "livros" || leitura);
  // Lista de alunos para o seletor de certificados (leitura via useApi). O backend
  // aceita até 1000 por página: há escola com mais de 500 ativos, e o seletor não
  // pode esconder em silêncio quem vem depois do 500º nome.
  const { dados: paginaAlunos, erro: erroAlunos } = useApi<PaginaAlunos>(
    escolaId ? `/escolas/${escolaId}/alunos?por_pagina=1000` : null,
  );
  // Só quem concorre entra no seletor. A Educação Infantil continua ativa e
  // matriculada — ela só não disputa premiação, e oferecer o nome aqui seria
  // oferecer um botão que o backend vai recusar com 409.
  const alunos = (paginaAlunos?.itens ?? [])
    .filter((aluno) => participaDePremiacao(aluno.ano_escolar))
    .map((aluno) => ({ id: aluno.id, nome: aluno.nome }));
  const foraDaPremiacao = (paginaAlunos?.itens ?? []).length - alunos.length;
  const carregandoAlunos = Boolean(escolaId) && !paginaAlunos && !erroAlunos;
  const [alunoId, setAlunoId] = useState("");
  const [busca, setBusca] = useState("");
  // A busca só estreita a lista; o aluno já escolhido continua no seletor.
  const termo = semAcento(busca.trim());
  const opcoes = termo
    ? alunos.filter((a) => semAcento(a.nome).includes(termo) || String(a.id) === alunoId)
    : alunos;
  // Bimestre IMPRESSO na arte da plataforma. O backend cai no bimestre do MÊS de
  // emissão quando não recebe o parâmetro — e aí o mesmo aluno, com o mesmo dado,
  // recebe "3" num dia e "4" no seguinte se a entrega atravessa a virada. Quem
  // emite escolhe; o padrão é o bimestre de hoje pelo calendário OFICIAL, que vem
  // do backend. Ano sem calendário conhecido não tem "de hoje": o seletor abre
  // vazio e os modelos da plataforma esperam a escolha — antes abria no 1º (de
  // 2027 em diante, o ano todo) e esse número ia impresso.
  const calendario = useCalendarioBimestres(escolaId);
  const hoje = new Date();
  const sugerido = bimestreDeHoje(hoje, calendario);
  const [bimestreEscolhido, setBimestre] = useState<string | null>(null);
  const bimestre = bimestreEscolhido ?? (sugerido != null ? String(sugerido) : "");
  const semCalendario = semCalendarioOficial(hoje, calendario);
  // O erro aparece PERTO do botão que o causou: o da exportação sobre os cartões
  // de exportação; o do certificado (409/422 com o motivo do backend) dentro do
  // cartão de certificados — antes ficava no topo, fora da vista de quem clicou.
  const [erroExportacao, setErroExportacao] = useState("");
  const [erroCertificado, setErroCertificado] = useState("");
  const [ocupado, setOcupado] = useState("");

  async function baixar(caminho: string, chave: string) {
    if (!escolaId) return;
    const definirErro = chave.startsWith("cert-") ? setErroCertificado : setErroExportacao;
    setOcupado(chave);
    setErroExportacao("");
    setErroCertificado("");
    try {
      await apiDownload(caminho);
    } catch (excecao) {
      definirErro(excecao instanceof Error ? excecao.message : "Falha ao gerar o arquivo.");
    } finally {
      setOcupado("");
    }
  }

  // As artes das plataformas imprimem o bimestre (e só saem com ele escolhido); o
  // Geral não imprime.
  const todosModelos: {
    chave: string; rotulo: string; detalhe: string; icone: LucideIcon; tom: TomPastel; caminho: string;
    imprimeBimestre: boolean;
  }[] = [
    {
      chave: "cert-geral", rotulo: "Geral", detalhe: "turma, nota e posição", icone: Award, tom: "ambar",
      caminho: `/escolas/${escolaId}/certificados/${alunoId}`, imprimeBimestre: false,
    },
    {
      chave: "cert-elefante", rotulo: "Elefante Letrado", detalhe: "arte oficial · leitura", icone: BookOpen,
      tom: "violeta", caminho: `/escolas/${escolaId}/certificados/${alunoId}?modelo=elefante&bimestre=${bimestre}`,
      imprimeBimestre: true,
    },
    {
      chave: "cert-matific", rotulo: "Matific", detalhe: "arte oficial · matemática", icone: Calculator,
      tom: "teal", caminho: `/escolas/${escolaId}/certificados/${alunoId}?modelo=matific&bimestre=${bimestre}`,
      imprimeBimestre: true,
    },
  ];
  const modelos = todosModelos.filter(
    (m) => (m.chave !== "cert-elefante" || leitura) && (m.chave !== "cert-matific" || matematica));

  return (
    <div className="space-y-10">
      <PageHeader
        titulo="Relatórios"
        descricao="Exportações e certificados com a identidade visual da escola."
      />

      <section aria-labelledby={idExportacoes} className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <h2 id={idExportacoes} className="text-lg font-bold tracking-tight text-zinc-900 dark:text-white">
            Exportações
          </h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Escolha o formato: PDF, Excel ou CSV.</p>
        </div>
        {erroExportacao && <Mensagem tipo="erro">{erroExportacao}</Mensagem>}

        {/* 2 colunas até o desktop largo: em 1024 px, 3 cartões lado a lado com 3
            botões cada estouravam a largura (rolagem horizontal da página). */}
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {relatorios.map((relatorio) => (
            <Card key={relatorio.tipo} className="flex min-w-0 flex-col p-6">
              <div className="flex items-start gap-4">
                <IconePastel icone={relatorio.icone} tom={relatorio.tom} tamanho="lg" />
                <div className="min-w-0">
                  <h3 className="text-[17px] font-semibold text-zinc-900 dark:text-white">{relatorio.nome}</h3>
                  <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{relatorio.descricao}</p>
                </div>
              </div>
              <div className="mt-auto flex flex-wrap gap-2 pt-5">
                {FORMATOS.map(({ formato, rotulo, icone: Icone }) => (
                  <Botao
                    key={formato}
                    variante="secundario"
                    disabled={ocupado !== ""}
                    // Três cartões com "PDF/Excel/CSV": o nome acessível diz QUAL relatório.
                    aria-label={`Baixar ${relatorio.nome} em ${rotulo}`}
                    aria-busy={ocupado === `${relatorio.tipo}-${formato}`}
                    onClick={() =>
                      baixar(`/escolas/${escolaId}/relatorios/${relatorio.tipo}?formato=${formato}`,
                             `${relatorio.tipo}-${formato}`)
                    }
                  >
                    <Icone size={15} aria-hidden />
                    {ocupado === `${relatorio.tipo}-${formato}` ? "Gerando..." : rotulo}
                  </Botao>
                ))}
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby={idCertificados}>
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-4 border-b border-zinc-100 bg-gradient-to-r from-ouro-50 via-white to-white px-6 py-5 dark:border-zinc-800 dark:from-ouro-400/10 dark:via-zinc-900 dark:to-zinc-900">
            <IconePastel icone={Award} tom="ambar" tamanho="lg" />
            <div className="min-w-0">
              <h2 id={idCertificados} className="text-lg font-bold tracking-tight text-zinc-900 dark:text-white">
                Certificados
              </h2>
              <p className="text-sm text-zinc-600 dark:text-zinc-300">
                Escolha o aluno, o bimestre e o modelo: o PDF sai pronto para imprimir.
              </p>
            </div>
          </div>

          <div className="space-y-5 p-6">
            {erroAlunos && (
              <Mensagem tipo="erro">Não foi possível carregar os alunos: {erroAlunos.message}</Mensagem>
            )}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_10rem]">
              <Campo rotulo="Buscar pelo nome">
                <span className="relative block">
                  <Search size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
                  <input
                    type="search"
                    className={`${estiloInput} pl-9`}
                    placeholder="Parte do nome"
                    value={busca}
                    onChange={(e) => setBusca(e.target.value)}
                  />
                </span>
              </Campo>
              {/* Selects NATIVOS com a seta fina da v2 (appearance-none + ChevronDown), como
                  os filtros do Ranking, de Premiações e de Alunos. */}
              <Campo rotulo="Aluno">
                <span className="relative block">
                  <select
                    className={ESTILO_SELECT}
                    value={alunoId}
                    disabled={carregandoAlunos}
                    onChange={(e) => setAlunoId(e.target.value)}
                  >
                    <option value="">
                      {carregandoAlunos
                        ? "Carregando alunos…"
                        : termo && opcoes.length === 0 ? "Nenhum nome encontrado" : "Selecione…"}
                    </option>
                    {opcoes.map((aluno) => (
                      <option key={aluno.id} value={aluno.id}>{aluno.nome}</option>
                    ))}
                  </select>
                  <SetaSelect />
                </span>
              </Campo>
              <Campo rotulo="Bimestre">
                <span className="relative block">
                  <select className={ESTILO_SELECT} value={bimestre}
                          onChange={(e) => setBimestre(e.target.value)}>
                    {bimestre === "" && <option value="" disabled>Selecione…</option>}
                    {[1, 2, 3, 4].map((b) => (
                      <option key={b} value={b}>{b}º Bimestre</option>
                    ))}
                  </select>
                  <SetaSelect />
                </span>
              </Campo>
            </div>
            {sugerido == null && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {semCalendario
                  ? `O calendário oficial de ${hoje.getFullYear()} não está cadastrado no sistema: escolha o bimestre que o certificado vai afirmar.`
                  : "Escolha o bimestre que o certificado vai afirmar."}
              </p>
            )}
            {foraDaPremiacao > 0 && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                As premiações são do <strong>1º ao 5º ano</strong>;{" "}
                {foraDaPremiacao === 1
                  ? "1 aluno de Educação Infantil não aparece na lista"
                  : `${foraDaPremiacao} alunos de Educação Infantil não aparecem na lista`}
                {" "}— o cadastro e a matrícula deles seguem normais.
              </p>
            )}

            <div>
              <p className="mb-2.5 text-sm font-medium text-zinc-700 dark:text-zinc-300">Modelo do certificado</p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {modelos.map((m) => {
                  const idDetalhe = `${idCertificados}-${m.chave}`;
                  const rotulo = ocupado === m.chave ? "Gerando..." : m.rotulo;
                  return (
                    <button
                      key={m.chave}
                      type="button"
                      aria-label={rotulo}
                      aria-describedby={idDetalhe}
                      aria-busy={ocupado === m.chave}
                      disabled={!alunoId || ocupado !== "" || (m.imprimeBimestre && !bimestre)}
                      onClick={() => baixar(m.caminho, m.chave)}
                      className="flex min-w-0 items-center gap-3 rounded-2xl border border-zinc-200 bg-white p-4 text-left shadow-cartao transition-colors hover:border-indigo-300 hover:bg-indigo-50/40 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-zinc-200 disabled:hover:bg-white dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-indigo-500/50 dark:hover:bg-indigo-500/10 dark:disabled:hover:border-zinc-700 dark:disabled:hover:bg-zinc-900"
                    >
                      <IconePastel icone={m.icone} tom={m.tom} />
                      <span className="min-w-0">
                        <span className="block font-semibold text-zinc-900 dark:text-white">{rotulo}</span>
                        <span id={idDetalhe} className="block text-xs text-zinc-500 dark:text-zinc-400">{m.detalhe}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
              {!alunoId && !carregandoAlunos && (
                <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">Escolha um aluno para liberar os modelos.</p>
              )}
              {alunoId && !bimestre && modelos.some((m) => m.imprimeBimestre) && (
                <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                  Escolha o bimestre para liberar os modelos das plataformas.
                </p>
              )}
            </div>

            {erroCertificado && <Mensagem tipo="erro">{erroCertificado}</Mensagem>}

            {/* O texto longo continua inteiro — só passou para um "Como funciona". */}
            <details className="group rounded-2xl border border-zinc-200 bg-zinc-50/60 px-4 py-3 text-sm dark:border-zinc-800 dark:bg-zinc-800/30">
              <summary className="flex cursor-pointer select-none list-none items-center gap-2 font-semibold text-zinc-700 hover:text-indigo-600 dark:text-zinc-200 dark:hover:text-indigo-300 [&::-webkit-details-marker]:hidden">
                Como funciona
                <ChevronDown size={16} aria-hidden className="ml-auto text-zinc-400 transition-transform group-open:rotate-180" />
              </summary>
              <div className="mt-3 space-y-3 text-zinc-600 dark:text-zinc-300">
                <p>
                  Escolha o aluno e emita o certificado em PDF de alta resolução. Todos os campos
                  (instituição, nome do aluno, bimestre e data) são preenchidos <strong>automaticamente</strong>.
                  O <strong>Geral</strong> traz turma, nota e posição; os de <strong>Elefante Letrado</strong> e
                  <strong> Matific</strong> usam a arte oficial da plataforma.
                </p>
                <p>
                  O <strong>bimestre</strong> é o período que o documento afirma, e não a data em que
                  ele sai: dá para emitir hoje um certificado do 3º bimestre.{" "}
                  {sugerido != null
                    ? "O seletor abre no bimestre de hoje pelo calendário oficial, mas a sua escolha é que vale."
                    : "Sem o calendário oficial do ano no sistema, o seletor abre vazio: a escolha é sua."}
                </p>
              </div>
            </details>
          </div>
        </Card>
      </section>
    </div>
  );
}
