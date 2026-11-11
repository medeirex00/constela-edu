"""Etapa de deploy da Fase 3A — tira de circulação a senha de professor derivada do nome.

Por que existe
--------------
Até a Fase 3A a senha inicial do professor era derivável do nome (o @ + "123";
antes, o primeiro nome + "123"), a regra estava escrita no código de um
repositório público e não havia troca obrigatória. O código novo não cria mais
senhas assim — mas as contas ANTIGAS continuam com elas até alguém trocar. Este
script as encontra e, só quando pedido, as invalida.

Garantias
---------
* DIAGNÓSTICO POR PADRÃO: sem ``--aplicar`` nada é gravado (no Postgres a
  transação é aberta como ``READ ONLY``). Só confere o hash bcrypt de cada conta
  contra as senhas das convenções antigas — o @ e o primeiro nome + "123" em
  QUATRO caixas (como está, minúsculas, MAIÚSCULAS e só a primeira maiúscula:
  ``AnaSilva123``, ``anasilva123``, ``ANASILVA123``, ``Anasilva123``), inclusive
  com os nomes/@ que a conta JÁ teve (cadastro de professor ligado pelo e-mail e
  auditoria das edições). Limite: o nome anterior à 1ª edição do usuário não
  fica na auditoria (o ``PATCH /admin/usuarios`` grava só o nome novo); uma
  senha derivada dele só é achada se o cadastro de professor guardar esse nome.
* LIMITE DAS CAIXAS: a trava do login (``routers/auth.py``) recusa com 403 o
  nome/@ + "123" em QUALQUER combinação de maiúsculas e minúsculas (compara o
  texto digitado, sem bcrypt). O bcrypt não deixa conferir todas as combinações
  aqui: uma senha como ``anaSilva123`` (escolhida pela própria pessoa) não entra
  nas contagens nem no ``--aplicar`` e recebe o 403 do mesmo jeito. A saída diz
  isso (``AVISO_CAIXAS``); para conta GLOBAL, a confirmação é com a pessoa.
* ``--contagens``: o mesmo diagnóstico só-leitura (mesma transação ``READ ONLY``),
  mas a saída tem APENAS números — nem id, nem nome, nem @, nem e-mail, nem nome
  de escola. Recusa ``--aplicar`` e ``--escola`` antes de abrir o banco.
* CLASSIFICAÇÃO UMA VEZ: o diagnóstico, a conferência do ``--esperado`` e a
  gravação usam a mesma passada de bcrypt.
* ``--aplicar`` EXIGE ``--esperado N``: N é o número de alvos que o diagnóstico
  mostrou. Se o número desta execução for outro, aborta ANTES de gravar.
* COMPARE-AND-SET: só troca a senha se o hash ainda for o lido na classificação
  (e sobe o ``token_version`` na mesma instrução). Quem trocou a senha durante a
  execução não é tocado — sai listado.
* TRANSAÇÃO ÚNICA: uma falha no meio desfaz tudo (rollback total).
* NENHUMA SENHA É IMPRESSA, nem a antiga nem a nova (nem hash): a nova é
  aleatória e ninguém a recebe. O professor volta a entrar pelo link de
  redefinição de uso único ("Gerar link de redefinição", em Usuários).
* NÃO BLOQUEIA ninguém para sempre e NÃO cria senha conhecida de reserva: a
  conta continua ativa; só a senha pública deixa de funcionar.
* Classifica cada conta: NUNCA USADA (sem login registrado de forma alguma),
  USADA (tem ``ultimo_acesso``) ou INDETERMINADA (sinais divergentes — ex.:
  presença registrada sem ``ultimo_acesso``). ``--so-nunca-usadas`` só toca as
  NUNCA USADAS. Conta cujo hash não pôde ser conferido é listada à parte e
  nunca é tocada.
* Conta SEM ESCOLA nunca é tocada: sai listada à parte — a recuperação é manual,
  pelo admin global (``python -m scripts.link_redefinicao``).
* Administração global nunca é tocada: sai listada à parte (troca manual).
* As sessões abertas das contas invalidadas caem (``token_version``), e os
  aparelhos registrados para push saem junto (o app registra de novo no login).
* Cada conta invalidada fica no log de auditoria
  (``usuario.senha_derivada_invalidada``, detalhes ``{"uso", "origem"}``).

Antes de aplicar — decisão operacional
--------------------------------------
APLICAR EXIGE AUTORIZAÇÃO DO DONO E BACKUP VALIDADO (restaurável) do banco,
tomado imediatamente antes. Contas JÁ USADAS com a senha antiga deixam de entrar
até o professor receber o link. Combine com as escolas QUANDO aplicar e quem
gera os links (coordenação para professores, admin da escola para todos).
Contas nunca usadas não afetam ninguém.

Como executar
-------------
Só contagens (checklist pré-deploy; não grava nada e não imprime id, nome, @,
e-mail nem escola — só números: total, globais, ativas, já usadas e o detalhe
de cada grupo). É o que responde "alguma conta GLOBAL usa senha derivada?"
antes do deploy da trava do login (que passa a recusar essas senhas com 403; o
``scripts/link_redefinicao.py`` recusa conta global, então ela não tem volta
garantida):

    python -m scripts.senhas_derivadas --contagens

Diagnóstico (não grava nada; lista as contas e mostra o N de cada modo de
aplicação):

    python -m scripts.senhas_derivadas                    # todas as escolas
    python -m scripts.senhas_derivadas --escola 42        # uma escola

Aplicação (só com autorização e backup validado; N = o número de alvos que o
diagnóstico ACABOU de mostrar para o mesmo recorte e o mesmo modo):

    python -m scripts.senhas_derivadas --aplicar --esperado N --escola 42
    python -m scripts.senhas_derivadas --aplicar --so-nunca-usadas --esperado N
    python -m scripts.senhas_derivadas --aplicar --esperado N

``--so-nunca-usadas`` e ``--esperado`` só existem junto com ``--aplicar``;
``--contagens`` não combina com ``--aplicar`` nem com ``--escola`` (as contas
globais só entram na conferência da base inteira).

Contas de REDE (Secretaria) não entram no ``--escola``: alcançam a rede inteira e
só o admin global gera o link delas. Saem marcadas "(REDE n)" na execução completa.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Escola  # noqa: E402
from app.services import professores  # noqa: E402
from scripts._saida import forcar_saida_utf8  # noqa: E402

# Código de saída quando o --esperado não confere (nada gravado).
SAIDA_ESPERADO_DIVERGENTE = 3

# O que a contagem NÃO vê e a trava do login recusa (G_SCRIPTS-2): sai no
# --contagens e no diagnóstico. Sem id, nome, @ nem e-mail (vale para chamado e chat).
AVISO_CAIXAS = (
    "LIMITE: estas contas foram conferidas com o nome e o usuário + 123 em 4 caixas "
    "(como está, minúsculas, MAIÚSCULAS e só a primeira maiúscula); o login recusa "
    "com 403 o nome ou o usuário + 123 em QUALQUER combinação de maiúsculas e "
    "minúsculas. Uma senha assim em outra combinação não entra nestes números. "
    "Antes do deploy, confirme com cada administrador global que a senha dele não "
    "é o próprio nome ou usuário + 123, em caixa nenhuma.")


def _escola(conta: dict) -> str:
    return "-" if conta["escola_id"] is None else str(conta["escola_id"])


def _argumentos(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Encontra (e, com --aplicar --esperado N, invalida) senhas de "
                    "professor derivadas do nome.")
    parser.add_argument("--escola", type=int, default=None, help="só esta escola")
    parser.add_argument("--aplicar", action="store_true",
                        help="grava: invalida as senhas encontradas (sem isto, só "
                             "diagnostica). Exige --esperado.")
    parser.add_argument("--esperado", type=int, default=None, metavar="N",
                        help="com --aplicar: número de alvos conferido no diagnóstico; "
                             "se divergir, aborta sem gravar")
    parser.add_argument("--so-nunca-usadas", action="store_true",
                        help="com --aplicar, mexe só em contas que nunca entraram")
    parser.add_argument("--contagens", action="store_true",
                        help="só leitura: imprime APENAS números (total, globais, "
                             "ativas, já usadas), sem id, nome, @, e-mail nem escola "
                             "— o conferido do checklist pré-deploy")
    args = parser.parse_args(argv)
    if args.contagens and args.aplicar:
        parser.error("--contagens é só leitura: não combina com --aplicar.")
    if args.contagens and args.escola is not None:
        parser.error("--contagens confere a base inteira (as contas globais só "
                     "entram nela): não combina com --escola.")
    if args.so_nunca_usadas and not args.aplicar:
        parser.error("--so-nunca-usadas só vale junto com --aplicar "
                     "(o diagnóstico já mostra quantas são).")
    if args.esperado is not None and not args.aplicar:
        parser.error("--esperado só vale junto com --aplicar.")
    if args.aplicar and args.esperado is None:
        parser.error("--aplicar exige --esperado N (o número de alvos que o "
                     "diagnóstico mostrou).")
    if args.esperado is not None and args.esperado < 0:
        parser.error("--esperado não pode ser negativo.")
    return args


def _abrir_somente_leitura(db) -> None:
    """Diagnóstico no Postgres: a transação nasce READ ONLY (primeira instrução),
    então nem um engano no caminho consegue gravar. Outros dialetos (o SQLite dos
    testes) não têm a instrução — lá vale o rollback ao final."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))


def _resumo_por_escola(db, contas: list[dict]) -> list[str]:
    """Uma linha por escola: total e contagem por uso, cargo e status."""
    ids = sorted({c["escola_id"] for c in contas if c["escola_id"] is not None})
    nomes = dict(db.execute(select(Escola.id, Escola.nome)
                            .where(Escola.id.in_(ids or [-1]))).all())

    def fmt(cont: Counter) -> str:
        return ", ".join(f"{k} {v}" for k, v in sorted(cont.items()))

    linhas = []
    for eid in ids:
        grupo = [c for c in contas if c["escola_id"] == eid]
        linhas.append(
            f"  escola {eid} ({nomes.get(eid, '?')}): {len(grupo)} — "
            f"uso: {fmt(Counter(c['uso'] for c in grupo))} · "
            f"cargo: {fmt(Counter(c['cargo'] for c in grupo))} · "
            f"status: {fmt(Counter(c['status'] for c in grupo))}")
    return linhas


def _linha_conta(c: dict) -> str:
    # Conta de rede (Secretaria) pode não ter escola: "-" em vez de quebrar.
    excluida = " (EXCLUÍDA)" if c.get("status") == "excluido" else ""
    rede = (f" (REDE {c['rede_id']}: link só pelo admin global)"
            if c.get("rede_id") else "")
    return (f"  usuario_id={c['usuario_id']:<6} escola={_escola(c):<5} "
            f"@{(c['usuario'] or '-'):<28} {c['cargo']:<12} {c['uso'].upper()}"
            f"{excluida}{rede}")


def _contagens(classificacao: dict) -> list[str]:
    """As linhas do ``--contagens``: SÓ números, nenhum id, nome, @, e-mail ou
    escola (a saída pode ir para um chamado ou um chat). ``total`` soma as contas
    com escola, sem escola e globais com senha derivada; as de hash não
    conferível ficam à parte (não dá para afirmar que são derivadas)."""
    globais = classificacao["globais"]
    com_escola = classificacao["derivadas"]
    sem_escola = classificacao["sem_escola"]
    todas = com_escola + sem_escola + globais

    def ativas(contas: list[dict]) -> int:
        return sum(1 for c in contas if c["status"] == "ativo")

    def com_uso(contas: list[dict], uso: str) -> int:
        return sum(1 for c in contas if c["uso"] == uso)

    linhas = [
        "senhas derivadas do nome — só contagens (somente leitura, nada gravado)",
        f"total: {len(todas)}",
        f"globais: {len(globais)}",
        f"ativas: {ativas(todas)}",
        f"já usadas: {com_uso(todas, professores.USO_USADA)}",
        "detalhe:",
        f"  globais ativas: {ativas(globais)}",
        f"  globais já usadas: {com_uso(globais, professores.USO_USADA)}",
        f"  com escola (alvos do --aplicar): {len(com_escola)}",
        f"  sem escola (recuperação manual): {len(sem_escola)}",
        f"  nunca usadas: {com_uso(todas, professores.USO_NUNCA_USADA)}",
        f"  indeterminadas: {com_uso(todas, professores.USO_INDETERMINADO)}",
        f"  hash não conferível (fora da etapa): "
        f"{len(classificacao['nao_verificaveis'])}",
    ]
    if globais:
        linhas.append(
            "ATENÇÃO: há conta GLOBAL com senha derivada. Depois do deploy o login "
            "dela recebe 403 e não há volta garantida (o scripts/link_redefinicao.py "
            "recusa conta global): troque a senha ANTES do deploy e confira de novo "
            "até 'globais: 0'.")
    else:
        linhas.append("nenhuma conta global com senha derivada nas 4 caixas conferidas "
                      "(ver o limite abaixo).")
    linhas.append(AVISO_CAIXAS)
    return linhas


def main(argv=None) -> int:
    forcar_saida_utf8()
    args = _argumentos(argv)

    db = SessionLocal()
    try:
        if not args.aplicar:
            _abrir_somente_leitura(db)
        # A classificação (bcrypt) é feita UMA vez e serve a tudo abaixo.
        classificacao = professores.classificar_senhas_derivadas(db, args.escola)
        if args.contagens:
            for linha in _contagens(classificacao):
                print(linha)
            db.rollback()
            return 0
        achadas = classificacao["derivadas"]
        por_uso = {uso: [c for c in achadas if c["uso"] == uso]
                   for uso in (professores.USO_NUNCA_USADA, professores.USO_USADA,
                               professores.USO_INDETERMINADO)}
        print(f"contas com senha derivada do nome: {len(achadas)} "
              f"({len(por_uso['nunca_usada'])} nunca usadas, "
              f"{len(por_uso['usada'])} já usadas, "
              f"{len(por_uso['indeterminada'])} indeterminadas)")
        if achadas:
            print("resumo por escola:")
            for linha in _resumo_por_escola(db, achadas):
                print(linha)
            print("contas:")
        for c in achadas:
            print(_linha_conta(c))

        sem_escola = classificacao["sem_escola"]
        if sem_escola:
            print(f"\nsem escola: recuperação manual pelo admin global "
                  f"(scripts/link_redefinicao.py) — fora da etapa: {len(sem_escola)}")
            for c in sem_escola:
                print(_linha_conta(c))
        globais = classificacao["globais"]
        if globais:
            print(f"\nADMINISTRAÇÃO GLOBAL com senha derivada (troca MANUAL, "
                  f"fora da etapa): {len(globais)}")
            for c in globais:
                print(f"  usuario_id={c['usuario_id']:<6} @{(c['usuario'] or '-')}")
        nao_verificaveis = classificacao["nao_verificaveis"]
        if nao_verificaveis:
            print(f"\ncontas cujo hash não pôde ser conferido (fora da etapa): "
                  f"{len(nao_verificaveis)}")
            for c in nao_verificaveis:
                print(f"  usuario_id={c['usuario_id']:<6} escola={_escola(c):<5} "
                      f"@{(c['usuario'] or '-')}")

        if not args.aplicar:
            todos = len(professores.alvos_da_invalidacao(classificacao))
            nunca = len(professores.alvos_da_invalidacao(classificacao,
                                                         so_nunca_usadas=True))
            print(f"\nalvos: --aplicar → {todos}; --aplicar --so-nunca-usadas → {nunca}")
            print(AVISO_CAIXAS)
            print("diagnóstico apenas — nada foi gravado. Para invalidar (só com "
                  "autorização e backup validado): --aplicar --esperado N.")
            db.rollback()
            return 0

        try:
            resultado = professores.invalidar_senhas_derivadas(
                db, args.escola, aplicar=True, so_nunca_usadas=args.so_nunca_usadas,
                esperado=args.esperado, classificacao=classificacao,
                origem=professores.ORIGEM_ETAPA)
        except professores.EsperadoDivergente as e:
            db.rollback()
            print(f"\nABORTADO — esperado {e.esperado}, mas esta execução tem "
                  f"{e.encontrados} alvo(s). Nada foi gravado. Rode o diagnóstico de "
                  "novo e confira antes de aplicar.")
            return SAIDA_ESPERADO_DIVERGENTE
        db.commit()
        print(f"\ninvalidadas: {resultado['invalidadas']} de {resultado['encontradas']} "
              "encontradas. Os professores voltam a entrar pelo link de redefinição.")
        trocadas = resultado["trocadas_durante"]
        if trocadas:
            print(f"senha trocada durante a execução — não tocada: {len(trocadas)}")
            for c in trocadas:
                print(_linha_conta(c))
        if args.so_nunca_usadas:
            print("(--so-nunca-usadas: as já usadas e as indeterminadas não foram tocadas)")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
