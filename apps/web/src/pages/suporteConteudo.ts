/**
 * Texto da página Suporte. Cada resposta descreve o comportamento DESTA versão
 * do sistema (nomes de tela e de botão como aparecem no menu e nas telas) —
 * nada de regra que o código não aplica. Ao mudar uma tela, revise aqui.
 */
export interface Pergunta {
  pergunta: string;
  resposta: string;
}

/** "Os dados estão atualizados?" — os estados da tela Integrações
 *  (components/StatusIntegracao.tsx) e o que a coordenação faz em cada um. */
export const SINCRONIZACAO_GESTAO: Pergunta[] = [
  {
    pergunta: "Onde vejo se os dados chegaram?",
    resposta: "Em Plataformas › Integrações. Cada plataforma mostra um selo com a situação, a data da última sincronização e uma frase dizendo o que fazer. O botão “Atualizar” só recarrega a tela; para buscar dados nas plataformas, use “Sincronizar agora”.",
  },
  {
    pergunta: "Funcionando",
    resposta: "A última sincronização terminou bem. Confira também “Próxima”: se disser “manual”, os dados só chegam quando alguém clica em “Sincronizar agora”.",
  },
  {
    pergunta: "Sem dados ainda / Ainda não configurada / Conexão não validada",
    resposta: "Sem acesso salvo, abra “Configurar conexão”, informe usuário e senha da escola e clique em “Salvar e validar”; acesso salvo e não testado pede “Testar conexão”. Com a conexão pronta e nenhuma sincronização feita, clique em “Sincronizar” no cartão da plataforma.",
  },
  {
    pergunta: "Dados desatualizados",
    resposta: "Com a agenda automática ligada, não houve sincronização bem-sucedida no prazo dela (a frase mostra desde quando). Confira a conexão e a agenda em “Configurar conexão” e use “Sincronizar agora”.",
  },
  {
    pergunta: "Falhou",
    resposta: "Se a plataforma recusou ou expirou a senha, corrija em “Configurar conexão”. Nos outros casos, sincronize de novo; se continuar, copie o detalhe técnico da falha para o suporte ou envie o relatório manualmente.",
  },
  {
    pergunta: "O aluno não aparece, ou a conta dele não foi ligada",
    resposta: "Quando a plataforma manda um nome que o Constela não consegue ligar com segurança a um aluno da escola, a linha vai para Plataformas › Revisões de identidade. Os casos claros são ligados sozinhos; os que ficam lá pedem a sua escolha, e a escolha vale para as próximas sincronizações.",
  },
];

/** Para quem não opera as integrações (professor, Secretaria). */
export const SINCRONIZACAO_LEITURA: Pergunta[] = [
  {
    pergunta: "Os números parecem parados ou um aluno está sem dado",
    resposta: "Os dados das plataformas chegam pelas integrações da escola, que a coordenação acompanha na tela Integrações. Avise a coordenação com o nome da turma e da plataforma; se lá aparecer “Dados desatualizados” ou “Falhou”, ela sincroniza de novo ou fala com o suporte.",
  },
];

export const FAQ_COORDENACAO: Pergunta[] = [
  {
    pergunta: "Os números parecem velhos. O que faço?",
    resposta: "Abra Plataformas › Integrações e veja a situação e a data da última sincronização de cada plataforma. Para buscar dados novos, clique em “Sincronizar agora” (todas) ou no botão de sincronizar do cartão da plataforma; a tela se atualiza sozinha enquanto sincroniza.",
  },
  {
    pergunta: "Por que aparece “—” no lugar da nota?",
    resposta: "“—” quer dizer que o aluno não tem dado daquela plataforma: não é nota zero. Ele fica fora da classificação e da média daquela matéria e aparece em “Ainda não aferidos”, nas abas Leitura e Matemática do Ranking Geral. O 0 aparece só para quem já usa a plataforma e ainda não produziu.",
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
    resposta: "A tela diz o motivo: aluno arquivado, transferido ou fora da Lista Piloto, turma de Educação Infantil, ficha ainda não confirmada pela Lista Piloto ou, no certificado “Geral”, aluno ainda sem nota. Para confirmar a ficha, use Plataformas › Integrações › “Atualizar Lista Piloto”, ou funda a ficha repetida em Minha Escola › Alunos › “Fundir duplicatas”.",
  },
  {
    pergunta: "Como premio um bimestre que já terminou?",
    resposta: "Em Desempenho › Premiações, escolha o bimestre pelo número (por exemplo, “3º bimestre”): “Este bimestre” e “Bimestre passado” mudam de datas quando o bimestre vira. Só concorrem alunos do 1º ao 5º ano; as turmas de Educação Infantil ficam fora das premiações e dos certificados.",
  },
  {
    pergunta: "Um número do Matific ou do Elefante parece errado.",
    resposta: "Não corrija à mão pelos ícones de edição das telas Matific e Elefante Letrado: sincronize de novo em Plataformas › Integrações. Se continuar, procure o suporte informando a tela, o aluno e o número.",
  },
  {
    pergunta: "Releitura conta pontos?",
    resposta: "Não: cada livro conta uma vez. A releitura aparece em Relatórios, aba “Por período”, no cartão “Livros com atividade”.",
  },
  {
    pergunta: "Posso mostrar o nome completo dos alunos no telão?",
    resposta: "A recomendação é não. Em Relatórios › Painel Público, mantenha marcado “Proteger o nome dos alunos no telão”: aparecem só o primeiro nome e a inicial do sobrenome. Desligar exibe o nome completo num endereço sem senha — só com o consentimento dos responsáveis.",
  },
  {
    pergunta: "Onde mudo a cor da escola, o brasão ou o nome da escola?",
    resposta: "Cor, brasão da cidade, logo da prefeitura e dados cadastrais da escola são da administração (o administrador da escola ou do Constela): peça a ela. As medalhas da escola você mesma edita em Gamificação › Editar conquistas.",
  },
  {
    pergunta: "Como a pontuação é calculada?",
    resposta: "Veja “Como a nota é calculada”, nesta página: os pesos e a régua vêm do próprio sistema e o exemplo mostra a conta feita pelo servidor. A mesma explicação fica em Configurações › Pontuação; só a administração do Constela altera a régua.",
  },
  {
    pergunta: "Dá para usar no celular?",
    resposta: "Sim, pelo navegador, no mesmo endereço. Em tela pequena, o menu abre pelo botão de três linhas no canto superior esquerdo; a pesquisa do topo e algumas colunas só aparecem em telas maiores.",
  },
];

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

export const FAQ_SECRETARIA: Pergunta[] = [
  {
    pergunta: "Por que uma escola não aparece no Ranking da Rede?",
    resposta: "O ranking só lista escolas com pelo menos um aluno com dado das plataformas. Uma escola sem dado aparece no Panorama, em “Escolas que precisam de atenção”, com o motivo.",
  },
  {
    pergunta: "A nota de 0 a 100 da escola é alta, mas o índice é baixo. Qual vale?",
    resposta: "Os dois, para perguntas diferentes. O Índice (0 a 1000) compara as escolas por aluno e ordena o ranking; a nota de 0 a 100 compara cada aluno com os colegas da própria escola e serve para acompanhar a escola no tempo.",
  },
  {
    pergunta: "Consigo ver a lista de alunos de uma escola?",
    resposta: "Não: a conta da Secretaria mostra só números por escola, nunca dados individuais de crianças. Por isso a pesquisa do topo não encontra alunos nem turmas.",
  },
  {
    pergunta: "O Panorama está mostrando uma escola só. Como volto para a rede?",
    resposta: "Escolha “Toda a Rede Municipal” no seletor do topo, ou clique em “‹ Toda a Rede Municipal”, acima do título.",
  },
  {
    pergunta: "Os números de uma escola parecem parados.",
    resposta: "A tela que mostra se os dados estão atualizados (Integrações) é da escola, e a Secretaria não a abre. Pergunte à coordenação o que ela mostra; se aparecer “Dados desatualizados” ou “Falhou”, a coordenação sincroniza de novo ou fala com o suporte.",
  },
];
