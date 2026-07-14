# API interna do Matific — documentação de engenharia reversa

> **Escopo e método.** Esta documentação descreve a **API interna (privada)** que o
> painel do professor/administrador do Matific consome. Não é uma API pública nem
> documentada pelo fornecedor. Tudo aqui foi obtido **de forma legítima**, a partir
> da conta da própria escola, inspecionando o tráfego do navegador (DevTools) e a
> API que a página já chama quando o gestor está logado. Serve para o **Constela Edu**
> integrar automaticamente, sem depender de PDF.
>
> **Status de cada endpoint:** ✅ confirmado (corpo capturado) · 🔍 observado (visto na
> aba Network, corpo ainda a capturar) · ❓ provável (inferido pelo padrão).
>
> **Sem PII/segredos.** Exemplos são anonimizados; IDs reais e cookies de sessão NÃO
> entram aqui. Rode `tools/matific_crawler.py` (login manual) para completar os 🔍/❓.

---

## 1. Visão geral

- **Tipo:** API REST interna, consumida por um SPA **Angular** (Sentry `sentry.javascript.angular`).
- **Base URL:** `https://www.matific.com/api/v2/`
- **Formato:** JSON. Vários campos numéricos vêm como **string** (`"3914"`).
- **Versão vista:** `9.17.0` (header `baggage: sentry-release=9.17.0`).
- **API pública self-serve de data-out?** Não. Feeds oficiais existem só em contrato
  district/enterprise (OneRoster/Clever são para *rostering-in*, não para exportar
  desempenho). Por isso a coleta reproduz o que o professor faz no portal.

## 2. Autenticação

**Por COOKIE de sessão (Django), não por token.** Não há `Authorization: Bearer`,
não há JWT no header, e **não há refresh token** observável — a sessão é do lado do
servidor, renovada pelo próprio cookie enquanto válida.

Cookies relevantes (os demais são analytics — GA/Facebook/Hotjar):

| Cookie | Papel |
|---|---|
| `sessionid` | **Sessão** Django (autenticação). É o que autoriza as chamadas. |
| `csrftoken` | Token CSRF — necessário no header `X-CSRFToken` para **mutações** (POST/PUT/DELETE). Leituras (GET) não exigem. |
| `slatemath_user_id` | UUID do usuário logado. |
| `slatemath_user_type` | Papel: **`3` = professor/admin**. |
| `matific_language`, `slatemath_locale_iso` | Idioma (`pt-br` / `pt-BR`). |

**Como o Constela usa:** o navegador/robô loga (ou reusa a sessão logada do gestor) e
chama a API **same-origin** com `credentials: 'include'` — o cookie `sessionid` vai
junto automaticamente. Nenhum token precisa ser extraído.

> ⚠️ **reCAPTCHA v3 no login.** O login por senha é protegido por reCAPTCHA v3
> (pontuação de risco). IP de datacenter recebe nota baixa e é barrado de forma
> intermitente. Mitigações: **login manual** (o humano passa o captcha; usado pelo
> crawler e pelo bookmarklet do Constela) ou **proxy residencial** (`SYNC_PROXY_URL`).

## 3. Headers observados (em toda chamada)

```
accept: application/json, text/plain, */*
accept-language: pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7
referer: https://www.matific.com/bra/pt-br/teachers/admin/school-leaderboard
user-agent: <navegador>
sec-fetch-site: same-origin          # confirma que a API é same-origin
baggage / sentry-trace               # rastreio Sentry — NÃO obrigatório
```
Para **mutações**, some `X-CSRFToken: <csrftoken>` (não confirmado — só leituras foram exercitadas).

---

## 4. Endpoints CONFIRMADOS

### 4.1 ✅ Placar por ALUNO (dados de desempenho da escola)

```
GET /api/v2/reports/leaderboard/school_student/?duration=<periodo>&school_id=<SCHOOL_UUID>
```
- **Auth:** cookie de sessão. **Query:** `duration` (ver §8), `school_id` (UUID).
- **Resposta:** lista com **um** objeto agregado + `data[]` por aluno.

```jsonc
[{
  "school_id": "<SCHOOL_UUID>",
  "total_points": 38163,          // estrelas totais da escola
  "school_score": 180.01,         // média da escola
  "students_count_in_school": 212,
  "data": [{
    "account_id": "ALUNO A",       // nome ABREVIADO (o exibido na tela)
    "rank_score": null,
    "score": "362",                // ESTRELAS do aluno (string)
    "grade_code": "3",             // série
    "activities_completed": "100", // atividades finalizadas (string)
    "schoolName": "ESCOLA X, Brazil ",
    "klassName": "3 ANO B (300396804)",  // turma (o (nº) é o código SED)
    "region": 4,
    "id": "acda7e37...",           // hash; alunos vazios trazem MD5-de-vazio
    "uuid": "<STUDENT_UUID>"        // chave p/ cruzar com o student-leaderboard
  }]
}]
```
> **Pontuação média** da tela = `score / activities_completed` (ex.: 362/100 = 3.62).
> Linhas-fantasma no fim (`account_id`/`uuid` vazios) devem ser ignoradas.

### 4.2 ✅ Placar por ALUNO da competição (com NOME COMPLETO)

```
GET /api/v2/competition-v2/<COMPETITION_UUID>/school/<SCHOOL_UUID>/student-leaderboard/
```
- **Uso no Constela:** cruzar `student_id` (== `uuid` do 4.1) → resolve o nome
  abreviado para o **nome completo** matriculável.

```jsonc
{ "leaderboard": [{
  "accuracy": "90.65",            // precisão % na competição
  "goal_score": 250,
  "school_id": "<SCHOOL_UUID>",
  "school_name": "ESCOLA X, CIDADE",
  "total_attempts": 62,
  "student_count": null,
  "percentile": -1,
  "class_id": "<CLASS_UUID>",
  "class_name": "4 ANO A (300397061)",
  "teacher_name": "A Sobrenome",  // NÃO confiável (veio o dono da conta p/ todas)
  "class_grade": 4,
  "rank": null,
  "student_id": "<STUDENT_UUID>", // == uuid do school_student
  "student_name": "Nome Completo Do Aluno"
}]}
```

---

## 5. Endpoints OBSERVADOS (na aba Network — corpo a capturar)

Vistos ao abrir o **Placar da Escola**; nomes reais na coluna *Name* do DevTools.
Rode o crawler (§10) para capturar os corpos e promovê-los a ✅.

| Método | Caminho (provável) | Observado | O que deve ser |
|---|---|---|---|
| GET | `/api/v2/reports/leaderboard/school_klass/?duration=&school_id=` | 🔍 1.7 kB | Placar por **TURMA** (Turmas líderes) |
| GET | `/api/v2/competition-v2/<comp>/school/<school>/class-leaderboard/` | 🔍 1.9 kB | Placar de **turmas** na competição |
| GET | `/api/v2/competition-v2/?require_participation=false` | 🔍 1.8 kB | **Lista de competições** (provável fonte do `competition_id` + `school_id` — endpoint de descoberta) |
| GET | `/api/v2/.../score/` | 🔍 1.0 kB | Resumo de pontuação (estrelas/média da escola) |
| GET | `/api/v2/.../activity-list/` | 🔍 0.8 kB | Lista de atividades |
| GET | `/api/v2/.../locales/` | 🔍 32 kB | i18n (não é dado pedagógico) |

## 6. Endpoints por área (a completar pelo crawler)

Alvos do objetivo; ✅ = já temos, 🔍 = observado, ❓ = a descobrir.

- **School Leaderboard:** ✅ `reports/leaderboard/school_student/`, 🔍 `reports/leaderboard/school_klass/`
- **Student Leaderboard:** ✅ `competition-v2/<c>/school/<s>/student-leaderboard/`
- **Class Leaderboard:** 🔍 `competition-v2/<c>/school/<s>/class-leaderboard/`
- **Competition:** 🔍 `competition-v2/?require_participation=false`, ✅ `competition-v2/<c>/school/<s>/...`
- **Schools:** ❓ (provável `schools/` ou `me/schools/` — onde o SPA descobre o `school_id`)
- **Classes:** ❓ (`klasses/` / `classes/`)
- **Students:** ❓ (lista de alunos da turma — "Todos os Estudantes")
- **Teachers:** ❓ ("Todos os Professores")
- **Reports / Analytics / Dashboard:** ❓ ("Painel do Administrador", "Uso da escola")
- **Export / PDF:** ❓ (o botão "Placares"/"Uso da escola" pode chamar um `export`/`pdf`)

## 7. Endpoints ocultos

Chamadas disparadas por worker/lib que não aparecem fácil no Network são capturadas
pelo crawler (intercepta `page.on('response')` de TODAS as requisições) e pelo
interceptador de console (monkey-patch de `fetch`/`XMLHttpRequest`). Ver §10.

## 8. Datas personalizadas (custom range)

- Confirmado: `?duration=this-year` (= "Ano acadêmico atual").
- A tela tem também **"Período Personalizado"** → deve existir uma variante de
  `duration` ou params de data. ❓ **A capturar:** abra o Placar, troque o filtro
  para *Personalizado* (ou semana/mês) e veja a nova URL do `school_student` —
  candidatos: `?duration=this-week|this-month|custom`, ou `?start=YYYY-MM-DD&end=YYYY-MM-DD`
  / `?from=&to=`. **É o que habilita premiar por período no Constela.**

## 9. API pública × interna

- **Interna:** tudo em `/api/v2/` sob cookie de sessão (este documento).
- **Pública:** não há data-out self-serve. Integração oficial exige contrato
  enterprise com chave de API negociada.

## 10. Ferramentas para completar a documentação

1. **Crawler Playwright** — `tools/matific_crawler.py`. Login **manual** (você digita
   na janela, passa o reCAPTCHA), depois ele percorre automaticamente todas as telas
   do admin (segue os links `/teachers/…`), intercepta TODAS as requisições/respostas,
   salva **cada JSON num arquivo** em `matific_captura/`, um `_index.json` e um
   **`matific-openapi-auto.yaml`** gerado do que viu. Uso:
   ```bash
   cd backend && ./.venv/Scripts/python.exe ../tools/matific_crawler.py
   ```
2. **Interceptador de console** — cole o snippet do Constela na aba logada; captura
   fetch/XHR e baixa tudo (bom para chamadas ocultas de uma tela específica).
3. **OpenAPI base** — `docs/matific-openapi.yaml` (endpoints confirmados). O crawler
   emite a versão completa a partir da sua conta.

Depois de rodar, me mande a pasta `matific_captura/` (pode remover nomes de alunos)
que eu completo este documento e o OpenAPI com todos os endpoints.
