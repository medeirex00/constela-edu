"""Configuração própria do Constela Quest (lida do ambiente / .env, como a do Edu).

Mora aqui, e não em app/core/config.py, só por posse de arquivo nesta rodada; o
lugar natural é junto das demais ``QUEST_*`` em ``Settings`` — mover sem mudar o
nome da variável não muda comportamento.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigQuest(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Liga as rotas do LADO DO ALUNO (/quest/auth/*, /quest/perfil*, /quest/
    # conquistas). Padrão = comportamento atual (ligadas). Com false, elas
    # respondem 404 como rota inexistente — a superfície de login infantil sai
    # da internet enquanto o app do aluno não estiver publicado. As rotas do
    # professor (cartões, no Edu) não dependem disto. Ligar/desligar é decisão
    # do dono (recomendação registrada em docs/lgpd/RETENCAO-TECNICA.md).
    QUEST_ALUNO_HABILITADO: bool = True

    # Nas chaves dos limites POR IP do login infantil, um IPv6 conta pela REDE
    # /QUEST_LIMITE_PREFIXO_IPV6 (padrão 64: o que um provedor entrega a um
    # assinante), não pelo endereço — senão quem tem um /64 troca de "IP" a cada
    # palpite. IPv4 segue por endereço. 128 = por endereço (o comportamento
    # antigo, NÃO recomendado); abaixo de 32 juntaria clientes sem relação.
    QUEST_LIMITE_PREFIXO_IPV6: int = Field(default=64, ge=32, le=128)

    # Teto GLOBAL de falhas do login por código (/quest/auth/quem e /entrar),
    # SOMANDO TODOS OS IPs: QUEST_LIMITE_GLOBAL_FALHAS falhas em
    # QUEST_LIMITE_GLOBAL_JANELA_S segundos suspendem o login por CÓDIGO da API
    # inteira (429) por uma janela e geram um log de alerta. Freia a varredura
    # distribuída (muitos IPs), que o teto por IP não vê. Trade-off aceito: sob
    # ataque, as crianças também esperam a janela — o QR do cartão segue
    # entrando. O padrão (400 em 5 min) fica muito acima das falhas de uso real
    # (erros de digitação de várias turmas ao mesmo tempo); ver
    # docs/lgpd/RETENCAO-TECNICA.md §2.4 antes de mudar.
    QUEST_LIMITE_GLOBAL_FALHAS: int = Field(default=400, ge=1)
    QUEST_LIMITE_GLOBAL_JANELA_S: int = Field(default=300, ge=60, le=3600)


config_quest = ConfigQuest()
