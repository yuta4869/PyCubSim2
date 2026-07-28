from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk
from typing import Any


class PrimitiveDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("Add object")
        self.resizable(False, False)
        self.transient(parent)
        self.result: dict[str, Any] | None = None
        self.color = (0.88, 0.16, 0.12, 1.0)
        self.name_var = tk.StringVar(value="Object")
        self.shape_var = tk.StringVar(value="box")
        self.size_vars = [
            tk.StringVar(value="0.14"),
            tk.StringVar(value="0.14"),
            tk.StringVar(value="0.14"),
        ]
        self.mass_var = tk.StringVar(value="0.25")
        self.fixed_var = tk.BooleanVar(value=False)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.wait_visibility()
        self.focus_force()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text="Name").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.name_var, width=24).grid(
            row=0, column=1, columnspan=3, sticky="ew", pady=4
        )
        ttk.Label(frame, text="Shape").grid(row=1, column=0, sticky="w", pady=4)
        shape = ttk.Combobox(
            frame,
            textvariable=self.shape_var,
            values=("box", "sphere", "cylinder"),
            state="readonly",
            width=16,
        )
        shape.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        shape.bind("<<ComboboxSelected>>", self._shape_changed)

        for column, label in enumerate(("Size X", "Size Y", "Size Z")):
            ttk.Label(frame, text=label).grid(
                row=2, column=column + 1, sticky="w", pady=(8, 2)
            )
            ttk.Entry(
                frame, textvariable=self.size_vars[column], width=8
            ).grid(row=3, column=column + 1, sticky="ew", padx=(0, 5))
        ttk.Label(frame, text="Geometry").grid(row=3, column=0, sticky="w")

        ttk.Label(frame, text="Mass kg").grid(row=4, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.mass_var, width=10).grid(
            row=4, column=1, sticky="w", pady=8
        )
        ttk.Checkbutton(frame, text="Fixed base", variable=self.fixed_var).grid(
            row=4, column=2, columnspan=2, sticky="w", pady=8
        )

        ttk.Label(frame, text="Color").grid(row=5, column=0, sticky="w", pady=4)
        self.color_button = tk.Button(
            frame,
            text="",
            width=10,
            height=1,
            borderwidth=1,
            background="#e0281f",
            command=self._choose_color,
        )
        self.color_button.grid(row=5, column=1, sticky="w", pady=4)

        actions = ttk.Frame(frame)
        actions.grid(row=6, column=0, columnspan=4, sticky="e", pady=(14, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).grid(
            row=0, column=0, padx=4
        )
        ttk.Button(actions, text="Add", command=self._accept).grid(
            row=0, column=1
        )

    def _shape_changed(self, _event: tk.Event) -> None:
        defaults = {
            "box": ("0.14", "0.14", "0.14"),
            "sphere": ("0.14", "0.14", "0.14"),
            "cylinder": ("0.14", "0.14", "0.20"),
        }[self.shape_var.get()]
        for variable, value in zip(self.size_vars, defaults):
            variable.set(value)

    def _choose_color(self) -> None:
        initial = "#%02x%02x%02x" % tuple(
            round(value * 255) for value in self.color[:3]
        )
        rgb, hex_value = colorchooser.askcolor(initialcolor=initial, parent=self)
        if rgb is None or hex_value is None:
            return
        self.color = tuple(value / 255.0 for value in rgb) + (1.0,)
        self.color_button.configure(background=hex_value)

    def _accept(self) -> None:
        try:
            size = tuple(float(variable.get()) for variable in self.size_vars)
            mass = float(self.mass_var.get())
            if any(value <= 0 for value in size):
                raise ValueError("Sizes must be greater than zero.")
            if mass < 0:
                raise ValueError("Mass cannot be negative.")
        except ValueError as exc:
            messagebox.showerror("Invalid object", str(exc), parent=self)
            return
        self.result = {
            "name": self.name_var.get().strip() or "Object",
            "shape": self.shape_var.get(),
            "size": size,
            "mass": mass,
            "color": self.color,
            "fixed_base": self.fixed_var.get(),
        }
        self.destroy()


class ModelImportDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, model_path: str | Path) -> None:
        super().__init__(parent)
        self.model_path = Path(model_path)
        self.title("Import model")
        self.resizable(False, False)
        self.transient(parent)
        self.result: dict[str, Any] | None = None
        self.name_var = tk.StringVar(value=self.model_path.stem)
        self.scale_var = tk.StringVar(value="1.0")
        self.mass_var = tk.StringVar(value="1.0")
        self.fixed_var = tk.BooleanVar(value=True)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.wait_visibility()
        self.focus_force()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text="File").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(
            frame,
            text=self.model_path.name,
            foreground="#4f5e58",
            width=30,
        ).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(frame, text="Name").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(
            row=1, column=1, sticky="ew", pady=4
        )
        ttk.Label(frame, text="Scale").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.scale_var, width=12).grid(
            row=2, column=1, sticky="w", pady=4
        )
        ttk.Label(frame, text="Mass kg").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.mass_var, width=12).grid(
            row=3, column=1, sticky="w", pady=4
        )
        ttk.Checkbutton(frame, text="Fixed base", variable=self.fixed_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=6
        )
        actions = ttk.Frame(frame)
        actions.grid(row=5, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).grid(
            row=0, column=0, padx=4
        )
        ttk.Button(actions, text="Import", command=self._accept).grid(
            row=0, column=1
        )

    def _accept(self) -> None:
        try:
            scale = float(self.scale_var.get())
            mass = float(self.mass_var.get())
            if scale <= 0:
                raise ValueError("Scale must be greater than zero.")
            if mass < 0:
                raise ValueError("Mass cannot be negative.")
        except ValueError as exc:
            messagebox.showerror("Invalid model options", str(exc), parent=self)
            return
        self.result = {
            "name": self.name_var.get().strip() or self.model_path.stem,
            "scale": scale,
            "mass": mass,
            "fixed_base": self.fixed_var.get(),
        }
        self.destroy()

