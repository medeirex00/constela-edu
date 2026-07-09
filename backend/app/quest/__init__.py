"""Constela Quest — módulo do backend (plataforma dos alunos).

Fronteira de dependência (docs/quest/01-arquitetura.md): este pacote PODE
importar o núcleo compartilhado (escolas, alunos, turmas, usuarios,
configuracoes, auditoria); o código do Edu NUNCA importa deste pacote —
ele consome o Quest pelas rotas /quest/professor/* e pelo outbox.
"""
