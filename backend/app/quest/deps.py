"""Dependências de sessão do ALUNO (papel "aluno" no JWT).

Espelha app/core/deps.py, mas para o outro lado da fronteira: um token de
aluno só funciona aqui, e um token do Edu (sem papel) é rejeitado aqui —
os dois mundos nunca se cruzam.
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import oauth2_scheme
from app.core.security import decodificar_token
from app.models import Aluno
from app.quest.models import QuestCredencialAluno, QuestPerfil
from sqlalchemy import select


@dataclass
class ContextoAluno:
    credencial: QuestCredencialAluno
    perfil: QuestPerfil
    aluno: Aluno

    @property
    def escola_id(self) -> int:
        return self.credencial.escola_id


def get_aluno_atual(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> ContextoAluno:
    payload = decodificar_token(token)
    if payload is None or payload.get("papel") != "aluno":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Sessão inválida ou expirada.")
    credencial = db.get(QuestCredencialAluno, int(payload["sub"]))
    if credencial is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Sessão inválida ou expirada.")
    # Cartão regenerado → sessões antigas caem (mesma mecânica do Edu)
    if int(payload.get("ver", 0)) != int(credencial.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Sessão expirada. Peça um cartão novo!")
    aluno = db.get(Aluno, credencial.aluno_id)
    if aluno is None or aluno.status != "ativo":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Cadastro do aluno inativo.")
    perfil = db.execute(
        select(QuestPerfil).where(QuestPerfil.aluno_id == aluno.id)
    ).scalar_one_or_none()
    if perfil is None or perfil.status != "ativo":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Perfil do Quest indisponível.")
    return ContextoAluno(credencial=credencial, perfil=perfil, aluno=aluno)
