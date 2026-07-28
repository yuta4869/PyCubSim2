from __future__ import annotations

import math


class Controller:
    def __init__(self) -> None:
        self.elapsed = 0.0
        self.origin = (0.0, 0.0, 0.05)

    def on_start(self, api) -> None:
        self.elapsed = 0.0
        self.origin = tuple(api.get_pose()["position"])

    def update(self, api, dt_s, sensors):
        self.elapsed += dt_s
        bob = 0.025 * (1.0 + math.sin(self.elapsed * 2.2))
        yaw = math.degrees(self.elapsed * 0.35) % 360.0
        return {
            "base_position": (
                self.origin[0],
                self.origin[1],
                self.origin[2] + bob,
            ),
            "base_rpy_deg": (0.0, 0.0, yaw),
            "joint_positions_deg": {
                "head_yaw": 42.0 * math.sin(self.elapsed * 1.4)
            },
        }

    def on_stop(self, api) -> None:
        api.set_pose(self.origin, (0.0, 0.0, 0.0))
