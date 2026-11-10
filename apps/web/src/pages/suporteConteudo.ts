/**
 * Texto da página Suporte. Cada resposta descreve o comportamento DESTA versão
 * do sistema (nomes de tela e de botão como aparecem no menu e nas telas) —
 * nada de regra que o código não aplica. Ao mudar uma tela, revise aqui.
 *
 * Caminhos do menu ("Dados e integrações › Integrações") seguem a TRILHA do topo:
 * o grupo (acordeão) do item ou, se o item é solto, a seção — e são escritos para
 * o menu da coordenação (o mesmo da administração da escola, salvo Configurações
 * Gerais); `caminhosDoMenu` os traduz para o Admin Global (components/Layout.tsx,
 * `gruposDoPerfil`). O FAQ da Secretaria usa as três áreas do menu dela (Panorama da Rede,
 * Escolas e Avaliações externas).
 */
import { rotuloDasPlataformas } from "../hooks/useModulos";

export interface Pergunta {
  pergunta: string;
  resposta: string;
}

/** "Os dados estão atualizados?" — os estados da tela Integrações
 *  (components/StatusIntegracao.tsx) e o que a coordenação faz em cada um. */
export const SINCRONIZACAO_GESTAO: Pergunta[] = [
  {
    pergunta: "Onde vejo se os dados chegaram?",
    resposta: "Em Dados e integrações › Integrações. Cada plataforma mostra um selo com a situação, a data da última sincronização e uma frase dizendo o que fazer. O botão “Atualizar” só recarrega a tela; para buscar dados nas plataformas, use “Sincronizar agora”.",
  },
  {
    pergunta: "Atualizado",
    resposta: "O último sucesso está dentro do prazo e os dados desta plataforma estão em dia; o cartão mostra quando foi o último sucesso e, à parte, a última tentativa. Confira também “Próxima”: se disser “manual”, os dados só chegam quando alguém clica em “Sincronizar agora”.",
  },
  {
    pergunta: "Sem dados ainda / Ainda não configurada / Conexão não validada",
    resposta: "Sem acesso salvo, abra “Configurar conexão”, informe usuário e senha da escola e clique em “Salvar e validar”. “Conexão não validada” quer dizer que o acesso foi salvo, mas o teste não foi feito ou não terminou (a plataforma não confirmou o login): use “Testar conexão” mais tarde. Com a conexão pronta e nenhuma sincronização feita, clique em “Sincronizar” no cartão da plataforma.",
  },
  {
    pergunta: "Sem dados na última coleta",
    resposta: "A última sincronização terminou sem trazer dados (relatório vazio ou incompleto) — isso não conta como sucesso. Confira na plataforma se as turmas têm atividade; se continuar, envie o relatório manualmente.",
  },
  {
    pergunta: "Sem atualização: nenhuma conta da escola reconhecida",
    resposta: "A plataforma mandou dados, mas nenhuma conta já ligada a um aluno da escola veio na coleta: todas as linhas ficaram em Dados e integrações › Revisões de identidade. Isso não conta como dado em dia — passado o prazo da agenda, aparece “Dados desatualizados”. Se a escola já tinha alunos ligados, confira primeiro em “Configurar conexão” se o acesso cadastrado é o desta escola (o acesso de outra escola dá exatamente isso) e não resolva as revisões antes. Se é a primeira coleta, confirme que os nomes são desta escola e resolva as revisões.",
  },
  {
    pergunta: "Dados desatualizados",
    resposta: "Não há sincronização bem-sucedida recente (o selo mostra há quanto tempo; a frase, desde quando). Se a frase disser que a atualização automática está “pausada no servidor”, os dados só chegam quando alguém clica em “Sincronizar”. Confira a conexão e a agenda em “Configurar conexão” e use “Sincronizar agora”.",
  },
  {
    pergunta: "Falhou",
    resposta: "O selo diz o tipo da falha. Senha recusada ou expirada: corrija em “Configurar conexão”. Plataforma fora do ar ou bloqueando o acesso: tente mais tarde ou envie o relatório manualmente. Erro ao processar: sincronize de novo; se continuar, copie o detalhe técnico da falha para o suporte.",
  },
  {
    pergunta: "Coleta indisponível neste servidor",
    resposta: "O servidor não consegue abrir a plataforma para coletar (por exemplo, o navegador automático não está disponível). Não é problema da senha da escola: envie o relatório manualmente e avise o suporte.",
  },
  {
    pergunta: "O aluno não aparece, ou a conta dele não foi ligada",
    resposta: "Os casos claros são ligados sozinhos. Quando há dúvida (dois alunos parecidos, nome que só casa em outra turma, duas contas para a mesma ficha), a linha vai para Dados e integrações › Revisões de identidade; escolhida a ficha, as próximas sincronizações já ligam aquela conta sozinhas — uma linha descartada volta se a plataforma mandá-la de novo. Se a escola permite que a sincronização crie fichas, um nome sem nenhum candidato vira ficha nova: junte-a à certa em Minha Escola › Alunos › “Fundir duplicatas”.",
  },
];

/** Para quem não opera as integrações (professor, Secretaria). */
export const SINCRONIZACAO_LEITURA: Pergunta[] = [
  {
    pergunta: "Os números parecem parados ou um aluno está sem dado",
    resposta: "Os dados das plataformas chegam pelas integrações da escola, que a coordenação acompanha na tela Integrações. Avise a coordenação com o nome da turma e da plataforma; se lá aparecer “Dados desatualizados” ou “Falhou”, ela sincroniza de novo ou fala com o suporte.",
  },
];

const FAQ_GESTAO_BASE: Pergunta[] = [
  {
    pergunta: "Os números parecem velhos. O que faço?",
    resposta: "Abra Dados e integrações › Integrações e veja a situação e a data da última sincronização de cada plataforma. Para buscar dados novos, clique em “Sincronizar agora” (todas) ou no botão de sincronizar do cartão da plataforma; a tela se atualiza sozinha enquanto sincroniza.",
  },
  {
    pergunta: "Por que aparece “—” no lugar da nota?",
    resposta: "“—” quer dizer que o aluno não tem dado daquela plataforma: não é nota zero. Ele fica fora da classificação e da média daquela matéria e aparece em “Ainda não aferidos”, nas abas Leitura e Matemática do Ranking Geral; nessas abas, o 0 aparece só para quem já usa a plataforma e ainda não produziu. Na coluna Geral, quem não tem dado de nenhuma plataforma aparece com 0,0.",
  },
  {
    pergunta: "O professor diz que não vê os alunos dele.",
    resposta: "Em Minha Escola › Usuários, use os três pontinhos na linha dele › “Vincular turmas”, marque as turmas e clique em “Salvar turmas”: o professor só vê os alunos das turmas vinculadas. Se ele nem aparece em Usuários, crie o acesso em Minha Escola › Professores › “Adicionar professor”, com “Criar conta de acesso” marcado.",
  },
  {
    pergunta: "O professor esqueceu a senha ou vai entrar pela primeira vez.",
    resposta: "Em Minha Escola › Usuários, use os três pontinhos › “Redefinir senha” › “Gerar link de redefinição” › “Copiar”, e entregue o link junto com o nome de usuário dele. O link vale uma única vez e expira no prazo que a tela mostra; gerar outro invalida o anterior.",
  },
  {
    pergunta: "Eu esqueci a minha senha.",
    resposta: "A tela de entrada não tem “Esqueci minha senha”: peça um link de redefinição à administração do Constela. Se você ainda está conectada, gere o link para você mesma em Minha Escola › Usuários, na linha marcada “(você)”.",
  },
  {
    pergunta: "Um aluno aparece duas vezes.",
    resposta: "Confirme com a secretaria da escola que é a mesma criança. Depois use Minha Escola › Alunos › “Fundir duplicatas”, ou os três pontinhos do aluno › “Fundir com outro aluno”, e digite FUNDIR para confirmar — a fusão não pode ser desfeita.",
  },
  {
    pergunta: "Um aluno saiu da escola.",
    resposta: "Nos três pontinhos do aluno, use “Marcar como transferido”: ele sai das listas e dos rankings, o histórico fica guardado e uma nova Lista Piloto não o traz de volta sozinha. Se a criança voltar, abra a turma em Minha Escola › Turmas, marque “Mostrar arquivados” e use “Reativar”.",
  },
  {
    pergunta: "O certificado de um aluno não sai.",
    resposta: "A tela diz o motivo: aluno arquivado, transferido ou fora da Lista Piloto, turma de Educação Infantil, ficha ainda não confirmada pela Lista Piloto ou, no certificado “Geral”, aluno ainda sem nota. Para confirmar a ficha, importe ou atualize a Lista Piloto em Dados e integrações › Integrações (botão “Importar Lista Piloto” ou “Atualizar Lista Piloto”), ou funda a ficha repetida em Minha Escola › Alunos › “Fundir duplicatas”.",
  },
  {
    pergunta: "Como premio um bimestre que já terminou?",
    resposta: "Em Reconhecimento › Premiações, escolha o bimestre pelo número (por exemplo, “3º bimestre”): “Este bimestre” e “Bimestre passado” mudam de datas quando o bimestre vira. Só concorrem alunos do 1º ao 5º ano; as turmas de Educação Infantil ficam fora das premiações e dos certificados.",
  },
  {
    pergunta: "Um número do Matific ou do Elefante parece errado.",
    resposta: "Não corrija à mão pelos ícones de edição das telas Matific e Elefante Letrado: sincronize de novo em Dados e integrações › Integrações. Se continuar, procure o suporte informando a tela, o aluno e o número.",
  },
  {
    pergunta: "Releitura conta pontos?",
    resposta: "Não: cada livro conta uma vez. A releitura aparece em Relatórios, aba “Por período”, no cartão “Livros com atividade”.",
  },
  {
    pergunta: "Posso mostrar o nome completo dos alunos no telão?",
    resposta: "A recomendação é não. Em Reconhecimento › Painel Público, mantenha marcado “Proteger o nome dos alunos no telão”: aparecem só o primeiro nome e a inicial do sobrenome. Desligar exibe o nome completo num endereço sem senha — só com o consentimento dos responsáveis.",
  },
  {
    pergunta: "Onde mudo a cor da escola, o brasão ou o nome da escola?",
    resposta: "Cor, brasão da cidade, logo da prefeitura e dados cadastrais da escola são da administração (o administrador da escola ou do Constela): peça a ela. As medalhas da escola você mesma edita em Regras de pontuação › Editar conquistas.",
  },
  {
    pergunta: "Como a pontuação é calculada?",
    resposta: "Veja “Como a nota é calculada”, nesta página: os pesos e a régua vêm do próprio sistema e o exemplo mostra a conta feita pelo servidor. A mesma explicação fica em Regras de pontuação › Critérios; só a administração do Constela altera a régua.",
  },
  {
    pergunta: "Dá para usar no celular?",
    resposta: "Sim, pelo navegador, no mesmo endereço. Em tela pequena, o menu abre pelo botão de três linhas no canto superior esquerdo e a pesquisa continua no topo; a linha do topo que mostra em que página você está e algumas colunas das tabelas só aparecem em telas maiores.",
  },
];

const CONFIG_INSTITUCIONAL = "Onde mudo a cor da escola, o brasão ou o nome da escola?";
const PONTUACAO = "Como a pontuação é calculada?";

interface PerfilDaGestao { admin: boolean; global: boolean }

/** Os caminhos do texto-base (o menu da COORDENAÇÃO) no menu de quem lê:
 *  - admin da escola: os mesmos — Usuários também mora em "Minha Escola"; só
 *    Configurações Gerais (solto na seção Gestão) é dele, e entra pelas `trocas`;
 *  - Admin Global: Usuários é solto na seção "Administração", Integrações e Revisões
 *    ficam em "Integrações e dados" e Alunos/Turmas/Professores em "Gestão escolar" (não
 *    há "Minha Escola"). Reconhecimento é igual nos três.
 *  A ordem das trocas do global importa: "Minha Escola › Usuários" vira Administração
 *  ANTES de o resto de "Minha Escola ›" virar "Gestão escolar ›". */
function caminhosDoMenu(texto: string, { global }: PerfilDaGestao): string {
  if (global) {
    return texto
      .split("Minha Escola › Usuários").join("Administração › Usuários")
      .split("Dados e integrações ›").join("Integrações e dados ›")
      .split("Minha Escola ›").join("Gestão escolar ›")
      .replace("peça um link de redefinição à administração do Constela", "peça um link de redefinição a outro administrador do Constela");
  }
  return texto;
}

/** O FAQ da gestão com os caminhos do MENU de quem lê: a coordenação não tem
 *  Configurações Gerais (edita as medalhas por "Regras de pontuação"); o admin da
 *  escola tem (solto em "Gestão"); o Admin Global também (no grupo "Configurações"). */
export function faqDaGestao({ admin, global }: PerfilDaGestao): Pergunta[] {
  const trocas: Record<string, string> = {};
  if (global) {
    trocas[CONFIG_INSTITUCIONAL] = "Em Configurações › Configurações Gerais, com a escola escolhida no cartão Escola, no fim do menu lateral: cor, brasão da cidade, logo da prefeitura e dados da escola. As medalhas ficam no cartão “Conquistas” da mesma tela.";
    trocas[PONTUACAO] = "Veja “Como a nota é calculada”, nesta página: os pesos e a régua vêm do próprio sistema e o exemplo mostra a conta feita pelo servidor. Os parâmetros ficam em Configurações › Critérios.";
  } else if (admin) {
    trocas[CONFIG_INSTITUCIONAL] = "Em Gestão › Configurações Gerais: cor, brasão da cidade, logo da prefeitura e dados da escola. As medalhas ficam no cartão “Conquistas” da mesma tela.";
  }
  return FAQ_GESTAO_BASE.map((p) => ({
    ...p,
    resposta: caminhosDoMenu(trocas[p.pergunta] ?? p.resposta, { admin, global }),
  }));
}

/** "Os dados estão atualizados?" com os caminhos do menu de quem lê (coordenação,
 *  admin da escola ou Admin Global). */
export function sincronizacaoDaGestao(perfil: PerfilDaGestao): Pergunta[] {
  return SINCRONIZACAO_GESTAO.map((p) => ({ ...p, resposta: caminhosDoMenu(p.resposta, perfil) }));
}

/** O FAQ da coordenação (o caso mais comum da gestão). */
export const FAQ_COORDENACAO: Pergunta[] = faqDaGestao({ admin: false, global: false });

export const FAQ_PROFESSOR: Pergunta[] = [
  {
    pergunta: "Esqueci a senha, ou o link não funciona.",
    resposta: "Peça à coordenação um link de redefinição: a tela de entrada não tem “Esqueci minha senha”. O link vale uma única vez e por tempo limitado, e se a coordenação gerar outro, só o mais novo vale.",
  },
  {
    pergunta: "A minha lista de alunos está vazia, ou falta um aluno.",
    resposta: "Meus Alunos mostra só os alunos ativos das turmas vinculadas ao seu cadastro. Peça à coordenação para conferir as suas turmas e o cadastro do aluno; aluno transferido ou arquivado sai da lista.",
  },
  {
    pergunta: "O aluno aparece com “—”.",
    resposta: "Não há dado daquela plataforma para ele: não é nota zero. Se ele já usa a plataforma há dias, avise a coordenação — a conta dele pode ainda não estar ligada à ficha.",
  },
  {
    pergunta: "Mudei o período e a aba Geral do Ranking não mudou.",
    resposta: "A aba Geral é sempre o acumulado do ano letivo; para ver um período, use a aba Evolução ou as Premiações. No Ranking, a posição conta só os alunos das suas turmas.",
  },
  {
    pergunta: "Apareceu “Algo deu errado”.",
    resposta: "Clique em “Recarregar”: os seus dados estão salvos. Se repetir, avise a coordenação dizendo o nome da tela.",
  },
];

/** As plataformas que a rede contratou, para o texto da Secretaria. */
interface PlataformasDaRede { elefante: boolean; matific: boolean }

/** FAQ da Secretaria, com as TRÊS áreas do MENU dela (Layout.tsx, seção Rede municipal:
 *  Panorama da Rede, Escolas e Avaliações externas — DESENHO3 §1). Linguagem administrativa,
 *  sem termo estatístico, e nada de causa e efeito: o que cada área mostra e de quando são os
 *  números. Cada resposta cita só as plataformas que a rede TEM (`faqDaSecretaria`): numa rede
 *  só com o Matific, nada do Elefante, e vice-versa. */
function perguntasDaSecretaria({ elefante, matific }: PlataformasDaRede): Pergunta[] {
  const duas = elefante && matific;
  const nome = rotuloDasPlataformas([...(elefante ? ["leitura"] : []), ...(matific ? ["matematica"] : [])]);
  // "o Elefante e o Matific" / "o Elefante Letrado" / "o Matific" (e "no", com a preposição).
  const comArtigo = duas ? "o Elefante e o Matific" : `o ${nome}`;
  const comPreposicao = duas ? "no Elefante e no Matific" : `no ${nome}`;
  const uso = [
    // O uso do Elefante conta também a releitura (o mesmo número da participação): "um livro".
    ...(elefante ? ["leu um livro no Elefante"] : []),
    ...(matific ? ["fez uma atividade no Matific"] : []),
  ].join(" ou ");
  const criterio = [
    ...(elefante ? ["Leitura: livros lidos por aluno no Elefante, somados desde o início da conta de cada aluno."] : []),
    ...(matific ? ["Matemática: estrelas por aluno no Matific, no ano letivo."] : []),
  ].join(" ");
  // Quem soma, por plataforma (a regra do servidor vale em cada uma separadamente).
  const quemSoma = [
    ...(elefante ? ["algum livro lido no Elefante"] : []),
    ...(matific ? ["alguma estrela no Matific"] : []),
  ].join("; ");
  return [
    {
      pergunta: "Por onde começo?",
      resposta: "Pelo Panorama da Rede, a página inicial. O menu tem três áreas, na seção Rede municipal: Panorama da Rede (como a rede usa o Constela e as escolas em destaque), Escolas (todas as escolas, a comparação lado a lado e a ficha de cada uma) e Avaliações externas (os indicadores oficiais). No teclado, Alt+1, Alt+2 e Alt+3 abrem cada uma.",
    },
    {
      pergunta: "O que o Panorama da Rede mostra?",
      resposta: `Primeiro, a rede no Constela: quantas escolas estão cadastradas, quantas estão ativas no cadastro e quantas tiveram uso no ano letivo. Depois, a participação dos alunos ${comPreposicao} no ano letivo, todas as escolas da rede com a situação de uso de cada uma, as escolas em destaque, o reconhecimento público (a vitrine) e as metas da rede. Cada número diz o que mede e de quando é; as avaliações externas ficam na área delas.`,
    },
    {
      pergunta: "Qual a diferença entre escola cadastrada, ativa e com uso?",
      resposta: `Não são a mesma coisa. Cadastrada: a escola está vinculada à rede no Constela. Ativa: a situação do cadastro está ativa — isso não diz se a escola usa as plataformas. Com uso no ano letivo: pelo menos um aluno do 1º ao 5º ano ${uso} no ano letivo, pelas coletas. “Sem uso registrado”: a coleta está em dia e não registrou uso (com a coleta parcial, a tela diz até que data vale). “Sem dado”: não há como saber (sem coleta, sem contas ou sem alunos do 1º ao 5º ano). “Protegida”: a escola tem poucos alunos e os números ficam escondidos para proteger as crianças. Sem dado nunca é zero.`,
    },
    {
      pergunta: "Como as escolas em destaque são escolhidas?",
      resposta: `Pelo mesmo critério da vitrine pública, calculado pelo Constela. ${criterio} Entram só escolas ativas, com pelo menos 5 alunos do 1º ao 5º ano e${duas ? ", em cada plataforma," : ""} pelo menos 5 deles com resultado (${quemSoma}); aparecem as 5 maiores${duas ? " de cada plataforma" : ""}. Escola com grupo muito pequeno fica de fora para proteger as crianças, e a tela diz quantas ficaram. Destaque mostra o uso da plataforma: não é nota oficial nem avaliação de aprendizagem.`,
    },
    {
      pergunta: "Onde ligo a vitrine pública da rede?",
      resposta: "No Panorama da Rede, em “Reconhecimento público”: ligar ou desligar, copiar o link e abrir a vitrine. A vitrine usa o mesmo critério das escolas em destaque; a lista do Panorama pode ter menos escolas, porque a escola com o número protegido (poucos alunos) fica de fora dela. O painel público de cada escola é ligado pela coordenação da escola.",
    },
    {
      pergunta: "Como comparo as escolas?",
      resposta: `Em Escolas: todas as escolas da rede, em ordem alfabética (não é ranking), com ${comArtigo} no período escolhido. Marque de 2 a 4 escolas em “Comparar” para vê-las lado a lado, com as avaliações externas de cada uma, quando houver: em cada avaliação vale a edição mais recente entre as escolas marcadas, e a escola cujo último resultado é de uma edição anterior aparece com o ano dele, sem o número (o número fica na ficha). O Ranking da Rede, com link nessa tela, é outra medida: a pontuação que o Constela calcula a partir das plataformas.`,
    },
    {
      pergunta: "O que tem na ficha da escola?",
      resposta: `Para abrir, clique no nome da escola (em Escolas ou no Panorama da Rede) ou escolha a escola no cartão Contexto, no fim do menu lateral (em qualquer tela fora do Suporte). A ficha mostra a situação do cadastro, o número de alunos, turmas e professores do ano letivo, a situação de uso, ${comArtigo} no período, a evolução por bimestre e as avaliações externas da escola — quando não há resultado oficial, ela diz por quê. “Ver as turmas da escola” abre os números por turma.`,
    },
    {
      pergunta: "Escolhi uma escola no cartão Contexto. O Panorama muda?",
      resposta: "Não: o Panorama da Rede mostra sempre a rede inteira. Escolher uma escola no cartão Contexto abre a ficha dela (aqui no Suporte, só mostra a regra da nota dela, sem sair da página); escolher “Toda a Rede Municipal” numa tela da escola (como as turmas) volta ao Panorama.",
    },
    {
      pergunta: "Onde vejo o Ideb, o Saeb, o SARESP, o ICA e o IEE?",
      resposta: "Em Avaliações externas. Cada indicador tem um cartão que diz o que ele mede, quem publica, a edição mais recente importada (ou que nenhuma edição foi importada) e a situação da meta. Dá para comparar as edições de cada indicador e as escolas numa mesma edição; “Arquivos oficiais de cada número” mostra a fonte de cada resultado. Cada avaliação tem escala e calendário próprios: compare cada uma com ela mesma.",
    },
    {
      pergunta: `Posso comparar as avaliações oficiais com ${comArtigo}?`,
      resposta: "Não diretamente: as avaliações oficiais são de edições anteriores e as plataformas, do ano letivo atual — são medidas e períodos diferentes. Por isso aparecem separadas, também na comparação e na ficha da escola, e nunca entram na mesma conta. As plataformas mostram quanto e como as crianças as usam; não são avaliação oficial de aprendizagem.",
    },
    ...(elefante ? [{
      pergunta: "De quando são os números do Elefante?",
      resposta: "Depende do número. O uso (participação, livros novos por aluno) vem das coletas do período escolhido — o padrão é o ano letivo. Os destaques, a vitrine e o Ranking da Rede somam os livros lidos desde o início da conta de cada aluno. Cada número diz de quando é.",
    }] : []),
    {
      pergunta: "Por que uma escola não aparece nos destaques ou no Ranking da Rede?",
      resposta: "Os destaques só mostram escolas ativas com alunos suficientes (veja o critério acima), e o Ranking da Rede só lista escolas com pelo menos um aluno com dado das plataformas. A escola continua na lista de todas as escolas, no Panorama da Rede e em Escolas, com a situação de uso por extenso (por exemplo, “Sem dado” ou “Sem uso registrado”).",
    },
    {
      pergunta: "A nota de 0 a 100 da escola é alta, mas o índice é baixo. Qual vale?",
      resposta: "Os dois, para perguntas diferentes. O Índice (0 a 1000) compara as escolas por aluno e ordena o Ranking da Rede. A nota de 0 a 100 mostra como cada aluno está em relação aos colegas da própria escola: não compara escolas e não mede a evolução da escola — se todos os alunos dobrarem a atividade, a média 0 a 100 não muda.",
    },
    {
      pergunta: "Consigo ver a lista de alunos de uma escola?",
      resposta: "Não: a conta da Secretaria mostra só números por escola e por turma, nunca dados individuais de crianças. Por isso a pesquisa do topo não encontra alunos nem turmas.",
    },
    {
      pergunta: "Os números de uma escola parecem parados.",
      resposta: "A tela que mostra se os dados estão atualizados (Integrações) é da escola, e a Secretaria não a abre. Pergunte à coordenação o que ela mostra; se aparecer “Dados desatualizados” ou “Falhou”, a coordenação sincroniza de novo ou fala com o suporte.",
    },
  ];
}

/** O FAQ da Secretaria com as plataformas que a rede TEM — o mesmo nome do h1 da tela delas
 *  (`rotuloDasPlataformas`). Numa rede só com o Matific, o texto citava um produto que a rede
 *  não contratou. Sem módulo nenhum (configuração ausente), as duas — como no menu. */
export function faqDaSecretaria(modulos: string[]): Pergunta[] {
  const leitura = modulos.includes("leitura");
  const matematica = modulos.includes("matematica");
  const nenhum = !leitura && !matematica;
  return perguntasDaSecretaria({ elefante: leitura || nenhum, matific: matematica || nenhum });
}

/** O FAQ de uma rede com as duas plataformas (o caso padrão). */
export const FAQ_SECRETARIA: Pergunta[] = faqDaSecretaria(["leitura", "matematica"]);
