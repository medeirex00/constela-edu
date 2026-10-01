/** Relatórios (PRD §86–§103): exportação CSV/Excel/PDF e certificados. */
import { Award, BookOpen, Calculator, FileDown, FileSpreadsheet, FileText } from "lucide-react";
import { useState } from "react";

import { Botao, Campo, Card, Mensagem, PageHeader, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { apiDownload } from "../lib/api";
import type { PaginaAlunos } from "../lib/types";

const RELATORIOS = [
  { tipo: "ranking", nome: "Ranking Geral", descricao: "Posição e notas de todos os alunos do ano letivo." },
  { tipo: "alunos", nome: "Lista de Alunos", descricao: "Alunos ativos com turma, série e número de chamada." },
  { tipo: "livros", nome: "Catálogo de Livros", descricao: "Acervo com níveis e total de leituras registradas." },
];

const FORMATOS = [
  { formato: "pdf", rotulo: "PDF", icone: FileText },
  { formato: "xlsx", rotulo: "Excel", icone: FileSpreadsheet },
  { formato: "csv", rotulo: "CSV", icone: FileDown },
];

/** Calendário oficial dos bimestres (Rede Estadual de SP, 2026) — as MESMAS
 *  datas de `backend/app/services/bimestres.py`, que é quem manda. Aqui elas só
 *  decidem qual opção o seletor abre marcada; o número impresso é sempre o que
 *  o backend recebe. Fim de cada bimestre, inclusivo: 22/04, 23/07, 04/10, 31/12.
 *
 *  Não é o mês do relógio: em 01/10 o 3º bimestre ainda não acabou, e era
 *  exatamente aí que o mapa por mês fazia o seletor abrir em "4º". */
const FIM_DO_BIMESTRE: Array<[number, number, number]> = [
  [1, 2026, Date.UTC(2026, 3, 22)],
  [2, 2026, Date.UTC(2026, 6, 23)],
  [3, 2026, Date.UTC(2026, 9, 4)],
  [4, 2026, Date.UTC(2026, 11, 31)],
];

export function bimestreDeHoje(d: Date): number {
  const dia = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const doAno = FIM_DO_BIMESTRE.filter(([, ano]) => ano === d.getFullYear());
  if (!doAno.length) return 1; // ano sem calendário: o backend decide o padrão
  const achado = doAno.find(([, , fim]) => dia <= fim);
  return achado ? achado[0] : 4;
}

/** Turmas que NÃO concorrem às premiações — espelho de
 *  `backend/app/services/elegibilidade.py`. O backend barra de verdade (409);
 *  isto aqui só evita oferecer na tela um nome que não pode ser emitido. */
const RE_ETAPA_FORA =
  /\b(FASE|ETAPA|EMEI|INFANTIL|MATERNAL|BERCARIO|CRECHE|JARDIM|PRE|EJA|MINIGRUPO)\b/;
// O `O` maiúsculo na classe não é descuido: NFKD decompõe "º" em "o", e o rótulo
// é passado para MAIÚSCULAS logo em seguida — "4º" chega aqui como "4O".
const RE_ANO_EXPLICITO = /\b(\d\s*[º°O]?\s*ANO|ANO\s*\d)\b/;

export function participaDePremiacao(anoEscolar: string | null | undefined): boolean {
  const plano = (anoEscolar ?? "")
    .normalize("NFKD").replace(/[̀-ͯ]/g, "").toUpperCase().trim();
  if (!plano) return true; // sem rótulo não dá para afirmar que é fase
  if (!RE_ANO_EXPLICITO.test(plano) && RE_ETAPA_FORA.test(plano)) return false;
  const n = Number((plano.match(/\d/) ?? [])[0]);
  return n >= 1 && n <= 5;
}

export default function Relatorios() {
  const { escolaId, usuario } = useApp();
  // Professor exporta só o superficial (ranking e alunos das turmas dele);
  // o backend também recusa os demais tipos.
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const relatorios = gestor
    ? RELATORIOS
    : RELATORIOS.filter((r) => r.tipo === "ranking" || r.tipo === "alunos");
  // Lista de alunos para o seletor de certificados (leitura via useApi).
  const { dados: paginaAlunos, erro: erroAlunos } = useApi<PaginaAlunos>(
    escolaId ? `/escolas/${escolaId}/alunos?por_pagina=500` : null,
  );
  // Só quem concorre entra no seletor. A Educação Infantil continua ativa e
  // matriculada — ela só não disputa premiação, e oferecer o nome aqui seria
  // oferecer um botão que o backend vai recusar com 409.
  const alunos = (paginaAlunos?.itens ?? [])
    .filter((aluno) => participaDePremiacao(aluno.ano_escolar))
    .map((aluno) => ({ id: aluno.id, nome: aluno.nome }));
  const foraDaPremiacao = (paginaAlunos?.itens ?? []).length - alunos.length;
  const [alunoId, setAlunoId] = useState("");
  // Bimestre IMPRESSO na arte da plataforma. O backend cai no bimestre do MÊS de
  // emissão quando não recebe o parâmetro — e aí o mesmo aluno, com o mesmo dado,
  // recebe "3" num dia e "4" no seguinte se a entrega atravessa a virada. Quem
  // emite escolhe; o padrão é o bimestre de hoje, para a tela não mudar nada
  // para quem não liga para isso.
  const [bimestre, setBimestre] = useState(String(bimestreDeHoje(new Date())));
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState("");

  async function baixar(caminho: string, chave: string) {
    if (!escolaId) return;
    setOcupado(chave);
    setErro("");
    try {
      await apiDownload(caminho);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao gerar o arquivo.");
    } finally {
      setOcupado("");
    }
  }

  return (
    <div>
      <PageHeader
        titulo="Relatórios"
        descricao="Exportações com a identidade visual da escola. Uma cópia de cada arquivo fica registrada em /exports."
      />
      {erro && <div className="mb-4"><Mensagem tipo="erro">{erro}</Mensagem></div>}

      <div className="grid gap-4 lg:grid-cols-3">
        {relatorios.map((relatorio) => (
          <Card key={relatorio.tipo} className="flex flex-col p-5">
            <h3 className="text-sm font-semibold">{relatorio.nome}</h3>
            <p className="mt-1 flex-1 text-sm text-zinc-500 dark:text-zinc-400">{relatorio.descricao}</p>
            <div className="mt-4 flex gap-2">
              {FORMATOS.map(({ formato, rotulo, icone: Icone }) => (
                <Botao
                  key={formato}
                  variante="neutro"
                  disabled={ocupado !== ""}
                  onClick={() =>
                    baixar(`/escolas/${escolaId}/relatorios/${relatorio.tipo}?formato=${formato}`,
                           `${relatorio.tipo}-${formato}`)
                  }
                >
                  <Icone size={14} />
                  {ocupado === `${relatorio.tipo}-${formato}` ? "Gerando..." : rotulo}
                </Botao>
              ))}
            </div>
          </Card>
        ))}
      </div>

      <div className="mt-8 max-w-2xl">
        <h2 className="mb-3 text-sm font-semibold">Certificados</h2>
        <Card className="p-5">
          <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
            Escolha o aluno e emita o certificado em PDF de alta resolução. Todos os campos
            (instituição, nome do aluno, bimestre e data) são preenchidos <strong>automaticamente</strong>.
            O <strong>Geral</strong> traz turma, nota e posição; os de <strong>Elefante Letrado</strong> e
            <strong> Matific</strong> usam a arte oficial da plataforma.
          </p>
          <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
            O <strong>bimestre</strong> é o período que o documento afirma, e não a data em que
            ele sai: dá para emitir hoje um certificado do 3º bimestre. O seletor abre no
            bimestre de hoje pelo calendário oficial, mas a sua escolha é que vale.
            {foraDaPremiacao > 0 && (
              <>
                {" "}As premiações são do <strong>1º ao 5º ano</strong>;{" "}
                {foraDaPremiacao === 1
                  ? "1 aluno de Educação Infantil não aparece na lista"
                  : `${foraDaPremiacao} alunos de Educação Infantil não aparecem na lista`}
                {" "}— o cadastro e a matrícula deles seguem normais.
              </>
            )}
          </p>
          {erroAlunos && (
            <div className="mb-4"><Mensagem tipo="erro">Não foi possível carregar os alunos: {erroAlunos.message}</Mensagem></div>
          )}
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1">
              <Campo rotulo="Aluno">
                <select className={estiloInput} value={alunoId} onChange={(e) => setAlunoId(e.target.value)}>
                  <option value="">Selecione…</option>
                  {alunos.map((aluno) => (
                    <option key={aluno.id} value={aluno.id}>{aluno.nome}</option>
                  ))}
                </select>
              </Campo>
            </div>
            <div className="w-44">
              <Campo rotulo="Bimestre">
                <select className={estiloInput} value={bimestre}
                        onChange={(e) => setBimestre(e.target.value)}>
                  {[1, 2, 3, 4].map((b) => (
                    <option key={b} value={b}>{b}º Bimestre</option>
                  ))}
                </select>
              </Campo>
            </div>
            <div className="flex flex-wrap gap-2">
              <Botao
                variante="neutro"
                disabled={!alunoId || ocupado !== ""}
                onClick={() => baixar(`/escolas/${escolaId}/certificados/${alunoId}`, "cert-geral")}
              >
                <Award size={15} /> {ocupado === "cert-geral" ? "Gerando..." : "Geral"}
              </Botao>
              <Botao
                disabled={!alunoId || ocupado !== ""}
                onClick={() => baixar(`/escolas/${escolaId}/certificados/${alunoId}?modelo=elefante&bimestre=${bimestre}`, "cert-elefante")}
              >
                <BookOpen size={15} /> {ocupado === "cert-elefante" ? "Gerando..." : "Elefante Letrado"}
              </Botao>
              <Botao
                disabled={!alunoId || ocupado !== ""}
                onClick={() => baixar(`/escolas/${escolaId}/certificados/${alunoId}?modelo=matific&bimestre=${bimestre}`, "cert-matific")}
              >
                <Calculator size={15} /> {ocupado === "cert-matific" ? "Gerando..." : "Matific"}
              </Botao>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
