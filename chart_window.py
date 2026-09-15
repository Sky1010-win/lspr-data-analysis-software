from __future__ import annotations

import csv
import colorsys
import json
import math
from dataclasses import dataclass
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

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


class LSPRShiftBarChartWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        entries: list[dict[str, object]],
        initial_target: str = "",
        y_axis_title: str = "Delta LSPR [nm]",
    ) -> None:
        super().__init__(parent)
        self.title("LSPR Shift Bar Chart")
        self.geometry("820x520")
        self.minsize(560, 360)
        self.transient(parent.winfo_toplevel())
        self.entries = entries
        self.y_axis_title = y_axis_title
        self.target_var = tk.StringVar(value=initial_target or "All")
        self.label_font_size_var = tk.StringVar(value="8")
        self.value_font_size_var = tk.StringVar(value="8")
        self.label_bold_var = tk.BooleanVar(value=False)
        self.value_bold_var = tk.BooleanVar(value=True)
        self.show_error_bars_var = tk.BooleanVar(value=True)
        self.background_color_var = tk.StringVar(value=self._initial_background_color())
        self.bar_colors: dict[str, str] = {}
        self.text_annotations: list[dict[str, object]] = []
        self._annotation_hitboxes: list[tuple[int, tuple[float, float, float, float]]] = []
        self._drag_annotation_index: int | None = None
        self._drag_offset: tuple[float, float] = (0.0, 0.0)
        for entry in self.entries:
            name = str(entry.get("name", "")).strip()
            if name:
                self.bar_colors.setdefault(name, str(entry.get("color", "#f4bd82")))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        controls = ttk.Frame(self, padding=(10, 10, 10, 0))
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(5, weight=1)
        ttk.Label(controls, text="Target").grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.target_box = ttk.Combobox(
            controls,
            textvariable=self.target_var,
            values=self._target_options(),
            width=28,
            state="readonly",
        )
        self.target_box.grid(row=0, column=1, sticky="w")
        self.target_box.bind("<<ComboboxSelected>>", lambda _event: self.draw_chart())
        ttk.Label(controls, text="Solutions").grid(row=0, column=2, padx=(14, 6), sticky="nw")
        solution_frame = ttk.Frame(controls)
        solution_frame.grid(row=0, column=3, sticky="w")
        self.solution_listbox = tk.Listbox(solution_frame, selectmode=tk.MULTIPLE, exportselection=False, height=4, width=30)
        solution_scroll = ttk.Scrollbar(solution_frame, orient="vertical", command=self.solution_listbox.yview)
        self.solution_listbox.configure(yscrollcommand=solution_scroll.set)
        self.solution_listbox.grid(row=0, column=0, sticky="nsew")
        solution_scroll.grid(row=0, column=1, sticky="ns")
        for name in self._solution_options():
            self.solution_listbox.insert(tk.END, name)
        self.solution_listbox.selection_set(0, tk.END)
        self.solution_listbox.bind("<<ListboxSelect>>", lambda _event: self.draw_chart())
        button_box = ttk.Frame(controls)
        button_box.grid(row=0, column=4, padx=(8, 0), sticky="nw")
        ttk.Button(button_box, text="All", command=self._select_all_solutions, width=8).grid(row=0, column=0, pady=(0, 4))
        ttk.Button(button_box, text="Clear", command=self._clear_solution_selection, width=8).grid(row=1, column=0)
        format_box = ttk.Frame(controls)
        format_box.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        ttk.Label(format_box, text="Name Font").grid(row=0, column=0, padx=(0, 4), sticky="w")
        ttk.Spinbox(format_box, from_=6, to=24, textvariable=self.label_font_size_var, width=5, command=self.draw_chart).grid(row=0, column=1, padx=(0, 6), sticky="w")
        ttk.Checkbutton(format_box, text="Bold", variable=self.label_bold_var, command=self.draw_chart).grid(row=0, column=2, padx=(0, 12), sticky="w")
        ttk.Label(format_box, text="Value Font").grid(row=0, column=3, padx=(0, 4), sticky="w")
        ttk.Spinbox(format_box, from_=6, to=24, textvariable=self.value_font_size_var, width=5, command=self.draw_chart).grid(row=0, column=4, padx=(0, 6), sticky="w")
        ttk.Checkbutton(format_box, text="Bold", variable=self.value_bold_var, command=self.draw_chart).grid(row=0, column=5, padx=(0, 12), sticky="w")
        ttk.Checkbutton(format_box, text="Error Bars", variable=self.show_error_bars_var, command=self.draw_chart).grid(row=0, column=6, padx=(0, 12), sticky="w")
        ttk.Button(format_box, text="Insert Text", command=self.insert_text_annotation, width=12).grid(row=0, column=7, padx=(0, 8), sticky="w")
        ttk.Button(format_box, text="Background", command=self.choose_background_color, width=12).grid(row=0, column=8, padx=(0, 8), sticky="w")
        ttk.Button(format_box, text="Bar Colors", command=self.open_bar_color_settings, width=12).grid(row=0, column=9, padx=(0, 8), sticky="w")
        ttk.Button(format_box, text="Export Image", command=self.export_high_resolution_image, width=13).grid(row=0, column=10, padx=(0, 8), sticky="w")

        self.canvas = tk.Canvas(self, bg="white", highlightthickness=1, highlightbackground="#d0d0d0")
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.canvas.bind("<Configure>", lambda _event: self.draw_chart())
        self.canvas.bind("<ButtonPress-1>", self._start_annotation_drag)
        self.canvas.bind("<B1-Motion>", self._drag_annotation)
        self.canvas.bind("<ButtonRelease-1>", self._end_annotation_drag)
        self.after(0, self.draw_chart)

    def _target_options(self) -> list[str]:
        targets = []
        seen: set[str] = set()
        for entry in self.entries:
            target = str(entry.get("target", "")).strip()
            if target and target not in seen:
                seen.add(target)
                targets.append(target)
        return ["All", *targets]

    def _visible_entries(self) -> list[dict[str, object]]:
        target = self.target_var.get().strip()
        selected_solutions = self._selected_solutions()
        entries = self.entries
        if target and target != "All":
            entries = [entry for entry in entries if str(entry.get("target", "")).strip() == target]
        if selected_solutions:
            entries = [entry for entry in entries if str(entry.get("name", "")).strip() in selected_solutions]
        else:
            entries = []
        return entries

    def _solution_options(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for entry in self.entries:
            name = str(entry.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def _selected_solutions(self) -> set[str]:
        selected: set[str] = set()
        for index in self.solution_listbox.curselection():
            selected.add(str(self.solution_listbox.get(index)))
        return selected

    def _select_all_solutions(self) -> None:
        self.solution_listbox.selection_set(0, tk.END)
        self.draw_chart()

    def _clear_solution_selection(self) -> None:
        self.solution_listbox.selection_clear(0, tk.END)
        self.draw_chart()

    def _label_font_size(self) -> int:
        return self._clamped_int_text(self.label_font_size_var, 8, 6, 24)

    def _value_font_size(self) -> int:
        return self._clamped_int_text(self.value_font_size_var, 8, 6, 24)

    def _clamped_int_text(self, var: tk.StringVar, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(float(var.get()))
        except (tk.TclError, ValueError):
            value = default
            var.set(str(default))
        value = max(minimum, min(maximum, value))
        var.set(str(value))
        return value

    def _initial_background_color(self) -> str:
        for entry in self.entries:
            color = str(entry.get("target_color", "")).strip()
            if color:
                return self._soft_fill_color(color)
        return "#ffffff"

    def _bar_color(self, entry: dict[str, object]) -> str:
        name = str(entry.get("name", "")).strip()
        return self.bar_colors.get(name, str(entry.get("color", "#f4bd82")))

    def _wrap_label(self, text: str, max_chars: int) -> str:
        cleaned = text.strip()
        if not cleaned or len(cleaned) <= max_chars:
            return cleaned
        parts: list[str] = []
        current = ""
        for chunk in cleaned.replace("-", "_").split("_"):
            candidate = chunk if not current else f"{current}_{chunk}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    parts.append(current)
                current = chunk
        if current:
            parts.append(current)
        if len(parts) <= 1:
            return "\n".join(cleaned[index:index + max_chars] for index in range(0, len(cleaned), max_chars))
        return "\n".join(parts)

    def choose_background_color(self) -> None:
        chosen = colorchooser.askcolor(color=self.background_color_var.get(), parent=self)
        if chosen and chosen[1]:
            self.background_color_var.set(chosen[1])
            self.draw_chart()

    def insert_text_annotation(self) -> None:
        text = simpledialog.askstring("Insert Text", "Text:", parent=self)
        if text is None:
            return
        text = text.strip()
        if not text:
            return
        width = max(self.canvas.winfo_width(), 560)
        height = max(self.canvas.winfo_height(), 360)
        self.text_annotations.append(
            {
                "text": text,
                "x": float(width * 0.5),
                "y": float(height * 0.18),
                "font_size": 11,
                "bold": True,
            }
        )
        self.draw_chart()

    def open_bar_color_settings(self) -> None:
        window = tk.Toplevel(self)
        window.title("Bar Colors")
        window.transient(self)
        window.geometry("420x420")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        frame = ttk.Frame(window, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        names = self._solution_options()
        if not names:
            ttk.Label(frame, text="No bars available.").grid(row=0, column=0, sticky="w")
            return
        for row, name in enumerate(names):
            ttk.Label(frame, text=name).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            button = tk.Button(frame, text="     ", width=4, bg=self.bar_colors.get(name, "#f4bd82"))
            button.grid(row=row, column=1, sticky="w", pady=3)

            def choose(n=name, btn=button) -> None:
                chosen = colorchooser.askcolor(color=self.bar_colors.get(n, "#f4bd82"), parent=window)
                if chosen and chosen[1]:
                    self.bar_colors[n] = chosen[1]
                    btn.configure(bg=chosen[1])
                    self.draw_chart()

            button.configure(command=choose)

    def export_high_resolution_image(self) -> None:
        file_path = filedialog.asksaveasfilename(
            title="Export Bar Chart Image",
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
                messagebox.showinfo("Export Complete", f"Bar chart image exported to:\n{file_path}")
                return
            self._pillow_modules()
            image = self._render_export_image(scale=4)
            if suffix in {".jpg", ".jpeg"}:
                image = image.convert("RGB")
                image.save(file_path, format="JPEG", quality=95, dpi=(300, 300))
            elif suffix in {".tif", ".tiff"}:
                image.save(file_path, format="TIFF", dpi=(300, 300))
            elif suffix == ".bmp":
                image.save(file_path, format="BMP")
            else:
                image.save(file_path, format="PNG", dpi=(300, 300))
            messagebox.showinfo("Export Complete", f"Bar chart image exported to:\n{file_path}")
        except Exception as exc:
            messagebox.showerror("Export Failed", f"Unable to export bar chart image:\n{exc}")

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
                "Pillow is required for PNG/TIFF/JPEG/BMP export.\n\n"
                "Please click the main window's Install Dependencies button, then try Export Image again."
            ) from exc
        Image = loaded_image
        ImageDraw = loaded_image_draw
        ImageFont = loaded_image_font
        return Image, ImageDraw, ImageFont

    def _capture_visible_canvas(self, scale: int = 3):
        self.lift()
        self.update_idletasks()
        self.canvas.update()
        x = self.canvas.winfo_rootx()
        y = self.canvas.winfo_rooty()
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
        if scale > 1:
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            image = image.resize((width * scale, height * scale), resampling)
        return image

    def _render_export_image(self, scale: int = 3):
        entries = self._visible_entries()
        width = max(self.canvas.winfo_width(), 900)
        height = max(self.canvas.winfo_height(), 460)
        image = Image.new("RGB", (width * scale, height * scale), "white")
        draw = ImageDraw.Draw(image)

        def s(value: float) -> int:
            return int(round(value * scale))

        left, right = 82, width - 42
        top = 54
        bottom = height - max(92, self._label_font_size() * 4 + 54)
        if right <= left + 40:
            right = left + 40
        if bottom <= top + 40:
            bottom = top + 40
        title_font = self._export_font(14 * scale, bold=True)
        axis_font = self._export_font(11 * scale, bold=True)
        tick_font = self._export_font(9 * scale)
        label_font = self._export_font(self._label_font_size() * scale, bold=self.label_bold_var.get())
        value_font = self._export_font(self._value_font_size() * scale, bold=self.value_bold_var.get())
        self._draw_export_centered_text(draw, s(width / 2), s(24), self._chart_title(), title_font, "#222222")

        if not entries:
            draw.text((s(24), s(24)), "No Target values to plot.", fill="#666666", font=tick_font)
            self._draw_export_text_annotations(draw, scale)
            return image

        values = [float(entry["value"]) for entry in entries]
        error_bounds = [
            (value - self._entry_error(entry), value + self._entry_error(entry))
            for value, entry in zip(values, entries)
        ]
        min_value = min(0.0, *(lower for lower, _upper in error_bounds))
        max_value = max(0.0, *(upper for _lower, upper in error_bounds))
        if math.isclose(min_value, max_value):
            max_value = min_value + 1.0
        padding = (max_value - min_value) * 0.12
        min_value -= padding
        max_value += padding

        def y_to_px(value: float) -> float:
            return bottom - (value - min_value) * (bottom - top) / (max_value - min_value)

        draw.rectangle((s(left), s(top), s(right), s(bottom)), fill=self.background_color_var.get(), outline="#d0d0d0")
        self._draw_export_backgrounds(draw, entries, left, right, top, bottom, scale)
        zero_y = y_to_px(0.0)
        draw.line((s(left), s(zero_y), s(right), s(zero_y)), fill="#222222", width=s(2))
        draw.line((s(left), s(top), s(left), s(bottom)), fill="#222222", width=s(2))
        draw.line((s(right), s(top), s(right), s(bottom)), fill="#222222", width=s(1))
        draw.line((s(left), s(top), s(right), s(top)), fill="#222222", width=s(1))
        self._draw_export_rotated_text(image, s(26), s((top + bottom) / 2), self.y_axis_title, axis_font)

        tick_count = 6
        for index in range(tick_count + 1):
            value = min_value + (max_value - min_value) * index / tick_count
            y = y_to_px(value)
            draw.line((s(left - 5), s(y), s(right), s(y)), fill="#dddddd", width=s(1))
            draw.line((s(left - 5), s(y), s(left), s(y)), fill="#444444", width=s(1))
            self._draw_export_right_text(draw, s(left - 10), s(y), f"{value:.3f}", tick_font, "#555555")

        slot_width = (right - left) / max(len(entries), 1)
        bar_width = max(18.0, min(58.0, slot_width * 0.55))
        for index, entry in enumerate(entries):
            value = float(entry["value"])
            error = self._entry_error(entry)
            x = left + slot_width * (index + 0.5)
            y = y_to_px(value)
            bar_top = min(y, zero_y)
            bar_bottom = max(y, zero_y)
            draw.rectangle(
                (s(x - bar_width / 2), s(bar_top), s(x + bar_width / 2), s(bar_bottom)),
                fill=self._bar_color(entry),
            )
            if error > 0:
                error_top = y_to_px(value + error)
                error_bottom = y_to_px(value - error)
                cap = min(bar_width * 0.45, 12.0)
                draw.line((s(x), s(error_top), s(x), s(error_bottom)), fill="#111111", width=s(1.2))
                draw.line((s(x - cap), s(error_top), s(x + cap), s(error_top)), fill="#111111", width=s(1.2))
                draw.line((s(x - cap), s(error_bottom), s(x + cap), s(error_bottom)), fill="#111111", width=s(1.2))
            else:
                error_top = bar_top
                error_bottom = bar_bottom
            value_y = min(bar_top, error_top) - (self._value_font_size() + 5) if value >= 0 else max(bar_bottom, error_bottom) + (self._value_font_size() + 5)
            self._draw_export_centered_text(draw, s(x), s(value_y), f"{value:+.3f}", value_font, "#111111")
            label = self._wrap_label(str(entry["name"]), max(7, int(slot_width / max(self._label_font_size() * 0.58, 1))))
            self._draw_export_centered_multiline(draw, s(x), s(bottom + 6), label, label_font, "#333333")
            self._draw_export_centered_text(draw, s(x), s(height - 22), str(index + 1), tick_font, "#111111")
        self._draw_export_text_annotations(draw, scale)
        return image

    def _entry_error(self, entry: dict[str, object]) -> float:
        if not self.show_error_bars_var.get():
            return 0.0
        try:
            return max(0.0, float(entry.get("error", 0.0)))
        except (TypeError, ValueError):
            return 0.0

    def _export_font(self, size: int, bold: bool = False):
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, max(1, int(size)))
            except Exception:
                continue
        return ImageFont.load_default()

    def _draw_export_centered_text(self, draw, x: int, y: int, text: str, font, fill: str) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (bbox[2] - bbox[0]) / 2, y - (bbox[3] - bbox[1]) / 2), text, fill=fill, font=font)

    def _draw_export_right_text(self, draw, x: int, y: int, text: str, font, fill: str) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (bbox[2] - bbox[0]), y - (bbox[3] - bbox[1]) / 2), text, fill=fill, font=font)

    def _draw_export_centered_multiline(self, draw, x: int, y: int, text: str, font, fill: str) -> None:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=2, align="center")
        draw.multiline_text((x - (bbox[2] - bbox[0]) / 2, y), text, fill=fill, font=font, spacing=2, align="center")

    def _draw_export_text_annotations(self, draw, scale: int) -> None:
        for annotation in self.text_annotations:
            text = str(annotation.get("text", "")).strip()
            if not text:
                continue
            try:
                x = float(annotation.get("x", 120.0)) * scale
                y = float(annotation.get("y", 80.0)) * scale
                font_size = int(float(annotation.get("font_size", 11))) * scale
            except (TypeError, ValueError):
                x, y, font_size = 120.0 * scale, 80.0 * scale, 11 * scale
            font = self._export_font(max(6, min(32 * scale, font_size)), bold=bool(annotation.get("bold", True)))
            bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=2 * scale, align="center")
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            pad_x, pad_y = 6 * scale, 4 * scale
            left = x - text_width / 2 - pad_x
            top = y - text_height / 2 - pad_y
            right = x + text_width / 2 + pad_x
            bottom = y + text_height / 2 + pad_y
            draw.rectangle((left, top, right, bottom), fill="#ffffff", outline="#111111", width=max(1, scale))
            draw.multiline_text(
                (x - text_width / 2, y - text_height / 2),
                text,
                fill="#111111",
                font=font,
                spacing=2 * scale,
                align="center",
            )

    def _draw_export_rotated_text(self, image, x: int, y: int, text: str, font) -> None:
        bbox = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)
        text_image = Image.new("RGBA", (bbox[2] - bbox[0] + 8, bbox[3] - bbox[1] + 8), (255, 255, 255, 0))
        text_draw = ImageDraw.Draw(text_image)
        text_draw.text((4, 4), text, fill="#222222", font=font)
        rotated = text_image.rotate(90, expand=True)
        image.paste(rotated, (int(x - rotated.width / 2), int(y - rotated.height / 2)), rotated)

    def _draw_export_backgrounds(self, draw, entries: list[dict[str, object]], left: float, right: float, top: float, bottom: float, scale: int) -> None:
        slot_width = (right - left) / max(len(entries), 1)
        start_index = 0
        while start_index < len(entries):
            target = str(entries[start_index].get("target", "")).strip()
            end_index = start_index
            while end_index + 1 < len(entries) and str(entries[end_index + 1].get("target", "")).strip() == target:
                end_index += 1
            x1 = left + slot_width * start_index
            x2 = left + slot_width * (end_index + 1)
            draw.rectangle(
                (int(x1 * scale), int(top * scale), int(x2 * scale), int(bottom * scale)),
                fill=self.background_color_var.get(),
                outline="#777777",
            )
            start_index = end_index + 1

    def draw_chart(self) -> None:
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 560)
        height = max(self.canvas.winfo_height(), 360)
        entries = self._visible_entries()
        if not entries:
            self.canvas.create_text(
                24,
                24,
                anchor="nw",
                text="No Target values to plot.",
                fill="#666666",
                font=("Segoe UI", 11),
            )
            self._draw_text_annotations()
            return

        left, right = 82, width - 42
        top = 54
        bottom = height - max(92, self._label_font_size() * 4 + 54)
        if right <= left + 40:
            right = left + 40
        if bottom <= top + 40:
            bottom = top + 40

        values = [float(entry["value"]) for entry in entries]
        error_bounds = [
            (value - self._entry_error(entry), value + self._entry_error(entry))
            for value, entry in zip(values, entries)
        ]
        min_value = min(0.0, *(lower for lower, _upper in error_bounds))
        max_value = max(0.0, *(upper for _lower, upper in error_bounds))
        if math.isclose(min_value, max_value):
            max_value = min_value + 1.0
        padding = (max_value - min_value) * 0.12
        min_value -= padding
        max_value += padding

        def y_to_canvas(value: float) -> float:
            return bottom - (value - min_value) * (bottom - top) / (max_value - min_value)

        zero_y = y_to_canvas(0.0)
        self.canvas.create_text(
            width / 2,
            24,
            text=self._chart_title(),
            font=("Segoe UI", 14, "bold"),
            fill="#222222",
        )
        self.canvas.create_rectangle(left, top, right, bottom, outline="#d0d0d0", fill=self.background_color_var.get())
        self._draw_target_backgrounds(entries, left, right, top, bottom)
        self.canvas.create_line(left, zero_y, right, zero_y, fill="#222222", width=2)
        self.canvas.create_line(left, top, left, bottom, fill="#222222", width=2)
        self.canvas.create_line(right, top, right, bottom, fill="#222222", width=1)
        self.canvas.create_line(left, top, right, top, fill="#222222", width=1)
        self.canvas.create_text(
            26,
            (top + bottom) / 2,
            text=self.y_axis_title,
            angle=90,
            font=("Segoe UI", 11, "bold"),
            fill="#222222",
        )

        tick_count = 6
        for index in range(tick_count + 1):
            value = min_value + (max_value - min_value) * index / tick_count
            y = y_to_canvas(value)
            self.canvas.create_line(left - 5, y, right, y, fill="#dddddd")
            self.canvas.create_line(left - 5, y, left, y, fill="#444444")
            self.canvas.create_text(
                left - 10,
                y,
                text=f"{value:.3f}",
                anchor="e",
                fill="#555555",
                font=("Segoe UI", 9),
            )

        slot_width = (right - left) / max(len(entries), 1)
        bar_width = max(18.0, min(58.0, slot_width * 0.55))
        label_font = ("Segoe UI", self._label_font_size(), "bold" if self.label_bold_var.get() else "normal")
        value_font = ("Segoe UI", self._value_font_size(), "bold" if self.value_bold_var.get() else "normal")
        for index, entry in enumerate(entries):
            value = float(entry["value"])
            error = self._entry_error(entry)
            x = left + slot_width * (index + 0.5)
            y = y_to_canvas(value)
            bar_top = min(y, zero_y)
            bar_bottom = max(y, zero_y)
            self.canvas.create_rectangle(
                x - bar_width / 2,
                bar_top,
                x + bar_width / 2,
                bar_bottom,
                fill=self._bar_color(entry),
                outline="",
            )
            if error > 0:
                error_top = y_to_canvas(value + error)
                error_bottom = y_to_canvas(value - error)
                cap = min(bar_width * 0.45, 12.0)
                self.canvas.create_line(x, error_top, x, error_bottom, fill="#111111", width=1.4)
                self.canvas.create_line(x - cap, error_top, x + cap, error_top, fill="#111111", width=1.4)
                self.canvas.create_line(x - cap, error_bottom, x + cap, error_bottom, fill="#111111", width=1.4)
            else:
                error_top = bar_top
                error_bottom = bar_bottom
            value_y = min(bar_top, error_top) - (self._value_font_size() + 5) if value >= 0 else max(bar_bottom, error_bottom) + (self._value_font_size() + 5)
            self.canvas.create_text(
                x,
                value_y,
                text=f"{value:+.3f}",
                fill="#111111",
                font=value_font,
            )
            label = self._wrap_label(str(entry["name"]), max(7, int(slot_width / max(self._label_font_size() * 0.58, 1))))
            self.canvas.create_text(
                x,
                bottom + 6,
                text=label,
                angle=0,
                anchor="n",
                justify="center",
                fill="#333333",
                font=label_font,
            )
            self.canvas.create_text(
                x,
                height - 22,
                text=str(index + 1),
                anchor="n",
                fill="#111111",
                font=("Segoe UI", 9),
            )
        self._draw_text_annotations()

    def _draw_text_annotations(self) -> None:
        self._annotation_hitboxes = []
        for index, annotation in enumerate(self.text_annotations):
            text = str(annotation.get("text", "")).strip()
            if not text:
                continue
            try:
                x = float(annotation.get("x", 120.0))
                y = float(annotation.get("y", 80.0))
                font_size = int(float(annotation.get("font_size", 11)))
            except (TypeError, ValueError):
                x, y, font_size = 120.0, 80.0, 11
            font_size = max(6, min(32, font_size))
            weight = "bold" if bool(annotation.get("bold", True)) else "normal"
            tag = f"bar_text_annotation_{index}"
            text_id = self.canvas.create_text(
                x,
                y,
                text=text,
                fill="#111111",
                font=("Segoe UI", font_size, weight),
                anchor="center",
                justify="center",
                tags=(tag,),
            )
            bbox = self.canvas.bbox(text_id)
            if bbox is None:
                continue
            x1, y1, x2, y2 = bbox
            pad_x, pad_y = 6, 4
            box = (x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y)
            rect_id = self.canvas.create_rectangle(*box, fill="#ffffff", outline="#111111", tags=(tag,))
            self.canvas.tag_lower(rect_id, text_id)
            self._annotation_hitboxes.append((index, box))

    def _start_annotation_drag(self, event: tk.Event) -> None:
        for index, (x1, y1, x2, y2) in reversed(self._annotation_hitboxes):
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._drag_annotation_index = index
                annotation = self.text_annotations[index]
                self._drag_offset = (
                    float(annotation.get("x", event.x)) - float(event.x),
                    float(annotation.get("y", event.y)) - float(event.y),
                )
                return
        self._drag_annotation_index = None

    def _drag_annotation(self, event: tk.Event) -> None:
        if self._drag_annotation_index is None:
            return
        if not (0 <= self._drag_annotation_index < len(self.text_annotations)):
            return
        self.text_annotations[self._drag_annotation_index]["x"] = float(event.x + self._drag_offset[0])
        self.text_annotations[self._drag_annotation_index]["y"] = float(event.y + self._drag_offset[1])
        self.draw_chart()

    def _end_annotation_drag(self, _event: tk.Event) -> None:
        self._drag_annotation_index = None

    def _draw_target_backgrounds(
        self,
        entries: list[dict[str, object]],
        left: float,
        right: float,
        top: float,
        bottom: float,
    ) -> None:
        slot_width = (right - left) / max(len(entries), 1)
        start_index = 0
        while start_index < len(entries):
            target = str(entries[start_index].get("target", "")).strip()
            color = self.background_color_var.get().strip() or str(entries[start_index].get("target_color", "#dff4ff")).strip() or "#dff4ff"
            end_index = start_index
            while end_index + 1 < len(entries) and str(entries[end_index + 1].get("target", "")).strip() == target:
                end_index += 1
            x1 = left + slot_width * start_index
            x2 = left + slot_width * (end_index + 1)
            self.canvas.create_rectangle(x1, top, x2, bottom, fill=color, outline="#777777")
            start_index = end_index + 1

    def _soft_fill_color(self, color: str) -> str:
        text = color.strip()
        if not text.startswith("#") or len(text) not in {4, 7}:
            return text or "#dff4ff"
        if len(text) == 4:
            text = "#" + "".join(char * 2 for char in text[1:])
        try:
            red = int(text[1:3], 16)
            green = int(text[3:5], 16)
            blue = int(text[5:7], 16)
        except ValueError:
            return "#dff4ff"
        red = int(red + (255 - red) * 0.35)
        green = int(green + (255 - green) * 0.35)
        blue = int(blue + (255 - blue) * 0.35)
        return f"#{red:02x}{green:02x}{blue:02x}"

    def _chart_title(self) -> str:
        target = self.target_var.get().strip()
        if target and target != "All":
            return target
        return "Target LSPR Bar Chart"


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
        self._series_shades: dict[str, str] = {}
        self._series_widths: dict[str, str] = {}
        self._stage_regions: list[tuple[float, float, str, str]] = []
        self._target_regions: list[tuple[float, float, str, str]] = []
        self._hidden_time_ranges: list[tuple[float, float]] = []
        self._annotations: list[dict[str, object]] = []
        self._lspr_shift_items: list[dict[str, object]] = []
        self._lspr_bar_entries: list[dict[str, object]] = []
        self._right_label_positions: dict[str, tuple[float, float]] = {}
        self._hidden_right_labels: set[str] = set()
        self._title_positions: dict[str, tuple[float, float]] = {}
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
        self.hide_start_var = tk.StringVar()
        self.hide_end_var = tk.StringVar()
        self.hidden_range_label_var = tk.StringVar(value="Break 0")
        self.text_var = tk.StringVar()
        self.running_buffer_var = tk.StringVar(value="5*SSC")
        self.target_stage_var = tk.StringVar()
        self.lspr_bar_target_var = tk.StringVar()
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
        self.target_stage_box: ttk.Combobox | None = None
        self.lspr_bar_target_box: ttk.Combobox | None = None
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
        ttk.Button(action_bar, text="Labels", command=lambda: self.open_plot_settings("Labels"), width=APP_BUTTON_WIDTH).grid(row=1, column=4, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="Format").grid(row=1, column=5, padx=(8, 4), pady=(6, 0), sticky="w")
        self.format_box = ttk.Combobox(action_bar, textvariable=self.format_preset_var, width=18, state="readonly")
        self.format_box.grid(row=1, column=6, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Save Format", command=self.save_format_preset, width=APP_BUTTON_WIDTH).grid(row=1, column=7, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Apply Format", command=self.apply_selected_format_preset, width=APP_BUTTON_WIDTH).grid(row=1, column=8, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="Running Buffer").grid(row=2, column=0, padx=(0, 4), pady=(6, 0), sticky="w")
        self.running_buffer_box = ttk.Combobox(
            action_bar,
            textvariable=self.running_buffer_var,
            width=22,
            state="readonly",
        )
        self.running_buffer_box.grid(row=2, column=1, padx=(0, 8), pady=(6, 0), sticky="w")
        self.running_buffer_box.bind("<Return>", lambda _event: self.calculate_lspr_shift_for_all_series())
        self.running_buffer_box.bind("<<ComboboxSelected>>", self._on_running_buffer_change)
        ttk.Button(action_bar, text="LSPR Shift", command=self.calculate_lspr_shift_for_all_series, width=APP_BUTTON_WIDTH).grid(row=2, column=2, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="Bar Target").grid(row=2, column=3, padx=(0, 4), pady=(6, 0), sticky="w")
        self.lspr_bar_target_box = ttk.Combobox(
            action_bar,
            textvariable=self.lspr_bar_target_var,
            width=18,
            state="disabled",
        )
        self.lspr_bar_target_box.grid(row=2, column=4, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="LSPR Bar Chart", command=self.show_lspr_shift_bar_chart, width=APP_BUTTON_WIDTH).grid(row=2, column=5, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Clear LSPR", command=self.clear_lspr_shift, width=APP_BUTTON_WIDTH).grid(row=2, column=6, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="LSPR Font").grid(row=2, column=7, padx=(8, 4), pady=(6, 0), sticky="w")
        lspr_font_spin = ttk.Spinbox(
            action_bar,
            from_=7,
            to=24,
            textvariable=self.lspr_font_size_var,
            width=5,
            command=self.draw_chart,
        )
        lspr_font_spin.grid(row=2, column=8, padx=(0, 8), pady=(6, 0), sticky="w")
        lspr_font_spin.bind("<Return>", lambda _event: self.draw_chart())
        lspr_font_spin.bind("<FocusOut>", lambda _event: self.draw_chart())
        ttk.Label(action_bar, text="Target").grid(row=3, column=0, padx=(0, 4), pady=(6, 0), sticky="w")
        self.target_stage_box = ttk.Combobox(
            action_bar,
            textvariable=self.target_stage_var,
            width=22,
            state="readonly",
        )
        self.target_stage_box.grid(row=3, column=1, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Target", command=self.calculate_target_shift_for_selected_stage, width=APP_BUTTON_WIDTH).grid(row=3, column=2, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="Axis Break").grid(row=4, column=0, padx=(0, 4), pady=(6, 0), sticky="w")
        ttk.Entry(action_bar, textvariable=self.hide_start_var, width=10).grid(row=4, column=1, padx=(0, 4), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, text="to").grid(row=4, column=2, padx=(0, 4), pady=(6, 0), sticky="w")
        ttk.Entry(action_bar, textvariable=self.hide_end_var, width=10).grid(row=4, column=3, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Add Break", command=self.add_hidden_time_range, width=APP_BUTTON_WIDTH).grid(row=4, column=4, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Button(action_bar, text="Clear Break", command=self.clear_hidden_time_ranges, width=APP_BUTTON_WIDTH).grid(row=4, column=5, padx=(0, 8), pady=(6, 0), sticky="w")
        ttk.Label(action_bar, textvariable=self.hidden_range_label_var).grid(row=4, column=6, padx=(0, 8), pady=(6, 0), sticky="w")
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
        target_regions: list[tuple[float, float, str, str]] | None = None,
    ) -> None:
        self.data = [list(row) for row in data]
        self.headers = headers[:]
        if stage_regions is not None:
            self._stage_regions = stage_regions[:]
            self.stage_text_var.set(
                "\n".join(f"{start},{end},{label},{color}" for start, end, label, color in self._stage_regions)
            )
        if target_regions is not None:
            self._target_regions = target_regions[:]
        self._refresh_target_stage_options()
        self._refresh_lspr_bar_target_options()
        self._refresh_running_buffer_options()
        if selected_y_names is not None:
            self._selected_y_cache = [name for name in selected_y_names if name in self.headers[1:]]
        else:
            self._selected_y_cache = self.headers[1:]
        self._view_bounds = None
        self._pan_anchor = None
        self._pan_bounds = None
        self._lspr_shift_items = []
        self._lspr_bar_entries = []
        self._populate_controls()
        self.schedule_draw()

    def clear(self) -> None:
        self.data = []
        self.headers = []
        self._series = []
        self._selected_y_cache = []
        self._stage_regions = []
        self._target_regions = []
        self._hidden_time_ranges = []
        self._annotations = []
        self._lspr_shift_items = []
        self._lspr_bar_entries = []
        self._right_label_positions = {}
        self._title_positions = {}
        self._draggables = []
        self._drag_target = None
        self._view_bounds = None
        self._refresh_hidden_range_label()
        self._refresh_running_buffer_options()
        self._refresh_target_stage_options()
        self.canvas.delete("all")
        self._draw_message("Import Average Values to plot curves.")

    def clear_plot(self) -> None:
        self._series = []
        self._lspr_shift_items = []
        self._lspr_bar_entries = []
        self._view_bounds = None
        self._plot_rect = None
        self.canvas.delete("all")
        self._draw_message("Plot cleared. Press Plot Curves to generate again.")

    def clear_lspr_shift(self) -> None:
        self._lspr_shift_items = []
        self._lspr_bar_entries = []
        self._refresh_lspr_bar_target_options()
        self.draw_chart()

    def add_hidden_time_range(self) -> None:
        try:
            start = float(self.hide_start_var.get().strip())
            end = float(self.hide_end_var.get().strip())
        except ValueError:
            messagebox.showinfo("Invalid Axis Break", "Please enter numeric start and end time.")
            return
        if math.isclose(start, end):
            messagebox.showinfo("Invalid Axis Break", "Start and end time cannot be the same.")
            return
        if end < start:
            start, end = end, start
        self._hidden_time_ranges.append((start, end))
        self._hidden_time_ranges = self._merge_hidden_time_ranges(self._hidden_time_ranges)
        self._lspr_shift_items = []
        self._lspr_bar_entries = []
        self._refresh_lspr_bar_target_options()
        self._refresh_hidden_range_label()
        self.draw_chart()

    def clear_hidden_time_ranges(self) -> None:
        self._hidden_time_ranges = []
        self.hide_start_var.set("")
        self.hide_end_var.set("")
        self._lspr_shift_items = []
        self._lspr_bar_entries = []
        self._refresh_lspr_bar_target_options()
        self._refresh_hidden_range_label()
        self.draw_chart()

    def _on_running_buffer_change(self, _event=None) -> None:
        self._lspr_shift_items = []
        self._lspr_bar_entries = []
        self._refresh_lspr_bar_target_options()

    def show_lspr_shift_bar_chart(self) -> None:
        entries = self._lspr_bar_entries or self._build_target_bar_entries()
        selected_target = self.lspr_bar_target_var.get().strip()
        if selected_target:
            filtered_entries = [
                entry
                for entry in entries
                if self._same_target_label(str(entry.get("target", "")), selected_target)
            ]
            if not filtered_entries:
                filtered_entries = self._build_bar_entries_for_target_by_position(selected_target)
            entries = filtered_entries
        if not entries:
            detail = self._lspr_bar_status_detail()
            messagebox.showinfo(
                "No LSPR Shift Data",
                f"Click LSPR Shift first, then create the bar chart from the displayed Target values.\n\n{detail}",
            )
            return
        window = LSPRShiftBarChartWindow(
            self,
            entries,
            initial_target=selected_target,
            y_axis_title=self._locked_y_axis_title(),
        )
        window.focus_set()

    def _same_target_label(self, left: str, right: str) -> bool:
        left_key = self._normalize_stage_name(left)
        right_key = self._normalize_stage_name(right)
        return bool(left_key and right_key and (left_key == right_key or left_key in right_key or right_key in left_key))

    def _refresh_lspr_bar_target_options(self) -> None:
        if self.lspr_bar_target_box is None:
            return
        entries = self._lspr_bar_entries
        targets: list[str] = []
        seen: set[str] = set()
        if entries:
            source = [str(entry.get("target", "")).strip() for entry in entries]
        else:
            source = [
                str(label).strip()
                for _start, _end, label, _color in self._target_region_candidates()
            ]
        for target in source:
            if target and target not in seen:
                seen.add(target)
                targets.append(target)
        self.lspr_bar_target_box["values"] = targets
        if targets:
            current = self.lspr_bar_target_var.get().strip()
            if current not in targets:
                self.lspr_bar_target_var.set(targets[0])
            self.lspr_bar_target_box.configure(state="readonly")
        else:
            self.lspr_bar_target_var.set("")
            self.lspr_bar_target_box.configure(state="disabled")

    def _lspr_bar_status_detail(self) -> str:
        shift_count = sum(1 for item in self._lspr_shift_items if item.get("kind") == "shift")
        target_count = sum(
            1
            for _start, _end, label, _color in (self._target_regions or self._stage_regions)
            if "target" in self._normalize_stage_name(str(label))
        )
        entry_count = len(self._lspr_bar_entries or self._build_target_bar_entries())
        selected_target = self.lspr_bar_target_var.get().strip() or "None"
        return (
            f"Detected LSPR Shift labels: {shift_count}. "
            f"Detected Target regions: {target_count}. "
            f"Generated bar entries: {entry_count}. "
            f"Selected Bar Target: {selected_target}."
        )

    def _build_target_bar_entries(self) -> list[dict[str, object]]:
        shift_items = [item for item in self._lspr_shift_items if item.get("kind") == "shift"]
        if not shift_items:
            return []

        entries: list[dict[str, object]] = []
        for item in shift_items:
            try:
                delta = float(item.get("delta", 0.0))
            except (TypeError, ValueError):
                continue

            target_label = str(item.get("target", "")).strip()
            target_color = str(item.get("target_color", "")).strip()
            if not target_label:
                target_region = self._target_region_for_shift_item(item)
                if target_region is None:
                    continue
                _start, _end, target_label, target_color = target_region

            if not target_label or "target" not in self._normalize_stage_name(target_label):
                continue
            entries.append(
                {
                    "target": target_label,
                    "target_color": target_color or "#dff4ff",
                    "name": str(item.get("series_label") or item.get("series_name") or "LSPR Shift"),
                    "value": delta,
                    "error": self._item_error(item),
                    "color": str(item.get("series_color", "#f4bd82")),
                }
            )
        return entries

    def _build_bar_entries_for_target_by_position(self, selected_target: str) -> list[dict[str, object]]:
        target_region = self._target_region_for_label(selected_target)
        if target_region is None:
            return []
        start, end, target_label, target_color = target_region
        center = (start + end) / 2

        best_by_series: dict[str, tuple[float, dict[str, object]]] = {}
        for item in self._lspr_shift_items:
            if item.get("kind") != "shift":
                continue
            try:
                x_value = float(item.get("x", center))
                delta = float(item.get("delta", 0.0))
            except (TypeError, ValueError):
                continue
            distance = 0.0 if start <= x_value <= end else abs(x_value - center)
            series_label = str(item.get("series_label") or item.get("series_name") or "LSPR Shift")
            candidate = {
                "target": target_label,
                "target_color": target_color or "#dff4ff",
                "name": series_label,
                "value": delta,
                "error": self._item_error(item),
                "color": str(item.get("series_color", "#f4bd82")),
            }
            current = best_by_series.get(series_label)
            if current is None or distance < current[0]:
                best_by_series[series_label] = (distance, candidate)
        return [entry for _distance, entry in best_by_series.values()]

    def _build_all_target_bar_entries_by_position(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for _start, _end, target_label, _target_color in self._target_region_candidates():
            entries.extend(self._build_bar_entries_for_target_by_position(target_label))
        return entries

    def _build_all_target_bar_entries_by_transition(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for target_region in self._target_region_candidates():
            entries.extend(self._build_bar_entries_for_target_transition(target_region))
        return entries

    def _build_bar_entries_for_target_transition(
        self,
        target_region: tuple[float, float, str, str],
    ) -> list[dict[str, object]]:
        start, end, target_label, target_color = target_region
        buffer_pair = self._buffer_indexes_around_region(start, end)
        if buffer_pair is None:
            return []
        previous_index, current_index = buffer_pair
        entries: list[dict[str, object]] = []
        for item in self._lspr_shift_items:
            if item.get("kind") != "shift":
                continue
            try:
                from_index = int(item.get("from", -1))
                to_index = int(item.get("to", -1))
                delta = float(item.get("delta", 0.0))
            except (TypeError, ValueError):
                continue
            if from_index != previous_index or to_index != current_index:
                continue
            entries.append(
                {
                    "target": target_label,
                    "target_color": target_color or "#dff4ff",
                    "name": str(item.get("series_label") or item.get("series_name") or "LSPR Shift"),
                    "value": delta,
                    "error": self._item_error(item),
                    "color": str(item.get("series_color", "#f4bd82")),
                }
            )
        return entries

    def _item_error(self, item: dict[str, object]) -> float:
        try:
            return max(0.0, float(item.get("error", 0.0)))
        except (TypeError, ValueError):
            return 0.0

    def _buffer_indexes_around_region(self, start: float, end: float) -> tuple[int, int] | None:
        buffers = [
            (index + 1, float(region_start), float(region_end), str(label))
            for index, (region_start, region_end, label, _color) in enumerate(self._running_buffer_regions())
        ]
        previous = [region for region in buffers if region[2] <= start + 1e-9]
        following = [region for region in buffers if region[1] >= end - 1e-9]
        if not previous or not following:
            return None
        previous_index = max(previous, key=lambda region: region[2])[0]
        current_index = min(following, key=lambda region: region[1])[0]
        if current_index <= previous_index:
            return None
        return previous_index, current_index

    def _running_buffer_regions(self) -> list[tuple[float, float, str, str]]:
        label = self.running_buffer_var.get().strip() or "5*SSC"
        return [
            (float(start), float(end), str(region_label), str(color))
            for start, end, region_label, color in self._stage_regions
            if self._stage_label_matches(str(region_label), label)
        ]

    def _target_region_for_label(self, selected_target: str) -> tuple[float, float, str, str] | None:
        candidates = self._target_region_candidates()
        for region in candidates:
            if self._same_target_label(region[2], selected_target):
                return region
        if self.lspr_bar_target_box is not None:
            values = list(self.lspr_bar_target_box["values"])
            try:
                index = values.index(selected_target)
            except ValueError:
                index = -1
            if 0 <= index < len(candidates):
                return candidates[index]
        return None

    def _target_region_for_shift_item(self, item: dict[str, object]) -> tuple[float, float, str, str] | None:
        target_regions = self._target_region_candidates()
        if not target_regions:
            return None

        try:
            x_value = float(item.get("x", 0.0))
        except (TypeError, ValueError):
            x_value = None

        if x_value is not None:
            containing = self._target_region_for_shift_x(x_value, target_regions)
            if containing is not None:
                return containing

        series_name = str(item.get("series_name", ""))
        try:
            previous_index = int(item.get("from", -1))
            current_index = int(item.get("to", -1))
        except (TypeError, ValueError):
            previous_index = -1
            current_index = -1

        transition_region = self._target_region_for_lspr_transition(previous_index, current_index)
        if transition_region is not None:
            return transition_region

        previous_segment = self._lspr_segment(series_name, previous_index)
        current_segment = self._lspr_segment(series_name, current_index)
        if previous_segment is not None and current_segment is not None:
            try:
                interval_start = float(previous_segment.get("stage_end", previous_segment.get("end", 0.0)))
                interval_end = float(current_segment.get("stage_start", current_segment.get("start", 0.0)))
            except (TypeError, ValueError):
                interval_start = None
                interval_end = None
            if interval_start is not None and interval_end is not None:
                between = self._target_region_between(interval_start, interval_end)
                if between is not None:
                    return between
                midpoint = (interval_start + interval_end) / 2
                nearest = self._nearest_target_region(midpoint, target_regions)
                if nearest is not None:
                    return nearest

        if x_value is not None:
            return self._nearest_target_region(x_value, target_regions)
        return None

    def _target_region_for_lspr_transition(self, previous_index: int, current_index: int) -> tuple[float, float, str, str] | None:
        if previous_index <= 0 or current_index <= previous_index:
            return None
        buffer_regions = [
            (float(start), float(end), str(label), str(color))
            for start, end, label, color in self._stage_regions
            if self._stage_label_matches(str(label), self.running_buffer_var.get().strip() or "5*SSC")
        ]
        if previous_index > len(buffer_regions) or current_index > len(buffer_regions):
            return None
        previous_region = buffer_regions[previous_index - 1]
        current_region = buffer_regions[current_index - 1]
        return self._target_region_between(previous_region[1], current_region[0])

    def _lspr_segment(self, series_name: str, index: int) -> dict[str, object] | None:
        for item in self._lspr_shift_items:
            if item.get("kind") != "segment":
                continue
            if str(item.get("series_name", "")) != series_name:
                continue
            try:
                item_index = int(item.get("index", -1))
            except (TypeError, ValueError):
                continue
            if item_index == index:
                return item
        return None

    def _target_region_between(self, start: float, end: float) -> tuple[float, float, str, str] | None:
        candidate_regions = self._target_region_candidates()
        candidates = [
            region
            for region in candidate_regions
            if region[1] >= start - 1e-9 and region[0] <= end + 1e-9
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda region: min(region[1], end) - max(region[0], start))

    def _target_region_candidates(self) -> list[tuple[float, float, str, str]]:
        regions = self._target_regions or self._stage_regions
        candidates: list[tuple[float, float, str, str]] = []
        for region_start, region_end, label, color in regions:
            label_text = str(label)
            if "target" not in self._normalize_stage_name(label_text):
                continue
            try:
                candidates.append((float(region_start), float(region_end), label_text, str(color)))
            except (TypeError, ValueError):
                continue
        return candidates

    def _nearest_target_region(
        self,
        x_value: float,
        target_regions: list[tuple[float, float, str, str]],
    ) -> tuple[float, float, str, str] | None:
        if not target_regions:
            return None

        def distance(region: tuple[float, float, str, str]) -> float:
            start, end, _label, _color = region
            if start <= x_value <= end:
                return 0.0
            return min(abs(x_value - start), abs(x_value - end))

        nearest = min(target_regions, key=distance)
        nearest_distance = distance(nearest)
        widths = [max(end - start, 1.0) for start, end, _label, _color in target_regions]
        tolerance = max(widths) * 1.25
        if nearest_distance <= tolerance:
            return nearest
        return None

    def _target_region_for_shift_x(
        self,
        x_value: float,
        target_regions: list[tuple[float, float, str, str]],
    ) -> tuple[float, float, str, str] | None:
        for region in target_regions:
            start, end, _label, _color = region
            if start <= x_value <= end:
                return region
        return None

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
        curve_names = self._selected_y_names() or self.headers[1:]
        hidden_indexes = [
            index
            for index, name in enumerate(curve_names)
            if name in self._hidden_right_labels
        ]
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
            "axis_break_ranges": [list(item) for item in self._hidden_time_ranges],
            "hidden_time_ranges": [list(item) for item in self._hidden_time_ranges],
            "series_labels": dict(self._series_labels),
            "series_colors": dict(self._series_colors),
            "series_shades": dict(self._series_shades),
            "series_widths": dict(self._series_widths),
            "hidden_right_labels": sorted(self._hidden_right_labels),
            "hidden_right_label_indexes": hidden_indexes,
            "legend_position": list(self._legend_position) if self._legend_position else None,
            "right_label_positions": {key: list(value) for key, value in self._right_label_positions.items()},
            "title_positions": {key: list(value) for key, value in self._title_positions.items()},
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
        self._hidden_time_ranges = self._parse_hidden_time_ranges(
            preset.get("axis_break_ranges", preset.get("hidden_time_ranges", []))
        )
        self._refresh_hidden_range_label()

        self._series_labels.update(self._string_dict(preset.get("series_labels", {})))
        self._series_colors.update(self._string_dict(preset.get("series_colors", {})))
        self._series_shades.update(self._string_dict(preset.get("series_shades", {})))
        self._series_widths.update(self._string_dict(preset.get("series_widths", {})))
        current_curve_names = self._selected_y_names() or self.headers[1:]
        hidden_labels = preset.get("hidden_right_labels", [])
        hidden_indexes = preset.get("hidden_right_label_indexes", [])
        hidden_names = {str(name) for name in hidden_labels} if isinstance(hidden_labels, list) else set()
        if isinstance(hidden_indexes, list):
            for raw_index in hidden_indexes:
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(current_curve_names):
                    hidden_names.add(current_curve_names[index])
        self._hidden_right_labels = hidden_names
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
        raw_title_positions = preset.get("title_positions", {})
        if not isinstance(raw_title_positions, dict):
            raw_title_positions = {}
        self._title_positions = {
            str(key): value
            for key, raw in raw_title_positions.items()
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

    def _parse_hidden_time_ranges(self, value: object) -> list[tuple[float, float]]:
        if not isinstance(value, list):
            return []
        ranges: list[tuple[float, float]] = []
        for item in value:
            parsed = self._point_tuple(item)
            if parsed is None:
                continue
            start, end = parsed
            if math.isclose(start, end):
                continue
            ranges.append((min(start, end), max(start, end)))
        return self._merge_hidden_time_ranges(ranges)

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
        labels_tab = ttk.Frame(notebook, padding=10)
        stages = ttk.Frame(notebook, padding=10)
        notebook.add(general, text="General")
        notebook.add(curves, text="Curves")
        notebook.add(labels_tab, text="Labels")
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
        style_controls: list[tuple[str, tk.StringVar, tk.StringVar, tk.Variable, tk.StringVar, tk.Button]] = []
        if not curve_names:
            ttk.Label(curves, text="Create a plot first.").grid(row=0, column=0, sticky="w")
        global_color_var = tk.StringVar(value=self._series_colors.get(curve_names[0], "#1f77b4") if curve_names else "#1f77b4")
        global_shade_var = tk.DoubleVar(value=100.0)
        global_shade_label_var = tk.StringVar(value="100")
        global_width_var = tk.StringVar(value=self.line_width_var.get() or "2")
        global_bar = ttk.Frame(curves)
        global_bar.grid(row=0, column=0, columnspan=7, sticky="ew", pady=(0, 8))
        ttk.Label(global_bar, text="All Curves").grid(row=0, column=0, padx=(0, 8), sticky="w")
        global_color_button = tk.Button(global_bar, text="     ", bg=global_color_var.get(), width=4)
        global_color_button.grid(row=0, column=1, padx=(0, 8), sticky="w")
        ttk.Label(global_bar, text="Shade").grid(row=0, column=2, padx=(0, 4), sticky="w")
        ttk.Scale(
            global_bar,
            from_=0,
            to=200,
            variable=global_shade_var,
            orient="horizontal",
            length=120,
            command=lambda value: global_shade_label_var.set(str(int(float(value)))),
        ).grid(row=0, column=3, padx=(0, 4), sticky="w")
        ttk.Label(global_bar, textvariable=global_shade_label_var, width=4).grid(row=0, column=4, padx=(0, 8), sticky="w")
        ttk.Label(global_bar, text="Width").grid(row=0, column=5, padx=(0, 4), sticky="w")
        ttk.Spinbox(global_bar, from_=1, to=12, textvariable=global_width_var, width=5).grid(row=0, column=6, padx=(0, 8), sticky="w")

        def choose_global_color() -> None:
            chosen = colorchooser.askcolor(color=global_color_var.get(), parent=window)
            if chosen and chosen[1]:
                global_color_var.set(chosen[1])
                global_color_button.configure(bg=chosen[1])

        def apply_all_curves() -> None:
            base_color = global_color_var.get().strip() or "#000000"
            shade = self._clamped_number_var(global_shade_var, 100, 0, 200)
            display_color = self._shade_color(base_color, shade)
            width = str(self._clamped_int_text(global_width_var, 2, 1, 12))
            self.line_width_var.set(width)
            for name, _label_var, color_var, shade_var, width_var, color_button in style_controls:
                color_var.set(base_color)
                shade_var.set(shade)
                width_var.set(width)
                self._series_colors[name] = base_color
                self._series_shades[name] = str(shade)
                self._series_widths[name] = width
                color_button.configure(bg=display_color)
            self.draw_chart()

        global_color_button.configure(command=choose_global_color)
        ttk.Button(global_bar, text="Apply All", command=apply_all_curves, width=APP_BUTTON_WIDTH).grid(row=0, column=7, padx=(0, 8), sticky="w")
        for row, name in enumerate(curve_names):
            color = self._series_colors.get(name, self._series_color(row, len(curve_names)))
            label_var = tk.StringVar(value=self._series_labels.get(name, name))
            color_var = tk.StringVar(value=color)
            try:
                initial_shade = float(self._series_shades.get(name, "100"))
            except (TypeError, ValueError):
                initial_shade = 100.0
            initial_shade = max(0.0, min(200.0, initial_shade))
            shade_var = tk.DoubleVar(value=initial_shade)
            shade_label_var = tk.StringVar(value=str(int(initial_shade)))
            width_var = tk.StringVar(value=self._series_widths.get(name, self.line_width_var.get() or "2"))
            self._series_labels[name] = label_var.get()
            self._series_colors[name] = color_var.get()
            self._series_shades.setdefault(name, str(int(initial_shade)))
            self._series_widths[name] = width_var.get()
            grid_row = row + 1
            ttk.Label(curves, text=name).grid(row=grid_row, column=0, sticky="w", pady=3, padx=(0, 8))
            ttk.Entry(curves, textvariable=label_var).grid(row=grid_row, column=1, sticky="ew", pady=3, padx=(0, 8))
            color_button = tk.Button(curves, text="     ", bg=self._shade_color(color_var.get(), int(initial_shade)), width=4)
            color_button.grid(row=grid_row, column=2, sticky="w", pady=3)
            ttk.Label(curves, text="Shade").grid(row=grid_row, column=3, sticky="e", padx=(8, 4), pady=3)
            ttk.Scale(
                curves,
                from_=0,
                to=200,
                variable=shade_var,
                orient="horizontal",
                length=110,
                command=lambda value, v=shade_label_var: v.set(str(int(float(value)))),
            ).grid(row=grid_row, column=4, sticky="w", pady=3)
            ttk.Label(curves, textvariable=shade_label_var, width=4).grid(row=grid_row, column=5, sticky="w", pady=3)
            ttk.Label(curves, text="Width").grid(row=grid_row, column=6, sticky="e", padx=(8, 4), pady=3)
            ttk.Spinbox(curves, from_=1, to=12, textvariable=width_var, width=5).grid(row=grid_row, column=7, sticky="w", pady=3)
            style_controls.append((name, label_var, color_var, shade_var, width_var, color_button))

            def save_curve(n=name, lv=label_var, cv=color_var, sv=shade_var, wv=width_var, btn=color_button) -> None:
                self._series_labels[n] = lv.get().strip() or n
                base_color = cv.get().strip() or self._series_colors.get(n, "#000000")
                shade = self._clamped_number_var(sv, 100, 0, 200)
                self._series_colors[n] = base_color
                self._series_shades[n] = str(shade)
                self._series_widths[n] = str(self._clamped_int_text(wv, 2, 1, 12))
                btn.configure(bg=self._shade_color(base_color, shade))
                self.draw_chart()

            def choose_color(n=name, cv=color_var, sv=shade_var, btn=color_button) -> None:
                chosen = colorchooser.askcolor(color=cv.get(), parent=window)
                if chosen and chosen[1]:
                    cv.set(chosen[1])
                    self._series_colors[n] = chosen[1]
                    btn.configure(bg=self._shade_color(chosen[1], self._clamped_number_var(sv, 100, 0, 200)))
                    self.draw_chart()

            color_button.configure(command=choose_color)
            ttk.Button(curves, text="Apply", command=save_curve, width=APP_BUTTON_WIDTH).grid(row=grid_row, column=8, padx=(8, 0), pady=3)

        labels_tab.columnconfigure(0, weight=1)
        labels_tab.columnconfigure(2, weight=1)
        ttk.Label(labels_tab, text="Right-side curve labels").grid(row=0, column=0, sticky="w")
        right_label_list = tk.Listbox(labels_tab, selectmode=tk.MULTIPLE, exportselection=False, height=10)
        right_label_list.grid(row=1, column=0, sticky="nsew", pady=(4, 8), padx=(0, 8))
        labels_tab.rowconfigure(1, weight=1)
        for name in curve_names:
            label = self._series_labels.get(name, name)
            state = "hidden" if name in self._hidden_right_labels else "shown"
            right_label_list.insert(tk.END, f"{label}  [{state}]")

        right_buttons = ttk.Frame(labels_tab)
        right_buttons.grid(row=1, column=1, sticky="ns", padx=(0, 16))

        def hide_selected_right_labels() -> None:
            for index in right_label_list.curselection():
                if 0 <= index < len(curve_names):
                    self._hidden_right_labels.add(curve_names[index])
            self.draw_chart()
            window.destroy()
            self.open_plot_settings("Labels")

        def show_all_right_labels() -> None:
            self._hidden_right_labels.clear()
            self.draw_chart()
            window.destroy()
            self.open_plot_settings("Labels")

        def hide_all_right_labels() -> None:
            self._hidden_right_labels = set(curve_names)
            self.draw_chart()
            window.destroy()
            self.open_plot_settings("Labels")

        ttk.Button(right_buttons, text="Hide", command=hide_selected_right_labels, width=APP_BUTTON_WIDTH).grid(row=0, column=0, pady=(0, 6))
        ttk.Button(right_buttons, text="Hide All", command=hide_all_right_labels, width=APP_BUTTON_WIDTH).grid(row=1, column=0, pady=(0, 6))
        ttk.Button(right_buttons, text="Show All", command=show_all_right_labels, width=APP_BUTTON_WIDTH).grid(row=2, column=0)

        ttk.Label(labels_tab, text="Inserted text labels").grid(row=0, column=2, sticky="w")
        annotation_list = tk.Listbox(labels_tab, selectmode=tk.MULTIPLE, exportselection=False, height=10)
        annotation_list.grid(row=1, column=2, sticky="nsew", pady=(4, 8))
        for annotation in self._annotations:
            text = str(annotation.get("text", "")).strip()
            annotation_list.insert(tk.END, text if text else "(empty)")
        annotation_buttons = ttk.Frame(labels_tab)
        annotation_buttons.grid(row=2, column=2, sticky="w")

        def add_text_label() -> None:
            text = simpledialog.askstring("Add Plot Label", "Text:", parent=window)
            if text is None:
                return
            text = text.strip()
            if not text:
                return
            width = max(self.canvas.winfo_width(), 600)
            height = max(self.canvas.winfo_height(), 380)
            self._annotations.append({"x": float(width * 0.5), "y": float(height * 0.18), "text": text})
            self.draw_chart()
            window.destroy()
            self.open_plot_settings("Labels")

        def delete_selected_text_labels() -> None:
            for index in sorted(annotation_list.curselection(), reverse=True):
                if 0 <= index < len(self._annotations):
                    del self._annotations[index]
            self.draw_chart()
            window.destroy()
            self.open_plot_settings("Labels")

        ttk.Button(annotation_buttons, text="Add Text", command=add_text_label, width=APP_BUTTON_WIDTH).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(annotation_buttons, text="Delete", command=delete_selected_text_labels, width=APP_BUTTON_WIDTH).grid(row=0, column=1)

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
            for name, label_var, color_var, shade_var, width_var, color_button in style_controls:
                self._series_labels[name] = label_var.get().strip() or name
                base_color = color_var.get().strip() or self._series_colors.get(name, "#000000")
                shade = self._clamped_number_var(shade_var, 100, 0, 200)
                self._series_colors[name] = base_color
                self._series_shades[name] = str(shade)
                self._series_widths[name] = str(self._clamped_int_text(width_var, 2, 1, 12))
                color_button.configure(bg=self._shade_color(base_color, shade))
            stage_text_value = stage_text.get("1.0", "end").strip()
            if self._is_default_stage_example(stage_text_value):
                stage_text_value = ""
            self.stage_text_var.set(stage_text_value)
            self._parse_stage_regions()
            self._refresh_running_buffer_options()
            self._refresh_target_stage_options()
            self.tick_font_size_var.set(str(self._clamped_int_text(self.tick_font_size_var, 9, 7, 24)))
            if self.grid_style_var.get() not in {"solid", "dash", "dot", "dash dot"}:
                self.grid_style_var.set("solid")
            self.draw_chart()

        ttk.Button(button_bar, text="Apply", command=apply_settings, width=APP_BUTTON_WIDTH).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(button_bar, text="Apply and Close", command=lambda: (apply_settings(), window.destroy()), width=APP_BUTTON_WIDTH).grid(row=0, column=2)
        if initial_tab == "Curves":
            notebook.select(curves)
        elif initial_tab == "Labels":
            notebook.select(labels_tab)

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
        ys = [y for item in series for _x, y in self._visible_points(item.points)]
        if not ys:
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
        self._draw_lspr_sample_windows(left, top, right, bottom, x_min, x_max)
        if self.show_grid_var.get():
            self._draw_grid(left, top, right, bottom)
        self._draw_axes(left, top, right, bottom, x_min, x_max, y_min, y_max)
        self._draw_series(series, left, top, right, bottom, x_min, x_max, y_min, y_max, line_width, point_size)
        self._draw_axis_break_marks(left, top, right, bottom, x_min, x_max)
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
        self._lspr_bar_entries = []
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

    def _refresh_target_stage_options(self) -> None:
        if self.target_stage_box is None:
            return
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
        self.target_stage_box["values"] = labels
        if labels:
            current = self.target_stage_var.get().strip()
            if current not in labels:
                preferred = next((label for label in labels if "target" in self._normalize_stage_name(label)), labels[0])
                self.target_stage_var.set(preferred)
            self.target_stage_box.configure(state="readonly")
        else:
            self.target_stage_var.set("")
            self.target_stage_box.configure(state="disabled")

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
        self._lspr_bar_entries = self._build_target_bar_entries()
        if not self._lspr_bar_entries:
            self._lspr_bar_entries = self._build_all_target_bar_entries_by_transition()
        self._refresh_lspr_bar_target_options()
        self.draw_chart()

    def calculate_lspr_shift_for_first_series(self) -> None:
        self.calculate_lspr_shift_for_all_series()

    def calculate_target_shift_for_selected_stage(self) -> None:
        self.draw_chart()
        if not self._series:
            messagebox.showinfo("No Plot", "Create a plot first.")
            return
        if not self._stage_regions:
            messagebox.showinfo("No Stage Regions", "No stage background regions were found.")
            return
        selected_label = self.target_stage_var.get().strip()
        if not selected_label:
            messagebox.showinfo("No Target", "Please select a List name in Target.")
            return

        target_items: list[dict[str, object]] = []
        bar_entries: list[dict[str, object]] = []
        selected_regions = self._selected_stage_regions(selected_label)
        if not selected_regions:
            messagebox.showinfo("No Target", f"No regions matching {selected_label} were found.")
            return

        for region_index, region in enumerate(selected_regions):
            items, entries = self._calculate_center_stage_shift_items(region, region_index, len(selected_regions))
            target_items.extend(items)
            bar_entries.extend(entries)

        if not target_items:
            messagebox.showinfo(
                "No Target Shift",
                f"No usable left/right stages were found for {selected_label}.",
            )
            return
        self._lspr_shift_items = target_items
        self._lspr_bar_entries = bar_entries
        self._refresh_lspr_bar_target_options()
        if bar_entries:
            self.lspr_bar_target_var.set(str(bar_entries[0].get("target", "")))
        self.draw_chart()

    def _selected_stage_regions(self, selected_label: str) -> list[tuple[float, float, str, str]]:
        regions: list[tuple[float, float, str, str]] = []
        for start, end, label, color in self._stage_regions:
            if self._stage_label_matches(str(label), selected_label):
                regions.append((float(start), float(end), str(label), str(color)))
        return regions

    def _calculate_center_stage_shift_items(
        self,
        target_region: tuple[float, float, str, str],
        region_index: int,
        region_count: int,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        start, end, label, color = target_region
        neighbors = self._neighbor_regions_for_stage(start, end)
        if neighbors is None:
            return [], []
        left_region, right_region = neighbors

        items: list[dict[str, object]] = []
        bar_entries: list[dict[str, object]] = []
        for series_index, series in enumerate(self._series):
            points = self._points_for_lspr(series)
            left_values, left_window_start, left_window_end = self._stage_region_value_window(points, left_region[0], left_region[1])
            right_values, right_window_start, right_window_end = self._stage_region_value_window(points, right_region[0], right_region[1])
            if not left_values or not right_values:
                continue
            left_avg = sum(left_values) / len(left_values)
            right_avg = sum(right_values) / len(right_values)
            left_error = self._standard_error(left_values)
            right_error = self._standard_error(right_values)
            delta_error = math.sqrt(left_error**2 + right_error**2)
            delta = right_avg - left_avg
            y_span = max((max(y for _x, y in points) - min(y for _x, y in points)), 0.001)
            label_offset = y_span * (0.04 + min(series_index, 8) * 0.025)
            if (region_index + series_index) % 2:
                label_offset *= -1
            label_x = (start + end) / 2
            label_y = max(left_avg, right_avg) + label_offset
            items.append(
                {
                    "kind": "segment",
                    "start": float(left_window_start),
                    "end": float(left_window_end),
                    "stage_start": float(left_region[0]),
                    "stage_end": float(left_region[1]),
                    "avg": float(left_avg),
                    "error": float(left_error),
                    "label": str(left_region[2]),
                    "index": 1,
                    "series_name": series.name,
                    "series_label": series.label,
                    "series_color": series.color,
                    "series_index": series_index,
                }
            )
            items.append(
                {
                    "kind": "segment",
                    "start": float(right_window_start),
                    "end": float(right_window_end),
                    "stage_start": float(right_region[0]),
                    "stage_end": float(right_region[1]),
                    "avg": float(right_avg),
                    "error": float(right_error),
                    "label": str(right_region[2]),
                    "index": 2,
                    "series_name": series.name,
                    "series_label": series.label,
                    "series_color": series.color,
                    "series_index": series_index,
                }
            )
            item = {
                "kind": "shift",
                "x": float(label_x),
                "y": float(label_y),
                "delta": float(delta),
                "error": float(delta_error),
                "series_name": series.name,
                "series_label": series.label,
                "series_color": series.color,
                "series_index": series_index,
                "target": str(label),
                "target_color": str(color),
            }
            items.append(item)
            bar_entries.append(
                {
                    "target": str(label),
                    "target_color": str(color),
                    "name": str(series.label),
                    "value": float(delta),
                    "error": float(delta_error),
                    "color": str(series.color),
                }
            )
        return items, bar_entries

    def _neighbor_regions_for_stage(
        self,
        start: float,
        end: float,
    ) -> tuple[tuple[float, float, str, str], tuple[float, float, str, str]] | None:
        regions = sorted(
            [(float(region_start), float(region_end), str(label), str(color)) for region_start, region_end, label, color in self._stage_regions],
            key=lambda region: (region[0], region[1]),
        )
        previous_regions = [region for region in regions if region[1] <= start + 1e-9]
        next_regions = [region for region in regions if region[0] >= end - 1e-9]
        if not previous_regions or not next_regions:
            return None
        return max(previous_regions, key=lambda region: region[1]), min(next_regions, key=lambda region: region[0])

    def _stage_region_average(self, points: list[tuple[float, float]], start: float, end: float) -> float | None:
        values = self._stage_region_values(points, start, end)
        if not values:
            return None
        return sum(values) / len(values)

    def _standard_error(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        return math.sqrt(variance) / math.sqrt(len(values))

    def _stage_region_sample_window(self, start: float, end: float) -> tuple[float, float]:
        if end <= start:
            return start, end
        window_end = end - 20.0
        if window_end <= start:
            window_end = end
        window_start = max(start, window_end - 80.0)
        return window_start, window_end

    def _stage_region_value_window(
        self,
        points: list[tuple[float, float]],
        start: float,
        end: float,
    ) -> tuple[list[float], float, float]:
        if end <= start:
            return [], start, end
        window_start, window_end = self._stage_region_sample_window(start, end)
        values = [y_value for x_value, y_value in points if window_start <= x_value <= window_end]
        if values:
            return values, window_start, window_end
        values = [y_value for x_value, y_value in points if start <= x_value <= end]
        return values, start, end

    def _stage_region_values(self, points: list[tuple[float, float]], start: float, end: float) -> list[float]:
        values, _window_start, _window_end = self._stage_region_value_window(points, start, end)
        return values

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
            window_values, window_start, window_end = self._stage_region_value_window(points, float(start), float(end))
            if not window_values:
                continue
            avg = sum(window_values) / len(window_values)
            error = self._standard_error(window_values)
            segments.append(
                {
                    "kind": "segment",
                    "start": float(window_start),
                    "end": float(window_end),
                    "stage_start": float(start),
                    "stage_end": float(end),
                    "avg": float(avg),
                    "error": float(error),
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
            error = math.sqrt(float(segment.get("error", 0.0)) ** 2 + float(previous.get("error", 0.0)) ** 2)
            previous_end = float(previous["end"])
            current_start = float(segment["start"])
            if current_start > previous_end:
                label_x = (previous_end + current_start) / 2
            else:
                label_x = (float(segment["start"]) + float(segment["end"])) / 2
            label_y = max(float(previous["avg"]), float(segment["avg"])) + label_offset
            target_region = self._target_region_between(float(previous["stage_end"]), float(segment["stage_start"]))
            target_payload = {}
            if target_region is not None:
                _target_start, _target_end, target_label, target_color = target_region
                target_payload = {
                    "target": target_label,
                    "target_color": target_color,
                }
            items.append(
                {
                    "kind": "shift",
                    "x": float(label_x),
                    "y": float(label_y),
                    "delta": delta,
                    "error": float(error),
                    "from": int(previous["index"]),
                    "to": int(segment["index"]),
                    "series_name": series.name,
                    "series_label": series.label,
                    "series_color": series.color,
                    "series_index": series_index,
                    **target_payload,
                }
            )
        return items

    def _points_for_lspr(self, series: PlotSeries) -> list[tuple[float, float]]:
        points = series.points
        if self._smooth_enabled() and len(points) >= 5:
            smoothed: list[tuple[float, float]] = []
            for segment in self._visible_point_segments(points):
                if len(segment) >= 5:
                    smoothed.extend(self._savitzky_golay_points(segment))
                else:
                    smoothed.extend(segment)
            return smoothed
        return self._visible_points(points)

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
        text = text.replace("×", "x")
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
                y = self._y_to_canvas(float(item["avg"]), top, bottom, y_min, y_max)
                y = max(top + 3, min(bottom - 3, y))
                color = str(item.get("series_color", "#ff0000"))
                for visible_start, visible_end in self._visible_interval_segments(float(item["start"]), float(item["end"]), x_min, x_max):
                    x1 = self._x_to_canvas(visible_start, left, right, x_min, x_max)
                    x2 = self._x_to_canvas(visible_end, left, right, x_min, x_max)
                    if x2 < left or x1 > right:
                        continue
                    x1 = max(left, min(right, x1))
                    x2 = max(left, min(right, x2))
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

    def _draw_lspr_sample_windows(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
        x_min: float,
        x_max: float,
    ) -> None:
        if not self._lspr_shift_items:
            return
        drawn_windows: set[tuple[float, float]] = set()
        for item in self._lspr_shift_items:
            if item.get("kind") != "segment":
                continue
            try:
                start = float(item["start"])
                end = float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            key = (round(start, 6), round(end, 6))
            if key in drawn_windows:
                continue
            drawn_windows.add(key)
            for visible_start, visible_end in self._visible_interval_segments(start, end, x_min, x_max):
                x1 = self._x_to_canvas(visible_start, left, right, x_min, x_max)
                x2 = self._x_to_canvas(visible_end, left, right, x_min, x_max)
                if abs(x2 - x1) < 2:
                    continue
                self.canvas.create_rectangle(
                    x1,
                    top,
                    x2,
                    bottom,
                    fill="#FFF2A8",
                    outline="#C89A00",
                    stipple="gray25",
                )

    def _draw_export_lspr_shift_items(self, draw, x_to_px, y_to_px, font, scale: float, x_min: float, x_max: float) -> None:
        if not self._lspr_shift_items:
            return
        for item in self._lspr_shift_items:
            kind = item.get("kind")
            if kind == "segment":
                y = y_to_px(float(item["avg"]))
                color = str(item.get("series_color", "#ff0000"))
                for visible_start, visible_end in self._visible_interval_segments(float(item["start"]), float(item["end"]), x_min, x_max):
                    x1 = x_to_px(visible_start)
                    x2 = x_to_px(visible_end)
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

    def _draw_export_lspr_sample_windows(
        self,
        draw,
        left: float,
        top: float,
        right: float,
        bottom: float,
        x_min: float,
        x_max: float,
        x_to_px,
        scale: float,
    ) -> None:
        if not self._lspr_shift_items:
            return
        drawn_windows: set[tuple[float, float]] = set()
        for item in self._lspr_shift_items:
            if item.get("kind") != "segment":
                continue
            try:
                start = float(item["start"])
                end = float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            key = (round(start, 6), round(end, 6))
            if key in drawn_windows:
                continue
            drawn_windows.add(key)
            for visible_start, visible_end in self._visible_interval_segments(start, end, x_min, x_max):
                x1 = x_to_px(visible_start)
                x2 = x_to_px(visible_end)
                if abs(x2 - x1) < 2:
                    continue
                draw.rectangle(
                    (x1, top, x2, bottom),
                    fill="#FFF2A8",
                    outline="#C89A00",
                    width=max(1, int(scale)),
                )

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
            return self._x_to_canvas(value, left, right, x_min, x_max)

        def y_to_px(value: float) -> float:
            if math.isclose(y_min, y_max):
                return (top + bottom) / 2
            return bottom - (value - y_min) * (bottom - top) / (y_max - y_min)

        draw.rectangle((left, top, right, bottom), fill="white", outline="#d0d0d0", width=max(1, int(scale)))
        self._draw_export_stage_regions(draw, left, top, right, bottom, x_min, x_max, x_to_px, font_label, scale)
        self._draw_export_lspr_sample_windows(draw, left, top, right, bottom, x_min, x_max, x_to_px, scale)
        if self.show_grid_var.get():
            self._draw_export_grid(draw, left, top, right, bottom, scale)
        self._draw_export_axes(draw, left, top, right, bottom, x_min, x_max, y_min, y_max, x_to_px, y_to_px, font_tick, scale)
        self._export_plot_rect = (left, top, right, bottom)
        self._draw_export_series(draw, series, x_to_px, y_to_px, line_width, point_size, scale)
        self._draw_export_axis_break_marks(draw, left, top, right, bottom, x_min, x_max, x_to_px, scale)
        self._export_plot_rect = (0, 0, width, height)
        self._draw_export_lspr_shift_items(draw, x_to_px, y_to_px, font_lspr, scale, x_min, x_max)
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
        ys = [y for item in series for _x, y in self._visible_points(item.points)]
        if not ys:
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
            for visible_start, visible_end in self._visible_interval_segments(start, end, x_min, x_max):
                x1 = x_to_px(visible_start)
                x2 = x_to_px(visible_end)
                if abs(x2 - x1) < 2:
                    continue
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
            if self._is_x_hidden(value):
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

    def _draw_export_axis_break_marks(
        self,
        draw,
        left: int,
        top: int,
        right: int,
        bottom: int,
        x_min: float,
        x_max: float,
        x_to_px,
        scale: float,
    ) -> None:
        mark_width = max(2, int(2 * scale))
        pad_x = 13 * scale
        pad_y = 9 * scale
        for start, end in self._active_axis_break_ranges(x_min, x_max):
            x1 = x_to_px(start)
            x2 = x_to_px(end)
            x = (x1 + x2) / 2
            if x < left - 20 * scale or x > right + 20 * scale:
                continue
            for y in (top, bottom):
                draw.rectangle((x - pad_x, y - pad_y, x + pad_x, y + pad_y), fill="#ffffff")
                draw.line((x - 9 * scale, y + 7 * scale, x - 2 * scale, y - 7 * scale), fill="#222222", width=mark_width)
                draw.line((x + 2 * scale, y + 7 * scale, x + 9 * scale, y - 7 * scale), fill="#222222", width=mark_width)

    def _draw_export_series(self, draw, series: list[PlotSeries], x_to_px, y_to_px, line_width: int, point_size: int, scale: float) -> None:
        chart_type = self.chart_type_var.get()
        radius = max(1, int(point_size * scale))
        left, top, right, bottom = self._export_plot_rect
        for item in series:
            width = max(1, int(self._series_line_width(item.name, line_width) * scale))
            if chart_type == "bar":
                bar_width = max(4, int(12 * scale))
                for x_value, y_value in self._visible_points(item.points):
                    x = x_to_px(x_value)
                    y = y_to_px(y_value)
                    if x + bar_width / 2 < left or x - bar_width / 2 > right:
                        continue
                    zero_y = min(bottom, max(top, y_to_px(0)))
                    clipped_y = min(bottom, max(top, y))
                    draw.rectangle(
                        (
                            max(left, x - bar_width / 2),
                            min(clipped_y, zero_y),
                            min(right, x + bar_width / 2),
                            max(clipped_y, zero_y),
                        ),
                        fill=item.color,
                    )
                continue
            render_segments: list[list[tuple[float, float]]] = []
            for segment in self._visible_point_segments(item.points):
                if self._smooth_enabled() and len(segment) >= 5:
                    render_segments.append(self._savitzky_golay_points(segment))
                else:
                    render_segments.append(segment)
            for segment in render_segments:
                coords = [(x_to_px(x), y_to_px(y)) for x, y in segment]
                for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                    clipped = self._clip_line_to_rect(x1, y1, x2, y2, left, top, right, bottom)
                    if clipped is None:
                        continue
                    draw.line(clipped, fill=item.color, width=width)
            if self.show_points_var.get() or chart_type == "scatter":
                point_segments = render_segments if chart_type == "scatter" else self._visible_point_segments(item.points)
                for segment in point_segments:
                    for x_value, y_value in segment:
                        x = x_to_px(x_value)
                        y = y_to_px(y_value)
                        if x < left or x > right or y < top or y > bottom:
                            continue
                        draw.ellipse(
                            (
                                max(left, x - radius),
                                max(top, y - radius),
                                min(right, x + radius),
                                min(bottom, y + radius),
                            ),
                            fill=item.color,
                            outline=item.color,
                        )

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
        labels = [(value, item) for value, item in labels if item.name not in self._hidden_right_labels]
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
        main_x, main_y = self._export_title_position("main", width / 2, 22 * scale, scale)
        x_title_x, x_title_y = self._export_title_position("x", (left + right) / 2, bottom + 64 * scale, scale)
        y_title_x, y_title_y = self._export_title_position("y", max(30 * scale, left - 58 * scale), (top + bottom) / 2, scale)
        self._draw_export_centered_text(draw, main_x, main_y, title, title_font, fill="#222222")
        self._draw_export_centered_text(draw, x_title_x, x_title_y, self.x_title_var.get().strip() or x_name, axis_font, fill="#111111")
        self._draw_export_rotated_text(image, draw, y_title_x, y_title_y, self._locked_y_axis_title(), axis_font)

    def _export_title_position(self, key: str, default_x: float, default_y: float, scale: float) -> tuple[float, float]:
        position = self._title_positions.get(key)
        if position is None:
            return default_x, default_y
        x, y = position
        return float(x) * scale, float(y) * scale

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

    def _clamped_number_var(self, var: tk.Variable, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(round(float(var.get())))
        except (tk.TclError, ValueError, TypeError):
            value = default
        value = max(minimum, min(maximum, value))
        try:
            var.set(value)
        except tk.TclError:
            pass
        return value

    def _shade_color(self, color: str, percent: int) -> str:
        text = str(color).strip()
        if not text.startswith("#") or len(text) != 7:
            return text or "#000000"
        try:
            red = int(text[1:3], 16)
            green = int(text[3:5], 16)
            blue = int(text[5:7], 16)
        except ValueError:
            return "#000000"
        percent = max(0, min(200, int(percent)))
        if percent == 100:
            return f"#{red:02x}{green:02x}{blue:02x}"
        if percent < 100:
            factor = (percent / 100.0) ** 0.35 if percent > 0 else 0.0
            red = round(red * factor)
            green = round(green * factor)
            blue = round(blue * factor)
        else:
            factor = (percent - 100) / 100.0
            red = round(red + (255 - red) * factor)
            green = round(green + (255 - green) * factor)
            blue = round(blue + (255 - blue) * factor)
        return f"#{red:02x}{green:02x}{blue:02x}"

    def _series_display_color(self, name: str, fallback: str) -> str:
        base_color = self._series_colors.get(name, fallback)
        try:
            shade = int(float(self._series_shades.get(name, "100")))
        except (TypeError, ValueError):
            shade = 100
        return self._shade_color(base_color, shade)

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
                base_color = self._series_colors.get(y_name, self._series_color(index, len(y_names)))
                color = self._series_display_color(y_name, base_color)
                self._series_labels.setdefault(y_name, label)
                self._series_colors.setdefault(y_name, base_color)
                self._series_shades.setdefault(y_name, "100")
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

    def _visible_points(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if not self._hidden_time_ranges:
            return points
        return [(x_value, y_value) for x_value, y_value in points if not self._is_x_hidden(x_value)]

    def _visible_point_segments(self, points: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
        if not self._hidden_time_ranges:
            return [points] if points else []
        segments: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        for x_value, y_value in points:
            if self._is_x_hidden(x_value):
                if current:
                    segments.append(current)
                    current = []
                continue
            current.append((x_value, y_value))
        if current:
            segments.append(current)
        return segments

    def _visible_interval_segments(self, start: float, end: float, x_min: float, x_max: float) -> list[tuple[float, float]]:
        visible_start = max(min(start, end), x_min)
        visible_end = min(max(start, end), x_max)
        if visible_end <= visible_start:
            return []
        segments = [(visible_start, visible_end)]
        for break_start, break_end in self._active_axis_break_ranges(x_min, x_max):
            next_segments: list[tuple[float, float]] = []
            for segment_start, segment_end in segments:
                if break_end <= segment_start or break_start >= segment_end:
                    next_segments.append((segment_start, segment_end))
                    continue
                if segment_start < break_start:
                    next_segments.append((segment_start, break_start))
                if break_end < segment_end:
                    next_segments.append((break_end, segment_end))
            segments = next_segments
            if not segments:
                break
        return [(segment_start, segment_end) for segment_start, segment_end in segments if segment_end > segment_start]

    def _is_x_hidden(self, x_value: float) -> bool:
        return any(start <= x_value <= end for start, end in self._hidden_time_ranges)

    def _active_axis_break_ranges(self, x_min: float, x_max: float) -> list[tuple[float, float]]:
        if not self._hidden_time_ranges:
            return []
        active: list[tuple[float, float]] = []
        for start, end in self._hidden_time_ranges:
            visible_start = max(start, x_min)
            visible_end = min(end, x_max)
            if visible_end <= visible_start:
                continue
            active.append((visible_start, visible_end))
        return active

    def _axis_break_gap(self, x_min: float, x_max: float) -> float:
        span = abs(x_max - x_min)
        if math.isclose(span, 0.0):
            return 1.0
        return max(span * 0.012, span / 300.0)

    def _x_display_value(self, value: float, x_min: float, x_max: float) -> float:
        display_value = value
        gap = self._axis_break_gap(x_min, x_max)
        for start, end in self._active_axis_break_ranges(x_min, x_max):
            if value >= end:
                display_value -= max(0.0, (end - start) - gap)
            elif value > start:
                return display_value - (value - start) + gap * 0.5
        return display_value

    def _x_display_bounds(self, x_min: float, x_max: float) -> tuple[float, float]:
        display_min = self._x_display_value(x_min, x_min, x_max)
        display_max = self._x_display_value(x_max, x_min, x_max)
        if math.isclose(display_min, display_max):
            display_max = display_min + 1.0
        return display_min, display_max

    def _display_to_x_value(self, display_value: float, x_min: float, x_max: float) -> float:
        original = display_value
        gap = self._axis_break_gap(x_min, x_max)
        removed_before = 0.0
        for start, end in self._active_axis_break_ranges(x_min, x_max):
            break_display_start = start - removed_before
            break_display_end = break_display_start + gap
            removed = max(0.0, (end - start) - gap)
            if display_value < break_display_start:
                return original
            if display_value <= break_display_end:
                ratio = 0.0 if math.isclose(gap, 0.0) else (display_value - break_display_start) / gap
                return start + ratio * (end - start)
            original += removed
            removed_before += removed
        return original

    def _merge_hidden_time_ranges(self, ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
        ordered = sorted((min(start, end), max(start, end)) for start, end in ranges)
        merged: list[tuple[float, float]] = []
        for start, end in ordered:
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                previous_start, previous_end = merged[-1]
                merged[-1] = (previous_start, max(previous_end, end))
        return merged

    def _refresh_hidden_range_label(self) -> None:
        if not self._hidden_time_ranges:
            self.hidden_range_label_var.set("Break 0")
            return
        ranges = "; ".join(f"{self._format_tick(start)}-{self._format_tick(end)}" for start, end in self._hidden_time_ranges)
        self.hidden_range_label_var.set(f"Break {len(self._hidden_time_ranges)}: {ranges}")

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
            if self._is_x_hidden(value):
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

    def _draw_axis_break_marks(self, left: float, top: float, right: float, bottom: float, x_min: float, x_max: float) -> None:
        for start, end in self._active_axis_break_ranges(x_min, x_max):
            x1 = self._x_to_canvas(start, left, right, x_min, x_max)
            x2 = self._x_to_canvas(end, left, right, x_min, x_max)
            x = (x1 + x2) / 2
            if x < left - 20 or x > right + 20:
                continue
            for y in (top, bottom):
                self.canvas.create_rectangle(x - 13, y - 9, x + 13, y + 9, fill="#ffffff", outline="")
                self.canvas.create_line(x - 9, y + 7, x - 2, y - 7, fill="#222222", width=2)
                self.canvas.create_line(x + 2, y + 7, x + 9, y - 7, fill="#222222", width=2)

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
            for visible_start, visible_end in self._visible_interval_segments(start, end, x_min, x_max):
                x1 = self._x_to_canvas(visible_start, left, right, x_min, x_max)
                x2 = self._x_to_canvas(visible_end, left, right, x_min, x_max)
                if abs(x2 - x1) < 2:
                    continue
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
                self._draw_bar_series(self._visible_points(item.points), left, top, right, bottom, x_min, x_max, y_min, y_max, item.color)
                continue
            render_segments: list[list[tuple[float, float]]] = []
            for segment in self._visible_point_segments(item.points):
                if self._smooth_enabled() and len(segment) >= 5:
                    render_segments.append(self._savitzky_golay_points(segment))
                else:
                    render_segments.append(segment)
            for segment in render_segments:
                coords = [
                    (
                        self._x_to_canvas(x_value, left, right, x_min, x_max),
                        self._y_to_canvas(y_value, top, bottom, y_min, y_max),
                    )
                    for x_value, y_value in segment
                ]
                for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                    clipped = self._clip_line_to_rect(x1, y1, x2, y2, left, top, right, bottom)
                    if clipped is None:
                        continue
                    self.canvas.create_line(
                        *clipped,
                        fill=item.color,
                        width=self._series_line_width(item.name, line_width),
                        smooth=False,
                    )
            if self.show_points_var.get() or chart_type == "scatter":
                point_segments = render_segments if chart_type == "scatter" else self._visible_point_segments(item.points)
                for segment in point_segments:
                    for x_value, y_value in segment:
                        x = self._x_to_canvas(x_value, left, right, x_min, x_max)
                        y = self._y_to_canvas(y_value, top, bottom, y_min, y_max)
                        if x < left or x > right or y < top or y > bottom:
                            continue
                        self.canvas.create_oval(
                            max(left, x - point_size),
                            max(top, y - point_size),
                            min(right, x + point_size),
                            min(bottom, y + point_size),
                            fill=item.color,
                            outline="",
                        )

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
            if x + width / 2 < left or x - width / 2 > right:
                continue
            y = self._y_to_canvas(y_value, top, bottom, y_min, y_max)
            y = min(bottom, max(top, y))
            self.canvas.create_rectangle(
                max(left, x - width / 2),
                min(y, bottom),
                min(right, x + width / 2),
                max(y, bottom),
                fill=color,
                outline="",
            )

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
        title_x, title_y = self._title_positions.get("main", (width / 2, 22))
        title_tag = "drag_plot_title_main"
        title_id = self.canvas.create_text(
            title_x,
            title_y,
            text=title,
            font=("Segoe UI", 14, "bold"),
            fill="#222222",
            tags=(title_tag,),
        )
        self._register_draggable("plot_title", "main", title_id, tag=title_tag)
        if self._plot_rect is not None:
            left, top, right, bottom = self._plot_rect
            x_title_x, x_title_y = self._title_positions.get("x", ((left + right) / 2, bottom + 64))
            x_title_tag = "drag_plot_title_x"
            x_title_id = self.canvas.create_text(
                x_title_x,
                x_title_y,
                text=self.x_title_var.get().strip() or x_name,
                font=("Segoe UI", 13, "bold"),
                fill="#111111",
                tags=(x_title_tag,),
            )
            self._register_draggable("plot_title", "x", x_title_id, tag=x_title_tag)
            y_title_x, y_title_y = self._title_positions.get("y", (max(30, left - 58), (top + bottom) / 2))
            y_title_tag = "drag_plot_title_y"
            y_title_id = self.canvas.create_text(
                y_title_x,
                y_title_y,
                text=self._locked_y_axis_title(),
                angle=90,
                font=("Segoe UI", 13, "bold"),
                fill="#111111",
                tags=(y_title_tag,),
            )
            self._register_draggable("plot_title", "y", y_title_id, tag=y_title_tag)

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
            if item.name in self._hidden_right_labels:
                continue
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
            elif target.get("kind") == "plot_title":
                self._title_positions.setdefault(str(target.get("key", "")), (current_x, current_y))
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
        if target.get("kind") == "plot_title":
            key = str(target.get("key", ""))
            if key in self._title_positions:
                return self._title_positions[key]
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
        elif kind == "plot_title":
            x, y = self._title_positions.get(str(key), self._draggable_position(self._drag_target))
            self._title_positions[str(key)] = (x + dx, y + dy)

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
        elif kind == "plot_title":
            self._title_positions[str(key)] = (float(x), float(y))
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
        ys = [y for item in self._series for _x, y in self._visible_points(item.points)]
        if not ys:
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
        display_min, display_max = self._x_display_bounds(x_min, x_max)
        display_span = display_max - display_min
        if math.isclose(display_span, 0.0):
            return (left + right) / 2
        display_value = self._x_display_value(value, x_min, x_max)
        return left + (display_value - display_min) * (right - left) / display_span

    def _y_to_canvas(self, value: float, top: float, bottom: float, y_min: float, y_max: float) -> float:
        span = y_max - y_min
        if math.isclose(span, 0.0):
            return (top + bottom) / 2
        return bottom - (value - y_min) * (bottom - top) / span

    def _clip_line_to_rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        left: float,
        top: float,
        right: float,
        bottom: float,
    ) -> tuple[float, float, float, float] | None:
        inside, left_code, right_code, top_code, bottom_code = 0, 1, 2, 4, 8

        def out_code(x: float, y: float) -> int:
            code = inside
            if x < left:
                code |= left_code
            elif x > right:
                code |= right_code
            if y < top:
                code |= top_code
            elif y > bottom:
                code |= bottom_code
            return code

        code1 = out_code(x1, y1)
        code2 = out_code(x2, y2)
        while True:
            if not (code1 | code2):
                return x1, y1, x2, y2
            if code1 & code2:
                return None
            code_out = code1 or code2
            if code_out & top_code:
                if math.isclose(y2, y1):
                    return None
                x = x1 + (x2 - x1) * (top - y1) / (y2 - y1)
                y = top
            elif code_out & bottom_code:
                if math.isclose(y2, y1):
                    return None
                x = x1 + (x2 - x1) * (bottom - y1) / (y2 - y1)
                y = bottom
            elif code_out & right_code:
                if math.isclose(x2, x1):
                    return None
                y = y1 + (y2 - y1) * (right - x1) / (x2 - x1)
                x = right
            else:
                if math.isclose(x2, x1):
                    return None
                y = y1 + (y2 - y1) * (left - x1) / (x2 - x1)
                x = left
            if code_out == code1:
                x1, y1 = x, y
                code1 = out_code(x1, y1)
            else:
                x2, y2 = x, y
                code2 = out_code(x2, y2)

    def _canvas_to_x(self, px: float, left: float, right: float, x_min: float, x_max: float) -> float:
        span = right - left
        if math.isclose(span, 0.0):
            return x_min
        display_min, display_max = self._x_display_bounds(x_min, x_max)
        display_value = display_min + (px - left) * (display_max - display_min) / span
        return self._display_to_x_value(display_value, x_min, x_max)

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
