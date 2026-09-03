from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from experiments.pain_self_other.dataset import (
    fit_normalization,
    resample_episode,
    split_episodes,
    validate_episode,
)
from experiments.pain_self_other.dmbn import (
    DMBN,
    DMBNConfig,
    Tensor,
    backward,
    reconstruction_loss,
)
from experiments.pain_self_other.evaluate import harm_readout
from experiments.pain_self_other.simulation import EpisodeConfig, run_episode


class PhysicalPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.raw = cls.root / "raw"
        cls.processed = cls.root / "processed"
        configs = [
            EpisodeConfig("contact_1", 101, speed="fast"),
            EpisodeConfig("contact_2", 102, speed="fast"),
            EpisodeConfig("contact_3", 103, speed="fast"),
            EpisodeConfig("no_contact", 104, speed="fast", no_contact=True),
            EpisodeConfig("other_rigid", 105, speed="fast", role="other"),
            EpisodeConfig(
                "other_compliant",
                105,
                speed="fast",
                role="other",
                body_condition="compliant",
            ),
            EpisodeConfig(
                "other_stopped",
                105,
                speed="fast",
                role="other",
                stop_probe_at_s=0.7,
            ),
        ]
        cls.metadata = {config.episode_id: run_episode(config, cls.raw) for config in configs}
        run_episode(configs[0], cls.root / "repeat")
        for config in configs:
            resample_episode(cls.raw / config.episode_id, cls.processed)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_contact_logger_and_link_specific_contact(self) -> None:
        with np.load(self.raw / "contact_1" / "trajectory.npz", allow_pickle=False) as data:
            self.assertGreater(float(data["contact_force"].max()), 0.0)
            active = data["contact_normal_force"] > 0.0
            self.assertTrue(np.any(data["contact_link_id_a"][active] >= 0))
            self.assertTrue(np.any(np.linalg.norm(data["contact_position_on_a"][active], axis=1) > 0.0))
            self.assertTrue(np.any(np.abs(data["contact_relative_normal_velocity"][active]) > 0.0))

    def test_no_contact_is_zero_and_controlled_contact_is_nonzero(self) -> None:
        self.assertEqual(self.metadata["no_contact"]["summary"]["peak_contact_force_n"], 0.0)
        self.assertGreater(self.metadata["contact_1"]["summary"]["peak_contact_force_n"], 1.0)

    def test_episode_is_deterministic(self) -> None:
        for filename in ("trajectory.npz", "rgb.npz"):
            with np.load(self.raw / "contact_1" / filename, allow_pickle=False) as first:
                with np.load(self.root / "repeat" / "contact_1" / filename, allow_pickle=False) as second:
                    self.assertEqual(first.files, second.files)
                    for name in first.files:
                        np.testing.assert_array_equal(first[name], second[name])

    def test_multi_pycub_and_dissociation_condition_generation(self) -> None:
        rigid = self.metadata["other_rigid"]
        compliant = self.metadata["other_compliant"]
        self.assertNotEqual(rigid["subject_entity_id"], rigid["observer_entity_id"])
        self.assertGreater(rigid["summary"]["peak_contact_force_n"], 1.0)
        self.assertLess(
            compliant["summary"]["peak_contact_force_n"],
            0.5 * rigid["summary"]["peak_contact_force_n"],
        )
        self.assertEqual(
            self.metadata["other_stopped"]["summary"]["peak_contact_force_n"], 0.0
        )
        with np.load(self.raw / "other_rigid" / "rgb.npz", allow_pickle=False) as data:
            self.assertEqual(data["rgb"].shape, (60, 128, 128, 3))
            self.assertGreater(float(data["rgb"].std()), 10.0)

    def test_sensor_synchronization_schema_and_dimensions(self) -> None:
        self.assertEqual(validate_episode(self.raw / "contact_1"), [])
        self.assertEqual(validate_episode(self.processed / "contact_1", processed=True), [])
        with np.load(self.raw / "contact_1" / "trajectory.npz", allow_pickle=False) as raw:
            self.assertEqual(len(raw["time_s"]), 480)
            self.assertTrue(np.all(np.diff(raw["time_s"]) > 0.0))
        with np.load(self.processed / "contact_1" / "episode.npz", allow_pickle=False) as data:
            self.assertEqual(data["X"].shape, (60, 16, 16, 3))
            self.assertEqual(data["T"].shape, (60, 10))
            self.assertEqual(data["P"].shape, (60, 14))
            self.assertEqual(data["I"].shape, (60, 16))
            np.testing.assert_allclose(data["time_normalized"][[0, -1]], (0.0, 1.0))

    def test_episode_level_split_and_train_only_normalization(self) -> None:
        manifest = self.root / "manifest.csv"
        rows = split_episodes(self.processed, manifest, seed=9)
        self.assertEqual(len({row["episode_id"] for row in rows}), len(rows))
        contact_rows = [row for row in rows if row["episode_id"].startswith("contact_")]
        self.assertEqual({row["split"] for row in contact_rows}, {"train", "validation", "test"})
        normalization = fit_normalization(rows, self.root / "normalization.json")
        train_paths = [Path(row["path"]) for row in rows if row["split"] == "train"]
        expected = []
        for path in train_paths:
            with np.load(path / "episode.npz", allow_pickle=False) as data:
                expected.append(data["P"])
        np.testing.assert_allclose(
            normalization["P"]["mean"],
            np.concatenate(expected).astype(np.float64).mean(axis=0),
        )

    def test_dissociation_seed_groups_do_not_cross_splits(self) -> None:
        root = self.root / "paired_processed"
        for seed in range(5):
            for condition in ("matched_high", "self_low_other_high"):
                for role in ("self", "other"):
                    episode = root / f"{seed}_{condition}_{role}"
                    episode.mkdir(parents=True)
                    (episode / "metadata.json").write_text(
                        json.dumps(
                            {
                                "episode_id": episode.name,
                                "seed": seed,
                                "role": role,
                                "speed": "fast",
                                "posture": "neutral",
                                "contact_location": "hand",
                                "body_condition": "rigid",
                                "self_body_condition": "rigid",
                                "dissociation_condition": condition,
                                "pair_id": f"{seed}_{condition}",
                                "no_contact": False,
                            }
                        )
                    )
        rows = split_episodes(root, self.root / "paired.csv", seed=2)
        by_seed = {}
        for row in rows:
            by_seed.setdefault(row["seed"], set()).add(row["split"])
        self.assertTrue(all(len(splits) == 1 for splits in by_seed.values()))


class DMBNSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = DMBN(
            DMBNConfig(
                dimensions={"X": 3, "T": 2, "P": 2, "I": 2},
                latent_size=5,
                hidden_size=7,
                trunk_size=8,
                seed=3,
            )
        )
        times = np.linspace(0.0, 1.0, 11)
        self.episode = {
            "time_normalized": times,
            "X": np.column_stack((times, times**2, np.sin(times))),
            "T": np.column_stack((times > 0.5, times)),
            "P": np.column_stack((np.cos(times), times**2)),
            "I": np.column_stack((times**3, np.sin(2.0 * times))),
        }

    def _context(self, modality: str, indices: tuple[int, ...]) -> np.ndarray:
        return np.column_stack(
            (self.episode["time_normalized"][list(indices)], self.episode[modality][list(indices)])
        )

    def test_arbitrary_past_and_future_query(self) -> None:
        contexts = {"X": self._context("X", (5, 7))}
        prediction = self.model.predict(contexts, ("X",), np.asarray((0.1, 0.9)))
        self.assertEqual(prediction["P"]["mean"].shape, (2, 2))
        self.assertTrue(np.all(prediction["P"]["scale"] > 0.0))

    def test_missing_modalities_and_four_modality_shapes(self) -> None:
        for modality in self.model.modalities:
            contexts = {modality: self._context(modality, (1, 4, 8))}
            prediction = self.model.predict(contexts, (modality,), np.linspace(0.0, 1.0, 6))
            self.assertEqual(set(prediction), set(self.model.modalities))
            for target, dimension in self.model.config.dimensions.items():
                self.assertEqual(prediction[target]["mean"].shape, (6, dimension))

    def test_aggregation_is_order_invariant(self) -> None:
        context = self._context("P", (1, 4, 8))
        first = self.model.predict({"P": context}, ("P",), np.asarray((0.3,)))
        second = self.model.predict({"P": context[::-1]}, ("P",), np.asarray((0.3,)))
        for modality in self.model.modalities:
            np.testing.assert_allclose(first[modality]["mean"], second[modality]["mean"])

    def test_availability_weighting_and_zero_weight(self) -> None:
        coefficients = self.model.coefficients(
            ("X", "P"), reliability={"X": 0.0, "P": 1.0}
        )
        self.assertEqual(coefficients["X"], 0.0)
        self.assertAlmostEqual(sum(coefficients.values()), 1.0)
        p_only = self.model.predict(
            {"P": self._context("P", (2, 6))}, ("P",), np.asarray((0.4,))
        )
        mixed = self.model.predict(
            {"X": self._context("X", (0, 10)), "P": self._context("P", (2, 6))},
            ("X", "P"),
            np.asarray((0.4,)),
            reliability={"X": 0.0, "P": 1.0},
        )
        np.testing.assert_allclose(p_only["I"]["mean"], mixed["I"]["mean"])

    def test_multiple_queries_are_independent_not_autoregressive(self) -> None:
        contexts = {"X": self._context("X", (1, 3))}
        together = self.model.predict(contexts, ("X",), np.asarray((0.2, 0.6, 0.9)))
        for index, time in enumerate((0.2, 0.6, 0.9)):
            alone = self.model.predict(contexts, ("X",), np.asarray((time,)))
            np.testing.assert_allclose(together["T"]["mean"][[index]], alone["T"]["mean"])

    def test_gradient_reaches_available_encoders_and_all_decoders(self) -> None:
        contexts = {
            modality: self._context(modality, (1, 4)) for modality in self.model.modalities
        }
        outputs = self.model.forward(
            contexts,
            self.model.coefficients(self.model.modalities),
            np.asarray((0.5,)),
        )
        targets = {modality: self.episode[modality][[5]] for modality in self.model.modalities}
        loss, _ = reconstruction_loss(outputs, targets, self.model.config)
        backward(loss)
        for encoder in self.model.encoders.values():
            self.assertGreater(float(np.abs(encoder.weights[0].grad).sum()), 0.0)
        for decoder in self.model.decoders.values():
            self.assertGreater(float(np.abs(decoder.weights[-1].grad).sum()), 0.0)

    def test_encoder_gradient_survives_negative_hidden_activations(self) -> None:
        encoder = self.model.encoders["X"]
        encoder.biases[0].data.fill(-100.0)
        output = encoder(Tensor(self._context("X", (1, 4, 8)))).square().mean()
        backward(output)
        self.assertGreater(float(np.abs(encoder.weights[0].grad).sum()), 0.0)

    def test_autodiff_matches_finite_difference(self) -> None:
        values = Tensor([[0.4, -0.2]])
        weight = Tensor([[0.3], [-0.7]], requires_grad=True)
        loss = (values @ weight).square().mean()
        backward(loss)
        epsilon = 1e-6
        original = weight.data[0, 0]
        weight.data[0, 0] = original + epsilon
        high = ((values.data @ weight.data) ** 2).item()
        weight.data[0, 0] = original - epsilon
        low = ((values.data @ weight.data) ** 2).item()
        weight.data[0, 0] = original
        self.assertAlmostEqual(float(weight.grad[0, 0]), (high - low) / (2 * epsilon), places=7)


class ProtectionTests(unittest.TestCase):
    def test_other_protection_decision_uses_predicted_other_components(self) -> None:
        scale = {
            "peak_contact_force_n": 10.0,
            "contact_impulse_ns": 2.0,
            "peak_joint_torque_nm": 4.0,
            "accumulated_torque_load_nms": 12.0,
        }
        low_t, low_i = np.zeros((5, 10)), np.zeros((5, 16))
        high_t, high_i = low_t.copy(), low_i.copy()
        high_t[:, 1], high_t[-1, 3] = 12.0, 2.4
        high_i[:, 0], high_i[-1, 14] = 5.0, 15.0
        self.assertFalse(harm_readout(low_t, low_i, scale)["intervene"])
        self.assertTrue(harm_readout(high_t, high_i, scale)["intervene"])


if __name__ == "__main__":
    unittest.main()
