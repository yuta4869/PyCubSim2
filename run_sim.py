#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extensible PyCubSim2 environment")
    parser.add_argument("--scene", type=Path, help="Open a saved scene JSON.")
    parser.add_argument(
        "--headless", action="store_true", help="Run without opening the GUI."
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=240,
        help="Physics steps used by a headless run.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/headless_preview.png"),
        help="Headless preview image path.",
    )
    parser.add_argument(
        "--agent",
        type=Path,
        help="Import an agent manifest before a headless run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from pycubsim2.config import SceneConfig

    scene = SceneConfig.load(args.scene) if args.scene else None
    if not args.headless:
        from pycubsim2.gui import launch

        launch(scene)
        return

    from PIL import Image

    from pycubsim2.simulation import PyCubSim2Simulation

    simulation = PyCubSim2Simulation(scene)
    try:
        agent_id = simulation.import_agent(args.agent) if args.agent else None
        if agent_id is not None:
            simulation.start_controller(agent_id)
        for _ in range(max(0, args.steps)):
            simulation.step(1)
        frame = simulation.render(1280, 800, "World", shadows=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(frame).save(args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "elapsed_s": simulation.elapsed_s,
                    "entities": [
                        {
                            "id": runtime.spec.entity_id,
                            "name": runtime.spec.name,
                            "kind": runtime.spec.kind,
                            "bodies": runtime.body_ids,
                            "joints": len(runtime.joints),
                        }
                        for runtime in simulation.entities.values()
                    ],
                },
                indent=2,
            )
        )
    finally:
        simulation.close()


if __name__ == "__main__":
    main()
