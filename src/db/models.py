import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.config import settings


def gen_uuid() -> str:
    return str(uuid.uuid4())


_ultimo = datetime.min.replace(tzinfo=UTC)


def adesso() -> datetime:
    """L'istante corrente, mai uguale al precedente: l'ordine dei messaggi non si decide a caso."""
    global _ultimo
    ora = datetime.now(UTC)
    if ora <= _ultimo:
        ora = _ultimo + timedelta(microseconds=1)
    _ultimo = ora
    return ora


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)  # chi ha aperto la conversazione
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=adesso)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        order_by="ChatMessage.created_at",
        cascade="all, delete-orphan",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # "user" oppure "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=adesso)
    session: Mapped[ChatSession] = relationship(back_populates="messages")
    tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_eur: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=Decimal("0"), server_default="0"
    )  # sei decimali: un messaggio costa frazioni di centesimo
    model_used: Mapped[str | None] = mapped_column(String(64), default=None)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # il codice cliente
    full_name: Mapped[str] = mapped_column(String(120))
    operator: Mapped[str] = mapped_column(String(64), index=True)  # chi lo ha in portafoglio


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(34), primary_key=True)  # l'IBAN
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    label: Mapped[str] = mapped_column(String(64))  # "principale", "risparmio"
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Movement(Base):
    __tablename__ = "movements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    booking_date: Mapped[date] = mapped_column(Date)  # la data contabile
    description: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # negativo = uscita


# ---- i documenti della banca, in passaggi indicizzati per similarità


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        # dichiarato anche nel modello: altrimenti la prossima --autogenerate lo cancella
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(String, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))
    chunk_metadata: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    visibility: Mapped[str] = mapped_column(
        String(32), default="public", server_default="public", index=True
    )


# ---- la spesa che non passa dalla chat (per ora solo l'advisor sui documenti)


class CostEvent(Base):
    __tablename__ = "cost_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    source: Mapped[str] = mapped_column(String(32), index=True)  # "advice"
    model_used: Mapped[str | None] = mapped_column(String(64), default=None)
    tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_eur: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=Decimal("0"), server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=adesso, index=True
    )

class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="operator")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=adesso)
