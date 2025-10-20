from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKey, BigInteger, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from .engine import Base


class Person(Base):
	__tablename__ = 'people'
	__table_args__ = (
		UniqueConstraint('telegram_username', name='uq_people_telegram_username'),
	)

	id = Column(Integer, primary_key=True, index=True)
	full_name = Column(String(255), nullable=False)
	course = Column(String(128), nullable=True)
	faculty = Column(String(255), nullable=True)
	telegram_username = Column(String(64), nullable=True)

	# Связь к одному пользователю бота (если пользователь связал свою учётку)
	bot_user = relationship('BotUser', back_populates='person', uselist=False)

	def __repr__(self) -> str:  # pragma: no cover - simple repr
		return f"<Person(id={self.id!r}, full_name={self.full_name!r}, telegram={self.telegram_username!r})>"


class BotUser(Base):
	__tablename__ = 'bot_users'
	__table_args__ = (
		UniqueConstraint('tg_id', name='uq_bot_users_tg_id'),
		UniqueConstraint('telegram_username', name='uq_bot_users_telegram_username'),
	)

	id = Column(Integer, primary_key=True, index=True)
	tg_id = Column(BigInteger, nullable=False)
	telegram_username = Column(String(64), nullable=True)
	# связь на таблицу Person — один BotUser связан максимум с одной записью Person
	person_id = Column(Integer, ForeignKey('people.id'), nullable=True, unique=True)

	person = relationship('Person', back_populates='bot_user')

	def __repr__(self) -> str:  # pragma: no cover - simple repr
		return f"<BotUser(id={self.id!r}, tg_id={self.tg_id!r}, telegram={self.telegram_username!r}, person_id={self.person_id!r})>"


class CO(Base):
	"""Campaign / рассылка (CO) - хранит параметры рассылки, текст и метаданные."""
	__tablename__ = 'co_campaigns'

	id = Column(Integer, primary_key=True, index=True)
	admin_id = Column(BigInteger, nullable=False)
	faculty = Column(String(255), nullable=False)
	is_presence = Column(Boolean, default=False)
	text = Column(String, nullable=False)
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	responses = relationship('COResponse', back_populates='campaign')


class COResponse(Base):
	"""Ответ пользователя на кампанию (да/нет)."""
	__tablename__ = 'co_responses'

	id = Column(Integer, primary_key=True, index=True)
	campaign_id = Column(Integer, ForeignKey('co_campaigns.id'), nullable=False)
	bot_user_id = Column(Integer, ForeignKey('bot_users.id'), nullable=False)
	answer = Column(String(16), nullable=False)  # 'yes' / 'no'
	responded_at = Column(DateTime(timezone=True), server_default=func.now())

	campaign = relationship('CO', back_populates='responses')
	bot_user = relationship('BotUser')

