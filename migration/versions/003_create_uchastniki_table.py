"""create uchastniki table

Revision ID: 003
Revises: 002
Create Date: 2025-11-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаём таблицу uchastniki
    op.create_table('uchastniki',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('course', sa.String(length=128), nullable=True),
        sa.Column('faculty', sa.String(length=255), nullable=True),
        sa.Column('telegram_username', sa.String(length=64), nullable=True),
        sa.Column('tg_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_username', name='uq_uchastniki_telegram_username')
    )
    op.create_index(op.f('ix_uchastniki_id'), 'uchastniki', ['id'], unique=False)


def downgrade() -> None:
    # Удаляем таблицу uchastniki
    op.drop_index(op.f('ix_uchastniki_id'), table_name='uchastniki')
    op.drop_table('uchastniki')

