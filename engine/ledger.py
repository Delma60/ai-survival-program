"""Wallet operations, integer-minor-unit transactions, and royalty routing."""

import sqlite3
from typing import Optional

from engine.db import atomic

CREDITS_PER_UNIT = 100
BASIS_POINTS = 10_000


def credits_to_minor(amount: int) -> int:
    """Convert a whole-credit configuration value to integer minor units."""
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError("credit amounts must be non-negative whole numbers")
    return amount * CREDITS_PER_UNIT


def _validate_minor_amount(amount: int) -> None:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("transaction amount must be a positive integer in minor units")


def _post(
    connection: sqlite3.Connection,
    amount: int,
    reason: str,
    from_wallet: Optional[int] = None,
    to_wallet: Optional[int] = None,
    ref_id: Optional[str] = None,
) -> int:
    _validate_minor_amount(amount)
    if from_wallet is None and to_wallet is None:
        raise ValueError("transaction must affect at least one wallet")
    cursor = connection.execute(
        """INSERT INTO transactions(from_wallet, to_wallet, amount, reason, ref_id)
           VALUES (?, ?, ?, ?, ?)""",
        (from_wallet, to_wallet, amount, reason, ref_id),
    )
    if from_wallet is not None:
        source = connection.execute(
            "SELECT balance FROM wallets WHERE id = ?", (from_wallet,)
        ).fetchone()
        if source is None:
            raise ValueError("source wallet does not exist")
        if source["balance"] < amount:
            raise ValueError("insufficient funds")
        connection.execute(
            "UPDATE wallets SET balance = balance - ? WHERE id = ?",
            (amount, from_wallet),
        )
    if to_wallet is not None:
        changed = connection.execute(
            "UPDATE wallets SET balance = balance + ? WHERE id = ?",
            (amount, to_wallet),
        ).rowcount
        if changed != 1:
            raise ValueError("destination wallet does not exist")
    return int(cursor.lastrowid)


def credit(
    connection: sqlite3.Connection,
    wallet_id: int,
    amount: int,
    reason: str,
    *,
    income: bool = False,
    ref_id: Optional[str] = None,
    royalty_rate_bp: int = 1_000,
    grandparent_rate_bp: int = 100,
) -> int:
    """Credit a wallet, routing configured income royalties automatically."""
    _validate_minor_amount(amount)
    if not 0 <= royalty_rate_bp <= BASIS_POINTS:
        raise ValueError("royalty rate must be between 0 and 10000 basis points")
    if not 0 <= grandparent_rate_bp <= BASIS_POINTS:
        raise ValueError("grandparent rate must be between 0 and 10000 basis points")
    if grandparent_rate_bp > royalty_rate_bp:
        raise ValueError("grandparent rate cannot exceed the parent royalty rate")

    with atomic(connection):
        owner = connection.execute(
            """SELECT a.parent_id FROM wallets w
               JOIN agents a ON a.id = w.owner_agent_id
               WHERE w.id = ?""",
            (wallet_id,),
        ).fetchone()
        if owner is None:
            raise ValueError("destination wallet does not exist")

        royalty = amount * royalty_rate_bp // BASIS_POINTS if income and owner["parent_id"] else 0
        grandparent_royalty = (
            amount * grandparent_rate_bp // BASIS_POINTS
            if royalty and grandparent_rate_bp
            else 0
        )
        parent_royalty = royalty - grandparent_royalty
        if amount - royalty:
            _post(
                connection, amount - royalty, reason, to_wallet=wallet_id, ref_id=ref_id
            )

        if parent_royalty:
            parent_wallet = connection.execute(
                "SELECT id FROM wallets WHERE owner_agent_id = ?",
                (owner["parent_id"],),
            ).fetchone()
            if parent_wallet is None:
                raise ValueError("parent agent has no wallet")
            _post(
                connection,
                parent_royalty,
                "royalty",
                to_wallet=parent_wallet["id"],
                ref_id=ref_id,
            )

        if grandparent_royalty:
            grandparent = connection.execute(
                "SELECT parent_id FROM agents WHERE id = ?", (owner["parent_id"],)
            ).fetchone()
            if grandparent and grandparent["parent_id"] is not None:
                grandparent_wallet = connection.execute(
                    "SELECT id FROM wallets WHERE owner_agent_id = ?",
                    (grandparent["parent_id"],),
                ).fetchone()
                if grandparent_wallet is None:
                    raise ValueError("grandparent agent has no wallet")
                _post(
                    connection,
                    grandparent_royalty,
                    "royalty-gen2",
                    to_wallet=grandparent_wallet["id"],
                    ref_id=ref_id,
                )
            else:
                parent_wallet = connection.execute(
                    "SELECT id FROM wallets WHERE owner_agent_id = ?",
                    (owner["parent_id"],),
                ).fetchone()
                if parent_wallet is None:
                    raise ValueError("parent agent has no wallet")
                _post(
                    connection,
                    grandparent_royalty,
                    "royalty",
                    to_wallet=parent_wallet["id"],
                    ref_id=ref_id,
                )
    return amount


def debit(
    connection: sqlite3.Connection,
    wallet_id: int,
    amount: int,
    reason: str,
    *,
    allow_overdraft: bool = False,
    ref_id: Optional[str] = None,
) -> int:
    """Debit a wallet to an economy sink and record the transaction."""
    _validate_minor_amount(amount)
    with atomic(connection):
        if allow_overdraft:
            row = connection.execute(
                "SELECT id FROM wallets WHERE id = ?", (wallet_id,)
            ).fetchone()
            if row is None:
                raise ValueError("source wallet does not exist")
            cursor = connection.execute(
                """INSERT INTO transactions(from_wallet, amount, reason, ref_id)
                   VALUES (?, ?, ?, ?)""",
                (wallet_id, amount, reason, ref_id),
            )
            connection.execute(
                "UPDATE wallets SET balance = balance - ? WHERE id = ?",
                (amount, wallet_id),
            )
            return int(cursor.lastrowid)
        return _post(connection, amount, reason, from_wallet=wallet_id, ref_id=ref_id)


def transfer(
    connection: sqlite3.Connection,
    from_wallet: int,
    to_wallet: int,
    amount: int,
    reason: str,
    ref_id: Optional[str] = None,
) -> int:
    """Transfer internal funds without treating them as income."""
    _validate_minor_amount(amount)
    with atomic(connection):
        return _post(
            connection,
            amount,
            reason,
            from_wallet=from_wallet,
            to_wallet=to_wallet,
            ref_id=ref_id,
        )
