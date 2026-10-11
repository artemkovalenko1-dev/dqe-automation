import re

import pytest

EXPECTED_SCHEMA = ["id", "name", "age", "email", "is_active"]
EMAIL_PATTERN = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def test_file_not_empty(read_csv):
    assert not read_csv.empty, "CSV file is empty: no data rows found"


@pytest.mark.validate_csv
def test_validate_schema(read_csv, validate_schema):
    validate_schema(read_csv.columns, EXPECTED_SCHEMA)


@pytest.mark.validate_csv
@pytest.mark.skip(reason="Age validation is not required for now")
def test_age_column_valid(read_csv):
    invalid = read_csv[~read_csv["age"].between(0, 100)]
    assert invalid.empty, f"Age out of range 0-100 for ids: {invalid['id'].tolist()}"


@pytest.mark.validate_csv
def test_email_column_valid(read_csv):
    invalid = read_csv[~read_csv["email"].astype(str).str.match(EMAIL_PATTERN)]
    assert invalid.empty, (
        f"Invalid email format for ids {invalid['id'].tolist()}: "
        f"{invalid['email'].tolist()}"
    )


@pytest.mark.validate_csv
@pytest.mark.xfail(reason="Known issue: source file contains duplicate rows")
def test_duplicates(read_csv):
    duplicates = read_csv[read_csv.duplicated(keep=False)]
    assert duplicates.empty, f"Duplicate rows found for ids: {duplicates['id'].unique().tolist()}"


@pytest.mark.parametrize("id, is_active", [(1, False), (2, True)])
def test_active_players(read_csv, id, is_active):
    rows = read_csv[read_csv["id"] == id]
    assert len(rows) == 1, f"Expected exactly one row for id={id}, found {len(rows)}"
    actual = bool(rows.iloc[0]["is_active"])
    assert actual == is_active, (
        f"id={id}: expected is_active={is_active}, got {actual}"
    )


def test_active_player(read_csv):
    rows = read_csv[read_csv["id"] == 2]
    assert len(rows) == 1, f"Expected exactly one row for id=2, found {len(rows)}"
    actual = bool(rows.iloc[0]["is_active"])
    assert actual is True, f"id=2: expected is_active=True, got {actual}"
