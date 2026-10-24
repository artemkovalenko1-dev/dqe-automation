from __future__ import annotations

import pandas as pd
import psycopg2


class PostgresConnectorContextManager:
    """
    Context manager that owns a read-only PostgreSQL connection and returns query results as DataFrames.

    Usage:
        with PostgresConnectorContextManager(db_host, db_name, db_user, db_password, db_port) as db:
            df = db.get_data_sql("SELECT 1 AS one")
    """

    def __init__(self, db_host: str, db_name: str, db_user: str, db_password: str, db_port: int | str = 5432):
        self.db_host = db_host
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password
        self.db_port = int(db_port)
        self.connection = None

    def __enter__(self):
        try:
            self.connection = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                dbname=self.db_name,
                user=self.db_user,
                password=self.db_password,
            )
        except psycopg2.Error as e:
            raise ConnectionError(
                f"Unable to connect to PostgreSQL at {self.db_host}:{self.db_port}/{self.db_name} "
                f"as '{self.db_user}': {e}"
            ) from e
        # DQ checks only read data; autocommit avoids a failed query poisoning the session-wide transaction.
        self.connection.set_session(readonly=True, autocommit=True)
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        if self.connection is not None and not self.connection.closed:
            self.connection.close()
        self.connection = None
        return False

    def get_data_sql(self, sql: str, params=None) -> pd.DataFrame:
        """Execute a SQL query and return the result set as a pandas DataFrame (column names from the cursor)."""
        if self.connection is None or self.connection.closed:
            raise RuntimeError("Connection is not open. Use PostgresConnectorContextManager as a context manager.")
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            if cursor.description is None:
                raise ValueError("The SQL statement did not return a result set.")
            columns = [column.name for column in cursor.description]
            rows = cursor.fetchall()
        return pd.DataFrame(rows, columns=columns)
