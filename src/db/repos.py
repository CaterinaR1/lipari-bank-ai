from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Account, ChatMessage, ChatSession, Customer, Movement


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_session(self, user_id: str) -> ChatSession:
        chat = ChatSession(user_id=user_id)
        self.session.add(chat)
        await self.session.flush()  # l'id esiste, il commit no: lo decide il service
        return chat

    async def find_session(self, session_id: str, user_id: str) -> ChatSession | None:
        """La conversazione con i suoi messaggi, solo se è di questo utente: due query, non N+1."""
        stmt = (
            select(ChatSession)
            .where(ChatSession.id == session_id, ChatSession.user_id == user_id)
            .options(selectinload(ChatSession.messages))
        )
        return await self.session.scalar(stmt)

    async def add_message(self, session_id: str, role: str, content: str) -> ChatMessage:
        messaggio = ChatMessage(session_id=session_id, role=role, content=content)
        self.session.add(messaggio)
        await self.session.flush()
        return messaggio

class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def of_user(self, username: str, account_id: str) -> Account | None:
        """Il conto, solo se è di un cliente nel portafoglio di questo operatore."""
        return await self.session.scalar(
            select(Account)
            .join(Customer, Customer.id == Account.customer_id)
            .where(Account.id == account_id, Customer.operator == username)
        )

    async def of_customer(self, username: str, customer_id: str) -> list[Account]:
        """I conti di un cliente, solo se il cliente è nel portafoglio di questo operatore."""
        stmt = (
            select(Account)
            .join(Customer, Customer.id == Account.customer_id)
            .where(Customer.id == customer_id, Customer.operator == username)
            .order_by(Account.label)
        )
        return list((await self.session.scalars(stmt)).all())

    async def adjust_balance(self, account_id: str, delta: Decimal) -> Decimal:
        """Somma delta al saldo, nel database: nessuna lettura-poi-scrittura in Python."""
        stmt = (
            update(Account)
            .where(Account.id == account_id)
            .values(balance=Account.balance + delta)
            .returning(Account.balance)
        )
        nuovo: Decimal = (await self.session.execute(stmt)).scalar_one()
        return nuovo


class MovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def recent(self, username: str, account_id: str, limite: int) -> list[Movement]:
        """Gli ultimi movimenti di un conto del portafoglio, dal più recente."""
        stmt = (
            select(Movement)
            .join(Account, Account.id == Movement.account_id)
            .join(Customer, Customer.id == Account.customer_id)
            .where(Account.id == account_id, Customer.operator == username)
            .order_by(Movement.booking_date.desc())
            .limit(limite)
        )
        return list((await self.session.scalars(stmt)).all())

    async def with_owner(
        self, username: str, account_id: str, dal: date, al: date
    ) -> list[tuple[Movement, str]]:
        """I movimenti di un conto in un periodo, ognuno con il nome dell'intestatario."""
        stmt = (
            select(Movement, Customer.full_name)
            .join(Account, Account.id == Movement.account_id)  # il movimento, al suo conto
            .join(Customer, Customer.id == Account.customer_id)  # il conto, al suo cliente
            .where(
                Account.id == account_id,
                Customer.operator == username,
                Movement.booking_date.between(dal, al),
            )
            .order_by(Movement.booking_date, Movement.id)
        )
        return list((await self.session.execute(stmt)).all())

    async def spent_by_month(
        self, username: str, account_id: str, dal: date, al: date
    ) -> list[tuple[str, Decimal]]:
        """Quanto è uscito dal conto, mese per mese: la somma delle uscite, cambiata di segno."""
        mese = func.to_char(Movement.booking_date, "YYYY-MM")
        stmt = (
            select(mese, func.sum(-Movement.amount))
            .join(Account, Account.id == Movement.account_id)
            .join(Customer, Customer.id == Account.customer_id)
            .where(
                Account.id == account_id,
                Customer.operator == username,
                Movement.booking_date.between(dal, al),
                Movement.amount < 0,  # solo le uscite: gli accrediti non sono spesa
            )
            .group_by(mese)
            .order_by(mese)
        )
        return list((await self.session.execute(stmt)).all())

    async def add(
        self, account_id: str, booking_date: date, description: str, amount: Decimal
    ) -> Movement:
        movimento = Movement(
            account_id=account_id,
            booking_date=booking_date,
            description=description,
            amount=amount,
        )
        self.session.add(movimento)
        await self.session.flush()  # scritto nella transazione, non ancora confermato
        return movimento
