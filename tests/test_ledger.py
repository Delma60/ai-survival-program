import pytest

from engine.db import connect, initialize_database
from engine.ledger import credit, credits_to_minor, debit, transfer


def create_agent(connection, parent_id=None):
    cursor = connection.execute(
        "INSERT INTO agents(parent_id, generation) VALUES (?, 1)", (parent_id,)
    )
    agent_id = cursor.lastrowid
    wallet = connection.execute(
        "INSERT INTO wallets(owner_agent_id) VALUES (?)", (agent_id,)
    )
    wallet_id = wallet.lastrowid
    connection.execute(
        "UPDATE agents SET wallet_id = ? WHERE id = ?", (wallet_id, agent_id)
    )
    return agent_id, wallet_id


def test_income_royalties_and_ledger_conservation(tmp_path):
    db_path = tmp_path / "world.db"
    initialize_database(db_path)
    connection = connect(db_path)
    try:
        with connection:
            grandparent_id, grandparent_wallet = create_agent(connection)
            parent_id, parent_wallet = create_agent(connection, grandparent_id)
            _, child_wallet = create_agent(connection, parent_id)

            credit(connection, child_wallet, credits_to_minor(50), "seed")
            credit(
                connection,
                child_wallet,
                credits_to_minor(10),
                "job_reward",
                income=True,
                ref_id="job-1",
            )

        balances = connection.execute(
            "SELECT id, balance FROM wallets ORDER BY id"
        ).fetchall()
        assert [row["balance"] for row in balances] == [10, 90, credits_to_minor(59)]
        royalties = connection.execute(
            """SELECT reason, amount FROM transactions
               WHERE reason LIKE 'royalty%' ORDER BY id"""
        ).fetchall()
        assert [(row["reason"], row["amount"]) for row in royalties] == [
            ("royalty", 90),
            ("royalty-gen2", 10),
        ]

        supply = connection.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN from_wallet IS NULL THEN amount ELSE 0 END), 0)
                 - COALESCE(SUM(CASE WHEN to_wallet IS NULL THEN amount ELSE 0 END), 0)
               AS n FROM transactions"""
        ).fetchone()["n"]
        assert sum(row["balance"] for row in balances) == supply
        assert grandparent_wallet != parent_wallet != child_wallet
    finally:
        connection.close()


def test_transfer_and_debit_validate_funds_atomically(tmp_path):
    db_path = tmp_path / "world.db"
    initialize_database(db_path)
    connection = connect(db_path)
    try:
        with connection:
            _, source = create_agent(connection)
            _, destination = create_agent(connection)
            credit(connection, source, credits_to_minor(5), "seed")

        with pytest.raises(ValueError, match="insufficient funds"):
            transfer(connection, source, destination, credits_to_minor(6), "transfer")
        assert connection.execute(
            "SELECT balance FROM wallets WHERE id = ?", (source,)
        ).fetchone()["balance"] == credits_to_minor(5)
        assert connection.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"] == 1

        transfer(connection, source, destination, credits_to_minor(2), "transfer")
        debit(connection, destination, credits_to_minor(1), "fee")
        assert connection.execute(
            "SELECT balance FROM wallets WHERE id = ?", (source,)
        ).fetchone()["balance"] == credits_to_minor(3)
        assert connection.execute(
            "SELECT balance FROM wallets WHERE id = ?", (destination,)
        ).fetchone()["balance"] == credits_to_minor(1)
    finally:
        connection.close()
