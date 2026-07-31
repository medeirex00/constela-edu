"""Fusão par-a-par de dois cadastros do MESMO aluno (duplicados).

Núcleo reusado tanto pela fusão manual de 1 par (POST /alunos/fundir) quanto
pela fusão em LOTE (Fundir duplicatas). Junta no ``manter`` TUDO do ``remover``
(snapshots Matific/Elefante, leituras, matrículas, notas, linha do tempo de
eventos, vínculo de identidade externa/UUID, ficha cadastral e o lado Quest) e
apaga o ``remover``.

Garantias de segurança (a regra do dono: nunca perder dado, nunca dobrar ponto):
  * cada relação resolve a própria UNICIDADE (migra o que falta, descarta o
    repetido) — nunca viola constraint nem duplica;
  * a pontuação NÃO é somada: os snapshots são reatribuídos e a nota é
    RECALCULADA do zero pelo chamador (o scoring usa só o snapshot mais recente
    por aluno×plataforma — juntar históricos não dobra);
  * ``db.flush()`` grava os UPDATE aluno_id ANTES do ``db.delete(remover)``,
    senão o ON DELETE CASCADE apagaria em silêncio o que acabou de ser movido;
  * antes de apagar, o estado do ``remover`` é fotografado no log de auditoria
    (``foto_pre_fusao``) — rede de segurança para reconstrução manual.

``fundir_par`` NÃO faz commit nem recálculo: o chamador decide (a fusão em lote
faz UM commit e UM recálculo de escola no fim). Devolve as contagens do que foi
movido/descartado.
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    EventoAluno,
    IdentidadeExterna,
    Leitura,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
)
from app.services.audit import registrar


def _foto_pre_fusao(db: Session, remover: Aluno) -> dict:
    """Retrato do cadastro que será apagado — guardado na auditoria para
    reconstrução manual (a fusão é irreversível por design; esta é a rede de
    segurança). Guarda os campos cadastrais + o vínculo com turmas/plataformas
    e a contagem de dados históricos (o volume bruto não cabe no log)."""
    matriculas = db.execute(
        select(Matricula.ano_letivo, Matricula.turma_id)
        .where(Matricula.aluno_id == remover.id)
    ).all()
    identidades = db.execute(
        select(IdentidadeExterna.plataforma, IdentidadeExterna.id_externo)
        .where(IdentidadeExterna.aluno_id == remover.id)
    ).all()

    def _conta(modelo) -> int:
        return len(db.execute(
            select(modelo.id).where(modelo.aluno_id == remover.id)).scalars().all())

    # Perfil Quest do `remover`: se for descartado na fusão (o `manter` já tem um),
    # o CASCADE apaga tudo — então guardamos o retrato dele para reconstrução.
    # Agregados (progresso/habilidades) só pelo helper sancionado (catraca §11).
    from app.quest.models import QuestPerfil, QuestTentativa  # noqa: E402
    from app.quest.services import agregados  # noqa: E402
    perfil = db.execute(
        select(QuestPerfil).where(QuestPerfil.aluno_id == remover.id)
    ).scalars().first()
    quest = None
    if perfil is not None:
        agg = agregados.contar_agregados_do_perfil(db, remover.escola_id, perfil.id)
        tentativas = len(db.execute(
            select(QuestTentativa.id)
            .where(QuestTentativa.perfil_id == perfil.id)).scalars().all())
        quest = {
            "nivel": getattr(perfil, "nivel", None),
            "xp_total": getattr(perfil, "xp_total", None),
            "moedas": getattr(perfil, "moedas", None),
            "estrelas_total": getattr(perfil, "estrelas_total", None),
            "sequencia_dias": getattr(perfil, "sequencia_dias", None),
            "progresso": agg["progresso"],
            "tentativas": tentativas,
            "habilidades": agg["habilidades"],
        }

    return {
        "id": remover.id,
        "nome": remover.nome,
        "status": remover.status,
        "da_lista_piloto": remover.da_lista_piloto,
        "foto_url": remover.foto_url,
        "numero_chamada": remover.numero_chamada,
        "data_nascimento": (remover.data_nascimento.isoformat()
                            if remover.data_nascimento else None),
        "observacoes": remover.observacoes,
        "ficha": dict(remover.ficha or {}),
        "matriculas": [{"ano_letivo": a, "turma_id": t} for a, t in matriculas],
        "identidades_externas": [{"plataforma": p, "id_externo": i}
                                 for p, i in identidades],
        "quest": quest,
        "contagens": {
            "leituras": _conta(Leitura),
            "snapshots_matific": _conta(SnapshotMatific),
            "snapshots_elefante": _conta(SnapshotElefante),
            "eventos": _conta(EventoAluno),
        },
    }


def fundir_par(db: Session, escola_id: int, manter: Aluno, remover: Aluno,
               usuario_id: int) -> dict:
    """Funde ``remover`` em ``manter`` (mesma escola, ambos já validados como
    ativos pelo chamador). Reatribui/deduplica cada relação, funde a ficha,
    registra a auditoria (com a foto pré-fusão) e apaga o ``remover``. NÃO
    commita nem recalcula — devolve as contagens do que foi movido."""
    manter_nome, remover_nome = manter.nome, remover.nome
    foto = _foto_pre_fusao(db, remover)   # ANTES de mover/apagar qualquer coisa

    # Leituras: reatribui as de livros que o `manter` ainda não tem; as
    # repetidas (mesmo livro) são descartadas (respeita uq_leitura_unica; a
    # releitura nunca pontua duas vezes, §35).
    livros_do_manter = set(db.execute(
        select(Leitura.livro_id).where(Leitura.aluno_id == manter.id)
    ).scalars().all())
    leituras_movidas = leituras_descartadas = 0
    for leitura in db.execute(
        select(Leitura).where(Leitura.aluno_id == remover.id)
    ).scalars().all():
        if leitura.livro_id in livros_do_manter:
            db.delete(leitura)
            leituras_descartadas += 1
        else:
            leitura.aluno_id = manter.id
            livros_do_manter.add(leitura.livro_id)
            leituras_movidas += 1

    # Snapshots das plataformas: reatribuídos INTEGRALMENTE (é aqui que o
    # Matific de um cadastro se junta ao Elefante do outro). Sem UNIQUE; o
    # scoring usa só o snapshot mais recente → juntar históricos não dobra nota.
    snaps_matific = db.execute(
        update(SnapshotMatific).where(SnapshotMatific.aluno_id == remover.id)
        .values(aluno_id=manter.id)
    ).rowcount
    snaps_elefante = db.execute(
        update(SnapshotElefante).where(SnapshotElefante.aluno_id == remover.id)
        .values(aluno_id=manter.id)
    ).rowcount

    # Eventos (linha do tempo): migra os que o `manter` não tem; descarta os
    # duplicados (mesma plataforma+chave_natural) para respeitar a UNIQUE de
    # idempotência. SEM a reatribuição, o delete cascatearia e apagaria em
    # silêncio o histórico do `remover`.
    chaves_evt_manter = set(db.execute(
        select(EventoAluno.plataforma, EventoAluno.chave_natural)
        .where(EventoAluno.aluno_id == manter.id)
    ).all())
    eventos_movidos = eventos_descartados = 0
    for evento in db.execute(
        select(EventoAluno).where(EventoAluno.aluno_id == remover.id)
    ).scalars().all():
        chave = (evento.plataforma, evento.chave_natural)
        if chave in chaves_evt_manter:
            db.delete(evento)
            eventos_descartados += 1
        else:
            evento.aluno_id = manter.id
            chaves_evt_manter.add(chave)
            eventos_movidos += 1

    # Identidade externa (vínculo UUID): RETÉM ambos os vínculos — só descarta o
    # que for EXATAMENTE igual (mesma plataforma E mesmo id_externo). Se a mesma
    # plataforma tiver UUIDs diferentes nos dois cadastros, os DOIS passam para o
    # `manter` (a UNIQUE é por escola+plataforma+id_externo, permite). Assim a
    # próxima sync recasa por QUALQUER um dos UUIDs e NÃO recria a duplicata.
    # CRÍTICO reatribuir (e não deixar cascatear): sem o UUID, a sync recasaria
    # por NOME e poderia recriar a duplicata, desfazendo a fusão.
    ids_ident_manter = set(db.execute(
        select(IdentidadeExterna.plataforma, IdentidadeExterna.id_externo)
        .where(IdentidadeExterna.aluno_id == manter.id)
    ).all())
    identidades_movidas = identidades_descartadas = 0
    for ident in db.execute(
        select(IdentidadeExterna).where(IdentidadeExterna.aluno_id == remover.id)
    ).scalars().all():
        chave = (ident.plataforma, ident.id_externo)
        if chave in ids_ident_manter:
            db.delete(ident)               # UUID idêntico → duplicata real
            identidades_descartadas += 1
        else:
            ident.aluno_id = manter.id      # retém o UUID (mesmo se mesma plataforma)
            ids_ident_manter.add(chave)
            identidades_movidas += 1

    # Matrículas: move as de anos que o `manter` não tem; nos anos em comum,
    # mantém a do `manter` (a turma dele prevalece).
    anos_do_manter = set(db.execute(
        select(Matricula.ano_letivo).where(Matricula.aluno_id == manter.id)
    ).scalars().all())
    for matricula in db.execute(
        select(Matricula).where(Matricula.aluno_id == remover.id)
    ).scalars().all():
        if matricula.ano_letivo in anos_do_manter:
            db.delete(matricula)
        else:
            matricula.aluno_id = manter.id
            anos_do_manter.add(matricula.ano_letivo)

    # Notas: migra as de anos que o `manter` não tem (preserva o histórico) e
    # descarta as de anos em comum. A do ano ATIVO é reescrita pelo recálculo.
    anos_nota_manter = set(db.execute(
        select(Nota.ano_letivo).where(Nota.aluno_id == manter.id)
    ).scalars().all())
    for nota in db.execute(
        select(Nota).where(Nota.aluno_id == remover.id)
    ).scalars().all():
        if nota.ano_letivo in anos_nota_manter:
            db.delete(nota)
        else:
            nota.aluno_id = manter.id

    # Lado Quest: perfil (com toda a telemetria via perfil_id), credencial e
    # responsáveis. Importado sob demanda para não acoplar o módulo Quest.
    # Os agregados (progresso/habilidades) são lidos SÓ pelo helper sancionado
    # (catraca de isolamento §11); tentativas não estão sob a catraca.
    from app.quest.models import (  # noqa: E402
        QuestCredencialAluno,
        QuestPerfil,
        QuestTentativa,
        ResponsavelAluno,
    )
    from app.quest.services import agregados  # noqa: E402

    quest_perfil_movido = quest_perfil_descartado = 0
    # Telemetria destruída quando o perfil do `remover` é descartado (o CASCADE
    # de quest_perfis apaga progresso/tentativas/habilidades). Contada para o log
    # não esconder o volume perdido (como leituras/eventos já fazem).
    quest_progresso_descartado = quest_tentativas_descartadas = 0
    quest_habilidades_descartadas = 0
    manter_tem_perfil = db.execute(
        select(QuestPerfil.id).where(QuestPerfil.aluno_id == manter.id)
    ).scalar_one_or_none() is not None
    for perfil in db.execute(
        select(QuestPerfil).where(QuestPerfil.aluno_id == remover.id)
    ).scalars().all():
        if manter_tem_perfil:
            agg = agregados.contar_agregados_do_perfil(db, escola_id, perfil.id)
            quest_progresso_descartado += agg["progresso"]
            quest_habilidades_descartadas += agg["habilidades"]
            quest_tentativas_descartadas += len(db.execute(
                select(QuestTentativa.id)
                .where(QuestTentativa.perfil_id == perfil.id)).scalars().all())
            db.delete(perfil)
            quest_perfil_descartado += 1
        else:
            perfil.aluno_id = manter.id
            manter_tem_perfil = True
            quest_perfil_movido += 1

    manter_tem_cred = db.execute(
        select(QuestCredencialAluno.id)
        .where(QuestCredencialAluno.aluno_id == manter.id)
    ).scalar_one_or_none() is not None
    quest_credencial_descartada = 0
    for cred in db.execute(
        select(QuestCredencialAluno).where(QuestCredencialAluno.aluno_id == remover.id)
    ).scalars().all():
        if manter_tem_cred:
            db.delete(cred)
            quest_credencial_descartada += 1
        else:
            cred.aluno_id = manter.id
            manter_tem_cred = True

    resp_do_manter = set(db.execute(
        select(ResponsavelAluno.usuario_id)
        .where(ResponsavelAluno.aluno_id == manter.id)
    ).scalars().all())
    for vinculo in db.execute(
        select(ResponsavelAluno).where(ResponsavelAluno.aluno_id == remover.id)
    ).scalars().all():
        if vinculo.usuario_id in resp_do_manter:
            db.delete(vinculo)
        else:
            vinculo.aluno_id = manter.id
            resp_do_manter.add(vinculo.usuario_id)

    # Campos escalares: preenche APENAS as lacunas do `manter` (nunca sobrescreve
    # um valor já existente — o canônico é o `manter`).
    if not manter.foto_url and remover.foto_url:
        manter.foto_url = remover.foto_url
    if manter.numero_chamada is None and remover.numero_chamada is not None:
        manter.numero_chamada = remover.numero_chamada
    if manter.data_nascimento is None and remover.data_nascimento is not None:
        manter.data_nascimento = remover.data_nascimento
    if not manter.observacoes and remover.observacoes:
        manter.observacoes = remover.observacoes

    # Ficha cadastral (RA/RM/responsável/endereço/CPF/SUS…): funde preenchendo só
    # as chaves AUSENTES no `manter` — não perde os dados cadastrais do `remover`
    # nem sobrescreve os do `manter`.
    ficha_remover = remover.ficha or {}
    if ficha_remover:
        ficha = dict(manter.ficha or {})
        for chave, valor in ficha_remover.items():
            if chave not in ficha or ficha[chave] in (None, ""):
                ficha[chave] = valor
        manter.ficha = ficha

    # Se QUALQUER lado veio da Lista Piloto, o `manter` herda a marca — senão a
    # próxima reconciliação incremental poderia marcá-lo "fora_lista_piloto".
    if remover.da_lista_piloto and not manter.da_lista_piloto:
        manter.da_lista_piloto = True

    manter_id = manter.id
    contagens = {
        "leituras_movidas": leituras_movidas,
        "leituras_descartadas": leituras_descartadas,
        "snapshots_matific": snaps_matific,
        "snapshots_elefante": snaps_elefante,
        "eventos_movidos": eventos_movidos,
        "eventos_descartados": eventos_descartados,
        "identidades_movidas": identidades_movidas,
        "identidades_descartadas": identidades_descartadas,
        "quest_perfil_movido": quest_perfil_movido,
        "quest_perfil_descartado": quest_perfil_descartado,
        "quest_credencial_descartada": quest_credencial_descartada,
        "quest_progresso_descartado": quest_progresso_descartado,
        "quest_tentativas_descartadas": quest_tentativas_descartadas,
        "quest_habilidades_descartadas": quest_habilidades_descartadas,
    }
    registrar(db, "aluno.fundido", escola_id=escola_id, usuario_id=usuario_id,
              entidade="aluno", entidade_id=manter_id,
              detalhes={"mantido": {"id": manter_id, "nome": manter_nome},
                        "removido": {"id": remover.id, "nome": remover_nome},
                        "foto_pre_fusao": foto,
                        **contagens})
    # Grava as reatribuições ANTES do delete — o cascade não pega o que foi movido.
    db.flush()
    db.delete(remover)

    return {"aluno_id": manter_id, "manter_nome": manter_nome,
            "remover_nome": remover_nome, **contagens}
