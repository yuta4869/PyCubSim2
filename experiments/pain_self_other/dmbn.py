"""Dependency-light DMBN preserving timed observation/query semantics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np


def _unbroadcast(gradient: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    while gradient.ndim > len(shape):
        gradient = gradient.sum(axis=0)
    for axis, size in enumerate(shape):
        if size == 1 and gradient.shape[axis] != 1:
            gradient = gradient.sum(axis=axis, keepdims=True)
    return gradient.reshape(shape)


class Tensor:
    """Small reverse-mode tensor covering the operations used by DMBN."""

    def __init__(
        self,
        data: object,
        requires_grad: bool = False,
        parents: Sequence["Tensor"] = (),
        backward: Callable | None = None,
    ) -> None:
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = requires_grad or any(parent.requires_grad for parent in parents)
        self.grad: np.ndarray | None = None
        self.parents = tuple(parents)
        self.backward_fn = backward

    @property
    def shape(self) -> tuple[int, ...]:
        return self.data.shape

    def _make(self, data: object, parents: Sequence["Tensor"], backward: Callable) -> "Tensor":
        return Tensor(data, parents=parents, backward=backward)

    def __add__(self, other: object) -> "Tensor":
        other = other if isinstance(other, Tensor) else Tensor(other)
        return self._make(
            self.data + other.data,
            (self, other),
            lambda gradient: (
                _unbroadcast(gradient, self.shape),
                _unbroadcast(gradient, other.shape),
            ),
        )

    __radd__ = __add__

    def __mul__(self, other: object) -> "Tensor":
        other = other if isinstance(other, Tensor) else Tensor(other)
        return self._make(
            self.data * other.data,
            (self, other),
            lambda gradient: (
                _unbroadcast(gradient * other.data, self.shape),
                _unbroadcast(gradient * self.data, other.shape),
            ),
        )

    __rmul__ = __mul__

    def __neg__(self) -> "Tensor":
        return self * -1.0

    def __sub__(self, other: object) -> "Tensor":
        return self + (-other if isinstance(other, Tensor) else -Tensor(other))

    def __rsub__(self, other: object) -> "Tensor":
        return (-self) + other

    def __truediv__(self, other: object) -> "Tensor":
        other = other if isinstance(other, Tensor) else Tensor(other)
        return self._make(
            self.data / other.data,
            (self, other),
            lambda gradient: (
                _unbroadcast(gradient / other.data, self.shape),
                _unbroadcast(-gradient * self.data / other.data**2, other.shape),
            ),
        )

    def __matmul__(self, other: "Tensor") -> "Tensor":
        return self._make(
            self.data @ other.data,
            (self, other),
            lambda gradient: (gradient @ other.data.T, self.data.T @ gradient),
        )

    def relu(self, negative_slope: float = 0.01) -> "Tensor":
        slope = np.where(self.data > 0.0, 1.0, negative_slope)
        return self._make(self.data * slope, (self,), lambda gradient: (gradient * slope,))

    def exp(self) -> "Tensor":
        value = np.exp(self.data)
        return self._make(value, (self,), lambda gradient: (gradient * value,))

    def square(self) -> "Tensor":
        return self._make(
            self.data**2, (self,), lambda gradient: (gradient * 2.0 * self.data,)
        )

    def log(self) -> "Tensor":
        return self._make(np.log(self.data), (self,), lambda gradient: (gradient / self.data,))

    def sum(self, axis: int | None = None, keepdims: bool = False) -> "Tensor":
        shape = self.shape

        def gradient_fn(gradient: np.ndarray) -> tuple[np.ndarray]:
            expanded = np.asarray(gradient)
            if axis is not None and not keepdims:
                expanded = np.expand_dims(expanded, axis)
            return (np.broadcast_to(expanded, shape).copy(),)

        return self._make(self.data.sum(axis=axis, keepdims=keepdims), (self,), gradient_fn)

    def mean(self, axis: int | None = None, keepdims: bool = False) -> "Tensor":
        count = self.data.size if axis is None else self.data.shape[axis]
        return self.sum(axis=axis, keepdims=keepdims) * (1.0 / count)


def concat(tensors: Sequence[Tensor], axis: int = 1) -> Tensor:
    sizes = [tensor.shape[axis] for tensor in tensors]

    def gradient_fn(gradient: np.ndarray) -> tuple[np.ndarray, ...]:
        result, start = [], 0
        for size in sizes:
            indices = [slice(None)] * gradient.ndim
            indices[axis] = slice(start, start + size)
            result.append(gradient[tuple(indices)])
            start += size
        return tuple(result)

    return Tensor(
        np.concatenate([tensor.data for tensor in tensors], axis=axis),
        parents=tensors,
        backward=gradient_fn,
    )


def _slice(tensor: Tensor, start: int, stop: int) -> Tensor:
    def gradient_fn(gradient: np.ndarray) -> tuple[np.ndarray]:
        full = np.zeros_like(tensor.data)
        full[:, start:stop] = gradient
        return (full,)

    return Tensor(tensor.data[:, start:stop], parents=(tensor,), backward=gradient_fn)


def backward(root: Tensor) -> None:
    order: list[Tensor] = []
    seen: set[int] = set()
    stack = [(root, False)]
    while stack:
        node, expanded = stack.pop()
        if expanded:
            order.append(node)
            continue
        if id(node) in seen:
            continue
        seen.add(id(node))
        stack.append((node, True))
        stack.extend((parent, False) for parent in node.parents if id(parent) not in seen)
    root.grad = np.ones_like(root.data)
    for node in reversed(order):
        if node.backward_fn is None or node.grad is None:
            continue
        for parent, gradient in zip(node.parents, node.backward_fn(node.grad)):
            if not parent.requires_grad and not parent.parents:
                continue
            parent.grad = gradient.copy() if parent.grad is None else parent.grad + gradient


class Adam:
    def __init__(
        self,
        parameters: Iterable[Tensor],
        learning_rate: float = 1e-3,
        clip_norm: float = 5.0,
    ) -> None:
        self.parameters = list(parameters)
        self.learning_rate = learning_rate
        self.clip_norm = clip_norm
        self.first = [np.zeros_like(parameter.data) for parameter in self.parameters]
        self.second = [np.zeros_like(parameter.data) for parameter in self.parameters]
        self.step_number = 0

    def zero_grad(self) -> None:
        for parameter in self.parameters:
            parameter.grad = None

    def step(self) -> None:
        self.step_number += 1
        norm = np.sqrt(
            sum(float(np.sum(parameter.grad**2)) for parameter in self.parameters if parameter.grad is not None)
        )
        scale = min(1.0, self.clip_norm / (norm + 1e-12))
        for index, parameter in enumerate(self.parameters):
            if parameter.grad is None:
                continue
            gradient = parameter.grad * scale
            self.first[index] = 0.9 * self.first[index] + 0.1 * gradient
            self.second[index] = 0.999 * self.second[index] + 0.001 * gradient**2
            first = self.first[index] / (1.0 - 0.9**self.step_number)
            second = self.second[index] / (1.0 - 0.999**self.step_number)
            parameter.data -= self.learning_rate * first / (np.sqrt(second) + 1e-8)


def _glorot(rng: np.random.Generator, fan_in: int, fan_out: int) -> np.ndarray:
    limit = np.sqrt(6.0 / (fan_in + fan_out))
    return rng.uniform(-limit, limit, size=(fan_in, fan_out))


class MLP:
    def __init__(
        self,
        rng: np.random.Generator,
        input_size: int,
        hidden_sizes: Sequence[int],
        output_size: int,
    ) -> None:
        sizes = [input_size, *hidden_sizes, output_size]
        self.weights = [
            Tensor(_glorot(rng, sizes[index], sizes[index + 1]), requires_grad=True)
            for index in range(len(sizes) - 1)
        ]
        self.biases = [
            Tensor(np.zeros((1, size)), requires_grad=True) for size in sizes[1:]
        ]

    def __call__(self, values: Tensor) -> Tensor:
        for index, (weight, bias) in enumerate(zip(self.weights, self.biases)):
            values = values @ weight + bias
            if index < len(self.weights) - 1:
                values = values.relu()
        return values

    def parameters(self) -> list[Tensor]:
        return self.weights + self.biases


@dataclass
class DMBNConfig:
    dimensions: dict[str, int]
    latent_size: int = 32
    hidden_size: int = 64
    trunk_size: int = 96
    seed: int = 20260903
    loss_weights: dict[str, float] = field(default_factory=dict)
    mean_mse_weight: float = 1.0


class DMBN:
    """Timed modality encoders -> arithmetic blend -> timed modality decoders."""

    def __init__(self, config: DMBNConfig) -> None:
        if not config.dimensions:
            raise ValueError("DMBN requires at least one modality")
        self.config = config
        self.modalities = tuple(config.dimensions)
        rng = np.random.default_rng(config.seed)
        self.encoders = {
            modality: MLP(
                rng,
                dimension + 1,
                (config.hidden_size,),
                config.latent_size,
            )
            for modality, dimension in config.dimensions.items()
        }
        self.trunk = MLP(
            rng,
            config.latent_size + 1,
            (config.trunk_size,),
            config.trunk_size,
        )
        self.decoders = {
            modality: MLP(
                rng,
                config.trunk_size,
                (config.hidden_size,),
                2 * dimension,
            )
            for modality, dimension in config.dimensions.items()
        }

    def parameters(self) -> list[Tensor]:
        parameters: list[Tensor] = []
        for encoder in self.encoders.values():
            parameters.extend(encoder.parameters())
        parameters.extend(self.trunk.parameters())
        for decoder in self.decoders.values():
            parameters.extend(decoder.parameters())
        return parameters

    def state_dict(self) -> dict[str, np.ndarray]:
        return {f"parameter_{index}": value.data.copy() for index, value in enumerate(self.parameters())}

    def load_state_dict(self, state: dict[str, np.ndarray]) -> None:
        for index, parameter in enumerate(self.parameters()):
            parameter.data = state[f"parameter_{index}"].copy()

    def parameter_count(self) -> int:
        return int(sum(parameter.data.size for parameter in self.parameters()))

    def coefficients(
        self,
        available: Sequence[str],
        *,
        reliability: dict[str, float] | None = None,
        rng: np.random.Generator | None = None,
    ) -> dict[str, float]:
        unknown = set(available) - set(self.modalities)
        if unknown:
            raise ValueError(f"Unknown modalities: {sorted(unknown)}")
        reliability = reliability or {modality: 1.0 for modality in self.modalities}
        weights = np.asarray(
            [max(0.0, float(reliability.get(modality, 1.0))) for modality in available]
        )
        if not len(weights) or weights.sum() == 0.0:
            raise ValueError("At least one modality must have positive availability")
        mixture = (
            np.ones(len(available)) / len(available)
            if rng is None
            else rng.dirichlet(np.ones(len(available)))
        )
        normalized = mixture * weights
        normalized /= normalized.sum()
        result = {modality: 0.0 for modality in self.modalities}
        result.update({modality: float(value) for modality, value in zip(available, normalized)})
        return result

    def encode_and_blend(
        self, contexts: dict[str, np.ndarray], coefficients: dict[str, float]
    ) -> Tensor:
        blended: Tensor | None = None
        for modality in self.modalities:
            coefficient = coefficients.get(modality, 0.0)
            if coefficient == 0.0:
                continue
            representations = self.encoders[modality](Tensor(contexts[modality]))
            pooled = representations.mean(axis=0, keepdims=True)
            blended = pooled * coefficient if blended is None else blended + pooled * coefficient
        if blended is None:
            raise ValueError("No available context was supplied")
        return blended

    def decode(
        self, representation: Tensor, query_times: np.ndarray
    ) -> dict[str, tuple[Tensor, Tensor]]:
        query = Tensor(np.asarray(query_times, dtype=np.float64).reshape(-1, 1))
        count = len(query.data)
        if count == 1:
            repeated = representation
        else:
            repeated = Tensor(
                np.repeat(representation.data, count, axis=0),
                parents=(representation,),
                backward=lambda gradient: (gradient.sum(axis=0, keepdims=True),),
            )
        hidden = self.trunk(concat((repeated, query), axis=1)).relu()
        result: dict[str, tuple[Tensor, Tensor]] = {}
        for modality, decoder in self.decoders.items():
            output = decoder(hidden)
            dimension = self.config.dimensions[modality]
            result[modality] = (
                _slice(output, 0, dimension),
                _slice(output, dimension, 2 * dimension),
            )
        return result

    def forward(
        self,
        contexts: dict[str, np.ndarray],
        coefficients: dict[str, float],
        query_times: np.ndarray,
    ) -> dict[str, tuple[Tensor, Tensor]]:
        return self.decode(self.encode_and_blend(contexts, coefficients), query_times)

    def predict(
        self,
        contexts: dict[str, np.ndarray],
        available: Sequence[str],
        query_times: np.ndarray,
        reliability: dict[str, float] | None = None,
    ) -> dict[str, dict[str, np.ndarray]]:
        coefficients = self.coefficients(available, reliability=reliability)
        outputs = self.forward(contexts, coefficients, query_times)
        return {
            modality: {
                "mean": mean.data.copy(),
                "scale": np.logaddexp(0.0, log_scale.data),
            }
            for modality, (mean, log_scale) in outputs.items()
        }

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            destination,
            config=np.asarray(json.dumps(asdict(self.config))),
            **self.state_dict(),
        )

    @classmethod
    def load(cls, path: str | Path) -> "DMBN":
        with np.load(path, allow_pickle=False) as loaded:
            raw = json.loads(str(loaded["config"]))
            model = cls(DMBNConfig(**raw))
            model.load_state_dict(
                {name: loaded[name] for name in loaded.files if name.startswith("parameter_")}
            )
        return model


def _softplus(value: Tensor) -> Tensor:
    data = np.logaddexp(0.0, value.data)
    derivative = np.empty_like(value.data)
    positive = value.data >= 0.0
    derivative[positive] = 1.0 / (1.0 + np.exp(-value.data[positive]))
    exp_value = np.exp(value.data[~positive])
    derivative[~positive] = exp_value / (1.0 + exp_value)
    return Tensor(data, parents=(value,), backward=lambda gradient: (gradient * derivative,))


def gaussian_nll(mean: Tensor, log_scale: Tensor, target: np.ndarray) -> Tensor:
    scale = _softplus(log_scale) + 1e-6
    residual = (Tensor(target) - mean) / scale
    return ((residual.square() + np.log(2.0 * np.pi)) * 0.5 + scale.log()).mean()


def reconstruction_loss(
    outputs: dict[str, tuple[Tensor, Tensor]],
    targets: dict[str, np.ndarray],
    config: DMBNConfig,
) -> tuple[Tensor, dict[str, float]]:
    terms = {
        modality: gaussian_nll(mean, log_scale, targets[modality])
        + (Tensor(targets[modality]) - mean).square().mean() * config.mean_mse_weight
        for modality, (mean, log_scale) in outputs.items()
    }
    weights = {
        modality: float(config.loss_weights.get(modality, 1.0))
        for modality in terms
    }
    denominator = sum(weights.values())
    total: Tensor | None = None
    for modality, term in terms.items():
        weighted = term * (weights[modality] / denominator)
        total = weighted if total is None else total + weighted
    assert total is not None
    return total, {modality: float(term.data) for modality, term in terms.items()}


def modality_subsets(modalities: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        subset
        for size in range(1, len(modalities) + 1)
        for subset in combinations(modalities, size)
    )


def _training_case(
    episode: dict[str, np.ndarray],
    model: DMBN,
    rng: np.random.Generator,
    obs_max: int,
) -> tuple[dict[str, np.ndarray], dict[str, float], np.ndarray, dict[str, np.ndarray]]:
    available = modality_subsets(model.modalities)[rng.integers(0, 2 ** len(model.modalities) - 1)]
    contexts: dict[str, np.ndarray] = {}
    length = len(episode["time_normalized"])
    for modality in available:
        count = int(rng.integers(1, min(obs_max, length - 1) + 1))
        indices = rng.choice(length, size=count, replace=False)
        contexts[modality] = np.column_stack(
            (episode["time_normalized"][indices], episode[modality][indices])
        )
    target_index = int(rng.integers(0, length))
    query = episode["time_normalized"][[target_index]]
    targets = {modality: episode[modality][[target_index]] for modality in model.modalities}
    return contexts, model.coefficients(available, rng=rng), query, targets


def validation_loss(model: DMBN, episodes: Sequence[dict[str, np.ndarray]]) -> float:
    values: list[float] = []
    first = model.modalities[0]
    for episode in episodes:
        observation_indices = np.linspace(0, len(episode[first]) // 3, 3).round().astype(int)
        contexts = {
            first: np.column_stack(
                (episode["time_normalized"][observation_indices], episode[first][observation_indices])
            )
        }
        query_indices = np.unique(
            np.append(np.arange(0, len(episode[first]), 5), len(episode[first]) - 1)
        )
        outputs = model.forward(
            contexts,
            model.coefficients((first,)),
            episode["time_normalized"][query_indices],
        )
        targets = {modality: episode[modality][query_indices] for modality in model.modalities}
        values.append(float(reconstruction_loss(outputs, targets, model.config)[0].data))
    return float(np.mean(values))


def train(
    model: DMBN,
    train_episodes: Sequence[dict[str, np.ndarray]],
    validation_episodes: Sequence[dict[str, np.ndarray]],
    output_dir: str | Path,
    *,
    steps: int = 500,
    learning_rate: float = 1e-3,
    obs_max: int = 5,
    validate_every: int = 50,
    patience: int = 6,
) -> list[dict[str, float]]:
    if not train_episodes or not validation_episodes:
        raise ValueError("training requires non-empty train and validation episodes")
    rng = np.random.default_rng(model.config.seed + 1)
    optimizer = Adam(model.parameters(), learning_rate)
    best_state = model.state_dict()
    best_validation = float("inf")
    stale = 0
    history: list[dict[str, float]] = []
    for step in range(1, steps + 1):
        episode = train_episodes[int(rng.integers(0, len(train_episodes)))]
        contexts, coefficients, query, targets = _training_case(
            episode, model, rng, obs_max
        )
        outputs = model.forward(contexts, coefficients, query)
        loss, _ = reconstruction_loss(outputs, targets, model.config)
        optimizer.zero_grad()
        backward(loss)
        optimizer.step()
        if step == 1 or step % validate_every == 0 or step == steps:
            current_validation = validation_loss(model, validation_episodes)
            history.append(
                {
                    "step": float(step),
                    "train_nll": float(loss.data),
                    "validation_nll": current_validation,
                }
            )
            if np.isfinite(current_validation) and current_validation < best_validation:
                best_validation = current_validation
                best_state = model.state_dict()
                stale = 0
            else:
                stale += 1
            if stale >= patience:
                break
    model.load_state_dict(best_state)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    model.save(destination / "best_model.npz")
    (destination / "training_history.json").write_text(
        json.dumps(history, indent=2) + "\n", encoding="utf-8"
    )
    return history
