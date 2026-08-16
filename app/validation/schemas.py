"""
Transaction schemas.

We use two separate models on purpose:

- TransactionCreate: what the CLIENT sends us (POST /transactions/test).
  Does not include transaction_value or status — those are computed
  or defaulted by the server, not supplied by the caller.

- TransactionOut: what WE send back to the client. Includes the
  Mongo-generated id (converted to a plain string) plus the
  server-computed fields.

Keeping these separate avoids a common mistake: reusing one model for
both input and output, which either lets clients set fields they
shouldn't, or forces optional fields that should really be required.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class TransactionCreate(BaseModel):
    transaction_id: str = Field(..., min_length=1, description="Unique transaction identifier")
    timestamp: datetime
    symbol: str = Field(..., min_length=1, description="e.g. BTCUSDT")
    price: float = Field(..., gt=0)
    quantity: float = Field(..., gt=0)
    status: str = Field(default="received")


class TransactionOut(BaseModel):
    id: str
    transaction_id: str
    timestamp: datetime
    symbol: str
    price: float
    quantity: float
    transaction_value: float
    status: str
