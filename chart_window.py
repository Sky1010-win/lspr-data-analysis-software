from __future__ import annotations

import csv
import colorsys
import json
import math
from dataclasses import dataclass
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - handled by the main app.
    pd = None

try:
    from PIL import ImageGrab
except ModuleNotFoundError:  # pragma: no cover - loaded lazily when exporting.
    ImageGrab = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:  # pragma: no cover - loaded lazily when exporting.
    Image = None
    ImageDraw = None
    ImageFont = None


APP_BUTTON_WIDTH = 13
PRESET_FILE_NAME = "plot_format_presets.json"


@dataclass(slots=True)
class PlotSeries:
    name: str
    label: str
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
        self._series_labels: dict[str, str] = {}
        self._series_colors: dict[str, str] = {}
        self._series_widths: dict[str, str] = {}
        self._stage_regions: list[tuple[float, float, str, str]] = []
        self._annotations: list[dict[str, object]] = []
        self._lspr_shift_items: list[dict[str, object]] = []
        self._right_label_positions: dict[str, tuple[float, float]] = {}
        self._draggables: list[dict[str, object]] = []
        self._drag_target: dict[str, object] | None = None
        self._drag_offset: tuple[float, float] = (0.0, 0.0)
        self._drag_last: tuple[float, float] | None = None
        self._legend_position: tuple[float, float] | None = None
        self._plot_rect: tuple[float, float, float, float] | None = None
        self._view_bounds: tuple[float, float, float, float] | None = None
        self._pan_anchor: tuple[int, int] | None = None
        self._pan_bounds: tuple[float, float, float, float] | None = None
        self._draw_after_id: str | None = None

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
        self.running_buffer_var = tk.StringVar(value="5*SSC")
        self.lspr_font_size_var = tk.StringVar(value="10")
        self.title_var = tk.StringVar(value="")
        self.x_title_var = tk.StringVar(value="Time [s]")
        self.y_title_var = tk.StringVar(value=self._locked_y_axis_title())
        self.stage_text_var = tk.StringVar(value="")
        self.smooth_window_var = tk.IntVar(value=0)
        self.smooth_window_label_var = tk.StringVar(value="Smooth 0")
        self.grid_density_var = tk.IntVar(value=6)
        self.x_tick_count_var = tk.IntVar(value=8)
        self.y_tick_count_var = tk.IntVar(value=8)
        self.grid_color_var = tk.StringVar(value="#eeeeee")
        self.grid_width_var = tk.StringVar(value="1")
        self.grid_style_var = tk.StringVar(value="solid")
        self.tick_font_size_var = tk.StringVar(value="9")
        self.tick_bold_var = tk.BooleanVar(value=False)
        self.stage_opacity_var = tk.IntVar(value=70)
        self.stage_opacity_label_var = tk.StringVar(value="Background 70%")
        self.format_preset_var = tk.StringVar(value="")
        self._format_presets: dict[str, dict] = {}
        self.running_buffer_box: ttk.Combobox | None = None
        self.show_points_var = tk.BooleanVar(value=True)
        self.show_grid_var = tk.BooleanVar(value=True)
        self.show_legend_var = tk.BooleanVar(value=True)
        self.show_right_labels_var = tk.BooleanVar(value=True)
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
        self.x_box.bind("<<ComboboxSelected>>", self._on_plot_selection_change)

        ttk.Label(controls, text="Y").grid(row=0, column=2, padx=(0, 4), pady=2, sticky="w")
        y_frame = ttk.Frame(controls)
        y_frame.grid(row=0, column=3, rowspan=2, padx=(0, 10), pady=2, sticky="nw")
        self.y_listbox = tk.Listbox(y_frame, selectmode=tk.MULTIPLE, exportselection=False, height=4, width=28)
        y_scroll = ttk.Scrollbar(y_frame, orient="vertical", command=self.y_listbox.yview)
        self.y_listbox.configure(yscrollcommand=y_scroll.set)
        self.y_listbox.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.y_listbox.bind("<<ListboxSelect>>", self._on_plot_selection_change)

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
        options.grid(row=1, column=4, columnspan=12, sticky="ew", pady=(4, 0))
        options.columnconfigure(6, weight=1)
        ttk.Checkbutton(options, text="Grid", variable=self.show_grid_var, command=self.draw_chart).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Checkbutton(options, text="Points", variable=self.show_points_var, command=self.draw_chart).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Checkbutton(options, text="Legend", variable=self.show_legend_var, command=self.draw_chart).grid(
            row=0, column=2, padx=(0, 8)
        )
        ttk.Checkbutton(options, text="Smooth", variable=self.smooth_var, command=self._on_smooth_toggle).grid(
            row=0, column=3, padx=(0, 8)
        )
        ttk.Label(options, textvariable=self.smooth_window_label_var).grid(row=0, column=4, padx=(6, 4))
        ttk.Scale(
            options,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.smooth_window_var,
            command=self._on_smooth_window_change,
            length=220,
        ).grid(row=0, column=5, padx=(0, 8), sticky="ew")
        ttk.Label(options, textvariable=self.stage_opacity_label_var).grid(row=0, column=6, padx=(8, 4))
        ttk.Scale(
            options,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.stage_opacity_var,
            command=self._on_stage_opacity_change,
            length=160,
        ).grid(row=0, column=7, padx=(0, 8), sticky="ew")

        axis_bar = ttk.Frame(controls)
        axis_bar.grid(row=2, column=0, columnspan=14, sticky="ew", pady=(6, 0))
        labels = [("X min", self.x_min_var), ("X max", self.x_max_var), ("Y min", self.y_min_var), ("Y max", self.y_max_var)]
        for index, (label, var) in enumerate(labels):
            ttk.Label(axis_bar, text=label).grid(row=0, column=index * 2, padx=(0, 4))
            ttk.Entry(axis_bar, textvariable=var, width=10).grid(row=0, column=index * 2 + 1, padx=(0, 10))
        ttk.Label(axis_bar, text="Grid").grid(row=0, column=8, padx=(4, 4))
        grid_spin = ttk.Spinbox(
            axis_bar,
            from_=2,
            to=30,
            textvariable=self.grid_density_var,
            width=5,
            command=self._on_axis_detail_change,
        )
        grid_spin.grid(row=0, column=9, padx=(0, 10))
        ttk.Label(axis_bar, text="X ticks").grid(row=0, column=10, padx=(0, 4))
        x_tick_spin = ttk.Spinbox(
            axis_bar,
            from_=2,
            to=30,
            textvariable=self.x_tick_count_var,
            width=5,
            command=self._on_axis_detail_change,
        )
        x_tick_spin.grid(row=0, column=11, padx=(0, 10))
        ttk.Label(axis_bar, text="Y ticks").grid(row=0, column=12, padx=(0, 4))
        y_tick_spin = ttk.Spinbox(
            axis_bar,
            from_=2,
            to=30,
            textvariable=self.y_tick_count_var,
            width=5,
            command=self._on_axis_detail_change,
        )
        y_tick_spin.grid(row=0, column=13, padx=(0, 10))
        for spin in (grid_spin, x_tick_spin, y_tick_spin):
            spin.bind("<Return>", self._on_axis_detail_change)
            spin.bind("<FocusOut>", self._on_axis_detail_change)

        action_bar = ttk.Frame(controls)
        action_bar.grid(row=3, column=0, columnspan=16, sticky="ew", pady=(6, 0))
        ttk.Button(action_bar, text="Delete Plot", command=self.clear_plot, width=APP_BUTTON_WIDTH).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(action_bar, text="Export Data", command=self.export_plot_data, width=APP_BUTTON_WIDTH).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(action_bar, text="Export Image", command=self.export_plot_image, width=APP_BUTTON_WIDTH).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(action_bar, text="Plot Settings", command=self.open_plot_settings, width=APP_BUTTON_WIDTH).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(action_bar, text="Legend Colors", command=lambda: self.open_plot_settings("Curves"), width=APP_BUTTON_WIDTH).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(action_bar, text="Zoom X-", command=lambda: self.zoom_view(1.18, axis="x"), width=APP_BUTTON_WIDTH).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(action_bar, text="Zoom X+", command=lambda: self.zoom_view(0.85, axis="x"), width=APP_BUTTON_WIDTH).grid(row=0, column=6, padx=(0, 8))
        ttk.Button(action_bar, text="Zoom Y-", command=lambda: self.zoom_view(1.18, axis="y"), width=APP_BUTTON_WIDTH).grid(row=0, column=7, padx=(0, 8))
        ttk.Button(action_bar, text="Zoom Y+", command=lambda: self.zoom_view(0.85, axis="y"), width=APP_BUTTON_WIDTH).grid(row=0, column=8, padx=(0, 8))
        ttk.Button(action_bar, text="Reset View", command=self.reset_view, width=APP_BUTTON_WIDTH).grid(row=0, column=9, padx=(0, 8))
        ttk.Label(action_bar, text="Text").grid(row=1, column=0, padx=(0, 4), pady=(6, 0), sticky="w")
        ttk.Entry(action_bar, textvariable=self.text_var, width=34).grid(row=1, column=1, columnspan=2, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Insert Text", command=self._begin_text_mode, width=APP_BUTTON_WIDTH).grid(row=1, column=3, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="Format").grid(row=1, column=4, padx=(8, 4), pady=(6, 0), sticky="w")
        self.format_box = ttk.Combobox(action_bar, textvariable=self.format_preset_var, width=18, state="readonly")
        self.format_box.grid(row=1, column=5, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Save Format", command=self.save_format_preset, width=APP_BUTTON_WIDTH).grid(row=1, column=6, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Apply Format", command=self.apply_selected_format_preset, width=APP_BUTTON_WIDTH).grid(row=1, column=7, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="Running Buffer").grid(row=2, column=0, padx=(0, 4), pady=(6, 0), sticky="w")
        self.running_buffer_box = ttk.Combobox(
            action_bar,
            textvariable=self.running_buffer_var,
            width=22,
            state="readonly",
        )
        self.running_buffer_box.grid(row=2, column=1, padx=(0, 8), pady=(6, 0), sticky="w")
        self.running_buffer_box.bind("<Return>", lambda _event: self.calculate_lspr_shift_for_all_series())
        self.running_buffer_box.bind("<<ComboboxSelected>>", lambda _event: self.clear_lspr_shift())
        ttk.Button(action_bar, text="LSPR Shift", command=self.calculate_lspr_shift_for_all_series, width=APP_BUTTON_WIDTH).grid(row=2, column=2, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Clear LSPR", command=self.clear_lspr_shift, width=APP_BUTTON_WIDTH).grid(row=2, column=3, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="LSPR Font").grid(row=2, column=4, padx=(8, 4), pady=(6, 0), sticky="w")
        lspr_font_spin = ttk.Spinbox(
            action_bar,
            from_=7,
            to=24,
            textvariable=self.lspr_font_size_var,
            width=5,
            command=self.draw_chart,
        )
        lspr_font_spin.grid(row=2, column=5, padx=(0, 8), pady=(6, 0), sticky="w")
        lspr_font_spin.bind("<Return>", lambda _event: self.draw_chart())
        lspr_font_spin.bind("<FocusOut>", lambda _event: self.draw_chart())
        self._load_format_presets()

        self.canvas = tk.Canvas(self, bg="white", highlightthickness=1, highlightbackground="#d0d0d0")
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.canvas.bind("<Configure>", lambda _event: self.schedule_draw())
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click)
        self.canvas.bind("<Button-2>", self._on_canvas_right_click)
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
        stage_regions: list[tuple[float, float, str, str]] | None = None,
    ) -> None:
        self.data = [list(row) for row in data]
        self.headers = headers[:]
        if stage_regions is not None:
            self._stage_regions = stage_regions[:]
            self.stage_text_var.set(
                "\n".join(f"{start},{end},{label},{color}" for start, end, label, color in self._stage_regions)
            )
        self._refresh_running_buffer_options()
        if selected_y_names is not None:
            self._selected_y_cache = [name for name in selected_y_names if name in self.headers[1:]]
        else:
            self._selected_y_cache = self.headers[1:]
        self._view_bounds = None
        self._pan_anchor = None
        self._pan_bounds = None
        self._lspr_shift_items = []
        self._populate_controls()
        self.schedule_draw()

    def clear(self) -> None:
        self.data = []
        self.headers = []
        self._series = []
        self._selected_y_cache = []
        self._stage_regions = []
        self._annotations = []
        self._lspr_shift_items = []
        self._right_label_positions = {}
        self._draggables = []
        self._drag_target = None
        self._view_bounds = None
        self._refresh_running_buffer_options()
        self.canvas.delete("all")
        self._draw_message("Import Average Values to plot curves.")

    def clear_plot(self) -> None:
        self._series = []
        self._lspr_shift_items = []
        self._view_bounds = None
        self._plot_rect = None
        self.canvas.delete("all")
        self._draw_message("Plot cleared. Press Plot Curves to generate again.")

    def clear_lspr_shift(self) -> None:
        self._lspr_shift_items = []
        self.draw_chart()

    def save_format_preset(self) -> None:
        name = self._ask_preset_name(self.format_preset_var.get().strip(), mode="save")
        if not name:
            return
        self._format_presets[name] = self._collect_format_preset()
        self._write_format_presets()
        self._refresh_format_box(name)
        messagebox.showinfo("Format Saved", f"Plot format saved as:\n{name}")

    def apply_selected_format_preset(self) -> None:
        name = self.format_preset_var.get().strip()
        if not name:
            messagebox.showinfo("No Format", "Please select a saved format first.")
            return
        preset = self._format_presets.get(name)
        if not preset:
            messagebox.showinfo("Format Not Found", "The selected format was not found.")
            self._load_format_presets()
            return
        self._apply_format_preset(preset)
        self.format_preset_var.set(name)
        self.schedule_draw()

    def _ask_preset_name(self, initial_name: str = "", mode: str = "save") -> str:
        window = tk.Toplevel(self)
        window.title("Save Plot Format")
        window.transient(self.winfo_toplevel())
        window.grab_set()
        window.resizable(False, False)
        names = sorted(self._format_presets)
        default_name = initial_name or f"Format {len(self._format_presets) + 1}"
        name_var = tk.StringVar(value=default_name)
        ttk.Label(window, text="Format name").grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")
        entry = ttk.Combobox(window, textvariable=name_var, values=names, width=32, state="normal")
        entry.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        result = {"name": ""}

        def confirm() -> None:
            chosen = name_var.get().strip()
            if not chosen:
                messagebox.showinfo("No Name", "Please enter a format name.", parent=window)
                return
            result["name"] = chosen
            window.destroy()

        def cancel() -> None:
            window.destroy()

        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="e")
        ttk.Button(buttons, text="Save", command=confirm, width=APP_BUTTON_WIDTH).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Cancel", command=cancel, width=APP_BUTTON_WIDTH).grid(row=0, column=1)
        entry.focus_set()
        entry.selection_range(0, tk.END)
        entry.bind("<Return>", lambda _event: confirm())
        window.wait_window()
        return result["name"]

    def _preset_path(self) -> Path:
        return Path(__file__).with_name(PRESET_FILE_NAME)

    def _load_format_presets(self) -> None:
        path = self._preset_path()
        presets: dict[str, dict] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    presets = {str(key): value for key, value in raw.items() if isinstance(value, dict)}
            except Exception:
                presets = {}
        self._format_presets = presets
        self._refresh_format_box(self.format_preset_var.get())

    def _write_format_presets(self) -> None:
        self._preset_path().write_text(
            json.dumps(self._format_presets, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _refresh_format_box(self, selected: str = "") -> None:
        names = sorted(self._format_presets)
        if hasattr(self, "format_box"):
            self.format_box["values"] = names
        if selected in self._format_presets:
            self.format_preset_var.set(selected)
        elif names and not self.format_preset_var.get():
            self.format_preset_var.set(names[0])

    def _collect_format_preset(self) -> dict:
        return {
            "title": self.title_var.get(),
            "x_title": self.x_title_var.get(),
            "running_buffer": self.running_buffer_var.get(),
            "lspr_font_size": self.lspr_font_size_var.get(),
            "chart_type": self.chart_type_var.get(),
            "line_width": self.line_width_var.get(),
            "point_size": self.point_size_var.get(),
            "step": self.step_var.get(),
            "show_points": self.show_points_var.get(),
            "show_grid": self.show_grid_var.get(),
            "show_legend": self.show_legend_var.get(),
            "show_right_labels": self.show_right_labels_var.get(),
            "smooth": self.smooth_var.get(),
            "smooth_window": self.smooth_window_var.get(),
            "grid_density": self.grid_density_var.get(),
            "x_tick_count": self.x_tick_count_var.get(),
            "y_tick_count": self.y_tick_count_var.get(),
            "grid_color": self.grid_color_var.get(),
            "grid_width": self.grid_width_var.get(),
            "grid_style": self.grid_style_var.get(),
            "tick_font_size": self.tick_font_size_var.get(),
            "tick_bold": self.tick_bold_var.get(),
            "stage_opacity": self.stage_opacity_var.get(),
            "series_labels": dict(self._series_labels),
            "series_colors": dict(self._series_colors),
            "series_widths": dict(self._series_widths),
            "legend_position": list(self._legend_position) if self._legend_position else None,
            "right_label_positions": {key: list(value) for key, value in self._right_label_positions.items()},
            "annotations": [dict(item) for item in self._annotations],
        }

    def _apply_format_preset(self, preset: dict) -> None:
        self.title_var.set(str(preset.get("title", "")))
        self.x_title_var.set(str(preset.get("x_title", "Time [s]")))
        self.running_buffer_var.set(str(preset.get("running_buffer", "5*SSC")) or "5*SSC")
        self.lspr_font_size_var.set(str(preset.get("lspr_font_size", "10")) or "10")
        self.y_title_var.set(self._locked_y_axis_title())
        self.chart_type_var.set(str(preset.get("chart_type", "line")))
        self.line_width_var.set(str(preset.get("line_width", "2")))
        self.point_size_var.set(str(preset.get("point_size", "3")))
        self.step_var.set(str(preset.get("step", "1")))
        self.show_points_var.set(bool(preset.get("show_points", True)))
        self.show_grid_var.set(bool(preset.get("show_grid", True)))
        self.show_legend_var.set(bool(preset.get("show_legend", True)))
        self.show_right_labels_var.set(bool(preset.get("show_right_labels", True)))
        self.smooth_var.set(bool(preset.get("smooth", False)))
        self.smooth_window_var.set(int(preset.get("smooth_window", 0) or 0))
        self.smooth_window_label_var.set(f"Smooth {self.smooth_window_var.get()}")
        self.grid_density_var.set(int(preset.get("grid_density", 6) or 6))
        self.x_tick_count_var.set(int(preset.get("x_tick_count", 8) or 8))
        self.y_tick_count_var.set(int(preset.get("y_tick_count", 8) or 8))
        self.grid_color_var.set(str(preset.get("grid_color", "#eeeeee")))
        self.grid_width_var.set(str(preset.get("grid_width", "1")))
        self.grid_style_var.set(str(preset.get("grid_style", "solid")))
        self.tick_font_size_var.set(str(preset.get("tick_font_size", "9")))
        self.tick_bold_var.set(bool(preset.get("tick_bold", False)))
        self.stage_opacity_var.set(max(0, min(100, int(preset.get("stage_opacity", 70) or 70))))
        self.stage_opacity_label_var.set(f"Background {self.stage_opacity_var.get()}%")

        self._series_labels.update(self._string_dict(preset.get("series_labels", {})))
        self._series_colors.update(self._string_dict(preset.get("series_colors", {})))
        self._series_widths.update(self._string_dict(preset.get("series_widths", {})))
        legend_position = preset.get("legend_position")
        self._legend_position = self._point_tuple(legend_position)
        raw_positions = preset.get("right_label_positions", {})
        if not isinstance(raw_positions, dict):
            raw_positions = {}
        self._right_label_positions = {
            str(key): value
            for key, raw in raw_positions.items()
            if (value := self._point_tuple(raw)) is not None
        }
        annotations = preset.get("annotations", [])
        self._annotations = [
            {"x": float(item.get("x", 0)), "y": float(item.get("y", 0)), "text": str(item.get("text", ""))}
            for item in annotations
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ]

    def _string_dict(self, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(key): str(item) for key, item in value.items()}

    def _point_tuple(self, value: object) -> tuple[float, float] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None

    def open_plot_settings(self, initial_tab: str = "General") -> None:
        window = tk.Toplevel(self)
        window.title("Plot Settings")
        window.transient(self.winfo_toplevel())
        window.geometry("760x520")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(window)
        notebook.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        general = ttk.Frame(notebook, padding=10)
        curves = ttk.Frame(notebook, padding=10)
        stages = ttk.Frame(notebook, padding=10)
        notebook.add(general, text="General")
        notebook.add(curves, text="Curves")
        notebook.add(stages, text="Stages")

        general.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate(
            (
                ("Title", self.title_var),
                ("X axis title", self.x_title_var),
            )
        ):
            ttk.Label(general, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
            ttk.Entry(general, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Label(general, text="Y axis title").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Label(general, text=self._locked_y_axis_title()).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Checkbutton(general, text="Show right-side curve labels", variable=self.show_right_labels_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 4)
        )
        ttk.Label(general, text="Grid color").grid(row=4, column=0, sticky="w", pady=4, padx=(0, 8))
        grid_color_button = tk.Button(general, text="     ", bg=self.grid_color_var.get(), width=4)
        grid_color_button.grid(row=4, column=1, sticky="w", pady=4)
        ttk.Label(general, text="Grid width").grid(row=5, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Spinbox(general, from_=1, to=5, textvariable=self.grid_width_var, width=6).grid(
            row=5, column=1, sticky="w", pady=4
        )
        ttk.Label(general, text="Grid style").grid(row=6, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Combobox(
            general,
            textvariable=self.grid_style_var,
            values=("solid", "dash", "dot", "dash dot"),
            width=12,
            state="readonly",
        ).grid(row=6, column=1, sticky="w", pady=4)
        ttk.Label(general, text="Tick font size").grid(row=7, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Spinbox(general, from_=7, to=24, textvariable=self.tick_font_size_var, width=6).grid(
            row=7, column=1, sticky="w", pady=4
        )
        ttk.Checkbutton(general, text="Bold tick labels", variable=self.tick_bold_var).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=4
        )

        def choose_grid_color() -> None:
            chosen = colorchooser.askcolor(color=self.grid_color_var.get(), parent=window)
            if chosen and chosen[1]:
                self.grid_color_var.set(chosen[1])
                grid_color_button.configure(bg=chosen[1])
                self.draw_chart()

        grid_color_button.configure(command=choose_grid_color)

        curves.columnconfigure(1, weight=1)
        curve_names = self._selected_y_names() or self.headers[1:]
        style_controls: list[tuple[str, tk.StringVar, tk.StringVar, tk.StringVar, tk.Button]] = []
        if not curve_names:
            ttk.Label(curves, text="Create a plot first.").grid(row=0, column=0, sticky="w")
        for row, name in enumerate(curve_names):
            color = self._series_colors.get(name, self._series_color(row, len(curve_names)))
            label_var = tk.StringVar(value=self._series_labels.get(name, name))
            color_var = tk.StringVar(value=color)
            width_var = tk.StringVar(value=self._series_widths.get(name, self.line_width_var.get() or "2"))
            self._series_labels[name] = label_var.get()
            self._series_colors[name] = color_var.get()
            self._series_widths[name] = width_var.get()
            ttk.Label(curves, text=name).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
            ttk.Entry(curves, textvariable=label_var).grid(row=row, column=1, sticky="ew", pady=3, padx=(0, 8))
            color_button = tk.Button(curves, text="     ", bg=color_var.get(), width=4)
            color_button.grid(row=row, column=2, sticky="w", pady=3)
            ttk.Label(curves, text="Width").grid(row=row, column=3, sticky="e", padx=(8, 4), pady=3)
            ttk.Spinbox(curves, from_=1, to=12, textvariable=width_var, width=5).grid(row=row, column=4, sticky="w", pady=3)
            style_controls.append((name, label_var, color_var, width_var, color_button))

            def save_curve(n=name, lv=label_var, cv=color_var, wv=width_var, btn=color_button) -> None:
                self._series_labels[n] = lv.get().strip() or n
                self._series_colors[n] = cv.get().strip() or self._series_colors.get(n, "#000000")
                self._series_widths[n] = str(self._clamped_int_text(wv, 2, 1, 12))
                btn.configure(bg=self._series_colors[n])
                self.draw_chart()

            def choose_color(n=name, cv=color_var, btn=color_button) -> None:
                chosen = colorchooser.askcolor(color=cv.get(), parent=window)
                if chosen and chosen[1]:
                    cv.set(chosen[1])
                    self._series_colors[n] = chosen[1]
                    btn.configure(bg=chosen[1])
                    self.draw_chart()

            color_button.configure(command=choose_color)
            ttk.Button(curves, text="Apply", command=save_curve, width=APP_BUTTON_WIDTH).grid(row=row, column=5, padx=(8, 0), pady=3)

        stages.columnconfigure(0, weight=1)
        ttk.Label(
            stages,
            text="Optional. One region per line: start,end,label,color.",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        stage_text = tk.Text(stages, height=12, wrap="none")
        stage_text.grid(row=1, column=0, sticky="nsew")
        stages.rowconfigure(1, weight=1)
        if self.stage_text_var.get().strip():
            stage_text.insert("1.0", self.stage_text_var.get())

        button_bar = ttk.Frame(window, padding=(10, 0, 10, 10))
        button_bar.grid(row=1, column=0, sticky="ew")
        button_bar.columnconfigure(0, weight=1)

        def apply_settings() -> None:
            self.y_title_var.set(self._locked_y_axis_title())
            for name, label_var, color_var, width_var, color_button in style_controls:
                self._series_labels[name] = label_var.get().strip() or name
                self._series_colors[name] = color_var.get().strip() or self._series_colors.get(name, "#000000")
                self._series_widths[name] = str(self._clamped_int_text(width_var, 2, 1, 12))
                color_button.configure(bg=self._series_colors[name])
            stage_text_value = stage_text.get("1.0", "end").strip()
            if self._is_default_stage_example(stage_text_value):
                stage_text_value = ""
            self.stage_text_var.set(stage_text_value)
            self._parse_stage_regions()
            self._refresh_running_buffer_options()
            self.tick_font_size_var.set(str(self._clamped_int_text(self.tick_font_size_var, 9, 7, 24)))
            if self.grid_style_var.get() not in {"solid", "dash", "dot", "dash dot"}:
                self.grid_style_var.set("solid")
            self.draw_chart()

        ttk.Button(button_bar, text="Apply", command=apply_settings, width=APP_BUTTON_WIDTH).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(button_bar, text="Apply and Close", command=lambda: (apply_settings(), window.destroy()), width=APP_BUTTON_WIDTH).grid(row=0, column=2)
        if initial_tab == "Curves":
            notebook.select(curves)

    def refresh_from_source(self) -> None:
        if callable(self._refresh_callback):
            self._refresh_callback()
            return
        self.draw_chart()

    def draw_chart(self) -> None:
        if self._draw_after_id is not None:
            try:
                self.after_cancel(self._draw_after_id)
            except Exception:
                pass
            self._draw_after_id = None
        self.canvas.delete("all")
        self._series = []
        self._draggables = []

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
        margin_left, margin_right, margin_top, margin_bottom = 92, 190, 50, 86
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
        self._draw_stage_regions(left, top, right, bottom, x_min, x_max)
        if self.show_grid_var.get():
            self._draw_grid(left, top, right, bottom)
        self._draw_axes(left, top, right, bottom, x_min, x_max, y_min, y_max)
        self._draw_series(series, left, top, right, bottom, x_min, x_max, y_min, y_max, line_width, point_size)
        self._draw_lspr_shift_items(left, top, right, bottom, x_min, x_max, y_min, y_max)
        if self.show_legend_var.get():
            legend_x, legend_y = self._legend_position or (right + 16, top + 10)
            self._draw_legend(legend_x, legend_y, series)
        if self.show_right_labels_var.get():
            self._draw_right_labels(right + 8, top + 34, bottom, series)
        self._draw_titles(width, x_name, y_names)
        self._draw_annotations()

    def schedule_draw(self, delay_ms: int = 50) -> None:
        if self._draw_after_id is not None:
            try:
                self.after_cancel(self._draw_after_id)
            except Exception:
                pass
        self._draw_after_id = self.after(delay_ms, self.draw_chart)

    def _on_plot_selection_change(self, _event: object | None = None) -> None:
        self._lspr_shift_items = []
        self.draw_chart()

    def _refresh_running_buffer_options(self) -> None:
        labels: list[str] = []
        seen: set[str] = set()
        for _start, _end, label, _color in self._stage_regions:
            display_label = str(label).strip()
            if not display_label:
                continue
            key = self._normalize_stage_name(display_label)
            if not key or key in seen:
                continue
            seen.add(key)
            labels.append(display_label)
        if self.running_buffer_box is not None:
            self.running_buffer_box["values"] = labels
        current = self.running_buffer_var.get().strip()
        if labels and (not current or not any(self._stage_label_matches(label, current) for label in labels)):
            preferred = next((label for label in labels if self._stage_label_matches(label, "5*SSC")), labels[0])
            self.running_buffer_var.set(preferred)

    def calculate_lspr_shift_for_all_series(self) -> None:
        self.draw_chart()
        if not self._series:
            messagebox.showinfo("No Plot", "Create a plot first.")
            return
        if not self._stage_regions:
            messagebox.showinfo("No Stage Regions", "No stage background regions were found.")
            return
        target_label = self.running_buffer_var.get().strip()
        if not target_label:
            messagebox.showinfo("No Running Buffer", "Please select a List name in Running Buffer.")
            return
        items: list[dict[str, object]] = []
        for series_index, series in enumerate(self._series):
            items.extend(self._calculate_lspr_shift_items(series, target_label, series_index, len(self._series)))
        if not items:
            messagebox.showinfo(
                "No LSPR Shift",
                f"No usable {target_label} stages were found. Please confirm the background labels include this List name.",
            )
            return
        self._lspr_shift_items = items
        self.draw_chart()

    def calculate_lspr_shift_for_first_series(self) -> None:
        self.calculate_lspr_shift_for_all_series()

    def _calculate_lspr_shift_items(
        self,
        series: PlotSeries,
        target_label: str = "5*SSC",
        series_index: int = 0,
        series_count: int = 1,
    ) -> list[dict[str, object]]:
        points = self._points_for_lspr(series)
        if not points:
            return []
        ssc_regions = [
            (start, end, label, color)
            for start, end, label, color in self._stage_regions
            if self._stage_label_matches(label, target_label)
        ]
        if not ssc_regions:
            return []

        segments: list[dict[str, object]] = []
        for start, end, label, _color in ssc_regions:
            window_end = end - 20.0
            if window_end <= start:
                window_end = end
            window_start = max(start, window_end - 80.0)
            window_points = [(x, y) for x, y in points if window_start <= x <= window_end]
            if not window_points:
                window_points = [(x, y) for x, y in points if start <= x <= end]
            if not window_points:
                continue
            avg = sum(y for _x, y in window_points) / len(window_points)
            segments.append(
                {
                    "kind": "segment",
                    "start": float(window_start),
                    "end": float(window_end),
                    "stage_start": float(start),
                    "stage_end": float(end),
                    "avg": float(avg),
                    "label": str(label),
                    "index": len(segments) + 1,
                    "series_name": series.name,
                    "series_label": series.label,
                    "series_color": series.color,
                    "series_index": series_index,
                }
            )

        if len(segments) < 2:
            return segments

        items: list[dict[str, object]] = []
        y_span = max((max(y for _x, y in points) - min(y for _x, y in points)), 0.001)
        label_offset = y_span * (0.04 + min(series_index, 8) * 0.025)
        if series_count > 1 and series_index % 2:
            label_offset *= -1
        for index, segment in enumerate(segments):
            items.append(segment)
            if index == 0:
                continue
            previous = segments[index - 1]
            delta = float(segment["avg"]) - float(previous["avg"])
            previous_end = float(previous["end"])
            current_start = float(segment["start"])
            if current_start > previous_end:
                label_x = (previous_end + current_start) / 2
            else:
                label_x = (float(segment["start"]) + float(segment["end"])) / 2
            label_y = max(float(previous["avg"]), float(segment["avg"])) + label_offset
            items.append(
                {
                    "kind": "shift",
                    "x": float(label_x),
                    "y": float(label_y),
                    "delta": delta,
                    "from": int(previous["index"]),
                    "to": int(segment["index"]),
                    "series_name": series.name,
                    "series_label": series.label,
                    "series_color": series.color,
                    "series_index": series_index,
                }
            )
        return items

    def _points_for_lspr(self, series: PlotSeries) -> list[tuple[float, float]]:
        points = series.points
        if self._smooth_enabled() and len(points) >= 5:
            return self._savitzky_golay_points(points)
        return points

    def _is_ssc_stage_label(self, label: str) -> bool:
        return self._stage_label_matches(label, "5*SSC")

    def _stage_label_matches(self, label: str, target_label: str) -> bool:
        stage = self._normalize_stage_name(label)
        target = self._normalize_stage_name(target_label)
        if not stage or not target:
            return False
        return stage == target or target in stage or stage in target

    def _normalize_stage_name(self, value: str) -> str:
        text = str(value).lower()
        for old, new in (("×", "x"), ("*", "x"), ("_", ""), ("-", ""), (" ", ""), ("\t", "")):
            text = text.replace(old, new)
        return "".join(char for char in text if char.isalnum())

    def _draw_lspr_shift_items(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
    ) -> None:
        if not self._lspr_shift_items:
            return
        font_size = self._lspr_font_size()
        for index, item in enumerate(self._lspr_shift_items):
            kind = item.get("kind")
            if kind == "segment":
                x1 = self._x_to_canvas(float(item["start"]), left, right, x_min, x_max)
                x2 = self._x_to_canvas(float(item["end"]), left, right, x_min, x_max)
                y = self._y_to_canvas(float(item["avg"]), top, bottom, y_min, y_max)
                if x2 < left or x1 > right:
                    continue
                x1 = max(left, min(right, x1))
                x2 = max(left, min(right, x2))
                y = max(top + 3, min(bottom - 3, y))
                color = str(item.get("series_color", "#ff0000"))
                self.canvas.create_line(x1, y, x2, y, fill=color, width=5)
                self.canvas.create_line(x1, y, x2, y, fill="#ffffff", width=1)
            elif kind == "shift":
                if "label_px" in item and "label_py" in item:
                    x = float(item["label_px"])
                    y = float(item["label_py"])
                else:
                    x = self._x_to_canvas(float(item["x"]), left, right, x_min, x_max)
                    y = self._y_to_canvas(float(item["y"]), top, bottom, y_min, y_max)
                    x = max(left + 12, min(right - 12, x))
                y = max(top + 18, min(bottom - 18, y))
                delta = float(item["delta"])
                series_label = str(item.get("series_label", "")).strip()
                label = f"{series_label} Δλ={delta:+.3f}" if series_label else f"Δλ={delta:+.3f}"
                tag = f"drag_lspr_label_{index}"
                text_id = self._create_text_box(
                    x,
                    y,
                    label,
                    tag=tag,
                    font=("Segoe UI", font_size, "bold"),
                )
                self._register_draggable("lspr_label", index, text_id, tag=tag)

    def _draw_export_lspr_shift_items(self, draw, x_to_px, y_to_px, font, scale: float) -> None:
        if not self._lspr_shift_items:
            return
        for item in self._lspr_shift_items:
            kind = item.get("kind")
            if kind == "segment":
                x1 = x_to_px(float(item["start"]))
                x2 = x_to_px(float(item["end"]))
                y = y_to_px(float(item["avg"]))
                color = str(item.get("series_color", "#ff0000"))
                draw.line((x1, y, x2, y), fill=color, width=max(4, int(5 * scale)))
                draw.line((x1, y, x2, y), fill="#ffffff", width=max(1, int(1 * scale)))
            elif kind == "shift":
                if "label_px" in item and "label_py" in item:
                    x = float(item["label_px"]) * scale
                    y = float(item["label_py"]) * scale
                else:
                    x = x_to_px(float(item["x"]))
                    y = y_to_px(float(item["y"]))
                series_label = str(item.get("series_label", "")).strip()
                label = (
                    f"{series_label} Δλ={float(item['delta']):+.3f}"
                    if series_label
                    else f"Δλ={float(item['delta']):+.3f}"
                )
                self._draw_export_boxed_text(draw, x, y, label, font, anchor="center")

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
            defaultextension=".png",
            filetypes=[
                ("PNG image", "*.png"),
                ("TIFF image", "*.tif *.tiff"),
                ("JPEG image", "*.jpg *.jpeg"),
                ("Bitmap image", "*.bmp"),
                ("PostScript files", "*.ps"),
                ("Encapsulated PostScript", "*.eps"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        try:
            suffix = Path(file_path).suffix.lower()
            if suffix in {".ps", ".eps"}:
                self.canvas.postscript(file=file_path, colormode="color")
            else:
                self._export_canvas_bitmap(Path(file_path))
        except Exception as exc:
            messagebox.showerror("Export Failed", f"Unable to export image:\n{exc}")

    def _export_canvas_bitmap(self, path: Path) -> None:
        image = self._render_high_resolution_image()
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            image = image.convert("RGB")
            image.save(path, format="JPEG", quality=95, dpi=(300, 300))
        elif suffix in {".tif", ".tiff"}:
            image.save(path, format="TIFF", dpi=(300, 300))
        elif suffix == ".bmp":
            image.save(path, format="BMP")
        else:
            image.save(path, format="PNG", dpi=(300, 300))

    def _image_grab_module(self):
        global ImageGrab
        if ImageGrab is not None:
            return ImageGrab
        try:
            from PIL import ImageGrab as loaded_image_grab
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Pillow is required for PNG/TIFF/JPEG/BMP export.\n\n"
                "Please click the main window's Install Dependencies button, then try Export Image again."
            ) from exc
        ImageGrab = loaded_image_grab
        return ImageGrab

    def _pillow_modules(self):
        global Image, ImageDraw, ImageFont
        if Image is not None and ImageDraw is not None and ImageFont is not None:
            return Image, ImageDraw, ImageFont
        try:
            from PIL import Image as loaded_image
            from PIL import ImageDraw as loaded_image_draw
            from PIL import ImageFont as loaded_image_font
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Pillow is required for high-resolution PNG/TIFF/JPEG/BMP export.\n\n"
                "Please click the main window's Install Dependencies button, then try Export Image again."
            ) from exc
        Image = loaded_image
        ImageDraw = loaded_image_draw
        ImageFont = loaded_image_font
        return Image, ImageDraw, ImageFont

    def _render_high_resolution_image(self):
        image_module, draw_module, font_module = self._pillow_modules()
        series, x_name, y_names, bounds, line_width, point_size = self._plot_export_state()
        if not series or bounds is None:
            raise RuntimeError("Create a plot before exporting an image.")

        x_min, x_max, y_min, y_max = bounds
        canvas_width = max(self.canvas.winfo_width(), 600)
        canvas_height = max(self.canvas.winfo_height(), 380)
        width = 3600
        scale = width / max(canvas_width, 1)
        height = max(1, int(round(canvas_height * scale)))

        margin_left = int(92 * scale)
        margin_right = int(190 * scale)
        margin_top = int(50 * scale)
        margin_bottom = int(86 * scale)
        left = margin_left
        top = margin_top
        right = width - margin_right
        bottom = height - margin_bottom

        image = image_module.new("RGB", (width, height), "white")
        draw = draw_module.Draw(image)
        font_title = self._export_font(font_module, int(20 * scale), bold=True)
        font_axis = self._export_font(font_module, int(16 * scale), bold=True)
        tick_size = self._clamped_int_text(self.tick_font_size_var, 9, 7, 24)
        font_tick = self._export_font(font_module, int(tick_size * scale), bold=self.tick_bold_var.get())
        font_label = self._export_font(font_module, int(12 * scale), bold=True)
        font_lspr = self._export_font(font_module, int(self._lspr_font_size() * scale), bold=True)
        font_legend = self._export_font(font_module, int(12 * scale))

        def x_to_px(value: float) -> float:
            if math.isclose(x_min, x_max):
                return (left + right) / 2
            return left + (value - x_min) * (right - left) / (x_max - x_min)

        def y_to_px(value: float) -> float:
            if math.isclose(y_min, y_max):
                return (top + bottom) / 2
            return bottom - (value - y_min) * (bottom - top) / (y_max - y_min)

        draw.rectangle((left, top, right, bottom), fill="white", outline="#d0d0d0", width=max(1, int(scale)))
        self._draw_export_stage_regions(draw, left, top, right, bottom, x_min, x_max, x_to_px, font_label, scale)
        if self.show_grid_var.get():
            self._draw_export_grid(draw, left, top, right, bottom, scale)
        self._draw_export_axes(draw, left, top, right, bottom, x_min, x_max, y_min, y_max, x_to_px, y_to_px, font_tick, scale)
        self._draw_export_series(draw, series, x_to_px, y_to_px, line_width, point_size, scale)
        self._draw_export_lspr_shift_items(draw, x_to_px, y_to_px, font_lspr, scale)
        if self.show_legend_var.get():
            legend_x, legend_y = self._scaled_export_position(
                self._legend_position,
                right + int(16 * scale),
                top + int(10 * scale),
                width,
                height,
            )
            self._draw_export_legend(draw, legend_x, legend_y, series, font_label, font_legend, scale)
        if self.show_right_labels_var.get():
            self._draw_export_right_labels(draw, right + int(16 * scale), top + int(34 * scale), bottom, series, font_label, scale)
        self._draw_export_titles(image, draw, width, left, right, top, bottom, x_name, y_names, font_title, font_axis)
        self._draw_export_annotations(draw, font_label, scale)
        return image

    def _plot_export_state(
        self,
    ) -> tuple[list[PlotSeries], str, list[str], tuple[float, float, float, float] | None, int, int]:
        if not self.data or not self.headers or len(self.headers) < 2:
            return [], "", [], None, 2, 3

        x_name = self.x_var.get().strip() or self.headers[0]
        if x_name not in self.headers:
            x_name = self.headers[0]
        y_names = self._selected_y_names()
        if not y_names:
            y_names = self.headers[1:]

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

        x_values, _labels = self._extract_x_values(self.headers.index(x_name))
        series = self._build_series(x_values, y_names, step)
        if not series:
            return [], x_name, y_names, None, line_width, point_size
        xs = [x for item in series for x, _ in item.points]
        ys = [y for item in series for _, y in item.points]
        bounds = self._resolve_bounds(xs, ys)
        return series, x_name, y_names, bounds, line_width, point_size

    def _export_font(self, font_module, size: int, bold: bool = False):
        size = max(8, size)
        candidates = ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
        for candidate in candidates:
            try:
                return font_module.truetype(candidate, size)
            except Exception:
                continue
        return font_module.load_default()

    def _draw_export_stage_regions(
        self,
        draw,
        left: int,
        top: int,
        right: int,
        bottom: int,
        x_min: float,
        x_max: float,
        x_to_px,
        font,
        scale: float,
    ) -> None:
        if not self._stage_regions and self.stage_text_var.get().strip():
            self._parse_stage_regions()
        for start, end, label, color in self._stage_regions:
            visible_start = max(start, x_min)
            visible_end = min(end, x_max)
            if visible_end <= visible_start:
                continue
            x1 = x_to_px(visible_start)
            x2 = x_to_px(visible_end)
            draw.rectangle((x1, top, x2, bottom), fill=self._stage_fill_color(color), outline="#777777")
            self._draw_export_centered_text(draw, (x1 + x2) / 2, top + 14 * scale, label, font, fill="#000000")

    def _draw_export_grid(self, draw, left: int, top: int, right: int, bottom: int, scale: float) -> None:
        density = self._clamped_int_var(self.grid_density_var, 6, 2, 30)
        color = self.grid_color_var.get().strip() or "#eeeeee"
        width = max(1, int(self._clamped_int_text(self.grid_width_var, 1, 1, 5) * scale))
        for i in range(1, density):
            x = left + (right - left) * i / density
            y = top + (bottom - top) * i / density
            self._draw_export_styled_line(draw, (x, top, x, bottom), fill=color, width=width, scale=scale)
            self._draw_export_styled_line(draw, (left, y, right, y), fill=color, width=width, scale=scale)

    def _draw_export_styled_line(self, draw, coords: tuple[float, float, float, float], fill: str, width: int, scale: float) -> None:
        pattern = self._grid_dash_pattern(scale=scale)
        if not pattern:
            draw.line(coords, fill=fill, width=width)
            return
        x1, y1, x2, y2 = coords
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 0:
            return
        ux = (x2 - x1) / length
        uy = (y2 - y1) / length
        distance = 0.0
        draw_segment = True
        pattern_index = 0
        while distance < length:
            segment = pattern[pattern_index % len(pattern)]
            next_distance = min(length, distance + segment)
            if draw_segment:
                sx = x1 + ux * distance
                sy = y1 + uy * distance
                ex = x1 + ux * next_distance
                ey = y1 + uy * next_distance
                draw.line((sx, sy, ex, ey), fill=fill, width=width)
            draw_segment = not draw_segment
            distance = next_distance
            pattern_index += 1

    def _draw_export_axes(
        self,
        draw,
        left: int,
        top: int,
        right: int,
        bottom: int,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        x_to_px,
        y_to_px,
        font,
        scale: float,
    ) -> None:
        axis_width = max(2, int(2 * scale))
        tick_size = int(7 * scale)
        draw.line((left, bottom, right, bottom), fill="#444444", width=axis_width)
        draw.line((left, top, left, bottom), fill="#444444", width=axis_width)
        draw.line((left, top, right, top), fill="#444444", width=axis_width)
        draw.line((right, top, right, bottom), fill="#444444", width=axis_width)
        x_ticks = self._nice_ticks(x_min, x_max, count=self._clamped_int_var(self.x_tick_count_var, 8, 2, 30))
        y_ticks = self._nice_ticks(y_min, y_max, count=self._clamped_int_var(self.y_tick_count_var, 8, 2, 30))
        x_step = self._tick_step(x_ticks)
        y_step = self._tick_step(y_ticks)
        for value in x_ticks:
            if value < x_min - 1e-9 or value > x_max + 1e-9:
                continue
            x = x_to_px(value)
            draw.line((x, bottom, x, bottom + tick_size), fill="#444444", width=axis_width)
            self._draw_export_centered_text(
                draw,
                x,
                bottom + int(24 * scale),
                self._format_tick(value, x_step),
                font,
                fill="#333333",
            )
        for value in y_ticks:
            if value < y_min - 1e-9 or value > y_max + 1e-9:
                continue
            y = y_to_px(value)
            draw.line((left - tick_size, y, left, y), fill="#444444", width=axis_width)
            self._draw_export_right_text(draw, left - int(14 * scale), y, self._format_tick(value, y_step), font, fill="#333333")

    def _draw_export_series(self, draw, series: list[PlotSeries], x_to_px, y_to_px, line_width: int, point_size: int, scale: float) -> None:
        chart_type = self.chart_type_var.get()
        radius = max(1, int(point_size * scale))
        for item in series:
            width = max(1, int(self._series_line_width(item.name, line_width) * scale))
            points = item.points
            render_points = points
            if self._smooth_enabled() and len(points) >= 5:
                render_points = self._savitzky_golay_points(points)
            coords = [(x_to_px(x), y_to_px(y)) for x, y in render_points]
            if chart_type == "bar":
                bar_width = max(4, int(12 * scale))
                for x, y in coords:
                    draw.rectangle((x - bar_width / 2, y, x + bar_width / 2, y_to_px(0)), fill=item.color)
                continue
            if len(coords) >= 2:
                draw.line(coords, fill=item.color, width=width, joint="curve")
            if self.show_points_var.get() or chart_type == "scatter":
                source = render_points if chart_type == "scatter" else points
                for x_value, y_value in source:
                    x = x_to_px(x_value)
                    y = y_to_px(y_value)
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=item.color, outline=item.color)

    def _draw_export_legend(self, draw, x: float, y: float, series: list[PlotSeries], title_font, item_font, scale: float) -> None:
        box = 18 * scale
        for item in series:
            draw.rectangle((x, y + 4 * scale, x + box, y + 4 * scale + box), fill=item.color, outline=item.color)
            draw.text((x + 28 * scale, y + 3 * scale), item.label, fill="#222222", font=item_font)
            y += 30 * scale

    def _draw_export_right_labels(
        self,
        draw,
        x: float,
        top: float,
        bottom: float,
        series: list[PlotSeries],
        font,
        scale: float,
    ) -> None:
        labels = [(item.points[-1][1], item) for item in series if item.points]
        labels.sort(reverse=True, key=lambda pair: pair[0])
        if len(labels) == 1:
            y_positions = [(top + bottom) / 2]
        else:
            step = max(22.0 * scale, (bottom - top) / max(len(labels) - 1, 1))
            y_positions = [top + index * step for index in range(len(labels))]
        for y, (_value, item) in zip(y_positions, labels):
            x_pos, y_pos = self._right_label_positions.get(item.name, (x, y))
            if item.name in self._right_label_positions:
                x_pos *= scale
                y_pos *= scale
            self._draw_export_boxed_text(draw, x_pos, y_pos, item.label, font, anchor="w")

    def _draw_export_titles(self, image, draw, width: int, left: int, right: int, top: int, bottom: int, x_name: str, y_names: list[str], title_font, axis_font) -> None:
        title = self.title_var.get().strip() or f"{', '.join(self._series_labels.get(name, name) for name in y_names)} vs {x_name}"
        scale = width / max(max(self.canvas.winfo_width(), 600), 1)
        self._draw_export_centered_text(draw, width / 2, 22 * scale, title, title_font, fill="#222222")
        self._draw_export_centered_text(draw, (left + right) / 2, bottom + 64 * scale, self.x_title_var.get().strip() or x_name, axis_font, fill="#111111")
        self._draw_export_rotated_text(image, draw, max(30 * scale, left - 58 * scale), (top + bottom) / 2, self._locked_y_axis_title(), axis_font)

    def _draw_export_annotations(self, draw, font, scale: float) -> None:
        for annotation in self._annotations:
            x = float(annotation.get("x", 0)) * scale
            y = float(annotation.get("y", 0)) * scale
            text = str(annotation.get("text", ""))
            self._draw_export_boxed_text(draw, x, y, text, font, anchor="center")

    def _scaled_export_position(
        self,
        position: tuple[float, float] | None,
        default_x: float,
        default_y: float,
        export_width: int,
        export_height: int,
    ) -> tuple[float, float]:
        if position is None:
            return default_x, default_y
        canvas_width = max(self.canvas.winfo_width(), 600)
        canvas_height = max(self.canvas.winfo_height(), 380)
        return float(position[0]) * export_width / canvas_width, float(position[1]) * export_height / canvas_height

    def _draw_export_centered_text(self, draw, x: float, y: float, text: str, font, fill: str = "#000000") -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (bbox[2] - bbox[0]) / 2, y - (bbox[3] - bbox[1]) / 2), text, fill=fill, font=font)

    def _draw_export_right_text(self, draw, x: float, y: float, text: str, font, fill: str = "#000000") -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (bbox[2] - bbox[0]), y - (bbox[3] - bbox[1]) / 2), text, fill=fill, font=font)

    def _draw_export_boxed_text(self, draw, x: float, y: float, text: str, font, anchor: str = "center") -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if anchor == "w":
            text_x = x
            text_y = y - height / 2
        else:
            text_x = x - width / 2
            text_y = y - height / 2
        pad_x, pad_y = 6, 4
        draw.rectangle(
            (text_x - pad_x, text_y - pad_y, text_x + width + pad_x, text_y + height + pad_y),
            fill="#ffffff",
            outline="#000000",
            width=2,
        )
        draw.text((text_x, text_y), text, fill="#000000", font=font)

    def _draw_export_rotated_text(self, image, draw, x: float, y: float, text: str, font, fill: str = "#000000") -> None:
        image_module, draw_module, _font_module = self._pillow_modules()
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = max(1, bbox[2] - bbox[0])
        text_height = max(1, bbox[3] - bbox[1])
        text_image = image_module.new("RGBA", (text_width + 8, text_height + 8), (255, 255, 255, 0))
        text_draw = draw_module.Draw(text_image)
        text_draw.text((4, 4), text, fill=fill, font=font)
        rotated = text_image.rotate(90, expand=True)
        image.paste(rotated, (int(x - rotated.width / 2), int(y - rotated.height / 2)), rotated)

    def _locked_y_axis_title(self) -> str:
        return "Δλ_LSPR [nm]"

    def _series_line_width(self, name: str, fallback: int) -> int:
        value = self._series_widths.get(name, str(fallback))
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            parsed = fallback
        parsed = max(1, min(12, parsed))
        self._series_widths[name] = str(parsed)
        return parsed

    def _grid_dash_pattern(self, scale: float = 1.0):
        style = self.grid_style_var.get().strip().lower()
        if style == "dash":
            return (max(1, int(8 * scale)), max(1, int(5 * scale)))
        if style == "dot":
            return (max(1, int(2 * scale)), max(1, int(5 * scale)))
        if style == "dash dot":
            return (max(1, int(8 * scale)), max(1, int(4 * scale)), max(1, int(2 * scale)), max(1, int(4 * scale)))
        return None

    def _safe_tag(self, text: str) -> str:
        return "".join(char if char.isalnum() else "_" for char in str(text))

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
        return self._insert_text_at(event.x, event.y)

    def _on_canvas_right_click(self, event: tk.Event) -> str:
        return self._insert_text_at(event.x, event.y) or "break"

    def _insert_text_at(self, x: int, y: int) -> str | None:
        text = self.text_var.get().strip()
        if not text:
            self._text_mode = False
            messagebox.showinfo("No Text", "Type text in the Text box first.")
            return "break"
        annotation = {"x": float(x), "y": float(y), "text": text}
        self._annotations.append(annotation)
        index = len(self._annotations) - 1
        tag = f"drag_annotation_{index}"
        text_id = self._create_text_box(float(x), float(y), text, tag=tag)
        self._register_draggable("annotation", index, text_id, tag=tag)
        self._text_mode = False
        return "break"

    def _draw_annotations(self) -> None:
        for index, annotation in enumerate(self._annotations):
            tag = f"drag_annotation_{index}"
            text_id = self._create_text_box(
                float(annotation.get("x", 0)),
                float(annotation.get("y", 0)),
                str(annotation.get("text", "")),
                tag=tag,
            )
            self._register_draggable("annotation", index, text_id, tag=tag)

    def _create_text_box(
        self,
        x: float,
        y: float,
        text: str,
        anchor: str = "center",
        tag: str | None = None,
        font: tuple[str, int, str] | None = None,
    ) -> int:
        text_id = self.canvas.create_text(
            x,
            y,
            text=text,
            fill="#111111",
            font=font or ("Segoe UI", 10, "bold"),
            anchor=anchor,
            tags=(tag,) if tag else (),
        )
        self._draw_text_box(text_id, tag=tag)
        return text_id

    def _draw_text_box(self, text_id: int, tag: str | None = None) -> None:
        bbox = self.canvas.bbox(text_id)
        if not bbox:
            return
        self.canvas.create_rectangle(
            bbox[0] - 4,
            bbox[1] - 2,
            bbox[2] + 4,
            bbox[3] + 2,
            fill="#ffffff",
            outline="#333333",
            tags=(tag,) if tag else (),
        )
        self.canvas.tag_raise(text_id)

    def _register_draggable(self, kind: str, key: object, text_id: int, tag: str | None = None) -> None:
        bbox = self.canvas.bbox(text_id)
        if not bbox:
            return
        self._draggables.append(
            {
                "kind": kind,
                "key": key,
                "tag": tag,
                "bbox": (float(bbox[0] - 4), float(bbox[1] - 4), float(bbox[2] + 4), float(bbox[3] + 4)),
            }
        )

    def _on_smooth_window_change(self, value: str) -> None:
        try:
            amount = int(float(value))
        except ValueError:
            amount = 0
        self.smooth_window_var.set(max(0, min(100, amount)))
        self.smooth_window_label_var.set(f"Smooth {self.smooth_window_var.get()}")
        self.smooth_var.set(self.smooth_window_var.get() > 0)
        self.schedule_draw(delay_ms=35)

    def _on_smooth_toggle(self) -> None:
        if self.smooth_var.get() and self.smooth_window_var.get() <= 0:
            self.smooth_window_var.set(25)
        elif not self.smooth_var.get():
            self.smooth_window_var.set(0)
        self.smooth_window_label_var.set(f"Smooth {self.smooth_window_var.get()}")
        self.schedule_draw()

    def _smooth_enabled(self) -> bool:
        return bool(self.smooth_var.get()) and self.smooth_window_var.get() > 0

    def _on_stage_opacity_change(self, value: str) -> None:
        try:
            amount = int(float(value))
        except ValueError:
            amount = 70
        amount = max(0, min(100, amount))
        self.stage_opacity_var.set(amount)
        self.stage_opacity_label_var.set(f"Background {amount}%")
        self.schedule_draw(delay_ms=35)

    def _on_axis_detail_change(self, _event: object | None = None) -> None:
        self.grid_density_var.set(self._clamped_int_var(self.grid_density_var, 6, 2, 30))
        self.x_tick_count_var.set(self._clamped_int_var(self.x_tick_count_var, 8, 2, 30))
        self.y_tick_count_var.set(self._clamped_int_var(self.y_tick_count_var, 8, 2, 30))
        self.schedule_draw()

    def _clamped_int_var(self, var: tk.IntVar, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(var.get())
        except (tk.TclError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _clamped_int_text(self, var: tk.StringVar, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(float(var.get()))
        except (tk.TclError, ValueError):
            value = default
            var.set(str(default))
        value = max(minimum, min(maximum, value))
        var.set(str(value))
        return value

    def _lspr_font_size(self) -> int:
        return self._clamped_int_text(self.lspr_font_size_var, 10, 7, 24)

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
        self.schedule_draw()

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
                label = self._series_labels.get(y_name, y_name)
                color = self._series_colors.get(y_name, self._series_color(index, len(y_names)))
                self._series_labels.setdefault(y_name, label)
                self._series_colors.setdefault(y_name, color)
                series.append(PlotSeries(name=y_name, label=label, points=points, color=color))
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
        density = self._clamped_int_var(self.grid_density_var, 6, 2, 30)
        color = self.grid_color_var.get().strip() or "#eeeeee"
        width = self._clamped_int_text(self.grid_width_var, 1, 1, 5)
        dash = self._grid_dash_pattern()
        line_options = {"fill": color, "width": width}
        if dash:
            line_options["dash"] = dash
        for i in range(1, density):
            x = left + (right - left) * i / density
            y = top + (bottom - top) * i / density
            self.canvas.create_line(x, top, x, bottom, **line_options)
            self.canvas.create_line(left, y, right, y, **line_options)

    def _draw_axes(self, left: float, top: float, right: float, bottom: float, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        self.canvas.create_line(left, bottom, right, bottom, fill="#444444", width=2)
        self.canvas.create_line(left, top, left, bottom, fill="#444444", width=2)
        self.canvas.create_line(left, top, right, top, fill="#444444", width=2)
        self.canvas.create_line(right, top, right, bottom, fill="#444444", width=2)
        x_ticks = self._nice_ticks(x_min, x_max, count=self._clamped_int_var(self.x_tick_count_var, 8, 2, 30))
        y_ticks = self._nice_ticks(y_min, y_max, count=self._clamped_int_var(self.y_tick_count_var, 8, 2, 30))
        x_step = self._tick_step(x_ticks)
        y_step = self._tick_step(y_ticks)
        tick_size = self._clamped_int_text(self.tick_font_size_var, 9, 7, 24)
        tick_weight = "bold" if self.tick_bold_var.get() else "normal"
        tick_font = ("Segoe UI", tick_size, tick_weight)
        for value in x_ticks:
            if value < x_min - 1e-9 or value > x_max + 1e-9:
                continue
            px = self._x_to_canvas(value, left, right, x_min, x_max)
            self.canvas.create_line(px, bottom, px, bottom + 6, fill="#444444")
            self.canvas.create_text(
                px,
                bottom + 18,
                text=self._format_tick(value, x_step),
                fill="#333333",
                font=tick_font,
            )
        for value in y_ticks:
            if value < y_min - 1e-9 or value > y_max + 1e-9:
                continue
            py = self._y_to_canvas(value, top, bottom, y_min, y_max)
            self.canvas.create_line(left - 6, py, left, py, fill="#444444")
            self.canvas.create_text(
                left - 10,
                py,
                text=self._format_tick(value, y_step),
                fill="#333333",
                font=tick_font,
                anchor="e",
            )

    def _parse_stage_regions(self) -> None:
        regions: list[tuple[float, float, str, str]] = []
        stage_text = self.stage_text_var.get()
        if self._is_default_stage_example(stage_text):
            self.stage_text_var.set("")
            self._stage_regions = []
            return
        for line in stage_text.splitlines():
            text = line.strip()
            if not text:
                continue
            parts = [part.strip() for part in text.split(",")]
            if len(parts) < 3:
                continue
            try:
                start = float(parts[0])
                end = float(parts[1])
            except ValueError:
                continue
            if math.isclose(start, end):
                continue
            label = parts[2]
            color = parts[3] if len(parts) >= 4 and parts[3] else "#eeeeee"
            if end < start:
                start, end = end, start
            regions.append((start, end, label, color))
        self._stage_regions = regions
        self._refresh_running_buffer_options()

    def _is_default_stage_example(self, text: str) -> bool:
        normalized = "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())
        default_example = "\n".join(
            [
                "0,300,5xSSC,#eeeeee",
                "300,600,FS,#f6d8bf",
                "900,1300,Target 1 uM,#b8ffb8",
                "1600,2500,HCl,#f7f3b0",
            ]
        )
        return normalized == default_example

    def _stage_fill_color(self, color: str) -> str:
        text = color.strip()
        if not text.startswith("#") or len(text) not in {4, 7}:
            return text or "#eeeeee"
        if len(text) == 4:
            text = "#" + "".join(char * 2 for char in text[1:])
        try:
            red = int(text[1:3], 16)
            green = int(text[3:5], 16)
            blue = int(text[5:7], 16)
        except ValueError:
            return "#eeeeee"
        opacity = self._clamped_int_var(self.stage_opacity_var, 70, 0, 100) / 100.0
        red = round(255 + (red - 255) * opacity)
        green = round(255 + (green - 255) * opacity)
        blue = round(255 + (blue - 255) * opacity)
        return f"#{red:02X}{green:02X}{blue:02X}"

    def _draw_stage_regions(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
        x_min: float,
        x_max: float,
    ) -> None:
        if not self._stage_regions and self.stage_text_var.get().strip():
            self._parse_stage_regions()
        for start, end, label, color in self._stage_regions:
            visible_start = max(start, x_min)
            visible_end = min(end, x_max)
            if visible_end <= visible_start:
                continue
            x1 = self._x_to_canvas(visible_start, left, right, x_min, x_max)
            x2 = self._x_to_canvas(visible_end, left, right, x_min, x_max)
            self.canvas.create_rectangle(x1, top, x2, bottom, fill=self._stage_fill_color(color), outline="#777777")
            self.canvas.create_text(
                (x1 + x2) / 2,
                top + 14,
                text=label,
                fill="#000000",
                font=("Segoe UI", 10, "bold"),
            )

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
            if self._smooth_enabled() and len(item.points) >= 5:
                render_points = self._savitzky_golay_points(item.points)
            coords: list[float] = []
            for x_value, y_value in render_points:
                coords.extend([
                    self._x_to_canvas(x_value, left, right, x_min, x_max),
                    self._y_to_canvas(y_value, top, bottom, y_min, y_max),
                ])
            if len(coords) >= 4:
                self.canvas.create_line(*coords, fill=item.color, width=self._series_line_width(item.name, line_width), smooth=False)
            if self.show_points_var.get() or chart_type == "scatter":
                point_source = item.points if chart_type != "scatter" else render_points
                for x_value, y_value in point_source:
                    x = self._x_to_canvas(x_value, left, right, x_min, x_max)
                    y = self._y_to_canvas(y_value, top, bottom, y_min, y_max)
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
        tag = "drag_legend"
        for item in series:
            self.canvas.create_rectangle(x, y + 4, x + 16, y + 16, fill=item.color, outline=item.color, tags=(tag,))
            self.canvas.create_text(x + 22, y + 10, anchor="w", text=item.label, font=("Segoe UI", 9), fill="#222222", tags=(tag,))
            y += 24
        bbox = self.canvas.bbox(tag)
        if bbox:
            self._draggables.append(
                {
                    "kind": "legend",
                    "key": "legend",
                    "tag": tag,
                    "bbox": (float(bbox[0] - 4), float(bbox[1] - 4), float(bbox[2] + 4), float(bbox[3] + 4)),
                }
            )

    def _draw_titles(self, width: int, x_name: str, y_names: list[str]) -> None:
        title = self.title_var.get().strip() or f"{', '.join(self._series_labels.get(name, name) for name in y_names)} vs {x_name}"
        self.canvas.create_text(
            width / 2,
            22,
            text=title,
            font=("Segoe UI", 14, "bold"),
            fill="#222222",
        )
        if self._plot_rect is not None:
            left, top, right, bottom = self._plot_rect
            self.canvas.create_text(
                (left + right) / 2,
                bottom + 64,
                text=self.x_title_var.get().strip() or x_name,
                font=("Segoe UI", 13, "bold"),
                fill="#111111",
            )
            self.canvas.create_text(
                max(30, left - 58),
                (top + bottom) / 2,
                text=self._locked_y_axis_title(),
                angle=90,
                font=("Segoe UI", 13, "bold"),
                fill="#111111",
            )

    def _draw_right_labels(
        self,
        x: float,
        top: float,
        bottom: float,
        series: list[PlotSeries],
    ) -> None:
        if not series:
            return
        labels: list[tuple[float, PlotSeries]] = []
        for item in series:
            if not item.points:
                continue
            labels.append((item.points[-1][1], item))
        labels.sort(reverse=True, key=lambda pair: pair[0])

        if len(labels) == 1:
            y_positions = [(top + bottom) / 2]
        else:
            step = max(22.0, (bottom - top) / max(len(labels) - 1, 1))
            y_positions = [top + index * step for index in range(len(labels))]
        for y, (_, item) in zip(y_positions, labels):
            x_pos, y_pos = self._right_label_positions.get(item.name, (x + 8, y))
            tag = f"drag_right_label_{self._safe_tag(item.name)}"
            text_id = self.canvas.create_text(
                x_pos,
                y_pos,
                text=item.label,
                anchor="w",
                fill="#000000",
                font=("Segoe UI", 9, "bold"),
                tags=(tag,),
            )
            bbox = self.canvas.bbox(text_id)
            if bbox:
                self.canvas.create_rectangle(
                    bbox[0] - 4,
                    bbox[1] - 2,
                    bbox[2] + 4,
                    bbox[3] + 2,
                    fill="#ffffff",
                    outline="#000000",
                    width=1,
                    tags=(tag,),
                )
                self.canvas.tag_raise(text_id)
            self._register_draggable("right_label", item.name, text_id, tag=tag)

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
        if self._text_mode:
            return
        target = self._hit_draggable(event.x, event.y)
        if target is not None:
            self._drag_target = target
            current_x, current_y = self._draggable_position(target)
            if target.get("kind") == "right_label":
                self._right_label_positions.setdefault(str(target.get("key", "")), (current_x, current_y))
            elif target.get("kind") == "legend":
                self._legend_position = self._legend_position or (current_x, current_y)
            self._drag_offset = (current_x - event.x, current_y - event.y)
            self._drag_last = (event.x, event.y)
            return
        if self._plot_rect is None or self._view_bounds is None:
            return
        self._pan_anchor = (event.x, event.y)
        self._pan_bounds = self._view_bounds

    def _drag_pan(self, event: tk.Event) -> None:
        if self._drag_target is not None:
            self._move_draggable_live(event.x, event.y)
            return
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
        self._drag_target = None
        self._drag_last = None
        self._pan_anchor = None
        self._pan_bounds = None

    def _hit_draggable(self, x: float, y: float) -> dict[str, object] | None:
        for item in reversed(self._draggables):
            left, top, right, bottom = item["bbox"]
            if float(left) <= x <= float(right) and float(top) <= y <= float(bottom):
                return item
        return None

    def _draggable_position(self, target: dict[str, object]) -> tuple[float, float]:
        if target.get("kind") == "annotation":
            index = int(target.get("key", -1))
            if 0 <= index < len(self._annotations):
                annotation = self._annotations[index]
                return float(annotation.get("x", 0)), float(annotation.get("y", 0))
        if target.get("kind") == "lspr_label":
            index = int(target.get("key", -1))
            if 0 <= index < len(self._lspr_shift_items):
                item = self._lspr_shift_items[index]
                if "label_px" in item and "label_py" in item:
                    return float(item["label_px"]), float(item["label_py"])
        if target.get("kind") == "right_label":
            key = str(target.get("key", ""))
            if key in self._right_label_positions:
                return self._right_label_positions[key]
        if target.get("kind") == "legend":
            if self._legend_position is not None:
                return self._legend_position
            left, top, _right, _bottom = target["bbox"]
            return float(left) + 4, float(top) + 4
        left, top, right, bottom = target["bbox"]
        return (float(left) + float(right)) / 2, (float(top) + float(bottom)) / 2

    def _move_draggable_live(self, event_x: float, event_y: float) -> None:
        if self._drag_target is None or self._drag_last is None:
            return
        dx = event_x - self._drag_last[0]
        dy = event_y - self._drag_last[1]
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return
        tag = self._drag_target.get("tag")
        if tag:
            self.canvas.move(str(tag), dx, dy)
        left, top, right, bottom = self._drag_target["bbox"]
        self._drag_target["bbox"] = (float(left) + dx, float(top) + dy, float(right) + dx, float(bottom) + dy)
        self._drag_last = (event_x, event_y)
        kind = self._drag_target.get("kind")
        key = self._drag_target.get("key")
        if kind == "annotation":
            index = int(key)
            if 0 <= index < len(self._annotations):
                self._annotations[index]["x"] = float(self._annotations[index].get("x", 0)) + dx
                self._annotations[index]["y"] = float(self._annotations[index].get("y", 0)) + dy
        elif kind == "lspr_label":
            index = int(key)
            if 0 <= index < len(self._lspr_shift_items):
                self._lspr_shift_items[index]["label_px"] = float(event_x + self._drag_offset[0])
                self._lspr_shift_items[index]["label_py"] = float(event_y + self._drag_offset[1])
        elif kind == "right_label":
            x, y = self._right_label_positions.get(str(key), self._draggable_position(self._drag_target))
            self._right_label_positions[str(key)] = (x + dx, y + dy)
        elif kind == "legend":
            x, y = self._legend_position or self._draggable_position(self._drag_target)
            self._legend_position = (x + dx, y + dy)

    def _move_draggable(self, x: float, y: float) -> None:
        if self._drag_target is None:
            return
        kind = self._drag_target.get("kind")
        key = self._drag_target.get("key")
        if kind == "annotation":
            index = int(key)
            if 0 <= index < len(self._annotations):
                self._annotations[index]["x"] = float(x)
                self._annotations[index]["y"] = float(y)
        elif kind == "lspr_label":
            index = int(key)
            if 0 <= index < len(self._lspr_shift_items):
                self._lspr_shift_items[index]["label_px"] = float(x)
                self._lspr_shift_items[index]["label_py"] = float(y)
        elif kind == "right_label":
            self._right_label_positions[str(key)] = (float(x), float(y))
        elif kind == "legend":
            self._legend_position = (float(x), float(y))
        self.draw_chart()

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

    def _tick_step(self, ticks: list[float]) -> float | None:
        if len(ticks) < 2:
            return None
        steps = [abs(ticks[index + 1] - ticks[index]) for index in range(len(ticks) - 1)]
        steps = [step for step in steps if not math.isclose(step, 0.0)]
        return min(steps) if steps else None

    def _format_tick(self, value: float, step: float | None = None) -> str:
        if abs(value) < 1e-12:
            value = 0.0
        decimals = 0
        if step is not None and step > 0:
            if step >= 1:
                decimals = 0
            else:
                decimals = min(6, max(1, int(math.ceil(-math.log10(step))) + 1))
        elif not float(value).is_integer():
            decimals = 3
        text = f"{value:.{decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

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

    def _savitzky_golay_points(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        amount = max(0, min(100, int(self.smooth_window_var.get())))
        if amount <= 0 or len(points) < 5:
            return points
        window = self._smooth_window_size(len(points), amount)
        if window < 5:
            return points
        order = min(3, window - 2)
        half = window // 2
        coefficients = self._savitzky_golay_coefficients(window, order)
        if not coefficients:
            return points
        ys = [point[1] for point in points]
        smoothed: list[tuple[float, float]] = []
        for index, (x_value, _) in enumerate(points):
            y_value = 0.0
            for offset, coefficient in enumerate(coefficients):
                source_index = index + offset - half
                source_index = min(max(source_index, 0), len(points) - 1)
                y_value += coefficient * ys[source_index]
            smoothed.append((x_value, y_value))
        return smoothed

    def _smooth_window_size(self, point_count: int, amount: int) -> int:
        if point_count < 5:
            return 0
        max_window = min(point_count if point_count % 2 == 1 else point_count - 1, 101)
        raw_window = 5 + round((max_window - 5) * amount / 100)
        if raw_window % 2 == 0:
            raw_window += 1
        return max(5, min(raw_window, max_window))

    def _savitzky_golay_coefficients(self, window: int, order: int) -> list[float]:
        half = window // 2
        xs = [float(index - half) for index in range(window)]
        size = order + 1
        matrix = [[0.0 for _ in range(size)] for _ in range(size)]
        for x_value in xs:
            powers = [1.0]
            for _ in range(1, size * 2):
                powers.append(powers[-1] * x_value)
            for row in range(size):
                for column in range(size):
                    matrix[row][column] += powers[row + column]
        inverse = self._invert_matrix(matrix)
        if inverse is None:
            return []
        coefficients: list[float] = []
        for x_value in xs:
            powers = [1.0]
            for _ in range(1, size):
                powers.append(powers[-1] * x_value)
            coefficients.append(sum(inverse[0][row] * powers[row] for row in range(size)))
        return coefficients

    def _invert_matrix(self, matrix: list[list[float]]) -> list[list[float]] | None:
        size = len(matrix)
        augmented = [
            row[:] + [1.0 if row_index == column_index else 0.0 for column_index in range(size)]
            for row_index, row in enumerate(matrix)
        ]
        for column in range(size):
            pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
            if abs(augmented[pivot][column]) < 1e-12:
                return None
            if pivot != column:
                augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
            pivot_value = augmented[column][column]
            for col in range(column, size * 2):
                augmented[column][col] /= pivot_value
            for row in range(size):
                if row == column:
                    continue
                factor = augmented[row][column]
                if math.isclose(factor, 0.0):
                    continue
                for col in range(column, size * 2):
                    augmented[row][col] -= factor * augmented[column][col]
        return [row[size:] for row in augmented]
