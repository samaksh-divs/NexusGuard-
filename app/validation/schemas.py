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
from typing import Any

from pydantic import BaseModel, Field


class TransactionCreate(BaseModel):
    transaction_id: str = Field(..., min_length=1, description="Unique transaction identifier")
    timestamp: datetime
    symbol: str = Field(..., min_length=1, description="e.g. BTCUSDT")
    amount: float | None = Field(default=None, ge=0)
    price: float = Field(..., gt=0)
    quantity: float = Field(..., ge=0)
    status: str = Field(default="received")
    # Phase 6: identifies which account/user this transaction belongs
    # to, so behavioral analysis can look up that account's history.
    # Defaulted (not required) so any client/test that predates Phase
    # 6 and doesn't send it still validates — it just won't get
    # meaningful behavioral analysis (an "UNKNOWN" account has no
    # real history to compare against).
    account_id: str = Field(default="UNKNOWN", min_length=1, description="Account/user identifier")
    source_transaction_id: str | None = None
    source_dataset: str | None = None
    chain: str | None = None
    network: str | None = None
    sender: str | None = None
    receiver: str | None = None
    bitcoin_amount: float | None = Field(default=None, ge=0)
    fee_sats: int | None = Field(default=None, ge=0)
    vin: list[dict[str, Any]] | None = None
    vout: list[dict[str, Any]] | None = None
    mempool_status: dict[str, Any] | None = None
    mempool_observed_at: datetime | None = None


class TransactionOut(BaseModel):
    id: str
    transaction_id: str
    timestamp: datetime
    symbol: str
    price: float | None
    quantity: float
    transaction_value: float | None
    status: str
    account_id: str
    amount: float | None = None
