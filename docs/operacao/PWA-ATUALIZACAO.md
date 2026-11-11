# Atualização do app instalado (PWA) — como uma versão nova chega a quem já usa

> Escopo: o web (`apps/web`). Validado **localmente** em 20 e 21/10/2026 (build real +
> service worker real no Chromium, dados inventados). Nada aqui foi publicado.

## Por que existia o "faça hard refresh"

O web é um PWA (vite-plugin-pwa 1.3, Workbox 7.4, `generateSW`). O service worker
guarda no Cache Storage o "esqueleto" do app (HTML, JS, CSS, fontes, ícones — nunca
`/api`) e responde as navegações com o `index.html` guardado.

Até esta rodada a configuração era `registerType: "autoUpdate"`:

1. o navegador só procura `sw.js` novo numa **navegação de verdade** (ou a cada
   24 h). O app é SPA: quem deixa a aba aberta o dia todo — e o telão, que fica
   semanas na TV — nunca navega de verdade e **seguia na versão antiga**;
2. ao abrir o app depois de um deploy, a 1ª tela ainda vinha do cache (versão
   antiga); a nova baixava em segundo plano, assumia sozinha (`skipWaiting` +
   `clientsClaim`) e o plugin **recarregava a página** — segundos depois de abrir,
   às vezes com alguém já digitando (o formulário se perdia);
3. sem saber disso, a orientação virou "Ctrl+Shift+R" (que pula o service worker).

## Como funciona agora

`registerType: "prompt"` (apps/web/vite.config.ts): a versão nova é baixada e
**espera**. Quem decide a troca é `apps/web/src/lib/pwaAtualizacao.ts`, com o aviso
`apps/web/src/components/PwaAviso.tsx`, ligados no `apps/web/src/main.tsx`.

| Situação | O que acontece |
|---|---|
| App logado, pessoa usando (já tocou/digitou) | Aviso no canto: **"Nova versão do Constela disponível — Salve o que estiver editando: atualizar recarrega a página."** Botões **Atualizar agora** e **Depois**. Nada recarrega sem o clique: enquanto o aviso espera, as telas desta aba seguem abrindo pela versão antiga, do cache. |
| "Atualizar agora" | O service worker novo assume (`SKIP_WAITING`) e a página recarrega **uma vez**, já na versão nova. |
| "Depois" | O aviso some. A versão nova entra na **próxima abertura** do app (ver linha abaixo). |
| Abertura do app (F5, nova aba, ícone instalado) com versão nova esperando, nos primeiros 10 s e antes de qualquer toque | Troca direta, **sem cartão**: o pedido de troca sai 1 s depois de a página carregar e ela recarrega uma vez, já na nova. Se a pessoa tocar ou digitar antes da recarga, a troca é **cancelada** e vira o aviso acima (nada do que ela digitou se perde). **Um F5 comum basta — não precisa de hard refresh.** |
| Página que veio da **rede** com versão esperando ao abrir: Ctrl+Shift+R, a recarga do plano B, o telão `/p/` (o service worker nunca serve esse HTML) | **Nada**: ela já é a versão mais nova que havia quando abriu. Antes ela tentava trocar e, com outra aba do Constela aberta segurando o service worker antigo, recarregava a cada 4 s até a outra aba fechar (medido: 23 recargas em 90 s). |
| Telão `/p/…` e vitrine `/rede/p/…` | Troca e recarrega **sozinha** (sem formulário e sem ninguém para clicar). Sem aviso na TV. |
| Outra aba aplicou a versão nova | Esta aba **não** recarrega na hora: avisa "O Constela foi atualizado em outra aba. Recarregue esta página quando terminar o que está fazendo." com o botão **Recarregar**. Mas os arquivos da versão antiga já não existem: nem no cache do service worker novo, que passou a controlar esta aba, nem no servidor. Se a pessoa abrir uma tela que esta aba ainda não tinha aberto, ela recarrega **uma vez, sozinha**, já na versão nova, sem perder o login (o socorro da última linha); a tela de antes já estava sendo deixada. |
| Procura por versão nova | A cada **1 hora**, ao **voltar para a aba** (se a última procura tiver 5+ min) e quando a **conexão volta**. Sem conexão, não procura. A versão que chega é vista pelo próprio registro do service worker (`updatefound`/`statechange`), não só pelos avisos do plugin: o workbox-window desliga o ouvinte dele na 1ª atualização "externa", e uma 1ª instalação que falhasse (rede da escola caiu, 5xx) deixava a aba e o telão sem ver nenhum deploy seguinte. O mesmo worker não vira aviso duas vezes (o "Depois" não volta a cada hora). A **1ª instalação** do service worker (1ª visita, nenhum worker ativo no registro) não é versão nova e é ignorada: no `installed` dela o Chromium ainda a mostra em `waiting` por um instante, e com o precache lento (186 arquivos, 3,8 MB: passar de 10 s é plausível na rede da escola) isso virava o aviso no `/login` e troca + plano B no telão e na vitrine. |
| O service worker novo não assume em 4 s depois do pedido | Plano B: desregistra o service worker e recarrega (a página vem da rede). **Não apaga o cache do PWA**: outra aba aberta ainda roda a versão antiga com ele. Na troca **automática**, no máximo **uma vez a cada 10 min por aba** (marca `pwa_plano_b_em` na sessionStorage); barrado, o app volta ao aviso e o telão tenta de novo quando o intervalo passa. O clique em **Atualizar agora** não é barrado pela marca (cada clique é a pessoa pedindo; não há laço): numa página que veio da rede o worker novo nunca assume, e só o plano B a atualiza. |
| Chunk de tela que sumiu no deploy: a aba do "atualizado em outra aba", ou a página que veio da rede (1ª visita, Ctrl+Shift+R, plano B), abre depois do deploy uma tela que ainda não tinha aberto | Socorro de `lib/atualizacao.ts`: desregistra o service worker e recarrega da rede, **uma vez por sessão**, já na versão nova (o login fica). **Não apaga o cache do PWA**, o mesmo cuidado do plano B: o cache é de todas as abas do navegador. Antes ele apagava, e a outra aba que esperava o clique na versão antiga recarregava sozinha na próxima tela, e a aba já na versão nova deixava de abrir sem internet até o próximo deploy. O botão **Recarregar** da tela "Algo deu errado" faz o mesmo. Evitar até esta recarga pediria manter os arquivos da versão anterior no servidor por um tempo depois do deploy (decisão de infraestrutura, não tomada). |

O aviso tem `role="status"` (anuncia ao leitor de tela sem tirar o foco de quem
digita) e fica fora do roteador e do `LimiteErro` — aparece até numa tela que
quebrou por arquivo antigo.

### Por que o pedido de troca espera 1 s depois do `load`

A primeira versão desta rodada dizia que "depois de um F5 com versão esperando, o
`SKIP_WAITING` não ativa o worker novo naquela mesma página". Medido de novo em
21/10 (build real, Chromium do Playwright, roteiros em `e86/fix/web/sonda/`): não é
o F5. É **quando** o pedido sai. Enviado durante a carga da página, o `SKIP_WAITING`
fica preso — o worker novo não assume enquanto aquela página viver, e reenviar não
adianta (o navegador só reavalia quando alguma aba fecha ou recarrega). Enviado depois
que a página assentou, assume na hora:

| Quando o `SKIP_WAITING` sai | Preso |
|---|---|
| no aviso do plugin (o código anterior, ~40 ms depois da navegação) | 7 de 11 aberturas |
| no `DOMContentLoaded` | 1 de 4 |
| no `load` | 4 de 12 |
| 300 ms depois do `load` | 0 de 4 |
| 1 s depois do `load` | 0 de 6 |

Era isso que mandava mais da metade das aberturas para o plano B. Com o atraso de 1 s, a
troca da abertura entra pelo caminho normal (o worker novo assume e a página recarrega
uma vez); o plano B fica para o caso raro.

### O que NÃO mudou

- Nada de `/api` no cache (respostas autenticadas e multiescola em computador
  compartilhado da escola).
- `navigateFallbackDenylist` (`/api`, `/p/`) e `cleanupOutdatedCaches`.
- O `sw.js` é servido pela Vercel com `max-age=0, must-revalidate` (padrão) e no
  nginx do Docker sem cache longo; os arquivos de `assets/` têm nome com hash.

## Como conferir (local)

1. `npx vitest run src/test/pwaAtualizacao.test.tsx` — 40 testes da máquina de
   estados e do aviso (inclui as catracas que reprovam se o `vite.config.ts` voltar ao
   `autoUpdate` ou tirar o `/p/` do `navigateFallbackDenylist`).
2. `npx vite build` — o `dist/sw.js` gerado tem só
   `addEventListener("message", … "SKIP_WAITING" … self.skipWaiting())` e **não**
   tem `skipWaiting()` solto nem `clientsClaim`.
3. Ponta a ponta (navegador real, service worker real): build `v1`; cópia `v2` com
   um `<meta name="versao-e2e" content="v2">` no `index.html` e a revisão do
   `index.html` trocada no `sw.js`; servidor estático local imitando a Vercel. O
   roteiro usado em 20/10 (fora do repositório, na pasta de rascunho da rodada:
   `e86/agentes/ui/pwa-e2e/validar_pwa.mjs`) conferiu 10/10:
   - A: aba aberta e em uso → `registration.update()` acha a v2 → aviso aparece,
     **sem recarga** e com o rascunho do formulário intacto → "Atualizar agora" → v2;
   - B: "Depois" → aviso some → **F5 comum** → v2;
   - C: vitrine pública → troca sozinha → v2, sem aviso;
   - D: duas abas → a que clicou vai para a v2; a outra **não recarrega**, mantém o
     rascunho e mostra "atualizado em outra aba".

   Em 21/10, com as correções da revisão, o mesmo `validar_pwa.mjs` (10/10) e os
   cenários do revisor (`e86/fix/web/e2e/cenarios.mjs`) no build corrigido:
   - E: aba A com "Depois" + aba B nova: B recarrega **uma** vez e fica na v2, sem
     plano B; A não recarrega, mantém o rascunho e avisa "atualizado em outra aba"
     (antes: 23 recargas de B em 90 s);
   - E2/E3: aba A com aviso + telão `/p/` ou aba nova do app: telão sem nenhuma
     recarga, aba nova com uma, ambos na v2; fechar A não muda nada (antes: 5
     recargas em 20 s);
   - H (transição): aba no build antigo + telão `/p/` aberto: 1 carga em 60 s, já na
     v2 (antes: 15 recargas);
   - F/G: aba aberta há 62 s, 1ª instalação falha e a 2ª dá certo: o aviso aparece
     no app e o telão vai sozinho para a v2 (antes: nada, para sempre);
   - S (3×) e Q: "Depois" + F5 comum e "Atualizar agora": v2 pelo caminho normal,
     sem plano B (antes, o F5 caía no plano B);
   - I (2×): F5 com versão esperando e a pessoa digita logo ao abrir: nada recarrega,
     o texto fica e aparece o aviso (antes: a página recarregava).

   Ainda em 21/10, a revisão dessa correção achou uma regressão, já corrigida: a
   detecção própria tomava a **1ª instalação** por versão nova quando o precache
   demorava mais que os 10 s da abertura. Roteiro do verificador
   (`e86/fix/verif_web/primeira_instalacao.mjs`: contexto novo, um chunk do precache
   segurado por 11–13 s):
   - antes da correção: `/login` com o aviso "Nova versão" sem haver versão nova;
     telão `/p/` com 2 cargas e plano B (o worker recém-instalado desregistrado);
   - depois: `/login`, `/p/` e `/rede/p/` com 11 s e 13 s (6 rodadas): aviso 0,
     1 carga, sem plano B.
   E o clique depois de um plano B (`e86/fix/web/e2e_p2/clique_apos_plano_b.mjs`:
   página que veio da rede, outra aba segurando a v1, marca de plano B de 1 min atrás,
   deploy, "Atualizar agora"): antes, o aviso voltava e a página seguia na v1; agora
   ela recarrega uma vez, já na v2.

## Para o suporte (o que dizer à escola)

- "Apareceu 'Nova versão do Constela disponível'": salve o que estiver fazendo e
  clique **Atualizar agora**. Se preferir, **Depois** — a versão entra quando o app
  for aberto de novo.
- Não é mais preciso "Ctrl+Shift+R". Se alguém ainda vir tela antiga, fechar a aba e
  abrir de novo resolve (a troca acontece na abertura).
- O telão da escola se atualiza sozinho em até 1 hora depois de um deploy (ou na
  hora, se a TV for religada).
- "A página recarregou sozinha quando abri uma tela", logo depois de uma
  atualização: é esperado na aba que mostrava "atualizado em outra aba" (ou na que
  foi aberta pela primeira vez, ou com Ctrl+Shift+R, antes do deploy). Os arquivos da
  versão anterior saíram do servidor; a página recarrega uma vez, já na versão nova, e
  o login continua.

## Produção (nada foi feito) — a transição do 1º deploy

Nenhuma ação técnica: a mudança vai com o próximo deploy do web. Mas o 1º deploy com
este fluxo encontra abas rodando o código ANTIGO (`autoUpdate`), que não sabe pedir
a troca a um service worker que espera. Medido localmente (build antigo → build
novo, roteiro `e86/agentes/ui/pwa-e2e/validar_transicao.mjs`, 4/4):

- aba do app aberta na versão antiga: **não recarrega sozinha** (rascunho a salvo) e
  um **F5 ainda mostra a antiga**; **fechar a aba (ou a janela do app instalado) e
  abrir de novo** traz a nova — e dali em diante vale a tabela acima;
- telão `/p/…`: um **F5** já traz a nova (essa rota vem sempre da rede). Aberto
  numa aba nova com uma aba antiga ainda aberta, ele já abre na nova e não recarrega
  (antes desta correção, recarregava a cada 4 s enquanto a aba antiga vivesse);
- vitrine `/rede/p/…`: como o app — fechar e abrir a aba.

Procedimento sugerido no dia do deploy (só comunicação, sem executar nada no servidor):
avisar as escolas e a Secretaria para **fechar e abrir o Constela uma vez** e dar
**F5 no telão**; quem não fizer recebe a versão nova quando o navegador ou o
computador for reiniciado. A partir desse deploy, nenhuma orientação de "hard
refresh" é necessária.
