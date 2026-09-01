"""Proveniencia DataJud e catalogo de fontes externas.

Revision ID: 20260901_0004
Revises: 20260826_0003
"""
from alembic import op

from bpc_ingestion.models import ColetaRegistroDatajud, RecursoExterno


revision = "20260901_0004"
down_revision = "20260826_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ColetaRegistroDatajud.__table__.create(bind=bind, checkfirst=True)
    RecursoExterno.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    RecursoExterno.__table__.drop(bind=bind, checkfirst=True)
    ColetaRegistroDatajud.__table__.drop(bind=bind, checkfirst=True)
