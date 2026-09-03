# Physical Self/Other DMBN Handoff

## Repository state

- **Base**: PyCubSim2 official `main` commit `23353265cba6e32e295fbe98be98f7db8f43152e`.
- **Branch**: `research/pain-self-other-dmbn`.
- **Important commits**:
  - `0ab90a0` — Stage 1 simulator instrumentation.
  - `53a934b` — Physical Self/Other DMBN experiments, tests, and executed reports.
- **Python**: `/opt/miniconda3/envs/pycub310/bin/python` with Python 3.10, NumPy 1.26.4, PyBullet 3.25, SciPy 1.15.2, and Matplotlib 3.10.9.
- **Execution**: local CPU and headless PyBullet; no GPU was used.

## Stage status

| Stage | Status | Executed acceptance evidence |
|---|---|---|
| **0** | **DONE** | Three papers and complete official notebook inspected; audit/specification/implementation notes exist |
| **1** | **DONE** | Headless deterministic X/T/P/I, 363-episode batch, zero-force control, contact, speed/posture effects, synchronized sensors, and two-PyCub tests pass |
| **2** | **DONE** | 360-contact Full Self dataset plus 3 controls; all physics gates pass; report and figures exist |
| **3A** | **DONE** | DMBN semantics tests pass; X→P and P→X both beat mean trajectories |
| **3B** | **PARTIAL** | Vision→Touch and Touch→Vision executed; onset improves, but X→T full-trajectory MAE does not beat mean |
| **3C** | **PARTIAL** | Conditions X, XP, XPI, and P executed; XPI→T beats mean, but X-only T/I and XPI→I do not |
| **4** | **PARTIAL** | Transparent predicted-state readout and physical stop mechanism exist; predicted high trials remain below threshold |
| **5** | **DONE** | A observes B, separate Self-CF output is produced, and paired A physical reference is saved |
| **6** | **DONE** | B actual sensors and 0/5/20/100 calibration evaluations exist; non-monotonic calibration is preserved as a negative result |
| **7** | **DONE** | Four physical conditions, separate predictions, paired references, trajectory plots, Self-projection/body-shuffle/time-shift controls executed |
| **8** | **PARTIAL** | Required policy executed; Self-high/Other-low is correct, Self-low/Other-high misses intervention, so selective-protection gate fails |

## Implemented code

- `pycubsim2/simulation.py`: cylinder API correction, motor force/gain scaling, and structured link-specific contacts with physical point velocity.
- `experiments/pain_self_other/simulation.py`: deterministic 240 Hz PyBullet protocol, 30 Hz 128x128 RGB, Self/Other, rigid/compliant, and stop-probe actions.
- `experiments/pain_self_other/dataset.py`: resampling, schema validation, seed-grouped episode splits, and training-only normalization.
- `experiments/pain_self_other/dmbn.py`: modality encoders, timed observation aggregation, stochastic arithmetic blending, explicit reliability, timed independent decoders, mean/scale outputs, NumPy autodiff, checkpointing, and validation selection.
- `experiments/pain_self_other/evaluate.py`: physical and temporal metrics, mean baseline, harm readout, and required plots.
- `experiments/pain_self_other/run.py`: one CLI for generation, preparation, training, evaluation, physics, harm, dissociation, and protection.
- `tests/test_pain_self_other.py`: **16 tests** covering simulation, data, DMBN semantics/autodiff, split leakage, and protection.

## Datasets

| Dataset | Path | Episodes | Split | Disk size |
|---|---|---:|---|---:|
| **Self Mini raw** | `experiments/pain_self_other/data/raw/self_mini` | 57 | source | 8.8 MB |
| **Self Mini processed** | `experiments/pain_self_other/data/processed/self_mini` | 57 | 21 / 18 / 18 | 0.9 MB |
| **Self Full raw** | `experiments/pain_self_other/data/raw/self_full` | 363 | source | 56.8 MB |
| **Self Full processed** | `experiments/pain_self_other/data/processed/self_full` | 363 | 255 / 54 / 54 | 5.8 MB |
| **Dissociation raw** | `experiments/pain_self_other/data/raw/dissociation` | 160 | source | 31 MB |
| **Dissociation processed** | `experiments/pain_self_other/data/processed/dissociation` | 160 | 112 / 24 / 24 | 3.2 MB |

Manifests and normalization are in `experiments/pain_self_other/data/manifests`. Generated data, checkpoints, and prediction arrays are ignored by Git but retained locally.

## Checkpoints

| Experiment | Checkpoint | Train / validation | Key result |
|---|---|---:|---|
| **S3A_DMBN_XP_full** | `experiments/pain_self_other/checkpoints/S3A_DMBN_XP_full/best_model.npz` | 255 / 54 | X→P MAE 0.000815 vs mean 0.038775 |
| **S3B_DMBN_XT_full** | `experiments/pain_self_other/checkpoints/S3B_DMBN_XT_full/best_model.npz` | 255 / 54 | X→T MAE 2.944523 vs mean 2.683248 |
| **S3C_DMBN_XTPI_full** | `experiments/pain_self_other/checkpoints/S3C_DMBN_XTPI_full/best_model.npz` | 255 / 54 | XPI→T MAE 2.404786 vs mean 2.683248 |
| **S5_SELF_CF_rigid/compliant** | `experiments/pain_self_other/checkpoints/S5_SELF_CF_*` | 28 / 6 each | Separate Self body predictions |
| **S6_OTHER_*_005** | `experiments/pain_self_other/checkpoints/S6_OTHER_*_005` | 2 / 6 each | Requested 5%, realized 7.14% |
| **S6_OTHER_*_020** | `experiments/pain_self_other/checkpoints/S6_OTHER_*_020` | 6 / 6 each | Requested 20%, realized 21.43% |
| **S6_OTHER_*_100** | `experiments/pain_self_other/checkpoints/S6_OTHER_*_100` | 28 / 6 each | Body-specific Other model |

Earlier plain-ReLU, NLL-only, high-capacity, and reweighted checkpoints remain as implementation/tuning evidence but are not final models.

## Metrics and figures

- **Detailed illustrated report**: `experiments/pain_self_other/reports/DETAILED_EXPERIMENT_REPORT.md`.
- **Reproducible report figures**: `experiments/pain_self_other/reports/figures` (10 PNGs), regenerated by `python -m experiments.pain_self_other.report_figures`.
- **Full results**: `experiments/pain_self_other/reports/EXPERIMENT_RESULTS.md`.
- **Physics**: `experiments/pain_self_other/reports/STAGE2_PHYSICS_VALIDATION_FULL.md`.
- **Stage 3 predictions**: `experiments/pain_self_other/outputs/S3*`.
- **Stage 4**: `experiments/pain_self_other/outputs/S4_SELF_HARM_full_*`.
- **Stage 6 calibration**: `experiments/pain_self_other/outputs/S6_CAL_*`.
- **Stage 7 metrics/plots**: `experiments/pain_self_other/outputs/S7_DISSOCIATION_full`.
- **Stage 8 metrics/figure**: `experiments/pain_self_other/outputs/S8_OTHER_PROTECTION_full`.

## Scientific results

### Known objective facts

- **Full physical effects**: speed→impulse eta-squared 0.1820; posture→peak torque 0.5558; posture→load 0.2024; speed→peak force only 0.0091.
- **Self/Other physics**: rigid Self/Other peaks are 10.621/10.787 N; compliant Self/Other peaks are 3.053/2.765 N.
- **Dissociation**:
  - Self-high/Other-low predicts Self-CF H 0.7080 and Other H 0.2961.
  - Self-low/Other-high predicts Self-CF H 0.2963 and Other H 0.6850.
- **Other-specific vs Self-projection**: T/P/I MAE improves by 44.5%/94.5%/50.9%.
- **Shuffled body context**: T/P/I MAE worsens to 1.5440/0.04719/0.22786.

### Fact-based interpretation

The central continuous-state result distinguishes “I would be harmed” from “the Other is harmed” under paired, visually matched events. Body-specific prediction materially improves over Self projection, and shuffling the body context degrades it. Absolute T/I amplitude remains underfit, so this supports a computational Self/Other dissociation precursor rather than a strong artificial-pain or empathy claim.

## Negative results and failed gates

- X-only T/I amplitude does not beat the mean trajectory.
- Calibration fraction is not monotonically related to accuracy.
- A 0.25 normalized-time shift does not measurably degrade early-context prediction.
- Predicted high Other H is 0.685, below the fixed 0.75 action threshold.
- Stage 8 therefore does not intervene in Self-low/Other-high and does not reduce force in the executed policy run.

## Fixed implementation failures

- PyBullet cylinder visual shape requires `length`, while collision shape requires `height`.
- Plain ReLU killed all 64 image hidden units; Leaky ReLU 0.01 restored image gradients and X→P.
- NLL alone collapsed difficult predictive means into scale; executed training uses NLL + normalized mean MSE and global gradient norm 5.0.
- Dissociation duplicates initially risked split leakage; all episodes sharing a seed are now assigned to one split, with a regression test.

## Tests and environment limitation

- **Research tests**: 16/16 pass in 20.124 s.
- **Upstream non-GUI tests**: 10/10 pass in 5.286 s.
- **GUI test**: macOS Tk/AppKit aborts in the sandbox with `NSInternalInconsistencyException`; it is not reported as passed. Core headless camera, sensor, IK, controller, scene, and multi-robot tests pass.

## Exact reproduction commands

```bash
export MPLCONFIGDIR=/tmp/dmbnv3-mpl
PY=/opt/miniconda3/envs/pycub310/bin/python

$PY -m unittest -v tests.test_pain_self_other
$PY -m unittest -v tests.test_pycubsim2.ConfigTests tests.test_pycubsim2.SimulationTests

$PY -m experiments.pain_self_other.run generate --design self --repetitions 20 --output experiments/pain_self_other/data/raw/self_full --seed 20261000
$PY -m experiments.pain_self_other.run prepare --raw experiments/pain_self_other/data/raw/self_full --processed experiments/pain_self_other/data/processed/self_full --manifest experiments/pain_self_other/data/manifests/self_full.csv --normalization experiments/pain_self_other/data/manifests/self_full_normalization.json --seed 20261000
$PY -m experiments.pain_self_other.run physics-report --raw experiments/pain_self_other/data/raw/self_full --output experiments/pain_self_other/reports/STAGE2_PHYSICS_VALIDATION_FULL.md

$PY -m experiments.pain_self_other.run train --manifest experiments/pain_self_other/data/manifests/self_full.csv --normalization experiments/pain_self_other/data/manifests/self_full_normalization.json --modalities XP --role self --output experiments/pain_self_other/checkpoints/S3A_DMBN_XP_full --steps 20000 --validate-every 200 --patience 20 --seed 20260903
$PY -m experiments.pain_self_other.run train --manifest experiments/pain_self_other/data/manifests/self_full.csv --normalization experiments/pain_self_other/data/manifests/self_full_normalization.json --modalities XT --role self --output experiments/pain_self_other/checkpoints/S3B_DMBN_XT_full --steps 30000 --validate-every 200 --patience 20 --seed 20260904
$PY -m experiments.pain_self_other.run train --manifest experiments/pain_self_other/data/manifests/self_full.csv --normalization experiments/pain_self_other/data/manifests/self_full_normalization.json --modalities XTPI --role self --output experiments/pain_self_other/checkpoints/S3C_DMBN_XTPI_full --steps 40000 --validate-every 200 --patience 20 --seed 20260905

$PY -m experiments.pain_self_other.run generate --design dissociation --repetitions 20 --output experiments/pain_self_other/data/raw/dissociation --seed 20262000 --no-controls
$PY -m experiments.pain_self_other.run prepare --raw experiments/pain_self_other/data/raw/dissociation --processed experiments/pain_self_other/data/processed/dissociation --manifest experiments/pain_self_other/data/manifests/dissociation.csv --normalization experiments/pain_self_other/data/manifests/dissociation_normalization.json --seed 20262000

# Repeat for role/body/fraction combinations recorded in the checkpoint table.
$PY -m experiments.pain_self_other.run train --manifest experiments/pain_self_other/data/manifests/dissociation.csv --normalization experiments/pain_self_other/data/manifests/dissociation_normalization.json --modalities XTPI --role other --body-condition rigid --fraction 1 --output experiments/pain_self_other/checkpoints/S6_OTHER_rigid_100 --steps 15000 --validate-every 200 --patience 20 --seed 20263003

$PY -m experiments.pain_self_other.run dissociation-report --manifest experiments/pain_self_other/data/manifests/dissociation.csv --normalization experiments/pain_self_other/data/manifests/dissociation_normalization.json --self-rigid-model experiments/pain_self_other/checkpoints/S5_SELF_CF_rigid/best_model.npz --self-compliant-model experiments/pain_self_other/checkpoints/S5_SELF_CF_compliant/best_model.npz --other-rigid-model experiments/pain_self_other/checkpoints/S6_OTHER_rigid_100/best_model.npz --other-compliant-model experiments/pain_self_other/checkpoints/S6_OTHER_compliant_100/best_model.npz --output experiments/pain_self_other/outputs/S7_DISSOCIATION_full
$PY -m experiments.pain_self_other.run protection-run --manifest experiments/pain_self_other/data/manifests/dissociation.csv --metrics experiments/pain_self_other/outputs/S7_DISSOCIATION_full/metrics.json --stop-at 0.7 --output experiments/pain_self_other/outputs/S8_OTHER_PROTECTION_full
```

## Known bugs and unresolved questions

- No known schema, gradient, synchronization, split, or headless simulator bug remains after the final tests.
- T/I predictive means remain the main modeling limitation.
- The fixed action threshold is not calibrated to the model's systematic amplitude bias; it must not be changed post hoc and reported as confirmatory evidence on this dataset.
- A future confirmatory dataset should pre-register either a calibrated validation-only threshold or a conservative uncertainty-aware action rule.

## Recommended next action

**Run a fresh pre-registered confirmatory dissociation dataset after improving or calibrating T/I amplitude on validation data only.** This is the shortest scientifically valid path to test whether the continuous Self/Other separation can yield the missing Self-low/Other-high intervention without post-hoc threshold tuning.
