"""Exclusão permanente de aluno — o que guarda o nome ou o id da criança FORA das
tabelas do cadastro (auditoria de 20/10/2026, achado 3).

``routers/academico._apagar_alunos_e_dados`` apaga o cadastro e os filhos diretos
(leituras, snapshots, notas, matrículas, eventos, identidades externas, Quest) e
anonimiza o log de auditoria. Sobravam, com o nome ou o id da criança: a fila de
revisões de identidade (nome recebido, linhas, candidatos), mensagens de
sincronização, o nome do arquivo original de relatório INDIVIDUAL importado (e o
próprio arquivo) e as cópias de relatórios em /exports. Este módulo fecha essas
lacunas com uma regra técnica única:

APAGADO (é dado da criança e não sustenta nenhuma obrigação):
  * revisão de identidade DELA — resolvida para ela, da identidade externa dela
    (plataforma + id externo) ou com o nome dela quando nenhuma outra criança da
    escola tem o mesmo nome (com homônimo vivo, o nome também é do outro: fica);
  * o arquivo original de um relatório INDIVIDUAL dela (o nome do arquivo traz o
    nome dela) e todas as cópias em /exports (não dá para saber quais trazem o
    nome; o download nunca depende delas) — os dois só DEPOIS do commit: se a
    exclusão reverter, nenhum arquivo some. O original só sai se for um arquivo
    que o servidor gravou para ESTA escola (nenhuma importação de outra escola
    aponta para ele) e que não traz dado de criança que continua;
  * as conversas da IA que citam o nome (``conversas_ia_que_citam``).
ANONIMIZADO (o nome vira ``[removido]``; o resto do registro fica):
  * revisão de OUTRA criança que a listava como candidata: a candidata excluída
    sai da lista, o nome dela some dos dados;
  * ``sincronizacao_logs``/``sincronizacao_alertas``/``sincronizacao_execucoes``
    que citem o nome; ``importacoes.arquivo_original`` com o nome;
  * original que traz dado de criança que continua (é a prova da importação
    dela, §15): RENOMEADO no disco para um nome neutro, e a linha aponta o novo
    nome — nem o arquivo nem o texto guardam o nome da excluída.

NOME QUE TAMBÉM É DE QUEM FICA (regra única, valendo para tudo acima): o texto que
cita o nome excluído só é tocado quando o trecho NÃO é também o nome — ou parte do
nome — de uma criança que continua na escola. Excluir "Joao Pedro Silva" não
mexe em "Joao Pedro Silva Testelli" (viva), nem no homônimo vivo "Joao Pedro
Silva": o texto não prova ser da excluída, e apagar destrói o dado de quem não
pediu esquecimento.
FICHAS ABSORVIDAS POR FUSÃO (``fichas_absorvidas``): são a mesma criança. Tudo acima
vale também para o nome que ela tinha nelas (o do stub da importação ou da coleta,
"ANA B. SOUZA"), salvo quando esse nome é também o nome — ou parte do nome — de quem
fica (``nomes_absorvidos_que_contam``, a mesma regra do log); e a candidata de
revisão que é a ficha absorvida sai da lista, como a da excluída.
FICA POR OBRIGAÇÃO DE AUDITORIA, SEM NOME: o log de auditoria (o id vira referência
anônima; inclusive o ``aluno.excluido_permanente``), o registro de cada importação
(quem, quando, quantos) e o histórico das sincronizações.

MARCA DE ESQUECIMENTO DAS CONTAS (``contas_da_crianca``, ``marcas_para_o_log``): a
conta da criança no Matific ou no Elefante Letrado continua existindo lá, e a coleta
seguinte a manda de novo. Sem memória, era uma conta desconhecida: com a política
padrão a ficha voltava inteira (nome, conta, retrato, ranking); com "bloquear", o
nome voltava para a fila de revisões e para o log. Por isso a exclusão permanente
grava no ``aluno.excluido_permanente`` de cada criança (preservado do expurgo,
``audit.ACOES_PRESERVADAS``) a MARCA de cada conta dela — a vinculada à ficha e a da
revisão que prova ser dela; a pendência que só tem o nome dela (pode ser de uma
homônima ainda sem ficha) não marca: a plataforma e o HMAC-SHA256
do id externo com a chave do servidor — nem o nome nem o id em claro. A porta única
de identidade (``identidade_aluno.decidir``) ignora a linha de conta marcada antes
de qualquer outro passo. Linha SEM conta (relatório ou planilha só com o nome) não
tem como ser reconhecida: a tela avisa.

FORA DO ALCANCE DESTE CÓDIGO (docs/lgpd/RETENCAO-TECNICA.md): backups já feitos,
originais de relatório de TURMA (várias crianças no mesmo arquivo), prévias não
confirmadas em uploads/temporarios (expiram em 24 h: o expurgo de fundo,
app/core/expurgo_arquivos.py, as apaga em até 25 h, no boot e a cada hora), logs da
aplicação/Sentry,
cópias fora do sistema e a plataforma de origem, onde a conta continua ativa até ser
encerrada lá (o Constela só passa a ignorá-la).

Nada aqui commita: o chamador fecha a transação.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import unicodedata
from pathlib import Path

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import segredos_da_cifra

logger = logging.getLogger("constela.exclusao")

MARCA_REMOVIDO = "[removido]"

# Palavra = letras/dígitos COM as marcas combinantes que vierem atrás. Em texto
# decomposto (NFD — nome de arquivo vindo de macOS: "Joa" + "~" + "o"), a marca não
# é \w e partiria "João" em "Joa" + "o"; o nome nunca seria achado dentro do texto.
_MARCAS = "\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f"
_PALAVRA = re.compile(rf"(?:[^\W_][{_MARCAS}]*)+")
# Como o /confirmar grava o original: AAAAMMDD_HHMMSS_<nome> (importacoes.py).
_NOME_GRAVADO_PELO_SERVIDOR = re.compile(r"\d{8}_\d{6}_.+")
_PENDENTES = "exclusao_aluno.arquivos_apos_commit"
_OUVINTE = "exclusao_aluno.ouvinte"


def _normalizar(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                         if unicodedata.category(c) != "Mn")
    return sem_acento.casefold()


def _palavras(texto: str) -> list[str]:
    return _PALAVRA.findall(_normalizar(texto))


def _chave(nome: str) -> str:
    return " ".join(_palavras(nome))


def _ocorrencias(sequencias: list[list[str]], normal: list[str]) -> list[tuple[int, int]]:
    """(1ª, última) palavra de cada ocorrência das sequências em ``normal``."""
    achadas = []
    for seq in sequencias:
        n = len(seq)
        for i in range(len(normal) - n + 1):
            if normal[i:i + n] == seq:
                achadas.append((i, i + n - 1))
    return achadas


class NomesAlvo:
    """Os nomes das crianças excluídas, prontos para procurar e redigir.

    Igualdade = mesmas palavras, sem acento/caixa/pontuação. Dentro de um texto
    maior, só nome de 2+ palavras e por PALAVRA inteira ("Ana Souza" não casa em
    "Mariana Souza Silva"; "Ana" sozinha não é procurada no meio de frase —
    ``palavra_unica=True`` procura, por palavra inteira, onde achar a mais é só
    apagar a mais, como nas conversas da IA).

    ``preservar`` = nomes de quem CONTINUA na escola. Trecho que também é o nome
    (ou está dentro do nome) de um deles não conta: excluir "Ana Souza" não toca
    "Ana Souza Lima", nem o homônimo vivo "Ana Souza"."""

    def __init__(self, nomes, preservar=(), *, palavra_unica: bool = False) -> None:
        self._vivas = {_chave(n) for n in preservar if n and _palavras(n)}
        self.chaves = {_chave(n) for n in nomes if n and _palavras(n)}
        minimo = 1 if palavra_unica else 2
        self._sequencias = [s.split() for s in self.chaves if len(s.split()) >= minimo]
        # Só um nome vivo que CONTÉM um nome procurado pode cobrir uma ocorrência; a
        # escola tem milhares de nomes vivos e o texto varrido (mensagens de sync,
        # revisões) também é grande — procurar todos em todo texto custava minutos
        # com a transação da exclusão aberta.
        self._sequencias_vivas = [
            viva for viva in (s.split() for s in self._vivas)
            if any(_ocorrencias([seq], viva) for seq in self._sequencias)]
        self._primeiras = {seq[0] for seq in self._sequencias}

    def __bool__(self) -> bool:
        return bool(self.chaves)

    def e_o_nome(self, valor: str) -> bool:
        if not isinstance(valor, str):
            return False
        chave = _chave(valor)
        return chave in self.chaves and chave not in self._vivas

    def _trechos(self, texto: str) -> list[tuple[int, int]]:
        # Atalho: sem a 1ª palavra de nenhum nome procurado no texto normalizado,
        # não há ocorrência (a palavra normalizada é pedaço do texto normalizado).
        normalizado = _normalizar(texto)
        if not any(primeira in normalizado for primeira in self._primeiras):
            return []
        palavras = list(_PALAVRA.finditer(texto))
        normal = [_normalizar(p.group()) for p in palavras]
        achadas = _ocorrencias(self._sequencias, normal)
        if not achadas:
            return []
        vivas = _ocorrencias(self._sequencias_vivas, normal)
        return [(palavras[i].start(), palavras[f].end()) for i, f in achadas
                if not any(vi <= i and f <= vf for vi, vf in vivas)]

    def cita(self, texto: str) -> bool:
        return bool(texto) and (self.e_o_nome(texto) or bool(self._trechos(texto)))

    def redigir_texto(self, texto: str) -> str:
        if not texto:
            return texto
        if self.e_o_nome(texto):
            return MARCA_REMOVIDO
        for inicio, fim in sorted(self._trechos(texto), reverse=True):
            texto = texto[:inicio] + MARCA_REMOVIDO + texto[fim:]
        return texto

    def redigir(self, valor):
        """Recursivo em dict/list (JSON gravado)."""
        if isinstance(valor, dict):
            return {chave: self.redigir(item) for chave, item in valor.items()}
        if isinstance(valor, list):
            return [self.redigir(item) for item in valor]
        if isinstance(valor, str):
            return self.redigir_texto(valor)
        return valor


# ---------------------------------------------------------------------------
# Revisões de identidade
# ---------------------------------------------------------------------------

def _revisao_dela(rev, ids: set[int], identidades: set[tuple[str, str]],
                  alvos: NomesAlvo) -> bool:
    """A revisão é da criança excluída: resolvida para ela, da conta dela ou, sem
    ficha escolhida, com o nome dela — este só quando nenhum homônimo continua
    (``e_o_nome`` já exclui o nome de quem fica: com homônimo vivo, o nome não
    prova ser dela). Esta regra APAGA a revisão (``_esquecer_revisoes``: ela guarda
    o nome dela). A marca da conta (``contas_da_crianca``) exige mais: o nome
    sozinho não prova de quem é a conta (``_donas_pela_pendencia``)."""
    return (rev.aluno_escolhido_id in ids
            or (rev.plataforma, rev.id_externo or "") in identidades
            or (rev.aluno_escolhido_id is None
                and alvos.e_o_nome(rev.nome_recebido or "")))


def _esquecer_revisoes(db: Session, escola_id: int, ids: set[int], vivos_ids: set[int],
                       alvos: NomesAlvo,
                       identidades: set[tuple[str, str]]) -> dict[str, int]:
    from app.models import RevisaoIdentidade

    apagadas = anonimizadas = 0
    for rev in db.execute(select(RevisaoIdentidade)
                          .where(RevisaoIdentidade.escola_id == escola_id)).scalars().all():
        if _revisao_dela(rev, ids, identidades, alvos):
            db.delete(rev)
            apagadas += 1
            continue
        # A candidata excluída sai. A de criança que CONTINUA na escola leva o
        # próprio nome (que pode coincidir com o dela) — não se redige. As demais
        # passam pelo casador, que já preserva o nome de quem fica: entrada sem
        # ``aluno_id`` e a de ficha que não existe mais (a fusão apaga a duplicata
        # e não mexe nas revisões: a candidata dela pode trazer o nome da excluída).
        candidatos = [c if isinstance(c, dict) and c.get("aluno_id") in vivos_ids
                      else alvos.redigir(c)
                      for c in (rev.candidatos or [])
                      if not (isinstance(c, dict) and c.get("aluno_id") in ids)]
        novos = {
            "candidatos": candidatos,
            "linhas": alvos.redigir(rev.linhas or []),
            "contexto": alvos.redigir(rev.contexto or {}),
            "resolucao": alvos.redigir(rev.resolucao) if rev.resolucao else rev.resolucao,
        }
        mudou = False
        for campo, valor in novos.items():
            if valor != getattr(rev, campo):
                setattr(rev, campo, valor)   # reatribui → o JSON é regravado
                mudou = True
        if mudou:
            anonimizadas += 1
    return {"revisoes_apagadas": apagadas, "revisoes_anonimizadas": anonimizadas}


# ---------------------------------------------------------------------------
# Sincronização e importações
# ---------------------------------------------------------------------------

def _redigir_mensagens_de_sync(db: Session, escola_id: int, alvos: NomesAlvo) -> int:
    from app.models import SincronizacaoAlerta, SincronizacaoExecucao, SincronizacaoLog

    redigidas = 0
    for modelo, campo in ((SincronizacaoLog, "mensagem"),
                          (SincronizacaoAlerta, "mensagem"),
                          (SincronizacaoExecucao, "erro_resumo")):
        for linha in db.execute(select(modelo).where(modelo.escola_id == escola_id)
                                .execution_options(yield_per=500)).scalars():
            texto = getattr(linha, campo)
            if texto and alvos.cita(texto):
                setattr(linha, campo, alvos.redigir_texto(texto))
                redigidas += 1
    return redigidas


def _arquivo_de_upload(caminho_gravado: str, plataforma: str) -> Path | None:
    """``uploads/<plataforma>/<AAAAMMDD_HHMMSS_nome>`` — exatamente a forma que o
    /confirmar grava — → caminho real, só se estiver DENTRO de UPLOADS_DIR (nunca
    apaga fora dele). Qualquer outra forma não é um original que o servidor
    gravou: ``arquivo_original`` também guarda o ``arquivo_nome`` que o CLIENTE
    mandou (importação sem ``arquivo_token``), que não prova nada."""
    partes = Path(caminho_gravado.replace("\\", "/")).parts
    if (len(partes) != 3 or partes[0] != "uploads" or partes[1] != plataforma
            or not _NOME_GRAVADO_PELO_SERVIDOR.fullmatch(partes[2])):
        return None
    base = settings.UPLOADS_DIR.resolve()
    alvo = base.joinpath(*partes[1:]).resolve()
    return alvo if alvo.is_relative_to(base) and alvo.parent != base else None


def _apontado_por_outra_escola(db: Session, escola_id: int, canonico: str) -> bool:
    """O servidor grava um arquivo por importação; um caminho que OUTRA escola
    também registra pode ser dela (o texto desta linha pode ter vindo do cliente
    apontando para lá) — e o inverso também é possível, porque o /confirmar não
    marca qual linha ele gravou. Sem como provar a posse, o arquivo não é tocado
    (pergunta ao dono: marcar no /confirmar o caminho gerado pelo servidor).
    Comparação pelo caminho RESOLVIDO e sem caixa: grafias diferentes do mesmo
    arquivo (barra invertida, maiúsculas num disco que não as distingue) contam."""
    from sqlalchemy import func

    from app.models import Importacao

    return db.execute(
        select(Importacao.id).where(
            Importacao.escola_id != escola_id,
            func.lower(func.replace(Importacao.arquivo_original, "\\", "/"))
            == canonico.lower())
        .limit(1)).first() is not None


def _traz_dado_de_quem_fica(db: Session, importacao_id: int, ids: set[int]) -> bool:
    """Snapshot ou evento de criança que CONTINUA veio desta importação: o
    arquivo é a prova (§15) do dado de mais alguém, não só o relatório dela."""
    from app.models import EventoAluno, SnapshotElefante, SnapshotMatific

    return any(
        db.execute(select(modelo.id).where(modelo.importacao_id == importacao_id,
                                           modelo.aluno_id.not_in(list(ids)))
                   .limit(1)).first() is not None
        for modelo in (SnapshotElefante, SnapshotMatific, EventoAluno))


def _esquecer_originais_individuais(
        db: Session, escola_id: int, alvos: NomesAlvo, ids: set[int],
) -> tuple[int, list[Path], list[tuple[Path, Path]]]:
    """(linhas redigidas, arquivos a apagar, arquivos a renomear) — os dois
    últimos só no commit. Por arquivo (várias linhas da escola podem apontar o
    mesmo), o nome da criança sai do texto da linha e do disco:

    * só dela → o arquivo é apagado e a linha fica ``[removido]``;
    * com dado de quem fica → o arquivo é RENOMEADO para um nome neutro
      (``AAAAMMDD_HHMMSS_importacao-<id>``) e a linha aponta o novo nome: a prova
      da importação continua ligada a ela, sem o nome da excluída;
    * apontado também por outra escola → o arquivo não é tocado e a linha
      desta escola fica ``[removido]`` (ver ``_apontado_por_outra_escola``)."""
    from app.models import Importacao

    base = settings.UPLOADS_DIR.resolve()
    redigidas = 0
    por_arquivo: dict[str, tuple[Path, list]] = {}
    for imp in db.execute(select(Importacao)
                          .where(Importacao.escola_id == escola_id)).scalars().all():
        gravado = imp.arquivo_original or ""
        if not gravado or not alvos.cita(Path(gravado.replace("\\", "/")).name):
            continue
        # O texto DESTA linha cita a excluída (e não quem fica): sai em todo caso;
        # só a renomeação abaixo troca o ``[removido]`` pelo nome neutro.
        imp.arquivo_original = MARCA_REMOVIDO
        redigidas += 1
        real = _arquivo_de_upload(gravado, imp.plataforma)
        if real is not None:
            canonico = "uploads/" + real.relative_to(base).as_posix()
            por_arquivo.setdefault(canonico.lower(), (real, []))[1].append(imp)

    apagar: list[Path] = []
    renomear: list[tuple[Path, Path]] = []
    for canonico, (real, imps) in por_arquivo.items():
        if _apontado_por_outra_escola(db, escola_id, canonico):
            continue
        if not any(_traz_dado_de_quem_fica(db, imp.id, ids) for imp in imps):
            apagar.append(real)
            continue
        neutro = real.with_name(
            f"{real.name[:15]}_importacao-{min(imp.id for imp in imps)}{real.suffix}")
        if real.is_file() and not neutro.exists():
            ponteiro = "uploads/" + neutro.relative_to(base).as_posix()
            for imp in imps:
                imp.arquivo_original = ponteiro
            renomear.append((real, neutro))
    return redigidas, apagar, renomear


def _copias_em_exports() -> list[Path]:
    pasta = settings.EXPORTS_DIR
    try:
        if not pasta.exists():
            return []
        return [a for a in pasta.iterdir() if a.is_file() and not a.name.startswith(".")]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Arquivos: só depois do commit
# ---------------------------------------------------------------------------

def _apagar_arquivos(caminhos: list[Path]) -> int:
    apagados = 0
    falhas: dict[str, int] = {}
    for caminho in caminhos:
        try:
            if caminho.is_file():
                caminho.unlink()
                apagados += 1
        except OSError:
            falhas[caminho.parent.name] = falhas.get(caminho.parent.name, 0) + 1
    if falhas:
        # NUNCA o nome do arquivo: o original foi escolhido justamente por trazer o
        # nome da criança que pediu esquecimento, e o log da aplicação (Railway,
        # Sentry) não é expurgado. Só a contagem por pasta (plataforma/exports).
        logger.warning("Exclusão de aluno: %d arquivo(s) não apagado(s) por pasta: %s",
                       sum(falhas.values()), dict(sorted(falhas.items())))
    return apagados


def _renomear_arquivos(pares: list[tuple[Path, Path]]) -> int:
    """Nunca sobrescreve: destino que já existe conta como falha (o ponteiro já
    gravado aponta o nome neutro, e o arquivo que lá estiver não é o desta
    importação). Falha só vai para o log em contagem por pasta, como em
    ``_apagar_arquivos`` (o nome de origem traz o nome da criança)."""
    feitos = 0
    falhas: dict[str, int] = {}
    for origem, destino in pares:
        try:
            if origem.is_file() and not destino.exists():
                origem.rename(destino)
                feitos += 1
                continue
        except OSError:
            pass
        falhas[origem.parent.name] = falhas.get(origem.parent.name, 0) + 1
    if falhas:
        logger.warning("Exclusão de aluno: %d arquivo(s) não renomeado(s) por pasta: %s",
                       sum(falhas.values()), dict(sorted(falhas.items())))
    return feitos


def _ao_commitar(sessao: Session) -> None:
    # O after_commit também dispara no RELEASE de savepoint: só o commit da
    # transação RAIZ mexe no disco, e só no que foi pedido NELA (de raiz
    # revertida, os pedidos ficam para trás e são descartados aqui).
    if sessao.in_nested_transaction():
        return
    raiz = sessao.get_transaction()
    pendentes = sessao.info.get(_PENDENTES) or []
    sessao.info[_PENDENTES] = []
    _renomear_arquivos([par for dona, _, pares in pendentes if dona is raiz
                        for par in pares])
    _apagar_arquivos([c for dona, lista, _ in pendentes if dona is raiz for c in lista])


def apagar_arquivos_apos_commit(db: Session, caminhos: list[Path],
                                renomear: list[tuple[Path, Path]] | None = None) -> None:
    """Apaga ``caminhos`` e renomeia ``renomear`` (origem → destino) só no commit
    da transação aberta agora; se ela reverter, o disco fica como estava — e os
    ponteiros revertidos continuam certos."""
    if not caminhos and not renomear:
        return
    raiz = db.get_transaction()
    if raiz is None:            # sem transação aberta: nada a esperar
        _renomear_arquivos(list(renomear or []))
        _apagar_arquivos(caminhos)
        return
    if not db.info.get(_OUVINTE):
        event.listen(db, "after_commit", _ao_commitar)
        db.info[_OUVINTE] = True
    db.info.setdefault(_PENDENTES, []).append((raiz, list(caminhos), list(renomear or [])))


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def nomes_absorvidos_que_contam(absorvidas: dict[int, set[str]] | None,
                                vivos) -> list[str]:
    """Os nomes das fichas absorvidas (``fichas_absorvidas``) que entram como nome
    da criança excluída: só os que NÃO são também o nome — ou parte do nome — de
    uma criança que continua na escola (``vivos``). O nome do stub é muitas vezes
    abreviado ("ANA SOUZA") e, contido no nome de quem fica ("Ana Souza Lima"), não
    prova ser dela. A mesma regra do log (``_anonimizar_logs_do_aluno``)."""
    nomes = {n for ns in (absorvidas or {}).values() for n in ns if n and _palavras(n)}
    if not nomes:
        return []
    vivas = [s.split() for s in {_chave(v) for v in vivos if v and _palavras(v)}]
    return sorted(n for n in nomes
                  if not any(_ocorrencias([_chave(n).split()], viva) for viva in vivas))


def esquecer_fora_do_cadastro(db: Session, escola_id: int, nomes: dict[int, str],
                              identidades: set[tuple[str, str]],
                              absorvidas: dict[int, set[str]] | None = None
                              ) -> dict[str, int]:
    """Fecha as lacunas listadas no cabeçalho para as crianças ``nomes``
    ({aluno_id: nome}) de ``escola_id``. ``identidades`` = {(plataforma,
    id_externo)} delas, lidas ANTES de apagar ``identidades_externas``. Chamar
    ANTES do DELETE em ``alunos`` (a revisão resolvida para ela ainda aponta o id).
    Não commita; os arquivos somem no commit. Devolve as contagens (sem nome).

    ``absorvidas`` ({id: {nomes}}, de ``fichas_absorvidas``, lidas ANTES de
    anonimizar o log, que é de onde vêm os nomes): as fichas que elas absorveram
    por fusão são ELAS. Os ids delas contam nas revisões (a candidata que é a
    ficha absorvida sai da lista) e os nomes delas são procurados como os delas
    (``nomes_absorvidos_que_contam``)."""
    from app.models import Aluno

    ids = set(nomes)
    # Quem CONTINUA na escola (qualquer status: arquivado/transferido seguem no
    # cadastro) — uma vez só, valendo para revisões, mensagens e originais. Os
    # ids também: a candidata de revisão só é "de quem fica" se a ficha existe.
    vivos = dict(db.execute(select(Aluno.id, Aluno.nome).where(
        Aluno.escola_id == escola_id, Aluno.id.not_in(list(ids)))).all())
    alvos = NomesAlvo([*nomes.values(),
                       *nomes_absorvidos_que_contam(absorvidas, vivos.values())],
                      preservar=vivos.values())
    ids |= set(absorvidas or {})
    contagens = _esquecer_revisoes(db, escola_id, ids, set(vivos), alvos, identidades)
    contagens["mensagens_sync_redigidas"] = (
        _redigir_mensagens_de_sync(db, escola_id, alvos) if alvos else 0)
    redigidas, originais, renomear = (
        _esquecer_originais_individuais(db, escola_id, alvos, ids)
        if alvos else (0, [], []))
    contagens["importacoes_redigidas"] = redigidas
    copias = _copias_em_exports()
    contagens["arquivos_a_apagar"] = len(originais) + len(copias)
    if renomear:
        contagens["arquivos_a_renomear"] = len(renomear)
    apagar_arquivos_apos_commit(db, originais + copias, renomear)
    db.flush()   # as revisões saem ANTES do DELETE em alunos (que vem em Core)
    return contagens


def fichas_absorvidas(db: Session, escola_id: int, aluno_ids) -> dict[int, set[str]]:
    """As fichas que ``aluno_ids`` absorveram por FUSÃO — direta ou em cadeia —,
    com os nomes que elas tinham: ``{id da absorvida: {nomes}}``.

    É a MESMA criança. As entradas antigas dessas fichas no log (o
    ``aluno.criado_auto`` do stub da importação, a fusão em que elas absorveram
    outra) ficam com o id DELAS, e a foto pré-fusão da absorvida (nascimento,
    observações, foto) fica na entrada da fusão. Sem isto, o esquecimento não as
    alcança. A fonte é o próprio log ``aluno.fundido`` da escola
    (``mantido.id`` ← ``removido.id``): a ficha absorvida já não existe.

    Id que hoje é de uma ficha VIVA fica de fora: a absorvida foi apagada, então o
    id em uso é de outra criança (reaproveitamento de id)."""
    from app.models import Aluno, LogAuditoria

    filhos: dict[int, list[tuple[int, set[str]]]] = {}
    for entidade_id, detalhes in db.execute(
        select(LogAuditoria.entidade_id, LogAuditoria.detalhes).where(
            LogAuditoria.escola_id == escola_id, LogAuditoria.acao == "aluno.fundido")
        .execution_options(yield_per=500)
    ):
        detalhes = detalhes if isinstance(detalhes, dict) else {}
        mantido = (detalhes.get("mantido") or {}).get("id", entidade_id)
        removido = detalhes.get("removido") or {}
        foto = detalhes.get("foto_pre_fusao") or {}
        if not isinstance(mantido, int) or not isinstance(removido.get("id"), int):
            continue
        nomes = {n for n in (removido.get("nome"), foto.get("nome"))
                 if isinstance(n, str) and n.strip() and n != MARCA_REMOVIDO}
        filhos.setdefault(mantido, []).append((removido["id"], nomes))

    removidos = {filho for lista in filhos.values() for filho, _ in lista}
    # Nem entra nem é percorrida: as fusões gravadas com esse id podem ser da
    # criança viva que o reaproveitou.
    vivas = set(db.execute(select(Aluno.id).where(
        Aluno.id.in_(list(removidos)))).scalars()) if removidos else set()
    alvos = set(aluno_ids)
    achadas: dict[int, set[str]] = {}
    pilha = list(alvos)
    while pilha:
        for filho, nomes in filhos.get(pilha.pop(), ()):
            if filho in alvos or filho in vivas:
                continue
            if filho not in achadas:
                pilha.append(filho)
            achadas.setdefault(filho, set()).update(nomes)
    return achadas


def conversas_ia_que_citam(db: Session, escola_id: int, nomes: dict[int, str],
                           absorvidas: dict[int, set[str]] | None = None) -> set[int]:
    """Ids das conversas da IA de ``escola_id`` que citam alguma das crianças
    ``nomes`` ({aluno_id: nome}) — o direito ao esquecimento APAGA a conversa.
    Também pelo nome das fichas que elas absorveram por fusão (``absorvidas``, de
    ``fichas_absorvidas``): enquanto o stub existia, o assistente o citava por ele.
    Esse nome só conta quando não é também o nome — ou parte do nome — de quem
    fica (``nomes_absorvidos_que_contam``; nele, nem o homônimo exato apaga).

    Antes era ``conteudo ILIKE %nome%``: excluir "Joao Pedro Silva" apagava a
    conversa sobre "Joao Pedro Silva Testelli", que continua na escola, e "Ana"
    apagava a de "Mariana". Agora o ILIKE só pré-seleciona e quem decide é o
    casador do módulo: palavra inteira (também para nome de uma palavra só) e
    sem contar o trecho que está dentro do nome MAIOR de quem fica.

    Diferente das revisões e mensagens, o homônimo vivo EXATO não salva a
    conversa: ela é do usuário, não da outra criança, e com o mesmo nome não há
    como dizer de qual das duas fala — entre apagar a conversa a mais (que a
    retenção de 90 dias já apagaria) e guardar o nome de quem pediu
    esquecimento, apaga-se (como já era)."""
    from app.models import Aluno, ConversaIA, MensagemIA

    ids = set(nomes)
    vivos = [n for n in db.execute(select(Aluno.nome).where(
        Aluno.escola_id == escola_id, Aluno.id.not_in(list(ids)))).scalars() if n]
    procurados = [*nomes.values(), *nomes_absorvidos_que_contam(absorvidas, vivos)]
    chaves = {_chave(n) for n in procurados if n and _palavras(n)}
    maiores_vivos = [n for n in vivos if _chave(n) not in chaves]
    alvos = NomesAlvo(procurados, preservar=maiores_vivos, palavra_unica=True)
    achadas: set[int] = set()
    for nome in sorted({n.strip() for n in procurados if n and n.strip()}):
        for conversa_id, conteudo in db.execute(
                select(MensagemIA.conversa_id, MensagemIA.conteudo)
                .join(ConversaIA, ConversaIA.id == MensagemIA.conversa_id)
                .where(ConversaIA.escola_id == escola_id,
                       MensagemIA.conteudo.icontains(nome, autoescape=True))
                .execution_options(yield_per=500)):
            if conversa_id not in achadas and alvos.cita(conteudo):
                achadas.add(conversa_id)
    return achadas


# ---------------------------------------------------------------------------
# Marca de esquecimento das contas da plataforma
# ---------------------------------------------------------------------------

# A entrada do log que leva as marcas (uma por criança excluída de vez: preservada do
# expurgo, ``audit.ACOES_PRESERVADAS``) e a chave delas em ``detalhes``.
ACAO_EXCLUSAO_PERMANENTE = "aluno.excluido_permanente"
CHAVE_CONTAS_ESQUECIDAS = "contas_esquecidas"
# Separação de domínio: a chave do servidor gera, para este uso, uma chave HMAC só
# dele (a marca de uma conta não serve para mais nada, nem para o código do Quest).
_DOMINIO_MARCA = "constela-conta-esquecida"


def marca_da_conta(plataforma: str, id_externo: str, *, segredo: str | None = None) -> str:
    """HMAC-SHA256 (hex, 64) da conta — plataforma + id externo — com a chave do
    servidor: o que fica gravado no lugar do id. ``segredo`` só para conferir com
    outra chave do anel (``marcas_da_conta``)."""
    segredo = segredo if segredo is not None else segredos_da_cifra()[0]
    chave = hashlib.sha256(f"{segredo}|{_DOMINIO_MARCA}".encode()).digest()
    conta = f"{plataforma}\x1f{str(id_externo).strip()}"
    return hmac.new(chave, conta.encode("utf-8"), hashlib.sha256).hexdigest()


def marcas_da_conta(plataforma: str, id_externo: str) -> list[str]:
    """A marca da conta em CADA chave do anel (``segredos_da_cifra``: a atual grava,
    todas conferem). A marca gravada antes de uma troca de chave continua
    reconhecida enquanto a chave antiga estiver no anel — tirá-la do anel apaga a
    memória dessas contas, e o id em claro não existe mais para regravar
    (docs/lgpd/RETENCAO-TECNICA.md, seção 3)."""
    return [marca_da_conta(plataforma, id_externo, segredo=s) for s in segredos_da_cifra()]


# Motivos de pendência em que o motor achou a ficha como a ÚNICA correspondência
# segura e só não associou por uma trava: a ficha já tem outra conta nesta
# plataforma, a ficha está inativa, ou quem confirmou a importação pediu a revisão.
# A conta da pendência é da criança dessa ficha. Os demais motivos sem ficha
# escolhida são dúvida de identidade ("homonimo_em_outra_sala",
# "nome_casa_em_outra_sala", "candidatos_multiplos", "correspondencia_insegura",
# "criacao_bloqueada_por_politica", "contas_repetidas_no_relatorio", "sem_turma"…):
# a conta pode ser de OUTRA criança, de mesmo nome e ainda sem ficha — e a marca a
# tiraria das coletas da escola para sempre (não há ação para levantá-la).
_MOTIVOS_DA_PROPRIA_FICHA = frozenset({
    "outra_identidade_na_plataforma", "ficha_inativa", "deixada_para_revisao",
})


def _donas_pela_pendencia(rev, ids: set[int], vivos: set[int]) -> set[int]:
    """Das crianças ``ids``, de quem a conta da pendência SEM ficha escolhida
    provadamente é: só com motivo de ``_MOTIVOS_DA_PROPRIA_FICHA``, o id dela entre
    os candidatos e nenhuma ficha que continua na escola (``vivos``) entre eles.
    Vazio quando a pendência não prova de quem é a conta."""
    if rev.aluno_escolhido_id is not None or rev.motivo not in _MOTIVOS_DA_PROPRIA_FICHA:
        return set()
    candidatos = {c.get("aluno_id") for c in (rev.candidatos or []) if isinstance(c, dict)}
    return set() if candidatos & vivos else candidatos & ids


def contas_da_crianca(db: Session, escola_id: int,
                      nomes: dict[int, str]) -> dict[int, set[tuple[str, str]]]:
    """As contas da plataforma (plataforma, id externo) de cada criança ``nomes``
    ({aluno_id: nome}) de ``escola_id``: as vinculadas à ficha (qualquer situação,
    inclusive a aposentada e as que ela absorveu por fusão) e, das revisões dela
    (``_revisao_dela``), só as que PROVAM ser dela: a resolvida para ela e a
    pendência que aponta só para a ficha dela (``_donas_pela_pendencia``) — por
    exemplo a segunda conta que a coleta mandou para a fila
    ("outra_identidade_na_plataforma"). Ler ANTES de apagar identidades e revisões.

    A pendência que só tem o nome dela não basta: a de OUTRA criança, homônima e
    ainda sem ficha ("homonimo_em_outra_sala"), também tem. Ela é apagada (guarda o
    nome), mas a conta não é marcada e a coleta seguinte a trata como conta nova.

    Conta vinculada a uma ficha que CONTINUA na escola nunca entra: é de outra
    criança, e marcá-la a apagaria das coletas (a revisão resolvida para a excluída
    pode citar a conta que depois foi parar em outra ficha)."""
    from app.models import Aluno, IdentidadeExterna, RevisaoIdentidade

    ids = set(nomes)
    por_aluno: dict[int, set[tuple[str, str]]] = {aid: set() for aid in ids}
    if not ids:
        return por_aluno
    vinculadas: dict[tuple[str, str], int] = {}
    for plataforma, id_externo, aluno_id in db.execute(
            select(IdentidadeExterna.plataforma, IdentidadeExterna.id_externo,
                   IdentidadeExterna.aluno_id)
            .where(IdentidadeExterna.aluno_id.in_(list(ids)))):
        vinculadas[(plataforma, id_externo)] = aluno_id
    vivos = dict(db.execute(select(Aluno.id, Aluno.nome).where(
        Aluno.escola_id == escola_id, Aluno.id.not_in(list(ids)))).all())
    alvos = NomesAlvo(nomes.values(), preservar=vivos.values())
    contas: dict[tuple[str, str], set[int]] = {
        conta: {aid} for conta, aid in vinculadas.items()}
    identidades = set(vinculadas)
    for rev in db.execute(select(RevisaoIdentidade).where(
            RevisaoIdentidade.escola_id == escola_id,
            RevisaoIdentidade.id_externo.is_not(None))).scalars():
        if not (rev.id_externo or "").strip() or not _revisao_dela(
                rev, ids, identidades, alvos):
            continue
        conta = (rev.plataforma, rev.id_externo)
        if rev.aluno_escolhido_id in ids:
            donas = {rev.aluno_escolhido_id}
        elif conta in vinculadas:
            donas = {vinculadas[conta]}
        else:   # sem ficha escolhida: o nome não basta (``_donas_pela_pendencia``)
            donas = _donas_pela_pendencia(rev, ids, set(vivos))
        if donas:
            contas.setdefault(conta, set()).update(donas)
    de_quem_fica = {(plataforma, id_externo) for plataforma, id_externo in db.execute(
        select(IdentidadeExterna.plataforma, IdentidadeExterna.id_externo).where(
            IdentidadeExterna.escola_id == escola_id,
            IdentidadeExterna.aluno_id.not_in(list(ids))))} if contas else set()
    for (plataforma, id_externo), donas in contas.items():
        if not plataforma or (plataforma, id_externo) in de_quem_fica:
            continue
        for aid in donas:
            por_aluno[aid].add((plataforma, str(id_externo).strip()))
    return por_aluno


def marcas_para_o_log(contas: set[tuple[str, str]]) -> list[dict[str, str]]:
    """``[{"plataforma", "marca"}]`` para ``detalhes`` do ``aluno.excluido_permanente``
    — o id externo NÃO vai em claro. Ordem estável."""
    return sorted(({"plataforma": plataforma, "marca": marca_da_conta(plataforma, id_externo)}
                   for plataforma, id_externo in contas if plataforma and id_externo),
                  key=lambda m: (m["plataforma"], m["marca"]))


def marcas_esquecidas(db: Session, escola_id: int) -> set[tuple[str, str]]:
    """{(plataforma, marca)} das contas esquecidas de ``escola_id`` — lidas das
    entradas ``aluno.excluido_permanente`` da escola (poucas: a ação é rara e o
    índice é por ação)."""
    from app.models import LogAuditoria

    marcas: set[tuple[str, str]] = set()
    for detalhes in db.execute(select(LogAuditoria.detalhes).where(
            LogAuditoria.acao == ACAO_EXCLUSAO_PERMANENTE,
            LogAuditoria.escola_id == escola_id)).scalars():
        itens = detalhes.get(CHAVE_CONTAS_ESQUECIDAS) if isinstance(detalhes, dict) else None
        for item in itens if isinstance(itens, list) else ():
            if (isinstance(item, dict) and isinstance(item.get("plataforma"), str)
                    and isinstance(item.get("marca"), str)):
                marcas.add((item["plataforma"], item["marca"]))
    return marcas


def conta_esquecida(marcas: set[tuple[str, str]], plataforma: str, id_externo: str) -> bool:
    """A conta é de uma criança excluída de vez nesta escola (``marcas`` de
    ``marcas_esquecidas``)?"""
    if not (marcas and plataforma and str(id_externo or "").strip()):
        return False
    return any((plataforma, marca) in marcas for marca in marcas_da_conta(plataforma, id_externo))
