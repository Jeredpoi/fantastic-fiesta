from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from .dxf_writer import save_dxf
from .geometry import LayoutResult, generate_laser_layout


class BoxForgeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Laser Cutter Box Maker")
        self.geometry("1100x700")
        self.configure(bg="#c0bcd8")
        self.minsize(980, 620)

        self._after_id: str | None = None
        self._last_layout: LayoutResult | None = None

        self.thickness_var = tk.StringVar(value="4")
        self.width_var = tk.StringVar(value="200")
        self.height_var = tk.StringVar(value="200")
        self.depth_var = tk.StringVar(value="50")
        self.notch_var = tk.IntVar(value=23)
        self.box_type_var = tk.StringVar(value="open")
        self.dividers_var = tk.BooleanVar(value=False)
        self.divider_count_var = tk.StringVar(value="2")
        self.sloped_var = tk.BooleanVar(value=False)
        self.slope_values_var = tk.StringVar(value="40 0")
        self.output_dir_var = tk.StringVar(value=self._default_output_dir())
        self.status_var = tk.StringVar(value="Меняй параметры слева: справа сразу видно раскрой.")

        self._build_ui()
        self._bind_live_updates()
        self.after(150, self._redraw)

    def _default_output_dir(self) -> str:
        desktop = Path.home() / "Desktop"
        return str(desktop if desktop.exists() else Path.cwd())

    def _build_ui(self) -> None:
        left = tk.Frame(
            self,
            bg="#b0acd0",
            bd=2,
            relief="groove",
            padx=10,
            pady=10,
        )
        left.pack(side="left", fill="y", padx=8, pady=8)

        tk.Label(
            left,
            text="Лазерный резак",
            bg="#b0acd0",
            font=("Arial", 12, "bold"),
        ).grid(row=0, column=0, columnspan=3, pady=(0, 8), sticky="w")

        self._entry_row(left, 1, "Толщина листа", self.thickness_var)
        self._entry_row(left, 2, "X (ширина)", self.width_var)
        self._entry_row(left, 3, "Y (высота)", self.height_var)
        self._entry_row(left, 4, "Z (глубина)", self.depth_var)

        tk.Label(
            left,
            text="все размеры в мм (внешние)",
            bg="#b0acd0",
            font=("Arial", 7),
            fg="#555",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.notch_lbl = tk.Label(left, text="шаг зубчика = 23", bg="#b0acd0")
        self.notch_lbl.grid(row=6, column=0, columnspan=3, sticky="w")
        tk.Scale(
            left,
            from_=5,
            to=90,
            orient="horizontal",
            variable=self.notch_var,
            showvalue=False,
            bg="#b0acd0",
            highlightthickness=0,
            length=190,
            command=self._on_notch_change,
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 8))

        type_box = tk.Frame(left, bg="#c8c4e8", bd=1, relief="solid", padx=4, pady=4)
        type_box.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        type_opts = [
            ("Открытая коробка", "open", "normal"),
            ("Закрытая коробка", "closed", "normal"),
            ("Рамка", "frame", "normal"),
        ]
        for text, value, state in type_opts:
            tk.Radiobutton(
                type_box,
                text=text,
                variable=self.box_type_var,
                value=value,
                state=state,
                bg="#c8c4e8",
                activebackground="#c8c4e8",
                command=self._schedule_redraw,
            ).pack(anchor="w")

        divider_row = tk.Frame(left, bg="#b0acd0")
        divider_row.grid(row=9, column=0, columnspan=3, sticky="w")
        tk.Checkbutton(
            divider_row,
            text="Перегородки",
            variable=self.dividers_var,
            bg="#b0acd0",
            activebackground="#b0acd0",
            command=self._schedule_redraw,
        ).pack(side=tk.LEFT)
        tk.Entry(divider_row, textvariable=self.divider_count_var, width=4).pack(side=tk.LEFT, padx=(6, 0))

        sloped_row = tk.Frame(left, bg="#b0acd0")
        sloped_row.grid(row=10, column=0, columnspan=3, sticky="w", pady=(2, 2))
        tk.Checkbutton(
            sloped_row,
            text="Наклонная",
            variable=self.sloped_var,
            bg="#b0acd0",
            activebackground="#b0acd0",
            command=self._schedule_redraw,
        ).pack(side=tk.LEFT)
        tk.Entry(sloped_row, textvariable=self.slope_values_var, width=8).pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(left, text="Папка экспорта", bg="#b0acd0").grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(8, 2)
        )
        tk.Entry(left, textvariable=self.output_dir_var, width=28).grid(
            row=12, column=0, columnspan=2, sticky="we"
        )
        tk.Button(left, text="...", width=4, command=self._choose_output_dir).grid(
            row=12, column=2, padx=(4, 0)
        )

        btn_style = dict(
            width=18,
            relief="raised",
            bg="#e0ddf5",
            activebackground="#ccc8f0",
            font=("Arial", 10),
        )
        tk.Button(left, text="Перерисовать", command=self._redraw, **btn_style).grid(
            row=13, column=0, columnspan=3, pady=(10, 4)
        )
        tk.Button(left, text="Сохранить DXF", command=self._save_dxf, **btn_style).grid(
            row=14, column=0, columnspan=3, pady=4
        )
        tk.Button(left, text="Открыть папку", command=self._open_output_dir, **btn_style).grid(
            row=15, column=0, columnspan=3, pady=4
        )

        tk.Label(
            left,
            textvariable=self.status_var,
            bg="#b0acd0",
            fg="#303f9f",
            justify=tk.LEFT,
            anchor="w",
            wraplength=260,
        ).grid(row=16, column=0, columnspan=3, sticky="we", pady=(8, 4))

        right = tk.Frame(self, bg="#d9d4b0", bd=2, relief="groove")
        right.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(right, bg="#d9d4b0", cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._schedule_redraw)

    def _entry_row(self, parent: tk.Widget, row: int, label: str, var: tk.StringVar) -> None:
        tk.Label(parent, text=label, bg="#b0acd0").grid(row=row, column=0, sticky="w", pady=2)
        tk.Entry(parent, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=(6, 0))

    def _bind_live_updates(self) -> None:
        for var in (
            self.thickness_var,
            self.width_var,
            self.height_var,
            self.depth_var,
            self.divider_count_var,
            self.slope_values_var,
        ):
            var.trace_add("write", self._schedule_redraw)

    def _on_notch_change(self, value: str) -> None:
        self.notch_lbl.config(text=f"шаг зубчика = {value}")
        self._schedule_redraw()

    def _schedule_redraw(self, *_args: object) -> None:
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(220, self._redraw)

    def _choose_output_dir(self) -> None:
        chosen = filedialog.askdirectory(
            title="Папка для экспорта DXF",
            initialdir=self.output_dir_var.get() or self._default_output_dir(),
        )
        if chosen:
            self.output_dir_var.set(chosen)

    def _open_output_dir(self) -> None:
        folder = Path(self.output_dir_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _parse_positive_float(self, raw: str, field_name: str) -> float:
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError as error:
            raise ValueError(f"Поле '{field_name}' должно быть числом.") from error
        if value <= 0:
            raise ValueError(f"Поле '{field_name}' должно быть больше 0.")
        return value

    def _read_params(
        self, show_error: bool
    ) -> tuple[float, float, float, float, int, str, bool, int, bool, float] | None:
        try:
            thickness = self._parse_positive_float(self.thickness_var.get(), "Толщина")
            x_size = self._parse_positive_float(self.width_var.get(), "X")
            y_size = self._parse_positive_float(self.height_var.get(), "Y")
            z_size = self._parse_positive_float(self.depth_var.get(), "Z")
            notch = int(self.notch_var.get())
            if notch <= 0:
                raise ValueError("Шаг зубчика должен быть больше 0.")
            if notch < thickness * 1.5:
                raise ValueError("Шаг зубчика должен быть не меньше 1.5 * толщины.")
            box_type = self.box_type_var.get()
            show_dividers = self.dividers_var.get()
            sloped = self.sloped_var.get()
            slope_value = 0.0
            if sloped:
                parts = self.slope_values_var.get().strip().replace(",", ".").split()
                if len(parts) == 0:
                    raise ValueError("Поле 'Наклонная' должно содержать число, например: 40 0")
                slope_value = float(parts[0])
                if slope_value < 0:
                    raise ValueError("Наклон должен быть >= 0.")
            divider_count = 0
            if show_dividers:
                divider_count = int(self.divider_count_var.get().strip())
                if divider_count <= 0:
                    raise ValueError("Количество перегородок должно быть больше 0.")
                if divider_count > 20:
                    raise ValueError("Слишком много перегородок (максимум 20).")
            return (
                x_size,
                y_size,
                z_size,
                thickness,
                notch,
                box_type,
                show_dividers,
                divider_count,
                sloped,
                slope_value,
            )
        except ValueError as error:
            if show_error:
                messagebox.showerror("Ошибка параметров", str(error))
            return None

    def _build_layout(self, show_error: bool) -> LayoutResult | None:
        params = self._read_params(show_error=show_error)
        if params is None:
            return None
        x_size, y_size, z_size, thickness, notch, box_type, show_dividers, divider_count, sloped, slope_value = params
        try:
            return generate_laser_layout(
                width_x=x_size,
                # Match Jerome input semantics:
                # X = width, Y = wall height, Z = box depth(length).
                length_y=z_size,
                height_z=y_size,
                thickness=thickness,
                notch=float(notch),
                box_type=box_type,
                show_dividers=show_dividers,
                divider_count=divider_count,
                sloped=sloped,
                slope=slope_value,
            )
        except ValueError as error:
            if show_error:
                messagebox.showerror("Ошибка генерации", str(error))
            return None

    def _redraw(self, *_args: object) -> None:
        self._after_id = None
        layout = self._build_layout(show_error=False)
        self.canvas.delete("all")

        if layout is None:
            self.canvas.create_text(
                max(100, self.canvas.winfo_width() / 2),
                max(80, self.canvas.winfo_height() / 2),
                text="Введите корректные параметры.",
                fill="#c62828",
                font=("Arial", 14, "bold"),
            )
            self.status_var.set("Ошибка параметров: проверь значения слева.")
            self._last_layout = None
            return

        self._last_layout = layout
        self._draw_layout(layout)
        self.status_var.set(
            f"Лист: {layout.total_width:.1f} x {layout.total_height:.1f} мм | "
            f"Панелей: {len(layout.panels)}"
        )

    def _draw_layout(self, layout: LayoutResult) -> None:
        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 40 or ch < 40:
            return

        pad = 8.0
        scale = min((cw - 2 * pad) / layout.total_width, (ch - 2 * pad) / layout.total_height, 6.0)
        ox = (cw - layout.total_width * scale) / 2.0
        oy = (ch - layout.total_height * scale) / 2.0

        def sx(v: float) -> float:
            return ox + v * scale

        def sy(v: float) -> float:
            return oy + v * scale

        self.canvas.create_rectangle(0, 0, cw, ch, fill="#d9d4b0", outline="")

        for seg in layout.segments:
            color = "#000000"
            self.canvas.create_line(
                sx(seg.x1),
                sy(seg.y1),
                sx(seg.x2),
                sy(seg.y2),
                fill=color,
                width=1.0,
            )

        self.canvas.create_text(
            sx(2),
            sy(2),
            text=f"{layout.total_width:.0f} x {layout.total_height:.0f} мм",
            anchor="nw",
            fill="#455a64",
            font=("Arial", 9, "bold"),
        )

        for panel in layout.panels:
            cx = sx(panel.x + panel.width / 2.0)
            cy = sy(panel.y + panel.height / 2.0)
            self.canvas.create_text(
                cx,
                cy,
                text=panel.name,
                fill="#5d6472",
                font=("Arial", 9),
            )

    def _save_dxf(self) -> None:
        layout = self._build_layout(show_error=True)
        if layout is None:
            return

        output_dir = Path(self.output_dir_var.get()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"laser_box_{self.box_type_var.get()}_{stamp}.dxf"
        target = filedialog.asksaveasfilename(
            defaultextension=".dxf",
            initialdir=str(output_dir),
            initialfile=name,
            filetypes=[("DXF файл", "*.dxf"), ("Все файлы", "*.*")],
            title="Сохранить DXF",
        )
        if not target:
            return

        save_dxf(Path(target), layout.segments)
        self.status_var.set(f"DXF сохранен: {target}")
        messagebox.showinfo(
            "Готово",
            f"DXF сохранен:\n{target}\n\nРазмер листа: {layout.total_width:.0f} x {layout.total_height:.0f} мм",
        )


def main() -> int:
    app = BoxForgeApp()
    app.mainloop()
    return 0
