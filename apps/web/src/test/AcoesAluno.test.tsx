/**
 * Arquivar/Reativar um aluno partem direto do menu (sem modal próprio): a falha
 * NÃO pode ser silenciosa. Antes, o erro era setado mas nunca renderizado.
 */
import { vi } from "vitest";

import AcoesAluno from "../components/AcoesAluno";
import { api } from "../lib/__mocks__/api";
import type { Aluno } from "../lib/types";
import { renderComApp, responder, responderErro, screen, userEvent } from "./utils";

const aluno: Aluno = {
  id: 10, nome: "Ana Souza", foto_url: null, numero_chamada: 1,
  status: "ativo", turma: "3º Ano A", ano_escolar: "3º Ano",
  data_nascimento: null, observacoes: null,
};

async function abrirMenuEArquivar() {
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Arquivar"));
}

test("falha ao arquivar aparece para o usuário (não é silenciosa)", async () => {
  responderErro("POST", /\/alunos\/acoes/, 400, "Não foi possível arquivar agora.");
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />);

  await abrirMenuEArquivar();

  expect(await screen.findByText("Não foi possível arquivar agora.")).toBeInTheDocument();
});

test("falha ao REATIVAR (mesmo caminho) também aparece", async () => {
  responderErro("POST", /\/alunos\/acoes/, 400, "Não foi possível reativar agora.");
  renderComApp(
    <AcoesAluno aluno={{ ...aluno, status: "arquivado" }} escolaId={1} aoMudar={vi.fn()} />,
  );
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Reativar"));
  expect(await screen.findByText("Não foi possível reativar agora.")).toBeInTheDocument();
});

test("403 do D10 ao reativar ficha excluída aparece com o motivo", async () => {
  responderErro("POST", /\/alunos\/acoes/, 403,
    "A ficha excluída de “Ana Souza” tem uma conta da plataforma que hoje é a " +
    "identidade de um aluno de OUTRA escola do Constela. […] só o Admin Global decide.");
  const aoMudar = vi.fn();
  renderComApp(
    <AcoesAluno aluno={{ ...aluno, status: "excluido" }} escolaId={1} aoMudar={aoMudar} />,
  );
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Reativar"));
  expect(await screen.findByText(/só o Admin Global decide/)).toBeInTheDocument();
  expect(aoMudar).not.toHaveBeenCalled();
});

const AVISO_D10 = "Atenção: esta conta da plataforma continua vinculada a um aluno de " +
  "outra escola do Constela, que não foi alterada.";

test("reativar com aviso na resposta mostra o aviso até o usuário fechar", async () => {
  responder("POST", /\/alunos\/acoes/,
    { mensagem: "1 aluno(s) reativado(s).", afetados: 1, avisos: [AVISO_D10] });
  const aoMudar = vi.fn();
  renderComApp(
    <AcoesAluno aluno={{ ...aluno, status: "excluido" }} escolaId={1} aoMudar={aoMudar} />,
  );
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Reativar"));

  expect(await screen.findByText(AVISO_D10)).toBeInTheDocument();
  // A tela só recarrega depois do "Entendi": recarregar antes desmontaria este
  // componente (PerfilAluno → <Carregando/>) e o aviso sumiria sem ser lido.
  expect(aoMudar).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Entendi" }));
  expect(screen.queryByText(AVISO_D10)).toBeNull();
  expect(aoMudar).toHaveBeenCalledTimes(1);
});

test("fechar o aviso pelo fundo da janela também avisa a tela uma única vez", async () => {
  responder("POST", /\/alunos\/acoes/,
    { mensagem: "1 aluno(s) reativado(s).", afetados: 1, avisos: [AVISO_D10] });
  const aoMudar = vi.fn();
  renderComApp(
    <AcoesAluno aluno={{ ...aluno, status: "excluido" }} escolaId={1} aoMudar={aoMudar} />,
  );
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Reativar"));

  expect(await screen.findByText(AVISO_D10)).toBeInTheDocument();
  expect(aoMudar).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Fechar janela" }));
  expect(screen.queryByText(AVISO_D10)).toBeNull();
  expect(aoMudar).toHaveBeenCalledTimes(1);
});

test("ação sem aviso não abre a janela de atenção", async () => {
  responder("POST", /\/alunos\/acoes/,
    { mensagem: "1 aluno(s) reativado(s).", afetados: 1, avisos: [] });
  const aoMudar = vi.fn();
  renderComApp(
    <AcoesAluno aluno={{ ...aluno, status: "arquivado" }} escolaId={1} aoMudar={aoMudar} />,
  );
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Reativar"));
  await vi.waitFor(() => expect(aoMudar).toHaveBeenCalled());
  expect(screen.queryByText(/Ação concluída — atenção/)).toBeNull();
});

test("arquivar com sucesso avisa a tela e não mostra erro", async () => {
  responder("POST", /\/alunos\/acoes/, { ok: true });
  const aoMudar = vi.fn();
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={aoMudar} />);

  await abrirMenuEArquivar();

  await vi.waitFor(() => expect(aoMudar).toHaveBeenCalled());
  expect(screen.queryByText(/Não foi possível concluir a ação/i)).toBeNull();
});

// --- Marcar como transferido (saiu da escola) --------------------------------
// O verbo é novo e tem vizinho perigoso: "Transferir de turma" move de sala,
// "Marcar como transferido" tira da escola. Estes testes travam (a) que a ação
// enviada ao backend é a certa e (b) que ela some quando o aluno já está inativo
// — oferecer "marcar transferido" para quem já saiu seria ruído.

test("marcar como transferido envia a ação correta ao backend", async () => {
  responder("POST", /\/alunos\/acoes/, { ok: true });
  const aoMudar = vi.fn();
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={aoMudar} />);

  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Marcar como transferido"));

  await vi.waitFor(() => expect(aoMudar).toHaveBeenCalled());
  const chamada = api.mock.calls.find(
    ([caminho]) => String(caminho) === "/escolas/1/alunos/acoes");
  expect(chamada).toBeDefined();
  expect(JSON.parse(String((chamada![1] as RequestInit).body)))
    .toEqual({ aluno_ids: [10], acao: "marcar_transferido" });
});

test("quem já está fora da escola não recebe a opção de novo", async () => {
  renderComApp(
    <AcoesAluno aluno={{ ...aluno, status: "transferido" }} escolaId={1}
                aoMudar={vi.fn()} />,
  );
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));

  expect(await screen.findByText("Reativar")).toBeInTheDocument();
  expect(screen.queryByText("Marcar como transferido")).toBeNull();
});

// --- Fusão com sinal de conflito de identidade ------------------------------
// A tela de fusão mostra só nome e turma. Quando o backend detecta prova de
// serem crianças diferentes (nascimento/RA divergentes) ele responde 409 e
// NOMEIA a divergência; a tela então revela um segundo campo de confirmação.
// Sem isso, a proteção do backend seria inalcançável pela interface.

test("conflito de identidade revela a segunda confirmação e a envia", async () => {
  responderErro("POST", /\/alunos\/fundir/, 409,
    "Estes dois cadastros têm sinais de serem crianças DIFERENTES: nascimento " +
    "2020-07-31 × 2021-07-31. Se ainda assim for a mesma criança, digite " +
    "“FUNDIR MESMO COM CONFLITO” para confirmar.");
  responder("GET", /\/alunos\?busca=/, {
    itens: [{ id: 20, nome: "Ana Souza Duplicada", status: "ativo", turma: "3º Ano A" }],
    total: 1, pagina: 1, por_pagina: 8,
  });
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />);

  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Fundir com outro aluno"));
  await userEvent.type(screen.getByPlaceholderText(/Buscar o cadastro duplicado/), "Ana");
  await userEvent.click(await screen.findByRole("button", { name: /Ana Souza Duplicada/ }));
  await userEvent.type(screen.getByPlaceholderText("FUNDIR"), "FUNDIR");
  await userEvent.click(screen.getByRole("button", { name: /Fundir cadastros/ }));

  // a divergência aparece nomeada, e o campo extra surge
  expect(await screen.findByText(/nascimento 2020-07-31 × 2021-07-31/)).toBeInTheDocument();
  const extra = await screen.findByPlaceholderText("FUNDIR MESMO COM CONFLITO");
  expect(extra).toBeInTheDocument();

  // e é enviado no corpo da segunda tentativa
  responder("POST", /\/alunos\/fundir/, { ok: true });
  await userEvent.type(extra, "FUNDIR MESMO COM CONFLITO");
  await userEvent.click(screen.getByRole("button", { name: /Fundir cadastros/ }));
  await vi.waitFor(() => {
    const chamadas = api.mock.calls.filter(([c]) => String(c).includes("/alunos/fundir"));
    const ultima = JSON.parse(String((chamadas.at(-1)![1] as RequestInit).body));
    expect(ultima.confirmar_conflito).toBe("FUNDIR MESMO COM CONFLITO");
  });
});

// --- A7: o que a fusão faz com as leituras repetidas, ANTES do FUNDIR ---------
// A regra (fica a data da ficha principal) não muda; a tela passa a dizer quantos
// livros têm data diferente e qual bimestre perde o livro, e respeita a direção.

const PREVIA_LEITURAS = {
  livros_repetidos: 3, com_data_diferente: 2, no_bimestre: 1,
  // "(o bimestre atual)" só aparece quando o backend diz que ele está em curso.
  bimestre: { numero: 3, rotulo: "3º bimestre", inicio: "2026-07-24", fim: "2026-10-04",
              ano: 2026, atual: true },
  por_bimestre: [{ numero: 3, rotulo: "3º bimestre", livros: 1 }],
  exemplos: [{ livro_id: 5, livro: "Livro Ficticio A", data_manter: "2026-03-25",
               data_remover: "2026-08-06", deixa_de_contar_em: 3 }],
};

async function abrirFusaoCom(nomeOutro: string) {
  responder("GET", /\/alunos\?busca=/, {
    itens: [{ id: 20, nome: nomeOutro, status: "ativo", turma: "3º Ano A" }],
    total: 1, pagina: 1, por_pagina: 8,
  });
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />);
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Fundir com outro aluno"));
  await userEvent.type(screen.getByPlaceholderText(/Buscar o cadastro duplicado/), "Ana");
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(nomeOutro) }));
}

test("a prévia mostra os livros repetidos com data diferente antes do FUNDIR", async () => {
  responder("GET", /\/alunos\/fundir\/previa/, (caminho: string) => {
    const q = new URL(`http://x${caminho}`).searchParams;
    return {
      manter: { id: Number(q.get("manter_id")), nome: "x" },
      remover: { id: Number(q.get("remover_id")), nome: "y" },
      leituras: PREVIA_LEITURAS,
    };
  });
  await abrirFusaoCom("Ana Souza Duplicada");

  const aviso = await screen.findByRole("note", { name: /Livros repetidos com data diferente/ });
  expect(aviso).toHaveTextContent("2 livros estão nas duas fichas com datas diferentes");
  expect(aviso).toHaveTextContent("Fica a data de “Ana Souza”");
  expect(aviso).toHaveTextContent("1 no 3º bimestre (o bimestre atual)");
  expect(aviso).toHaveTextContent("Livro Ficticio A: fica 25/03/2026, sai 06/08/2026");
  // a consulta foi feita na direção que está na tela
  const consultas = api.mock.calls.map(([c]) => String(c)).filter((c) => c.includes("/fundir/previa"));
  expect(consultas.at(-1)).toContain("manter_id=10&remover_id=20");
});

test("trocar a ficha principal refaz a prévia na outra direção", async () => {
  responder("GET", /\/alunos\/fundir\/previa/, (caminho: string) => {
    const q = new URL(`http://x${caminho}`).searchParams;
    return {
      manter: { id: Number(q.get("manter_id")), nome: "x" },
      remover: { id: Number(q.get("remover_id")), nome: "y" },
      leituras: PREVIA_LEITURAS,
    };
  });
  await abrirFusaoCom("Ana Souza Duplicada");
  await screen.findByRole("note", { name: /Livros repetidos/ });
  await userEvent.click(screen.getByRole("button", { name: "trocar" }));
  await vi.waitFor(() => {
    const consultas = api.mock.calls.map(([c]) => String(c)).filter((c) => c.includes("/fundir/previa"));
    expect(consultas.at(-1)).toContain("manter_id=20&remover_id=10");
  });
  expect(await screen.findByRole("note", { name: /Livros repetidos/ }))
    .toHaveTextContent("Fica a data de “Ana Souza Duplicada”");
});

test("se a prévia falhar, avisa e não bloqueia a fusão", async () => {
  responderErro("GET", /\/alunos\/fundir\/previa/, 500, "Banco ocupado");
  responder("POST", /\/alunos\/fundir$/, { ok: true });
  await abrirFusaoCom("Ana Souza Duplicada");
  expect(await screen.findByText(/Não foi possível conferir as leituras repetidas/)).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("FUNDIR"), "FUNDIR");
  expect(screen.getByRole("button", { name: /Fundir cadastros/ })).toBeEnabled();
});

// --- Direção da fusão: a ficha aberta não fica como principal só por estar aberta.
// A prévia traz a sugestão (mesma regra do lote) e o aviso de nome abreviado.

function previaComSugestao(manterSugerido: number) {
  return (caminho: string) => {
    const q = new URL(`http://x${caminho}`).searchParams;
    const manter = Number(q.get("manter_id"));
    const remover = Number(q.get("remover_id"));
    const nomes: Record<number, string> = { 10: "Ana Souza", 20: "Ana Souza Lima Ficticia" };
    return {
      manter: { id: manter, nome: nomes[manter] },
      remover: { id: remover, nome: nomes[remover] },
      sugestao: { manter_id: manterSugerido, remover_id: manterSugerido === 10 ? 20 : 10,
                  motivo: "lista_piloto" },
      nome: { mantem_abreviado: manter !== manterSugerido, fica: nomes[manter], sai: nomes[remover] },
      leituras: { livros_repetidos: 0, com_data_diferente: 0, no_bimestre: 0, bimestre: null,
                  por_bimestre: [], exemplos: [] },
    };
  };
}

test("abre com a ficha sugerida como principal, não com a ficha aberta", async () => {
  responder("GET", /\/alunos\/fundir\/previa/, previaComSugestao(20));
  responder("POST", /\/alunos\/fundir$/, { ok: true });
  await abrirFusaoCom("Ana Souza Lima Ficticia");

  expect(await screen.findByText(/Sugestão do sistema: manter este cadastro/)).toBeInTheDocument();
  expect(screen.getByText("Fica como principal:").parentElement)
    .toHaveTextContent("Ana Souza Lima Ficticia");
  expect(screen.queryByRole("note", { name: /nome abreviado/ })).toBeNull();

  await userEvent.type(screen.getByPlaceholderText("FUNDIR"), "FUNDIR");
  await userEvent.click(screen.getByRole("button", { name: /Fundir cadastros/ }));
  await vi.waitFor(() => {
    const post = api.mock.calls.find(([c, o]) => String(c).endsWith("/alunos/fundir")
      && (o as RequestInit)?.method === "POST");
    expect(JSON.parse(String((post![1] as RequestInit).body)))
      .toMatchObject({ manter_id: 20, remover_id: 10 });
  });
});

test("trocar contra a sugestão avisa do nome abreviado e não é desfeito", async () => {
  responder("GET", /\/alunos\/fundir\/previa/, previaComSugestao(20));
  await abrirFusaoCom("Ana Souza Lima Ficticia");
  await screen.findByText(/Sugestão do sistema/);

  await userEvent.click(screen.getByRole("button", { name: "trocar" }));
  const aviso = await screen.findByRole("note", { name: /nome abreviado/ });
  expect(aviso).toHaveTextContent("o nome que fica é “Ana Souza”");
  expect(aviso).toHaveTextContent("vai sair no certificado");
  expect(screen.getByText(/O sistema sugere manter/)).toHaveTextContent("Ana Souza Lima Ficticia");
  // a nova consulta (outra direção) não devolve a escolha para a sugestão
  expect(screen.getByText("Fica como principal:").parentElement).toHaveTextContent("Ana Souza");
  expect(screen.getByText("Fica como principal:").parentElement)
    .not.toHaveTextContent("Ana Souza Lima Ficticia");
  // não bloqueia: com FUNDIR digitado, o botão libera
  await userEvent.type(screen.getByPlaceholderText("FUNDIR"), "FUNDIR");
  expect(screen.getByRole("button", { name: /Fundir cadastros/ })).toBeEnabled();
});

test("enquanto a prévia confere, FUNDIR digitado não libera o botão", async () => {
  // Sem a prévia, o gestor fundiria na direção da ficha aberta (que pode ser o
  // stub) sem ver a sugestão, o aviso de nome abreviado nem as datas descartadas.
  let liberar: () => void = () => {};
  const chegou = new Promise<void>((r) => { liberar = r; });
  const previa = previaComSugestao(10);
  responder("GET", /\/alunos\/fundir\/previa/,
    (caminho: string) => chegou.then(() => previa(caminho)));
  responder("POST", /\/alunos\/fundir$/, { ok: true });
  await abrirFusaoCom("Ana Souza Lima Ficticia");

  expect(await screen.findByText(/Conferindo as leituras das duas fichas/)).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("FUNDIR"), "FUNDIR");
  const botao = screen.getByRole("button", { name: /Fundir cadastros/ });
  expect(botao).toBeDisabled();
  await userEvent.click(botao);
  expect(api.mock.calls.some(([c, o]) => String(c).endsWith("/alunos/fundir")
    && (o as RequestInit)?.method === "POST")).toBe(false);

  liberar();
  expect(await screen.findByText(/Sugestão do sistema: manter este cadastro/)).toBeInTheDocument();
  expect(screen.queryByText(/Conferindo as leituras/)).toBeNull();
  expect(screen.getByRole("button", { name: /Fundir cadastros/ })).toBeEnabled();
});

test("quando a ficha aberta já é a sugerida, ela continua principal", async () => {
  responder("GET", /\/alunos\/fundir\/previa/, previaComSugestao(10));
  await abrirFusaoCom("Ana Souza Lima Ficticia");
  expect(await screen.findByText(/Sugestão do sistema: manter este cadastro/)).toBeInTheDocument();
  expect(screen.getByText("Fica como principal:").parentElement).toHaveTextContent("Ana Souza");
  expect(screen.getByText("Fica como principal:").parentElement)
    .not.toHaveTextContent("Lima Ficticia");
});
