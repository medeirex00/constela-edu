import { ArrowLeft, ChartColumn, ClipboardCheck, MapPinned } from "lucide-react";
import { useCallback, useState } from "react";
import { Link } from "react-router-dom";

import { TabelaRolavel } from "../../../components/TabelaRolavel";
import { Botao, Card, Carregando, Erro, PageHeader, estiloInput } from "../../../components/ui";
import { useApp } from "../../../context/AppContext";
import { useApi } from "../../../hooks/useApi";
import { CLASSE_LINK_ACAO, CINZA, TITULO_SECAO } from "./pecas";
import MapaDemoCaragua from "./MapaDemoCaragua";
import {
  coberturaDemo, faixaDemo, notaDemo, participacaoDemo, resultadoDemo, totalizarDemo,
  type AvaliacaoDemo, type DadosDemoCaragua, type EscolaDemo, type RegiaoId,
} from "./dadosDemoCaragua";

const LIMITE_COMPARACAO = 4;
const tabela = "w-full text-left text-sm";
const divisoria = "border-b border-zinc-200 dark:border-zinc-800";
const celula = "px-3 py-2.5";

function Metricas({ escolas }: { escolas: EscolaDemo[] }) {
  const { nota, comDados, matriculados } = totalizarDemo(escolas);
  const { cor, rotulo } = faixaDemo(nota);
  return (
    <dl className="grid grid-cols-2 gap-2">
      <div className="min-w-0 rounded-xl bg-zinc-50 p-3 dark:bg-zinc-800/75">
        <dt className={"text-xs font-medium " + CINZA}>Desempenho</dt>
        <dd className="mt-1 break-words text-lg font-semibold">{notaDemo(nota)}{nota !== null && <small> / 100</small>}</dd>
        <dd className="mt-1 flex items-center gap-1.5 text-xs">
          <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: cor }} aria-hidden />
          {rotulo}
        </dd>
      </div>
      <div className="min-w-0 rounded-xl bg-zinc-50 p-3 dark:bg-zinc-800/75">
        <dt className={"text-xs font-medium " + CINZA}>Participação</dt>
        <dd className="mt-1 break-words text-lg font-semibold">{participacaoDemo(comDados, matriculados)}</dd>
        <dd className={"mt-1 text-xs " + CINZA}>{coberturaDemo(comDados, matriculados)}</dd>
      </div>
    </dl>
  );
}

function Comparacao({ escolas, limpar }: { escolas: EscolaDemo[]; limpar: () => void }) {
  return (
    <section aria-labelledby="demo-caragua-comparacao" className="scroll-mt-24" id="comparacao-escolas-demo">
      <Card className="space-y-4 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className={TITULO_SECAO} id="demo-caragua-comparacao">
            <ChartColumn size={20} aria-hidden className="text-indigo-500" /> Comparação de escolas
          </h2>
          {escolas.length > 0 && <Botao type="button" variante="secundario" tamanho="sm" onClick={limpar}>Limpar comparação</Botao>}
        </div>
        {escolas.length < 2 ? (
          <p className={"text-sm " + CINZA}>Marque de 2 a {LIMITE_COMPARACAO} escolas na lista do mapa.</p>
        ) : (
          <TabelaRolavel rotulo="Comparação de escolas fictícias">
            <table className={tabela}>
              <caption className="sr-only">Comparação de escolas fictícias</caption>
              <thead className={divisoria}>
                <tr>
                  <th scope="col" className={celula}>Escola</th>
                  <th scope="col" className={celula}>Desempenho (0 a 100)</th>
                  <th scope="col" className={celula}>Participação</th>
                  <th scope="col" className={celula}>Cobertura dos dados</th>
                </tr>
              </thead>
              <tbody>
                {escolas.map((escola) => (
                  <tr key={escola.id} className={divisoria + " last:border-0"}>
                    <th scope="row" className={celula + " font-medium"}>{escola.nome}</th>
                    <td className={celula}>{notaDemo(escola.nota)}</td>
                    <td className={celula}>{participacaoDemo(escola.com_dados, escola.matriculados)}</td>
                    <td className={celula}>{coberturaDemo(escola.com_dados, escola.matriculados)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>
    </section>
  );
}

function Avaliacoes({ dados }: { dados: DadosDemoCaragua }) {
  const [tipo, setTipo] = useState<AvaliacaoDemo["avaliacao"]>("SARESP");
  const [edicaoPreferida, setEdicao] = useState<number | null>(null);
  const [seriePreferida, setSerie] = useState("");
  const [disciplinaPreferida, setDisciplina] = useState("");
  const porAvaliacao = dados.avaliacoes.filter((linha) => linha.avaliacao === tipo);
  const edicoes = Array.from(new Set(porAvaliacao.map((linha) => linha.edicao))).sort((a, b) => b - a);
  const edicao = edicaoPreferida !== null && edicoes.includes(edicaoPreferida) ? edicaoPreferida : edicoes[0];
  const porEdicao = porAvaliacao.filter((linha) => linha.edicao === edicao);
  const series = Array.from(new Set(porEdicao.map((linha) => linha.serie)));
  const serie = series.includes(seriePreferida) ? seriePreferida : series[0] ?? "";
  const porSerie = porEdicao.filter((linha) => linha.serie === serie);
  const disciplinas = Array.from(new Set(porSerie.map((linha) => linha.disciplina)));
  const disciplina = disciplinas.includes(disciplinaPreferida) ? disciplinaPreferida : disciplinas[0] ?? "";
  const resultados = new Map(porSerie.filter((linha) => linha.disciplina === disciplina)
    .map((linha) => [linha.escola_id, linha.resultado]));

  return (
    <section aria-labelledby="demo-caragua-avaliacoes">
      <Card className="space-y-4 p-4 sm:p-6">
        <h2 className={TITULO_SECAO} id="demo-caragua-avaliacoes">
          <ClipboardCheck size={20} aria-hidden className="text-indigo-500" /> Avaliações externas
        </h2>
        <p className={"text-sm " + CINZA}>Resultados fictícios. Compare escolas na mesma avaliação, edição, série e disciplina. SARESP e SAEB têm escalas próprias.</p>
        <fieldset className="flex flex-wrap gap-3">
          <legend className="sr-only">Filtrar resultados da avaliação</legend>
          <div className="min-w-0">
            <label htmlFor="demo-caragua-filtro-avaliacao" className="text-sm font-medium">Avaliação</label>
            <select id="demo-caragua-filtro-avaliacao" className={"mt-1 block " + estiloInput} value={tipo}
                    onChange={(event) => {
                      setTipo(event.target.value as AvaliacaoDemo["avaliacao"]);
                      setEdicao(null);
                      setSerie("");
                      setDisciplina("");
                    }}>
              <option value="SARESP">SARESP</option>
              <option value="SAEB">SAEB</option>
            </select>
          </div>
          <div className="min-w-0">
            <label htmlFor="demo-caragua-filtro-edicao" className="text-sm font-medium">Edição</label>
            <select id="demo-caragua-filtro-edicao" className={"mt-1 block " + estiloInput} value={edicao ?? ""} disabled={!edicoes.length}
                    onChange={(event) => {
                      setEdicao(Number(event.target.value));
                      setSerie("");
                      setDisciplina("");
                    }}>
              {!edicoes.length && <option value="">Sem edição</option>}
              {edicoes.map((ano) => <option key={ano} value={ano}>{ano}</option>)}
            </select>
          </div>
          <div className="min-w-0">
            <label htmlFor="demo-caragua-filtro-serie" className="text-sm font-medium">Série</label>
            <select id="demo-caragua-filtro-serie" className={"mt-1 block " + estiloInput} value={serie} disabled={!series.length}
                    onChange={(event) => {
                      setSerie(event.target.value);
                      setDisciplina("");
                    }}>
              {!series.length && <option value="">Sem série</option>}
              {series.map((nome) => <option key={nome}>{nome}</option>)}
            </select>
          </div>
          <div className="min-w-0">
            <label htmlFor="demo-caragua-filtro-disciplina" className="text-sm font-medium">Disciplina</label>
            <select id="demo-caragua-filtro-disciplina" className={"mt-1 block " + estiloInput} value={disciplina} disabled={!disciplinas.length}
                    onChange={(event) => setDisciplina(event.target.value)}>
              {!disciplinas.length && <option value="">Sem disciplina</option>}
              {disciplinas.map((nome) => <option key={nome}>{nome}</option>)}
            </select>
          </div>
        </fieldset>
        {resultados.size === 0 ? (
          <p className={"text-sm " + CINZA}>Sem resultados neste recorte.</p>
        ) : (
          <TabelaRolavel rotulo={"Resultados fictícios de " + tipo}>
            <table className={tabela}>
              <caption className="sr-only">Resultados fictícios de {tipo}</caption>
              <thead className={divisoria}>
                <tr>
                  <th scope="col" className={celula}>Escola</th>
                  <th scope="col" className={celula}>Resultado · {tipo}</th>
                </tr>
              </thead>
              <tbody>
                {dados.escolas.map((escola) => (
                  <tr key={escola.id} className={divisoria + " last:border-0"}>
                    <th scope="row" className={celula + " font-medium"}>{escola.nome}</th>
                    <td className={celula}>{resultadoDemo(resultados.get(escola.id) ?? null)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>
    </section>
  );
}

function Demonstracao({ dados }: { dados: DadosDemoCaragua }) {
  const [regiaoId, setRegiao] = useState<RegiaoId | null>(null);
  const [escolaId, setEscola] = useState<string | null>(null);
  const [marcadas, setMarcadas] = useState<string[]>([]);
  const regiao = dados.regioes.find((item) => item.id === regiaoId);
  const escola = dados.escolas.find((item) => item.id === escolaId);
  const daRegiao = regiao ? dados.escolas.filter((item) => item.regiao === regiao.id) : dados.escolas;
  const selecionadas = dados.escolas.filter((item) => marcadas.includes(item.id));

  const escolherRegiao = useCallback((id: RegiaoId | null) => {
    setRegiao(id);
    setEscola(null);
  }, []);

  function escolherEscola(id: string) {
    const escolhida = dados.escolas.find((item) => item.id === id);
    if (escolhida) {
      setRegiao(escolhida.regiao);
      setEscola(id);
    }
  }

  function alternarComparacao(id: string) {
    setMarcadas((ids) => {
      if (ids.includes(id)) return ids.filter((item) => item !== id);
      return ids.length < LIMITE_COMPARACAO ? [...ids, id] : ids;
    });
  }

  return (
    <>
      <div className="grid min-w-0 grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1.8fr)_minmax(18rem,1fr)]">
        <MapaDemoCaragua escolas={dados.escolas} regiao={regiaoId} escola={escolaId}
            escolherRegiao={escolherRegiao} escolherEscola={escolherEscola} />
        <Card className="min-w-0 space-y-4 p-4">
          <div>
            <h2 className={TITULO_SECAO}>{escola?.nome ?? regiao?.nome ?? "Município inteiro"}</h2>
            <p className={"mt-1 text-xs " + CINZA}>
              {escola ? "Escola fictícia · " + regiao?.nome : "Média das escolas com nota"}
            </p>
          </div>
          <Metricas escolas={escola ? [escola] : daRegiao} />
          {regiao && (
            <div className="space-y-1 rounded-xl border border-zinc-200 p-3 dark:border-zinc-700">
              <h3 className="text-sm font-semibold">Contexto simulado da região</h3>
              <p className={"break-words text-sm " + CINZA}>{regiao.contexto}</p>
            </div>
          )}
          <fieldset>
            <legend className="mb-2 text-sm font-semibold">Filtrar região</legend>
            <div className="flex flex-wrap gap-2">
              <Botao type="button" variante="secundario" tamanho="sm" aria-pressed={regiaoId === null}
                     onClick={() => escolherRegiao(null)}>Todas</Botao>
              {dados.regioes.map((item) => (
                <Botao key={item.id} type="button" variante={regiaoId === item.id ? "primario" : "secundario"}
                       tamanho="sm" aria-pressed={regiaoId === item.id} onClick={() => escolherRegiao(item.id)}>
                  {item.nome}
                </Botao>
              ))}
            </div>
          </fieldset>
          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Escolas fictícias ({daRegiao.length})</h3>
              {marcadas.length >= 2 && (
                <a href="#comparacao-escolas-demo" className={CLASSE_LINK_ACAO}>Ver comparação ({marcadas.length})</a>
              )}
            </div>
            <ul className="max-h-48 divide-y divide-zinc-200 overflow-y-auto dark:divide-zinc-700">
              {daRegiao.map((item) => (
                <li key={item.id} className="flex min-w-0 items-center justify-between gap-2 py-1">
                  <button type="button" aria-pressed={escolaId === item.id} onClick={() => escolherEscola(item.id)}
                          className="min-h-10 min-w-0 flex-1 break-words rounded px-1 text-left text-sm font-semibold text-indigo-700 hover:underline dark:text-indigo-300">
                    {item.nome}
                  </button>
                  <label className="flex min-h-10 shrink-0 cursor-pointer items-center gap-1 text-xs">
                    <input type="checkbox" checked={marcadas.includes(item.id)} onChange={() => alternarComparacao(item.id)}
                           disabled={marcadas.length >= LIMITE_COMPARACAO && !marcadas.includes(item.id)}
                           aria-label={"Comparar " + item.nome} className="size-4 accent-indigo-600" />
                    Comparar
                  </label>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      </div>
      <Comparacao escolas={selecionadas} limpar={() => setMarcadas([])} />
      <Avaliacoes dados={dados} />
    </>
  );
}

export default function DemonstracaoCaragua() {
  const { usuario } = useApp();
  const redeId = usuario?.rede_id ?? null;
  const { dados, erro, carregando, recarregar } = useApi<DadosDemoCaragua>(
    redeId === null ? null : "/redes/" + redeId + "/demonstracao-caragua",
  );
  return (
    <div className="min-w-0 space-y-5">
      <Link to="/" className={CLASSE_LINK_ACAO}>
        <ArrowLeft size={16} aria-hidden /> Voltar ao Panorama da Rede
      </Link>
      <PageHeader
        titulo="Mapa de Caraguatatuba"
        descricao="Demonstração da Secretaria com escolas, indicadores e avaliações fictícios. Os recortes regionais foram definidos para a simulação."
        acoes={<span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-100 px-3 py-1 text-sm font-medium text-indigo-800 dark:bg-indigo-500/20 dark:text-indigo-200">
          <MapPinned size={16} aria-hidden /> Simulação
        </span>}
      />
      {carregando && <Carregando texto="Carregando a demonstração..." />}
      {erro && <Erro titulo="Não foi possível abrir a demonstração" descricao={erro.message} aoTentar={recarregar} />}
      {dados && !erro && <Demonstracao key={redeId} dados={dados} />}
    </div>
  );
}
