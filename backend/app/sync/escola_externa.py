"""VÍNCULO da escola do Constela com a escola EXTERNA da conta na plataforma.

POR QUE ISTO EXISTE. A credencial de uma escola é uma conta do Elefante/Matific,
e uma conta pode enxergar MAIS DE UMA escola na plataforma (gestor de duas
unidades, conta da Secretaria) — ou ser, por engano, a credencial de OUTRA
escola. O código não conferia a escola: com a credencial trocada, os dados de
outra escola entravam como se fossem desta (com a política "permitir", criando
fichas; com "bloquear", lotando a revisão).

O vínculo guarda, por (escola do Constela, plataforma), QUAL escola da plataforma
esta escola é: o id externo (``schoolId`` do Elefante, ``school_id`` do Matific)
e o nome com que a plataforma a mostra. Nada de segredo: é o que a própria tela
da plataforma mostra ao gestor. Fica na tabela ``configuracoes`` (namespace
próprio, uma linha por plataforma) — sem migração.

Regras (aplicadas pelo conector, que recusa ANTES de pedir os dados de turma, e
pelo serviço, que recusa antes de aplicar):

  * sem vínculo e a conta enxerga EXATAMENTE uma escola → o vínculo é APRENDIDO
    nessa coleta (é o que acontece com as escolas atuais na 1ª coleta depois da
    implantação) — menos quando o NOME que a plataforma mostra não confere com o
    cadastrado (decisão D9): aí a coleta segue, mas o vínculo não é gravado;
  * sem vínculo e a conta enxerga mais de uma → 'erro' ``conta_multiescola``:
    nada é aplicado até um Admin Global ou o coordenador da escola escolher a
    escola externa (``PUT /escolas/{id}/sync/escola-externa/{plataforma}``);
  * com vínculo, a escola vinculada precisa estar entre as que a conta enxerga;
    senão → 'erro' ``escola_externa_trocada`` (a credencial foi trocada pela de
    outra escola, ou a conta perdeu o acesso);
  * nenhuma escola identificável na resposta → 'erro'
    ``escola_nao_identificada`` (a suposição sobre a plataforma deixou de
    valer — ver docs/SINCRONIZACAO.md);
  * a mesma escola externa já vinculada a OUTRA escola do Constela → 'erro'
    ``escola_externa_em_outra_escola`` (a credencial cadastrada aqui é da outra);
  * sem vínculo, e TODAS as contas identificadas da coleta já são a identidade
    efetiva de alunos de OUTRA escola do Constela (nenhuma desta escola, nenhuma
    desconhecida) → 'erro' ``contas_de_outra_escola`` (decisão D8, LGPD): é a
    assinatura da credencial da outra escola, e nada é gravado — nem ficha, nem
    retrato, nem a revisão com o nome da criança de lá.

O NOME nunca bloqueia a coleta (nomes variam entre o cadastro e a plataforma):
com vínculo gravado é só aviso; sem vínculo, o nome divergente só impede o
APRENDIZADO automático (D9 — critério em ``nomes_compativeis``), e o vínculo fica
para o Admin Global gravar depois de conferir.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

NAMESPACE = "sync_escola_externa"
PLATAFORMAS = ("elefante", "matific")
ORIGENS = ("aprendido", "explicito")

# Códigos de erro do vínculo (mapa de alertas em ``service.ALERTA_POR_CODIGO``).
CONTA_MULTIESCOLA = "conta_multiescola"
ESCOLA_TROCADA = "escola_externa_trocada"
ESCOLA_NAO_IDENTIFICADA = "escola_nao_identificada"
ESCOLA_EM_OUTRA_ESCOLA = "escola_externa_em_outra_escola"
CONTAS_DE_OUTRA_ESCOLA = "contas_de_outra_escola"
CODIGOS = (CONTA_MULTIESCOLA, ESCOLA_TROCADA, ESCOLA_NAO_IDENTIFICADA, ESCOLA_EM_OUTRA_ESCOLA,
           CONTAS_DE_OUTRA_ESCOLA)

_RE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_RE_NUMERO = re.compile(r"^[0-9]{1,20}$")


def normalizar_id(plataforma: str, valor) -> str:
    """O id externo da escola na forma canônica, ou '' se não tem a forma da
    plataforma: Elefante = número (``schoolId``); Matific = uuid (``school_id``)."""
    if valor is None or isinstance(valor, bool):
        return ""
    texto = str(valor).strip().lower()
    if plataforma == "elefante":
        return texto if _RE_NUMERO.match(texto) else ""
    if plataforma == "matific":
        return texto if _RE_UUID.match(texto) else ""
    return ""


def _linha(db: Session, escola_id: int, plataforma: str):
    from app.models.configuracao import Configuracao

    return db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola_id,
        Configuracao.namespace == NAMESPACE,
        Configuracao.chave == plataforma)).scalars().first()


def _valor_legivel(plataforma: str, valor) -> dict | None:
    if not isinstance(valor, dict):
        return None
    id_ext = normalizar_id(plataforma, valor.get("id"))
    if not id_ext:
        return None
    return {"id": id_ext, "nome": str(valor.get("nome") or "")[:200],
            "origem": str(valor.get("origem") or "aprendido"),
            "definido_em": valor.get("definido_em"),
            "definido_por": valor.get("definido_por")}


def obter(db: Session, escola_id: int, plataforma: str) -> dict | None:
    """O vínculo desta escola nesta plataforma, ou None (ainda não aprendido).
    Um valor ilegível (editado à mão, id fora da forma) vale como AUSENTE — e a
    próxima coleta o reaprende pelas mesmas regras."""
    linha = _linha(db, escola_id, plataforma)
    return _valor_legivel(plataforma, linha.valor) if linha is not None else None


def obter_de_cada(db: Session, escola_id: int, plataformas) -> dict[str, dict | None]:
    """``obter`` de várias plataformas numa consulta só (o /status lê todas)."""
    from app.models.configuracao import Configuracao

    plataformas = list(plataformas)
    linhas = {linha.chave: linha for linha in db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola_id,
        Configuracao.namespace == NAMESPACE,
        Configuracao.chave.in_(plataformas))).scalars()}
    return {p: (_valor_legivel(p, linhas[p].valor) if p in linhas else None)
            for p in plataformas}


def salvar(db: Session, escola_id: int, plataforma: str, id_externo: str, nome: str = "",
           *, origem: str = "aprendido", usuario_id: int | None = None) -> dict:
    """Grava (ou troca) o vínculo. O chamador confere antes que o id não está
    vinculado a outra escola (``escolas_com_o_mesmo_vinculo``) e commita."""
    from app.models.configuracao import Configuracao

    id_ext = normalizar_id(plataforma, id_externo)
    if not id_ext:
        raise ValueError("id externo fora da forma da plataforma")
    valor = {"id": id_ext, "nome": (nome or "").strip()[:200],
             "origem": origem if origem in ORIGENS else "aprendido",
             "definido_em": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
             "definido_por": usuario_id}
    linha = _linha(db, escola_id, plataforma)
    if linha is None:
        db.add(Configuracao(escola_id=escola_id, namespace=NAMESPACE, chave=plataforma,
                            valor=valor))
    else:
        linha.valor = valor
    db.flush()
    return _valor_legivel(plataforma, valor) or {}


def remover(db: Session, escola_id: int, plataforma: str) -> bool:
    linha = _linha(db, escola_id, plataforma)
    if linha is None:
        return False
    db.delete(linha)
    db.flush()
    return True


def escolas_com_o_mesmo_vinculo(db: Session, plataforma: str, id_externo: str, *,
                                exceto: int | None = None) -> list[int]:
    """Escolas do Constela já vinculadas a esta escola externa (fora ``exceto``).
    Poucas linhas (uma por escola e plataforma): a comparação é feita aqui, sem
    depender de consulta a JSON (que difere entre SQLite e PostgreSQL)."""
    from app.models.configuracao import Configuracao

    alvo = normalizar_id(plataforma, id_externo)
    if not alvo:
        return []
    saida = []
    for escola_id, valor in db.execute(select(Configuracao.escola_id, Configuracao.valor).where(
            Configuracao.namespace == NAMESPACE, Configuracao.chave == plataforma)).all():
        legivel = _valor_legivel(plataforma, valor)
        if legivel and legivel["id"] == alvo and escola_id != exceto:
            saida.append(int(escola_id))
    return sorted(set(saida))


def ids_de_outras_escolas(db: Session, plataforma: str, escola_id: int) -> frozenset[str]:
    """As escolas externas já vinculadas a OUTRAS escolas do Constela (ids
    normalizados) — vão no contexto da coleta para o conector recusar a conta de
    outra escola ANTES de pedir qualquer dado de turma (o conector não toca o
    banco)."""
    from app.models.configuracao import Configuracao

    ids = set()
    for eid, valor in db.execute(select(Configuracao.escola_id, Configuracao.valor).where(
            Configuracao.namespace == NAMESPACE, Configuracao.chave == plataforma)).all():
        legivel = _valor_legivel(plataforma, valor)
        if legivel and eid != escola_id:
            ids.add(legivel["id"])
    return frozenset(ids)


# ---------------------------------------------------------------------------
# Nome: aviso e porteiro do APRENDIZADO automático (decisão D9)
# ---------------------------------------------------------------------------
# Palavras que não identificam a escola (tipo, preposições, títulos): "EMEF
# PROF. JORGE PASSOS" e "Escola Municipal Professor Jorge Passos" são a mesma.
_VAZIAS = frozenset({
    "e", "de", "da", "do", "das", "dos", "a", "o", "em",
    "escola", "municipal", "estadual", "ensino", "fundamental", "infantil", "educacao",
    "emef", "emei", "emeief", "emeif", "ee", "eeef", "emeb", "cmei", "cemei", "ceu", "cei",
    "ef", "ei", "creche",
    "prof", "profa", "professor", "professora", "dr", "dra", "doutor", "doutora",
    "ver", "vereador", "vereadora", "pres", "presidente", "gov", "governador",
    "dep", "deputado", "deputada", "cel", "coronel", "pe", "padre", "mons", "monsenhor",
    "unidade", "integral", "polo",
})


def _tokens(nome: str) -> set[str]:
    base = unicodedata.normalize("NFKD", nome or "")
    base = "".join(c for c in base if not unicodedata.combining(c)).casefold()
    tokens = re.findall(r"[a-z0-9]+", base)
    return {t for t in tokens if t not in _VAZIAS and len(t) > 1}


def _quase_iguais(a: str, b: str) -> bool:
    """Tokens iguais ou, com 5+ letras os dois, a UMA edição (letra trocada, a mais
    ou a menos): "THIMOTEO" × "TIMOTEO", "PASSOS" × "PASOS". Palavra curta só
    vale igual ("ANA" × "ANE" são outras)."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    curto, longo = (a, b) if len(a) < len(b) else (b, a)
    return any(longo[:i] + longo[i + 1:] == curto for i in range(len(longo)))


def nomes_compativeis(nome_plataforma: str, nome_cadastro: str) -> bool:
    """O nome que a plataforma mostra pode ser o da escola cadastrada?

    CRITÉRIO (documentado em docs/SINCRONIZACAO.md, decisão D9). Os dois nomes
    são normalizados — sem acento, sem caixa, sem pontuação — e reduzidos às
    palavras que identificam a escola (fora o tipo, as preposições e os títulos:
    EMEF, Escola Municipal, Prof., Vereador…; e letras soltas, como iniciais).
    São compatíveis quando as palavras do nome mais curto aparecem no outro, com
    tolerância de UMA letra nas palavras de 5+ letras — todas, ou ao menos dois
    terços delas (e no mínimo duas). Assim "EMEF PROF. JORGE PASSOS" casa com
    "Escola Municipal Professor Jorge Pasos" e "Mª Aparecida Ferreira Santos" com
    "Maria Aparecida Ferreira Santos", mas "Maria das Dores" não casa com "Maria
    José" (só "Maria" em comum).

    Nome vazio (ou só de palavras genéricas) de qualquer lado: não há o que
    comparar — compatível (sem aviso e sem bloquear o aprendizado). Usado no aviso
    da importação manual e do "Testar conexão" e, na sincronização, para NÃO
    aprender o vínculo automaticamente quando diverge (D9)."""
    a, b = _tokens(nome_plataforma), _tokens(nome_cadastro)
    if not a or not b:
        return True
    for menor, maior in ((a, b), (b, a)):
        if len(menor) > len(maior):
            continue
        casadas = sum(1 for t in menor if any(_quase_iguais(t, u) for u in maior))
        if casadas == len(menor) or (casadas >= 2 and 3 * casadas >= 2 * len(menor)):
            return True
    return False


def nomes_divergentes(nomes, nome_cadastro: str) -> list[str]:
    """Os nomes (não vazios) com que a plataforma mostra a escola que não são
    compatíveis com o cadastrado (``nomes_compativeis``), sem repetição."""
    return sorted({n for n in nomes or () if n and not nomes_compativeis(n, nome_cadastro)})


def aviso_de_nome(nome_plataforma: str, nome_cadastro: str) -> str:
    """Texto do AVISO de nome divergente ('' quando os nomes podem ser da mesma
    escola, ou falta um dos dois). Nunca bloqueia: nomes variam."""
    if not nome_plataforma or nomes_compativeis(nome_plataforma, nome_cadastro):
        return ""
    return (f"Aviso: o relatório é da escola “{nome_plataforma[:80]}” e esta escola está "
            f"cadastrada como “{(nome_cadastro or '')[:80]}”. Nomes variam — confira se o "
            "relatório é desta escola antes de confirmar.")


def descrever(escolas: list[dict]) -> str:
    """'23952 (EMEF ...), 23953' — para mensagens ao gestor (sem segredo)."""
    partes = []
    for e in escolas or []:
        nome = (e.get("nome") or "").strip()
        partes.append(f"{e.get('id')} ({nome[:60]})" if nome else str(e.get("id")))
    return ", ".join(partes)
