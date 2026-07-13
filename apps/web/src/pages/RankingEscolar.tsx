/**
 * Ranking Escolar — reservado para os DADOS ESCOLARES próprios (projeto em
 * desenvolvimento). Ainda não há fonte de dados conectada; a aba existe para
 * fixar o lugar no produto. Quando a plataforma de ensino própria entrar, esta
 * tela passa a listar o ranking com os mesmos filtros das demais.
 */
import { Card, PageHeader, Vazio } from "../components/ui";

export default function RankingEscolar({ embutido = false }: { embutido?: boolean } = {}) {
  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Ranking Escolar"
          descricao="Ranking com os dados escolares próprios (em construção)."
        />
      )}
      <Card>
        <Vazio
          titulo="Em construção"
          descricao="Aqui vai entrar o ranking dos dados escolares da sua própria plataforma de ensino. Assim que essa fonte for conectada, os alunos aparecem aqui com os mesmos filtros de período e turma."
        />
      </Card>
    </div>
  );
}
