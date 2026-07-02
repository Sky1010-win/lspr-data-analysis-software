from __future__ import annotations

import importlib
import subprocess
import sys
import tkinter as tk
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from tkinter import font
from tkinter import filedialog, messagebox, ttk

try:
    import pandas as pd
except ModuleNotFoundError:
    pd = None

try:
    from tksheet import Sheet
except ModuleNotFoundError:
    Sheet = None

import data_utils
from average_values import AverageValuesManager
from chart_window import AverageValuesChartPanel
import frame_tools


VIRTUAL_VIEW_ROWS = 200
ZOOM_MIN = 0.5
ZOOM_MAX = 2.0
ZOOM_STEP = 0.1
UNDO_LIMIT = 50


class DataAnalysisApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LSPR Data Analysis Software")
        self.geometry("980x680")
        self.minsize(820, 560)

        self.data = None
        self.current_file: Path | None = None
        self.load_note = ""
        self.source_data_rows: int | None = None
        self.selected_columns: set[int] = set()
        self.selected_rows: set[int] = set()
        self.average_columns: set[int] = set()
        self.drag_mode: str | None = None
        self.drag_anchor: int | None = None
        self.undo_stack: list[dict] = []
        self.table_offset = 0
        self.full_render_mode = False
        self.zoom_scale = 1.0
        self.average_editable_cell: tuple[int, int] | None = None
        self.last_frame_total_column_name: str | None = None
        self.average_values_data: list[list[str]] = []
        self.average_values_headers: list[str] = []
        self.average_sheet_context_menu: tk.Menu | None = None
        self.average_sheet_context_target: dict[str, int | None] = {"row": None, "column": None}
        self.average_values_manager: AverageValuesManager | None = None
        self.average_sheet = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(12, 12, 12, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(10, weight=1)

        ttk.Button(toolbar, text="Load Data", command=self.load_data).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(toolbar, text="Auto Analyze", command=self.analyze_data).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Button(
            toolbar,
            text="Average Selected Columns",
            command=self.average_selected_columns,
        ).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(
            toolbar,
            text="Import to Average Values",
            command=self.import_average_values,
        ).grid(row=1, column=2, padx=(0, 8), pady=(4, 0))
        ttk.Button(toolbar, text="Frame Total Time", command=self.generate_frame_time_column).grid(
            row=0, column=3, padx=(0, 8)
        )
        ttk.Button(
            toolbar,
            text="Import Frame Total",
            command=self.import_frame_total_to_average_values,
        ).grid(row=1, column=3, padx=(0, 8), pady=(4, 0))
        ttk.Button(
            toolbar,
            text="Export Average Values",
            command=self.export_average_values,
        ).grid(row=1, column=4, padx=(0, 8), pady=(4, 0))
        ttk.Button(
            toolbar,
            text="Plot Curves",
            command=self.show_curve_plot_tab,
        ).grid(row=1, column=5, padx=(0, 8), pady=(4, 0))
        ttk.Button(toolbar, text="Undo", command=self.undo_last_action).grid(
            row=0, column=4, padx=(0, 8)
        )
        ttk.Button(toolbar, text="Install Dependencies", command=self.install_dependencies).grid(
            row=0, column=5, padx=(0, 12)
        )
        ttk.Button(toolbar, text="Zoom -", command=lambda: self._change_zoom(-ZOOM_STEP)).grid(
            row=0, column=6, padx=(0, 6)
        )
        self.zoom_label = ttk.Label(toolbar, text="100%")
        self.zoom_label.grid(row=0, column=7, padx=(0, 6))
        ttk.Button(toolbar, text="Zoom +", command=lambda: self._change_zoom(ZOOM_STEP)).grid(
            row=0, column=8, padx=(0, 6)
        )
        ttk.Button(toolbar, text="Reset Zoom", command=self._reset_zoom).grid(
            row=0, column=9, padx=(0, 12)
        )

        self.file_label = ttk.Label(toolbar, text="No data loaded")
        self.file_label.grid(row=0, column=10, sticky="w")

        content = ttk.Frame(self, padding=(12, 0, 12, 12))
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(content)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.table_frame = ttk.Frame(self.notebook)
        self.average_frame = ttk.Frame(self.notebook)
        self.plot_frame = ttk.Frame(self.notebook)
        self.report_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.table_frame, text="Data Table")
        self.notebook.add(self.average_frame, text="Average Values")
        self.notebook.add(self.plot_frame, text="Curve Plot")
        self.notebook.add(self.report_frame, text="Report")

        self.table_frame.columnconfigure(0, weight=1)
        self.table_frame.rowconfigure(0, weight=1)
        self.average_frame.columnconfigure(0, weight=1)
        self.average_frame.rowconfigure(0, weight=0)
        self.average_frame.rowconfigure(1, weight=1)
        self.plot_frame.columnconfigure(0, weight=1)
        self.plot_frame.rowconfigure(0, weight=1)
        self.report_frame.columnconfigure(0, weight=1)
        self.report_frame.rowconfigure(0, weight=1)

        self.style = ttk.Style(self)
        self.report_font = font.Font(family="Consolas", size=10)
        self.sheet = self._create_sheet()
        self.average_values_manager = AverageValuesManager(self, self.average_frame)
        self.plot_panel = AverageValuesChartPanel(self.plot_frame, refresh_callback=self.update_curve_plot)
        self.plot_panel.grid(row=0, column=0, sticky="nsew")

        self.output = tk.Text(self.report_frame, wrap="none", font=self.report_font)
        self.output.grid(row=0, column=0, sticky="nsew")
        self.output.bind("<Control-MouseWheel>", self._on_zoom_mousewheel)
        self.output.bind("<Control-z>", lambda event: self._undo_from_event())
        self.output.bind("<Control-Z>", lambda event: self._undo_from_event())

        report_y_scroll = ttk.Scrollbar(
            self.report_frame, orient="vertical", command=self.output.yview
        )
        report_y_scroll.grid(row=0, column=1, sticky="ns")

        report_x_scroll = ttk.Scrollbar(
            self.report_frame, orient="horizontal", command=self.output.xview
        )
        report_x_scroll.grid(row=1, column=0, sticky="ew")

        self.output.configure(
            yscrollcommand=report_y_scroll.set,
            xscrollcommand=report_x_scroll.set,
        )
        self._apply_zoom()
        self._write_output("Click \"Load Data\" to select a CSV or Excel file.\n")
        self.notebook.select(self.report_frame)

    def load_data(self) -> None:
        if not self._ensure_dependencies():
            return

        file_path = filedialog.askopenfilename(
            title="Select Data File",
            filetypes=[
                ("Data files", "*.csv *.xlsx *.xls"),
                ("CSV files", "*.csv"),
                ("Excel files", "*.xlsx *.xls"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            self.data = self._read_file(path)
        except Exception as exc:
            messagebox.showerror("Load Failed", f"Unable to load file:\n{exc}")
            return

        self.current_file = path
        self.undo_stack.clear()
        self.average_columns.clear()
        self.average_editable_cell = None
        self.last_frame_total_column_name = None
        self.file_label.configure(text=f"Current file: {path.name}")
        self._show_data_table()

    def analyze_data(self) -> None:
        if not self._ensure_dependencies():
            return

        if self.data is None:
            messagebox.showwarning("No Data", "Please click \"Load Data\" first.")
            return

        df = self.data
        lines: list[str] = []
        lines.append("Auto Analysis Result")
        lines.append("=" * 80)
        lines.append(f"File name: {self.current_file.name if self.current_file else 'Unknown'}")
        lines.append(f"Data size: {df.shape[0]} rows x {df.shape[1]} columns")
        lines.append(f"Duplicate rows: {df.duplicated().sum()}")
        lines.append("")

        lines.append("Column Types")
        lines.append("-" * 80)
        lines.append(df.dtypes.astype(str).to_string())
        lines.append("")

        missing = df.isna().sum()
        missing_rate = (df.isna().mean() * 100).round(2)
        missing_report = pd.DataFrame(
            {"Missing Count": missing, "Missing Rate (%)": missing_rate}
        )
        lines.append("Missing Value Analysis")
        lines.append("-" * 80)
        lines.append(missing_report.to_string())
        lines.append("")

        numeric_df = df.select_dtypes(include="number")
        if not numeric_df.empty:
            lines.append("Numeric Column Statistics")
            lines.append("-" * 80)
            lines.append(numeric_df.describe().round(4).to_string())
            lines.append("")

            if numeric_df.shape[1] >= 2:
                lines.append("Numeric Column Correlation Matrix")
                lines.append("-" * 80)
                lines.append(numeric_df.corr().round(4).to_string())
                lines.append("")
        else:
            lines.append("No numeric columns detected.")
            lines.append("")

        categorical_df = df.select_dtypes(exclude="number")
        if not categorical_df.empty:
            lines.append("Text/Categorical Column Top 5 Values")
            lines.append("-" * 80)
            for column in categorical_df.columns:
                lines.append(f"[{column}]")
                lines.append(categorical_df[column].value_counts(dropna=False).head(5).to_string())
                lines.append("")

        self._write_output("\n".join(lines))
        self.notebook.select(self.report_frame)

    def average_selected_columns(self) -> None:
        if not self._ensure_dependencies():
            return

        if self.data is None:
            messagebox.showwarning("No Data", "Please click \"Load Data\" first.")
            return

        self._commit_average_column_name_edit()
        self._sync_sheet_selection()
        if not self.selected_columns:
            messagebox.showwarning(
                "No Columns Selected",
                "Click one or more column headers in the Data Table tab first.",
            )
            return

        selected_indexes = sorted(
            index for index in self.selected_columns if 0 <= index < len(self.data.columns)
        )
        if not selected_indexes:
            messagebox.showwarning("No Columns Selected", "The selected columns are no longer valid.")
            self.selected_columns.clear()
            self._apply_sheet_highlights()
            return

        selected_data = self.data.iloc[:, selected_indexes].apply(pd.to_numeric, errors="coerce")
        averages = selected_data.mean(axis=1, skipna=True)
        if averages.isna().all():
            messagebox.showwarning(
                "No Numeric Data",
                "The selected columns do not contain numeric values.",
            )
            return

        insert_at = max(selected_indexes) + 1
        column_name = self._next_average_column_name()
        self._save_undo_snapshot()
        formatted_averages = averages.map(self._format_decimal_places).tolist()
        self.data.insert(
            insert_at,
            column_name,
            formatted_averages,
            allow_duplicates=True,
        )
        self.average_columns = {index + 1 if index >= insert_at else index for index in self.average_columns}
        self.average_columns.add(insert_at)
        self.average_editable_cell = (0, insert_at)
        self.load_note = (
            f"Inserted '{column_name}' at column {insert_at + 1} from "
            f"{len(selected_indexes)} selected columns. Values are rounded to 3 decimal places."
        )
        self._show_data_table(keep_selection=True)
        self._activate_average_first_cell(insert_at)
        self._write_output(
            "\n".join(
                [
                    "Average Column Generated",
                    "=" * 80,
                    self.load_note,
                ]
            )
        )

    def import_average_values(self) -> None:
        if not self._ensure_dependencies():
            return

        if self.data is None:
            messagebox.showwarning("No Data", "Please click \"Load Data\" first.")
            return

        self._commit_average_column_name_edit()
        if self.average_values_manager is not None:
            self._sync_sheet_selection()
            selected_indexes = self._current_selected_column_indexes()
            if selected_indexes:
                self.average_values_manager.import_columns_from_main(
                    self.data,
                    selected_indexes,
                    prepend=False,
                    select_tab=True,
                )
                return

            if not self.average_columns:
                messagebox.showinfo(
                    "No Columns Selected",
                    "Select one or more columns in the Data Table first, or generate average columns first.",
                )
                return

            average_indexes = sorted(
                index for index in self.average_columns if 0 <= index < len(self.data.columns)
            )
            if not average_indexes:
                messagebox.showinfo(
                    "No Average Columns",
                    "Please calculate average columns in the Data Table first.",
                )
                return

            self.average_values_manager.import_columns_from_main(
                self.data,
                average_indexes,
                prepend=False,
                select_tab=True,
            )

    def _current_selected_column_indexes(self) -> list[int]:
        if self.data is None:
            return []

        current: set[int] = set()
        if self.sheet is not None:
            try:
                selected_columns = self.sheet.MT.get_selected_cols() if hasattr(self.sheet, "MT") else self.sheet.get_selected_columns()
                current |= {
                    data_index
                    for index in selected_columns
                    if isinstance(index, int)
                    for data_index in [self._sheet_column_to_data_index(index)]
                    if data_index is not None
                }
            except Exception:
                pass

            if not current:
                try:
                    selected_cells = self.sheet.MT.get_selected_cells(get_cols=True) if hasattr(self.sheet, "MT") else self.sheet.get_selected_cells(get_cols=True)
                    current |= {
                        data_index
                        for _, column in selected_cells
                        if isinstance(column, int)
                        for data_index in [self._sheet_column_to_data_index(column)]
                        if data_index is not None
                    }
                except Exception:
                    pass

            if not current:
                try:
                    selection_items = self.sheet.MT.get_selection_items(cells=False, rows=False, columns=True) if hasattr(self.sheet, "MT") else ()
                    for _, box in selection_items:
                        for sheet_column in range(box.coords.from_c, box.coords.upto_c):
                            data_index = self._sheet_column_to_data_index(sheet_column)
                            if data_index is not None:
                                current.add(data_index)
                except Exception:
                    pass

        if not current:
            current = set(self.selected_columns)

        return sorted(index for index in current if 0 <= index < len(self.data.columns))

    def _sheet_column_to_data_index(self, sheet_column: int) -> int | None:
        if sheet_column < 0:
            return None
        data_index = sheet_column
        if self.data is None or not (0 <= data_index < len(self.data.columns)):
            return None
        return data_index

    def import_frame_total_to_average_values(self) -> None:
        if not self._ensure_dependencies():
            return

        if self.data is None:
            messagebox.showwarning("No Data", "Please click \"Load Data\" first.")
            return

        column_name = self.last_frame_total_column_name
        if not column_name or column_name not in self.data.columns:
            candidates = [str(column) for column in self.data.columns if str(column).startswith("Unique_Frame_Total_Time_s")]
            if not candidates:
                messagebox.showinfo(
                    "No Frame Total Column",
                    "Please generate the Frame Total Time column first.",
                )
                return
            column_name = candidates[0]
            self.last_frame_total_column_name = column_name

        if self.average_values_manager is not None:
            self.average_values_manager.import_frame_total_column(
                self.data,
                column_name,
                select_tab=True,
            )

    def export_average_values(self) -> None:
        if not self._ensure_dependencies():
            return

        if self.average_values_manager is None:
            messagebox.showinfo("No Data", "Average Values is not ready yet.")
            return

        self.average_values_manager.export_data()

    def show_curve_plot_tab(self) -> None:
        if hasattr(self, "notebook"):
            self.notebook.select(self.plot_frame)
        self.update_curve_plot()

    def update_curve_plot(
        self,
        data: list[list[str]] | None = None,
        headers: list[str] | None = None,
    ) -> None:
        if not hasattr(self, "plot_panel"):
            return

        if data is None or headers is None:
            data, headers = self._average_plot_table()
            if not data or not headers:
                self.plot_panel.clear()
                return
        else:
            data = [list(row) for row in data]
            headers = self._clean_plot_headers(headers, data)

        if data and headers:
            selected_columns = self._average_plot_selected_columns(len(headers))

            if selected_columns:
                x_index = 0
                for index in selected_columns:
                    if index < len(headers) and "time" in str(headers[index]).lower():
                        x_index = index
                        break
                y_indexes = [
                    index
                    for index in selected_columns
                    if index != x_index and 0 <= index < len(headers)
                ]
                if not y_indexes:
                    y_indexes = [index for index in range(len(headers)) if index != x_index]
                keep_indexes = [x_index] + y_indexes
                unique_indexes: list[int] = []
                for index in keep_indexes:
                    if index not in unique_indexes and index < len(headers):
                        unique_indexes.append(index)
                filtered_headers = [headers[index] for index in unique_indexes]
                filtered_data = [
                    [row[index] if index < len(row) else "" for index in unique_indexes]
                    for row in data
                ]
                self.plot_panel.set_table(filtered_data, filtered_headers, selected_y_names=filtered_headers[1:])
            else:
                self.plot_panel.set_table(data, headers, selected_y_names=headers[1:])
        else:
            self.plot_panel.clear()

    def _average_plot_table(self) -> tuple[list[list[str]], list[str]]:
        if self.average_values_manager is None:
            return [], []

        manager = self.average_values_manager
        try:
            manager._sync_cache_from_sheet()
        except Exception:
            pass

        data = [list(row) for row in getattr(manager, "data", [])]
        headers = list(getattr(manager, "headers", []))
        sheet = getattr(manager, "sheet", None)

        if sheet is not None:
            try:
                sheet_data = sheet.get_sheet_data()
                if sheet_data and not manager._is_placeholder_data(sheet_data):
                    data = [list(row) for row in sheet_data]
            except Exception:
                pass

            try:
                sheet_headers = list(sheet.headers())
                if sheet_headers:
                    headers = [str(value) for value in sheet_headers]
            except Exception:
                pass

        return data, self._clean_plot_headers(headers, data)

    def _clean_plot_headers(self, headers: list[str], data: list[list[str]]) -> list[str]:
        column_count = max([len(headers), *(len(row) for row in data)] or [0])
        cleaned: list[str] = []
        for index in range(column_count):
            raw = str(headers[index]).strip() if index < len(headers) else ""
            cleaned.append(raw or f"Column {index + 1}")
        return cleaned

    def _average_plot_selected_columns(self, column_count: int) -> list[int]:
        sheet = None
        if self.average_values_manager is not None:
            sheet = getattr(self.average_values_manager, "sheet", None)
        if sheet is None:
            sheet = self.average_sheet
        if sheet is None:
            return []

        selected: set[int] = set()

        for getter in (
            lambda: sheet.get_selected_columns(),
            lambda: sheet.MT.get_selected_cols() if hasattr(sheet, "MT") else [],
        ):
            try:
                selected.update(index for index in getter() if isinstance(index, int))
            except Exception:
                pass

        for getter in (
            lambda: sheet.get_selected_cells(get_cols=True),
            lambda: sheet.MT.get_selected_cells(get_cols=True) if hasattr(sheet, "MT") else [],
        ):
            try:
                for item in getter():
                    if isinstance(item, int):
                        selected.add(item)
                    elif isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], int):
                        selected.add(item[1])
            except Exception:
                pass

        try:
            selection_items = sheet.MT.get_selection_items(cells=True, rows=False, columns=True) if hasattr(sheet, "MT") else ()
            for _, box in selection_items:
                coords = getattr(box, "coords", None)
                if coords is None:
                    continue
                for column in range(getattr(coords, "from_c", 0), getattr(coords, "upto_c", 0)):
                    selected.add(column)
        except Exception:
            pass

        for getter in (
            lambda: sheet.get_all_selection_boxes(),
            lambda: sheet.MT.get_all_selection_boxes() if hasattr(sheet, "MT") else [],
        ):
            try:
                for box in getter():
                    coords = getattr(box, "coords", box)
                    from_c = getattr(coords, "from_c", None)
                    upto_c = getattr(coords, "upto_c", None)
                    if from_c is not None and upto_c is not None:
                        for column in range(from_c, upto_c):
                            selected.add(column)
            except Exception:
                pass

        return sorted(index for index in selected if 0 <= index < column_count)

    def generate_frame_time_column(self) -> None:
        if not self._ensure_dependencies():
            return

        if self.data is None:
            messagebox.showwarning("No Data", "Please click \"Load Data\" first.")
            return

        image_column_index = frame_tools.find_image_column_index(self.data)
        if image_column_index is None:
            messagebox.showwarning(
                "Missing Image Column",
                "Could not find an Image column in the loaded data.",
            )
            return

        measuring_time_column_index = frame_tools.find_measuring_time_column_index(self.data)
        if measuring_time_column_index is None:
            messagebox.showwarning(
                "Missing Measuring Time Column",
                "Could not find the Measuring time [s] column in the loaded data.",
            )
            return

        image_column_name = str(self.data.columns[image_column_index])
        try:
            result = frame_tools.build_unique_frame_total_time_column(
                self.data,
                image_column_index,
                measuring_time_column_index,
                existing_names={str(column) for column in self.data.columns},
            )
        except ValueError as exc:
            messagebox.showwarning("No Frame Data", str(exc))
            return

        insert_at = image_column_index + 1
        self._save_undo_snapshot()
        self.data.insert(
            insert_at,
            result.column_name,
            result.values,
            allow_duplicates=True,
        )
        self.last_frame_total_column_name = result.column_name
        self.load_note = f"Inserted '{result.column_name}' after '{image_column_name}'. {result.note}"
        if self.selected_columns:
            self.selected_columns = {
                index + 1 if index >= insert_at else index for index in self.selected_columns
            }
        if self.sheet is not None:
            self._insert_sheet_column(insert_at, result.column_name, result.values)
            self._apply_sheet_highlights()
        self._write_output(
            "\n".join(
                [
                    "Frame Total Time Generated",
                    "=" * 80,
                    self.load_note,
                ]
            )
        )

    def undo_last_action(self) -> None:
        if not self.undo_stack:
            messagebox.showinfo("Nothing to Undo", "There is no previous calculation to undo.")
            return

        self._commit_average_column_name_edit()
        snapshot = self.undo_stack.pop()
        self.data = snapshot["data"]
        self.load_note = snapshot["load_note"]
        self.selected_columns = set(snapshot["selected_columns"])
        self.selected_rows = set(snapshot["selected_rows"])
        self.average_columns = set(snapshot["average_columns"])
        self.average_editable_cell = snapshot.get("average_editable_cell")
        self.table_offset = snapshot["table_offset"]
        self.last_frame_total_column_name = snapshot.get("last_frame_total_column_name")

        self._show_data_table(keep_selection=True)
        self._write_output(
            "\n".join(
                [
                    "Undo Complete",
                    "=" * 80,
                    "The previous step was restored.",
                    f"Remaining undo steps: {len(self.undo_stack)}",
                ]
            )
        )

    def _undo_from_event(self) -> str:
        self.undo_last_action()
        return "break"

    def _save_undo_snapshot(self) -> None:
        if self.data is None:
            return

        self._commit_average_column_name_edit()
        self.undo_stack.append({
            "data": self.data.copy(deep=True),
            "load_note": self.load_note,
            "selected_columns": set(self.selected_columns),
            "selected_rows": set(self.selected_rows),
            "average_columns": set(self.average_columns),
            "average_editable_cell": self.average_editable_cell,
            "table_offset": self.table_offset,
            "last_frame_total_column_name": self.last_frame_total_column_name,
        })
        if len(self.undo_stack) > UNDO_LIMIT:
            self.undo_stack.pop(0)

    def install_dependencies(self) -> None:
        requirements_path = Path(__file__).with_name("requirements.txt")
        if not requirements_path.exists():
            messagebox.showerror("Install Failed", "requirements.txt was not found.")
            return

        self._write_output(
            "Installing dependencies. Please wait...\n\n"
            f"Python: {sys.executable}\n"
            f"Command: {sys.executable} -m pip install -r {requirements_path}\n"
        )
        self.update_idletasks()

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            messagebox.showerror("Install Failed", f"Unable to start pip:\n{exc}")
            return

        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        if result.returncode != 0:
            self._write_output("Dependency installation failed:\n\n" + output)
            messagebox.showerror(
                "Install Failed",
                "Dependency installation failed. See the output panel for details.",
            )
            return

        self._load_pandas()
        self._load_tksheet()
        self._write_output(
            "Dependencies installed successfully.\n\n"
            "You can now click \"Load Data\" to continue.\n\n"
            + output
        )
        messagebox.showinfo(
            "Install Complete",
            "Dependencies have been installed. You can now load data.",
        )

    def _read_file(self, path: Path):
        data, load_note, source_rows = data_utils.read_and_prepare_data(path)
        self.load_note = load_note
        self.source_data_rows = source_rows
        return data

    def _ensure_dependencies(self) -> bool:
        self._load_pandas()
        self._load_tksheet()
        if pd is not None and Sheet is not None:
            return True

        missing = []
        if pd is None:
            missing.append("pandas")
        if Sheet is None:
            missing.append("tksheet")
        message = (
            f"The current Python environment is missing dependencies: {', '.join(missing)}.\n\n"
            "Click the \"Install Dependencies\" button above, or run this command "
            "in the project folder:\n"
            f"{sys.executable} -m pip install -r requirements.txt\n\n"
            "After installation, click RUN again."
        )
        messagebox.showerror("Missing Dependencies", message)
        self._write_output(message)
        return False

    def _ensure_pandas(self) -> bool:
        return self._ensure_dependencies()

    def _load_pandas(self) -> None:
        global pd
        if pd is not None:
            return

        try:
            pd = importlib.import_module("pandas")
        except ModuleNotFoundError:
            pd = None

    def _load_tksheet(self) -> None:
        global Sheet
        if Sheet is not None:
            return

        try:
            from tksheet import Sheet as LoadedSheet
        except ModuleNotFoundError:
            Sheet = None
        else:
            Sheet = LoadedSheet

    def _create_sheet(
        self,
        parent: ttk.Frame | None = None,
        bind_selection_sync: bool = True,
        enable_editing: bool = False,
        bind_app_shortcuts: bool = True,
        use_custom_double_click: bool = True,
    ):
        target_parent = parent or self.table_frame
        if Sheet is None:
            label = ttk.Label(
                target_parent,
                text="Missing tksheet dependency. Click Install Dependencies.",
            )
            label.grid(row=0, column=0, sticky="nsew")
            return None

        sheet = Sheet(
            target_parent,
            data=[],
            headers=[],
            row_index=[],
            theme="light blue",
            show_row_index=True,
            show_header=True,
            font=("Segoe UI", 9, "normal"),
            header_font=("Segoe UI", 9, "bold"),
            index_font=("Segoe UI", 9, "normal"),
            default_row_height=24,
            default_column_width=110,
            table_selected_columns_bg="#cfe8ff",
            table_selected_rows_bg="#cfe8ff",
            header_selected_columns_bg="#0B57D0",
            header_selected_columns_fg="#FFFFFF",
            index_selected_rows_bg="#0B57D0",
            index_selected_rows_fg="#FFFFFF",
        )
        sheet.grid(row=0, column=0, sticky="nsew")
        sheet.enable_bindings("single_select", "drag_select", "column_select", "row_select", "arrowkeys", "copy", "rc_select")
        if enable_editing:
            sheet.enable_bindings("edit")
        if bind_selection_sync:
            sheet.bind("<ButtonRelease-1>", self._sync_sheet_selection_later)
            sheet.bind("<KeyRelease>", self._sync_sheet_selection_later)
        if use_custom_double_click:
            sheet.bind("<Double-Button-1>", self._on_sheet_double_click, add="+")
        sheet.bind("<Control-MouseWheel>", self._on_zoom_mousewheel)
        if bind_app_shortcuts:
            sheet.bind("<Control-z>", lambda event: self._undo_from_event())
            sheet.bind("<Control-Z>", lambda event: self._undo_from_event())
        return sheet

    def _bind_average_sheet_actions(self) -> None:
        if self.average_sheet is None:
            return

        self.average_sheet.bind("<Double-Button-1>", self._on_average_sheet_double_click, add="+")
        self.average_sheet.bind("<Delete>", self._on_average_sheet_delete_key, add="+")
        self.average_sheet.bind("<BackSpace>", self._on_average_sheet_delete_key, add="+")
        self.average_sheet.bind("<Control-a>", self._on_average_sheet_select_all, add="+")
        self.average_sheet.bind("<Control-A>", self._on_average_sheet_select_all, add="+")
        self.average_sheet.bind("<Button-3>", self._on_average_sheet_right_click, add="+")
        self.average_sheet.bind("<Button-2>", self._on_average_sheet_right_click, add="+")

    def _build_average_sheet_context_menu(self) -> None:
        self.average_sheet_context_menu = tk.Menu(self, tearoff=0)
        self.average_sheet_context_menu.add_command(label="Add Row", command=self._average_menu_add_row)
        self.average_sheet_context_menu.add_command(label="Delete Row", command=self._average_menu_delete_row)
        self.average_sheet_context_menu.add_separator()
        self.average_sheet_context_menu.add_command(label="Add Column", command=self._average_menu_add_column)
        self.average_sheet_context_menu.add_command(label="Delete Column", command=self._average_menu_delete_column)

    def _show_data_table(self, keep_selection: bool = False) -> None:
        if self.data is None:
            return
        self._commit_average_column_name_edit()
        if self.sheet is None:
            self._load_tksheet()
            self.sheet = self._create_sheet()
            if self.sheet is None:
                messagebox.showerror("Missing Dependency", "tksheet is required for the data table.")
                return

        df = self.data
        if not keep_selection:
            self.table_offset = 0
            self.selected_columns.clear()
            self.selected_rows.clear()
        self.drag_mode = None
        self.drag_anchor = None
        self.full_render_mode = True
        self._set_sheet_data()
        self._apply_sheet_highlights()
        self._restore_average_editable_cell()

        self.notebook.select(self.table_frame)
        self._write_output(
            "\n".join(
                [
                    "Data Loaded Successfully",
                    "=" * 80,
                    f"File name: {self.current_file.name if self.current_file else 'Unknown'}",
                    f"Data size: {df.shape[0]} rows x {df.shape[1]} columns",
                    *( [f"Source data rows: {self.source_data_rows}"] if self.source_data_rows is not None else [] ),
                    "",
                    *( [self.load_note, ""] if self.load_note else [] ),
                    "The dataset is shown in the Data Table tab.",
                    "All loaded rows are rendered in the table.",
                    "Selected rows and columns are highlighted in blue.",
                    "Generated Average columns are highlighted in yellow.",
                ]
            )
        )

    def _set_sheet_data(self) -> None:
        if self.data is None or self.sheet is None:
            return

        sheet_data = [
            [self._format_cell(value) for value in row]
            for row in self.data.itertuples(index=False, name=None)
        ]
        headers = [self._display_column_name(index) for index in range(len(self.data.columns))]
        row_index = [str(index) for index in range(1, len(self.data) + 1)]
        self.sheet.set_sheet_data(
            sheet_data,
            reset_col_positions=True,
            reset_row_positions=True,
            reset_highlights=True,
        )
        self.sheet.headers(headers, reset_col_positions=False)
        self.sheet.row_index(row_index, reset_row_positions=False)
        self._apply_content_column_widths(redraw=False)
        self.sheet.set_all_row_heights(height=self._scale_size(24), redraw=False)
        self.sheet.redraw()

    def _apply_sheet_highlights(self) -> None:
        if self.sheet is None:
            return

        self.sheet.dehighlight_all(redraw=False)
        if self.average_columns:
            self.sheet.highlight_columns(
                sorted(self.average_columns),
                bg="#fff2a8",
                fg="black",
                highlight_header=True,
                redraw=False,
            )
        if self.selected_columns:
            self.sheet.highlight_columns(
                sorted(self.selected_columns),
                bg="#cfe8ff",
                fg="black",
                highlight_header=True,
                redraw=False,
            )
        if self.selected_rows:
            self.sheet.highlight_rows(
                sorted(self.selected_rows),
                bg="#cfe8ff",
                fg="black",
                highlight_index=True,
                redraw=False,
            )
        self.sheet.redraw()

    def _activate_average_first_cell(self, average_column_index: int) -> None:
        if self.sheet is None or self.data is None:
            return

        if not (0 <= average_column_index < len(self.data.columns)):
            return

        self.sheet.readonly_cells(cells=[(0, average_column_index)], readonly=False, redraw=False)
        self.sheet.select_cell(0, average_column_index, redraw=False)
        self.sheet.redraw()
        try:
            self.sheet.open_cell()
        except Exception:
            pass

    def _restore_average_editable_cell(self) -> None:
        if self.sheet is None or self.data is None or self.average_editable_cell is None:
            return

        row, column = self.average_editable_cell
        if not (0 <= row < len(self.data) and 0 <= column < len(self.data.columns)):
            return

        self.sheet.readonly_cells(cells=[(row, column)], readonly=False, redraw=False)
        self.sheet.redraw()

    def _commit_average_column_name_edit(self) -> None:
        if self.sheet is None or self.data is None or self.average_editable_cell is None:
            return

        row, column = self.average_editable_cell
        if row != 0 or not (0 <= row < len(self.data)) or not (0 <= column < len(self.data.columns)):
            return

        try:
            edited_value = self.sheet.get_cell_data(row, column)
        except Exception:
            return

        edited_name = str(edited_value).strip()
        if not edited_name:
            return

        current_cell_value = self._format_cell(self.data.iat[row, column]).strip()
        if edited_name == current_cell_value:
            return

        current_columns = list(self.data.columns)
        current_columns[column] = edited_name
        self.data.columns = current_columns
        self.data.iat[row, column] = edited_name

    def _on_sheet_double_click(self, event: tk.Event) -> str | None:
        if self.sheet is None or self.data is None or self.average_editable_cell is None:
            return None

        if self.sheet.identify_region(event) != "table":
            return None

        row = self.sheet.identify_row(event)
        column = self.sheet.identify_column(event)
        if row is None or column is None:
            return None

        if (row, column) != self.average_editable_cell:
            return None

        self.sheet.readonly_cells(cells=[(row, column)], readonly=False, redraw=False)
        self.sheet.select_cell(row, column, redraw=False)
        self.sheet.redraw()
        self.after_idle(lambda: self._open_average_editable_cell(row, column))
        return "break"

    def _open_average_editable_cell(self, row: int, column: int) -> None:
        if self.sheet is None or self.data is None:
            return

        if self.average_editable_cell != (row, column):
            return

        if not (0 <= row < len(self.data) and 0 <= column < len(self.data.columns)):
            return

        self.sheet.readonly_cells(cells=[(row, column)], readonly=False, redraw=False)
        self.sheet.select_cell(row, column, redraw=False)
        try:
            self.sheet.open_cell()
        except Exception:
            pass

    def _sync_sheet_selection_later(self, event=None) -> str:
        self.after_idle(self._sync_sheet_selection)
        return "break"

    def _sync_sheet_selection(self) -> None:
        if self.sheet is None or self.data is None:
            return

        selected_columns = set(self._current_selected_column_indexes())
        try:
            selected_rows = set(self.sheet.get_selected_rows())
        except Exception:
            selected_rows = set()
        selected_rows = {index for index in selected_rows if 0 <= index < len(self.data)}
        if not selected_columns and not selected_rows:
            return
        if selected_columns != self.selected_columns or selected_rows != self.selected_rows:
            self.selected_columns = selected_columns
            self.selected_rows = selected_rows
            self._apply_sheet_highlights()

    def _toggle_column_selection(self, column_index: int) -> None:
        if column_index in self.selected_columns:
            self.selected_columns.remove(column_index)
        else:
            self.selected_columns.add(column_index)
        self._apply_sheet_highlights()

    def _on_table_click(self, event: tk.Event) -> str | None:
        return None

    def _on_table_drag(self, event: tk.Event) -> str:
        return "break"

    def _on_table_release(self, event: tk.Event) -> str:
        self.drag_mode = None
        self.drag_anchor = None
        return "break"

    def _table_column_to_data_index(self, column_id: str) -> int | None:
        if not column_id.startswith("#"):
            return None

        try:
            tree_column_index = int(column_id[1:]) - 1
        except ValueError:
            return None

        if tree_column_index <= 0:
            return None

        data_column_index = tree_column_index - 1
        if self.data is None or data_column_index >= len(self.data.columns):
            return None
        return data_column_index

    def _event_to_data_row_index(self, event: tk.Event) -> int | None:
        return None

    def _select_column_range(self, start: int, end: int) -> None:
        if self.data is None:
            return

        low, high = sorted((start, end))
        self.selected_columns = set(range(low, high + 1))
        self._apply_sheet_highlights()

    def _select_row_range(self, start: int, end: int) -> None:
        if self.data is None:
            return

        low, high = sorted((start, end))
        self.selected_rows = set(range(low, high + 1))
        self._apply_sheet_highlights()

    def _update_table_headings(self) -> None:
        self._apply_sheet_highlights()

    def _display_column_name(self, column_index: int) -> str:
        if self.data is None:
            return ""
        return str(self.data.columns[column_index])

    def _next_average_column_name(self) -> str:
        if self.data is None:
            return "Average"

        existing_names = {str(column) for column in self.data.columns}
        if "Average" not in existing_names:
            return "Average"

        suffix = 2
        while f"Average {suffix}" in existing_names:
            suffix += 1
        return f"Average {suffix}"

    def _render_table_rows(self) -> None:
        self._set_sheet_data()
        self._apply_sheet_highlights()

    def _update_visible_row_tags(self) -> None:
        self._apply_sheet_highlights()

    def _on_table_scroll(self, action: str, value: str, unit: str | None = None) -> None:
        return None

    def _on_table_mousewheel(self, event: tk.Event) -> str:
        return None

    def _on_zoom_mousewheel(self, event: tk.Event) -> str:
        if event.delta > 0:
            self._change_zoom(ZOOM_STEP)
        elif event.delta < 0:
            self._change_zoom(-ZOOM_STEP)
        return "break"

    def _change_zoom(self, delta: float) -> None:
        self.zoom_scale = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom_scale + delta))
        self._apply_zoom()

    def _reset_zoom(self) -> None:
        self.zoom_scale = 1.0
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        table_size = max(7, round(9 * self.zoom_scale))
        report_size = max(7, round(10 * self.zoom_scale))
        row_height = max(18, round(24 * self.zoom_scale))

        self.report_font.configure(size=report_size)
        self.zoom_label.configure(text=f"{round(self.zoom_scale * 100)}%")

        if self.sheet is not None:
            self.sheet.set_options(
                font=("Segoe UI", table_size, "normal"),
                header_font=("Segoe UI", table_size, "bold"),
                index_font=("Segoe UI", table_size, "normal"),
                row_height=row_height,
                redraw=False,
            )
            self.sheet.set_all_row_heights(height=row_height, redraw=False)
            self._apply_content_column_widths(redraw=True)

        if self.average_values_manager is not None:
            self.average_values_manager.apply_zoom(table_size, row_height)

    def _refresh_table_column_widths(self) -> None:
        if self.data is None or self.sheet is None:
            return

        self._apply_content_column_widths(redraw=True)

    def _move_table(self, delta: int) -> str:
        return ""

    def _set_table_offset(self, offset: int) -> str:
        self.table_offset = max(0, min(offset, self._max_table_offset()))
        return "break"

    def _max_table_offset(self) -> int:
        if self.data is None:
            return 0
        return max(len(self.data) - VIRTUAL_VIEW_ROWS, 0)

    def _apply_content_column_widths(self, redraw: bool = False) -> None:
        if self.data is None or self.sheet is None:
            return

        try:
            column_count = len(self.data.columns)
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

    def _insert_sheet_column(self, index: int, header: str, values: list[object]) -> None:
        if self.sheet is None:
            return

        payload = [header, *values]
        try:
            self.sheet.insert_columns(
                columns=[payload],
                idx=index,
                headers=True,
                fill=True,
                undo=False,
                emit_event=False,
                create_selections=False,
                add_row_heights=False,
                push_ops=False,
                redraw=False,
            )
            try:
                text_width = self.sheet.get_column_text_width(index, visible_only=True)
                self.sheet.column_width(index, width=min(max(text_width + 18, 80), 360), redraw=False)
            except Exception:
                pass
            self.sheet.redraw()
        except Exception:
            self._show_data_table(keep_selection=True)

    def _refresh_average_sheet(self, select_tab: bool = False) -> None:
        self._render_average_values_sheet(select_tab=select_tab, placeholder=True)

    def _append_main_average_columns_to_average_values(self, select_tab: bool = False) -> None:
        if self.data is None:
            return

        average_indexes = sorted(index for index in self.average_columns if 0 <= index < len(self.data.columns))
        if not average_indexes:
            messagebox.showinfo(
                "No Average Columns",
                "Please calculate average columns in the Data Table first.",
            )
            return

        column_names = [str(self.data.columns[index]) for index in average_indexes]
        self._append_main_columns_to_average_values(column_names, prepend=False, select_tab=select_tab)

    def _append_main_columns_to_average_values(
        self,
        column_names: list[str],
        prepend: bool = False,
        select_tab: bool = False,
    ) -> None:
        if self.data is None or self.average_sheet is None:
            return

        source_columns = [column for column in column_names if column in self.data.columns]
        if not source_columns:
            return

        self._sync_average_values_cache_from_sheet()
        target_rows = len(self.data)
        self._ensure_average_values_row_count(target_rows)

        extracted_columns: list[list[str]] = []
        extracted_headers: list[str] = []
        for column_name in source_columns:
            extracted_headers.append(str(column_name))
            extracted_columns.append(self._extract_average_value_column_values(column_name))

        if not self.average_values_data:
            self.average_values_data = [[""] * len(extracted_columns) for _ in range(target_rows)]
            for column_offset, column_values in enumerate(extracted_columns):
                for row_index, value in enumerate(column_values):
                    self.average_values_data[row_index][column_offset] = value
            self.average_values_headers = extracted_headers[:]
        else:
            insertion_index = 0 if prepend else len(self.average_values_headers)
            if not self.average_values_headers:
                self.average_values_headers = [f"Column {index + 1}" for index in range(len(self.average_values_data[0]) if self.average_values_data else 0)]
            for header, values in zip(extracted_headers, extracted_columns, strict=False):
                self._insert_average_value_column(insertion_index, header, values)
                insertion_index += 1

        self._render_average_values_sheet(select_tab=select_tab)

    def _insert_average_value_column(self, index: int, header: str, values: list[str]) -> None:
        row_count = max(len(self.average_values_data), len(values))
        if not self.average_values_data:
            self.average_values_data = [[""] for _ in range(row_count)]
        self._ensure_average_values_row_count(row_count)
        for row_index in range(row_count):
            value = values[row_index] if row_index < len(values) else ""
            self.average_values_data[row_index].insert(index, value)
        self.average_values_headers.insert(index, header)

    def _extract_average_value_column_values(self, column_name: str) -> list[str]:
        if self.data is None or column_name not in self.data.columns:
            return []

        values = [self._format_cell(value) for value in self.data[column_name].tolist()]
        if values and values[0] == str(column_name):
            values = values[1:]
        return values

    def _sync_average_values_cache_from_sheet(self) -> None:
        if self.average_sheet is None:
            return

        try:
            sheet_data = self.average_sheet.get_sheet_data()
        except Exception:
            return

        if self._is_average_placeholder_data(sheet_data):
            return

        normalized = [list(row) for row in sheet_data]
        self._normalize_average_values_rows(normalized)
        self.average_values_data = normalized
        if not self.average_values_headers or len(self.average_values_headers) != self._average_values_column_count():
            self.average_values_headers = [
                f"Column {index + 1}"
                for index in range(self._average_values_column_count())
            ]

    def _ensure_average_values_row_count(self, target_rows: int) -> None:
        if target_rows <= 0:
            self.average_values_data = []
            return

        if not self.average_values_data:
            column_count = len(self.average_values_headers)
            self.average_values_data = [[""] * column_count for _ in range(target_rows)]
            return

        column_count = self._average_values_column_count()
        for row in self.average_values_data:
            if len(row) < column_count:
                row.extend([""] * (column_count - len(row)))
            elif len(row) > column_count:
                del row[column_count:]

        current_rows = len(self.average_values_data)
        if current_rows < target_rows:
            for _ in range(target_rows - current_rows):
                self.average_values_data.append([""] * column_count)
        elif current_rows > target_rows:
            del self.average_values_data[target_rows:]

    def _normalize_average_values_rows(self, rows: list[list[str]]) -> None:
        if not rows:
            return

        column_count = max(len(row) for row in rows)
        for row in rows:
            if len(row) < column_count:
                row.extend([""] * (column_count - len(row)))
            elif len(row) > column_count:
                del row[column_count:]

    def _average_values_column_count(self) -> int:
        if self.average_values_data:
            return max(len(row) for row in self.average_values_data)
        return len(self.average_values_headers)

    def _is_average_placeholder_data(self, rows: list[list[str]]) -> bool:
        if len(rows) != 1 or not rows[0]:
            return False
        text = str(rows[0][0]).strip().lower()
        return text.startswith("load data first") or text.startswith("no average columns")

    def _render_average_values_sheet(self, select_tab: bool = False, placeholder: bool = False) -> None:
        if self.average_sheet is None:
            return

        sheet = self.average_sheet
        if self.average_values_data:
            data = [list(row) for row in self.average_values_data]
            headers = self.average_values_headers[:]
            if not headers:
                headers = [f"Column {index + 1}" for index in range(len(data[0]))]
                self.average_values_headers = headers[:]
        else:
            if self.data is None or not self.average_columns:
                note = "Load data first, then generate average columns."
            else:
                note = "No average columns have been generated yet."
            data = [[note]]
            headers = ["Note"]

        if not data:
            data = [[""]]
            headers = ["Note"]

        self._normalize_average_values_rows(data)
        column_count = max(len(row) for row in data)
        if not headers or len(headers) != column_count:
            headers = [
                headers[index] if index < len(headers) else f"Column {index + 1}"
                for index in range(column_count)
            ]
            self.average_values_headers = headers[:]

        row_index = [str(index) for index in range(1, len(data) + 1)]
        sheet.set_sheet_data(
            data,
            reset_col_positions=True,
            reset_row_positions=True,
            reset_highlights=True,
        )
        sheet.headers(headers, reset_col_positions=False)
        sheet.row_index(row_index, reset_row_positions=False)
        sheet.set_all_column_widths(width=None, redraw=False)
        sheet.set_all_row_heights(height=self._scale_size(24), redraw=False)
        sheet.redraw()
        self.average_values_sheet_ready = bool(self.average_values_data)

        if select_tab:
            self.notebook.select(self.average_frame)

    def _average_context_selection(self) -> tuple[list[int], list[int]]:
        if self.average_sheet is None:
            return [], []

        try:
            selected_columns = sorted(
                index for index in self.average_sheet.get_selected_columns() if isinstance(index, int) and index >= 0
            )
        except Exception:
            selected_columns = []

        try:
            selected_rows = sorted(
                index for index in self.average_sheet.get_selected_rows() if isinstance(index, int) and index >= 0
            )
        except Exception:
            selected_rows = []

        return selected_columns, selected_rows

    def _on_average_sheet_right_click(self, event: tk.Event) -> str:
        if self.average_sheet is None or self.average_sheet_context_menu is None:
            return "break"

        row = self.average_sheet.identify_row(event)
        column = self.average_sheet.identify_column(event)
        self.average_sheet_context_target = {"row": row, "column": column}

        try:
            region = self.average_sheet.identify_region(event)
            if region == "header" and column is not None:
                self.average_sheet.select_column(column, redraw=False)
            elif region == "index" and row is not None:
                self.average_sheet.select_row(row, redraw=False)
            elif region == "table" and row is not None and column is not None:
                self.average_sheet.select_cell(row, column, redraw=False)
            self.average_sheet.redraw()
            self.average_sheet_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.average_sheet_context_menu.grab_release()
        return "break"

    def _average_context_column_index(self) -> int | None:
        selected_columns, _ = self._average_context_selection()
        if selected_columns:
            return selected_columns[-1]
        return self.average_sheet_context_target.get("column")

    def _average_context_row_index(self) -> int | None:
        _, selected_rows = self._average_context_selection()
        if selected_rows:
            return selected_rows[-1]
        return self.average_sheet_context_target.get("row")

    def _average_menu_add_column(self) -> None:
        if self.average_sheet is None:
            return

        self._sync_average_values_cache_from_sheet()
        column_index = self._average_context_column_index()
        if column_index is None:
            column_index = self._average_values_column_count() - 1
        insert_at = max(column_index + 1, 0)
        row_count = len(self.average_values_data)
        if row_count == 0:
            self.average_values_data = [[""]]
            self.average_values_headers = ["Column 1"]
            self._render_average_values_sheet(select_tab=True)
            return

        values = [""] * row_count
        header = self._next_average_sheet_column_name()
        self._insert_average_value_column(insert_at, header, values)
        self._render_average_values_sheet(select_tab=True)

    def _average_menu_delete_column(self) -> None:
        if self.average_sheet is None:
            return

        self._sync_average_values_cache_from_sheet()
        selected_columns, _ = self._average_context_selection()
        if not selected_columns:
            column_index = self._average_context_column_index()
            if column_index is None:
                return
            selected_columns = [column_index]

        selected_columns = sorted(set(index for index in selected_columns if 0 <= index < self._average_values_column_count()))
        if not selected_columns:
            return

        for column_index in reversed(selected_columns):
            for row in self.average_values_data:
                if column_index < len(row):
                    del row[column_index]
            if column_index < len(self.average_values_headers):
                del self.average_values_headers[column_index]

        self._render_average_values_sheet(select_tab=True)

    def _average_menu_add_row(self) -> None:
        if self.average_sheet is None:
            return

        self._sync_average_values_cache_from_sheet()
        row_index = self._average_context_row_index()
        insert_at = len(self.average_values_data) if row_index is None else max(row_index + 1, 0)
        column_count = self._average_values_column_count()
        if column_count == 0:
            column_count = max(len(self.average_values_headers), 1)
            self.average_values_headers = self.average_values_headers or [self._next_average_sheet_column_name()]
        self.average_values_data.insert(insert_at, [""] * column_count)
        self._render_average_values_sheet(select_tab=True)

    def _average_menu_delete_row(self) -> None:
        if self.average_sheet is None:
            return

        self._sync_average_values_cache_from_sheet()
        _, selected_rows = self._average_context_selection()
        if not selected_rows:
            row_index = self._average_context_row_index()
            if row_index is None:
                return
            selected_rows = [row_index]

        selected_rows = sorted(set(index for index in selected_rows if 0 <= index < len(self.average_values_data)))
        if not selected_rows:
            return

        for row_index in reversed(selected_rows):
            del self.average_values_data[row_index]

        self._render_average_values_sheet(select_tab=True)

    def _next_average_sheet_column_name(self) -> str:
        existing = set(self.average_values_headers)
        suffix = 1
        while True:
            candidate = "New Column" if suffix == 1 else f"New Column {suffix}"
            if candidate not in existing:
                return candidate
            suffix += 1

    def _on_average_sheet_double_click(self, event: tk.Event) -> str | None:
        if self.average_sheet is None:
            return None

        if self.average_sheet.identify_region(event) != "table":
            return None

        row = self.average_sheet.identify_row(event)
        column = self.average_sheet.identify_column(event)
        if row is None or column is None:
            return None

        try:
            self.average_sheet.select_cell(row, column, redraw=False)
            self.average_sheet.redraw()
            self.average_sheet.open_cell()
        except Exception:
            pass
        return "break"

    def _on_average_sheet_delete_key(self, event: tk.Event) -> str:
        if self.average_sheet is None:
            return "break"

        try:
            self.average_sheet.delete(event)
        except Exception:
            try:
                self.average_sheet.clear()
            except Exception:
                pass
        return "break"

    def _on_average_sheet_select_all(self, event: tk.Event) -> str:
        if self.average_sheet is None:
            return "break"

        try:
            self.average_sheet.select_all()
        except Exception:
            pass
        return "break"

    def _scale_size(self, value: int) -> int:
        return max(1, round(value * self.zoom_scale))

    def _format_cell(self, value) -> str:
        if pd is not None and pd.isna(value):
            return ""
        return str(value)

    def _format_table_cell(self, value, column_index: int) -> str:
        return self._format_cell(value)

    def _format_decimal_places(self, value) -> str:
        if pd is not None and pd.isna(value):
            return ""
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return ""
        return str(number.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))

    def _write_output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.configure(state="disabled")


if __name__ == "__main__":
    app = DataAnalysisApp()
    app.mainloop()
