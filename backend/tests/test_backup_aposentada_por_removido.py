"""Restauração do backup × autor de uma APOSENTADORIA removido depois do backup
(4ª revisão de integração do e97, dimensão identidade-backup; regressão da prova 2,
invertida).

O export leva ``identidades_externas.aposentada_por_id`` (FK para ``usuarios``,
fora de ``backup.IGNORADAS``). Usuários não entram no backup: se quem aposentou a
conta foi removido em definitivo depois do backup (DELETE
/usuarios/{id}/permanente, só do Admin Global; na linha viva a FK é SET NULL), o
INSERT violava a FK e a restauração inteira voltava 400 "dados inconsistentes ou
duplicados" — o backup anterior deixava de ser restaurável. Agora a referência ao
usuário que não existe mais vira NULL (``backup.REFERENCIAS_A_USUARIO``) e o resto
da linha (status, aposentada_em, motivo) volta como veio; com o autor vivo, nada
muda. Dados 100% fictícios; sem rede.
"""
import io
import json

from sqlalchemy import select

from app.core.security import hash_senha
from app.models import IdentidadeExterna, Usuario
from app.services import backup as svc_backup
from app.services import identidade_efetiva

API = "/api/v1"
MOTIVO = "conta duplicada (ficticio)"


def _estado(db, escola_completa):
    """A coordenadora (fictícia) aposenta a conta duplicada da Ana."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    coord = Usuario(escola_id=eid, nome="Coordenadora Ficticia",
                    email="coord.ficticia@teste.local", senha_hash=hash_senha("s3nh4"),
                    cargo="coordenador")
    db.add(coord)
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="matific",
                             id_externo="u-efetiva"))
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="matific",
                             id_externo="u-duplicada"))
    db.commit()
    identidade_efetiva.definir_efetiva(
        db, eid, aluno_id=a.id, plataforma="matific", id_externo_efetivo="u-efetiva",
        aposentar=["u-duplicada"], motivo=MOTIVO, usuario_id=coord.id)
    db.commit()
    return eid, a, coord


def _restaurar(cliente_global, eid, dados):
    arq = io.BytesIO(json.dumps(dados).encode("utf-8"))
    return cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                               files={"arquivo": ("b.json", arq, "application/json")})


def _identidades(db, eid):
    db.expire_all()
    return {i.id_externo: i for i in db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == eid)).scalars()}


def _aposentada_no_arquivo(dados):
    [apos] = [i for i in dados["tabelas"]["identidades_externas"]
              if i["status"] == "aposentada"]
    return apos


def test_backup_restaura_com_o_autor_da_aposentadoria_vivo_e_mantem_o_autor(
        db, escola_completa, cliente, cliente_global):
    eid, a, coord = _estado(db, escola_completa)
    b = cliente.get(f"{API}/escolas/{eid}/backup")
    assert b.status_code == 200, b.text
    r = _restaurar(cliente_global, eid, b.json())
    assert r.status_code == 200, r.text
    dup = _identidades(db, eid)["u-duplicada"]
    assert (dup.status, dup.aposentada_por_id, dup.motivo_aposentadoria) == (
        "aposentada", coord.id, MOTIVO)


def test_backup_anterior_a_remocao_de_quem_aposentou_restaura_sem_o_autor(
        db, escola_completa, cliente, cliente_global):
    eid, a, coord = _estado(db, escola_completa)
    coord_id = coord.id
    b = cliente.get(f"{API}/escolas/{eid}/backup")
    assert b.status_code == 200, b.text
    dados = b.json()
    apos = _aposentada_no_arquivo(dados)
    assert apos["aposentada_por_id"] == coord_id
    # Depois do backup, o Admin Global remove a coordenadora em definitivo.
    d = cliente_global.delete(f"{API}/escolas/{eid}/usuarios/{coord_id}/permanente",
                              params={"confirmacao": coord.email})
    assert d.status_code == 200, d.text
    r = _restaurar(cliente_global, eid, dados)
    assert r.status_code == 200, r.text                  # antes: 400 "inconsistentes"
    ids = _identidades(db, eid)
    dup = ids["u-duplicada"]
    # A conta continua APOSENTADA (a decisão da escola volta), só sem o autor.
    assert dup.status == "aposentada"
    assert dup.aposentada_por_id is None
    assert dup.motivo_aposentadoria == MOTIVO
    assert dup.aposentada_em is not None
    assert dup.aposentada_em.isoformat()[:19] == str(apos["aposentada_em"])[:19]
    assert dup.aluno_id == ids["u-efetiva"].aluno_id
    assert ids["u-efetiva"].status == "efetiva"


def test_restaurar_servico_anula_so_a_referencia_a_usuario_inexistente(db, escola_completa):
    """No serviço, direto: um id de usuário que nunca existiu neste banco (arquivo
    levado para outro banco) também vira NULL, e a contagem não perde a linha."""
    eid, a, coord = _estado(db, escola_completa)
    db.expire_all()
    dados = json.loads(json.dumps(svc_backup.exportar(db, eid), default=str))
    _aposentada_no_arquivo(dados)["aposentada_por_id"] = 987654
    contagem = svc_backup.restaurar(db, eid, dados)
    db.commit()
    assert contagem["identidades_externas"] == 2
    dup = _identidades(db, eid)["u-duplicada"]
    assert (dup.status, dup.aposentada_por_id, dup.motivo_aposentadoria) == (
        "aposentada", None, MOTIVO)


def test_referencias_a_usuario_no_arquivo_sao_varridas_no_metadata():
    """Catraca: toda coluna de tabela do backup com FK para ``usuarios`` que SAI no
    arquivo está em ``REFERENCIAS_A_USUARIO`` (hoje só ``aposentada_por_id``) — uma
    coluna nova assim não volta a derrubar a restauração."""
    esperado = {}
    for nome, modelo in svc_backup.MODELOS:
        colunas = tuple(c.name for c in modelo.__table__.columns
                        if c.name not in svc_backup.IGNORADAS
                        and any(fk.column.table.name == "usuarios" for fk in c.foreign_keys))
        if colunas:
            esperado[nome] = colunas
    assert svc_backup.REFERENCIAS_A_USUARIO == esperado
    assert svc_backup.REFERENCIAS_A_USUARIO["identidades_externas"] == ("aposentada_por_id",)
