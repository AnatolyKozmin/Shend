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
	f"""Campaign / рассылка (CO) - хранит параметры рассылки, текст и метаданные."""
	__tablename__ = 'co_campaigns'

	id = Column(Integer, primary_key=True, index=True)
	admin_id = Column(BigInteger, nullable=False)
	faculty = Column(String(255), nullable=False)
	is_presence = Column(Boolean, default=False)
	text = Column(String, nullable=False)
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	responses = relationship('COResponse', back_populates='campaign')


class COResponse(Base):
	f"""Ответ пользователя на кампанию (да/нет)."""
	__tablename__ = 'co_responses'

	id = Column(Integer, primary_key=True, index=True)
	campaign_id = Column(Integer, ForeignKey('co_campaigns.id'), nullable=False)
	bot_user_id = Column(Integer, ForeignKey('bot_users.id'), nullable=False)
	answer = Column(String(16), nullable=False)  # 'yes' / 'no'
	responded_at = Column(DateTime(timezone=True), server_default=func.now())

	campaign = relationship('CO', back_populates='responses')
	bot_user = relationship('BotUser')


class Reserv(Base):
	f"""Резервная таблица для рассылок - данные из res.xlsx."""
	__tablename__ = 'reserv'
	__table_args__ = (
		UniqueConstraint('telegram_username', name='uq_reserv_telegram_username'),
	)

	id = Column(Integer, primary_key=True, index=True)
	full_name = Column(String(255), nullable=False)
	course = Column(String(128), nullable=True)
	faculty = Column(String(255), nullable=True)
	telegram_username = Column(String(64), nullable=True)
	message_sent = Column(Boolean, default=False)  # флаг отправки сообщения
	last_answer = Column(String(16), nullable=True)  # последний ответ: 'yes' / 'no'
	answered_at = Column(DateTime(timezone=True), nullable=True)  # время ответа
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	def __repr__(self) -> str:  # pragma: no cover - simple repr
		return f"<Reserv(id={self.id!r}, full_name={self.full_name!r}, telegram={self.telegram_username!r})>"


class Interviewer(Base):
	f"""Собеседующие - те, кто проводит собеседования."""
	__tablename__ = 'interviewers'

	id = Column(Integer, primary_key=True, index=True)
	full_name = Column(String(255), nullable=False)
	telegram_id = Column(BigInteger, nullable=False, unique=True)
	telegram_username = Column(String(64), nullable=True)
	interviewer_sheet_id = Column(String(64), nullable=True)  # ID из Google Sheets (колонка C)
	access_code = Column(String(10), nullable=True)  # Код доступа из Google Sheets (колонка B)
	faculties = Column(String(500), nullable=True)  # Список факультетов через запятую
	is_active = Column(Boolean, default=True)
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	# Связи
	time_slots = relationship('TimeSlot', back_populates='interviewer')
	interviews = relationship('Interview', back_populates='interviewer')

	def __repr__(self) -> str:
		return f"<Interviewer(id={self.id!r}, full_name={self.full_name!r}, tg_id={self.telegram_id!r})>"


class TimeSlot(Base):
	f"""Временные слоты для собеседований."""
	__tablename__ = 'time_slots'

	id = Column(Integer, primary_key=True, index=True)
	interviewer_id = Column(Integer, ForeignKey('interviewers.id'), nullable=False)
	date = Column(String(10), nullable=False)  # Формат: YYYY-MM-DD
	time_start = Column(String(5), nullable=False)  # Формат: HH:MM
	time_end = Column(String(5), nullable=False)  # Формат: HH:MM
	is_available = Column(Boolean, default=True)
	google_sheet_sync = Column(DateTime(timezone=True), nullable=True)  # Последняя синхронизация
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	# Связи
	interviewer = relationship('Interviewer', back_populates='time_slots')
	interview = relationship('Interview', back_populates='time_slot', uselist=False)

	def __repr__(self) -> str:
		return f"<TimeSlot(id={self.id!r}, date={self.date!r}, time={self.time_start}-{self.time_end}, available={self.is_available!r})>"


class Interview(Base):
	f"""Записи на собеседования."""
	__tablename__ = 'interviews'

	id = Column(Integer, primary_key=True, index=True)
	time_slot_id = Column(Integer, ForeignKey('time_slots.id'), nullable=False, unique=True)
	interviewer_id = Column(Integer, ForeignKey('interviewers.id'), nullable=False)
	bot_user_id = Column(Integer, ForeignKey('bot_users.id'), nullable=False)
	person_id = Column(Integer, ForeignKey('people.id'), nullable=True)
	faculty = Column(String(255), nullable=True)
	status = Column(String(20), default='pending')  # pending/confirmed/cancelled
	cancellation_allowed = Column(Boolean, default=True)  # Можно ли отменить
	cancelled_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(String(1000), nullable=True)
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	# Связи
	time_slot = relationship('TimeSlot', back_populates='interview')
	interviewer = relationship('Interviewer', back_populates='interviews')
	bot_user = relationship('BotUser')
	person = relationship('Person')
	messages = relationship('InterviewMessage', back_populates='interview')

	def __repr__(self) -> str:
		return f"<Interview(id={self.id!r}, status={self.status!r})>"


class InterviewMessage(Base):
	f"""Сообщения между студентом и собеседующим."""
	__tablename__ = 'interview_messages'

	id = Column(Integer, primary_key=True, index=True)
	interview_id = Column(Integer, ForeignKey('interviews.id'), nullable=False)
	from_user_id = Column(BigInteger, nullable=False)  # tg_id отправителя
	to_user_id = Column(BigInteger, nullable=False)  # tg_id получателя
	message_text = Column(String(4000), nullable=False)
	message_id = Column(BigInteger, nullable=True)  # ID сообщения в Telegram
	is_read = Column(Boolean, default=False)
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	# Связи
	interview = relationship('Interview', back_populates='messages')

	def __repr__(self) -> str:
		return f"<InterviewMessage(id={self.id!r}, from={self.from_user_id!r}, to={self.to_user_id!r})>"


class ReservTimeSlot(Base):
	"""Временные слоты для листа 'резерв'."""
	__tablename__ = 'reserv_time_slots'

	id = Column(Integer, primary_key=True, index=True)
	interviewer_id = Column(Integer, ForeignKey('interviewers.id'), nullable=False)
	date = Column(String(10), nullable=False)  # Формат: YYYY-MM-DD
	time_start = Column(String(5), nullable=False)  # Формат: HH:MM
	time_end = Column(String(5), nullable=False)  # Формат: HH:MM
	is_available = Column(Boolean, default=True)
	google_sheet_sync = Column(DateTime(timezone=True), nullable=True)  # Последняя синхронизация
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	# Связи
	interviewer = relationship('Interviewer', foreign_keys=[interviewer_id])

	def __repr__(self) -> str:
		return f"<ReservTimeSlot(id={self.id!r}, date={self.date!r}, time={self.time_start}-{self.time_end})>"


class ReservBooking(Base):
	"""Записи на собеседования для листа 'резерв'."""
	__tablename__ = 'reserv_bookings'

	id = Column(Integer, primary_key=True, index=True)
	time_slot_id = Column(Integer, ForeignKey('reserv_time_slots.id'), nullable=False, unique=True)
	interviewer_id = Column(Integer, ForeignKey('interviewers.id'), nullable=False)
	bot_user_id = Column(Integer, ForeignKey('bot_users.id'), nullable=False)
	person_id = Column(Integer, ForeignKey('people.id'), nullable=True)
	status = Column(String(20), default='confirmed')  # confirmed/cancelled
	notes = Column(String(1000), nullable=True)
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	# Связи
	time_slot = relationship('ReservTimeSlot')
	interviewer = relationship('Interviewer', foreign_keys=[interviewer_id])
	bot_user = relationship('BotUser')
	person = relationship('Person')

	def __repr__(self) -> str:
		return f"<ReservBooking(id={self.id!r}, status={self.status!r})>"


class FinfakTimeSlot(Base):
	"""Временные слоты для листа 'финфак'."""
	__tablename__ = 'finfak_time_slots'

	id = Column(Integer, primary_key=True, index=True)
	interviewer_id = Column(Integer, ForeignKey('interviewers.id'), nullable=False)
	date = Column(String(10), nullable=False)  # Формат: YYYY-MM-DD
	time_start = Column(String(5), nullable=False)  # Формат: HH:MM
	time_end = Column(String(5), nullable=False)  # Формат: HH:MM
	is_available = Column(Boolean, default=True)
	google_sheet_sync = Column(DateTime(timezone=True), nullable=True)  # Последняя синхронизация
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	# Связи
	interviewer = relationship('Interviewer', foreign_keys=[interviewer_id])

	def __repr__(self) -> str:
		return f"<FinfakTimeSlot(id={self.id!r}, date={self.date!r}, time={self.time_start}-{self.time_end})>"


class FinfakBooking(Base):
	"""Записи на собеседования для листа 'финфак'."""
	__tablename__ = 'finfak_bookings'

	id = Column(Integer, primary_key=True, index=True)
	time_slot_id = Column(Integer, ForeignKey('finfak_time_slots.id'), nullable=False, unique=True)
	interviewer_id = Column(Integer, ForeignKey('interviewers.id'), nullable=False)
	bot_user_id = Column(Integer, ForeignKey('bot_users.id'), nullable=False)
	person_id = Column(Integer, ForeignKey('people.id'), nullable=True)
	status = Column(String(20), default='confirmed')  # confirmed/cancelled
	notes = Column(String(1000), nullable=True)
	created_at = Column(DateTime(timezone=True), server_default=func.now())

	# Связи
	time_slot = relationship('FinfakTimeSlot')
	interviewer = relationship('Interviewer', foreign_keys=[interviewer_id])
	bot_user = relationship('BotUser')
	person = relationship('Person')

	def __repr__(self) -> str:
		return f"<FinfakBooking(id={self.id!r}, status={self.status!r})>"