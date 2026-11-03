# src/types/accounts.py — i movimenti di un conto, e la spesa per mese
import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MovementOut(BaseModel):
    booking_date: dt.date
    description: str
    amount: Decimal  # nel JSON esce come stringa, "-87.40": un importo non passa da un float
    owner: str  # l'intestatario del conto, dalla JOIN


class MonthlySpending(BaseModel):
    month: str  # "2026-07"
    spent: Decimal


class Spending(BaseModel):
    account_id: str
    date_from: dt.date
    date_to: dt.date
    months: list[MonthlySpending]
    total: Decimal

class MovementCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    booking_date: dt.date
    description: str = Field(min_length=1, max_length=200)
    # max 2 decimali: un importo con tre decimali si rifiuta, non si arrotonda in silenzio
    amount: Decimal = Field(max_digits=12, decimal_places=2, description="Negativo = uscita")

    @field_validator("amount")
    @classmethod
    def non_zero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("l'importo non può essere zero")
        return v


class MovementCreated(BaseModel):
    booking_date: dt.date
    description: str
    amount: Decimal
    balance_after: Decimal  # il saldo dopo il movimento
