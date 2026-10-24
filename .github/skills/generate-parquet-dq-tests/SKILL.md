---
name: generate-parquet-dq-tests
description: >-
  Creates one PyTest DQ module per Parquet dataset at
  "PyTest DQ Framework/tests/dq checks/parquet_files/test_<dataset_name>.py", deriving the
  expected (source) Postgres SQL only from docs/parquet-aggregated-data-mapping.md and comparing it
  to the Parquet target with the framework's DataQualityLibrary. Invoke explicitly when asked to
  generate or regenerate Parquet dataset tests. Refuses to edit framework code (connectors, library,
  conftest.py, pytest.ini, requirements.txt, Jenkinsfile) and to use data_dev/ SQL as expected results.
disable-model-invocation: true
---

# Generate Parquet DQ tests

This skill applies the **Test Automation Strategy** (TAS) to produce Parquet DQ test modules. Sources of truth:

- `PyTest DQ Framework/docs/test-automation-strategy.md`: **§5 Skill contract**, **§6 Test design standard**
- `docs/parquet-aggregated-data-mapping.md`: dataset definitions (the **only** source for expected SQL)
- `docs/project-environment.md`: 3NF tables and join keys (relationships only, not transformation logic)

## When this skill applies

Use it when the user explicitly asks to create or regenerate a DQ test module for one or more Parquet datasets under `/parquet_data/<dataset_name>/`.

**Preconditions (check before writing anything):**

- The framework exists and is functional:
  - `PyTest DQ Framework/src/connectors/postgres/postgres_connector.py` (`PostgresConnectorContextManager.get_data_sql`)
  - `PyTest DQ Framework/src/connectors/file_system/parquet_reader.py` (`ParquetReader.process`)
  - `PyTest DQ Framework/src/data_quality/data_quality_validation_library.py` (`DataQualityLibrary`)
  - `PyTest DQ Framework/tests/conftest.py` (fixtures `db_connection`, `parquet_reader`, `data_quality_library`)
  - `PyTest DQ Framework/tests/pytest.ini` (markers)
- The dataset has a section in the mapping document.

**Allowed write paths:**

- `PyTest DQ Framework/tests/dq checks/parquet_files/test_<dataset_name>.py` (create or overwrite)
- `PyTest DQ Framework/tests/pytest.ini`, but **only** to append a missing `<dataset_name>` marker line under `markers =`

**Refuse (or stop and ask the user) when:**

- The request is to change framework code, `conftest.py`, `requirements.txt`, or the `Jenkinsfile`. That is outside this skill unless the user explicitly asks for it separately.
- The dataset is not in the mapping, or the mapping is ambiguous (unknown source column, unclear join path, unclear grain). Ask; do not guess.
- The user asks to make failing tests pass by changing the expected SQL so it matches the Parquet output.

## Inputs you must have

| Input | Source |
| --- | --- |
| Dataset name (= folder under `/parquet_data/`) | User |
| Target columns, transformations, source table/column, comments (grouping / not null / rounding / format) | Mapping section `## \`<dataset_name>\`` in `docs/parquet-aggregated-data-mapping.md` |
| Filters | The mapping's `**Filters:**` line (`—` means **no filter**) |
| Join keys between 3NF tables | `docs/project-environment.md` ER model (`visits.facility_id → facilities.id`, `visits.patient_id → patients.id`) |
| Requirement id and author for the header | User; otherwise keep the placeholders `TICKET-1234` and `<name>` and say so in your reply |

If the mapping file or the dataset section is missing, **stop** and tell the user. Do not invent the mapping from the Parquet files, the HTML report, or the pipeline.

**Forbidden sources for the expected SQL:**

- Anything in `data_dev/`, especially `queries.py`, `src/data/parquet_loader.py`, and `src/reporting/`.
- Parquet contents or schema used to "fix" the query. Previewing Parquet to confirm column names is fine; changing logic to match it is not.
- `tests/test_examples.py`. Its source/target direction is swapped and its paths are placeholders.

## Hard rules

1. **Path and name.** One dataset per module: `PyTest DQ Framework/tests/dq checks/parquet_files/test_<dataset_name>.py`, where `<dataset_name>` is the exact snake_case Parquet folder name.
2. **Source = Postgres, target = Parquet.** `source_data` uses the `db_connection` fixture with the mapping-derived SQL. `target_data` uses the `parquet_reader` fixture. Never swap them, and never compare a dataset to itself.
3. **Mapping-only SQL.** Build the expected query only from the mapping (plus join keys from the ER model). Do not read or copy SQL from `data_dev/`.
4. **No pipeline artefacts.** Add `UNION`, `WHERE`/`HAVING`, `CASE`, `ABS`/sign flips, `COALESCE`, `DISTINCT`, or extra columns only if the mapping states them. Mapping comments such as "can't be negative" or "not null" are **expectations to verify**. Do not use them to filter or patch the data in SQL.
5. **No dataset SQL in this skill.** This file stays dataset-agnostic. Concrete SQL lives only in the generated module.
6. **Aliases = target columns.** Every output column of `source_data` is aliased to the mapping's *Target column* name, in mapping order. Grain = the columns whose comment says `grouping`.
7. **Target path.** `target_path = '/parquet_data/<dataset_name>'`, read with `include_subfolders=True`. Partition folders are technical; partition columns are not mapping columns and are not added to `source_data`.
8. **Library methods only.** Test bodies call `DataQualityLibrary` methods (`check_dataset_is_not_empty`, `check_data_completeness`, `check_count`, `check_duplicates`, `check_not_null_values`) and nothing else. No inline pandas logic, no `assert True`, no try/except, `skip`, or `xfail` around checks.
9. **All five tests, every time:** `test_check_dataset_is_not_empty`, `test_check_data_completeness`, `test_check_count`, `test_check_uniqueness`, `test_check_not_null_values`.
10. **Markers.** Every test has `@pytest.mark.parquet_data` and `@pytest.mark.<dataset_name>`. `@pytest.mark.smoke` goes **only** on `test_check_dataset_is_not_empty`. The `<dataset_name>` marker must be registered in `tests/pytest.ini` (`--strict-markers` is on); append it if missing.
11. **Uniqueness = grain.** `test_check_uniqueness` passes the grain (`grouping`) columns as `column_names`, so a duplicated business key fails even when the measures differ.
12. **Not-null list = all mapped target columns** of the dataset, in mapping order.
13. **Do not edit framework code** (connectors, library, `conftest.py`, `requirements.txt`, `Jenkinsfile`) unless the user explicitly asks for it.

## Workflow

1. **Confirm inputs.** Get the dataset name and check the preconditions above. Open the dataset's section in the mapping.
2. **Extract a column table** from the mapping: target column, transformation, source table, source column, and comments. Classify each column as:
   - **dimension**: the comment contains `grouping`
   - **measure**: has an aggregate transformation (`min`, `avg`, `SUM`, ...)
3. **Note the constraints** from the comments (rounding, string format, not null, sign) and the Filters line.
4. **Derive the expected SQL** with the generic rules below. Write it down once, then do not change it to match Parquet.
5. **Fill the template:** dataset name, header, SQL, target path, grain columns for uniqueness, and all mapped columns for not-null.
6. **Register the marker** `<dataset_name>` in `PyTest DQ Framework/tests/pytest.ini` if it is not already there.
7. **Self-check** the module against the Hard rules and the review list below, then report the file path and the SQL derivation (column → expression) to the user.

## Template

This is the TAS §6.2 skeleton. Source and target follow the TAS (not `test_examples.py`). The only addition is the grain columns passed to `check_duplicates` (rule 11).

```python
"""
Description: Data Quality checks for <dataset_name> dataset.
Requirement(s): TICKET-1234
Author(s): <name>
"""

import pytest


@pytest.fixture(scope='module')
def source_data(db_connection):
    source_query = """
    -- expected query derived from mapping (grain + measures + joins)
    """
    return db_connection.get_data_sql(source_query)


@pytest.fixture(scope='module')
def target_data(parquet_reader):
    target_path = '/parquet_data/<dataset_name>'
    return parquet_reader.process(target_path, include_subfolders=True)


@pytest.mark.parquet_data
@pytest.mark.smoke
@pytest.mark.<dataset_name>
def test_check_dataset_is_not_empty(target_data, data_quality_library):
    data_quality_library.check_dataset_is_not_empty(target_data)


@pytest.mark.parquet_data
@pytest.mark.<dataset_name>
def test_check_data_completeness(source_data, target_data, data_quality_library):
    data_quality_library.check_data_completeness(source_data, target_data)


@pytest.mark.parquet_data
@pytest.mark.<dataset_name>
def test_check_count(source_data, target_data, data_quality_library):
    data_quality_library.check_count(source_data, target_data)


@pytest.mark.parquet_data
@pytest.mark.<dataset_name>
def test_check_uniqueness(target_data, data_quality_library):
    data_quality_library.check_duplicates(target_data, ['<grain_col_1>', '<grain_col_2>'])


@pytest.mark.parquet_data
@pytest.mark.<dataset_name>
def test_check_not_null_values(target_data, data_quality_library):
    data_quality_library.check_not_null_values(target_data, ['<col_1>', '<col_2>', '<col_3>'])
```

## SQL derivation (generic)

Apply these rules mechanically to the column table from the workflow. They are patterns, not a query for any specific dataset.

- **FROM / JOIN.** Start from the fact table that holds the measures (usually `visits v`). Add an `INNER JOIN` to each parent table that the mapping references as a *Source*, using the ER keys: `JOIN facilities f ON f.id = v.facility_id` and `JOIN patients p ON p.id = v.patient_id`. Join only tables the mapping uses. Do not use outer joins unless the mapping says so.
- **Table names.** The mapping writes `table.<name>`. That is the Postgres table `<name>` in the default schema, not a schema called `table`.
- **Dates.** When a `*_date` target comes from a timestamp column with no transformation, use `CAST(<timestamp_col> AS date) AS <target>`. Group by the same expression. Do not truncate to month: the "Partitioned by year-month" note describes the storage layout, not the grain.
- **Names / concatenation.** Follow the mapping's format literally. For example, `<first><space><last>` becomes `<first> || ' ' || <last>` in that order, with no `TRIM`/`INITCAP`/`COALESCE` unless the mapping says so.
- **Aggregates.** Map the transformation verbatim: `min(x)` → `MIN(x)`, `avg(x)` → `AVG(x)`, `SUM(x)` → `SUM(x)`. Apply rounding only where the comment says so: "rounding to N decimal places" → `ROUND(AVG(x)::numeric, N)`. Do not round measures that have no rounding comment.
- **GROUP BY.** Group by every dimension expression (the same expressions as in the SELECT, not their aliases if they are computed). Grouping by the business attribute, as the mapping states, is correct even if the attribute is not unique by id.
- **Aliases and order.** `SELECT` each column `AS <target column>`, in mapping order. No extra columns: no ids, no partition columns.
- **Filters.** `Filters: —` means no `WHERE` and no `HAVING`. If a filter is listed, translate exactly that predicate and nothing more.
- **No `ORDER BY`** is needed: completeness ignores row order.
- **Constraints in comments** ("not null", "can't be negative", value formats) are verified by the checks or reported as defects. They are never encoded into the SQL.

## After generation

- Run pytest **only if the user asks**, from `PyTest DQ Framework/`:
  `pytest "tests/dq checks/parquet_files/test_<dataset_name>.py" --db_host=localhost --db_port=5434 --db_name=mydatabase --db_user=<user> --db_password=<password> --html=html_report/report.html`
  Never write real credentials into files.
- **Failing checks are transformation defects until proven otherwise.** Do **not** edit the expected SQL, loosen checks, or add `skip`/`xfail` to get a green run. Change the SQL only if you find you misread the mapping, and state which mapping line you misread.
- For each failure, report (TAS §10):
  1. dataset and test name
  2. what the mapping expects
  3. what the Parquet contains (from the assert message or a sample)
  4. the likely root cause in the transformation
- An all-green run must be justified (the SQL is mapping-correct **and** the Parquet truly matches), not assumed.

---

## Skill review (self-check before Step 3)

Reject your own skill if any of these are true. Each box is left unchecked because the condition is **false** for this skill; the reason is noted next to it.

- [ ] Contains concrete expected SQL for `facility_name_min_time_spent_per_visit_date`, `facility_type_avg_time_spent_per_visit_date`, or `patient_sum_treatment_cost_per_facility_type`. *(Only generic patterns and placeholders.)*
- [ ] Tells the agent to use `data_dev/` or parquet loader SQL. *(Listed as forbidden sources in Inputs and rule 3.)*
- [ ] Omits completeness, count, uniqueness, or not-null. *(All five tests are mandatory: rule 9 and the Template.)*
- [ ] Swaps Postgres vs Parquet fixtures or generates trivial always-pass checks. *(Rules 2 and 8: source = `db_connection`, target = `parquet_reader`.)*
- [ ] Any section still says `TODO`. *(All sections are filled.)*
