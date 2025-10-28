"""create reserv table

Revision ID: 001
Revises: 
Create Date: 2025-10-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаём таблицу reserv
    op.create_table('reserv',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('course', sa.String(length=128), nullable=True),
        sa.Column('faculty', sa.String(length=255), nullable=True),
        sa.Column('telegram_username', sa.String(length=64), nullable=True),
        sa.Column('message_sent', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_username', name='uq_reserv_telegram_username')
    )
    op.create_index(op.f('ix_reserv_id'), 'reserv', ['id'], unique=False)


def downgrade() -> None:
    # Удаляем таблицу reserv
    op.drop_index(op.f('ix_reserv_id'), table_name='reserv')
    op.drop_table('reserv')

