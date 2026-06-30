from __future__ import annotations

import re
from dataclasses import dataclass

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - handled by the main app.
    pd = None


@dataclass(frozen=True)
class FrameTotalTimeColumn:
    column_name: str
    values: list[int | float | str]
    invalid_rows: int
    note: str


def build_unique_frame_total_time_column(
    data,
    image_column_index: int,
    measuring_time_column_index: int,
    existing_names: set[str] | None = None,
) -> FrameTotalTimeColumn:
    if pd is None:
        raise RuntimeError("Missing pandas dependency. Run: pip install -r requirements.txt")

    image_series = data.iloc[:, image_column_index].map(extract_frame_index)
    measuring_time_series = pd.to_numeric(data.iloc[:, measuring_time_column_index], errors="coerce")
    working = pd.DataFrame(
        {
            "frame": image_series,
            "measuring_time": measuring_time_series,
        }
    ).dropna(subset=["frame", "measuring_time"])

    if working.empty:
        raise ValueError("The Image and Measuring time [s] columns do not contain usable frame data.")

    frame_max_times = (
        working.groupby("frame", sort=True)["measuring_time"]
        .max()
        .astype(float)
        .to_dict()
    )
    if not frame_max_times:
        raise ValueError("No grouped frame time values were generated.")

    unique_times: list[int | float] = []
    seen_times: set[int | float] = set()
    for frame_key in sorted(frame_max_times):
        time_value = format_frame_time_value(frame_max_times[frame_key])
        if time_value in seen_times:
            continue
        seen_times.add(time_value)
        unique_times.append(time_value)

    generated_values: list[int | float | str] = unique_times + [""] * max(len(data) - len(unique_times), 0)
    invalid_rows = int(image_series.isna().sum())
    column_name = next_unique_frame_total_time_column_name(existing_names or set())
    note = (
        "Inserted '"
        f"{column_name}' using grouped maxima from 'Measuring time [s]' by Frame number, "
        "deduped to a unique list."
    )
    if invalid_rows:
        note += f" {invalid_rows} rows could not be parsed."
    return FrameTotalTimeColumn(column_name, generated_values, invalid_rows, note)


def next_unique_frame_total_time_column_name(existing_names: set[str]) -> str:
    base_name = "Unique_Frame_Total_Time_s"
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
    if float(value).is_integer():
        return int(value)
    return round(value, 3)
