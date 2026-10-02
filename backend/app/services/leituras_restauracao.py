"""Restauração histórica de leituras: devolver a uma ``Leitura`` a data e o
tempo que ela comprovadamente tinha, usando o ``EventoAluno`` como evidência.

POR QUE ISTO EXISTE. A fusão de duas fichas do mesmo aluno
(``alunos_fusao.fundir_par``) deduplica as leituras por ``livro_id`` e mantém a
linha de QUEM FICA — com a data de quem fica. Quando a ficha sobrevivente é a
que tem o histórico ANTIGO, o livro continua contado, mas passa a valer com uma
data velha: ele SAI da janela do período premiado. A perda é invisível no total
anual e decisiva no pódio do bimestre. Nenhum caminho existente conserta: o
importador pula livro que "já constava" (§35) e NUNCA atualiza
``Leitura.data`` — reimportar e sincronizar são no-op.

A EVIDÊNCIA. O espelho de eventos (``EventoAluno``) é gravado por um laço
SEPARADO do das leituras, que percorre TODAS as linhas do relatório — inclusive
as que a §35 descarta. Os dois nascem da MESMA linha, com o mesmo instante e o
mesmo tempo (``tempo_segundos = tempo_livro_min * 60``). E a ``chave_natural``
do evento é ``sha256("plataforma|tipo|aluno_id|titulo|minuto|extra")``: o
``aluno_id`` da ficha ONDE o evento nasceu está DENTRO do hash, e a fusão move a
linha sem regenerar a chave. Logo o evento sobrevivente prova, criptográfica e
não estatisticamente, três coisas: de qual ficha ele veio, em que instante, e
com que tempo.

A REGRA. A linha ``Leitura`` nasce na PRIMEIRA importação que viu o livro e
nunca é atualizada. Toda importação seguinte grava um evento NOVO, com data
maior. Portanto o que a fusão apagou é, exatamente:

    data  = min(ocorrido_em dos eventos DAQUELA ficha, para aquele livro)
    tempo = tempo_segundos / 60 desse MESMO primeiro evento

Este serviço NÃO deduz nada: o chamador declara o que quer restaurar e a
evidência que sustenta cada item, e aqui cada afirmação é CONFERIDA contra o
banco — inclusive recalculando o hash. Sem evidência que feche, a operação
inteira é recusada. É o oposto de "completar" um número que não fechou.

GOVERNANÇA. Reescrever histórico é ação retroativa, então vale a mesma régua do
``aplicar_ao_historico`` do catálogo: só o Admin Global, com motivo escrito,
auditada item a item com o de/para e o evento-fonte, e numa transação única.
Este módulo NÃO commita — quem chama confirma, igual a ``alunos_fusao``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, EventoAluno, Leitura, Livro
from app.models.base import agora
from app.services.audit import registrar
from app.services.eventos import chave_evento

# Nomes das ações de auditoria (``LogAuditoria.acao`` é String(80)).
ACAO_ITEM = "leitura.data_restaurada"
ACAO_LOTE = "leituras.restauracao_historica"

MOTIVO_MINIMO = 10


class RestauracaoInvalida(Exception):
    """Um item não se sustenta na evidência. A operação INTEIRA é recusada.

    ``indice`` é a posição do item no lote recebido (0-based) para o chamador
    apontar a linha exata; ``None`` quando o problema é do lote como um todo.
    """

    def __init__(self, mensagem: str, indice: int | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.indice = indice


@dataclass(frozen=True)
class ItemRestauracao:
    """Uma restauração pedida, com a evidência que o chamador afirma ter.

    ``aluno_origem_id`` é a ficha ABSORVIDA, de onde o dado veio. Ela não existe
    mais como registro — e não precisa: o que a identifica é estar dentro do
    hash da ``chave_natural`` do evento. É justamente por isso que ela é
    declarada e conferida, nunca adivinhada.
    """

    aluno_id: int
    aluno_origem_id: int
    livro_id: int
    data_original: datetime
    tempo_original: int | None
    evidencia_evento_id: int
    evidencia_chave_natural: str
    motivo: str


def _sem_tz(momento: datetime) -> datetime:
    """``Leitura.data`` e ``EventoAluno.ocorrido_em`` são naive (a data do
    relatório é naive). Comparar aware com naive levanta TypeError, então
    normaliza antes — sem deslocar o instante de quem já é naive."""
    return momento.replace(tzinfo=None) if momento.tzinfo is not None else momento


def _conferir(db: Session, escola_id: int, item: ItemRestauracao,
              indice: int, *, permitir_fora_do_ano_letivo: bool) -> dict:
    """Confere UM item contra o banco e devolve o plano daquela linha.

    Só leitura: nada aqui altera estado. É a MESMA função que o dry-run usa, de
    propósito — um ensaio que não passa pela validação real não ensaia nada.
    """
    def recusar(mensagem: str):
        return RestauracaoInvalida(mensagem, indice)

    if not (item.motivo or "").strip() or len(item.motivo.strip()) < MOTIVO_MINIMO:
        raise recusar(
            f"O item {indice + 1} está sem motivo escrito. Reescrever histórico "
            f"exige dizer por quê, em pelo menos {MOTIVO_MINIMO} caracteres — é "
            "o que a auditoria vai mostrar para quem perguntar depois.")

    if item.aluno_origem_id == item.aluno_id:
        raise recusar(
            f"No item {indice + 1}, a ficha de origem e a de destino são a "
            f"mesma ({item.aluno_id}). Uma restauração histórica só faz sentido "
            "quando o dado veio de OUTRA ficha — a que a fusão absorveu.")

    # --- 1 e 2: o aluno existe, é desta escola e está ativo
    aluno = db.get(Aluno, item.aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise recusar(
            f"A ficha {item.aluno_id} do item {indice + 1} não é desta escola.")
    if aluno.status != "ativo":
        raise recusar(
            f"“{aluno.nome}” está com status “{aluno.status}”. Não se reescreve "
            "o histórico de uma ficha que não está ativa: resolva a situação "
            "cadastral primeiro.")

    # --- 3: o livro existe e é desta escola
    livro = db.get(Livro, item.livro_id)
    if livro is None or livro.escola_id != escola_id:
        raise recusar(
            f"O livro {item.livro_id} do item {indice + 1} não é do acervo "
            "desta escola.")

    # --- 4: a leitura a corrigir existe (e é uma só — a UNIQUE garante)
    leitura = db.execute(
        select(Leitura).where(Leitura.aluno_id == item.aluno_id,
                              Leitura.livro_id == item.livro_id)).scalars().first()
    if leitura is None:
        raise recusar(
            f"“{aluno.nome}” não tem leitura registrada de “{livro.titulo}”. "
            "Este serviço CORRIGE a data de uma leitura existente; ele não cria "
            "leitura nenhuma — criar seria inventar que a criança leu.")
    if leitura.escola_id != escola_id:
        raise recusar(
            f"A leitura {leitura.id} do item {indice + 1} está registrada em "
            "outra escola.")

    # --- 5: a evidência existe
    evento = db.get(EventoAluno, item.evidencia_evento_id)
    if evento is None:
        raise recusar(
            f"O evento {item.evidencia_evento_id}, apresentado como evidência "
            f"do item {indice + 1}, não existe.")
    if evento.escola_id != escola_id:
        raise recusar(
            f"O evento {evento.id} do item {indice + 1} é de outra escola.")

    # --- 6: a evidência é do aluno e do livro certos, e a chave declarada é a
    # que está gravada (impede apresentar um hash calculado por fora)
    if evento.aluno_id != item.aluno_id:
        raise recusar(
            f"O evento {evento.id} está na ficha {evento.aluno_id}, não na "
            f"{item.aluno_id}. Evidência de outra criança não restaura nada.")
    if evento.livro_id != item.livro_id:
        raise recusar(
            f"O evento {evento.id} é do livro {evento.livro_id}, e o item "
            f"{indice + 1} quer corrigir o livro {item.livro_id}.")
    if evento.chave_natural != item.evidencia_chave_natural:
        raise recusar(
            f"A chave natural declarada no item {indice + 1} não é a do evento "
            f"{evento.id} que está gravado.")

    # --- 7: a evidência COMPROVA a data. Duas conferências independentes: o
    # instante gravado e o hash. O hash fixa o MINUTO e a ficha de ORIGEM; a
    # igualdade com ``ocorrido_em`` fixa o segundo. Juntas, não sobra folga.
    data_original = _sem_tz(item.data_original)
    if _sem_tz(evento.ocorrido_em) != data_original:
        raise recusar(
            f"O evento {evento.id} ocorreu em {evento.ocorrido_em:%d/%m/%Y %H:%M}, "
            f"e o item {indice + 1} afirma {data_original:%d/%m/%Y %H:%M}.")
    esperada = chave_evento(evento.plataforma, evento.tipo_evento,
                            item.aluno_origem_id, evento.conteudo_titulo or "",
                            data_original)
    if esperada != evento.chave_natural:
        raise recusar(
            f"A evidência do item {indice + 1} NÃO prova a origem: recalculando "
            f"a chave do evento {evento.id} para a ficha "
            f"{item.aluno_origem_id} em {data_original:%d/%m/%Y %H:%M} o hash "
            "não é o que está gravado. Ou o evento nasceu em outra ficha, ou a "
            "data não é a dele.")

    # --- 8: a evidência COMPROVA o tempo
    tempo_evidencia = ((evento.tempo_segundos or 0) // 60
                       if evento.tempo_segundos is not None else None)
    if (item.tempo_original or 0) != (tempo_evidencia or 0):
        raise recusar(
            f"O evento {evento.id} registra {tempo_evidencia} minuto(s) e o "
            f"item {indice + 1} afirma {item.tempo_original}. O tempo também "
            "tem que sair da evidência, não de uma estimativa.")

    # --- 9: a evidência é a PRIMEIRA ocorrência daquele livro naquela ficha.
    # É a regra inteira do método: a linha ``Leitura`` nasce na primeira
    # importação. Aceitar um evento posterior seria escolher a data mais
    # conveniente entre as disponíveis — exatamente a inferência que este
    # serviço existe para proibir.
    anteriores = [
        outro for outro in db.execute(
            select(EventoAluno).where(
                EventoAluno.aluno_id == item.aluno_id,
                EventoAluno.livro_id == item.livro_id,
                EventoAluno.plataforma == evento.plataforma,
                EventoAluno.ocorrido_em < evento.ocorrido_em)).scalars()
        if outro.chave_natural == chave_evento(
            outro.plataforma, outro.tipo_evento, item.aluno_origem_id,
            outro.conteudo_titulo or "", _sem_tz(outro.ocorrido_em))
    ]
    if anteriores:
        primeiro = min(anteriores, key=lambda e: e.ocorrido_em)
        raise recusar(
            f"O evento {evento.id} não é a primeira ocorrência de "
            f"“{livro.titulo}” na ficha {item.aluno_origem_id}: existe o "
            f"{primeiro.id}, em {primeiro.ocorrido_em:%d/%m/%Y %H:%M}. A data "
            "que a fusão apagou é a da PRIMEIRA, porque a linha de leitura "
            "nasce na primeira importação e nunca é atualizada.")

    # --- 10: nada a fazer é RECUSA, não sucesso silencioso. É esta regra que
    # protege os livros em que as duas fichas tinham a MESMA data: lá a fusão
    # não perdeu nada, e "restaurar" só maquiaria um número.
    atual = _sem_tz(leitura.data)
    if atual == data_original and (leitura.tempo_leitura_min or 0) == (item.tempo_original or 0):
        raise recusar(
            f"A leitura de “{livro.titulo}” já está em "
            f"{atual:%d/%m/%Y %H:%M} com {leitura.tempo_leitura_min} minuto(s) "
            "— a evidência confirma o que já está gravado. Nada foi perdido "
            "neste livro, então não há o que restaurar.")

    # --- 11: guarda de sanidade da data
    if data_original > _sem_tz(agora()):
        raise recusar(
            f"O item {indice + 1} quer datar a leitura em "
            f"{data_original:%d/%m/%Y}, no futuro.")
    if not permitir_fora_do_ano_letivo:
        escola = db.get(Escola, escola_id)
        ano = getattr(escola, "ano_letivo_ativo", None)
        if ano and data_original.year != ano:
            raise recusar(
                f"O item {indice + 1} restauraria para "
                f"{data_original:%d/%m/%Y}, fora do ano letivo ativo ({ano}). "
                "Se isso é mesmo o pretendido, é uma decisão explícita: use "
                "“permitir_fora_do_ano_letivo”.")

    return {
        "leitura_id": leitura.id,
        "aluno_id": item.aluno_id,
        "aluno_nome": aluno.nome,
        "aluno_origem_id": item.aluno_origem_id,
        "livro_id": item.livro_id,
        "livro_titulo": livro.titulo,
        "data_anterior": atual,
        "data_restaurada": data_original,
        "tempo_anterior": leitura.tempo_leitura_min,
        "tempo_restaurado": item.tempo_original,
        "evidencia_evento_id": evento.id,
        "evidencia_chave_natural": evento.chave_natural,
        "evidencia_plataforma": evento.plataforma,
        "motivo": item.motivo.strip(),
    }


def planejar(db: Session, escola_id: int, itens: list[ItemRestauracao], *,
             permitir_fora_do_ano_letivo: bool = False) -> list[dict]:
    """Confere o lote INTEIRO e devolve o plano, sem escrever nada.

    É o dry-run de verdade: mesma validação, mesma ordem, nenhuma escrita.
    Levanta ``RestauracaoInvalida`` no PRIMEIRO item que não se sustenta — se um
    item cai, o lote não vale, então não há motivo para continuar conferindo.
    """
    if not itens:
        raise RestauracaoInvalida("Nenhuma restauração foi informada.")

    vistos: set[tuple[int, int]] = set()
    plano: list[dict] = []
    for indice, item in enumerate(itens):
        # 12: duas correções do MESMO (aluno, livro) no mesmo lote — a segunda
        # sobrescreveria a primeira em silêncio, e o total mentiria.
        chave = (item.aluno_id, item.livro_id)
        if chave in vistos:
            raise RestauracaoInvalida(
                f"O item {indice + 1} repete o livro {item.livro_id} para a "
                f"ficha {item.aluno_id}, que já aparece antes neste lote.",
                indice)
        vistos.add(chave)
        plano.append(_conferir(db, escola_id, item, indice,
                               permitir_fora_do_ano_letivo=permitir_fora_do_ano_letivo))
    return plano


def restaurar(db: Session, escola_id: int, itens: list[ItemRestauracao],
              usuario_id: int | None, *,
              permitir_fora_do_ano_letivo: bool = False) -> dict:
    """Aplica a restauração. Tudo ou nada; NÃO commita (quem chama confirma).

    Confere o lote inteiro ANTES de tocar em qualquer linha: se o item 14 não se
    sustenta, os 13 primeiros nem chegam a ser escritos. Com commit do chamador,
    a transação única garante que auditoria, dados e recálculo caem juntos.
    """
    plano = planejar(db, escola_id, itens,
                     permitir_fora_do_ano_letivo=permitir_fora_do_ano_letivo)

    for linha in plano:
        leitura = db.get(Leitura, linha["leitura_id"])
        if leitura is None:          # pragma: no cover - conferido em planejar
            raise RestauracaoInvalida(
                f"A leitura {linha['leitura_id']} desapareceu durante a "
                "operação. Nada foi aplicado.")
        leitura.data = linha["data_restaurada"]
        leitura.tempo_leitura_min = linha["tempo_restaurado"]
        registrar(db, ACAO_ITEM, escola_id=escola_id, usuario_id=usuario_id,
                  entidade="leitura", entidade_id=leitura.id,
                  detalhes={k: (v.isoformat() if isinstance(v, datetime) else v)
                            for k, v in linha.items()})

    resumo = {
        "escola_id": escola_id,
        "leituras_restauradas": len(plano),
        "alunos": sorted({linha["aluno_id"] for linha in plano}),
        "livros": sorted(linha["livro_id"] for linha in plano),
        "minutos_de": sum((linha["tempo_anterior"] or 0) for linha in plano),
        "minutos_para": sum((linha["tempo_restaurado"] or 0) for linha in plano),
    }
    registrar(db, ACAO_LOTE, escola_id=escola_id, usuario_id=usuario_id,
              entidade="escola", entidade_id=escola_id,
              detalhes={**resumo,
                        "motivos": sorted({linha["motivo"] for linha in plano})})
    db.flush()
    return {**resumo, "itens": plano}
