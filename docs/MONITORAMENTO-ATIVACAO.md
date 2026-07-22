# Ativação de Monitoramento e Alertas — Constela Edu

O código de observabilidade já está pronto e é seguro para LGPD (erros sem PII,
IP mascarado, `send_default_pii=False`). O que falta é **ligar** — ação de
configuração, não de código. Este guia fecha o achado “sem alerta/monitoramento
ativo: uma queda é descoberta pela escola reclamando”.

> **Por que importa:** o robô de sincronização e as premiações ao vivo dependem
> da API. Sem alerta, uma queda às 7h30 só seria notada por reclamação. Os dois
> passos abaixo levam ~15 minutos e são gratuitos.

---

## 1. Sentry — erros e desempenho (5 min)

1. Crie um projeto **Python/FastAPI** em [sentry.io](https://sentry.io) (plano
   grátis basta) e copie o **DSN**.
2. No **Railway** (backend), em *Variables*, defina:

   | Variável | Valor |
   |----------|-------|
   | `SENTRY_DSN` | o DSN copiado |
   | `SENTRY_ENVIRONMENT` | `production` |
   | `SENTRY_TRACES_SAMPLE_RATE` | `0.1` (10% de tracing; opcional) |

3. Redeploy. Pronto: exceções passam a chegar no Sentry com alerta por e-mail.
   Nenhum dado pessoal de aluno é enviado — a redação já está no código
   (`app/core/observabilidade.py::configurar_sentry`).

## 2. Monitor de uptime externo (10 min)

O código expõe um health check próprio para isto:

- **Liveness:** `GET https://api.constelaedu.com/api/health/live`
- **Readiness (checa o banco):** `GET https://api.constelaedu.com/api/health/ready`

Cadastre o endpoint **/api/health/ready** em um monitor externo gratuito
(UptimeRobot, BetterStack, Cronitor…):

1. Novo monitor HTTP(s) → URL acima → intervalo 1–5 min.
2. Alerta por e-mail/telefone quando falhar 2 checagens seguidas.
3. (Opcional) Adicione também o frontend `https://www.constelaedu.com`.

> Use um monitor **externo** (fora do Railway): se o Railway cair, ele é quem
> avisa — um monitor interno cairia junto.

## 3. Métricas Prometheus (opcional, para mais tarde)

`GET /metrics` já existe (formato Prometheus). Para proteger, defina
`METRICS_TOKEN` no Railway e configure o scraper com esse token no header. Não é
necessário para o alerta básico de indisponibilidade — pode ficar para quando
houver um Grafana.

## 4. Checklist

- [ ] `SENTRY_DSN` definido no Railway e um erro de teste apareceu no Sentry
- [ ] Monitor externo no `/api/health/ready` com alerta por e-mail
- [ ] (Opcional) Frontend monitorado
- [ ] (Opcional) `METRICS_TOKEN` + scraper Prometheus
