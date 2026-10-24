from __future__ import annotations

import datetime as dt
from decimal import Decimal

import numpy as np
import pandas as pd


class DataQualityLibrary:
    """
    A library of static methods for performing data quality checks on pandas DataFrames.

    This class is intended to be used in a PyTest-based testing framework to validate
    the quality of data in DataFrames. Each method performs a specific data quality
    check and uses assertions to ensure that the data meets the expected conditions.
    Assertion messages contain the offending rows / counts / columns for debugging.
    """

    MAX_ROWS_IN_MESSAGE = 20
    FLOAT_PRECISION = 6

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _format_rows(df: pd.DataFrame, limit: int | None = None) -> str:
        limit = limit or DataQualityLibrary.MAX_ROWS_IN_MESSAGE
        text = df.head(limit).to_string(index=False)
        if len(df) > limit:
            text += f"\n... ({len(df) - limit} more rows)"
        return text

    @staticmethod
    def _assert_is_dataframe(df, name: str = "df") -> None:
        assert isinstance(df, pd.DataFrame), f"{name} must be a pandas DataFrame, got {type(df).__name__}"

    @staticmethod
    def _assert_columns_exist(df: pd.DataFrame, column_names: list[str]) -> None:
        missing = [c for c in column_names if c not in df.columns]
        assert not missing, f"Columns {missing} not found in dataset. Available columns: {list(df.columns)}"

    @staticmethod
    def _kind(series: pd.Series) -> str:
        """Classify a column as 'numeric', 'datetime', 'bool' or 'other' (strings/mixed)."""
        if pd.api.types.is_bool_dtype(series):
            return "bool"
        if pd.api.types.is_numeric_dtype(series):
            return "numeric"
        if pd.api.types.is_datetime64_any_dtype(series):
            return "datetime"
        values = series.dropna()
        if values.empty:
            return "other"
        if values.map(lambda v: isinstance(v, (int, float, Decimal, np.number)) and not isinstance(v, bool)).all():
            return "numeric"
        if values.map(lambda v: isinstance(v, (dt.date, dt.datetime, pd.Timestamp))).all():
            return "datetime"
        return "other"

    @staticmethod
    def _to_numeric(series: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(series.map(lambda v: float(v) if isinstance(v, Decimal) else v), errors="raise")
        return numeric.astype("float64").round(DataQualityLibrary.FLOAT_PRECISION)

    @staticmethod
    def _to_datetime(series: pd.Series) -> pd.Series:
        converted = pd.to_datetime(series, errors="raise")
        if getattr(converted.dt, "tz", None) is not None:
            converted = converted.dt.tz_convert("UTC").dt.tz_localize(None)
        return converted.astype("datetime64[ns]")

    @staticmethod
    def _to_object(series: pd.Series) -> pd.Series:
        obj = series.astype(object)
        return obj.where(series.notna(), None)

    @classmethod
    def _normalize_column_pair(cls, expected: pd.Series, actual: pd.Series) -> tuple[pd.Series, pd.Series]:
        """
        Bring an expected/actual column pair to one comparable representation.

        Source (Postgres/psycopg2) and target (Parquet/pyarrow) return the same logical values
        with different Python types, e.g. ``Decimal`` vs ``float64`` or ``datetime.date`` vs
        ``datetime64``. Values are only converted between representations (floats are rounded
        to ``FLOAT_PRECISION`` decimals to absorb binary float noise), so real data
        differences still fail the comparison.
        """
        expected_kind, actual_kind = cls._kind(expected), cls._kind(actual)
        target_kind = expected_kind if expected_kind != "other" else actual_kind
        converters = {"numeric": cls._to_numeric, "datetime": cls._to_datetime}
        if target_kind in converters:
            try:
                return converters[target_kind](expected), converters[target_kind](actual)
            except (TypeError, ValueError):
                pass
        return cls._to_object(expected), cls._to_object(actual)

    # ------------------------------------------------------------------ checks

    @staticmethod
    def check_dataset_is_not_empty(df: pd.DataFrame) -> None:
        """Assert the dataset is a DataFrame and has at least one row."""
        DataQualityLibrary._assert_is_dataframe(df)
        assert not df.empty, f"Dataset is empty: 0 rows (columns: {list(df.columns)})"

    @staticmethod
    def check_count(df1: pd.DataFrame, df2: pd.DataFrame) -> None:
        """Assert expected (df1) and actual (df2) datasets have the same number of rows."""
        DataQualityLibrary._assert_is_dataframe(df1, "expected")
        DataQualityLibrary._assert_is_dataframe(df2, "actual")
        expected_count, actual_count = len(df1), len(df2)
        assert expected_count == actual_count, (
            f"Row count mismatch: expected (source) = {expected_count}, actual (target) = {actual_count}, "
            f"difference = {actual_count - expected_count:+d}"
        )

    @classmethod
    def check_data_completeness(cls, df1: pd.DataFrame, df2: pd.DataFrame) -> None:
        """
        Assert expected (df1, source) and actual (df2, target) contain exactly the same rows.

        Row order and column order are ignored; duplicate rows are compared as a multiset.
        Fails with the list of missing/extra columns or the rows present on one side only.
        """
        cls._assert_is_dataframe(df1, "expected")
        cls._assert_is_dataframe(df2, "actual")

        expected_cols, actual_cols = list(df1.columns), list(df2.columns)
        missing_cols = [c for c in expected_cols if c not in actual_cols]
        extra_cols = [c for c in actual_cols if c not in expected_cols]
        assert not missing_cols and not extra_cols, (
            f"Column mismatch between expected (source) and actual (target).\n"
            f"Missing in target: {missing_cols}\nUnexpected in target: {extra_cols}\n"
            f"Expected columns: {expected_cols}\nActual columns: {actual_cols}"
        )

        expected = pd.DataFrame(index=range(len(df1)))
        actual = pd.DataFrame(index=range(len(df2)))
        for column in expected_cols:
            expected[column], actual[column] = cls._normalize_column_pair(
                df1[column].reset_index(drop=True), df2[column].reset_index(drop=True)
            )

        # Number each occurrence of an identical row so duplicates are matched one-to-one.
        occurrence = "__dq_occurrence__"
        expected[occurrence] = expected.groupby(expected_cols, dropna=False, sort=False).cumcount()
        actual[occurrence] = actual.groupby(expected_cols, dropna=False, sort=False).cumcount()

        merged = expected.merge(actual, on=expected_cols + [occurrence], how="outer", indicator=True)
        only_expected = merged.loc[merged["_merge"] == "left_only", expected_cols]
        only_actual = merged.loc[merged["_merge"] == "right_only", expected_cols]

        message_parts = []
        if not only_expected.empty:
            message_parts.append(
                f"{len(only_expected)} row(s) expected (source) but missing in target:\n"
                f"{cls._format_rows(only_expected)}"
            )
        if not only_actual.empty:
            message_parts.append(
                f"{len(only_actual)} row(s) in target but not expected (source):\n"
                f"{cls._format_rows(only_actual)}"
            )
        assert not message_parts, (
            f"Data completeness check failed (expected rows = {len(df1)}, actual rows = {len(df2)}).\n"
            + "\n\n".join(message_parts)
        )

    @staticmethod
    def check_duplicates(df: pd.DataFrame, column_names: list[str] | None = None) -> None:
        """Assert there are no duplicate rows (considering all columns, or only ``column_names``)."""
        DataQualityLibrary._assert_is_dataframe(df)
        subset = list(column_names) if column_names else list(df.columns)
        DataQualityLibrary._assert_columns_exist(df, subset)
        duplicated = df[df.duplicated(subset=subset, keep=False)]
        if not duplicated.empty:
            duplicated = duplicated.sort_values(by=subset, na_position="last")
        assert duplicated.empty, (
            f"Found {len(duplicated)} row(s) involved in duplicates by columns {subset} "
            f"({df.duplicated(subset=subset).sum()} extra occurrence(s)):\n"
            f"{DataQualityLibrary._format_rows(duplicated)}"
        )

    @staticmethod
    def check_not_null_values(df: pd.DataFrame, column_names: list[str] | None = None) -> None:
        """Assert the given columns (all columns if omitted) contain no null values."""
        DataQualityLibrary._assert_is_dataframe(df)
        columns = list(column_names) if column_names else list(df.columns)
        DataQualityLibrary._assert_columns_exist(df, columns)
        null_counts = df[columns].isna().sum()
        null_counts = null_counts[null_counts > 0]
        if null_counts.empty:
            return
        null_rows = df[df[columns].isna().any(axis=1)]
        details = ", ".join(f"'{col}': {count}" for col, count in null_counts.items())
        raise AssertionError(
            f"Null values found in column(s) {{{details}}} out of {len(df)} rows.\n"
            f"Sample rows with nulls:\n{DataQualityLibrary._format_rows(null_rows)}"
        )
