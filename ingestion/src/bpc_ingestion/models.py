from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger as SqlBigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB as PgJSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Mesmo schema logico nos dois bancos; Integer permite autoincremento no SQLite.
BigInteger = SqlBigInteger().with_variant(Integer(), "sqlite")
JSONB = JSON().with_variant(PgJSONB(), "postgresql")
UUID = Uuid


class Base(DeclarativeBase):
    pass


class Coleta(Base):
    __tablename__ = "coletas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    fonte: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    particao: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="executando")
    parametros: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    registros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    arquivo_bruto: Mapped[str | None] = mapped_column(Text)
    erro: Mapped[str | None] = mapped_column(Text)
    iniciado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TarefaPainel(Base):
    __tablename__ = "tarefas_painel"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    parametros: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    comando: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    log: Mapped[str] = mapped_column(Text, nullable=False, default="")
    codigo_saida: Mapped[int | None] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    iniciado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Processo(Base):
    __tablename__ = "processos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    numero_processo: Mapped[str] = mapped_column(String(25), unique=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RegistroDatajud(Base):
    __tablename__ = "registros_datajud"
    __table_args__ = (
        UniqueConstraint("datajud_index", "datajud_id", name="uq_datajud_index_id"),
        Index("ix_registros_datajud_tribunal_grau", "tribunal", "grau"),
        Index("ix_registros_datajud_ajuizamento", "data_ajuizamento"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    processo_id: Mapped[int] = mapped_column(
        ForeignKey("processos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    datajud_index: Mapped[str] = mapped_column(String(120), nullable=False)
    datajud_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tribunal: Mapped[str | None] = mapped_column(String(20), index=True)
    grau: Mapped[str | None] = mapped_column(String(30), index=True)
    classe_codigo: Mapped[int | None] = mapped_column(BigInteger, index=True)
    classe_nome: Mapped[str | None] = mapped_column(Text)
    orgao_codigo: Mapped[int | None] = mapped_column(BigInteger, index=True)
    orgao_nome: Mapped[str | None] = mapped_column(Text)
    nivel_sigilo: Mapped[int | None] = mapped_column(Integer)
    data_ajuizamento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_ultima_atualizacao: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_sort: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    coletado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ColetaRegistroDatajud(Base):
    __tablename__ = "coleta_registros_datajud"

    coleta_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coletas.id", ondelete="CASCADE"), primary_key=True
    )
    registro_id: Mapped[int] = mapped_column(
        ForeignKey("registros_datajud.id", ondelete="CASCADE"), primary_key=True
    )
    observado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RecursoExterno(Base):
    __tablename__ = "recursos_externos"
    __table_args__ = (
        UniqueConstraint("fonte", "recurso_id", name="uq_recurso_externo_fonte_id"),
        Index("ix_recursos_externos_fonte_formato", "fonte", "formato"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fonte: Mapped[str] = mapped_column(String(30), nullable=False)
    conjunto_id: Mapped[str] = mapped_column(String(200), nullable=False)
    conjunto_nome: Mapped[str | None] = mapped_column(Text)
    recurso_id: Mapped[str] = mapped_column(String(500), nullable=False)
    nome: Mapped[str | None] = mapped_column(Text)
    formato: Mapped[str | None] = mapped_column(String(30), index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IndicadorBpcMunicipio(Base):
    __tablename__ = "indicadores_bpc_municipio"
    __table_args__ = (
        UniqueConstraint("fonte", "mes_ano", "codigo_ibge", "tipo_id", name="uq_indicador_bpc_municipio"),
        Index("ix_indicadores_bpc_municipio_local_periodo", "codigo_ibge", "mes_ano"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fonte: Mapped[str] = mapped_column(String(30), nullable=False)
    mes_ano: Mapped[int] = mapped_column(Integer, nullable=False)
    data_referencia: Mapped[date] = mapped_column(Date, nullable=False)
    codigo_ibge: Mapped[str] = mapped_column(String(7), nullable=False)
    municipio_nome: Mapped[str | None] = mapped_column(Text)
    uf: Mapped[str | None] = mapped_column(String(2))
    tipo_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quantidade_beneficiados: Mapped[int] = mapped_column(BigInteger, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    coleta_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coletas.id"), nullable=False)
    coletado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Assunto(Base):
    __tablename__ = "assuntos"

    codigo: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nome: Mapped[str | None] = mapped_column(Text)


class ReferenciaTpu(Base):
    __tablename__ = "referencias_tpu"

    tipo: Mapped[str] = mapped_column(String(20), primary_key=True)
    codigo: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_pai: Mapped[int | None] = mapped_column(BigInteger, index=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    segmentos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    fonte_arquivo: Mapped[str] = mapped_column(Text, nullable=False)
    importado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RegistroAssunto(Base):
    __tablename__ = "registro_assuntos"

    registro_id: Mapped[int] = mapped_column(
        ForeignKey("registros_datajud.id", ondelete="CASCADE"), primary_key=True
    )
    assunto_codigo: Mapped[int] = mapped_column(
        ForeignKey("assuntos.codigo"), primary_key=True, index=True
    )


class Movimento(Base):
    __tablename__ = "movimentos"
    __table_args__ = (UniqueConstraint("registro_id", "sequencia", name="uq_movimento_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    registro_id: Mapped[int] = mapped_column(
        ForeignKey("registros_datajud.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequencia: Mapped[int] = mapped_column(Integer, nullable=False)
    codigo: Mapped[int | None] = mapped_column(BigInteger, index=True)
    nome: Mapped[str | None] = mapped_column(Text)
    data_hora: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    complementos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class ConsultaPje(Base):
    __tablename__ = "consultas_pje"

    processo_id: Mapped[int] = mapped_column(
        ForeignKey("processos.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    http_status: Mapped[int | None] = mapped_column(Integer)
    quantidade: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    erro: Mapped[str | None] = mapped_column(Text)
    consultado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ComunicacaoPje(Base):
    __tablename__ = "comunicacoes_pje"
    __table_args__ = (
        UniqueConstraint("processo_id", "hash_conteudo", name="uq_comunicacao_hash"),
        Index("ix_comunicacoes_tipo_data", "tipo_comunicacao", "data_disponibilizacao"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    processo_id: Mapped[int] = mapped_column(
        ForeignKey("processos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    comunica_id: Mapped[str | None] = mapped_column(String(100), index=True)
    hash_conteudo: Mapped[str] = mapped_column(String(64), nullable=False)
    tribunal: Mapped[str | None] = mapped_column(String(30), index=True)
    tipo_comunicacao: Mapped[str | None] = mapped_column(String(100), index=True)
    tipo_documento: Mapped[str | None] = mapped_column(String(100), index=True)
    orgao_nome: Mapped[str | None] = mapped_column(Text)
    data_disponibilizacao: Mapped[date | None] = mapped_column(Date, index=True)
    texto: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    coletado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentoChunk(Base):
    __tablename__ = "documento_chunks"
    __table_args__ = (
        UniqueConstraint(
            "comunicacao_id", "numero_chunk", "modelo_embedding", "versao_pipeline",
            name="uq_chunk_modelo_versao",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    comunicacao_id: Mapped[int] = mapped_column(
        ForeignKey("comunicacoes_pje.id", ondelete="CASCADE"), nullable=False, index=True
    )
    processo_id: Mapped[int] = mapped_column(
        ForeignKey("processos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    numero_chunk: Mapped[int] = mapped_column(Integer, nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    quantidade_tokens: Mapped[int | None] = mapped_column(Integer)
    modelo_embedding: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    dimensao: Mapped[int] = mapped_column(Integer, nullable=False)
    versao_pipeline: Mapped[str] = mapped_column(String(50), nullable=False)
    hash_texto: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector().with_variant(JSON(), "sqlite"), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExtracaoIa(Base):
    __tablename__ = "extracoes_ia"
    __table_args__ = (
        UniqueConstraint(
            "processo_id", "tipo_extracao", "modelo", "versao_prompt",
            name="uq_extracao_modelo_prompt",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    processo_id: Mapped[int] = mapped_column(
        ForeignKey("processos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_extracao: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    modelo: Mapped[str] = mapped_column(String(100), nullable=False)
    versao_prompt: Mapped[str] = mapped_column(String(50), nullable=False)
    resultado: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confianca: Mapped[float | None] = mapped_column(Float)
    status_validacao: Mapped[str] = mapped_column(String(30), nullable=False, default="pendente")
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TentativaIa(Base):
    """Reserva e histórico operacional de chamadas de IA ainda não aceitas."""

    __tablename__ = "tentativas_ia"
    __table_args__ = (
        UniqueConstraint(
            "processo_id", "tipo_extracao", "modelo", "versao_prompt",
            name="uq_tentativa_ia_modelo_prompt",
        ),
        Index("ix_tentativas_ia_status_expira", "status", "expira_em"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    processo_id: Mapped[int] = mapped_column(
        ForeignKey("processos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_extracao: Mapped[str] = mapped_column(String(100), nullable=False)
    modelo: Mapped[str] = mapped_column(String(100), nullable=False)
    versao_prompt: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hash_entrada: Mapped[str | None] = mapped_column(String(64))
    erro: Mapped[str | None] = mapped_column(Text)
    diagnostico_arquivo: Mapped[str | None] = mapped_column(Text)
    expira_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
