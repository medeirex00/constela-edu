# 22 — Monetização & Modelo de Negócio / Monetization & Business Model

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 22, subseções 22.1–22.19 + 10 perguntas ao dono; ADR candidato C.20), `_estado-atual/RELATORIO-2026-07-09.md`, `00-visao-e-norte.md` ("Comprador: a escola/rede licencia o produto"), e o **código Q0** — que **não tem monetização**: `backend/app/models/escola.py` (só `nome`/`cidade`/`estado`/`logotipo_url`/`ano_letivo_ativo`/`status` = `ativa|inativa`; **sem plano/tier/contrato/assinatura/assento**), `backend/app/models/configuracao.py` (KV por escola `escola_id`/`namespace`/`chave`/`valor` JSON — o **mecanismo de gating** já existe, hoje só namespaces do Edu `pesos.*`/`gamificacao.*`/`desempate.*`; o `quest.*` é aspiracional), `backend/app/quest/models/catalogo.py` (`moedas_base=10` — moeda **de jogo**), `backend/app/quest/models/perfil.py` (`moedas` cache; "a verdade vive no **ledger** e nas tentativas" — o **ledger P14 ainda não é tabela**), `apps/web/src/pages/Escolas.tsx` (`REDE_CARAGUA` — ~28 escolas municipais, evidência do arquétipo **B2G**), Seções [01](01-principios-imutaveis.md)/[05](05-sistemas-de-jogo.md)/[10](10-professor-familia.md)/[12](12-seguranca-privacidade.md)/[14](14-infra-deploy-dr.md)/[17](17-telemetria-metricas.md)/[19](19-liveops.md)/[21](21-suporte-operacao.md)/[23](23-roadmap.md), Apêndices A.8/C.20/F
- **Depende de / Depends on:** princípios **imutáveis** (P7 sem compra in-app · passe gratuito; P8 zero dark patterns; P6 erro nunca pune; P18 sem anúncios/rastreamento; P14 economia auditável) → [01](01-principios-imutaveis.md); **mecânica** do passe e da **economia de moedas/estrelas/XP** (moeda de jogo) → [05](05-sistemas-de-jogo.md); **valores** de config `quest.*` + feature flags/kill-switches + **operação** do passe → [19](19-liveops.md); **SLA de suporte** e **onboarding operacional** → [21](21-suporte-operacao.md); **base legal**/consentimento do contrato → [12](12-seguranca-privacidade.md); **papéis** e vínculo responsável → [10](10-professor-familia.md); **taxonomia** das métricas de negócio → [17](17-telemetria-metricas.md); **números de infra** (COGS) → [14](14-infra-deploy-dr.md); **fase de lançamento comercial** → [23](23-roadmap.md); **glossário de negócio** → Apêndice A.8; **ADR de gratuidade imutável** → C.20.

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible; "22.NN" = uma subseção do plano do `INDICE.md`.
> **Escopo / Scope:** este capítulo decide o **modelo de negócio** do Constela — **quem paga** (a escola/rede
> licencia; a **criança nunca é fonte de receita**), o **gating de recursos por licença**, o **firewall** entre a
> economia do jogo e dinheiro real, a **estrutura de custos** e a **contratação comercial** — de forma **executável
> por um dev/comercial sem violar os princípios imutáveis**. Ele **decide o modelo e o que cada licença compra**;
> **não** decide a **mecânica** do passe/economia (Seção [05](05-sistemas-de-jogo.md)), os **valores** de config
> nem a **operação** do passe (Seção [19](19-liveops.md)), o **SLA operacional** (Seção [21](21-suporte-operacao.md)),
> a **política** LGPD (Seção [12](12-seguranca-privacidade.md)) nem a **taxonomia** (Seção [17](17-telemetria-metricas.md))
> — apenas os **referencia**. As decisões comerciais concretas (preço, planos, unidade) são **do dono** (§15).

---

## 🇧🇷 Monetização & Modelo de Negócio

### 1. Objetivo
Fixar **como o produto gera receita** — **licenciamento pela escola/rede**, **passe 100% gratuito** e **zero compras
in-app** — e deixar **explícito tudo que depende do dono**, para que o dev construa o "encanamento comercial"
**sem tomar decisão de produto e sem violar os princípios imutáveis**. Decide o **modelo**; **não** decide a mecânica
do jogo (Seção [05](05-sistemas-de-jogo.md)), os valores/operação de config (Seção [19](19-liveops.md)) nem a
política LGPD (Seção [12](12-seguranca-privacidade.md)) — apenas os **referencia**. Alimenta o **Apêndice F**.

### 2. Contexto
No **Hub → Edu → Quest**, o **comprador é a escola/rede** (`00-visao-e-norte.md`: "Comprador: a escola/rede
licencia o produto"; a criança é **Jogador**, nunca comprador — **P7**). É um modelo **B2B** (escola privada) e
**B2G** (rede/secretaria municipal — o código já traz a `REDE_CARAGUA` com ~28 escolas). **Estado atual (Q0) —
greenfield comercial:**
- **Nada de monetização no código** — a `Escola` tem `nome`/`cidade`/`estado`/`logotipo_url`/`ano_letivo_ativo`/`status`
  (`ativa|inativa`)/`created_at`; **sem nenhum** campo de plano, tier, assento, licença, contato de suporte ou datas de contrato. **Nenhuma** rota
  de pagamento/assinatura; **nenhum** `stripe`/`pix`/`boleto`/`checkout`. O "financeiro do Edu" **não existe**.
- **Compra in-app inexistente (P7 confirmado no código)** — trocar avatar/aparência é **grátis**; os 6
  personagens-base são **gratuitos**; **não** há loja com dinheiro, loot box paga nem anúncio.
- **O gating tem a caixa pronta** — a `Configuracao` (KV por escola) é o **mecanismo** de ligar/desligar recurso;
  hoje só serve ao Edu (`pesos.*`/`gamificacao.*`/`desempate.*`). O namespace **`quest.*`** (dono = Seção
  [19](19-liveops.md)) é **aspiracional** — declarado num docstring, **sem** código que leia/grave uma chave.
- **Economia do jogo existe como *ganha*** — `moedas_base=10`, `moedas` no perfil (cache; a verdade é o ledger),
  `moedas_ganhas` por tentativa. É **moeda de jogo ganha jogando**, **nunca** dinheiro real.
- **Ainda NÃO existe** — o **ledger imutável** de moedas (P14) como **tabela** (só docstring); o **código de leitura**
  do gating `quest.*`; qualquer **loja/inventário/temporada/passe** (planejados p/ fases futuras — Seção [23](23-roadmap.md)).
- **Distribuição** — hoje **PWA instalável sem loja** (o `apps/mobile` gera APK por sideload, "sem loja").

Este capítulo **crava** as travas imutáveis do modelo e **registra** o que o dono precisa decidir.

### 3. Filosofia da funcionalidade
**"Quem paga é a escola; a criança joga de graça, para sempre."** A monetização do Constela é **B2B/B2G** por
princípio — a receita vem da **licença da escola/rede**, e a experiência da criança é **livre de dinheiro**.
Princípios que a Seção 22 **não pode contrariar** (são imutáveis — Seção [01](01-principios-imutaveis.md)): **P7**
(sem compra in-app; moeda só se ganha jogando; sem moeda comprável, sem caixa de surpresa paga, sem FOMO agressivo;
o passe é **gratuito**); **P8** (zero dark patterns — sem "vidas" que forçam espera/pagamento); **P18** (sem
anúncios e sem SDK de rastreamento de terceiros); **P6** (erro nunca pune — sem perda de moeda/estrela); **P14**
(economia **auditável** por ledger imutável). O gating comercial liga/desliga recursos **para o adulto/escola** —
**jamais** vira paywall, countdown ansioso ou trilho pago na tela da criança.

Conexão: a **economia de moedas** (Seção [05](05-sistemas-de-jogo.md)) é **fechada** — a moeda é **ganha** jogando e
**o que ela compra/gasta é da Seção [05](05-sistemas-de-jogo.md)** (a loja cosmética é fase futura; hoje trocar
avatar é grátis); **nunca** cruza com dinheiro real. A 22 apenas **garante o firewall** e **crava a gratuidade**; não redefine a economia.

### 4. Experiência que o jogador deve sentir
A criança **não** vê preço, plano, anúncio nem botão de compra — **nunca**. Ela vê um jogo **completo e gratuito**:
o passe é grátis, os cosméticos se ganham jogando, e nada a pressiona a pagar. **A escola/gestor** (o comprador)
sente **transparência**: sabe exatamente o que a licença compra, sem letra miúda, sem cobrança escondida da criança.
**A família** ouve, com alívio, que **não há compras** (a persona Dona Cláudia exige "privacidade, zero compras,
transparência").

### 5. Fluxo completo
O **ciclo comercial**, do interesse à renovação (⭐ = existe em Q0; ▢ = a construir/decidir):

1. **Contato/venda** ▢ — a escola/rede demonstra interesse; **piloto/trial** (formato ⚠️ §15).
2. **Contrato & consentimento** ▢ — o **instrumento de licença** define o que o plano compra; o **consentimento** dos
   responsáveis e o **vínculo** (Seção [10](10-professor-familia.md)) são coletados no fluxo. A **base legal aplicável**
   (execução de contrato, legítimo interesse ou consentimento) é **decisão da Seção [12](12-seguranca-privacidade.md)** —
   a 22 **não** a nomeia.
3. **Provisionamento & ativação** ⭐/▢ — a escola é criada e provisionada (**operacional** = Seção [21](21-suporte-operacao.md);
   **técnico/ETL** = Seção [20](20-migracao-importacao.md)); o **gating** liga os recursos do plano (mecanismo = `Configuracao`/`quest.*` da Seção [19](19-liveops.md)).
4. **Uso** ⭐/▢ — hoje ⭐ a criança **entra e customiza** o avatar/nome **de graça** (login + perfil existem em Q0); o
   **loop de jogo**, o **passe gratuito** e o **gating por licença** são ▢ (greenfield — §2/§10). Quando existirem, o
   gating limita recursos **do adulto/escola** conforme a licença e **nunca** cobra a criança.
5. **Controle de uso** ▢ — contagem de escolas/alunos ativos e imposição do **limite da licença** (antipirataria).
6. **Métricas de negócio** ▢ — ativação/churn de escola, LTV, alunos ativos por licença (sinais de produto = Seção [17](17-telemetria-metricas.md); definição das métricas comerciais = 22).
7. **Renovação/expansão** ▢ — a **execução** (CS, QBR) é operada pela Seção [21](21-suporte-operacao.md); o **modelo**
   (o que cada plano compra) é daqui.

### 6. Interface (quando existir)
**Nenhuma superfície comercial toca a criança** (P7). As superfícies do **adulto** (contrato, painel de licença,
faturamento) são **decisão do dono** (§15) e, quando existirem, seguem a Seção [07](07-ux-fluxos-navegacao.md) para o
layout. A tela **"sem licença / recurso desligado"** (estado de gating) é operada pela Seção [19](19-liveops.md) e
listada no Apêndice F. **Não** há tela de loja com dinheiro em lugar nenhum.

### 7. UX
A "UX comercial" é do **adulto** e **honesta** (P8): o gestor entende o que a licença compra **sem letra miúda**; a
família vê **"sem compras"** de forma explícita. **Nenhum** dark pattern — sem countdown ansioso, sem "só hoje", sem
paywall disfarçado. O **default do social é opt-in** (decisão da Seção [09](09-social.md)); o comercial **não** o afrouxa.

### 8. Game Design
**N/A quanto a criar economia** — a **economia** (moedas/estrelas/XP) é da Seção [05](05-sistemas-de-jogo.md) e a
**operação** do passe é da Seção [19](19-liveops.md); a 22 só decide o **modelo/formato** do passe (B17). A 22
contribui com **duas travas** de game design **impostas pelo negócio**: (1) o **passe é gratuito** — nunca há um
trilho pago paralelo; (2) o **firewall** — nenhuma recompensa comprável, nenhuma vantagem de jogo vendida; o passe
grátis dá **só cosméticos** (nunca vantagem competitiva paga disfarçada de "grátis"). Assim a monetização **não**
corrompe o design (sem pay-to-win).

### 9. Regras de negócio
As **normas de monetização** (a fonte do modelo; a **mecânica** do jogo é da Seção [05](05-sistemas-de-jogo.md), os
**valores** de config da Seção [19](19-liveops.md), a **política** LGPD da Seção [12](12-seguranca-privacidade.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| B1 | **Comprador = escola/rede** | a **escola/rede licencia** o produto (B2B/B2G); a **criança nunca** é fonte de receita (P7) | 22; princípio = [01](01-principios-imutaveis.md) |
| B2 | **Passe gratuito, zero compra in-app** | o **passe de temporada é 100% gratuito**, **sem trilho pago paralelo**; **sem** moeda comprável, caixa de surpresa paga ou FOMO agressivo — **já imutável por P7** (elevar a **princípio autônomo** = ADR candidato **C.20**, ⚠️ §15) | 22 (reafirma P7); C.20 = ⚠️ §15 |
| B3 | **Firewall economia × dinheiro** | moedas/estrelas/XP **jamais** convertem em dinheiro/compra/reembolso; a economia é **auditável** pelo **ledger imutável** (P14); o que a moeda **compra/gasta** é da Seção [05](05-sistemas-de-jogo.md) — a 22 só garante o firewall | 22 (firewall); economia/sumidouro = [05](05-sistemas-de-jogo.md)/P14 |
| B4 | **Sem anúncios/rastreamento** | **nenhum** anúncio e **nenhum** SDK de rastreamento de terceiros na experiência da criança (P18) | 22 (reafirma); política = [12](12-seguranca-privacidade.md)/P18 |
| B5 | **Gating nunca vira paywall na criança** | o gating comercial liga/desliga recursos **do adulto/escola**; **nunca** cria paywall, countdown ansioso ou trilho pago na tela da criança (P8; Seção [19](19-liveops.md) C18) | 22; limite = [19](19-liveops.md) |
| B6 | **Unidade de licenciamento** | escola inteira × rede/mantenedora × por aluno ativo × por turma — **parâmetro-mestre** que dita todo o gating e o faturamento | 22 ⚠️ (§15) |
| B7 | **Planos/tiers & mapa recurso↔plano** | se há níveis e o que cada um compra (social, IA, relatórios avançados); é o **mapa recurso↔plano** que a Seção [19](19-liveops.md) executa via `quest.*` | 22 (mapa) ⚠️ (§15); mecanismo = [19](19-liveops.md) |
| B8 | **Gating por licença** | o mecanismo de ligar/desligar recurso **reusa** a `Configuracao`/`quest.*` (dono do mecanismo = Seção [19](19-liveops.md)); a 22 fornece o **mapa plano→flags (quais recursos)**; os **valores** das chaves `quest.*` são da Seção [19](19-liveops.md) | 22 (mapa de flags); mecanismo/valores = [19](19-liveops.md) |
| B9 | **Precificação & faturamento** | faixa de preço, unidade (ex.: R$/aluno/ano) e moeda; ciclo de cobrança (anual/mensal) e quem emite nota; o "financeiro do Edu" **não existe** (greenfield) | 22 ⚠️ (§15) |
| B10 | **Trial/piloto/freemium** | duração do período gratuito, limites de uso e o que fica travado antes da conversão | 22 ⚠️ (§15) |
| B11 | **COGS (estrutura de custos)** | CDN/assets, TTS/áudio, chamadas de IA (Q6), infra (Railway/Redis), storage de telemetria — insumo do **preço-piso comercial**; **nenhuma** escolha de custo/infra pode rebaixar o produto abaixo do **piso de desempenho** (P17); os **números** de infra são da Seção [14](14-infra-deploy-dr.md) | 22 (mapa de custos); números = [14](14-infra-deploy-dr.md) |
| B12 | **Onboarding comercial & contratação** | o fluxo do "go" comercial; o **consentimento** (Seção [12](12-seguranca-privacidade.md)) e o **vínculo** (Seção [10](10-professor-familia.md)); o **provisionamento** (Seções [20](20-migracao-importacao.md)/[21](21-suporte-operacao.md)); o **SLA por plano** (pós-B7) que a Seção [21](21-suporte-operacao.md) **fecha/executa** | 22 (contrato); consentimento = [12](12-seguranca-privacidade.md); SLA = [21](21-suporte-operacao.md) |
| B13 | **Controle de uso & antipirataria** | contar escolas/alunos **ativos** e **impor o limite SÓ no lado do adulto** (alertar o gestor, travar matrícula administrativa/expansão) — **jamais** negar jogo a uma criança já matriculada (P7/P8); a **ação de imposição** é decisão do dono (o gatilho arquitetural ">30 escolas" é de escala, não teto comercial) | 22 ⚠️ (imposição — §15) |
| B14 | **Métricas de negócio** | ativação/churn de escola, LTV, alunos ativos por licença; a Seção [17](17-telemetria-metricas.md) fornece os **sinais de produto** (ex.: alunos ativos/uso); a **definição das métricas comerciais** (LTV, churn de escola) é da **22** | 22 (define métricas comerciais) ⚠️ (metas — §15); sinais de produto = [17](17-telemetria-metricas.md) |
| B15 | **Roadmap de monetização** | em que **fase** a cobrança real entra (hoje **piloto gratuito**); cruza com a **definição de lançamento comercial** da Seção [23](23-roadmap.md) | 22 ⚠️ (§15); fase = [23](23-roadmap.md) |
| B16 | **Plataformas-alvo & distribuição** | além do PWA instalável (padrão atual, **sem loja**), publicar em Play/App Store/Chromebook? A **política de compra-in-app das lojas colide com P7** — decidir com cuidado | 22 ⚠️ (§15) |
| B17 | **Formato do passe gratuito** | os pontos ⚠️ do dono são **nº de trilhos**, **linear × por níveis** e **duração** (~6–8 semanas); o **tipo de recompensa é fixo — só cosméticos, JAMAIS vantagem** (não negociável — P7/P8/ADR-22-C); a **economia** (moedas/XP/estrelas, curva) é da Seção [05](05-sistemas-de-jogo.md) e a **operação** da Seção [19](19-liveops.md) | 22 (formato) ⚠️ (§15); economia = [05](05-sistemas-de-jogo.md); operação = [19](19-liveops.md) |

### 10. Arquitetura técnica
Onde a monetização **tocará** o código (quase tudo **greenfield**):
- **Licença/plano** — uma entidade nova (Licença/Plano por escola) **não existe** hoje; a `Escola` só tem
  `status ativa|inativa`. **A construir (▢)** quando a unidade (B6) e os planos (B7) forem decididos.
- **Gating** — **reusa** a `Configuracao` (KV por escola) com o namespace `quest.*` (mecanismo/valores = Seção
  [19](19-liveops.md)); falta o **código de leitura** do `quest.*` (hoje aspiracional).
- **Firewall/ledger** — o **ledger imutável** de moedas (P14) **ainda não é tabela** (só docstring `perfil.py`); a
  **construção da tabela do ledger é da Seção [05](05-sistemas-de-jogo.md)** (economia/mecânica) — a 22 só **impõe a
  trava** de que ela **nasce sem** nenhum ponto de entrada de dinheiro real (B3).
- **Faturamento** — **inexistente**; qualquer integração de cobrança é nova e **fora** do Edu atual.
- **Antipirataria** — a contagem de escolas/alunos ativos (B13) usa dados que já existem; a **imposição do limite** é nova.

### 11. Dependências com outros módulos
**Consome / referencia:**
- **Seção [01](01-principios-imutaveis.md)** — as travas **imutáveis** (P7/P8/P18/P6/P14) que o modelo **não** pode contrariar.
- **Seção [05](05-sistemas-de-jogo.md)** — a **economia** de moedas/estrelas/XP e o **ledger imutável** (a 22 crava a gratuidade, não a economia).
- **Seção [19](19-liveops.md)** — o **mecanismo** de gating (`Configuracao`/`quest.*`), as feature flags e a **operação** do passe.
- **Seção [21](21-suporte-operacao.md)** — o **SLA operacional** e o **onboarding operacional** (a 22 fornece o **mapa de planos**; a 21 **fecha** o SLA por plano).
- **Seção [12](12-seguranca-privacidade.md)** / **Seção [10](10-professor-familia.md)** — a **base legal** (a 12 **decide** qual é), o **consentimento** e o **vínculo** que a contratação invoca.
- **Seção [17](17-telemetria-metricas.md)** — os **sinais de produto** (uso/alunos ativos) sobre os quais a 22 compõe as métricas de negócio.
- **Seção [14](14-infra-deploy-dr.md)** — os **números** de infra (COGS).
- **Seção [23](23-roadmap.md)** — a **fase** de lançamento comercial.
- **Apêndice A.8** — o **glossário de negócio** (licença, mantenedora, comprador vs jogador, LTV, churn, ativação, piloto).

**Alimenta:**
- **Apêndice F** — os checklists comerciais e o estado **"sem licença/recurso desligado"**.
- **Seção [21](21-suporte-operacao.md)** — o **mapa de planos** que fecha o SLA por plano e o gating de ativação.

**O que quebra se mudar:** se a 22 definir a **unidade** (B6) e os **planos** (B7), a Seção [19](19-liveops.md)
**materializa** o gating por licença e a Seção [21](21-suporte-operacao.md) **fecha** o SLA por plano; se elevar a
gratuidade a **princípio** (C.20), o passe pago fica **permanentemente** vedado.

### 12. Casos extremos (Edge Cases)
- **Loja das plataformas exige IAP** (Apple/Google) → **conflita com P7**; distribuir por loja **só** se a política
  não forçar compra-in-app na criança (B16, §15).
- **Escola excede o limite da licença** → o controle de uso **conta e impõe só no lado do adulto** (B13; alertar o gestor, travar matrícula administrativa/expansão); a criança **nunca** é bloqueada por isso (o limite é comercial, do adulto).
- **Recurso do plano desligado** → a tela é **"recurso desligado"** (estado da Seção [19](19-liveops.md)), **nunca** um paywall na criança (B5).
- **Alguém tenta "vender" moeda de jogo** → **proibido** (B3); a moeda é ganha jogando e não converte em dinheiro.
- **Passe pago disfarçado** ("trilho premium grátis mas com vantagem") → **proibido** (B2/B17): recompensa **só cosmética**.
- **Piloto gratuito sem fim definido** → o trial precisa de **duração e limites** (B10, §15) para não virar produto grátis por omissão.
- **Ledger de moeda ainda não existe** → antes de qualquer "encanamento comercial", o ledger imutável (P14) nasce **sem** entrada de dinheiro real (§13/§15).

### 13. Escalabilidade futura
- **Entidade de Licença/Plano** por escola — quando B6/B7 forem decididos.
- **Código de leitura do gating `quest.*`** — materializar o mapa recurso↔plano (mecanismo = Seção [19](19-liveops.md)).
- **Ledger imutável de moedas (P14)** — a **tabela é construída pela Seção [05](05-sistemas-de-jogo.md)** (economia); a 22 só **exige** que nasça **sem** ponto de dinheiro real (pré-requisito do firewall B3).
- **Integração de faturamento** — quando o ciclo de cobrança (B9) for decidido; hoje o Edu não cobra.
- **Passe/temporada/loja** — nascem **sem** trilho pago e **sem** compra por dinheiro (B2/B3).
- **Multi-moeda / multi-país** — se a expansão passar do Brasil (⚠️ futuro).

### 14. Checklist de implementação
**Este capítulo é greenfield (zero código comercial). O checklist rastreia decisões de MODELO — `[x]` = trava do
modelo **cravada** (não implementável, é princípio); `⚠️` = decisão pendente do dono (§15); `▢` = encanamento a
construir depois da decisão. Liga ao Apêndice F:**
- [x] **Comprador = escola/rede**; criança nunca é fonte de receita (P7) (B1).
- [x] **Passe gratuito & zero compra in-app** — já imutável por P7 (B2).
- [ ] ⚠️ **Elevar a gratuidade a princípio autônomo** (ADR C.20) (B2/C.20).
- [ ] ▢ **Firewall** economia × dinheiro real (ledger P14 sem entrada de dinheiro; ledger/sumidouro = Seção [05](05-sistemas-de-jogo.md)) (B3).
- [x] **Sem anúncios/rastreamento** reafirmado (P18) (B4).
- [x] **Gating nunca vira paywall na criança** (P8; limite da Seção [19](19-liveops.md) C18) (B5).
- [ ] ⚠️ **Unidade de licenciamento** decidida (B6).
- [ ] ⚠️ **Planos/tiers & mapa recurso↔plano** definidos (B7).
- [ ] ▢ **Gating por licença** reusando `Configuracao`/`quest.*` (mecanismo = Seção [19](19-liveops.md)) (B8).
- [ ] ⚠️ **Precificação & ciclo de faturamento** definidos (B9).
- [ ] ⚠️ **Trial/piloto/freemium** definido (B10).
- [ ] ▢ **COGS** mapeado (números = Seção [14](14-infra-deploy-dr.md)) (B11).
- [ ] ▢ **Onboarding comercial** amarrado a consentimento (Seção [12](12-seguranca-privacidade.md)) + SLA por plano (pós-B7 = Seção [21](21-suporte-operacao.md)) (B12).
- [ ] ⚠️ **Controle de uso & antipirataria** — imposição só no lado do adulto (B13).
- [ ] ⚠️ **Métricas de negócio** (sinais de produto = Seção [17](17-telemetria-metricas.md)) (B14).
- [ ] ⚠️ **Roadmap de monetização** por fase (cruza Seção [23](23-roadmap.md)) (B15).
- [ ] ⚠️ **Plataformas-alvo & distribuição** (PWA × lojas; IAP × P7) (B16).
- [ ] ⚠️ **Formato do passe gratuito** — nº de trilhos/linear×níveis/duração (recompensa é fixa: só cosméticos; economia = Seção [05](05-sistemas-de-jogo.md); operação = Seção [19](19-liveops.md)) (B17).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 22, não decisões autônomas (10 perguntas
registradas no `INDICE.md`):

- ⚠️ **C.20 — Elevar a gratuidade a princípio.** Confirmar **"passe 100% gratuito e zero compras in-app em TODAS as
  fases, permanentemente"** como **princípio imutável** (ADR candidato C.20). É a **pendência-mãe** que ancora P7 e toda a Seção 22.
- ⚠️ **B6 / 22.3 — Unidade de licenciamento.** Escola inteira × rede/mantenedora × por aluno ativo × por turma? É o
  **parâmetro-mestre** que dita todo o gating e o faturamento (hoje a `Escola` só tem `status ativa|inativa`).
- ⚠️ **B7 / 22.4 — Planos/tiers & recursos por plano.** Haverá níveis? Quais recursos (social, IA, relatórios
  avançados) em cada um? É o **mapa recurso↔plano** sem o qual não há gating.
- ⚠️ **B9 / 22.5/22.7 — Precificação & faturamento.** Faixa de preço, unidade (ex.: R$/aluno/ano) e moeda; ciclo
  (anual/mensal), quem emite nota, e a integração com um "financeiro" que **não existe**.
- ⚠️ **B10 / 22.6 — Trial/piloto/freemium.** Duração do período gratuito, limites de uso e o que trava antes da conversão.
- ⚠️ **B17 / 22.10 — Formato definitivo do passe gratuito.** Os pontos em aberto são **nº de trilhos**, **linear ×
  por níveis** e **duração** (~6–8 semanas) — coordenados com a Seção [05](05-sistemas-de-jogo.md) (economia/curva de
  XP) e a Seção [19](19-liveops.md) (operação/ciclo). O **tipo de recompensa NÃO está em aberto: é só cosméticos,
  JAMAIS vantagem** (não negociável — P7/P8/ADR-22-C).
- ⚠️ **B16 / 22.11/22.12 — Plataformas-alvo & distribuição.** Além do PWA (sem loja), apps nativos e/ou publicação em
  Play/App Store/Chromebook? A **política de IAP das lojas colide com P7**.
- ⚠️ **B14 / 22.17 — Métricas de negócio.** Metas de ativação/churn de escola, LTV, alunos ativos por licença
  (sinais de produto = Seção [17](17-telemetria-metricas.md); definição das métricas comerciais = 22).
- ⚠️ **B15 / 22.18 — Roadmap de monetização.** Em que fase a **cobrança real** entra (hoje tudo é **piloto
  gratuito**) — cruza com a definição de lançamento comercial da Seção [23](23-roadmap.md).
- ⚠️ **Base legal (com a Seção [12](12-seguranca-privacidade.md)).** A 22 **não** nomeia a base legal — a Seção
  [12](12-seguranca-privacidade.md) **decide** qual se aplica (execução de contrato, legítimo interesse ou
  consentimento), e a base **por fluxo** (jogo/telemetria/social) é **⚠️ do jurídico** (Seção [12](12-seguranca-privacidade.md) §15).

### 16. ADR (Architecture Decision Record)
- **ADR-22-A — A escola paga; a criança joga de graça.** A receita é **100% da licença** da escola/rede (B2B/B2G);
  a **criança nunca** é fonte de receita (P7 + `00-visao`). A 22 monetiza a **escola**, não a criança.
- **ADR-22-B — Passe gratuito e zero compra in-app, imutáveis.** O **passe é gratuito**, **sem trilho pago**, e **não
  há compra por dinheiro** dentro do app (P7); a economia de moedas é **fechada** e **auditável** (P14). Proposta:
  **elevar a princípio** (ADR candidato **C.20**) para vedar o passe pago **permanentemente**. *Confirmação do dono pendente (§15).*
- **ADR-22-C — Firewall economia-do-jogo × dinheiro real.** Moedas/estrelas/XP **jamais** convertem em
  dinheiro/compra/reembolso; qualquer futura loja/passe/**ledger** nasce **sem** ponto de entrada de dinheiro real. A
  **economia e a tabela do ledger** são da Seção [05](05-sistemas-de-jogo.md); a 22 só **garante o firewall** (a trava).
- **ADR-22-D — Gating por licença opera no nível ESCOLA, nunca cobra a criança.** O que cada plano compra liga/desliga
  recursos **do adulto/escola** via `Configuracao`/`quest.*` (mecanismo = Seção [19](19-liveops.md)); o gating
  **nunca** vira paywall, FOMO ou trilho pago na tela da criança (P8; Seção [19](19-liveops.md) C18). A 22 fornece o
  **mapa recurso↔plano**; a 19 o **executa**.

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Monetization & Business Model

### 1. Objective
To set **how the product generates revenue** — **licensing by the school/network**, a **100% free pass** and
**zero in-app purchases** — and to make **everything that depends on the owner explicit**, so the dev builds the
"commercial plumbing" **without making product decisions and without violating the immutable principles**. It decides
the **model**; it does **not** decide the game mechanics (Section [05](05-sistemas-de-jogo.md)), the config
values/operation (Section [19](19-liveops.md)) nor the LGPD policy (Section [12](12-seguranca-privacidade.md)) — it
only **references** them. It feeds **Appendix F**.

### 2. Context
In **Hub → Edu → Quest**, the **buyer is the school/network** (`00-visao-e-norte.md`: "Buyer: the school/network
licenses the product"; the child is the **Player**, never the buyer — **P7**). It is a **B2B** model (private school)
and **B2G** (municipal network/department — the code already carries `REDE_CARAGUA` with ~28 schools). **Current state
(Q0) — commercial greenfield:**
- **No monetization in the code** — the `Escola` has `nome`/`cidade`/`estado`/`logotipo_url`/`ano_letivo_ativo`/`status`
  (`ativa|inativa`)/`created_at`; **no** plan, tier, seat, license, support contact or contract dates. **No** payment/subscription
  route; **no** `stripe`/`pix`/`boleto`/`checkout`. The "Edu financials" **do not exist**.
- **No in-app purchase (P7 confirmed in code)** — changing avatar/appearance is **free**; the 6 base characters are
  **free**; there is **no** money shop, no paid loot box, no ad.
- **The gating has its box ready** — `Configuracao` (per-school KV) is the **mechanism** to turn a feature on/off;
  today it only serves Edu (`pesos.*`/`gamificacao.*`/`desempate.*`). The **`quest.*`** namespace (owner = Section
  [19](19-liveops.md)) is **aspirational** — declared in a docstring, with **no** code reading/writing a key.
- **The game economy exists as *earned*** — `moedas_base=10`, `moedas` on the profile (a cache; the truth is the
  ledger), `moedas_ganhas` per attempt. It is **game currency earned by playing**, **never** real money.
- **Not yet present** — the **immutable coin ledger** (P14) as a **table** (only a docstring); the `quest.*` gating
  **read code**; any **shop/inventory/season/pass** (planned for future phases — Section [23](23-roadmap.md)).
- **Distribution** — today a **PWA installable without a store** (`apps/mobile` produces a sideload APK, "no store").

This chapter **nails** the model's immutable locks and **records** what the owner needs to decide.

### 3. Feature philosophy
**"The school pays; the child plays for free, forever."** Constela's monetization is **B2B/B2G** by principle —
revenue comes from the **school/network license**, and the child's experience is **money-free**. Principles Section
22 **cannot contradict** (they are immutable — Section [01](01-principios-imutaveis.md)): **P7** (no in-app purchase;
currency is only earned by playing; no buyable currency, no paid surprise box, no aggressive FOMO; the pass is
**free**); **P8** (zero dark patterns — no "lives" that force waiting/payment); **P18** (no ads and no third-party
tracking SDK); **P6** (error never punishes — no coin/star loss); **P14** (economy **auditable** by an immutable
ledger). Commercial gating turns features on/off **for the adult/school** — it **never** becomes a paywall, an
anxious countdown or a paid track on the child's screen.

Link: the **coin economy** (Section [05](05-sistemas-de-jogo.md)) is **closed** — the coin is **earned** by playing
and **what it buys/spends on is Section [05](05-sistemas-de-jogo.md)'s** (the cosmetic shop is a future phase; today
changing the avatar is free); it **never** crosses into real money. 22 only **guarantees the firewall** and **nails
the free-ness**; it does not redefine the economy.

### 4. The experience the player should feel
The child does **not** see a price, plan, ad or buy button — **ever**. They see a **complete, free** game: the pass
is free, cosmetics are earned by playing, and nothing pressures them to pay. **The school/manager** (the buyer) feels
**transparency**: they know exactly what the license buys, no fine print, no hidden charge to the child. **The
family** hears, with relief, that there are **no purchases** (the persona Dona Cláudia demands "privacy, zero
purchases, transparency").

### 5. Complete flow
The **commercial cycle**, from interest to renewal (⭐ = exists in Q0; ▢ = to build/decide):

1. **Contact/sale** ▢ — the school/network shows interest; **pilot/trial** (format ⚠️ §15).
2. **Contract & consent** ▢ — the **license instrument** defines what the plan buys; the guardians' **consent** and
   the **binding** (Section [10](10-professor-familia.md)) are collected in the flow. The **applicable legal basis**
   (contract execution, legitimate interest or consent) is **Section [12](12-seguranca-privacidade.md)'s decision** —
   22 does **not** name it.
3. **Provisioning & activation** ⭐/▢ — the school is created and provisioned (**operational** = Section
   [21](21-suporte-operacao.md); **technical/ETL** = Section [20](20-migracao-importacao.md)); **gating** turns on the
   plan's features (mechanism = `Configuracao`/`quest.*` of Section [19](19-liveops.md)).
4. **Usage** ⭐/▢ — today ⭐ the child **enters and customizes** the avatar/name **for free** (login + profile exist in
   Q0); the **game loop**, the **free pass** and the **per-license gating** are ▢ (greenfield — §2/§10). Once they
   exist, gating limits **adult/school** features per the license and **never** charges the child.
5. **Usage control** ▢ — counting active schools/students and enforcing the **license limit** (anti-piracy).
6. **Business metrics** ▢ — school activation/churn, LTV, active students per license (product signals = Section [17](17-telemetria-metricas.md); commercial-metric definition = 22).
7. **Renewal/expansion** ▢ — the **execution** (CS, QBR) is run by Section [21](21-suporte-operacao.md); the **model**
   (what each plan buys) is from here.

### 6. Interface (when it exists)
**No commercial surface touches the child** (P7). The **adult** surfaces (contract, license panel, billing) are an
**owner decision** (§15) and, when they exist, follow Section [07](07-ux-fluxos-navegacao.md) for the layout. The
**"no license / feature off"** screen (gating state) is operated by Section [19](19-liveops.md) and listed in
Appendix F. There is **no** money shop screen anywhere.

### 7. UX
The "commercial UX" is the **adult's** and **honest** (P8): the manager understands what the license buys **without
fine print**; the family sees **"no purchases"** explicitly. **No** dark pattern — no anxious countdown, no "today
only", no disguised paywall. The **social default is opt-in** (Section [09](09-social.md)'s decision); the commercial
side does **not** loosen it.

### 8. Game Design
**N/A as to creating an economy** — the **economy** (coins/stars/XP) is Section [05](05-sistemas-de-jogo.md)'s and
the pass **operation** is Section [19](19-liveops.md)'s; 22 only decides the pass **model/format** (B17). 22
contributes **two** game-design locks **imposed by the business**: (1) the **pass
is free** — there is never a parallel paid track; (2) the **firewall** — no buyable reward, no sold game advantage;
the free pass gives **cosmetics only** (never a paid competitive advantage disguised as "free"). Thus monetization
does **not** corrupt the design (no pay-to-win).

### 9. Business rules
The **monetization norms** (the source of the model; the game **mechanics** are Section [05](05-sistemas-de-jogo.md)'s,
the config **values** Section [19](19-liveops.md)'s, the LGPD **policy** Section [12](12-seguranca-privacidade.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| B1 | **Buyer = school/network** | the **school/network licenses** the product (B2B/B2G); the **child is never** a revenue source (P7) | 22; principle = [01](01-principios-imutaveis.md) |
| B2 | **Free pass, zero in-app purchase** | the **season pass is 100% free**, **no parallel paid track**; **no** buyable currency, paid surprise box or aggressive FOMO — **already immutable via P7** (raising it to an **autonomous principle** = candidate ADR **C.20**, ⚠️ §15) | 22 (reaffirms P7); C.20 = ⚠️ §15 |
| B3 | **Economy × money firewall** | coins/stars/XP **never** convert into money/purchase/refund; the economy is **auditable** by the **immutable ledger** (P14); what the coin **buys/spends on** is Section [05](05-sistemas-de-jogo.md)'s — 22 only guarantees the firewall | 22 (firewall); economy/sink = [05](05-sistemas-de-jogo.md)/P14 |
| B4 | **No ads/tracking** | **no** ad and **no** third-party tracking SDK in the child's experience (P18) | 22 (reaffirms); policy = [12](12-seguranca-privacidade.md)/P18 |
| B5 | **Gating never becomes a child paywall** | commercial gating turns **adult/school** features on/off; it **never** creates a paywall, anxious countdown or paid track on the child's screen (P8; Section [19](19-liveops.md) C18) | 22; limit = [19](19-liveops.md) |
| B6 | **Licensing unit** | whole school × network/holder × per active student × per class — the **master parameter** that dictates all gating and billing | 22 ⚠️ (§15) |
| B7 | **Plans/tiers & feature↔plan map** | whether there are tiers and what each one buys (social, AI, advanced reports); it is the **feature↔plan map** Section [19](19-liveops.md) executes via `quest.*` | 22 (map) ⚠️ (§15); mechanism = [19](19-liveops.md) |
| B8 | **Gating by license** | the on/off mechanism **reuses** `Configuracao`/`quest.*` (mechanism owner = Section [19](19-liveops.md)); 22 provides the **plan→flags (which features) map**; the **values** of the `quest.*` keys are Section [19](19-liveops.md)'s | 22 (flag map); mechanism/values = [19](19-liveops.md) |
| B9 | **Pricing & billing** | price range, unit (e.g. BRL/student/year) and currency; billing cycle (annual/monthly) and who issues the invoice; the "Edu financials" **do not exist** (greenfield) | 22 ⚠️ (§15) |
| B10 | **Trial/pilot/freemium** | duration of the free period, usage limits and what stays locked before conversion | 22 ⚠️ (§15) |
| B11 | **COGS (cost structure)** | CDN/assets, TTS/audio, AI calls (Q6), infra (Railway/Redis), telemetry storage — an input to the **commercial floor-price**; **no** cost/infra choice may drop the product below the **performance floor** (P17); the infra **numbers** are Section [14](14-infra-deploy-dr.md)'s | 22 (cost map); numbers = [14](14-infra-deploy-dr.md) |
| B12 | **Commercial onboarding & contracting** | the commercial "go" flow; the **consent** (Section [12](12-seguranca-privacidade.md)) and the **binding** (Section [10](10-professor-familia.md)); the **provisioning** (Sections [20](20-migracao-importacao.md)/[21](21-suporte-operacao.md)); the **per-plan SLA** (post-B7) Section [21](21-suporte-operacao.md) **closes/executes** | 22 (contract); consent = [12](12-seguranca-privacidade.md); SLA = [21](21-suporte-operacao.md) |
| B13 | **Usage control & anti-piracy** | count **active** schools/students and **enforce the limit ONLY on the adult side** (alert the manager, block administrative enrollment/expansion) — **never** deny play to an already-enrolled child (P7/P8); the **enforcement action** is an owner decision (the ">30 schools" architectural trigger is about scale, not a commercial cap) | 22 ⚠️ (enforcement — §15) |
| B14 | **Business metrics** | school activation/churn, LTV, active students per license; Section [17](17-telemetria-metricas.md) provides the **product signals** (e.g. active students/usage); the **definition of the commercial metrics** (LTV, school churn) is **22's** | 22 (defines commercial metrics) ⚠️ (targets — §15); product signals = [17](17-telemetria-metricas.md) |
| B15 | **Monetization roadmap** | at which **phase** real charging begins (today a **free pilot**); crosses with the **commercial-launch definition** of Section [23](23-roadmap.md) | 22 ⚠️ (§15); phase = [23](23-roadmap.md) |
| B16 | **Target platforms & distribution** | beyond the installable PWA (current default, **no store**), publish on Play/App Store/Chromebook? The **stores' in-app-purchase policy collides with P7** — decide carefully | 22 ⚠️ (§15) |
| B17 | **Free-pass format** | the owner's ⚠️ points are **number of tracks**, **linear × tiered** and **duration** (~6–8 weeks); the **reward type is fixed — cosmetics only, NEVER an advantage** (non-negotiable — P7/P8/ADR-22-C); the **economy** (coins/XP/stars, curve) is Section [05](05-sistemas-de-jogo.md)'s and the **operation** Section [19](19-liveops.md)'s | 22 (format) ⚠️ (§15); economy = [05](05-sistemas-de-jogo.md); operation = [19](19-liveops.md) |

### 10. Technical architecture
Where monetization **will touch** code (almost all **greenfield**):
- **License/plan** — a new entity (License/Plan per school) **does not exist** today; the `Escola` only has
  `status ativa|inativa`. **To build (▢)** once the unit (B6) and plans (B7) are decided.
- **Gating** — **reuses** `Configuracao` (per-school KV) with the `quest.*` namespace (mechanism/values = Section
  [19](19-liveops.md)); the `quest.*` **read code** is missing (aspirational today).
- **Firewall/ledger** — the **immutable coin ledger** (P14) **is not yet a table** (only a `perfil.py` docstring); the
  **ledger table is built by Section [05](05-sistemas-de-jogo.md)** (economy/mechanics) — 22 only **imposes the lock**
  that it is **born without** any real-money entry point (B3).
- **Billing** — **nonexistent**; any billing integration is new and **outside** the current Edu.
- **Anti-piracy** — counting active schools/students (B13) uses existing data; **enforcing the limit** is new.

### 11. Dependencies on other modules
**Consumes / references:**
- **Section [01](01-principios-imutaveis.md)** — the **immutable** locks (P7/P8/P18/P6/P14) the model **cannot** contradict.
- **Section [05](05-sistemas-de-jogo.md)** — the **economy** of coins/stars/XP and the **immutable ledger** (22 nails free-ness, not the economy).
- **Section [19](19-liveops.md)** — the gating **mechanism** (`Configuracao`/`quest.*`), the feature flags and the pass **operation**.
- **Section [21](21-suporte-operacao.md)** — the **operational SLA** and the operational onboarding (22 provides the **plan map**; 21 **closes** the per-plan SLA).
- **Section [12](12-seguranca-privacidade.md)** / **Section [10](10-professor-familia.md)** — the **legal basis** (12 **decides** which applies), the **consent** and the **binding** contracting invokes.
- **Section [17](17-telemetria-metricas.md)** — the **product signals** (usage/active students) 22 composes the business metrics over.
- **Section [14](14-infra-deploy-dr.md)** — the infra **numbers** (COGS).
- **Section [23](23-roadmap.md)** — the commercial-launch **phase**.
- **Appendix A.8** — the **business glossary** (license, holder, buyer vs player, LTV, churn, activation, pilot).

**Feeds:**
- **Appendix F** — the commercial checklists and the **"no license/feature off"** state.
- **Section [21](21-suporte-operacao.md)** — the **plan map** that closes the per-plan SLA and activation gating.

**What breaks if it changes:** if 22 defines the **unit** (B6) and the **plans** (B7), Section [19](19-liveops.md)
**materializes** per-license gating and Section [21](21-suporte-operacao.md) **closes** the per-plan SLA; if it raises
free-ness to a **principle** (C.20), a paid pass is **permanently** barred.

### 12. Edge cases
- **Platform stores require IAP** (Apple/Google) → **conflicts with P7**; distribute via a store **only** if the
  policy does not force an in-app purchase on the child (B16, §15).
- **School exceeds the license limit** → usage control **counts and enforces on the adult side** (B13; alert the manager, block administrative enrollment/expansion); the child is **never** blocked by it (the limit is commercial, the adult's).
- **A plan feature is off** → the screen is **"feature off"** (a Section [19](19-liveops.md) state), **never** a child paywall (B5).
- **Someone tries to "sell" game currency** → **forbidden** (B3); the coin is earned by playing and does not convert to money.
- **Disguised paid pass** ("premium track free but with an advantage") → **forbidden** (B2/B17): reward is **cosmetic only**.
- **Open-ended free pilot** → the trial needs a **duration and limits** (B10, §15) so it does not become a free product by omission.
- **The coin ledger does not exist yet** → before any "commercial plumbing", the immutable ledger (P14) is born **without** a real-money entry (§13/§15).

### 13. Future scalability
- **License/Plan entity** per school — once B6/B7 are decided.
- **`quest.*` gating read code** — materialize the feature↔plan map (mechanism = Section [19](19-liveops.md)).
- **Immutable coin ledger (P14)** — the **table is built by Section [05](05-sistemas-de-jogo.md)** (economy); 22 only **requires** it be born **without** a real-money point (a prerequisite of firewall B3).
- **Billing integration** — once the billing cycle (B9) is decided; today Edu does not charge.
- **Pass/season/shop** — born **without** a paid track and **without** money purchases (B2/B3).
- **Multi-currency / multi-country** — if expansion goes beyond Brazil (⚠️ future).

### 14. Implementation checklist
**This chapter is greenfield (zero commercial code). The checklist tracks MODEL decisions — `[x]` = a **locked** model
lock (not implementable, it is a principle); `⚠️` = an owner decision pending (§15); `▢` = plumbing to build after the
decision. Links to Appendix F:**
- [x] **Buyer = school/network**; the child is never a revenue source (P7) (B1).
- [x] **Free pass & zero in-app purchase** — already immutable via P7 (B2).
- [ ] ⚠️ **Raise free-ness to an autonomous principle** (ADR C.20) (B2/C.20).
- [ ] ▢ **Firewall** economy × real money (P14 ledger with no money entry; ledger/sink = Section [05](05-sistemas-de-jogo.md)) (B3).
- [x] **No ads/tracking** reaffirmed (P18) (B4).
- [x] **Gating never becomes a child paywall** (P8; Section [19](19-liveops.md) C18's limit) (B5).
- [ ] ⚠️ **Licensing unit** decided (B6).
- [ ] ⚠️ **Plans/tiers & feature↔plan map** defined (B7).
- [ ] ▢ **Gating by license** reusing `Configuracao`/`quest.*` (mechanism = Section [19](19-liveops.md)) (B8).
- [ ] ⚠️ **Pricing & billing cycle** defined (B9).
- [ ] ⚠️ **Trial/pilot/freemium** defined (B10).
- [ ] ▢ **COGS** mapped (numbers = Section [14](14-infra-deploy-dr.md)) (B11).
- [ ] ▢ **Commercial onboarding** tied to consent (Section [12](12-seguranca-privacidade.md)) + per-plan SLA (post-B7 = Section [21](21-suporte-operacao.md)) (B12).
- [ ] ⚠️ **Usage control & anti-piracy** — enforcement only on the adult side (B13).
- [ ] ⚠️ **Business metrics** (product signals = Section [17](17-telemetria-metricas.md)) (B14).
- [ ] ⚠️ **Monetization roadmap** per phase (crosses Section [23](23-roadmap.md)) (B15).
- [ ] ⚠️ **Target platforms & distribution** (PWA × stores; IAP × P7) (B16).
- [ ] ⚠️ **Free-pass format** — number of tracks/linear×tiered/duration (reward is fixed: cosmetics only; economy = Section [05](05-sistemas-de-jogo.md); operation = Section [19](19-liveops.md)) (B17).

### 15. Open questions
Each item is an **owner decision** (⚠️); the defaults are 22's **proposals**, not autonomous decisions (10 questions
recorded in `INDICE.md`):

- ⚠️ **C.20 — Raise free-ness to a principle.** Confirm **"100% free pass and zero in-app purchases in ALL phases,
  permanently"** as an **immutable principle** (candidate ADR C.20). It is the **mother pending** that anchors P7 and all of Section 22.
- ⚠️ **B6 / 22.3 — Licensing unit.** Whole school × network/holder × per active student × per class? It is the
  **master parameter** that dictates all gating and billing (today the `Escola` only has `status ativa|inativa`).
- ⚠️ **B7 / 22.4 — Plans/tiers & per-plan features.** Will there be tiers? Which features (social, AI, advanced
  reports) in each? It is the **feature↔plan map** without which there is no gating.
- ⚠️ **B9 / 22.5/22.7 — Pricing & billing.** Price range, unit (e.g. BRL/student/year) and currency; cycle
  (annual/monthly), who issues the invoice, and integration with a "financials" that **does not exist**.
- ⚠️ **B10 / 22.6 — Trial/pilot/freemium.** Duration of the free period, usage limits and what locks before conversion.
- ⚠️ **B17 / 22.10 — Definitive free-pass format.** The open points are **number of tracks**, **linear × tiered** and
  **duration** (~6–8 weeks) — coordinated with Section [05](05-sistemas-de-jogo.md) (economy/XP curve) and Section
  [19](19-liveops.md) (operation/cycle). The **reward type is NOT open: cosmetics only, NEVER an advantage**
  (non-negotiable — P7/P8/ADR-22-C).
- ⚠️ **B16 / 22.11/22.12 — Target platforms & distribution.** Beyond the PWA (no store), native apps and/or publishing
  on Play/App Store/Chromebook? The **stores' IAP policy collides with P7**.
- ⚠️ **B14 / 22.17 — Business metrics.** School activation/churn, LTV, active-students-per-license targets (product
  signals = Section [17](17-telemetria-metricas.md); commercial-metric definition = 22).
- ⚠️ **B15 / 22.18 — Monetization roadmap.** At which phase does **real charging** begin (today all is a **free
  pilot**) — crosses with Section [23](23-roadmap.md)'s commercial-launch definition.
- ⚠️ **Legal basis (with Section [12](12-seguranca-privacidade.md)).** 22 does **not** name the legal basis — Section
  [12](12-seguranca-privacidade.md) **decides** which applies (contract execution, legitimate interest or consent),
  and the **per-flow** basis (game/telemetry/social) is **⚠️ the legal team's** (Section [12](12-seguranca-privacidade.md) §15).

### 16. ADR (Architecture Decision Record)
- **ADR-22-A — The school pays; the child plays for free.** Revenue is **100% from the license** of the school/network
  (B2B/B2G); the **child is never** a revenue source (P7 + `00-visao`). 22 monetizes the **school**, not the child.
- **ADR-22-B — Free pass and zero in-app purchase, immutable.** The **pass is free**, with **no paid track**, and
  there is **no money purchase** inside the app (P7); the coin economy is **closed** and **auditable** (P14). Proposal:
  **raise it to a principle** (candidate ADR **C.20**) to bar a paid pass **permanently**. *Owner confirmation pending (§15).*
- **ADR-22-C — Game economy × real money firewall.** Coins/stars/XP **never** convert into money/purchase/refund; any
  future shop/pass/**ledger** is born **without** a real-money entry point. The economy **and the ledger table** are
  Section [05](05-sistemas-de-jogo.md)'s; 22 only **guarantees the firewall** (the lock).
- **ADR-22-D — License gating operates at the SCHOOL level, never charging the child.** What each plan buys turns
  **adult/school** features on/off via `Configuracao`/`quest.*` (mechanism = Section [19](19-liveops.md)); gating
  **never** becomes a paywall, FOMO or paid track on the child's screen (P8; Section [19](19-liveops.md) C18). 22
  provides the **feature↔plan map**; 19 **executes** it.

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
