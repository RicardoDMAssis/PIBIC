"""Indicadores mensais agregados de BPC por município.

Revision ID: 20260922_0005
Revises: 20260901_0004
"""
from alembic import op

from bpc_ingestion.models import IndicadorBpcMunicipio


revision = "20260922_0005"
down_revision = "20260901_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    IndicadorBpcMunicipio.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    IndicadorBpcMunicipio.__table__.drop(bind=op.get_bind(), checkfirst=True)
