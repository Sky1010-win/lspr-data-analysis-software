from __future__ import annotations

import re
from dataclasses import dataclass

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - handled by the main app.
    pd = None


@dataclass(frozen=True)
class FrameTotalTimeColumn:
    column_names: list[str]
    values_list: list[list[int | float | str]]
    invalid_rows: int
    note: str


def build_unique_frame_total_time_column(
    data,
    image_column_index: int,
    measuring_time_column_index: int,
    existing_names: set[str] | None = None,
    selected_column_indexes: list[int] | None = None,
) -> FrameTotalTimeColumn:
    if pd is None:
        raise RuntimeError("Missing pandas dependency. Run: pip install -r requirements.txt")

    selected_column_indexes = sorted({int(index) for index in (selected_column_indexes or []) if isinstance(index, int)})
    if selected_column_indexes:
        image_column_index = _prefer_selected_column(
            data,
            selected_column_indexes,
            image_column_index,
            {"image"},
        )
        measuring_time_column_index = _prefer_selected_column(
            data,
            selected_column_indexes,
            measuring_time_column_index,
            {"measuring time [s]", "measuring time", "time [s]", "time"},
        )
        note_column_index = _prefer_selected_column(
            data,
            selected_column_indexes,
            -1,
            {"note pump plan", "pump plan", "note", "list", "stage"},
        )
    else:
        note_column_index = -1

    image_series = data.iloc[:, image_column_index].map(extract_frame_index)
    measuring_time_series = pd.to_numeric(data.iloc[:, measuring_time_column_index], errors="coerce")
    measuring_time_header = str(data.columns[measuring_time_column_index]).strip().lower()
    convert_ms_to_seconds = "ms" in measuring_time_header and "[s]" not in measuring_time_header
    note_series = data.iloc[:, note_column_index].astype(str).str.strip() if note_column_index >= 0 else pd.Series([""] * len(data))
    working = pd.DataFrame(
        {
            "frame": image_series,
            "measuring_time": measuring_time_series,
            "stage_name": note_series,
        }
    ).dropna(subset=["frame", "measuring_time"])

    if working.empty:
        raise ValueError("The Image and Measuring time [s] columns do not contain usable frame data.")

    frame_summary = (
        working.groupby("frame", sort=True)
        .agg(
            measuring_time=("measuring_time", "max"),
            stage_name=("stage_name", _first_meaningful_stage_name),
        )
    )
    if frame_summary.empty:
        raise ValueError("No grouped frame time values were generated.")

    unique_times: list[int | float] = []
    unique_stages: list[str] = []
    seen_times: set[int | float] = set()
    for frame_key, row in frame_summary.sort_index().iterrows():
        stage_name = str(row["stage_name"]).strip()
        if _is_ignored_stage_name(stage_name):
            continue
        raw_time = float(row["measuring_time"])
        if convert_ms_to_seconds:
            raw_time = raw_time / 1000.0
        time_value = format_frame_time_value(raw_time)
        if time_value in seen_times:
            continue
        seen_times.add(time_value)
        unique_times.append(time_value)
        unique_stages.append(stage_name)

    generated_time_values: list[int | float | str] = unique_times + [""] * max(len(data) - len(unique_times), 0)
    generated_stage_values: list[str] = unique_stages + [""] * max(len(data) - len(unique_stages), 0)
    invalid_rows = int(image_series.isna().sum())
    time_column_name = next_unique_frame_total_time_column_name(existing_names or set())
    stage_column_name = next_unique_frame_stage_name_column_name(existing_names or set())
    selected_note = " using the selected columns" if selected_column_indexes else ""
    note = (
        "Inserted '"
        f"{time_column_name}' and '{stage_column_name}'{selected_note} with grouped maxima from time values by Frame number, "
        "deduped to a unique list."
    )
    if invalid_rows:
        note += f" {invalid_rows} rows could not be parsed."
    return FrameTotalTimeColumn([time_column_name, stage_column_name], [generated_time_values, generated_stage_values], invalid_rows, note)


def _prefer_selected_column(data, selected_indexes: list[int], fallback_index: int, keywords: set[str]) -> int:
    normalized_keywords = {keyword.strip().lower() for keyword in keywords}
    for index in selected_indexes:
        if 0 <= index < len(data.columns):
            header = str(data.columns[index]).strip().lower()
            if header in normalized_keywords or any(keyword in header for keyword in normalized_keywords):
                return index
    return fallback_index


def _first_non_empty(series) -> str:
    for value in series:
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return ""


def _first_meaningful_stage_name(series) -> str:
    fallback = ""
    for value in series:
        text = str(value).strip()
        if not text or text.lower() == "nan":
            continue
        if fallback == "":
            fallback = text
        if not _is_ignored_stage_name(text):
            return text
    return fallback


def _is_ignored_stage_name(value: str) -> bool:
    return value.strip().lower() in {"pump is not running", "pump is not working"}


def next_unique_frame_total_time_column_name(existing_names: set[str]) -> str:
    base_name = "Unique_Frame_Total_Time_s"
    if base_name not in existing_names:
        return base_name

    suffix = 2
    while f"{base_name} {suffix}" in existing_names:
        suffix += 1
    return f"{base_name} {suffix}"


def next_unique_frame_stage_name_column_name(existing_names: set[str]) -> str:
    base_name = "Frame_PumpPlan"
    if base_name not in existing_names:
        return base_name

    suffix = 2
    while f"{base_name} {suffix}" in existing_names:
        suffix += 1
    return f"{base_name} {suffix}"


def find_image_column_index(data) -> int | None:
    if data is None:
        return None

    for index, column in enumerate(data.columns):
        if str(column).strip().lower() == "image":
            return index

    for index, column in enumerate(data.columns):
        if "image" in str(column).strip().lower():
            return index

    return None


def find_measuring_time_column_index(data) -> int | None:
    if data is None:
        return None

    for index, column in enumerate(data.columns):
        normalized = str(column).strip().lower()
        if normalized == "measuring time [ms]":
            return index

    for index, column in enumerate(data.columns):
        if str(column).strip().lower() == "measuring time [s]":
            return index

    for index, column in enumerate(data.columns):
        lowered = str(column).strip().lower()
        if "measuring time" in lowered and "[s]" in lowered:
            return index

    return None


def extract_frame_index(value) -> int | None:
    match = re.search(r"frame(\d+)", str(value), flags=re.IGNORECASE)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def format_frame_time_value(value: float) -> int | float:
    return round(float(value), 1)
