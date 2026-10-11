from pathlib import Path

import pandas as pd
import pytest

DEFAULT_CSV_PATH = Path(__file__).resolve().parents[1] / "src" / "data" / "data.csv"


@pytest.fixture(scope="session")
def path_to_file():
    return DEFAULT_CSV_PATH


# Fixture to read the CSV file
@pytest.fixture(scope="session")
def read_csv(path_to_file):
    assert Path(path_to_file).is_file(), f"CSV file not found: {path_to_file}"
    return pd.read_csv(path_to_file)


# Fixture to validate the schema of the file
@pytest.fixture(scope="session")
def validate_schema():
    def _validate(actual_schema, expected_schema):
        actual, expected = list(actual_schema), list(expected_schema)
        assert actual == expected, (
            f"Schema mismatch: expected {expected}, got {actual}"
        )

    return _validate


# Pytest hook to mark unmarked tests with a custom mark
def pytest_collection_modifyitems(items):
    for item in items:
        if not list(item.iter_markers()):
            item.add_marker(pytest.mark.unmarked)
