from __future__ import annotations

import copy
import json
import math
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any

import numpy as np
from PIL import Image, ImageTk

from .actions import BUILTIN_BEHAVIORS, MANUAL_JOINT_NAMES
from .config import EntitySpec, SceneConfig, Transform
from .dialogs import ModelImportDialog, PrimitiveDialog
from .layout_editor import SceneMapEditor
from .platform_ui import configure_application_icon
from .sensors import WebcamCapture
from .simulation import PROJECT_ROOT, PyCubSim2Simulation


SCENE_DIR = PROJECT_ROOT / "layouts"
ACTION_DIR = PROJECT_ROOT / "actions"
ARTIFACT_DIR = (
    Path.home() / "Documents" / "PyCubSim2"
    if getattr(sys, "frozen", False)
    else PROJECT_ROOT / "artifacts"
)


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(
            self, background="#f7f8f6", highlightthickness=0
        )
        self.scrollbar = ttk.Scrollbar(
            self, orient=tk.VERTICAL, command=self.canvas.yview
        )
        self.interior = ttk.Frame(self.canvas)
        self.window_item = self.canvas.create_window(
            (0, 0), window=self.interior, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.interior.bind("<Configure>", self._interior_configured)
        self.canvas.bind("<Configure>", self._canvas_configured)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.interior.bind("<MouseWheel>", self._wheel)

    def _interior_configured(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_configured(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_item, width=event.width)

    def _wheel(self, event: tk.Event) -> str:
        direction = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(direction * 3, "units")
        return "break"


class PyCubSim2App:
    def __init__(
        self,
        root: tk.Tk,
        simulation: PyCubSim2Simulation | None = None,
    ) -> None:
        self.root = root
        self.simulation = simulation or PyCubSim2Simulation()
        self._owns_simulation = simulation is None
        self.webcam = WebcamCapture()
        self.running = True
        self.current_scene_path: Path | None = None
        self.selected_entity_id: str | None = None
        self.sensor_source_key = "pycub_1:left_eye"
        self.secondary_source_key = "pycub_1:right_eye"
        self.sensor_source_map: dict[str, str] = {}
        self.secondary_source_map: dict[str, str] = {}
        self.photo: ImageTk.PhotoImage | None = None
        self.photos: dict[str, ImageTk.PhotoImage] = {}
        self._tick_after_id: str | None = None
        self._camera_fit_after_id: str | None = None
        self._camera_drag_last: tuple[int, int] | None = None
        self._camera_drag_mode = "orbit"
        self._cursor_drag_entity_id: str | None = None
        self._cursor_drag_plane_z = 0.0
        self._cursor_drag_offset = (0.0, 0.0)
        self._cursor_drag_changed = False
        self._cursor_drag_auto_center = True
        self._pending_edit_before: SceneConfig | None = None
        self._undo_stack: list[SceneConfig] = []
        self._redo_stack: list[SceneConfig] = []
        self._last_render_s = 0.0
        self._last_telemetry_s = 0.0
        self._last_tick_s = time.perf_counter()
        self._physics_accumulator_s = 0.0
        self._render_dirty = True
        self._manual_syncing = False
        self._property_color = (0.8, 0.2, 0.15, 1.0)

        self.status_var = tk.StringVar(value="Ready")
        self.time_var = tk.StringVar(value="0.00 s")
        self.run_button_var = tk.StringVar(value="Pause")
        self.view_var = tk.StringVar(value="World")
        self.secondary_view_var = tk.StringVar(value="Sensor RGB")
        self.split_view_var = tk.BooleanVar(value=False)
        self.cursor_mode_var = tk.StringVar(value="Camera")
        self.shadow_var = tk.BooleanVar(value=False)
        self.quality_var = tk.StringVar(value="Performance")
        self.selection_label_var = tk.StringVar(value="No entity selected")
        self.entity_type_var = tk.StringVar(value="")
        self.behavior_var = tk.StringVar(value="Manual pose")
        self.behavior_speed_var = tk.DoubleVar(value=1.0)
        self.behavior_intensity_var = tk.DoubleVar(value=0.55)
        self.action_file_var = tk.StringVar(value="No action loaded")
        self.controller_status_var = tk.StringVar(value="No external controller")
        self.left_grip_var = tk.DoubleVar(value=0.0)
        self.right_grip_var = tk.DoubleVar(value=0.0)
        self.ik_side_var = tk.StringVar(value="Right")
        self.ik_vars = {
            "x": tk.StringVar(value="-0.36"),
            "y": tk.StringVar(value="-0.20"),
            "z": tk.StringVar(value="0.63"),
        }
        self.property_vars = {
            key: tk.StringVar()
            for key in (
                "name",
                "x",
                "y",
                "z",
                "roll",
                "pitch",
                "yaw",
                "scale",
                "mass",
                "size_x",
                "size_y",
                "size_z",
            )
        }
        self.property_fixed_var = tk.BooleanVar(value=True)
        self.sensor_source_var = tk.StringVar()
        self.secondary_source_var = tk.StringVar()
        self.sensor_vars = {
            "rgb": tk.BooleanVar(value=True),
            "depth": tk.BooleanVar(value=True),
            "segmentation": tk.BooleanVar(value=False),
            "joints": tk.BooleanVar(value=True),
            "imu": tk.BooleanVar(value=True),
            "contact": tk.BooleanVar(value=True),
            "lidar": tk.BooleanVar(value=False),
        }
        self.camera_vars = {
            "yaw": tk.DoubleVar(value=self.simulation.camera_yaw),
            "pitch": tk.DoubleVar(value=self.simulation.camera_pitch),
            "distance": tk.DoubleVar(value=self.simulation.camera_distance),
        }
        self.manual_vars: dict[str, tk.DoubleVar] = {}
        self.property_inputs: dict[str, ttk.Entry] = {}

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self._refresh_entity_tree(select_id="pycub_1")
        self._refresh_camera_sources()
        self._sync_camera_vars()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._tick_after_id = self.root.after(80, self._tick)

    def _configure_window(self) -> None:
        self.root.title("PyCubSim2")
        (
            self._application_icon,
            self._macos_dock_icon_configured,
        ) = configure_application_icon(self.root)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(1600, max(1180, screen_width - 60))
        height = min(960, max(760, screen_height - 90))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2 - 10)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(1120, 720)
        self.root.configure(background="#e4e9e6")

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("TkDefaultFont", 11))
        style.configure("TFrame", background="#f7f8f6")
        style.configure("Header.TFrame", background="#1f2926")
        style.configure(
            "Header.TLabel",
            background="#1f2926",
            foreground="#ffffff",
            font=("TkDefaultFont", 16, "bold"),
        )
        style.configure(
            "HeaderSub.TLabel",
            background="#1f2926",
            foreground="#bec8c3",
            font=("TkDefaultFont", 10),
        )
        style.configure("Header.TButton", padding=(10, 7))
        style.configure("Primary.TButton", padding=(10, 7))
        style.configure("Status.TLabel", background="#dce3df", foreground="#33413c")
        style.configure("TLabelframe", background="#f7f8f6", padding=7)
        style.configure(
            "TLabelframe.Label",
            background="#f7f8f6",
            foreground="#26332f",
            font=("TkDefaultFont", 11, "bold"),
        )
        style.configure("Treeview", rowheight=24)

    def _build_ui(self) -> None:
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self._build_header()
        content = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            sashwidth=5,
            sashrelief=tk.FLAT,
            background="#c4ccc7",
            borderwidth=0,
        )
        content.grid(row=1, column=0, sticky="nsew")
        viewer = ttk.Frame(content)
        sidebar = ttk.Frame(content, width=480)
        content.add(viewer, minsize=650, stretch="always")
        content.add(sidebar, minsize=430, width=480, stretch="never")
        self._build_viewer(viewer)
        self._build_sidebar(sidebar)
        ttk.Label(
            self.root,
            textvariable=self.status_var,
            style="Status.TLabel",
            anchor="w",
            padding=(12, 6),
        ).grid(row=2, column=0, sticky="ew")

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(14, 9))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        title = ttk.Frame(header, style="Header.TFrame")
        title.grid(row=0, column=0, sticky="w")
        ttk.Label(title, text="PyCubSim2", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            title,
            text="extensible robot simulation",
            style="HeaderSub.TLabel",
        ).grid(row=1, column=0, sticky="w")

        simulation_controls = ttk.Frame(header, style="Header.TFrame")
        simulation_controls.grid(row=0, column=1, rowspan=2)
        ttk.Button(
            simulation_controls,
            textvariable=self.run_button_var,
            command=self._toggle_running,
            style="Header.TButton",
        ).grid(row=0, column=0, padx=3)
        ttk.Button(
            simulation_controls,
            text="Step",
            command=self._single_step,
            style="Header.TButton",
        ).grid(row=0, column=1, padx=3)
        ttk.Label(
            simulation_controls,
            textvariable=self.time_var,
            style="HeaderSub.TLabel",
            width=11,
            anchor="center",
        ).grid(row=0, column=2, padx=(8, 0))

        commands = ttk.Frame(header, style="Header.TFrame")
        commands.grid(row=0, column=2, rowspan=2, sticky="e")
        self.undo_button = ttk.Button(
            commands,
            text="Undo",
            command=self.undo,
            style="Header.TButton",
            state=tk.DISABLED,
        )
        self.undo_button.grid(row=0, column=0, padx=3)
        self.redo_button = ttk.Button(
            commands,
            text="Redo",
            command=self.redo,
            style="Header.TButton",
            state=tk.DISABLED,
        )
        self.redo_button.grid(row=0, column=1, padx=3)
        for column, (label, command) in enumerate(
            (
                ("Open", self.open_scene),
                ("Save", self.save_scene),
                ("Reset", self.reset_scene),
            ),
            start=2,
        ):
            ttk.Button(
                commands,
                text=label,
                command=command,
                style="Header.TButton",
            ).grid(row=0, column=column, padx=3)

    def _build_viewer(self, parent: ttk.Frame) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        toolbar = ttk.Frame(parent, padding=(8, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_columnconfigure(6, weight=1)
        for column, view in enumerate(
            ("World", "Top", "Side", "Sensor RGB", "Sensor Depth", "Segmentation")
        ):
            tk.Radiobutton(
                toolbar,
                text=view,
                value=view,
                variable=self.view_var,
                command=self._view_changed,
                indicatoron=False,
                borderwidth=0,
                relief=tk.FLAT,
                overrelief=tk.FLAT,
                background="#34423d",
                foreground="#ffffff",
                activebackground="#4b5a54",
                activeforeground="#ffffff",
                selectcolor="#13795b",
                padx=8,
                pady=6,
            ).grid(row=0, column=column, padx=2)
        self.viewer_source_combo = ttk.Combobox(
            toolbar,
            textvariable=self.sensor_source_var,
            state="readonly",
            width=24,
        )
        self.viewer_source_combo.grid(
            row=0, column=6, sticky="e", padx=(8, 3)
        )
        self.viewer_source_combo.bind(
            "<<ComboboxSelected>>", self._sensor_source_changed
        )

        cursor_controls = ttk.Frame(toolbar)
        cursor_controls.grid(
            row=1, column=0, columnspan=7, sticky="ew", pady=(6, 0)
        )
        cursor_controls.grid_columnconfigure(5, weight=1)
        ttk.Label(cursor_controls, text="Cursor").grid(
            row=0, column=0, sticky="w", padx=(2, 5)
        )
        for column, mode in enumerate(("Camera", "Select", "Move"), start=1):
            tk.Radiobutton(
                cursor_controls,
                text=mode,
                value=mode,
                variable=self.cursor_mode_var,
                command=self._cursor_mode_changed,
                indicatoron=False,
                borderwidth=1,
                relief=tk.FLAT,
                overrelief=tk.FLAT,
                background="#e2e7e4",
                foreground="#26332f",
                activebackground="#cbd8d2",
                selectcolor="#9fd0bf",
                padx=9,
                pady=4,
            ).grid(row=0, column=column, padx=1)
        ttk.Checkbutton(
            cursor_controls,
            text="Dual view",
            variable=self.split_view_var,
            command=self._split_view_changed,
        ).grid(row=0, column=4, padx=(10, 5))
        context_controls = ttk.Frame(cursor_controls)
        context_controls.grid(row=0, column=5, sticky="e")
        ttk.Label(
            context_controls,
            textvariable=self.selection_label_var,
            foreground="#44514c",
        ).grid(row=0, column=0, padx=(3, 8))
        for column, (label, tab_name) in enumerate(
            (("Info", "scene"), ("Actions", "actions"), ("Sensors", "sensors")),
            start=1,
        ):
            ttk.Button(
                context_controls,
                text=label,
                command=lambda name=tab_name: self._show_sidebar_tab(name),
            ).grid(row=0, column=column, padx=2)

        self.secondary_controls = ttk.Frame(toolbar)
        self.secondary_controls.grid(
            row=2, column=0, columnspan=7, sticky="ew", pady=(6, 0)
        )
        self.secondary_controls.grid_columnconfigure(1, weight=1)
        ttk.Label(self.secondary_controls, text="Second view").grid(
            row=0, column=0, sticky="w", padx=(2, 6)
        )
        self.secondary_source_combo = ttk.Combobox(
            self.secondary_controls,
            textvariable=self.secondary_source_var,
            state="readonly",
        )
        self.secondary_source_combo.grid(
            row=0, column=1, sticky="ew", padx=(0, 6)
        )
        self.secondary_source_combo.bind(
            "<<ComboboxSelected>>", self._secondary_source_changed
        )
        self.secondary_view_combo = ttk.Combobox(
            self.secondary_controls,
            textvariable=self.secondary_view_var,
            values=(
                "World",
                "Top",
                "Side",
                "Sensor RGB",
                "Sensor Depth",
                "Segmentation",
            ),
            state="readonly",
            width=17,
        )
        self.secondary_view_combo.grid(row=0, column=2, sticky="e")
        self.secondary_view_combo.bind(
            "<<ComboboxSelected>>", self._secondary_view_changed
        )
        self.secondary_controls.grid_remove()

        self.viewer_canvas_frame = ttk.Frame(parent)
        self.viewer_canvas_frame.grid(row=1, column=0, sticky="nsew")
        self.viewer_canvas_frame.grid_rowconfigure(0, weight=1)
        self.viewer_canvas_frame.grid_columnconfigure(0, weight=1)
        self.viewer_canvas_frame.grid_columnconfigure(1, weight=0)
        self.image_canvas = tk.Canvas(
            self.viewer_canvas_frame,
            background="#cbd2ce",
            highlightthickness=0,
            cursor="fleur",
        )
        self.image_canvas.grid(row=0, column=0, sticky="nsew")
        self.image_item = self.image_canvas.create_image(0, 0, anchor="nw")
        self.overlay_shadow_item = self.image_canvas.create_text(
            15,
            15,
            anchor="nw",
            text="World",
            fill="#111715",
            font=("TkDefaultFont", 11, "bold"),
        )
        self.overlay_item = self.image_canvas.create_text(
            14,
            14,
            anchor="nw",
            text="World",
            fill="#ffffff",
            font=("TkDefaultFont", 11, "bold"),
        )
        self.selection_item = self.image_canvas.create_rectangle(
            0,
            0,
            0,
            0,
            outline="#ffd43b",
            width=3,
            state=tk.HIDDEN,
        )
        self.secondary_canvas = tk.Canvas(
            self.viewer_canvas_frame,
            background="#cbd2ce",
            highlightthickness=0,
        )
        self.secondary_image_item = self.secondary_canvas.create_image(
            0, 0, anchor="nw"
        )
        self.secondary_overlay_shadow_item = (
            self.secondary_canvas.create_text(
                15,
                15,
                anchor="nw",
                text="Second view",
                fill="#111715",
                font=("TkDefaultFont", 11, "bold"),
            )
        )
        self.secondary_overlay_item = self.secondary_canvas.create_text(
            14,
            14,
            anchor="nw",
            text="Second view",
            fill="#ffffff",
            font=("TkDefaultFont", 11, "bold"),
        )
        self.secondary_selection_item = self.secondary_canvas.create_rectangle(
            0,
            0,
            0,
            0,
            outline="#ffd43b",
            width=3,
            state=tk.HIDDEN,
        )
        self.secondary_canvas.grid(
            row=0, column=1, sticky="nsew", padx=(2, 0)
        )
        self.secondary_canvas.grid_remove()
        self.image_canvas.bind("<ButtonPress-1>", self._camera_press)
        self.image_canvas.bind("<B1-Motion>", self._camera_motion)
        self.image_canvas.bind("<ButtonRelease-1>", self._camera_release)
        self.image_canvas.bind("<ButtonPress-2>", self._camera_pan_press)
        self.image_canvas.bind("<B2-Motion>", self._camera_motion)
        self.image_canvas.bind("<ButtonRelease-2>", self._camera_release)
        self.image_canvas.bind("<ButtonPress-3>", self._camera_pan_press)
        self.image_canvas.bind("<B3-Motion>", self._camera_motion)
        self.image_canvas.bind("<ButtonRelease-3>", self._camera_release)
        self.image_canvas.bind("<Control-ButtonPress-1>", self._camera_pan_press)
        self.image_canvas.bind("<MouseWheel>", self._camera_wheel)
        self.image_canvas.bind("<Double-Button-1>", self._focus_selected)
        self.image_canvas.bind("<Configure>", self._canvas_resized)
        self.secondary_canvas.bind("<Configure>", self._canvas_resized)
        self.secondary_canvas.bind(
            "<ButtonPress-1>", self._secondary_canvas_press
        )

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        self.notebook = ttk.Notebook(parent)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=7, pady=7)
        self.scene_tab = ttk.Frame(self.notebook, padding=9)
        self.layout_tab = ttk.Frame(self.notebook, padding=9)
        self.actions_tab = ttk.Frame(self.notebook, padding=9)
        self.sensors_tab = ttk.Frame(self.notebook, padding=10)
        self.camera_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.scene_tab, text="Scene")
        self.notebook.add(self.layout_tab, text="Layout")
        self.notebook.add(self.actions_tab, text="Actions")
        self.notebook.add(self.sensors_tab, text="Sensors")
        self.notebook.add(self.camera_tab, text="Camera")
        self.notebook.enable_traversal()
        self._build_scene_tab(self.scene_tab)
        self._build_layout_tab(self.layout_tab)
        self._build_actions_tab(self.actions_tab)
        self._build_sensors_tab(self.sensors_tab)
        self._build_camera_tab(self.camera_tab)
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)

    def _build_scene_tab(self, parent: ttk.Frame) -> None:
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        tree_frame = ttk.Frame(parent)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.entity_tree = ttk.Treeview(
            tree_frame,
            columns=("kind", "state"),
            show="tree headings",
            height=11,
            selectmode="browse",
        )
        self.entity_tree.heading("#0", text="Entity")
        self.entity_tree.heading("kind", text="Type")
        self.entity_tree.heading("state", text="Control")
        self.entity_tree.column("#0", width=170, minwidth=100)
        self.entity_tree.column("kind", width=75, anchor="center")
        self.entity_tree.column("state", width=105, anchor="center")
        scrollbar = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.entity_tree.yview
        )
        self.entity_tree.configure(yscrollcommand=scrollbar.set)
        self.entity_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.entity_tree.bind("<<TreeviewSelect>>", self._tree_selected)

        add_controls = ttk.Frame(parent)
        add_controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        add_controls.grid_columnconfigure((0, 1, 2), weight=1)
        commands = (
            ("+ PyCub", self.add_pycub),
            ("+ Table", self.add_table),
            ("+ Object", self.add_object),
            ("Import model", self.import_model),
            ("Import agent", self.import_agent),
            ("Duplicate", self.duplicate_selected),
        )
        for index, (label, command) in enumerate(commands):
            ttk.Button(add_controls, text=label, command=command).grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=2,
                pady=2,
            )
        ttk.Button(
            add_controls, text="Remove", command=self.remove_selected
        ).grid(row=2, column=0, columnspan=3, sticky="ew", padx=2, pady=(4, 2))

        properties = ttk.LabelFrame(parent, text="Selected entity")
        properties.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        properties.grid_columnconfigure((1, 3, 5), weight=1)
        ttk.Label(properties, textvariable=self.entity_type_var).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 5)
        )
        ttk.Label(properties, text="Name").grid(row=1, column=0, sticky="w")
        name_entry = ttk.Entry(
            properties, textvariable=self.property_vars["name"]
        )
        name_entry.grid(row=1, column=1, columnspan=5, sticky="ew", pady=2)
        self.property_inputs["name"] = name_entry

        for row, fields in enumerate(
            (
                (("X [m]", "x"), ("Y [m]", "y"), ("Z [m]", "z")),
                (
                    ("Roll [deg]", "roll"),
                    ("Pitch [deg]", "pitch"),
                    ("Yaw [deg]", "yaw"),
                ),
            ),
            start=2,
        ):
            for group, (label, key) in enumerate(fields):
                ttk.Label(properties, text=label).grid(
                    row=row, column=group * 2, sticky="w"
                )
                entry = ttk.Entry(
                    properties,
                    textvariable=self.property_vars[key],
                    width=7,
                )
                entry.grid(
                    row=row,
                    column=group * 2 + 1,
                    sticky="ew",
                    padx=(0, 5),
                    pady=2,
                )
                self.property_inputs[key] = entry

        for group, (label, key) in enumerate(
            (
                ("Size X [m]", "size_x"),
                ("Size Y [m]", "size_y"),
                ("Size Z [m]", "size_z"),
            )
        ):
            ttk.Label(properties, text=label).grid(
                row=4, column=group * 2, sticky="w"
            )
            entry = ttk.Entry(
                properties,
                textvariable=self.property_vars[key],
                width=7,
            )
            entry.grid(
                row=4,
                column=group * 2 + 1,
                sticky="ew",
                padx=(0, 5),
                pady=2,
            )
            self.property_inputs[key] = entry

        ttk.Label(properties, text="Scale").grid(row=5, column=0, sticky="w")
        scale_entry = ttk.Entry(
            properties, textvariable=self.property_vars["scale"], width=7
        )
        scale_entry.grid(row=5, column=1, sticky="ew", padx=(0, 5), pady=2)
        self.property_inputs["scale"] = scale_entry
        ttk.Label(properties, text="Mass [kg]").grid(
            row=5, column=2, sticky="w"
        )
        mass_entry = ttk.Entry(
            properties, textvariable=self.property_vars["mass"], width=7
        )
        mass_entry.grid(row=5, column=3, sticky="ew", padx=(0, 5), pady=2)
        self.property_inputs["mass"] = mass_entry
        self.property_fixed_check = ttk.Checkbutton(
            properties, text="Fixed", variable=self.property_fixed_var
        )
        self.property_fixed_check.grid(row=5, column=4, sticky="w")
        self.property_color_button = tk.Button(
            properties,
            text="Color",
            borderwidth=1,
            command=self._choose_property_color,
        )
        self.property_color_button.grid(row=5, column=5, sticky="ew", pady=2)

        property_actions = ttk.Frame(properties)
        property_actions.grid(
            row=6, column=0, columnspan=6, sticky="ew", pady=(7, 0)
        )
        property_actions.grid_columnconfigure(0, weight=1)
        property_actions.grid_columnconfigure(1, weight=1)
        ttk.Button(
            property_actions,
            text="Apply",
            command=self.apply_properties,
            style="Primary.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            property_actions,
            text="Focus",
            command=self._focus_selected,
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0))

    def _build_layout_tab(self, parent: ttk.Frame) -> None:
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        self.layout_editor = SceneMapEditor(
            parent,
            self.simulation.entity_specs(),
            on_change=self._map_entity_changed,
            on_select=self._map_entity_selected,
            on_edit_begin=self._begin_scene_edit,
            height=430,
        )
        self.layout_editor.grid(row=0, column=0, sticky="nsew")

        selected = ttk.LabelFrame(parent, text="Selected placement")
        selected.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        selected.grid_columnconfigure((1, 3, 5), weight=1)
        ttk.Label(
            selected,
            textvariable=self.selection_label_var,
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 5))
        for group, (label, key) in enumerate(
            (("X [m]", "x"), ("Y [m]", "y"), ("Yaw [deg]", "yaw"))
        ):
            ttk.Label(selected, text=label).grid(
                row=1, column=group * 2, sticky="w"
            )
            ttk.Entry(
                selected,
                textvariable=self.property_vars[key],
                width=8,
            ).grid(
                row=1,
                column=group * 2 + 1,
                sticky="ew",
                padx=(3, 7),
            )
        ttk.Button(
            selected,
            text="Apply placement",
            command=self._apply_layout_fields,
        ).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(7, 0), padx=(0, 3))
        ttk.Button(
            selected,
            text="Fit world camera",
            command=self._fit_scene_camera,
        ).grid(row=2, column=3, columnspan=3, sticky="ew", pady=(7, 0), padx=(3, 0))

        targets = ttk.Frame(parent)
        targets.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        targets.grid_columnconfigure((0, 1, 2), weight=1)
        for column, (label, tab_name) in enumerate(
            (("Entity info", "scene"), ("Actions", "actions"), ("Features", "sensors"))
        ):
            ttk.Button(
                targets,
                text=label,
                command=lambda name=tab_name: self._show_sidebar_tab(name),
            ).grid(row=0, column=column, sticky="ew", padx=2)

    def _build_actions_tab(self, parent: ttk.Frame) -> None:
        parent.grid_rowconfigure(4, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        ttk.Label(
            parent,
            textvariable=self.selection_label_var,
            font=("TkDefaultFont", 12, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        behavior_frame = ttk.LabelFrame(parent, text="Behavior")
        behavior_frame.grid(row=1, column=0, sticky="ew")
        behavior_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(behavior_frame, text="Mode").grid(row=0, column=0, sticky="w")
        self.behavior_combo = ttk.Combobox(
            behavior_frame,
            textvariable=self.behavior_var,
            values=BUILTIN_BEHAVIORS,
            state="readonly",
        )
        self.behavior_combo.grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
        ttk.Label(behavior_frame, text="Speed").grid(row=1, column=0, sticky="w")
        ttk.Scale(
            behavior_frame,
            variable=self.behavior_speed_var,
            from_=0.1,
            to=2.5,
        ).grid(row=1, column=1, sticky="ew", padx=(4, 7))
        ttk.Label(behavior_frame, text="Intensity").grid(row=1, column=2, sticky="w")
        ttk.Scale(
            behavior_frame,
            variable=self.behavior_intensity_var,
            from_=0.0,
            to=1.0,
        ).grid(row=1, column=3, sticky="ew", padx=(4, 0))
        controls = ttk.Frame(behavior_frame)
        controls.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(7, 0))
        controls.grid_columnconfigure((0, 1, 2), weight=1)
        ttk.Button(controls, text="Start", command=self.start_action).grid(
            row=0, column=0, sticky="ew", padx=2
        )
        ttk.Button(controls, text="Stop", command=self.stop_action).grid(
            row=0, column=1, sticky="ew", padx=2
        )
        ttk.Button(controls, text="Home", command=self.home_selected).grid(
            row=0, column=2, sticky="ew", padx=2
        )
        ttk.Button(
            behavior_frame, text="Load action JSON", command=self.load_action
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 2))
        ttk.Label(
            behavior_frame,
            textvariable=self.action_file_var,
            foreground="#66716c",
            anchor="w",
        ).grid(row=3, column=2, columnspan=2, sticky="ew", padx=(8, 0))
        ttk.Label(
            behavior_frame,
            textvariable=self.controller_status_var,
            foreground="#45645a",
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

        task_frame = ttk.LabelFrame(parent, text="Cartesian reach and grip")
        task_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        task_frame.grid_columnconfigure((1, 3, 5), weight=1)
        ttk.Label(task_frame, text="Arm").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Combobox(
            task_frame,
            textvariable=self.ik_side_var,
            values=("Right", "Left"),
            state="readonly",
            width=7,
        ).grid(row=0, column=1, columnspan=2, sticky="ew", padx=(4, 8))
        ttk.Button(task_frame, text="Reach", command=self.reach_target).grid(
            row=0, column=4, columnspan=2, sticky="ew"
        )
        for group, key in enumerate(("x", "y", "z")):
            ttk.Label(task_frame, text=f"{key.upper()} [m]").grid(
                row=1, column=group * 2, sticky="w"
            )
            ttk.Entry(
                task_frame, textvariable=self.ik_vars[key], width=7
            ).grid(row=1, column=group * 2 + 1, sticky="ew", padx=(3, 7))
        ttk.Label(task_frame, text="Left grip").grid(row=2, column=0, sticky="w")
        ttk.Scale(
            task_frame,
            variable=self.left_grip_var,
            from_=0.0,
            to=1.0,
            command=lambda _value: self._grip_changed("l"),
        ).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(4, 8))
        ttk.Label(task_frame, text="Right grip").grid(
            row=2, column=3, sticky="w"
        )
        ttk.Scale(
            task_frame,
            variable=self.right_grip_var,
            from_=0.0,
            to=1.0,
            command=lambda _value: self._grip_changed("r"),
        ).grid(row=2, column=4, columnspan=2, sticky="ew", padx=(4, 0))

        ttk.Label(
            parent,
            text="Manual joints",
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=3, column=0, sticky="w", pady=(9, 4))
        self.manual_frame = ScrollableFrame(parent)
        self.manual_frame.grid(row=4, column=0, sticky="nsew")

    def _build_sensors_tab(self, parent: ttk.Frame) -> None:
        parent.grid_rowconfigure(3, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        ttk.Label(parent, text="Camera source").grid(
            row=0, column=0, sticky="w"
        )
        self.sensor_source_combo = ttk.Combobox(
            parent,
            textvariable=self.sensor_source_var,
            state="readonly",
        )
        self.sensor_source_combo.grid(row=1, column=0, sticky="ew", pady=(3, 9))
        self.sensor_source_combo.bind(
            "<<ComboboxSelected>>", self._sensor_source_changed
        )

        options = ttk.LabelFrame(parent, text="Enabled sensors")
        options.grid(row=2, column=0, sticky="ew")
        for index, (key, label) in enumerate(
            (
                ("rgb", "RGB"),
                ("depth", "Depth"),
                ("segmentation", "Segmentation"),
                ("joints", "Joint state"),
                ("imu", "IMU"),
                ("contact", "Contact"),
                ("lidar", "Range rays"),
            )
        ):
            ttk.Checkbutton(
                options,
                text=label,
                variable=self.sensor_vars[key],
                command=self._sensor_options_changed,
            ).grid(
                row=index // 3,
                column=index % 3,
                sticky="w",
                padx=(0, 10),
                pady=3,
            )

        data_frame = ttk.LabelFrame(parent, text="Live data")
        data_frame.grid(row=3, column=0, sticky="nsew", pady=(9, 0))
        data_frame.grid_rowconfigure(0, weight=1)
        data_frame.grid_columnconfigure(0, weight=1)
        self.telemetry_text = tk.Text(
            data_frame,
            height=20,
            wrap="none",
            state=tk.DISABLED,
            font=("Menlo", 9),
            background="#f0f3f1",
            foreground="#24312d",
            borderwidth=0,
        )
        self.telemetry_text.grid(row=0, column=0, sticky="nsew")
        ttk.Button(
            parent, text="Export sensor snapshot", command=self.export_sensor
        ).grid(row=4, column=0, sticky="ew", pady=(9, 0))

    def _build_camera_tab(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        for row, (label, key, lower, upper) in enumerate(
            (
                ("Yaw [deg]", "yaw", -180.0, 180.0),
                ("Pitch [deg]", "pitch", -82.0, 10.0),
                ("Distance [m]", "distance", 0.65, 12.0),
            )
        ):
            line = ttk.Frame(parent)
            line.grid(row=row, column=0, sticky="ew", pady=(0, 12))
            line.grid_columnconfigure(0, weight=1)
            ttk.Label(line, text=label).grid(row=0, column=0, sticky="w")
            value_label = ttk.Label(line, width=10, anchor="e")
            value_label.grid(row=0, column=1, sticky="e")
            ttk.Scale(
                line,
                variable=self.camera_vars[key],
                from_=lower,
                to=upper,
                command=lambda _value, camera_key=key: self._camera_scale_changed(
                    camera_key
                ),
            ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            self.camera_vars[key].trace_add(
                "write",
                lambda *_args, variable=self.camera_vars[key], target=value_label, camera_key=key: target.configure(
                    text=(
                        f"{variable.get():.2f} m"
                        if camera_key == "distance"
                        else f"{variable.get():.0f} deg"
                    )
                ),
            )
            value_label.configure(
                text=(
                    f"{self.camera_vars[key].get():.2f} m"
                    if key == "distance"
                    else f"{self.camera_vars[key].get():.0f} deg"
                )
            )
        ttk.Checkbutton(
            parent,
            text="Shadows",
            variable=self.shadow_var,
            command=self._render_controls_changed,
        ).grid(row=3, column=0, sticky="w", pady=(2, 8))
        ttk.Label(parent, text="Render quality").grid(row=4, column=0, sticky="w")
        quality_combo = ttk.Combobox(
            parent,
            textvariable=self.quality_var,
            values=("Performance", "Balanced", "Quality"),
            state="readonly",
        )
        quality_combo.grid(row=5, column=0, sticky="ew", pady=(3, 10))
        quality_combo.bind(
            "<<ComboboxSelected>>", self._render_controls_changed
        )
        ttk.Button(
            parent, text="Focus selected", command=self._focus_selected
        ).grid(row=6, column=0, sticky="ew", pady=3)
        ttk.Button(
            parent, text="Fit whole scene", command=self._reset_camera
        ).grid(row=7, column=0, sticky="ew", pady=3)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<space>", lambda _event: self._toggle_running())
        self.root.bind("<Command-s>", lambda _event: self.save_scene())
        self.root.bind("<Command-o>", lambda _event: self.open_scene())
        self.root.bind("<Command-z>", lambda _event: self.undo())
        self.root.bind("<Command-Shift-z>", lambda _event: self.redo())
        self.root.bind("<Command-d>", lambda _event: self._toggle_split_view())
        self.root.bind("<Control-s>", lambda _event: self.save_scene())
        self.root.bind("<Control-o>", lambda _event: self.open_scene())
        self.root.bind("<Control-z>", lambda _event: self.undo())
        self.root.bind("<Control-Shift-z>", lambda _event: self.redo())
        self.root.bind("<Control-d>", lambda _event: self._toggle_split_view())
        self.root.bind(
            "<Control-Tab>", lambda _event: self._cycle_sidebar_tab(1)
        )
        self.root.bind(
            "<Control-Shift-Tab>", lambda _event: self._cycle_sidebar_tab(-1)
        )
        self.root.bind(
            "<Control-ISO_Left_Tab>",
            lambda _event: self._cycle_sidebar_tab(-1),
        )

    def _cycle_sidebar_tab(self, direction: int) -> str:
        tabs = self.notebook.tabs()
        if not tabs:
            return "break"
        current = self.notebook.index("current")
        self.notebook.select(tabs[(current + direction) % len(tabs)])
        self._tab_changed()
        return "break"

    def _show_sidebar_tab(self, name: str) -> None:
        tabs = {
            "scene": self.scene_tab,
            "layout": self.layout_tab,
            "actions": self.actions_tab,
            "sensors": self.sensors_tab,
            "camera": self.camera_tab,
        }
        target = tabs.get(name)
        if target is not None:
            self.notebook.select(target)
            self._tab_changed()

    @staticmethod
    def _same_scene(left: SceneConfig, right: SceneConfig) -> bool:
        return left.to_dict() == right.to_dict()

    def _update_history_buttons(self) -> None:
        self.undo_button.configure(
            state=tk.NORMAL if self._undo_stack else tk.DISABLED
        )
        self.redo_button.configure(
            state=tk.NORMAL if self._redo_stack else tk.DISABLED
        )

    def _begin_scene_edit(self) -> None:
        if self._pending_edit_before is None:
            self._pending_edit_before = self.simulation.scene_config()

    def _commit_scene_edit(self, status: str) -> None:
        before = self._pending_edit_before
        self._pending_edit_before = None
        if before is None:
            return
        after = self.simulation.scene_config()
        if self._same_scene(before, after):
            self.status_var.set(status)
            return
        self._undo_stack.append(before)
        del self._undo_stack[:-64]
        self._redo_stack.clear()
        self._update_history_buttons()
        self.status_var.set(status)

    def _restore_scene_snapshot(
        self, scene: SceneConfig, status: str
    ) -> None:
        selected = self.selected_entity_id
        self.webcam.close()
        self.simulation.load_scene(scene)
        select_id = selected if selected in self.simulation.entities else None
        self._refresh_entity_tree(select_id=select_id)
        self._refresh_camera_sources()
        self.layout_editor.set_entities(self.simulation.entity_specs())
        self.layout_editor.set_selection(self.selected_entity_id)
        self._fit_camera_to_viewer()
        self._request_render()
        self.status_var.set(status)

    def undo(self) -> str:
        if not self._undo_stack:
            return "break"
        current = self.simulation.scene_config()
        target = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._pending_edit_before = None
        self._restore_scene_snapshot(target, "Undid scene edit")
        self._update_history_buttons()
        return "break"

    def redo(self) -> str:
        if not self._redo_stack:
            return "break"
        current = self.simulation.scene_config()
        target = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._pending_edit_before = None
        self._restore_scene_snapshot(target, "Redid scene edit")
        self._update_history_buttons()
        return "break"

    def _map_entity_selected(self, entity_id: str) -> None:
        if entity_id not in self.simulation.entities:
            return
        self.entity_tree.selection_set(entity_id)
        self.entity_tree.focus(entity_id)
        self.entity_tree.see(entity_id)
        self._select_entity(entity_id)

    def _map_entity_changed(self, spec: EntitySpec, final: bool) -> None:
        if spec.entity_id not in self.simulation.entities:
            return
        self.simulation.set_entity_transform(spec.entity_id, spec.transform)
        self._sync_properties(self.simulation.runtime(spec.entity_id).spec)
        self._request_render()
        if final:
            self.layout_editor.set_entities(self.simulation.entity_specs())
            self.layout_editor.set_selection(spec.entity_id)
            if self.simulation.camera_auto_center:
                self._fit_camera_to_viewer()
            else:
                self._sync_camera_vars()
            self._commit_scene_edit(f"Moved {spec.name}")

    def _apply_layout_fields(self) -> None:
        if self.selected_entity_id is None:
            return
        runtime = self.simulation.runtime(self.selected_entity_id)
        transform = copy.deepcopy(runtime.spec.transform)
        try:
            transform.x = float(self.property_vars["x"].get())
            transform.y = float(self.property_vars["y"].get())
            transform.yaw_deg = float(self.property_vars["yaw"].get())
            transform = transform.validated()
        except Exception as exc:
            messagebox.showerror("Invalid placement", str(exc), parent=self.root)
            return
        self._begin_scene_edit()
        self.simulation.set_entity_transform(self.selected_entity_id, transform)
        self.layout_editor.set_entities(self.simulation.entity_specs())
        self.layout_editor.set_selection(self.selected_entity_id)
        self._sync_properties(self.simulation.runtime(self.selected_entity_id).spec)
        if self.simulation.camera_auto_center:
            self._fit_camera_to_viewer()
        else:
            self._sync_camera_vars()
        self._request_render()
        self._commit_scene_edit(f"Moved {runtime.spec.name}")

    def _primary_aspect(self) -> float:
        return max(
            0.35,
            self.image_canvas.winfo_width()
            / max(1, self.image_canvas.winfo_height()),
        )

    def _fit_camera_to_viewer(self) -> None:
        self.simulation.fit_camera_to_scene(self._primary_aspect())
        self._sync_camera_vars()
        self._request_render()

    def _fit_scene_camera(self) -> None:
        self._fit_camera_to_viewer()
        self.status_var.set("World camera fitted to the whole scene")

    @staticmethod
    def _format_number(value: float) -> str:
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text

    def _entity_state(self, entity_id: str) -> str:
        runtime = self.simulation.runtime(entity_id)
        if runtime.spec.kind == "pycub":
            return runtime.spec.behavior if runtime.behavior_running else "Stopped"
        if runtime.controller_host is not None:
            return "Controller" if runtime.controller_host.running else "Stopped"
        return "Fixed" if runtime.spec.fixed_base else "Dynamic"

    def _refresh_entity_tree(self, select_id: str | None = None) -> None:
        previous = select_id or self.selected_entity_id
        self.entity_tree.delete(*self.entity_tree.get_children())
        for runtime in self.simulation.entities.values():
            spec = runtime.spec
            self.entity_tree.insert(
                "",
                tk.END,
                iid=spec.entity_id,
                text=spec.name,
                values=(spec.kind, self._entity_state(spec.entity_id)),
            )
        if previous in self.simulation.entities:
            self.entity_tree.selection_set(previous)
            self.entity_tree.focus(previous)
            self.entity_tree.see(previous)
            self._select_entity(previous)
        elif self.simulation.entities:
            first = next(iter(self.simulation.entities))
            self.entity_tree.selection_set(first)
            self._select_entity(first)
        else:
            self.selected_entity_id = None
            self.selection_label_var.set("No entity selected")

    def _tree_selected(self, _event: tk.Event) -> None:
        selection = self.entity_tree.selection()
        if selection:
            self._select_entity(selection[0])

    def _select_entity(self, entity_id: str) -> None:
        if entity_id not in self.simulation.entities:
            return
        self.selected_entity_id = entity_id
        runtime = self.simulation.runtime(entity_id)
        self.selection_label_var.set(runtime.spec.name)
        self._sync_properties(runtime.spec)
        self.behavior_var.set(runtime.spec.behavior)
        self.behavior_speed_var.set(runtime.behavior_speed)
        self.behavior_intensity_var.set(runtime.behavior_intensity)
        self.left_grip_var.set(runtime.left_grip)
        self.right_grip_var.set(runtime.right_grip)
        if runtime.keyframe_action is not None:
            self.action_file_var.set(runtime.keyframe_action.name)
        else:
            self.action_file_var.set("No action loaded")
        if runtime.controller_host is None:
            self.controller_status_var.set("No external controller")
        else:
            state = "running" if runtime.controller_host.running else "stopped"
            suffix = (
                f" | {runtime.controller_host.error}"
                if runtime.controller_host.error
                else ""
            )
            self.controller_status_var.set(f"External controller: {state}{suffix}")
        self.behavior_combo.configure(
            state="readonly" if runtime.spec.kind == "pycub" else "disabled"
        )
        if hasattr(self, "layout_editor"):
            self.layout_editor.set_selection(entity_id)
        self._rebuild_manual_controls()
        self._sync_sensor_options(runtime.spec)
        self._request_render()

    def _sync_properties(self, spec: EntitySpec) -> None:
        transform = spec.transform
        values = {
            "name": spec.name,
            "x": transform.x,
            "y": transform.y,
            "z": transform.z,
            "roll": transform.roll_deg,
            "pitch": transform.pitch_deg,
            "yaw": transform.yaw_deg,
            "scale": spec.scale,
            "mass": spec.mass,
            "size_x": spec.size[0],
            "size_y": spec.size[1],
            "size_z": spec.size[2],
        }
        for key, value in values.items():
            self.property_vars[key].set(
                str(value) if key == "name" else self._format_number(value)
            )
        self.property_fixed_var.set(spec.fixed_base)
        self.entity_type_var.set(f"{spec.kind} | {spec.entity_id}")
        self._property_color = spec.color
        hex_color = "#%02x%02x%02x" % tuple(
            round(value * 255) for value in spec.color[:3]
        )
        self.property_color_button.configure(background=hex_color)
        self._configure_property_states(spec)

    def _configure_property_states(self, spec: EntitySpec) -> None:
        enabled = {
            "name",
            "x",
            "y",
            "z",
            "roll",
            "pitch",
            "yaw",
        }
        fixed_enabled = True
        color_enabled = False
        if spec.kind == "pycub":
            enabled.add("scale")
        elif spec.kind == "table":
            enabled.update(("size_x", "size_y", "size_z"))
            fixed_enabled = False
            color_enabled = True
        elif spec.kind == "primitive":
            enabled.update(("size_x", "size_y", "size_z", "mass"))
            color_enabled = True
        elif spec.kind == "model":
            suffix = Path(spec.model_path).suffix.lower()
            if suffix in {".obj", ".stl"}:
                enabled.update(("scale", "mass"))
                color_enabled = True
            elif suffix == ".urdf":
                enabled.add("scale")
        elif spec.kind == "agent":
            enabled.add("scale")

        for key, entry in self.property_inputs.items():
            entry.configure(state="normal" if key in enabled else "disabled")
        self.property_fixed_check.configure(
            state="normal" if fixed_enabled else "disabled"
        )
        self.property_color_button.configure(
            state=tk.NORMAL if color_enabled else tk.DISABLED
        )

    def _choose_property_color(self) -> None:
        initial = "#%02x%02x%02x" % tuple(
            round(value * 255) for value in self._property_color[:3]
        )
        rgb, hex_value = colorchooser.askcolor(
            initialcolor=initial, parent=self.root
        )
        if rgb is None or hex_value is None:
            return
        self._property_color = tuple(value / 255.0 for value in rgb) + (1.0,)
        self.property_color_button.configure(background=hex_value)

    def apply_properties(self) -> None:
        if self.selected_entity_id is None:
            return
        runtime = self.simulation.runtime(self.selected_entity_id)
        spec = copy.deepcopy(runtime.spec)
        try:
            spec.name = self.property_vars["name"].get().strip() or spec.name
            spec.transform = Transform(
                x=float(self.property_vars["x"].get()),
                y=float(self.property_vars["y"].get()),
                z=float(self.property_vars["z"].get()),
                roll_deg=float(self.property_vars["roll"].get()),
                pitch_deg=float(self.property_vars["pitch"].get()),
                yaw_deg=float(self.property_vars["yaw"].get()),
            )
            spec.scale = float(self.property_vars["scale"].get())
            spec.mass = float(self.property_vars["mass"].get())
            spec.size = (
                float(self.property_vars["size_x"].get()),
                float(self.property_vars["size_y"].get()),
                float(self.property_vars["size_z"].get()),
            )
            spec.fixed_base = self.property_fixed_var.get()
            spec.color = self._property_color
            spec = spec.validated()
            self._begin_scene_edit()
            self.simulation.update_entity(spec)
        except Exception as exc:
            self._pending_edit_before = None
            messagebox.showerror("Invalid entity", str(exc), parent=self.root)
            return
        self._refresh_entity_tree(select_id=spec.entity_id)
        self._refresh_camera_sources()
        self.layout_editor.set_entities(self.simulation.entity_specs())
        self.layout_editor.set_selection(spec.entity_id)
        if self.simulation.camera_auto_center:
            self._fit_camera_to_viewer()
        self._request_render()
        self._commit_scene_edit(f"Updated {spec.name}")

    def add_pycub(self) -> None:
        self._begin_scene_edit()
        try:
            entity_id = self.simulation.add_pycub()
        except Exception as exc:
            self._pending_edit_before = None
            messagebox.showerror("Could not add PyCub", str(exc), parent=self.root)
            return
        self._scene_changed(entity_id, "Added PyCub")

    def add_table(self) -> None:
        self._begin_scene_edit()
        try:
            entity_id = self.simulation.add_table()
        except Exception as exc:
            self._pending_edit_before = None
            messagebox.showerror("Could not add table", str(exc), parent=self.root)
            return
        self._scene_changed(entity_id, "Added table")

    def add_object(self) -> None:
        dialog = PrimitiveDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self._begin_scene_edit()
        try:
            entity_id = self.simulation.add_primitive(**dialog.result)
        except Exception as exc:
            self._pending_edit_before = None
            messagebox.showerror("Could not add object", str(exc), parent=self.root)
            return
        self._scene_changed(entity_id, "Added object")

    def import_model(self) -> None:
        source = filedialog.askopenfilename(
            parent=self.root,
            title="Import 3D model",
            filetypes=(
                ("Robot and model files", "*.urdf *.sdf *.xml *.obj *.stl"),
                ("URDF", "*.urdf"),
                ("SDF", "*.sdf"),
                ("MJCF", "*.xml"),
                ("Meshes", "*.obj *.stl"),
                ("All files", "*"),
            ),
        )
        if not source:
            return
        dialog = ModelImportDialog(self.root, source)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self._begin_scene_edit()
        try:
            entity_id = self.simulation.import_model(source, **dialog.result)
        except Exception as exc:
            self._pending_edit_before = None
            messagebox.showerror("Could not import model", str(exc), parent=self.root)
            return
        self._scene_changed(entity_id, f"Imported {Path(source).name}")

    def import_agent(self) -> None:
        source = filedialog.askopenfilename(
            parent=self.root,
            title="Import agent bundle",
            initialdir=PROJECT_ROOT / "examples" / "agents",
            filetypes=(("Agent manifest", "agent.json"), ("JSON", "*.json")),
        )
        if not source:
            return
        self._begin_scene_edit()
        try:
            entity_id = self.simulation.import_agent(source)
        except Exception as exc:
            self._pending_edit_before = None
            messagebox.showerror("Could not import agent", str(exc), parent=self.root)
            return
        self._scene_changed(
            entity_id,
            f"Imported agent {self.simulation.runtime(entity_id).spec.name}",
        )

    def duplicate_selected(self) -> None:
        if self.selected_entity_id is None:
            return
        self._begin_scene_edit()
        try:
            entity_id = self.simulation.duplicate_entity(self.selected_entity_id)
        except Exception as exc:
            self._pending_edit_before = None
            messagebox.showerror("Could not duplicate", str(exc), parent=self.root)
            return
        self._scene_changed(entity_id, "Duplicated entity")

    def remove_selected(self) -> None:
        if self.selected_entity_id is None:
            return
        name = self.simulation.runtime(self.selected_entity_id).spec.name
        if not messagebox.askyesno(
            "Remove entity",
            f"Remove {name} from the scene?",
            parent=self.root,
        ):
            return
        self._begin_scene_edit()
        entity_id = self.selected_entity_id
        self.simulation.remove_entity(entity_id)
        self.selected_entity_id = None
        self._refresh_entity_tree()
        self._refresh_camera_sources()
        self.layout_editor.set_entities(self.simulation.entity_specs())
        if self.simulation.camera_auto_center:
            self._fit_camera_to_viewer()
        self._request_render()
        self._commit_scene_edit(f"Removed {name}")

    def _scene_changed(self, select_id: str, status: str) -> None:
        self._refresh_entity_tree(select_id=select_id)
        self._refresh_camera_sources()
        self.layout_editor.set_entities(self.simulation.entity_specs())
        self.layout_editor.set_selection(select_id)
        if self.simulation.camera_auto_center:
            self._fit_camera_to_viewer()
        self._request_render()
        self._commit_scene_edit(status)

    def _rebuild_manual_controls(self) -> None:
        for child in self.manual_frame.interior.winfo_children():
            child.destroy()
        self.manual_vars.clear()
        if self.selected_entity_id is None:
            return
        runtime = self.simulation.runtime(self.selected_entity_id)
        if runtime.spec.kind != "pycub":
            ttk.Label(
                self.manual_frame.interior,
                text="Manual joint controls are available for PyCub.",
                foreground="#68736e",
            ).grid(row=0, column=0, sticky="w", padx=4, pady=8)
            return
        self._manual_syncing = True
        try:
            for row, name in enumerate(
                joint for joint in MANUAL_JOINT_NAMES if joint in runtime.joints
            ):
                joint_id = runtime.joints[name]
                lower, upper = runtime.joint_limits[joint_id]
                current = runtime.manual_deg.get(
                    name,
                    math.degrees(runtime.target_positions.get(joint_id, 0.0)),
                )
                variable = tk.DoubleVar(value=current)
                self.manual_vars[name] = variable
                ttk.Label(
                    self.manual_frame.interior,
                    text=name,
                    width=20,
                    anchor="w",
                ).grid(row=row, column=0, sticky="w", padx=(3, 5), pady=3)
                value_label = ttk.Label(
                    self.manual_frame.interior,
                    text=f"{current:.1f} deg",
                    width=10,
                    anchor="e",
                )
                value_label.grid(row=row, column=2, sticky="e", padx=(4, 3))
                ttk.Scale(
                    self.manual_frame.interior,
                    variable=variable,
                    from_=math.degrees(lower),
                    to=math.degrees(upper),
                    command=lambda _value, joint_name=name, var=variable, label=value_label: self._manual_changed(
                        joint_name, var, label
                    ),
                ).grid(row=row, column=1, sticky="ew", pady=3)
            self.manual_frame.interior.grid_columnconfigure(1, weight=1)
        finally:
            self._manual_syncing = False

    def _manual_changed(
        self, name: str, variable: tk.DoubleVar, label: ttk.Label
    ) -> None:
        value = variable.get()
        label.configure(text=f"{value:.1f} deg")
        if self._manual_syncing or self.selected_entity_id is None:
            return
        try:
            self.simulation.set_manual_joint_deg(
                self.selected_entity_id, name, value
            )
            self.behavior_var.set("Manual pose")
            self._request_render()
        except (KeyError, ValueError):
            return

    def start_action(self) -> None:
        if self.selected_entity_id is None:
            return
        runtime = self.simulation.runtime(self.selected_entity_id)
        try:
            if runtime.spec.kind == "pycub":
                self.simulation.set_behavior(
                    self.selected_entity_id,
                    self.behavior_var.get(),
                    running=True,
                    speed=self.behavior_speed_var.get(),
                    intensity=self.behavior_intensity_var.get(),
                )
                self.status_var.set(
                    f"{runtime.spec.name}: {self.behavior_var.get()}"
                )
            elif runtime.controller_host is not None:
                self.simulation.start_controller(self.selected_entity_id)
                self.status_var.set(f"Started {runtime.spec.name} controller")
            else:
                raise RuntimeError("Selected entity has no behavior controller.")
        except Exception as exc:
            messagebox.showerror("Could not start action", str(exc), parent=self.root)
        self._refresh_entity_tree(select_id=self.selected_entity_id)
        self._request_render()

    def stop_action(self) -> None:
        if self.selected_entity_id is None:
            return
        runtime = self.simulation.runtime(self.selected_entity_id)
        if runtime.spec.kind == "pycub":
            self.simulation.stop_behavior(self.selected_entity_id)
        self.simulation.stop_controller(self.selected_entity_id)
        self.status_var.set(f"Stopped {runtime.spec.name}")
        self._refresh_entity_tree(select_id=self.selected_entity_id)
        self._request_render()

    def home_selected(self) -> None:
        if self.selected_entity_id is None:
            return
        runtime = self.simulation.runtime(self.selected_entity_id)
        if runtime.spec.kind != "pycub":
            self.status_var.set("Home pose is available for PyCub")
            return
        self.simulation.home_entity(self.selected_entity_id)
        self.behavior_var.set("Manual pose")
        self._rebuild_manual_controls()
        self._request_render()
        self.status_var.set(f"{runtime.spec.name}: home pose")

    def load_action(self) -> None:
        if self.selected_entity_id is None:
            return
        source = filedialog.askopenfilename(
            parent=self.root,
            title="Load keyframe action",
            initialdir=ACTION_DIR,
            filetypes=(("Action JSON", "*.json"),),
        )
        if not source:
            return
        try:
            action = self.simulation.load_action(self.selected_entity_id, source)
        except Exception as exc:
            messagebox.showerror("Could not load action", str(exc), parent=self.root)
            return
        self.behavior_var.set("Keyframe action")
        self.action_file_var.set(action.name)
        self.status_var.set(f"Loaded action {action.name}")

    def reach_target(self) -> None:
        if self.selected_entity_id is None:
            return
        try:
            target = tuple(float(self.ik_vars[key].get()) for key in ("x", "y", "z"))
            side = "r" if self.ik_side_var.get() == "Right" else "l"
            error = self.simulation.reach(self.selected_entity_id, side, target)
        except Exception as exc:
            messagebox.showerror("Could not reach target", str(exc), parent=self.root)
            return
        self.behavior_var.set("Manual pose")
        self._rebuild_manual_controls()
        self._request_render()
        self.status_var.set(f"IK command set | initial error {error:.3f} m")

    def _grip_changed(self, side: str) -> None:
        if self._manual_syncing or self.selected_entity_id is None:
            return
        runtime = self.simulation.runtime(self.selected_entity_id)
        if runtime.spec.kind != "pycub":
            return
        value = self.left_grip_var.get() if side == "l" else self.right_grip_var.get()
        self.simulation.set_grip(self.selected_entity_id, side, value)
        self._request_render()

    def _refresh_camera_sources(self) -> None:
        sources = self.simulation.camera_sources()
        self.sensor_source_map = {label: key for key, label in sources}
        self.secondary_source_map = dict(self.sensor_source_map)
        labels = list(self.sensor_source_map)
        self.sensor_source_combo.configure(values=labels)
        self.viewer_source_combo.configure(values=labels)
        self.secondary_source_combo.configure(values=labels)
        current_label = next(
            (
                label
                for label, key in self.sensor_source_map.items()
                if key == self.sensor_source_key
            ),
            None,
        )
        if current_label is None:
            preferred = next(
                (
                    (key, label)
                    for key, label in sources
                    if key.endswith(":left_eye")
                ),
                sources[0],
            )
            self.sensor_source_key = preferred[0]
            current_label = preferred[1]
        self.sensor_source_var.set(current_label)
        secondary_label = next(
            (
                label
                for label, key in self.secondary_source_map.items()
                if key == self.secondary_source_key
            ),
            None,
        )
        if secondary_label is None:
            preferred = next(
                (
                    (key, label)
                    for key, label in sources
                    if key.endswith(":right_eye")
                ),
                next(
                    (
                        (key, label)
                        for key, label in sources
                        if key.endswith(":left_eye")
                    ),
                    sources[0],
                ),
            )
            self.secondary_source_key = preferred[0]
            secondary_label = preferred[1]
        self.secondary_source_var.set(secondary_label)

    def _sensor_source_changed(self, _event: tk.Event | None = None) -> None:
        label = self.sensor_source_var.get()
        key = self.sensor_source_map.get(label)
        if key is None:
            return
        self.sensor_source_key = key
        if key.startswith("webcam"):
            self.webcam.retry()
            self.view_var.set("Sensor RGB")
        elif key == "world":
            self.webcam.close()
            self.view_var.set("World")
        elif ":" in key:
            self.webcam.close()
            entity_id, mount = key.split(":", 1)
            if entity_id in self.simulation.entities:
                runtime = self.simulation.runtime(entity_id)
                runtime.spec.sensors.camera_mount = mount
                self._sync_sensor_options(runtime.spec)
        self._request_render()
        self.status_var.set(f"Camera source: {label}")

    def _secondary_source_changed(
        self, _event: tk.Event | None = None
    ) -> None:
        key = self.secondary_source_map.get(self.secondary_source_var.get())
        if key is None:
            return
        self.secondary_source_key = key
        if key.startswith("webcam"):
            self.webcam.retry()
            self.secondary_view_var.set("Sensor RGB")
        elif key == "world":
            self.secondary_view_var.set("World")
        self._request_render()
        self.status_var.set(
            f"Second camera source: {self.secondary_source_var.get()}"
        )

    def _secondary_view_changed(
        self, _event: tk.Event | None = None
    ) -> None:
        self._request_render()
        self.status_var.set(f"Second view: {self.secondary_view_var.get()}")

    def _split_view_changed(self) -> None:
        if self.split_view_var.get():
            self.viewer_canvas_frame.grid_columnconfigure(0, weight=1)
            self.viewer_canvas_frame.grid_columnconfigure(1, weight=1)
            self.secondary_controls.grid()
            self.secondary_canvas.grid()
        else:
            self.viewer_canvas_frame.grid_columnconfigure(0, weight=1)
            self.viewer_canvas_frame.grid_columnconfigure(1, weight=0)
            self.secondary_controls.grid_remove()
            self.secondary_canvas.grid_remove()
        self._request_render()

    def _toggle_split_view(self) -> str:
        self.split_view_var.set(not self.split_view_var.get())
        self._split_view_changed()
        return "break"

    def _cursor_mode_changed(self) -> None:
        mode = self.cursor_mode_var.get()
        cursor = {
            "Camera": "fleur",
            "Select": "crosshair",
            "Move": "hand2",
        }.get(mode, "arrow")
        self.image_canvas.configure(cursor=cursor)
        self.status_var.set(f"Cursor mode: {mode}")

    def _secondary_canvas_press(self, event: tk.Event) -> None:
        if self.cursor_mode_var.get() == "Camera":
            return
        view = self.secondary_view_var.get()
        if view not in {"World", "Top", "Side"}:
            self.status_var.set("Entity selection uses a scene view")
            return
        entity_id, _hit = self.simulation.pick_entity(
            view,
            event.x,
            event.y,
            self.secondary_canvas.winfo_width(),
            self.secondary_canvas.winfo_height(),
        )
        if entity_id is not None:
            self._map_entity_selected(entity_id)
            self.status_var.set(
                f"Selected {self.simulation.runtime(entity_id).spec.name}"
            )

    def _sync_sensor_options(self, spec: EntitySpec) -> None:
        options = spec.sensors
        for key in self.sensor_vars:
            self.sensor_vars[key].set(bool(getattr(options, key)))

    def _sensor_options_changed(self) -> None:
        entity_id = self._sensor_entity_id()
        if entity_id is None:
            return
        options = self.simulation.runtime(entity_id).spec.sensors
        for key, variable in self.sensor_vars.items():
            setattr(options, key, variable.get())
        self._request_render()

    def _tab_changed(self, _event: tk.Event | None = None) -> None:
        if self.notebook.select() == str(self.layout_tab):
            self.layout_editor.set_entities(self.simulation.entity_specs())
            self.layout_editor.set_selection(self.selected_entity_id)
        if self.notebook.select() == str(self.sensors_tab):
            self._last_telemetry_s = 0.0
            self._refresh_telemetry()

    def _sensor_entity_id(self) -> str | None:
        if ":" in self.sensor_source_key and not self.sensor_source_key.startswith(
            ("webcam", "world")
        ):
            entity_id = self.sensor_source_key.split(":", 1)[0]
            if entity_id in self.simulation.entities:
                return entity_id
        return self.selected_entity_id

    def _view_changed(self) -> None:
        mode = self.view_var.get()
        key_map = {
            "Sensor RGB": "rgb",
            "Sensor Depth": "depth",
            "Segmentation": "segmentation",
        }
        sensor_key = key_map.get(mode)
        entity_id = self._sensor_entity_id()
        if sensor_key is not None and entity_id is not None:
            setattr(
                self.simulation.runtime(entity_id).spec.sensors,
                sensor_key,
                True,
            )
            self.sensor_vars[sensor_key].set(True)
        self._request_render()
        self.status_var.set(f"{mode} view")

    def _render_size(self, width: int, height: int) -> tuple[int, int]:
        scale, max_width = {
            "Performance": (1.25, 1280),
            "Balanced": (1.65, 1920),
            "Quality": (2.0, 2560),
        }[self.quality_var.get()]
        render_width = min(max_width, max(64, round(width * scale)))
        render_height = max(
            64, round(height * render_width / max(1, width))
        )
        return render_width, render_height

    def _request_render(self) -> None:
        self._render_dirty = True

    def _canvas_resized(self, _event: tk.Event) -> None:
        self._request_render()
        if not self.simulation.camera_auto_center:
            return
        if self._camera_fit_after_id is not None:
            self.root.after_cancel(self._camera_fit_after_id)
        self._camera_fit_after_id = self.root.after(
            100, self._fit_camera_after_resize
        )

    def _fit_camera_after_resize(self) -> None:
        self._camera_fit_after_id = None
        if self.simulation.camera_auto_center:
            self._fit_camera_to_viewer()

    def _render_controls_changed(self, _event: tk.Event | None = None) -> None:
        self._request_render()

    def _render_fps(self) -> float:
        return {
            "Performance": 10.0,
            "Balanced": 8.0,
            "Quality": 5.0,
        }[self.quality_var.get()]

    def _continuous_render_required(self) -> bool:
        panes = [(self.view_var.get(), self.sensor_source_key)]
        if self.split_view_var.get():
            panes.append(
                (self.secondary_view_var.get(), self.secondary_source_key)
            )
        webcam_active = any(
            view not in {"World", "Top", "Side"}
            and source.startswith("webcam")
            and not self.webcam.error
            for view, source in panes
        )
        return webcam_active or (
            self.running and self.simulation.has_active_updates()
        )

    def _render_pane(
        self,
        *,
        pane_key: str,
        canvas: tk.Canvas,
        image_item: int,
        overlay_shadow_item: int,
        overlay_item: int,
        selection_item: int,
        view: str,
        source_key: str,
        source_label: str,
    ) -> None:
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 80 or height < 80:
            return
        render_width, render_height = self._render_size(width, height)
        overlay = view
        if view in {"World", "Top", "Side"}:
            frame = self.simulation.render(
                render_width,
                render_height,
                view=view,
                shadows=self.shadow_var.get(),
            )
        elif source_key.startswith("webcam"):
            index = int(source_key.split(":", 1)[1])
            frame = self.webcam.read(index, render_width, render_height)
            overlay = f"Sensor RGB | Mac webcam {index}"
            if view != "Sensor RGB":
                self.status_var.set("Webcam provides RGB only")
        elif source_key == "world":
            frame = self.simulation.render(
                render_width,
                render_height,
                view="World",
                shadows=self.shadow_var.get(),
            )
            overlay = f"{view} | World camera"
        else:
            sensor_frame = self.simulation.capture_camera(
                source_key,
                render_width,
                render_height,
            )
            if view == "Sensor Depth":
                frame = sensor_frame.depth_rgb
                center_depth = float(
                    sensor_frame.depth_m[
                        render_height // 2, render_width // 2
                    ]
                )
                depth_text = (
                    f"{center_depth:.3f} m"
                    if math.isfinite(center_depth) and center_depth < 9.95
                    else "no return"
                )
                overlay = f"{view} | {source_label} | center {depth_text}"
            elif view == "Segmentation":
                frame = sensor_frame.segmentation_rgb
            else:
                frame = sensor_frame.rgb
            if view != "Sensor Depth":
                overlay = f"{view} | {source_label}"
        image = Image.fromarray(frame)
        if image.size != (width, height):
            resampling = {
                "Performance": Image.Resampling.BILINEAR,
                "Balanced": Image.Resampling.BICUBIC,
                "Quality": Image.Resampling.LANCZOS,
            }[self.quality_var.get()]
            image = image.resize((width, height), resampling)
        photo = ImageTk.PhotoImage(image)
        self.photos[pane_key] = photo
        if pane_key == "primary":
            self.photo = photo
        canvas.itemconfigure(image_item, image=photo)
        canvas.itemconfigure(overlay_shadow_item, text=overlay)
        canvas.itemconfigure(overlay_item, text=overlay)

        bounds = None
        if (
            self.selected_entity_id in self.simulation.entities
            and view in {"World", "Top", "Side"}
        ):
            bounds = self.simulation.entity_screen_bounds(
                self.selected_entity_id,
                view,
                width,
                height,
            )
        if bounds is None:
            canvas.itemconfigure(selection_item, state=tk.HIDDEN)
        else:
            left, top, right, bottom = bounds
            canvas.coords(
                selection_item,
                max(2.0, left - 4.0),
                max(2.0, top - 4.0),
                min(width - 2.0, right + 4.0),
                min(height - 2.0, bottom + 4.0),
            )
            canvas.itemconfigure(selection_item, state=tk.NORMAL)
            canvas.tag_raise(selection_item)
        canvas.tag_raise(overlay_shadow_item)
        canvas.tag_raise(overlay_item)

    def _render_frame(self) -> None:
        panes = (
            (
                "primary",
                self.image_canvas,
                self.image_item,
                self.overlay_shadow_item,
                self.overlay_item,
                self.selection_item,
                self.view_var.get(),
                self.sensor_source_key,
                self.sensor_source_var.get(),
            ),
        )
        if self.split_view_var.get():
            panes += (
                (
                    "secondary",
                    self.secondary_canvas,
                    self.secondary_image_item,
                    self.secondary_overlay_shadow_item,
                    self.secondary_overlay_item,
                    self.secondary_selection_item,
                    self.secondary_view_var.get(),
                    self.secondary_source_key,
                    self.secondary_source_var.get(),
                ),
            )
        for (
            pane_key,
            canvas,
            image_item,
            overlay_shadow_item,
            overlay_item,
            selection_item,
            view,
            source_key,
            source_label,
        ) in panes:
            try:
                self._render_pane(
                    pane_key=pane_key,
                    canvas=canvas,
                    image_item=image_item,
                    overlay_shadow_item=overlay_shadow_item,
                    overlay_item=overlay_item,
                    selection_item=selection_item,
                    view=view,
                    source_key=source_key,
                    source_label=source_label,
                )
            except Exception as exc:
                self.status_var.set(f"{pane_key.title()} render error: {exc}")
        self._render_dirty = False

    def _refresh_telemetry(self) -> None:
        entity_id = self._sensor_entity_id()
        if entity_id is None or entity_id not in self.simulation.entities:
            text = "No sensor entity selected."
        else:
            runtime = self.simulation.runtime(entity_id)
            snapshot = self.simulation.sensor_snapshot(entity_id)
            lines = [
                f"entity   {runtime.spec.name}",
                f"type     {runtime.spec.kind}",
                f"time     {snapshot['time_s']:.3f} s",
                f"camera   {self.sensor_source_var.get()}",
            ]
            imu = snapshot.get("imu")
            if imu:
                position = imu["position"]
                rpy = imu["rpy_deg"]
                velocity = imu["linear_velocity"]
                lines.extend(
                    (
                        "",
                        "IMU",
                        f"  position [m]   {position[0]: .3f}"
                        f" {position[1]: .3f} {position[2]: .3f}",
                        f"  rpy [deg]      {rpy[0]: .1f} {rpy[1]: .1f} {rpy[2]: .1f}",
                        f"  velocity [m/s] {velocity[0]: .3f}"
                        f" {velocity[1]: .3f} {velocity[2]: .3f}",
                    )
                )
            contacts = snapshot.get("contact")
            if contacts:
                lines.extend(
                    (
                        "",
                        "CONTACT",
                        f"  count     {contacts['count']}",
                        f"  max force {contacts['max_force']:.3f} N",
                    )
                )
            joints = snapshot.get("joints")
            if joints:
                lines.extend(("", f"JOINTS   {len(joints)}"))
                for name in (
                    "torso_pitch",
                    "neck_yaw",
                    "r_shoulder_pitch",
                    "r_elbow",
                    "l_shoulder_pitch",
                    "l_elbow",
                ):
                    state = joints.get(name)
                    if state:
                        lines.append(
                            f"  {name:<18} {math.degrees(state['position']): 7.2f} deg"
                        )
            lidar = snapshot.get("lidar_m")
            if lidar:
                lines.extend(
                    (
                        "",
                        f"RANGE    {len(lidar)} rays",
                        f"  min/mean {min(lidar):.3f} / {sum(lidar) / len(lidar):.3f} m",
                    )
                )
            host = runtime.controller_host
            if host is not None:
                lines.extend(
                    (
                        "",
                        f"CONTROLLER {'running' if host.running else 'stopped'}",
                        f"  error {host.error or 'none'}",
                    )
                )
            text = "\n".join(lines)
        self.telemetry_text.configure(state=tk.NORMAL)
        self.telemetry_text.delete("1.0", tk.END)
        self.telemetry_text.insert("1.0", text)
        self.telemetry_text.configure(state=tk.DISABLED)

    def export_sensor(self) -> None:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export sensor snapshot",
            initialdir=ARTIFACT_DIR,
            initialfile="sensor_snapshot.png",
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"),),
        )
        if not destination:
            return
        try:
            source = self.sensor_source_key
            if source.startswith("webcam"):
                index = int(source.split(":", 1)[1])
                frame = self.webcam.read(index, 960, 640)
                snapshot = {"source": source, "type": "rgb"}
            elif source == "world":
                frame = self.simulation.render(960, 640, "World", True)
                snapshot = {"source": source, "type": "world"}
            else:
                sensor = self.simulation.capture_camera(source, 960, 640)
                mode = self.view_var.get()
                frame = (
                    sensor.depth_rgb
                    if mode == "Sensor Depth"
                    else sensor.segmentation_rgb
                    if mode == "Segmentation"
                    else sensor.rgb
                )
                entity_id = source.split(":", 1)[0]
                snapshot = self.simulation.sensor_snapshot(entity_id)
                snapshot["source"] = source
            Image.fromarray(frame).save(destination)
            json_path = Path(destination).with_suffix(".json")
            json_path.write_text(
                json.dumps(snapshot, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self.status_var.set(f"Exported {Path(destination).name}")
        except Exception as exc:
            messagebox.showerror("Could not export sensor", str(exc), parent=self.root)

    def _toggle_running(self) -> None:
        self.running = not self.running
        self.simulation.paused = not self.running
        self._physics_accumulator_s = 0.0
        self._last_tick_s = time.perf_counter()
        self.run_button_var.set("Pause" if self.running else "Run")
        self.status_var.set("Simulation running" if self.running else "Simulation paused")

    def _single_step(self) -> None:
        was_paused = self.simulation.paused
        self.simulation.paused = False
        self.simulation.step(1)
        self.simulation.paused = was_paused or not self.running
        self.time_var.set(f"{self.simulation.elapsed_s:.2f} s")
        self._request_render()

    def _camera_press(self, event: tk.Event) -> None:
        mode = self.cursor_mode_var.get()
        view = self.view_var.get()
        if mode == "Camera":
            self._camera_drag_last = (event.x, event.y)
            self._camera_drag_mode = (
                "pan" if event.state & 0x0001 else "orbit"
            )
            return
        if view not in {"World", "Top", "Side"}:
            self.status_var.set("Entity selection uses World, Top or Side")
            return
        entity_id, _hit_point = self.simulation.pick_entity(
            view,
            event.x,
            event.y,
            self.image_canvas.winfo_width(),
            self.image_canvas.winfo_height(),
        )
        if entity_id is None:
            self.status_var.set("No entity under cursor")
            return
        self._map_entity_selected(entity_id)
        runtime = self.simulation.runtime(entity_id)
        self.status_var.set(f"Selected {runtime.spec.name}")
        if mode != "Move" or view == "Side":
            return
        transform = runtime.spec.transform
        plane_point = self.simulation.screen_to_plane(
            view,
            event.x,
            event.y,
            self.image_canvas.winfo_width(),
            self.image_canvas.winfo_height(),
            transform.z,
        )
        if plane_point is None:
            return
        self._begin_scene_edit()
        self._cursor_drag_entity_id = entity_id
        self._cursor_drag_plane_z = transform.z
        self._cursor_drag_offset = (
            transform.x - plane_point[0],
            transform.y - plane_point[1],
        )
        self._cursor_drag_changed = False
        self._cursor_drag_auto_center = self.simulation.camera_auto_center
        self.simulation.camera_auto_center = False

    def _camera_pan_press(self, event: tk.Event) -> None:
        self._camera_drag_last = (event.x, event.y)
        self._camera_drag_mode = "pan"

    def _camera_motion(self, event: tk.Event) -> None:
        if self._cursor_drag_entity_id is not None:
            point = self.simulation.screen_to_plane(
                self.view_var.get(),
                event.x,
                event.y,
                self.image_canvas.winfo_width(),
                self.image_canvas.winfo_height(),
                self._cursor_drag_plane_z,
            )
            if point is None:
                return
            runtime = self.simulation.runtime(self._cursor_drag_entity_id)
            transform = copy.deepcopy(runtime.spec.transform)
            next_x = max(
                -20.0, min(20.0, point[0] + self._cursor_drag_offset[0])
            )
            next_y = max(
                -20.0, min(20.0, point[1] + self._cursor_drag_offset[1])
            )
            if (
                abs(next_x - transform.x) < 1e-7
                and abs(next_y - transform.y) < 1e-7
            ):
                return
            transform.x = next_x
            transform.y = next_y
            self.simulation.set_entity_transform(
                self._cursor_drag_entity_id, transform
            )
            self.layout_editor.update_entity(runtime.spec)
            self._sync_properties(runtime.spec)
            self._cursor_drag_changed = True
            self._request_render()
            return
        if self._camera_drag_last is None or self.view_var.get() != "World":
            return
        last_x, last_y = self._camera_drag_last
        delta_x = event.x - last_x
        delta_y = event.y - last_y
        self._camera_drag_last = (event.x, event.y)
        if self._camera_drag_mode == "pan":
            self.simulation.pan_camera(delta_x, delta_y)
        else:
            self.simulation.orbit_camera(delta_x, delta_y)
        self._sync_camera_vars()
        self._request_render()

    def _camera_release(self, _event: tk.Event) -> None:
        if self._cursor_drag_entity_id is not None:
            entity_id = self._cursor_drag_entity_id
            name = self.simulation.runtime(entity_id).spec.name
            self._cursor_drag_entity_id = None
            self.simulation.camera_auto_center = self._cursor_drag_auto_center
            if self._cursor_drag_auto_center:
                self._fit_camera_to_viewer()
            self.layout_editor.set_entities(self.simulation.entity_specs())
            self.layout_editor.set_selection(entity_id)
            if self._cursor_drag_changed:
                self._commit_scene_edit(f"Moved {name}")
            else:
                self._pending_edit_before = None
            self._cursor_drag_changed = False
            self._request_render()
        self._camera_drag_last = None

    def _camera_wheel(self, event: tk.Event) -> str:
        if self.view_var.get() != "World" or event.delta == 0:
            return "break"
        self.simulation.zoom_camera(1.0 if event.delta > 0 else -1.0)
        self._sync_camera_vars()
        self._request_render()
        return "break"

    def _sync_camera_vars(self) -> None:
        yaw = (self.simulation.camera_yaw + 180.0) % 360.0 - 180.0
        self.camera_vars["yaw"].set(yaw)
        self.camera_vars["pitch"].set(self.simulation.camera_pitch)
        self.camera_vars["distance"].set(self.simulation.camera_distance)

    def _camera_scale_changed(self, key: str) -> None:
        if key == "yaw":
            self.simulation.camera_yaw = self.camera_vars[key].get()
        elif key == "pitch":
            self.simulation.camera_pitch = self.camera_vars[key].get()
        else:
            self.simulation.camera_distance = self.camera_vars[key].get()
        self._request_render()

    def _focus_selected(self, _event: tk.Event | None = None) -> None:
        if self.selected_entity_id is None:
            return
        self.simulation.focus_entity(self.selected_entity_id)
        self._request_render()
        self.status_var.set(
            f"Focused {self.simulation.runtime(self.selected_entity_id).spec.name}"
        )

    def _reset_camera(self) -> None:
        self.simulation.reset_camera()
        self._fit_camera_to_viewer()
        self._request_render()
        self.status_var.set("Camera reset")

    def save_scene(self) -> None:
        SCENE_DIR.mkdir(parents=True, exist_ok=True)
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save scene",
            initialdir=(
                self.current_scene_path.parent
                if self.current_scene_path
                else SCENE_DIR
            ),
            initialfile=(
                self.current_scene_path.name
                if self.current_scene_path
                else "pycubsim2_scene.json"
            ),
            defaultextension=".json",
            filetypes=(("PyCubSim2 scene", "*.json"),),
        )
        if not destination:
            return
        try:
            self.simulation.save_scene(destination)
            self.current_scene_path = Path(destination)
            self.status_var.set(f"Saved {Path(destination).name}")
        except Exception as exc:
            messagebox.showerror("Could not save scene", str(exc), parent=self.root)

    def open_scene(self) -> None:
        SCENE_DIR.mkdir(parents=True, exist_ok=True)
        source = filedialog.askopenfilename(
            parent=self.root,
            title="Open scene",
            initialdir=SCENE_DIR,
            filetypes=(("PyCubSim2 scene", "*.json"),),
        )
        if not source:
            return
        self._begin_scene_edit()
        try:
            self.webcam.close()
            self.simulation.load_scene(source)
            self.current_scene_path = Path(source)
            self._refresh_entity_tree()
            self._refresh_camera_sources()
            self.layout_editor.set_entities(self.simulation.entity_specs())
            self._fit_camera_to_viewer()
            self._request_render()
            self._commit_scene_edit(f"Opened {Path(source).name}")
        except Exception as exc:
            self._pending_edit_before = None
            messagebox.showerror("Could not open scene", str(exc), parent=self.root)

    def reset_scene(self) -> None:
        if not messagebox.askyesno(
            "Reset scene",
            "Restore the default PyCub and table scene?",
            parent=self.root,
        ):
            return
        self._begin_scene_edit()
        self.webcam.close()
        self.simulation.reset_default_scene()
        self.current_scene_path = None
        self._refresh_entity_tree(select_id="pycub_1")
        self._refresh_camera_sources()
        self.layout_editor.set_entities(self.simulation.entity_specs())
        self.layout_editor.set_selection("pycub_1")
        self._fit_camera_to_viewer()
        self._request_render()
        self._commit_scene_edit("Default scene restored")

    def _tick(self) -> None:
        started = time.perf_counter()
        wall_dt = min(0.12, max(0.0, started - self._last_tick_s))
        self._last_tick_s = started
        if self.running:
            try:
                self._physics_accumulator_s = min(
                    0.12, self._physics_accumulator_s + wall_dt
                )
                physics_hz = self.simulation.config.physics_hz
                physics_steps = min(
                    round(physics_hz * 0.12),
                    int(self._physics_accumulator_s * physics_hz),
                )
                if physics_steps > 0:
                    self.simulation.step(physics_steps)
                    self._physics_accumulator_s -= physics_steps / physics_hz
            except Exception as exc:
                self.running = False
                self.run_button_var.set("Run")
                self.status_var.set(f"Simulation error: {exc}")
        else:
            self._physics_accumulator_s = 0.0
        now = time.perf_counter()
        render_due = (
            self._continuous_render_required()
            and now - self._last_render_s >= 1.0 / self._render_fps()
        )
        if self._render_dirty or render_due:
            self._render_frame()
            self._last_render_s = time.perf_counter()
        scene_active = self.simulation.has_active_updates()
        telemetry_interval = 0.25 if scene_active else 1.0
        if now - self._last_telemetry_s >= telemetry_interval:
            self.time_var.set(f"{self.simulation.elapsed_s:.2f} s")
            if self.notebook.select() == str(self.sensors_tab):
                self._refresh_telemetry()
            if (
                self.notebook.select() == str(self.actions_tab)
                and self.selected_entity_id in self.simulation.entities
            ):
                runtime = self.simulation.runtime(self.selected_entity_id)
                if runtime.controller_host is not None:
                    state = "running" if runtime.controller_host.running else "stopped"
                    error = (
                        f" | {runtime.controller_host.error}"
                        if runtime.controller_host.error
                        else ""
                    )
                    self.controller_status_var.set(
                        f"External controller: {state}{error}"
                    )
            self._last_telemetry_s = now
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        interactive_updates = (
            self._continuous_render_required() or self._camera_drag_last is not None
        )
        target_tick_ms = 16.0 if interactive_updates else 80.0
        delay = max(2, round(target_tick_ms - elapsed_ms))
        self._tick_after_id = self.root.after(delay, self._tick)

    def close(self) -> None:
        if self._tick_after_id is not None:
            self.root.after_cancel(self._tick_after_id)
            self._tick_after_id = None
        if self._camera_fit_after_id is not None:
            self.root.after_cancel(self._camera_fit_after_id)
            self._camera_fit_after_id = None
        self.webcam.close()
        if self._owns_simulation:
            self.simulation.close()
        self.root.destroy()


def launch(scene: SceneConfig | None = None) -> None:
    root = tk.Tk()
    simulation = PyCubSim2Simulation(scene)
    app = PyCubSim2App(root, simulation=simulation)
    app._owns_simulation = True
    root.mainloop()
