from __future__ import annotations

import copy
import json
import math
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import numpy as np
import pybullet as p

from pycubsim2.actions import KeyframeAction
from pycubsim2.config import SceneConfig, Transform, default_scene
from pycubsim2.plugins import AgentManifest
from pycubsim2.sensors import depth_colormap
from pycubsim2.simulation import PROJECT_ROOT, PyCubSim2Simulation


class ConfigTests(unittest.TestCase):
    def test_default_scene_and_round_trip(self) -> None:
        scene = default_scene()
        self.assertEqual([entity.kind for entity in scene.entities], ["pycub", "table"])
        self.assertEqual(scene.entities[0].name, "PyCub 1")
        self.assertEqual(scene.entities[1].name, "Table 1")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene.json"
            scene.save(path)
            loaded = SceneConfig.load(path)
        self.assertEqual(loaded.to_dict(), scene.to_dict())
        bundled = SceneConfig.load(PROJECT_ROOT / "layouts" / "default_scene.json")
        self.assertEqual(bundled.to_dict(), scene.to_dict())

    def test_action_and_agent_examples_parse(self) -> None:
        action = KeyframeAction.load(PROJECT_ROOT / "actions" / "greeting.json")
        manifest = AgentManifest.load(
            PROJECT_ROOT / "examples" / "agents" / "beacon_agent" / "agent.json"
        )
        self.assertGreater(len(action.keyframes), 1)
        self.assertEqual(manifest.name, "Beacon Agent")
        self.assertEqual(manifest.cameras[0].name, "head_camera")


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simulation = PyCubSim2Simulation()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.simulation.close()

    def setUp(self) -> None:
        self.simulation.reset_default_scene()

    def test_default_world_and_all_core_sensors(self) -> None:
        simulation = self.simulation
        self.assertEqual(set(simulation.entities), {"pycub_1", "table_1"})
        self.assertGreater(len(simulation.runtime("pycub_1").joints), 40)
        self.assertFalse(simulation.requires_physics_step())

        world = simulation.render(400, 280, "World", shadows=False)
        eye = simulation.capture_camera("pycub_1:left_eye", 240, 160)
        self.assertEqual(world.shape, (280, 400, 3))
        self.assertGreater(float(np.std(world)), 8.0)
        self.assertEqual(eye.rgb.shape, (160, 240, 3))
        self.assertTrue(np.all(np.isfinite(eye.depth_m)))
        self.assertGreater(np.unique(eye.segmentation).size, 1)

        runtime = simulation.runtime("pycub_1")
        runtime.spec.sensors.lidar = True
        snapshot = simulation.sensor_snapshot("pycub_1")
        self.assertIn("joints", snapshot)
        self.assertIn("imu", snapshot)
        self.assertIn("contact", snapshot)
        self.assertEqual(len(snapshot["lidar_m"]), 24)

    def test_multiple_pycubs_behavior_manual_ik_and_grip(self) -> None:
        simulation = self.simulation
        second = simulation.add_pycub()
        self.assertEqual(
            sum(runtime.spec.kind == "pycub" for runtime in simulation.entities.values()),
            2,
        )

        runtime = simulation.runtime(second)
        neck_joint = runtime.joints["neck_yaw"]
        before = runtime.target_positions[neck_joint]
        simulation.set_behavior(second, "Look around", running=True)
        simulation.step(180)
        after = runtime.target_positions[neck_joint]
        self.assertNotAlmostEqual(before, after, places=4)
        self.assertFalse(simulation.requires_physics_step())

        simulation.set_manual_joint_deg(second, "r_elbow", 45.0)
        self.assertFalse(runtime.behavior_running)
        self.assertAlmostEqual(
            runtime.target_positions[runtime.joints["r_elbow"]],
            math.radians(45.0),
            places=5,
        )
        simulation.set_grip(second, "r", 0.8)
        self.assertAlmostEqual(runtime.right_grip, 0.8)
        error = simulation.reach(second, "r", (-0.4, -0.2, 0.7))
        self.assertTrue(math.isfinite(error))
        self.assertFalse(runtime.behavior_running)

    def test_multi_pycub_cameras_and_scene_centered_world(self) -> None:
        simulation = self.simulation
        second = simulation.add_pycub()
        simulation.set_entity_transform(
            second,
            Transform(x=2.4, y=1.1, z=0.65, yaw_deg=-150.0),
        )
        simulation.fit_camera_to_scene(aspect=0.75)

        lower, upper = simulation.scene_bounds()
        expected_center = (lower + upper) / 2.0
        expected_center[2] = max(0.2, expected_center[2])
        np.testing.assert_allclose(
            simulation.camera_target, expected_center, atol=1e-7
        )
        for entity_id in simulation.entities:
            bounds = simulation.entity_screen_bounds(
                entity_id, "World", 300, 400
            )
            self.assertIsNotNone(bounds)
            left, top, right, bottom = bounds
            self.assertGreaterEqual(left, 0.0)
            self.assertGreaterEqual(top, 0.0)
            self.assertLessEqual(right, 300.0)
            self.assertLessEqual(bottom, 400.0)
        sources = {key for key, _label in simulation.camera_sources()}
        self.assertTrue(
            {
                f"{second}:left_eye",
                f"{second}:right_eye",
                f"{second}:body",
            }.issubset(sources)
        )
        frame = simulation.capture_camera(
            f"{second}:right_eye", width=220, height=150
        )
        self.assertEqual(frame.rgb.shape, (150, 220, 3))
        self.assertGreater(float(np.std(frame.rgb)), 4.0)
        top = simulation.render(500, 340, "Top", shadows=False)
        self.assertGreater(float(np.std(top)), 8.0)

    def test_screen_picking_plane_projection_and_metric_depth(self) -> None:
        simulation = self.simulation
        entity_id, hit = simulation.pick_entity(
            "Top", 200, 140, 400, 280
        )
        self.assertEqual(entity_id, "table_1")
        self.assertIsNotNone(hit)
        plane = simulation.screen_to_plane(
            "Top", 200, 140, 400, 280, plane_z=0.0
        )
        self.assertIsNotNone(plane)
        self.assertAlmostEqual(plane[2], 0.0, places=7)

        sensor = simulation.capture_camera(
            "pycub_1:left_eye", width=320, height=240
        )
        eye, target, _up, _fov = simulation.camera_pose(
            "pycub_1:left_eye"
        )
        direction = target - eye
        ray = p.rayTest(
            eye.tolist(),
            (eye + direction * 10.0).tolist(),
            physicsClientId=simulation.client_id,
        )[0]
        expected_depth_m = float(ray[2]) * 10.0
        self.assertAlmostEqual(
            float(sensor.depth_m[120, 160]),
            expected_depth_m,
            delta=0.06,
        )

        first = depth_colormap(
            np.asarray([[0.2, 1.0, 4.0]], dtype=np.float32)
        )
        second = depth_colormap(
            np.asarray([[0.5, 1.0, 2.0]], dtype=np.float32)
        )
        np.testing.assert_array_equal(first[0, 1], second[0, 1])

    def test_keyframe_action_and_dynamic_physics_switch(self) -> None:
        simulation = self.simulation
        action = simulation.load_action(
            "pycub_1", PROJECT_ROOT / "actions" / "table_inspection.json"
        )
        simulation.set_behavior("pycub_1", "Keyframe action", running=True)
        simulation.step(round(action.duration_s * simulation.config.physics_hz) + 8)
        self.assertFalse(simulation.runtime("pycub_1").behavior_running)

        ball = simulation.add_primitive(
            name="Dynamic ball",
            shape="sphere",
            size=(0.12, 0.12, 0.12),
            mass=0.2,
            color=(0.12, 0.52, 0.88, 1.0),
            fixed_base=False,
        )
        self.assertTrue(simulation.requires_physics_step())
        before_z = simulation.current_transform(ball).z
        simulation.step(240)
        after_z = simulation.current_transform(ball).z
        self.assertLess(after_z, before_z)
        simulation.remove_entity(ball)
        self.assertFalse(simulation.requires_physics_step())

    def test_external_model_agent_controller_and_camera(self) -> None:
        simulation = self.simulation
        agent_path = (
            PROJECT_ROOT / "examples" / "agents" / "beacon_agent" / "agent.json"
        )
        agent_id = simulation.import_agent(agent_path)
        runtime = simulation.runtime(agent_id)
        self.assertIsNotNone(runtime.controller_host)
        self.assertIn("head_yaw", runtime.joints)
        initial = simulation.current_transform(agent_id)
        simulation.start_controller(agent_id)
        simulation.step(180)
        moved = simulation.current_transform(agent_id)
        self.assertGreater(moved.z, initial.z)
        frame = simulation.capture_camera(
            f"{agent_id}:head_camera", width=200, height=140
        )
        self.assertEqual(frame.rgb.shape, (140, 200, 3))
        self.assertGreater(float(np.std(frame.rgb)), 4.0)
        simulation.stop_controller(agent_id)

        model_id = simulation.import_model(
            PROJECT_ROOT
            / "examples"
            / "agents"
            / "beacon_agent"
            / "beacon.urdf",
            name="Imported beacon model",
        )
        self.assertEqual(simulation.runtime(model_id).spec.kind, "model")

    def test_scene_save_load_preserves_added_entities(self) -> None:
        simulation = self.simulation
        second = simulation.add_pycub()
        simulation.set_entity_transform(
            second, Transform(x=0.8, y=0.4, z=0.65, yaw_deg=-145.0)
        )
        simulation.add_primitive(
            name="Marker",
            shape="box",
            size=(0.08, 0.10, 0.12),
            mass=0.0,
            color=(0.95, 0.72, 0.08, 1.0),
            fixed_base=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "saved_scene.json"
            simulation.save_scene(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            simulation.load_scene(path)
        self.assertEqual(len(data["entities"]), 4)
        self.assertEqual(len(simulation.entities), 4)
        self.assertAlmostEqual(
            simulation.runtime(second).spec.transform.x, 0.8, places=5
        )


class GuiSmokeTests(unittest.TestCase):
    def test_integrated_gui_constructs_and_selects_added_pycub(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is not available: {exc}")

        from pycubsim2.gui import PyCubSim2App

        simulation = PyCubSim2Simulation()
        app = PyCubSim2App(root, simulation)
        root.withdraw()
        try:
            app.add_pycub()
            selected = app.selected_entity_id
            self.assertIsNotNone(selected)
            self.assertEqual(simulation.runtime(selected).spec.kind, "pycub")
            app.behavior_var.set("Look around")
            app.start_action()
            simulation.step(60)
            self.assertTrue(simulation.runtime(selected).behavior_running)
            self.assertIn(
                f"{selected}:left_eye",
                {key for key, _label in simulation.camera_sources()},
            )
            self.assertIn(
                f"{selected}:right_eye",
                app.secondary_source_map.values(),
            )
            self.assertIn(
                simulation.runtime(selected).spec.name,
                " ".join(app.viewer_source_combo.cget("values")),
            )
            self.assertEqual(str(app.property_inputs["scale"].cget("state")), "normal")
            self.assertEqual(
                str(app.property_inputs["size_x"].cget("state")), "disabled"
            )
            app._select_entity("table_1")
            self.assertEqual(
                str(app.property_inputs["size_x"].cget("state")), "normal"
            )
            self.assertEqual(
                str(app.property_fixed_check.cget("state")), "disabled"
            )

            app.split_view_var.set(True)
            app._split_view_changed()
            root.update_idletasks()
            self.assertEqual(app.secondary_canvas.winfo_manager(), "grid")
            self.assertEqual(
                int(
                    app.viewer_canvas_frame.grid_columnconfigure(1)["weight"]
                ),
                1,
            )

            app._select_entity(selected)
            moved_spec = copy.deepcopy(simulation.runtime(selected).spec)
            original_x = moved_spec.transform.x
            moved_spec.transform.x += 0.35
            app._begin_scene_edit()
            app._map_entity_changed(moved_spec, final=True)
            self.assertAlmostEqual(
                simulation.runtime(selected).spec.transform.x,
                original_x + 0.35,
            )
            self.assertTrue(app._undo_stack)
            app.undo()
            self.assertAlmostEqual(
                simulation.runtime(selected).spec.transform.x,
                original_x,
            )
            app.redo()
            self.assertAlmostEqual(
                simulation.runtime(selected).spec.transform.x,
                original_x + 0.35,
            )
        finally:
            app.close()
            simulation.close()


if __name__ == "__main__":
    unittest.main()
