# src/api/accounts.py — i movimenti e la spesa di un conto del portafoglio
import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.services.account_service import AccountService
from src.types.accounts import MovementCreate, MovementCreated, MovementOut, Spending

router = APIRouter(prefix="/api/ai/accounts", tags=["Accounts"])

# L'operatore è finto, come l'utente della chat: dal Giorno 6 arriva dal token, e questa riga
# cambia. Il filtro per portafoglio invece c'è già, ed è nelle query.
OPERATORE = "mbianchi"


@router.get("/{account_id}/movements", response_model=list[MovementOut])
async def movements(
    account_id: str,
    date_from: dt.date,
    date_to: dt.date,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[MovementOut]:
    return await AccountService(session).movements_with_owner(
        OPERATORE, account_id, date_from, date_to
    )


@router.get("/{account_id}/spending", response_model=Spending)
async def spending(
    account_id: str,
    date_from: dt.date,
    date_to: dt.date,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Spending:
    return await AccountService(session).spending(OPERATORE, account_id, date_from, date_to)

@router.post("/{account_id}/movements", response_model=MovementCreated, status_code=201)
async def register_movement(
    account_id: str,
    body: MovementCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MovementCreated:
    return await AccountService(session).register_movement(OPERATORE, account_id, body)
