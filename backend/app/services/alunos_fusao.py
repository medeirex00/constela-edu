"""Fusão par-a-par de dois cadastros do MESMO aluno (duplicados).

Núcleo reusado tanto pela fusão manual de 1 par (POST /alunos/fundir) quanto
pela fusão em LOTE (Fundir duplicatas). Junta no ``manter`` TUDO do ``remover``
(snapshots Matific/Elefante, leituras, matrículas, notas, linha do tempo de
eventos, vínculo de identidade externa/UUID, memória das decisões de identidade,
ficha cadastral e o lado Quest) e apaga o ``remover``.

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

from collections import defaultdict
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.tempo import agora_br
from app.models import (
    Aluno,
    Escola,
    EventoAluno,
    IdentidadeExterna,
    Leitura,
    Livro,
    Matricula,
    Nota,
    Notificacao,
    RevisaoIdentidade,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import bimestres
from app.services.audit import registrar
from app.services.eventos import (
    conteudo_evento,
    origem_comprovada,
    primeiras_ocorrencias,
)


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


def _bimestre_da_data(dia: date, janelas: dict[int, tuple[date, date]]) -> int | None:
    for numero, (inicio, fim) in janelas.items():
        if inicio <= dia <= fim:
            return numero
    return None


def _bimestre_premiado(ano: int, janelas: dict, hoje: date) -> int | None:
    """O bimestre que a tela de premiação e o certificado abrem selecionado
    (``bimestres.bimestre_sugerido``). Com o ano letivo ainda virando, o último
    (ou o primeiro) bimestre DAQUELE ano — nunca o de um calendário de outro ano."""
    if not janelas:
        return None
    if hoje.year == ano:
        return bimestres.bimestre_sugerido(hoje)
    return 4 if hoje.year > ano else 1


def leituras_repetidas(db: Session, ano_letivo: int, pares: list[tuple[int, int]],
                       *, exemplos: int = 0, hoje: date | None = None
                       ) -> dict[tuple[int, int], dict]:
    """PRÉVIA, só leitura, do que a fusão faria com os livros que estão NAS DUAS
    fichas: por par ``(manter_id, remover_id)``, quantos são, quantos têm data
    diferente e quantos deixariam de contar em cada bimestre.

    A regra de qual data fica é a de ``fundir_par`` (a de quem fica) e aqui ela só
    é descrita. "Deixa de contar no bimestre" = a data descartada cai naquele
    bimestre e a que fica, não — é o livro que some do pódio sem ninguém ver.
    Compara a DATA, na mesma régua das telas por período (``Leitura.data`` sem
    conversão, janela inclusiva). Ano sem calendário oficial: sem bimestre
    (``None``), em vez de datas inventadas.

    O ``bimestre`` diz também o ``ano`` letivo e se é o ``atual`` (hoje está
    dentro dele). Na virada do ano o bimestre da premiação é o 4º do ano que
    terminou (ou o 1º, que ainda não começou): a tela não pode chamá-lo de
    "o bimestre atual".

    Uma consulta só, para qualquer número de pares (a prévia do lote lista todos)."""
    if not pares:
        return {}
    janelas = bimestres.calendario(ano_letivo) or {}
    hoje = hoje or agora_br().date()
    premiado = _bimestre_premiado(ano_letivo, janelas, hoje)
    bimestre = ({"numero": premiado, "rotulo": bimestres.rotulo(premiado),
                 "inicio": janelas[premiado][0].isoformat(),
                 "fim": janelas[premiado][1].isoformat(),
                 "ano": ano_letivo,
                 "atual": janelas[premiado][0] <= hoje <= janelas[premiado][1]}
                if premiado is not None else None)
    ids = {i for par in pares for i in par}
    datas: dict[int, dict[int, object]] = defaultdict(dict)
    for aluno_id, livro_id, quando in db.execute(
        select(Leitura.aluno_id, Leitura.livro_id, Leitura.data)
        .where(Leitura.aluno_id.in_(ids))
    ).all():
        datas[aluno_id][livro_id] = quando

    saida: dict[tuple[int, int], dict] = {}
    titulos_precisos: set[int] = set()
    for manter_id, remover_id in pares:
        fica, sai = datas.get(manter_id, {}), datas.get(remover_id, {})
        comuns = fica.keys() & sai.keys()
        diferentes: list[dict] = []
        saem_de: dict[int, int] = defaultdict(int)
        for livro_id in comuns:
            dia_fica, dia_sai = fica[livro_id].date(), sai[livro_id].date()
            if dia_fica == dia_sai:
                continue
            bimestre_sai = _bimestre_da_data(dia_sai, janelas)
            deixa = (bimestre_sai if bimestre_sai is not None
                     and bimestre_sai != _bimestre_da_data(dia_fica, janelas) else None)
            if deixa is not None:
                saem_de[deixa] += 1
            diferentes.append({"livro_id": livro_id, "data_manter": dia_fica.isoformat(),
                               "data_remover": dia_sai.isoformat(), "deixa_de_contar_em": deixa})
        # Primeiro o que muda pódio; a ordem por id deixa a lista estável.
        diferentes.sort(key=lambda d: (d["deixa_de_contar_em"] is None, d["livro_id"]))
        amostra = diferentes[:exemplos]
        titulos_precisos.update(d["livro_id"] for d in amostra)
        saida[(manter_id, remover_id)] = {
            "livros_repetidos": len(comuns),
            "com_data_diferente": len(diferentes),
            "no_bimestre": saem_de.get(premiado, 0) if premiado is not None else None,
            "bimestre": dict(bimestre) if bimestre is not None else None,
            "por_bimestre": [{"numero": n, "rotulo": bimestres.rotulo(n), "livros": saem_de[n]}
                             for n in sorted(saem_de)],
            "exemplos": amostra,
        }
    if titulos_precisos:
        titulos = dict(db.execute(select(Livro.id, Livro.titulo).where(
            Livro.id.in_(titulos_precisos))).all())
        for resumo in saida.values():
            for d in resumo["exemplos"]:
                d["livro"] = titulos.get(d["livro_id"])
    return saida


def _trocar_candidato_nas_pendencias(db: Session, escola_id: int, manter: Aluno,
                                     remover: Aluno) -> int:
    """Nas pendências ABERTAS da escola, o candidato ``remover`` vira ``manter``
    (sem repetir quem já está na lista). Devolve quantas pendências mudaram."""
    afetadas = [r for r in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola_id,
        RevisaoIdentidade.status == "pendente")).scalars()
        if any(isinstance(c, dict) and c.get("aluno_id") == remover.id
               for c in (r.candidatos or []))]
    if not afetadas:
        return 0
    escola = db.get(Escola, escola_id)
    turma = db.execute(
        select(Turma.nome).join(Matricula, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == manter.id,
               Matricula.ano_letivo == (escola.ano_letivo_ativo if escola else 0))
    ).scalars().first()
    for rev in afetadas:
        lista = list(rev.candidatos or [])
        ja_tem = any(isinstance(c, dict) and c.get("aluno_id") == manter.id for c in lista)
        nova: list = []
        for c in lista:
            if isinstance(c, dict) and c.get("aluno_id") == remover.id:
                if not ja_tem:
                    nova.append({**c, "aluno_id": manter.id, "nome": manter.nome,
                                 "status": manter.status,
                                 "turma": turma if turma is not None else c.get("turma")})
                    ja_tem = True
                continue
            nova.append(c)
        rev.candidatos = nova
    return len(afetadas)


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
    # releitura nunca pontua duas vezes, §35). Fica a data de quem fica (decisão
    # C2): a data descartada vai para o log, porque pode ser a única que caía no
    # período premiado.
    data_no_manter = dict(db.execute(
        select(Leitura.livro_id, Leitura.data).where(Leitura.aluno_id == manter.id)
    ).all())
    leituras_movidas = leituras_descartadas = 0
    descartes: list[dict] = []
    for leitura in db.execute(
        select(Leitura).where(Leitura.aluno_id == remover.id)
    ).scalars().all():
        if leitura.livro_id in data_no_manter:
            descartes.append({"livro_id": leitura.livro_id,
                              "data_manter": data_no_manter[leitura.livro_id].isoformat(),
                              "data_remover": leitura.data.isoformat()})
            db.delete(leitura)
            leituras_descartadas += 1
        else:
            leitura.aluno_id = manter.id
            data_no_manter[leitura.livro_id] = leitura.data
            leituras_movidas += 1
    if descartes:
        titulos = dict(db.execute(select(Livro.id, Livro.titulo).where(
            Livro.id.in_([d["livro_id"] for d in descartes]))).all())
        for d in descartes:
            d["livro"] = titulos.get(d["livro_id"])

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
    # duplicados para respeitar a UNIQUE de idempotência e não dobrar a linha do
    # tempo. SEM a reatribuição, o delete cascatearia e apagaria em silêncio o
    # histórico do `remover`.
    # Duplicado = mesma chave OU mesmo CONTEÚDO: a mesma linha do relatório nas
    # duas fichas tem chaves que diferem só pelo id da ficha (``chave_evento``).
    # Qual cópia sai: de preferência a NATIVA do `manter` (a de uma ficha
    # absorvida prova a origem — é a evidência da restauração histórica,
    # ``leituras_restauracao``); senão, a que vem do `remover`. Nunca sai a
    # primeira ocorrência de um livro para a ficha de origem dela quando essa
    # ficha tem outra ocorrência do livro depois (``primeiras_ocorrencias``):
    # sem ela, a posterior passaria por primeira e a restauração aceitaria a data
    # errada. Se as duas cópias são assim, ficam as duas; cópia cuja origem a
    # chave não prova também fica. A cópia descartada vai para o log.
    eventos_do_manter = db.execute(
        select(EventoAluno).where(EventoAluno.aluno_id == manter.id)
    ).scalars().all()
    eventos_do_remover = db.execute(
        select(EventoAluno).where(EventoAluno.aluno_id == remover.id)
    ).scalars().all()
    origem_de: dict[int, int | None] = {}
    for eventos_da_ficha, origens in ((eventos_do_manter, (manter.id,)),
                                      (eventos_do_remover, (remover.id,))):
        for evento in eventos_da_ficha:
            origem_de[evento.id] = origem_comprovada(evento, origens)
    protegidas = primeiras_ocorrencias(
        (evento.id, origem_de[evento.id], evento.livro_id, evento.plataforma,
         evento.ocorrido_em)
        for evento in (*eventos_do_manter, *eventos_do_remover))

    chaves_evt_manter: set[tuple[str, str]] = set()
    copia_no_manter: dict[tuple, EventoAluno] = {}      # conteúdo → cópia no `manter`
    for evento in eventos_do_manter:
        chaves_evt_manter.add((evento.plataforma, evento.chave_natural))
        conteudo = conteudo_evento(evento.plataforma, evento.tipo_evento,
                                   evento.conteudo_titulo, evento.ocorrido_em)
        if conteudo is not None:
            copia_no_manter.setdefault(conteudo, evento)
    eventos_movidos = eventos_descartados = 0
    eventos_descartes: list[dict] = []
    for evento in eventos_do_remover:
        chave = (evento.plataforma, evento.chave_natural)
        if chave in chaves_evt_manter:
            db.delete(evento)
            eventos_descartados += 1
            continue
        conteudo = conteudo_evento(evento.plataforma, evento.tipo_evento,
                                   evento.conteudo_titulo, evento.ocorrido_em)
        existente = copia_no_manter.get(conteudo) if conteudo is not None else None
        # A MESMA ocorrência só quando a chave de uma das cópias prova que ela
        # nasceu sem ``extra`` (a repetição no mesmo minuto, com ``extra``,
        # continua distinta).
        if existente is not None and (origem_de[existente.id] is not None
                                      or origem_de[evento.id] is not None):
            ordem = ((existente, evento) if origem_de[existente.id] == manter.id
                     else (evento, existente))
            sai = next((copia for copia in ordem if origem_de[copia.id] is not None
                        and copia.id not in protegidas), None)
            if sai is not None:
                fica = existente if sai is evento else evento
                eventos_descartes.append({
                    "evento_id": sai.id, "da_ficha": sai.aluno_id,
                    "igual_ao_evento_id": fica.id, "livro_id": sai.livro_id,
                    "ocorrido_em": sai.ocorrido_em.isoformat(),
                    "chave_natural": sai.chave_natural})
                db.delete(sai)
                eventos_descartados += 1
                if sai is evento:
                    continue
                copia_no_manter[conteudo] = evento
        evento.aluno_id = manter.id
        chaves_evt_manter.add(chave)
        if conteudo is not None:
            copia_no_manter.setdefault(conteudo, evento)
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

    # MEMÓRIA DAS DECISÕES HUMANAS (``RevisaoIdentidade.aluno_escolhido_id``): a
    # escolha de um gestor/Admin Global para uma identidade segue a criança. Sem
    # isto, o delete do `remover` zerava a coluna (FK ``ondelete=SET NULL``), o
    # ``carregar_contexto`` deixava de ler a memória, e a coleta seguinte mandava
    # de novo para a revisão a conta que o Admin Global confirmou (D10, passo 0d
    # de ``decidir``) — e a gestão leva 403 no /resolver. ``resolucao`` não muda:
    # é o registro do que foi escolhido na época.
    decisoes_movidas = db.execute(
        update(RevisaoIdentidade)
        .where(RevisaoIdentidade.escola_id == escola_id,
               RevisaoIdentidade.aluno_escolhido_id == remover.id)
        .values(aluno_escolhido_id=manter.id)
    ).rowcount

    # CANDIDATOS DAS PENDÊNCIAS: a lista é a foto de quando a revisão abriu. Com o
    # `remover` apagado, oferecê-lo dava 400 no /resolver depois do clique. Nas
    # PENDENTES ele sai e entra o `manter` (a mesma criança), se já não estiver; a
    # resolvida/descartada é registro do que foi decidido e não muda.
    pendencias_atualizadas = _trocar_candidato_nas_pendencias(db, escola_id, manter, remover)

    # NOTIFICAÇÕES: ``Notificacao.aluno_id`` não tem FK; sem isto, o aviso da ficha
    # absorvida ficava órfão e sumia do filtro por aluno (o do professor).
    notificacoes_movidas = db.execute(
        update(Notificacao).where(Notificacao.aluno_id == remover.id)
        .values(aluno_id=manter.id)
    ).rowcount
    # ...e o LINK vai junto: com o aviso no sino de quem vê a ficha que ficou (a
    # professora da turma dela), "/alunos/<absorvida>" abria "Aluno não encontrado".
    db.execute(
        update(Notificacao)
        .where(Notificacao.escola_id == escola_id, Notificacao.entidade == "aluno",
               Notificacao.entidade_id == remover.id)
        .values(entidade_id=manter.id))
    db.execute(
        update(Notificacao)
        .where(Notificacao.escola_id == escola_id,
               Notificacao.rota == f"/alunos/{remover.id}")
        .values(rota=f"/alunos/{manter.id}"))

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
        "pendencias_atualizadas": pendencias_atualizadas,
        "notificacoes_movidas": notificacoes_movidas,
    }
    registrar(db, "aluno.fundido", escola_id=escola_id, usuario_id=usuario_id,
              entidade="aluno", entidade_id=manter_id,
              detalhes={"mantido": {"id": manter_id, "nome": manter_nome},
                        "removido": {"id": remover.id, "nome": remover_nome},
                        "foto_pre_fusao": foto,
                        "decisoes_de_identidade_movidas": decisoes_movidas,
                        "leituras_descartadas_detalhe": descartes,
                        "eventos_descartados_detalhe": eventos_descartes,
                        **contagens})
    # Grava as reatribuições ANTES do delete — o cascade não pega o que foi movido.
    db.flush()
    db.delete(remover)

    return {"aluno_id": manter_id, "manter_nome": manter_nome,
            "remover_nome": remover_nome, **contagens}
