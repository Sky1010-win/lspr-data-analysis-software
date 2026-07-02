from __future__ import annotations

import csv
import re
from pathlib import Path

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - handled by the main app.
    pd = None


AUTO_SPLIT_DELIMITERS = [",", ";", "\t", "|"]
AUTO_SPLIT_MIN_RATIO = 0.6


def read_and_prepare_data(path: Path):
    if pd is None:
        raise RuntimeError("Missing pandas dependency. Run: pip install -r requirements.txt")

    load_note = ""
    source_data_rows: int | None = None
    suffix = path.suffix.lower()

    if suffix == ".csv":
        data, load_note, source_data_rows = read_csv_file(path)
    elif suffix in {".xlsx", ".xls"}:
        data = pd.read_excel(path)
    else:
        raise ValueError("Only CSV, XLSX, and XLS files are supported.")

    data, load_note = auto_split_single_column(data, load_note)
    data = clean_column_names(data)
    return data, load_note, source_data_rows


def read_csv_file(path: Path):
    if pd is None:
        raise RuntimeError("Missing pandas dependency. Run: pip install -r requirements.txt")

    load_note = ""
    sample_lines = read_text_sample(path)
    read_kwargs = infer_csv_read_kwargs(sample_lines)

    last_error = None
    attempts = [read_kwargs, {"sep": None, "engine": "python"}, {"sep": ",", "engine": "python"}]
    for options in attempts:
        try:
            data = pd.read_csv(path, **options)
            return data, load_note, len(data)
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Unable to read CSV file. Last error: {last_error}")


def read_text_sample(path: Path, max_lines: int = 200) -> list[str]:
    lines: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "gbk", "latin1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                for _ in range(max_lines):
                    line = handle.readline()
                    if not line:
                        break
                    lines.append(line.rstrip("\r\n"))
            return lines
        except UnicodeDecodeError:
            lines.clear()
            continue

    with path.open("r", errors="replace", newline="") as handle:
        for _ in range(max_lines):
            line = handle.readline()
            if not line:
                break
            lines.append(line.rstrip("\r\n"))
    return lines


def infer_csv_read_kwargs(sample_lines: list[str]) -> dict[str, object]:
    non_empty_lines = [line for line in sample_lines if line.strip()]
    sample_text = "\n".join(non_empty_lines[:50])
    if not sample_text:
        return {"sep": None, "engine": "python"}

    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=AUTO_SPLIT_DELIMITERS)
        delimiter = dialect.delimiter
        if delimiter == "\t":
            return {"sep": "\t", "engine": "python"}
        if delimiter in AUTO_SPLIT_DELIMITERS:
            return {"sep": delimiter, "engine": "python" if delimiter in {";", "|"} else "c"}
    except csv.Error:
        pass

    delimiter = detect_split_rule(non_empty_lines[:50])
    if delimiter is not None:
        return {"sep": delimiter[0] if delimiter[0] != "whitespace" else r"\s+", "engine": "python"}

    return {"sep": None, "engine": "python"}


def auto_split_single_column(data, existing_note: str = ""):
    if pd is None:
        raise RuntimeError("Missing pandas dependency. Run: pip install -r requirements.txt")

    if data.shape[1] != 1:
        return data, existing_note

    column_name = str(data.columns[0])
    values = data.iloc[:, 0].dropna().astype(str)
    sample = [column_name, *values.head(200).tolist()]
    split_rule = detect_split_rule(sample)
    if split_rule is None:
        return data, existing_note

    delimiter, expected_columns = split_rule
    parsed_rows = [
        split_cell(value, delimiter, expected_columns)
        for value in data.iloc[:, 0].map(str)
    ]

    header_values = split_cell(column_name, delimiter, expected_columns)
    if len(header_values) == expected_columns and len(set(header_values)) == expected_columns:
        columns = [value.strip() for value in header_values]
    else:
        columns = [""] * expected_columns

    split_note = (
        f"Auto-split one-column data into {expected_columns} columns "
        f"using {delimiter_label(delimiter)}."
    )
    load_note = f"{existing_note}\n{split_note}" if existing_note else split_note
    return pd.DataFrame(parsed_rows, columns=columns), load_note


def clean_column_names(data):
    if pd is None:
        raise RuntimeError("Missing pandas dependency. Run: pip install -r requirements.txt")

    cleaned_columns = []
    for column in data.columns:
        column_name = "" if column is None else str(column).strip()
        if re.fullmatch(r"Unnamed:\s*\d+(?:_level_\d+)?", column_name):
            column_name = ""
        cleaned_columns.append(column_name)

    data.columns = cleaned_columns
    return data


def detect_split_rule(sample: list[str]) -> tuple[str, int] | None:
    best_rule = None
    best_score = 0

    for delimiter in AUTO_SPLIT_DELIMITERS:
        counts = [len(split_cell(value, delimiter)) for value in sample if delimiter in value]
        rule = score_split_counts(delimiter, counts, len(sample))
        if rule and rule[2] > best_score:
            best_rule = (rule[0], rule[1])
            best_score = rule[2]

    if best_rule is not None:
        return best_rule

    whitespace_counts = [
        len(re.split(r"\s+", value.strip()))
        for value in sample
        if re.search(r"\s{2,}|\t", value.strip())
    ]
    rule = score_split_counts("whitespace", whitespace_counts, len(sample))
    if rule:
        return rule[0], rule[1]

    return None


def score_split_counts(
    delimiter: str, counts: list[int], sample_size: int
) -> tuple[str, int, int] | None:
    valid_counts = [count for count in counts if count > 1]
    if not valid_counts:
        return None

    expected_columns = max(valid_counts)
    split_ratio = len(valid_counts) / max(sample_size, 1)
    if sample_size > 3 and split_ratio < AUTO_SPLIT_MIN_RATIO:
        return None

    return delimiter, expected_columns, len(valid_counts) * expected_columns


def split_cell(value: str, delimiter: str, expected_columns: int | None = None) -> list[str]:
    text = str(value)
    if delimiter == "whitespace":
        parts = re.split(r"\s+", text.strip()) if text.strip() else [""]
    else:
        parts = next(csv.reader([text], delimiter=delimiter))

    cleaned_parts = [part.strip() for part in parts]
    if expected_columns is None:
        return cleaned_parts

    if len(cleaned_parts) < expected_columns:
        return [*cleaned_parts, *([""] * (expected_columns - len(cleaned_parts)))]
    return cleaned_parts


def delimiter_label(delimiter: str) -> str:
    labels = {
        ",": "comma delimiter",
        ";": "semicolon delimiter",
        "\t": "tab delimiter",
        "|": "pipe delimiter",
        "whitespace": "whitespace delimiter",
    }
    return labels.get(delimiter, f"{delimiter!r} delimiter")
