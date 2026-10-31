"""Custom Robot Framework keywords for comparing an HTML report table with a Parquet dataset."""
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
from selenium.webdriver.common.by import By

PARTITION_COLUMN = "partition_date"


def _text(element) -> str:
    # textContent works for SVG nodes, unlike WebElement.text
    return (element.get_attribute("textContent") or "").strip()


def _read_plotly_table(table_element):
    """Read headers and cells from a Plotly table (<g class="table">) rendered as SVG."""
    headers, columns = [], []
    for column in table_element.find_elements(By.CSS_SELECTOR, "g.y-column"):
        header = column.find_element(
            By.XPATH, ".//*[local-name()='g' and @id='header']//*[local-name()='text']"
        )
        headers.append(_text(header))
        cells = column.find_elements(
            By.XPATH, ".//*[local-name()='g' and starts-with(@id,'cells')]//*[local-name()='text']"
        )
        columns.append([t for t in (_text(c) for c in cells) if t])

    # Plotly virtualises long tables, so the DOM may hold only visible rows; use the figure data then
    source = table_element.parent.execute_script(
        "const gd = arguments[0].closest('.plotly-graph-div');"
        "const t = gd && gd.data ? gd.data.find(tr => tr.type === 'table') : null;"
        "return t ? t.cells.values : null;",
        table_element,
    )
    if source and not (columns and all(len(c) == len(source[0]) for c in columns)):
        columns = [[str(v) for v in col] for col in source]
    return headers, columns


def _read_html_table(table_element):
    """Read headers and cells from a regular HTML <table>."""
    headers = [_text(th) for th in table_element.find_elements(By.TAG_NAME, "th")]
    rows = [
        [_text(td) for td in tr.find_elements(By.TAG_NAME, "td")]
        for tr in table_element.find_elements(By.TAG_NAME, "tr")
    ]
    rows = [r for r in rows if r]
    return headers, [list(col) for col in zip(*rows)] if rows else [[] for _ in headers]


def read_html_table_to_dataframe(table_element) -> pd.DataFrame:
    """Convert a located table WebElement (HTML <table> or Plotly SVG table) into a DataFrame of strings."""
    if table_element.tag_name.lower() == "table":
        headers, columns = _read_html_table(table_element)
    else:
        headers, columns = _read_plotly_table(table_element)
    if not headers:
        raise AssertionError("No table headers found in the located table element")
    return pd.DataFrame(dict(zip(headers, columns)), columns=headers)


def read_parquet_dataset(folder, filter_date=None, date_column="visit_date", column_mapping=None) -> pd.DataFrame:
    """Read a Hive-partitioned Parquet dataset.

    If ``filter_date`` (YYYY-MM-DD) is given, only rows with ``date_column >= filter_date`` are kept;
    monthly ``partition_date=YYYY-MM`` partitions older than that month are pruned before reading.
    ``column_mapping`` optionally selects/renames columns (``{parquet_column: report_header}``).
    """
    path = Path(folder)
    if not path.is_dir():
        raise AssertionError(f"Parquet folder not found: {path}")

    dataset = ds.dataset(str(path), format="parquet", partitioning="hive")
    expression = None
    if filter_date:
        date = pd.Timestamp(str(filter_date))
        expression = ds.field(date_column) >= date.to_pydatetime()
        if PARTITION_COLUMN in dataset.schema.names:
            expression &= ds.field(PARTITION_COLUMN) >= date.strftime("%Y-%m")
    df = dataset.to_table(filter=expression).to_pandas()

    df = df.drop(columns=[PARTITION_COLUMN], errors="ignore")
    if column_mapping:
        mapping = dict(column_mapping)
        missing = set(mapping) - set(df.columns)
        if missing:
            raise AssertionError(f"Columns not found in Parquet dataset: {sorted(missing)}")
        df = df[list(mapping)].rename(columns=mapping)
    return df.reset_index(drop=True)


def _normalize(series: pd.Series) -> pd.Series:
    """Bring a column to a canonical comparable representation (number, YYYY-MM-DD date or text)."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.strftime("%Y-%m-%d")
    text = series.astype(str).str.strip()
    numeric = pd.to_numeric(text, errors="coerce")
    if numeric.notna().all():
        return numeric.astype(float)
    dates = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    if dates.notna().all():
        return dates.dt.strftime("%Y-%m-%d")
    return text


def compare_dataframes(actual: pd.DataFrame, expected: pd.DataFrame):
    """Compare two DataFrames for an exact match regardless of row order.

    Returns ``(True, "")`` when they match, otherwise ``(False, <description of differences>)``.
    """
    if list(actual.columns) != list(expected.columns):
        return False, (f"Column mismatch:\n  HTML:    {list(actual.columns)}\n"
                       f"  Parquet: {list(expected.columns)}")

    left = actual.apply(_normalize)
    right = expected.apply(_normalize)
    columns = list(left.columns)

    problems = []
    if len(left) != len(right):
        problems.append(f"Row count mismatch: HTML={len(left)}, Parquet={len(right)}")

    # Occurrence counter keeps duplicate rows significant in the outer join
    left["_n"] = left.groupby(columns, dropna=False).cumcount()
    right["_n"] = right.groupby(columns, dropna=False).cumcount()
    merged = left.merge(right, on=columns + ["_n"], how="outer", indicator=True)

    only_html = merged[merged["_merge"] == "left_only"][columns]
    only_parquet = merged[merged["_merge"] == "right_only"][columns]
    if not only_html.empty:
        problems.append(f"Rows only in HTML report ({len(only_html)}):\n{only_html.to_string(index=False)}")
    if not only_parquet.empty:
        problems.append(f"Rows only in Parquet dataset ({len(only_parquet)}):\n{only_parquet.to_string(index=False)}")

    return (not problems), "\n\n".join(problems)
