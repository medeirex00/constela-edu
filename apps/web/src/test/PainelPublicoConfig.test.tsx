/**
 * Configuração do Painel Público — a tela que controla a PRIVACIDADE das
 * crianças no telão sem senha. Regressão aqui é grave (LGPD/ECA), então cobrimos
 * o padrão protegido e o gesto consciente para expor.
 */
import PainelPublicoConfig from "../pages/PainelPublicoConfig";
import { api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor, within } from "./utils";

const DIALOGO_EXPOSICAO = "Exibir o nome completo no telão?";
const DIALOGO_TOKEN = "Gerar um novo endereço?";

/** Quantas vezes a tela chamou a API com este método e caminho (a consulta não conta: em
 *  loopback, o jsdom, a tela acrescenta `?origem=` — lib/linkPublico). */
function chamadas(metodo: string, caminho: string): number {
  return api.mock.calls.filter(
    ([c, opcoes]) => String(c).split("?")[0] === caminho
      && ((opcoes as RequestInit | undefined)?.method ?? "GET") === metodo,
  ).length;
}

interface ConfigOver {
  ativo?: boolean;
  anonimizar?: boolean;
}

function responderConfig(over: ConfigOver = {}) {
  responder("GET", "/escolas/1/painel-publico", {
    ativo: over.ativo ?? true,
    slides: ["ranking", "evolucao", "destaques", "mural"],
    intervalo_s: 12,
    max_posicoes: 10,
    anonimizar: over.anonimizar ?? true,
    url: "https://www.constelaedu.com/p/tok123",
  });
}

test("a proteção do nome das crianças vem LIGADA por padrão", async () => {
  responderConfig({ anonimizar: true });
  renderComApp(<PainelPublicoConfig />);
  const toggle = await screen.findByLabelText(/Proteger o nome dos alunos/i);
  expect(toggle).toBeChecked();
});

test("o aviso de privacidade aparece mesmo com o painel DESATIVADO", async () => {
  responderConfig({ ativo: false, anonimizar: true });
  renderComApp(<PainelPublicoConfig />);
  // O card de privacidade não fica mais escondido atrás de "painel ativo".
  expect(await screen.findByText(/Privacidade dos alunos/i)).toBeInTheDocument();
  expect(await screen.findByLabelText(/Proteger o nome dos alunos/i)).toBeChecked();
});

test("desligar a proteção PEDE confirmação; se recusar, continua protegido", async () => {
  responderConfig({ anonimizar: true });
  responder("PUT", "/escolas/1/painel-publico", () => ({}));
  renderComApp(<PainelPublicoConfig />);
  const toggle = await screen.findByLabelText(/Proteger o nome dos alunos/i);

  await userEvent.click(toggle);

  // Avisou antes de expor: o diálogo diz o efeito e pede o consentimento.
  const dialogo = await screen.findByRole("dialog", { name: DIALOGO_EXPOSICAO });
  expect(dialogo).toHaveTextContent(/EXIBIR O NOME COMPLETO das crianças no telão público/);
  expect(dialogo).toHaveTextContent(/consentimento dos responsáveis/);
  await userEvent.click(within(dialogo).getByRole("button", { name: "Cancelar" }));

  expect(screen.queryByRole("dialog", { name: DIALOGO_EXPOSICAO })).toBeNull();
  expect(toggle).toBeChecked(); // recusou → nada mudou, segue protegido
  expect(chamadas("PUT", "/escolas/1/painel-publico")).toBe(0);
});

/** Responde o PUT ecoando o corpo e guarda cada corpo enviado ao servidor. */
function capturarPuts() {
  const corpos: Record<string, unknown>[] = [];
  responder("PUT", "/escolas/1/painel-publico", (_caminho, opcoes) => {
    const corpo = JSON.parse(String((opcoes as RequestInit).body)) as Record<string, unknown>;
    corpos.push(corpo);
    return { ...corpo, url: "https://www.constelaedu.com/p/tok123" };
  });
  return corpos;
}

test("salvar o intervalo NÃO confirma a exposição do nome completo", async () => {
  // Aba carregada com o nome completo (anonimizar=false). Se outra pessoa
  // ligou a proteção depois, só o servidor sabe: esta aba não pode mandar
  // confirmar_exposicao=true ao salvar o intervalo.
  responderConfig({ anonimizar: false });
  const corpos = capturarPuts();
  renderComApp(<PainelPublicoConfig />);

  const intervalo = await screen.findByLabelText(/Segundos por slide/i);
  await userEvent.clear(intervalo);
  await userEvent.type(intervalo, "15");
  await userEvent.tab(); // blur salva
  await waitFor(() => expect(corpos).toHaveLength(1));
  expect(corpos[0]).toMatchObject({ intervalo_s: 15, anonimizar: false, confirmar_exposicao: false });
  expect(screen.queryByRole("dialog", { name: DIALOGO_EXPOSICAO })).toBeNull();
});

test("marcar/desmarcar slide também NÃO confirma a exposição", async () => {
  responderConfig({ anonimizar: false });
  const corpos = capturarPuts();
  renderComApp(<PainelPublicoConfig />);

  await userEvent.click(await screen.findByLabelText(/Mural da escola/i));
  await waitFor(() => expect(corpos).toHaveLength(1));
  expect(corpos[0]).toMatchObject({ anonimizar: false, confirmar_exposicao: false });
  expect(corpos[0].slides).not.toContain("mural");
  expect(screen.queryByRole("dialog", { name: DIALOGO_EXPOSICAO })).toBeNull();
});

test("a aba antiga recebe a recusa do servidor e mostra a mensagem", async () => {
  responderConfig({ anonimizar: false });
  responderErro("PUT", "/escolas/1/painel-publico", 400,
    "Para exibir o nome completo das crianças no telão público (link sem senha), é preciso confirmar a exposição explicitamente.");
  renderComApp(<PainelPublicoConfig />);

  const posicoes = await screen.findByLabelText(/Posições no ranking/i);
  await userEvent.clear(posicoes);
  await userEvent.type(posicoes, "12");
  await userEvent.tab();

  expect(await screen.findByText(/é preciso confirmar a exposição explicitamente/i)).toBeInTheDocument();
});

test("só o checkbox de privacidade, com o aviso ACEITO, confirma a exposição", async () => {
  responderConfig({ anonimizar: true });
  const corpos = capturarPuts();
  renderComApp(<PainelPublicoConfig />);
  const toggle = await screen.findByLabelText(/Proteger o nome dos alunos/i);

  await userEvent.click(toggle); // desliga a proteção: avisa e confirma
  const dialogo = await screen.findByRole("dialog", { name: DIALOGO_EXPOSICAO });
  expect(corpos).toHaveLength(0); // abrir o aviso não grava nada
  await userEvent.click(within(dialogo).getByRole("button", { name: "Exibir o nome completo" }));
  await waitFor(() => expect(corpos).toHaveLength(1));
  expect(corpos[0]).toMatchObject({ anonimizar: false, confirmar_exposicao: true });
  await waitFor(() => expect(toggle).not.toBeChecked());
  await waitFor(() => expect(screen.queryByRole("dialog", { name: DIALOGO_EXPOSICAO })).toBeNull());

  await userEvent.click(toggle); // religa a proteção: nada a confirmar
  await waitFor(() => expect(corpos).toHaveLength(2));
  expect(corpos[1]).toMatchObject({ anonimizar: true, confirmar_exposicao: false });
  expect(screen.queryByRole("dialog", { name: DIALOGO_EXPOSICAO })).toBeNull();
});

test("gerar novo endereço PEDE confirmação; confirmar troca o token", async () => {
  responderConfig({ ativo: true });
  responder("POST", "/escolas/1/painel-publico/novo-token", {
    ativo: true,
    slides: ["ranking"],
    intervalo_s: 12,
    max_posicoes: 10,
    anonimizar: true,
    url: "https://www.constelaedu.com/p/tok999",
  });
  renderComApp(<PainelPublicoConfig />);

  await userEvent.click(await screen.findByRole("button", { name: /Gerar novo endereço/ }));
  const dialogo = await screen.findByRole("dialog", { name: DIALOGO_TOKEN });
  expect(dialogo).toHaveTextContent("O link e o QR code atuais deixarão de funcionar.");
  expect(chamadas("POST", "/escolas/1/painel-publico/novo-token")).toBe(0);

  await userEvent.click(within(dialogo).getByRole("button", { name: "Gerar novo endereço" }));

  expect(await screen.findByText("Novo endereço gerado. Atualize o QR code impresso.")).toBeInTheDocument();
  expect(chamadas("POST", "/escolas/1/painel-publico/novo-token")).toBe(1);
  // O endereço mostrado é o que o servidor devolveu, sem reescrever (lib/linkPublico): o que
  // importa aqui é o TOKEN novo.
  expect(screen.getByText("https://www.constelaedu.com/p/tok999")).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: DIALOGO_TOKEN })).toBeNull();
});

test("cancelar o novo endereço mantém o link atual", async () => {
  responderConfig({ ativo: true });
  responder("POST", "/escolas/1/painel-publico/novo-token", {});
  renderComApp(<PainelPublicoConfig />);

  await userEvent.click(await screen.findByRole("button", { name: /Gerar novo endereço/ }));
  const dialogo = await screen.findByRole("dialog", { name: DIALOGO_TOKEN });
  await userEvent.click(within(dialogo).getByRole("button", { name: "Cancelar" }));

  expect(screen.queryByRole("dialog", { name: DIALOGO_TOKEN })).toBeNull();
  expect(chamadas("POST", "/escolas/1/painel-publico/novo-token")).toBe(0);
  expect(screen.getByText("https://www.constelaedu.com/p/tok123")).toBeInTheDocument();
});

// Antes, sem escola escolhida a tela ficava em "Carregando..." para sempre (a busca nunca saía).
// A vitrine da rede mora no Panorama da Rede (a página inicial da Secretaria, DESENHO3 §5): o
// Painel da Rede saiu do menu dela.
test("Secretaria: não busca o painel de escola e é levada à vitrine da rede, no Panorama (sem 'Carregando...' eterno)", async () => {
  responderConfig();
  renderComApp(<PainelPublicoConfig />, {
    rota: "/painel-publico",
    usuario: usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null }),
  });
  expect(await screen.findByText("A vitrine da rede fica no Panorama da Rede")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Ir para a vitrine da rede/ })).toHaveAttribute("href", "/");
  expect(screen.queryByText(/Painel da Rede/)).toBeNull();
  expect(screen.queryByText("Carregando...")).toBeNull();
  expect(api.mock.calls.some(([c]) => String(c).includes("/painel-publico"))).toBe(false);
});

// Fora da Secretaria a escola só falta com a lista VAZIA — e aí nem o seletor do menu lateral
// aparece: a tela diz que não há escola e a quem pedir, sem mandar usar um seletor ausente.
test("sem escola na lista: avisa que não há escola disponível e a quem pedir, sem buscar nada", async () => {
  responderConfig();
  renderComApp(<PainelPublicoConfig />, { rota: "/painel-publico", escolas: [] });
  expect(await screen.findByText("Nenhuma escola disponível")).toBeInTheDocument();
  expect(screen.getByText(
    "Esta conta ainda não tem escola vinculada. Peça à administração o cadastro ou o vínculo da escola para configurar o painel público.",
  )).toBeInTheDocument();
  expect(screen.queryByText(/seletor/)).toBeNull();
  expect(screen.queryByText("Carregando...")).toBeNull();
  expect(api.mock.calls.some(([c]) => String(c).includes("/painel-publico"))).toBe(false);
});
