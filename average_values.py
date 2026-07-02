from __future__ import annotations

import csv
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - handled by the main app.
    pd = None


class AverageValuesManager:
    def __init__(self, app: tk.Tk, parent_frame: ttk.Frame) -> None:
        self.app = app
        self.parent_frame = parent_frame
        self.sheet = None
        self.toolbar = ttk.Frame(self.parent_frame, padding=(8, 6, 8, 4))
        self.toolbar.grid(row=0, column=0, sticky="ew")
        self.toolbar.columnconfigure(0, weight=1)
        self.toolbar.columnconfigure(1, weight=0)
        self.toolbar.columnconfigure(2, weight=0)

        self.content = ttk.Frame(self.parent_frame)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.placeholder = ttk.Label(
            self.content,
            text="Average Values will appear here after import.",
            anchor="center",
        )
        self.placeholder.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.data: list[list[str]] = []
        self.headers: list[str] = []
        self.context_menu: tk.Menu | None = None
        self.context_target: dict[str, int | None] = {"row": None, "column": None}
    def apply_zoom(self, table_size: int, row_height: int) -> None:
        if self.sheet is None:
            return

        self.sheet.set_options(
            font=("Segoe UI", table_size, "normal"),
            header_font=("Segoe UI", table_size, "bold"),
            index_font=("Segoe UI", table_size, "normal"),
            row_height=row_height,
            redraw=False,
        )
        self.sheet.set_all_row_heights(height=row_height, redraw=False)
        self._apply_visible_column_widths(redraw=True)

    def import_columns_from_main(
        self,
        data,
        column_refs: list[object],
        *,
        prepend: bool = False,
        select_tab: bool = False,
    ) -> None:
        if data is None or not column_refs:
            return

        resolved_columns = [self._resolve_column_ref(data, ref) for ref in column_refs]
        resolved_columns = [item for item in resolved_columns if item is not None]
        if not resolved_columns:
            return

        self._ensure_sheet()
        self._sync_cache_from_sheet()

        extracted_headers: list[str] = []
        extracted_columns: list[list[str]] = []
        for column_ref, series in resolved_columns:
            extracted_headers.append(str(self._header_name_for_ref(data, column_ref, series.name)))
            extracted_columns.append(self._extract_column_values(series))

        if not self.data:
            row_count = max((len(values) for values in extracted_columns), default=0)
            row_count = max(row_count, 1)
            self.data = [[""] * len(extracted_columns) for _ in range(row_count)]
            for column_offset, column_values in enumerate(extracted_columns):
                for row_index, value in enumerate(column_values):
                    self.data[row_index][column_offset] = value
            self.headers = extracted_headers[:]
        else:
            insertion_index = 0 if prepend else len(self.headers)
            for header, values in zip(extracted_headers, extracted_columns):
                self._insert_column(insertion_index, header, values)
                insertion_index += 1

        self._render(select_tab=select_tab)

    def import_frame_total_column(self, data, column_name: str, *, select_tab: bool = False) -> None:
        if data is None or not column_name or column_name not in data.columns:
            return

        self._ensure_sheet()
        self._sync_cache_from_sheet()

        resolved = self._resolve_column_ref(data, column_name)
        values = self._extract_column_values(resolved[1], drop_empty=True) if resolved is not None else []
        if not values:
            return

        display_name = self._normalize_frame_total_header(str(column_name))
        self._insert_compact_first_column(display_name, values)
        self._render(select_tab=select_tab)

    def render_placeholder(self, text: str) -> None:
        if self.sheet is not None:
            self._render_note(text)
            return

        self.placeholder.configure(text=text)

    def _ensure_sheet(self) -> None:
        if self.sheet is not None:
            return

        if self.placeholder.winfo_exists():
            self.placeholder.destroy()

        self.sheet = self.app._create_sheet(
            parent=self.content,
            bind_selection_sync=False,
            enable_editing=True,
            bind_app_shortcuts=False,
            use_custom_double_click=False,
        )
        self._bind_sheet_actions()
        self._build_context_menu()
        self.apply_zoom(max(7, round(9 * self.app.zoom_scale)), max(18, round(24 * self.app.zoom_scale)))
        self._render(select_tab=False)

    def _bind_sheet_actions(self) -> None:
        if self.sheet is None:
            return

        self.sheet.bind("<Double-Button-1>", self._on_double_click, add="+")
        self.sheet.bind("<Delete>", self._on_delete_key, add="+")
        self.sheet.bind("<BackSpace>", self._on_delete_key, add="+")
        self.sheet.bind("<Control-a>", self._on_select_all, add="+")
        self.sheet.bind("<Control-A>", self._on_select_all, add="+")
        self.sheet.bind("<Button-3>", self._on_right_click, add="+")
        self.sheet.bind("<Button-2>", self._on_right_click, add="+")
        self.sheet.bind("<Control-MouseWheel>", self.app._on_zoom_mousewheel)
        self.toolbar.columnconfigure(3, weight=0)

    def _build_context_menu(self) -> None:
        self.context_menu = tk.Menu(self.app, tearoff=0)
        self.context_menu.add_command(label="Add Row", command=self._menu_add_row)
        self.context_menu.add_command(label="Delete Row", command=self._menu_delete_row)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Add Column", command=self._menu_add_column)
        self.context_menu.add_command(label="Delete Column", command=self._menu_delete_column)

    def _sync_cache_from_sheet(self) -> None:
        if self.sheet is None:
            return

        try:
            sheet_data = self.sheet.get_sheet_data()
        except Exception:
            return

        if self._is_placeholder_data(sheet_data):
            return

        data = [list(row) for row in sheet_data]
        self._normalize_rows(data)
        self.data = data
        if self.data:
            if not self.headers or len(self.headers) != len(self.data[0]):
                self.headers = [f"Column {index + 1}" for index in range(len(self.data[0]))]
        else:
            self.headers = []

    def _render(self, select_tab: bool = False) -> None:
        if self.sheet is None:
            self.render_placeholder("Average Values will appear here after import.")
            return

        if self.data:
            data = [list(row) for row in self.data]
            headers = self.headers[:]
            if not headers:
                headers = [f"Column {index + 1}" for index in range(len(data[0]))]
                self.headers = headers[:]
        else:
            data = [["Load data first, then import values."]]
            headers = ["Note"]
            self.headers = headers[:]

        self._normalize_rows(data)
        column_count = max(len(row) for row in data)
        if len(headers) != column_count:
            headers = [headers[index] if index < len(headers) else f"Column {index + 1}" for index in range(column_count)]
            self.headers = headers[:]

        row_index = [str(index) for index in range(1, len(data) + 1)]
        self.sheet.set_sheet_data(
            data,
            reset_col_positions=True,
            reset_row_positions=True,
            reset_highlights=True,
        )
        self.sheet.headers(headers, reset_col_positions=False)
        self.sheet.row_index(row_index, reset_row_positions=False)
        self._apply_visible_column_widths(redraw=False)
        self.sheet.set_all_row_heights(height=max(18, round(24 * self.app.zoom_scale)), redraw=False)
        self.sheet.redraw()
        if select_tab:
            self.app.notebook.select(self.app.average_frame)
        if hasattr(self.app, "update_curve_plot"):
            self.app.update_curve_plot(self.data, self.headers)

    def _render_note(self, note: str) -> None:
        if self.sheet is None:
            self.render_placeholder(note)
            return

        self.sheet.set_sheet_data(
            [[note]],
            reset_col_positions=True,
            reset_row_positions=True,
            reset_highlights=True,
        )
        self.sheet.headers(["Note"], reset_col_positions=False)
        self.sheet.row_index(["1"], reset_row_positions=False)
        self._apply_visible_column_widths(redraw=False)
        self.sheet.set_all_row_heights(height=max(18, round(24 * self.app.zoom_scale)), redraw=False)
        self.sheet.redraw()

    def _extract_column_values(self, data, drop_empty: bool = False) -> list[str]:
        if hasattr(data, "tolist"):
            raw_values = data.tolist()
        else:
            raw_values = list(data)

        values = [self._format_cell(value) for value in raw_values]
        header_text = str(getattr(data, "name", "")).strip()
        while values and (not values[0].strip() or values[0].strip() == header_text):
            values.pop(0)
        if drop_empty:
            values = [value for value in values if value.strip()]
        return values

    def _resolve_column_ref(self, data, column_ref: object) -> tuple[object, object] | None:
        if data is None:
            return None

        try:
            if isinstance(column_ref, int):
                if column_ref < 0 or column_ref >= len(data.columns):
                    return None
                series = data.iloc[:, column_ref]
                return column_ref, series

            if isinstance(column_ref, str):
                matches = data.loc[:, column_ref]
                if hasattr(matches, "iloc") and getattr(matches, "ndim", 1) == 2:
                    series = matches.iloc[:, 0]
                else:
                    series = matches
                return column_ref, series
        except Exception:
            return None

        return None

    def _header_name_for_ref(self, data, column_ref: object, fallback: object) -> str:
        if isinstance(column_ref, int) and 0 <= column_ref < len(data.columns):
            return str(data.columns[column_ref])
        if isinstance(column_ref, str):
            return column_ref
        return str(fallback) if fallback is not None else "Column"

    def _insert_compact_first_column(self, header: str, values: list[str]) -> None:
        row_count = len(values)
        if row_count == 0:
            return

        if not self.data:
            self.data = [[] for _ in range(row_count)]
        elif len(self.data) < row_count:
            current_columns = self._column_count()
            for _ in range(row_count - len(self.data)):
                self.data.append([""] * current_columns)

        current_columns = self._column_count()
        for row_index in range(row_count):
            if len(self.data[row_index]) < current_columns:
                self.data[row_index].extend([""] * (current_columns - len(self.data[row_index])))
            self.data[row_index].insert(0, values[row_index])

        if not self.headers:
            self.headers = []
        self.headers.insert(0, header)

    def _insert_column(self, index: int, header: str, values: list[str]) -> None:
        row_count = max(len(self.data), len(values))
        if not self.data:
            self.data = [[""] for _ in range(row_count)]
        self._ensure_row_count(row_count)
        for row_index in range(row_count):
            value = values[row_index] if row_index < len(values) else ""
            self.data[row_index].insert(index, value)
        self.headers.insert(index, header)

    def _apply_visible_column_widths(self, redraw: bool = False) -> None:
        if self.sheet is None:
            return

        try:
            column_count = len(self.headers) if self.headers else 0
            widths = []
            for index in range(column_count):
                text_width = self.sheet.get_column_text_width(index, visible_only=True)
                widths.append(min(max(text_width + 18, 80), 360))
            if widths:
                self.sheet.set_column_widths(widths)
        except Exception:
            self.sheet.set_all_column_widths(width=None, redraw=False)

        if redraw:
            self.sheet.redraw()

    def _ensure_row_count(self, target_rows: int) -> None:
        if target_rows <= 0:
            self.data = []
            return

        if not self.data:
            self.data = [[""] * len(self.headers) for _ in range(target_rows)]
            return

        column_count = self._column_count()
        for row in self.data:
            if len(row) < column_count:
                row.extend([""] * (column_count - len(row)))
            elif len(row) > column_count:
                del row[column_count:]

        current_rows = len(self.data)
        if current_rows < target_rows:
            for _ in range(target_rows - current_rows):
                self.data.append([""] * column_count)
        elif current_rows > target_rows:
            del self.data[target_rows:]

    def _normalize_rows(self, rows: list[list[str]]) -> None:
        if not rows:
            return

        column_count = max(len(row) for row in rows)
        for row in rows:
            if len(row) < column_count:
                row.extend([""] * (column_count - len(row)))
            elif len(row) > column_count:
                del row[column_count:]

    def _column_count(self) -> int:
        if self.data:
            return max(len(row) for row in self.data)
        return len(self.headers)

    def _is_placeholder_data(self, rows: list[list[str]]) -> bool:
        if len(rows) != 1 or not rows[0]:
            return False
        text = str(rows[0][0]).strip().lower()
        return text.startswith("average values will appear here") or text.startswith("load data first")

    def _average_selection(self) -> tuple[list[int], list[int]]:
        if self.sheet is None:
            return [], []

        try:
            selected_columns = sorted(
                index for index in self.sheet.get_selected_columns() if isinstance(index, int) and index >= 0
            )
        except Exception:
            selected_columns = []

        try:
            selected_rows = sorted(
                index for index in self.sheet.get_selected_rows() if isinstance(index, int) and index >= 0
            )
        except Exception:
            selected_rows = []

        return selected_columns, selected_rows

    def _on_right_click(self, event: tk.Event) -> str:
        if self.sheet is None or self.context_menu is None:
            return "break"

        row = self.sheet.identify_row(event)
        column = self.sheet.identify_column(event)
        self.context_target = {"row": row, "column": column}

        try:
            region = self.sheet.identify_region(event)
            if region == "header" and column is not None:
                self.sheet.select_column(column, redraw=False)
            elif region == "index" and row is not None:
                self.sheet.select_row(row, redraw=False)
            elif region == "table" and row is not None and column is not None:
                self.sheet.select_cell(row, column, redraw=False)
            self.sheet.redraw()
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
        return "break"

    def _context_column_index(self) -> int | None:
        selected_columns, _ = self._average_selection()
        if selected_columns:
            return selected_columns[-1]
        return self.context_target.get("column")

    def _context_row_index(self) -> int | None:
        _, selected_rows = self._average_selection()
        if selected_rows:
            return selected_rows[-1]
        return self.context_target.get("row")

    def _menu_add_column(self) -> None:
        if self.sheet is None:
            return

        self._sync_cache_from_sheet()
        insert_at = self._context_column_index()
        if insert_at is None:
            insert_at = self._column_count() - 1
        insert_at = max(insert_at + 1, 0)

        row_count = len(self.data)
        if row_count == 0:
            self.data = [[""]]
            self.headers = ["Column 1"]
            self._render(select_tab=True)
            return

        header = self._next_column_name()
        self._insert_column(insert_at, header, [""] * row_count)
        self._render(select_tab=True)

    def _menu_delete_column(self) -> None:
        if self.sheet is None:
            return

        self._sync_cache_from_sheet()
        selected_columns, _ = self._average_selection()
        if not selected_columns:
            column_index = self._context_column_index()
            if column_index is None:
                return
            selected_columns = [column_index]

        selected_columns = sorted(set(index for index in selected_columns if 0 <= index < self._column_count()))
        if not selected_columns:
            return

        for column_index in reversed(selected_columns):
            for row in self.data:
                if column_index < len(row):
                    del row[column_index]
            if column_index < len(self.headers):
                del self.headers[column_index]

        self._render(select_tab=True)

    def _menu_add_row(self) -> None:
        if self.sheet is None:
            return

        self._sync_cache_from_sheet()
        row_index = self._context_row_index()
        insert_at = len(self.data) if row_index is None else max(row_index + 1, 0)
        column_count = self._column_count()
        if column_count == 0:
            column_count = max(len(self.headers), 1)
            if not self.headers:
                self.headers = [self._next_column_name()]
        self.data.insert(insert_at, [""] * column_count)
        self._render(select_tab=True)

    def _menu_delete_row(self) -> None:
        if self.sheet is None:
            return

        self._sync_cache_from_sheet()
        _, selected_rows = self._average_selection()
        if not selected_rows:
            row_index = self._context_row_index()
            if row_index is None:
                return
            selected_rows = [row_index]

        selected_rows = sorted(set(index for index in selected_rows if 0 <= index < len(self.data)))
        if not selected_rows:
            return

        for row_index in reversed(selected_rows):
            del self.data[row_index]

        self._render(select_tab=True)

    def _next_column_name(self) -> str:
        existing = set(self.headers)
        suffix = 1
        while True:
            candidate = "New Column" if suffix == 1 else f"New Column {suffix}"
            if candidate not in existing:
                return candidate
            suffix += 1

    def _on_double_click(self, event: tk.Event) -> str | None:
        if self.sheet is None:
            return None

        if self.sheet.identify_region(event) != "table":
            return None

        row = self.sheet.identify_row(event)
        column = self.sheet.identify_column(event)
        if row is None or column is None:
            return None

        try:
            self.sheet.select_cell(row, column, redraw=False)
            self.sheet.redraw()
            self.sheet.open_cell()
        except Exception:
            pass
        return "break"

    def _on_delete_key(self, event: tk.Event) -> str:
        if self.sheet is None:
            return "break"

        try:
            self.sheet.delete(event)
        except Exception:
            try:
                self.sheet.clear()
            except Exception:
                pass
        self._sync_cache_from_sheet()
        self._render(select_tab=False)
        return "break"

    def _on_select_all(self, event: tk.Event) -> str:
        if self.sheet is None:
            return "break"

        try:
            self.sheet.select_all()
        except Exception:
            pass
        return "break"

    def _format_cell(self, value: object) -> str:
        if pd is not None and pd.isna(value):
            return ""
        return str(value)

    def export_data(self) -> None:
        if not self.data:
            messagebox.showinfo("No Data", "There is no Average Values data to export.")
            return

        file_name = filedialog.asksaveasfilename(
            title="Export Average Values",
            defaultextension=".csv",
            filetypes=[
                ("CSV files", "*.csv"),
                ("Excel files", "*.xlsx *.xls"),
                ("All files", "*.*"),
            ],
        )
        if not file_name:
            return

        path = Path(file_name)
        try:
            if path.suffix.lower() in {".xlsx", ".xls"}:
                self._export_excel(path)
            else:
                self._export_csv(path)
        except Exception as exc:
            messagebox.showerror("Export Failed", f"Unable to export data:\n{exc}")
            return

        messagebox.showinfo("Export Complete", f"Average Values exported to:\n{path}")

    def _export_csv(self, path: Path) -> None:
        normalized = self._export_rows()
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(self._export_headers())
            writer.writerows(normalized)

    def _export_excel(self, path: Path) -> None:
        if pd is None:
            raise RuntimeError("pandas is required to export Excel files.")

        df = pd.DataFrame(self._export_rows(), columns=self._export_headers())
        df.to_excel(path, index=False)

    def _export_rows(self) -> list[list[str]]:
        if not self.data:
            return []

        headers = self._export_headers()
        row_count = len(self.data)
        column_count = len(headers)
        rows: list[list[str]] = []
        for row in self.data[:row_count]:
            current = list(row[:column_count])
            if len(current) < column_count:
                current.extend([""] * (column_count - len(current)))
            rows.append(current)
        return rows

    def _export_headers(self) -> list[str]:
        if self.headers:
            return self.headers[:]
        if self.data and self.data[0]:
            return [f"Column {index + 1}" for index in range(len(self.data[0]))]
        return ["Column 1"]

    def _normalize_frame_total_header(self, header: str) -> str:
        normalized = header.strip()
        if normalized == "Unique_Frame_Total_Time_s":
            return "Experiment Time [s]"
        return normalized
