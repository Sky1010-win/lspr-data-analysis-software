from __future__ import annotations

import csv
import colorsys
import math
from dataclasses import dataclass
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - handled by the main app.
    pd = None


@dataclass(slots=True)
class PlotSeries:
    name: str
    points: list[tuple[float, float]]
    color: str


class AverageValuesChartPanel(ttk.Frame):
    def __init__(self, parent: tk.Misc, refresh_callback=None) -> None:
        super().__init__(parent)
        self._refresh_callback = refresh_callback
        self.data: list[list[str]] = []
        self.headers: list[str] = []
        self._selected_y_cache: list[str] = []
        self._series: list[PlotSeries] = []
        self._plot_rect: tuple[float, float, float, float] | None = None
        self._view_bounds: tuple[float, float, float, float] | None = None
        self._pan_anchor: tuple[int, int] | None = None
        self._pan_bounds: tuple[float, float, float, float] | None = None

        self.x_var = tk.StringVar()
        self.chart_type_var = tk.StringVar(value="line")
        self.step_var = tk.StringVar(value="1")
        self.line_width_var = tk.StringVar(value="2")
        self.point_size_var = tk.StringVar(value="3")
        self.x_min_var = tk.StringVar()
        self.x_max_var = tk.StringVar()
        self.y_min_var = tk.StringVar()
        self.y_max_var = tk.StringVar()
        self.text_var = tk.StringVar()
        self.show_points_var = tk.BooleanVar(value=True)
        self.show_grid_var = tk.BooleanVar(value=True)
        self.show_legend_var = tk.BooleanVar(value=True)
        self.smooth_var = tk.BooleanVar(value=False)
        self._text_mode = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        controls = ttk.Frame(self, padding=(8, 8, 8, 6))
        controls.grid(row=0, column=0, sticky="ew")
        for column in range(16):
            controls.columnconfigure(column, weight=0)
        controls.columnconfigure(15, weight=1)

        ttk.Label(controls, text="X").grid(row=0, column=0, padx=(0, 4), pady=2, sticky="w")
        self.x_box = ttk.Combobox(controls, textvariable=self.x_var, width=18, state="readonly")
        self.x_box.grid(row=0, column=1, padx=(0, 10), pady=2, sticky="w")
        self.x_box.bind("<<ComboboxSelected>>", lambda _event: self.draw_chart())

        ttk.Label(controls, text="Y").grid(row=0, column=2, padx=(0, 4), pady=2, sticky="w")
        y_frame = ttk.Frame(controls)
        y_frame.grid(row=0, column=3, rowspan=2, padx=(0, 10), pady=2, sticky="nw")
        self.y_listbox = tk.Listbox(y_frame, selectmode=tk.MULTIPLE, exportselection=False, height=4, width=28)
        y_scroll = ttk.Scrollbar(y_frame, orient="vertical", command=self.y_listbox.yview)
        self.y_listbox.configure(yscrollcommand=y_scroll.set)
        self.y_listbox.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.y_listbox.bind("<<ListboxSelect>>", lambda _event: self.draw_chart())

        ttk.Label(controls, text="Type").grid(row=0, column=4, padx=(0, 4), pady=2, sticky="w")
        self.chart_type_box = ttk.Combobox(
            controls,
            textvariable=self.chart_type_var,
            values=("line", "scatter", "bar"),
            width=10,
            state="readonly",
        )
        self.chart_type_box.grid(row=0, column=5, padx=(0, 10), pady=2, sticky="w")
        self.chart_type_box.bind("<<ComboboxSelected>>", lambda _event: self.draw_chart())

        ttk.Label(controls, text="Step").grid(row=0, column=6, padx=(0, 4), pady=2, sticky="w")
        ttk.Entry(controls, textvariable=self.step_var, width=6).grid(row=0, column=7, padx=(0, 10), pady=2, sticky="w")
        ttk.Label(controls, text="Line").grid(row=0, column=8, padx=(0, 4), pady=2, sticky="w")
        ttk.Entry(controls, textvariable=self.line_width_var, width=6).grid(row=0, column=9, padx=(0, 10), pady=2, sticky="w")
        ttk.Label(controls, text="Point").grid(row=0, column=10, padx=(0, 4), pady=2, sticky="w")
        ttk.Entry(controls, textvariable=self.point_size_var, width=6).grid(row=0, column=11, padx=(0, 10), pady=2, sticky="w")

        options = ttk.Frame(controls)
        options.grid(row=1, column=4, columnspan=5, sticky="w", pady=(4, 0))
        ttk.Checkbutton(options, text="Grid", variable=self.show_grid_var, command=self.draw_chart).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Checkbutton(options, text="Points", variable=self.show_points_var, command=self.draw_chart).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Checkbutton(options, text="Legend", variable=self.show_legend_var, command=self.draw_chart).grid(
            row=0, column=2, padx=(0, 8)
        )
        ttk.Checkbutton(options, text="Smooth", variable=self.smooth_var, command=self.draw_chart).grid(
            row=0, column=3, padx=(0, 8)
        )

        axis_bar = ttk.Frame(controls)
        axis_bar.grid(row=2, column=0, columnspan=14, sticky="ew", pady=(6, 0))
        labels = [("X min", self.x_min_var), ("X max", self.x_max_var), ("Y min", self.y_min_var), ("Y max", self.y_max_var)]
        for index, (label, var) in enumerate(labels):
            ttk.Label(axis_bar, text=label).grid(row=0, column=index * 2, padx=(0, 4))
            ttk.Entry(axis_bar, textvariable=var, width=10).grid(row=0, column=index * 2 + 1, padx=(0, 10))

        action_bar = ttk.Frame(controls)
        action_bar.grid(row=3, column=0, columnspan=16, sticky="ew", pady=(6, 0))
        ttk.Button(action_bar, text="Plot Curves", command=self.refresh_from_source).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(action_bar, text="Delete Plot", command=self.clear_plot).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(action_bar, text="Export Data", command=self.export_plot_data).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(action_bar, text="Export Image", command=self.export_plot_image).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(action_bar, text="Zoom X-", command=lambda: self.zoom_view(1.18, axis="x")).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(action_bar, text="Zoom X+", command=lambda: self.zoom_view(0.85, axis="x")).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(action_bar, text="Zoom Y-", command=lambda: self.zoom_view(1.18, axis="y")).grid(row=0, column=6, padx=(0, 8))
        ttk.Button(action_bar, text="Zoom Y+", command=lambda: self.zoom_view(0.85, axis="y")).grid(row=0, column=7, padx=(0, 8))
        ttk.Button(action_bar, text="Reset View", command=self.reset_view).grid(row=0, column=8, padx=(0, 8))
        ttk.Label(action_bar, text="Text").grid(row=0, column=9, padx=(10, 4), sticky="w")
        ttk.Entry(action_bar, textvariable=self.text_var, width=18).grid(row=0, column=10, padx=(0, 8), sticky="w")
        ttk.Button(action_bar, text="Insert Text", command=self._begin_text_mode).grid(row=0, column=11, padx=(0, 8), sticky="w")

        self.canvas = tk.Canvas(self, bg="white", highlightthickness=1, highlightbackground="#d0d0d0")
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.canvas.bind("<Configure>", lambda _event: self.draw_chart())
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<ButtonPress-1>", self._start_pan)
        self.canvas.bind("<B1-Motion>", self._drag_pan)
        self.canvas.bind("<ButtonRelease-1>", self._end_pan)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)

    def set_table(
        self,
        data: list[list[str]],
        headers: list[str],
        selected_y_names: list[str] | None = None,
    ) -> None:
        self.data = [list(row) for row in data]
        self.headers = headers[:]
        if selected_y_names is not None:
            self._selected_y_cache = [name for name in selected_y_names if name in self.headers[1:]]
        else:
            self._selected_y_cache = self.headers[1:]
        self._view_bounds = None
        self._pan_anchor = None
        self._pan_bounds = None
        self._populate_controls()
        self.draw_chart()

    def clear(self) -> None:
        self.data = []
        self.headers = []
        self._series = []
        self._selected_y_cache = []
        self._view_bounds = None
        self.canvas.delete("all")
        self._draw_message("Import Average Values to plot curves.")

    def clear_plot(self) -> None:
        self._series = []
        self._view_bounds = None
        self._plot_rect = None
        self.canvas.delete("all")
        self._draw_message("Plot cleared. Press Plot Curves to generate again.")

    def refresh_from_source(self) -> None:
        if callable(self._refresh_callback):
            self._refresh_callback()
            return
        self.draw_chart()

    def draw_chart(self) -> None:
        self.canvas.delete("all")
        self._series = []

        if pd is None:
            self._draw_message("pandas is not available.")
            return

        if not self.data or not self.headers or len(self.headers) < 2:
            self._draw_message("Import Average Values first.")
            return

        x_name = self.x_var.get().strip() or self.headers[0]
        if x_name not in self.headers:
            x_name = self.headers[0]
        x_index = self.headers.index(x_name)
        y_names = self._selected_y_names()
        if not y_names:
            self._draw_message("Select one or more Y series.")
            return

        try:
            step = max(1, int(float(self.step_var.get() or "1")))
        except ValueError:
            step = 1

        try:
            line_width = max(1, int(float(self.line_width_var.get() or "2")))
        except ValueError:
            line_width = 2

        try:
            point_size = max(1, int(float(self.point_size_var.get() or "3")))
        except ValueError:
            point_size = 3

        x_values, x_labels = self._extract_x_values(x_index)
        series = self._build_series(x_values, y_names, step)
        if not series:
            self._draw_message("No numeric points to plot.")
            return

        self._series = series
        xs = [x for item in series for x, _ in item.points]
        ys = [y for item in series for _, y in item.points]
        bounds = self._resolve_bounds(xs, ys)
        if bounds is None:
            self._draw_message("No visible data range.")
            return

        x_min, x_max, y_min, y_max = bounds
        width = max(self.canvas.winfo_width(), 600)
        height = max(self.canvas.winfo_height(), 380)
        margin_left, margin_right, margin_top, margin_bottom = 72, 190, 36, 64
        left = margin_left
        top = margin_top
        right = width - margin_right
        bottom = height - margin_bottom
        if right <= left + 20:
            right = left + 20
        if bottom <= top + 20:
            bottom = top + 20

        self._plot_rect = (left, top, right, bottom)
        self.canvas.create_rectangle(left, top, right, bottom, outline="#d0d0d0", fill="#ffffff")
        if self.show_grid_var.get():
            self._draw_grid(left, top, right, bottom)
        self._draw_axes(left, top, right, bottom, x_min, x_max, y_min, y_max)
        self._draw_series(series, left, top, right, bottom, x_min, x_max, y_min, y_max, line_width, point_size)
        self._draw_x_labels(x_values, x_labels, left, right, bottom, x_min, x_max)
        if self.show_legend_var.get():
            self._draw_legend(right + 16, top + 10, series)
        self._draw_titles(width, x_name, y_names)

    def export_plot_data(self) -> None:
        if not self.data or not self._series:
            messagebox.showinfo("No Plot", "Create a plot first.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Export Plot Data",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not file_path:
            return

        try:
            export_df = self._build_export_dataframe()
            export_df.to_csv(file_path, index=False, quoting=csv.QUOTE_MINIMAL)
        except Exception as exc:
            messagebox.showerror("Export Failed", f"Unable to export data:\n{exc}")

    def export_plot_image(self) -> None:
        file_path = filedialog.asksaveasfilename(
            title="Export Plot Image",
            defaultextension=".ps",
            filetypes=[("PostScript files", "*.ps"), ("Encapsulated PostScript", "*.eps"), ("All files", "*.*")],
        )
        if not file_path:
            return
        try:
            self.canvas.postscript(file=file_path, colormode="color")
        except Exception as exc:
            messagebox.showerror("Export Failed", f"Unable to export image:\n{exc}")

    def reset_view(self) -> None:
        self._view_bounds = None
        self.x_min_var.set("")
        self.x_max_var.set("")
        self.y_min_var.set("")
        self.y_max_var.set("")
        self.draw_chart()

    def zoom_view(self, factor: float, axis: str = "both") -> None:
        if self._plot_rect is None:
            self.draw_chart()
        if self._plot_rect is None:
            return
        x_min, x_max, y_min, y_max = self._current_bounds()
        if x_min is None:
            return
        center_x = (x_min + x_max) / 2
        center_y = (y_min + y_max) / 2
        new_x_min, new_x_max = x_min, x_max
        new_y_min, new_y_max = y_min, y_max
        if axis in {"both", "x"}:
            new_x_min, new_x_max = self._zoom_range(x_min, x_max, center_x, factor)
        if axis in {"both", "y"}:
            new_y_min, new_y_max = self._zoom_range(y_min, y_max, center_y, factor)
        self._view_bounds = (new_x_min, new_x_max, new_y_min, new_y_max)
        self._sync_bound_entries()
        self.draw_chart()

    def _begin_text_mode(self) -> None:
        text = self.text_var.get().strip()
        if not text:
            messagebox.showinfo("No Text", "Type some text first.")
            return
        self._text_mode = True
        messagebox.showinfo("Insert Text", "Click on the chart where you want the text to appear.")

    def _on_canvas_click(self, event: tk.Event) -> str | None:
        if not self._text_mode:
            return None
        text = self.text_var.get().strip()
        if not text:
            self._text_mode = False
            return None
        self.canvas.create_text(event.x, event.y, text=text, fill="#111111", font=("Segoe UI", 10, "bold"), anchor="center")
        self._text_mode = False
        return "break"

    def _populate_controls(self) -> None:
        self.x_box["values"] = self.headers[:1]
        if self.headers:
            self.x_var.set(self.headers[0])
            self.y_listbox.delete(0, tk.END)
            for header in self.headers[1:]:
                self.y_listbox.insert(tk.END, header)
            names = self._selected_y_cache or self.headers[1:]
            self._select_y_names([name for name in names if name in self.headers[1:]])

    def _selected_y_names(self) -> list[str]:
        selected = [self.y_listbox.get(index) for index in self.y_listbox.curselection()]
        if selected:
            self._selected_y_cache = selected
            return selected
        return [name for name in self._selected_y_cache if name in self.headers[1:]]

    def _select_y_names(self, names: list[str]) -> None:
        self._selected_y_cache = [name for name in names if name in self.headers[1:]]
        self.y_listbox.selection_clear(0, tk.END)
        values = [self.y_listbox.get(index) for index in range(self.y_listbox.size())]
        for name in names:
            if name in values:
                self.y_listbox.selection_set(values.index(name))

    def set_y_names(self, names: list[str]) -> None:
        self._select_y_names(names)
        self.draw_chart()

    def _extract_x_values(self, column_index: int) -> tuple[list[float], list[str]]:
        values: list[float] = []
        labels: list[str] = []
        for row in self.data:
            if column_index >= len(row):
                continue
            raw = row[column_index]
            labels.append(str(raw))
            value = self._to_float(raw)
            if value is None:
                value = float(len(values))
            values.append(value)
        return values, labels

    def _build_series(self, x_values: list[float], y_names: list[str], step: int) -> list[PlotSeries]:
        series: list[PlotSeries] = []
        for index, y_name in enumerate(y_names):
            if y_name not in self.headers:
                continue
            y_index = self.headers.index(y_name)
            points: list[tuple[float, float]] = []
            for row_index, row in enumerate(self.data):
                if row_index >= len(x_values) or row_index % step != 0:
                    continue
                if y_index >= len(row):
                    continue
                x_value = x_values[row_index]
                y_value = self._to_float(row[y_index])
                if y_value is None:
                    continue
                points.append((x_value, y_value))
            if points:
                series.append(PlotSeries(name=y_name, points=points, color=self._series_color(index, len(y_names))))
        return series

    def _build_export_dataframe(self) -> pd.DataFrame:
        x_name = self.x_var.get().strip() or self.headers[0]
        x_index = self.headers.index(x_name) if x_name in self.headers else 0
        y_names = [series.name for series in self._series]
        rows: dict[str, list[object]] = {x_name: []}
        for y_name in y_names:
            rows[y_name] = []

        for row in self.data:
            if x_index >= len(row):
                continue
            rows[x_name].append(row[x_index])
            for y_name in y_names:
                y_index = self.headers.index(y_name)
                rows[y_name].append(row[y_index] if y_index < len(row) else "")

        return pd.DataFrame(rows)

    def _resolve_bounds(self, xs: list[float], ys: list[float]) -> tuple[float, float, float, float] | None:
        manual = self._manual_bounds()
        if manual is not None:
            self._view_bounds = manual
            return manual
        if self._view_bounds is not None:
            return self._view_bounds
        if not xs or not ys:
            return None
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        if math.isclose(x_min, x_max):
            x_min -= 1
            x_max += 1
        if math.isclose(y_min, y_max):
            y_min -= 1
            y_max += 1
        return x_min, x_max, y_min, y_max

    def _manual_bounds(self) -> tuple[float, float, float, float] | None:
        try:
            x_min = float(self.x_min_var.get()) if self.x_min_var.get().strip() else None
            x_max = float(self.x_max_var.get()) if self.x_max_var.get().strip() else None
            y_min = float(self.y_min_var.get()) if self.y_min_var.get().strip() else None
            y_max = float(self.y_max_var.get()) if self.y_max_var.get().strip() else None
        except ValueError:
            return None
        if None in {x_min, x_max, y_min, y_max}:
            return None
        return x_min, x_max, y_min, y_max

    def _draw_grid(self, left: float, top: float, right: float, bottom: float) -> None:
        for i in range(1, 6):
            x = left + (right - left) * i / 6
            y = top + (bottom - top) * i / 6
            self.canvas.create_line(x, top, x, bottom, fill="#efefef")
            self.canvas.create_line(left, y, right, y, fill="#efefef")

    def _draw_axes(self, left: float, top: float, right: float, bottom: float, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        self.canvas.create_line(left, bottom, right, bottom, fill="#444444", width=2)
        self.canvas.create_line(left, top, left, bottom, fill="#444444", width=2)
        for value in self._nice_ticks(x_min, x_max):
            px = self._x_to_canvas(value, left, right, x_min, x_max)
            self.canvas.create_line(px, bottom, px, bottom + 6, fill="#444444")
            self.canvas.create_text(px, bottom + 18, text=self._format_tick(value), fill="#333333", font=("Segoe UI", 9))
        for value in self._nice_ticks(y_min, y_max):
            py = self._y_to_canvas(value, top, bottom, y_min, y_max)
            self.canvas.create_line(left - 6, py, left, py, fill="#444444")
            self.canvas.create_text(left - 10, py, text=self._format_tick(value), fill="#333333", font=("Segoe UI", 9), anchor="e")

    def _draw_series(
        self,
        series: list[PlotSeries],
        left: float,
        top: float,
        right: float,
        bottom: float,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        line_width: int,
        point_size: int,
    ) -> None:
        chart_type = self.chart_type_var.get()
        for item in series:
            if chart_type == "bar":
                self._draw_bar_series(item.points, left, top, right, bottom, x_min, x_max, y_min, y_max, item.color)
                continue
            render_points = item.points
            if self.smooth_var.get() and len(item.points) >= 4:
                render_points = self._smooth_points(item.points)
            coords: list[float] = []
            for x_value, y_value in render_points:
                coords.extend([
                    self._x_to_canvas(x_value, left, right, x_min, x_max),
                    self._y_to_canvas(y_value, top, bottom, y_min, y_max),
                ])
            if len(coords) >= 4:
                self.canvas.create_line(*coords, fill=item.color, width=line_width, smooth=False)
            if self.show_points_var.get() or chart_type == "scatter":
                for idx in range(0, len(coords), 2):
                    x = coords[idx]
                    y = coords[idx + 1]
                    self.canvas.create_oval(x - point_size, y - point_size, x + point_size, y + point_size, fill=item.color, outline="")

    def _draw_bar_series(
        self,
        points: list[tuple[float, float]],
        left: float,
        top: float,
        right: float,
        bottom: float,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        color: str,
    ) -> None:
        width = max(4.0, min(24.0, (right - left) / max(len(points), 1) * 0.55))
        for x_value, y_value in points:
            x = self._x_to_canvas(x_value, left, right, x_min, x_max)
            y = self._y_to_canvas(y_value, top, bottom, y_min, y_max)
            self.canvas.create_rectangle(x - width / 2, y, x + width / 2, bottom, fill=color, outline="")

    def _draw_legend(self, x: float, y: float, series: list[PlotSeries]) -> None:
        self.canvas.create_text(x, y, anchor="nw", text="Legend", font=("Segoe UI", 10, "bold"), fill="#333333")
        y += 24
        for item in series:
            self.canvas.create_rectangle(x, y + 4, x + 16, y + 16, fill=item.color, outline=item.color)
            self.canvas.create_text(x + 22, y + 10, anchor="w", text=item.name, font=("Segoe UI", 9), fill="#222222")
            y += 24

    def _draw_titles(self, width: int, x_name: str, y_names: list[str]) -> None:
        self.canvas.create_text(
            width / 2,
            14,
            text=f"{', '.join(y_names)} vs {x_name}",
            font=("Segoe UI", 11, "bold"),
            fill="#222222",
        )
        self.canvas.create_text(20, 18, text="Average", angle=90, font=("Segoe UI", 10, "bold"), fill="#222222")

    def _draw_x_labels(self, x_values: list[float], labels: list[str], left: float, right: float, bottom: float, x_min: float, x_max: float) -> None:
        if not x_values:
            return
        tick_values = self._nice_ticks(x_min, x_max, count=6)
        label_map = {value: label for value, label in zip(x_values, labels)}
        for value in tick_values:
            x = self._x_to_canvas(value, left, right, x_min, x_max)
            label = label_map.get(value, self._format_tick(value))
            if len(label) > 16:
                label = label[:16] + "..."
            self.canvas.create_text(x, bottom + 10, text=label, angle=25, anchor="n", fill="#555555")

    def _draw_message(self, text: str) -> None:
        self.canvas.create_text(20, 20, anchor="nw", text=text, fill="#666666", font=("Segoe UI", 11))

    def _start_pan(self, event: tk.Event) -> None:
        if self._plot_rect is None or self._view_bounds is None:
            return
        self._pan_anchor = (event.x, event.y)
        self._pan_bounds = self._view_bounds

    def _drag_pan(self, event: tk.Event) -> None:
        if self._pan_anchor is None or self._pan_bounds is None or self._plot_rect is None:
            return
        left, top, right, bottom = self._plot_rect
        width = max(right - left, 1.0)
        height = max(bottom - top, 1.0)
        dx = event.x - self._pan_anchor[0]
        dy = event.y - self._pan_anchor[1]
        x_min, x_max, y_min, y_max = self._pan_bounds
        x_shift = -dx * (x_max - x_min) / width
        y_shift = dy * (y_max - y_min) / height
        self._view_bounds = (x_min + x_shift, x_max + x_shift, y_min + y_shift, y_max + y_shift)
        self._sync_bound_entries()
        self.draw_chart()

    def _end_pan(self, _event: tk.Event) -> None:
        self._pan_anchor = None
        self._pan_bounds = None

    def _on_mousewheel(self, event: tk.Event) -> str | None:
        if self._plot_rect is None or self._view_bounds is None:
            return None
        shift_down = bool(getattr(event, "state", 0) & 0x0001)
        ctrl_down = bool(getattr(event, "state", 0) & 0x0004)
        factor = 1.12 if getattr(event, "delta", 0) < 0 or getattr(event, "num", 0) == 5 else 0.88
        left, top, right, bottom = self._plot_rect
        x_min, x_max, y_min, y_max = self._view_bounds
        mouse_x = min(max(event.x, left), right)
        mouse_y = min(max(event.y, top), bottom)
        x_anchor = self._canvas_to_x(mouse_x, left, right, x_min, x_max)
        y_anchor = self._canvas_to_y(mouse_y, top, bottom, y_min, y_max)
        new_x_min, new_x_max = x_min, x_max
        new_y_min, new_y_max = y_min, y_max
        if ctrl_down and not shift_down:
            new_x_min, new_x_max = self._zoom_range(x_min, x_max, x_anchor, factor)
        elif shift_down and not ctrl_down:
            new_y_min, new_y_max = self._zoom_range(y_min, y_max, y_anchor, factor)
        else:
            new_x_min, new_x_max = self._zoom_range(x_min, x_max, x_anchor, factor)
            new_y_min, new_y_max = self._zoom_range(y_min, y_max, y_anchor, factor)
        self._view_bounds = (new_x_min, new_x_max, new_y_min, new_y_max)
        self._sync_bound_entries()
        self.draw_chart()
        return "break"

    def _zoom_range(self, minimum: float, maximum: float, anchor: float, factor: float) -> tuple[float, float]:
        if math.isclose(minimum, maximum):
            return minimum - 1, maximum + 1
        new_min = anchor + (minimum - anchor) * factor
        new_max = anchor + (maximum - anchor) * factor
        if math.isclose(new_min, new_max):
            new_max = new_min + 1
        return new_min, new_max

    def _current_bounds(self) -> tuple[float | None, float | None, float | None, float | None]:
        if self._view_bounds is not None:
            return self._view_bounds
        if not self._series:
            return None, None, None, None
        xs = [x for item in self._series for x, _ in item.points]
        ys = [y for item in self._series for _, y in item.points]
        bounds = self._resolve_bounds(xs, ys)
        if bounds is None:
            return None, None, None, None
        return bounds

    def _sync_bound_entries(self) -> None:
        if self._view_bounds is None:
            return
        x_min, x_max, y_min, y_max = self._view_bounds
        self.x_min_var.set(self._format_tick(x_min))
        self.x_max_var.set(self._format_tick(x_max))
        self.y_min_var.set(self._format_tick(y_min))
        self.y_max_var.set(self._format_tick(y_max))

    def _x_to_canvas(self, value: float, left: float, right: float, x_min: float, x_max: float) -> float:
        span = x_max - x_min
        if math.isclose(span, 0.0):
            return (left + right) / 2
        return left + (value - x_min) * (right - left) / span

    def _y_to_canvas(self, value: float, top: float, bottom: float, y_min: float, y_max: float) -> float:
        span = y_max - y_min
        if math.isclose(span, 0.0):
            return (top + bottom) / 2
        return bottom - (value - y_min) * (bottom - top) / span

    def _canvas_to_x(self, px: float, left: float, right: float, x_min: float, x_max: float) -> float:
        span = right - left
        if math.isclose(span, 0.0):
            return x_min
        return x_min + (px - left) * (x_max - x_min) / span

    def _canvas_to_y(self, py: float, top: float, bottom: float, y_min: float, y_max: float) -> float:
        span = bottom - top
        if math.isclose(span, 0.0):
            return y_min
        return y_max - (py - top) * (y_max - y_min) / span

    def _nice_ticks(self, minimum: float, maximum: float, count: int = 5) -> list[float]:
        if count < 2:
            return [minimum, maximum]
        if math.isclose(minimum, maximum):
            return [minimum]
        span = maximum - minimum
        nice_span = self._nice_number(span, False)
        step = self._nice_number(nice_span / (count - 1), True)
        tick_min = math.floor(minimum / step) * step
        tick_max = math.ceil(maximum / step) * step
        ticks: list[float] = []
        value = tick_min
        while value <= tick_max + (step * 0.5):
            ticks.append(round(value, 12))
            value += step
        return ticks

    def _nice_number(self, value: float, round_: bool) -> float:
        if value == 0:
            return 1.0
        exponent = math.floor(math.log10(abs(value)))
        fraction = abs(value) / (10**exponent)
        if round_:
            if fraction < 1.5:
                nice_fraction = 1
            elif fraction < 3:
                nice_fraction = 2
            elif fraction < 7:
                nice_fraction = 5
            else:
                nice_fraction = 10
        else:
            if fraction <= 1:
                nice_fraction = 1
            elif fraction <= 2:
                nice_fraction = 2
            elif fraction <= 5:
                nice_fraction = 5
            else:
                nice_fraction = 10
        return nice_fraction * (10**exponent)

    def _format_tick(self, value: float) -> str:
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.4g}"

    def _to_float(self, value: object) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _series_color(self, index: int, total: int) -> str:
        total = max(total, 1)
        hue = (index / total) % 1.0
        red, green, blue = colorsys.hsv_to_rgb(hue, 0.72, 0.88)
        return f"#{int(red * 255):02x}{int(green * 255):02x}{int(blue * 255):02x}"

    def _smooth_points(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(points) < 4:
            return points
        smoothed: list[tuple[float, float]] = []
        for index in range(len(points) - 1):
            p0 = points[index - 1] if index > 0 else points[index]
            p1 = points[index]
            p2 = points[index + 1]
            p3 = points[index + 2] if index + 2 < len(points) else p2
            for step in range(12):
                t = step / 12
                tt = t * t
                ttt = tt * t
                x = 0.5 * (
                    (2 * p1[0])
                    + (-p0[0] + p2[0]) * t
                    + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * tt
                    + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * ttt
                )
                y = 0.5 * (
                    (2 * p1[1])
                    + (-p0[1] + p2[1]) * t
                    + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * tt
                    + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * ttt
                )
                smoothed.append((x, y))
        smoothed.append(points[-1])
        return smoothed
