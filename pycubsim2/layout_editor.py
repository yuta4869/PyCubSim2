from __future__ import annotations

import copy
import math
import tkinter as tk
from collections.abc import Callable

from .config import EntitySpec, Transform, normalized_angle


ENTITY_COLORS = {
    "pycub": "#1677ba",
    "table": "#a96832",
    "primitive": "#d34f3f",
    "model": "#586d79",
    "agent": "#188768",
}


class SceneMapEditor(tk.Canvas):
    """Top-down editor for arbitrary PyCubSim2 scene entities."""

    def __init__(
        self,
        master: tk.Misc,
        entities: list[EntitySpec],
        on_change: Callable[[EntitySpec, bool], None],
        on_select: Callable[[str], None] | None = None,
        on_edit_begin: Callable[[], None] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            master,
            background="#f2f4f1",
            highlightthickness=1,
            highlightbackground="#c8ceca",
            cursor="crosshair",
            **kwargs,
        )
        self.on_change = on_change
        self.on_select = on_select
        self.on_edit_begin = on_edit_begin
        self.entities: dict[str, EntitySpec] = {}
        self.selection: str | None = None
        self.world_center = (0.0, 0.0)
        self.world_half_span = 1.5
        self._drag_mode: str | None = None
        self._drag_offset = (0.0, 0.0)
        self.set_entities(entities)

        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)

    def set_entities(self, entities: list[EntitySpec]) -> None:
        self.entities = {
            spec.entity_id: copy.deepcopy(spec) for spec in entities
        }
        if self.selection not in self.entities:
            self.selection = next(iter(self.entities), None)
        self._fit_world()
        self.redraw()

    def set_selection(self, entity_id: str | None) -> None:
        if entity_id is not None and entity_id not in self.entities:
            return
        self.selection = entity_id
        self.redraw()

    def update_entity(self, spec: EntitySpec, *, fit: bool = False) -> None:
        if spec.entity_id not in self.entities:
            return
        self.entities[spec.entity_id] = copy.deepcopy(spec)
        if fit:
            self._fit_world()
        self.redraw()

    def _footprint(self, spec: EntitySpec) -> tuple[float, float]:
        if spec.kind == "table" or spec.kind == "primitive":
            return max(0.08, spec.size[0]), max(0.08, spec.size[1])
        if spec.kind == "pycub":
            diameter = max(0.34, 0.34 * spec.scale)
            return diameter, diameter
        diameter = max(0.24, 0.32 * spec.scale)
        return diameter, diameter

    def _fit_world(self) -> None:
        if not self.entities:
            self.world_center = (0.0, 0.0)
            self.world_half_span = 1.5
            return
        lower_x = math.inf
        lower_y = math.inf
        upper_x = -math.inf
        upper_y = -math.inf
        for spec in self.entities.values():
            width, depth = self._footprint(spec)
            radius = math.hypot(width, depth) / 2.0
            lower_x = min(lower_x, spec.transform.x - radius)
            upper_x = max(upper_x, spec.transform.x + radius)
            lower_y = min(lower_y, spec.transform.y - radius)
            upper_y = max(upper_y, spec.transform.y + radius)
        self.world_center = (
            (lower_x + upper_x) / 2.0,
            (lower_y + upper_y) / 2.0,
        )
        self.world_half_span = max(
            1.25,
            (upper_x - lower_x) / 2.0 + 0.4,
            (upper_y - lower_y) / 2.0 + 0.4,
        )

    def _geometry(self) -> tuple[float, float, float]:
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        padding = 25.0
        scale = min(
            (width - padding * 2.0) / (self.world_half_span * 2.0),
            (height - padding * 2.0) / (self.world_half_span * 2.0),
        )
        return width / 2.0, height / 2.0, max(1.0, scale)

    def world_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        origin_x, origin_y, scale = self._geometry()
        return (
            origin_x + (x - self.world_center[0]) * scale,
            origin_y - (y - self.world_center[1]) * scale,
        )

    def canvas_to_world(self, x: float, y: float) -> tuple[float, float]:
        origin_x, origin_y, scale = self._geometry()
        return (
            self.world_center[0] + (x - origin_x) / scale,
            self.world_center[1] + (origin_y - y) / scale,
        )

    @staticmethod
    def _rotated_point(
        center_x: float,
        center_y: float,
        local_x: float,
        local_y: float,
        yaw_deg: float,
    ) -> tuple[float, float]:
        yaw = math.radians(yaw_deg)
        cosine = math.cos(yaw)
        sine = math.sin(yaw)
        return (
            center_x + local_x * cosine - local_y * sine,
            center_y + local_x * sine + local_y * cosine,
        )

    def _polygon(self, spec: EntitySpec) -> list[float]:
        width, depth = self._footprint(spec)
        points: list[float] = []
        for local_x, local_y in (
            (-width / 2.0, -depth / 2.0),
            (width / 2.0, -depth / 2.0),
            (width / 2.0, depth / 2.0),
            (-width / 2.0, depth / 2.0),
        ):
            world_point = self._rotated_point(
                spec.transform.x,
                spec.transform.y,
                local_x,
                local_y,
                spec.transform.yaw_deg,
            )
            points.extend(self.world_to_canvas(*world_point))
        return points

    def redraw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        _, _, scale = self._geometry()
        center_x, center_y = self.world_center

        step = 0.5
        first_x = math.floor((center_x - self.world_half_span) / step)
        last_x = math.ceil((center_x + self.world_half_span) / step)
        first_y = math.floor((center_y - self.world_half_span) / step)
        last_y = math.ceil((center_y + self.world_half_span) / step)
        for index in range(first_x, last_x + 1):
            value = index * step
            x1, y1 = self.world_to_canvas(
                value, center_y - self.world_half_span
            )
            x2, y2 = self.world_to_canvas(
                value, center_y + self.world_half_span
            )
            axis = math.isclose(value, 0.0)
            self.create_line(
                x1,
                y1,
                x2,
                y2,
                fill="#aab4ae" if axis else "#dde2de",
                width=2 if axis else 1,
            )
        for index in range(first_y, last_y + 1):
            value = index * step
            x1, y1 = self.world_to_canvas(
                center_x - self.world_half_span, value
            )
            x2, y2 = self.world_to_canvas(
                center_x + self.world_half_span, value
            )
            axis = math.isclose(value, 0.0)
            self.create_line(
                x1,
                y1,
                x2,
                y2,
                fill="#aab4ae" if axis else "#dde2de",
                width=2 if axis else 1,
            )

        for spec in self.entities.values():
            selected = spec.entity_id == self.selection
            color = ENTITY_COLORS.get(spec.kind, "#66736d")
            center = self.world_to_canvas(
                spec.transform.x, spec.transform.y
            )
            width_m, depth_m = self._footprint(spec)
            if spec.kind == "pycub" or (
                spec.kind == "primitive"
                and spec.primitive_shape in {"sphere", "cylinder"}
            ):
                radius_x = max(10.0, width_m * scale / 2.0)
                radius_y = max(10.0, depth_m * scale / 2.0)
                self.create_oval(
                    center[0] - radius_x,
                    center[1] - radius_y,
                    center[0] + radius_x,
                    center[1] + radius_y,
                    fill=color,
                    outline="#0d5947" if selected else "#ffffff",
                    width=3 if selected else 2,
                )
            else:
                self.create_polygon(
                    self._polygon(spec),
                    fill=color,
                    outline="#0d5947" if selected else "#ffffff",
                    width=3 if selected else 2,
                    joinstyle=tk.ROUND,
                )

            label = "P" if spec.kind == "pycub" else spec.name[:9]
            self.create_text(
                center[0],
                center[1],
                text=label,
                fill="#ffffff",
                font=("TkDefaultFont", 9, "bold"),
            )
            yaw = math.radians(spec.transform.yaw_deg)
            handle_distance = max(0.30, max(width_m, depth_m) * 0.7)
            handle = self.world_to_canvas(
                spec.transform.x + math.cos(yaw) * handle_distance,
                spec.transform.y + math.sin(yaw) * handle_distance,
            )
            self.create_line(
                center[0],
                center[1],
                handle[0],
                handle[1],
                fill=color,
                width=3,
                arrow=tk.LAST,
                arrowshape=(9, 11, 4),
            )
            if selected:
                self.create_oval(
                    handle[0] - 5,
                    handle[1] - 5,
                    handle[0] + 5,
                    handle[1] + 5,
                    fill="#ffffff",
                    outline=color,
                    width=2,
                )

        self.create_text(
            12,
            10,
            anchor="nw",
            text="+X right   +Y up",
            fill="#59635e",
            font=("TkDefaultFont", 9, "bold"),
        )
        self.create_rectangle(
            0,
            0,
            width - 1,
            height - 1,
            outline="#c8ceca",
            width=1,
        )

    def _heading_hit(
        self, spec: EntitySpec, canvas_x: float, canvas_y: float
    ) -> bool:
        width, depth = self._footprint(spec)
        yaw = math.radians(spec.transform.yaw_deg)
        distance = max(0.30, max(width, depth) * 0.7)
        handle = self.world_to_canvas(
            spec.transform.x + math.cos(yaw) * distance,
            spec.transform.y + math.sin(yaw) * distance,
        )
        return math.hypot(canvas_x - handle[0], canvas_y - handle[1]) <= 12.0

    def _entity_hit(self, world_x: float, world_y: float) -> str | None:
        for spec in reversed(tuple(self.entities.values())):
            delta_x = world_x - spec.transform.x
            delta_y = world_y - spec.transform.y
            yaw = math.radians(-spec.transform.yaw_deg)
            local_x = delta_x * math.cos(yaw) - delta_y * math.sin(yaw)
            local_y = delta_x * math.sin(yaw) + delta_y * math.cos(yaw)
            width, depth = self._footprint(spec)
            if spec.kind == "pycub" or (
                spec.kind == "primitive"
                and spec.primitive_shape in {"sphere", "cylinder"}
            ):
                normalized = (
                    (local_x / max(0.04, width / 2.0)) ** 2
                    + (local_y / max(0.04, depth / 2.0)) ** 2
                )
                if normalized <= 1.25:
                    return spec.entity_id
            elif (
                abs(local_x) <= width / 2.0 + 0.04
                and abs(local_y) <= depth / 2.0 + 0.04
            ):
                return spec.entity_id
        return None

    def _begin_edit(self) -> None:
        if self.on_edit_begin is not None:
            self.on_edit_begin()

    def _select(self, entity_id: str) -> None:
        self.selection = entity_id
        if self.on_select is not None:
            self.on_select(entity_id)

    def _on_press(self, event: tk.Event) -> None:
        world_x, world_y = self.canvas_to_world(event.x, event.y)
        if self.selection is not None:
            selected = self.entities[self.selection]
            if self._heading_hit(selected, event.x, event.y):
                self._begin_edit()
                self._drag_mode = f"rotate:{self.selection}"
                return

        entity_id = self._entity_hit(world_x, world_y)
        if entity_id is None:
            self._drag_mode = None
            return
        self._select(entity_id)
        spec = self.entities[entity_id]
        self._drag_offset = (
            spec.transform.x - world_x,
            spec.transform.y - world_y,
        )
        self._begin_edit()
        self._drag_mode = f"move:{entity_id}"
        self.redraw()

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_mode is None:
            return
        mode, entity_id = self._drag_mode.split(":", 1)
        spec = self.entities[entity_id]
        world_x, world_y = self.canvas_to_world(event.x, event.y)
        transform = copy.deepcopy(spec.transform)
        if mode == "move":
            transform.x = max(
                -20.0, min(20.0, world_x + self._drag_offset[0])
            )
            transform.y = max(
                -20.0, min(20.0, world_y + self._drag_offset[1])
            )
        else:
            transform.yaw_deg = normalized_angle(
                math.degrees(
                    math.atan2(
                        world_y - transform.y,
                        world_x - transform.x,
                    )
                )
            )
        spec.transform = transform.validated()
        self.redraw()
        self.on_change(copy.deepcopy(spec), False)

    def _on_release(self, _event: tk.Event) -> None:
        if self._drag_mode is None:
            return
        _mode, entity_id = self._drag_mode.split(":", 1)
        self._drag_mode = None
        self.on_change(copy.deepcopy(self.entities[entity_id]), True)

    def _on_wheel(self, event: tk.Event) -> str:
        if self.selection is None or event.delta == 0:
            return "break"
        self._begin_edit()
        spec = self.entities[self.selection]
        transform = copy.deepcopy(spec.transform)
        transform.yaw_deg = normalized_angle(
            transform.yaw_deg + (5.0 if event.delta > 0 else -5.0)
        )
        spec.transform = transform.validated()
        self.redraw()
        self.on_change(copy.deepcopy(spec), True)
        return "break"
