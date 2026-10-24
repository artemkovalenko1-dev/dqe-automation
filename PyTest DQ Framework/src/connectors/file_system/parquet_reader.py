from __future__ import annotations

from pathlib import Path

import pandas as pd


class ParquetReader:
    """
    Reads Parquet data from the local (or mounted network) file system into a pandas DataFrame.

    Datasets written with ``partition_cols`` are stored as Hive-style folders
    (``<dataset>/<partition_col>=<value>/<file>.parquet``). The reader loads the physical
    ``.parquet`` files only, so technical partition columns that exist solely in folder
    names are not added to the result. This keeps the target schema equal to the data
    actually stored in the files.
    """

    PARQUET_SUFFIX = ".parquet"

    def __init__(self, engine: str = "pyarrow"):
        self.engine = engine

    def list_files(self, path: str | Path, include_subfolders: bool = True) -> list[Path]:
        """Return a sorted list of Parquet files in ``path`` (a file or a directory)."""
        root = Path(path)
        if not root.exists():
            raise FileNotFoundError(f"Parquet path does not exist: {root}")
        if root.is_file():
            return [root]
        pattern = f"**/*{self.PARQUET_SUFFIX}" if include_subfolders else f"*{self.PARQUET_SUFFIX}"
        return sorted(p for p in root.glob(pattern) if p.is_file() and not p.name.startswith((".", "_")))

    def process(self, path: str | Path, include_subfolders: bool = False) -> pd.DataFrame:
        """
        Read a Parquet file or every Parquet file in a folder and concatenate them.

        :param path: Path to a ``.parquet`` file or to a dataset folder.
        :param include_subfolders: Also read files from nested (e.g. partition) folders.
        :return: One DataFrame with a fresh ``RangeIndex``.
        """
        files = self.list_files(path, include_subfolders=include_subfolders)
        if not files:
            raise FileNotFoundError(
                f"No '{self.PARQUET_SUFFIX}' files found in {path} (include_subfolders={include_subfolders})"
            )
        frames = [pd.read_parquet(file, engine=self.engine) for file in files]
        return pd.concat(frames, ignore_index=True)
