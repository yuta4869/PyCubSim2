# PyCubSim2 Physical Self/Other DMBN Study

> We investigate whether multimodal bodily experience learned through
> Deep Modality Blending Networks can support a progression from
> prediction of one's own bodily consequences to inference of another
> agent's bodily state.
>
> A robot first learns the temporal relationship between external
> visual events, touch, proprioception, and internal mechanical state
> through its own physically simulated experience.
>
> When observing the same type of event happening to another robot,
> the learned body model is first used to generate a Self-counterfactual
> prediction: what would happen to the observer if the event occurred
> to itself.
>
> The study then tests whether this Self-based simulation can be
> corrected using information or experience about the Other's body to
> predict the Other's actual tactile, proprioceptive, and internal
> mechanical trajectory.
>
> The critical experiment deliberately creates conditions where the
> consequence for Self and Other differs, allowing us to distinguish
> simple self-projection from Other-specific bodily-state inference.

## Scientific scope

**X/T/P/I are physically measured or deterministic transforms of PyBullet measurements.** The model predicts bodily trajectories; a transparent downstream readout decides whether to stop the probe. Behavior does not define harm.

- **X**: left-eye RGB.
- **T**: multi-point contact force, location, duration, and impulse.
- **P**: selected left-arm joint position and velocity.
- **I**: joint torque and deterministic mechanical-load transforms.

The study extends original DMBN vision/proprioception and the Artificial Pain vision/touch experiment. It follows Silicopathy only for the short-term embodied self-to-other pathway. It does **not** implement or claim subjective pain, biological empathy, ODRC memory, LLM memory, or moral reasoning.

## Difference from prior M1/M1-MIRROR

**The new targets come from PyBullet contact, motion, and torque rather than a researcher-defined severity latent.** Prior M1-MIRROR mapped `X_other` to Self-counterfactual P/I. This study keeps that output and separately predicts actual Other T/P/I using B-specific context or calibration, then evaluates it against B's measured sensors.

## Stage map

- **Stages 0-2**: references, physical acquisition, and Self physics.
- **Stages 3A-3C**: X/P sanity, X/T precedent, full X/T/P/I Self DMBN.
- **Stage 4**: transparent Self harm readout and simple protection.
- **Stages 5-6**: two-PyCub observation, Self counterfactual, actual Other prediction, calibration.
- **Stage 7**: matched and mismatched Self/Other conditions plus shortcut controls.
- **Stage 8**: stop-probe proof of concept based on predicted Other state.

## Commands

Run from the repository root with the existing PyCubSim2 environment:

```bash
export MPLCONFIGDIR=/tmp/dmbnv3-mpl
PY=/opt/miniconda3/envs/pycub310/bin/python

# Stages 1-2: 3 x 3 x 2 x 20 Self trials plus controls.
$PY -m experiments.pain_self_other.run generate --design self --repetitions 20 --output experiments/pain_self_other/data/raw/self_full --seed 20261000
$PY -m experiments.pain_self_other.run prepare --raw experiments/pain_self_other/data/raw/self_full --processed experiments/pain_self_other/data/processed/self_full --manifest experiments/pain_self_other/data/manifests/self_full.csv --normalization experiments/pain_self_other/data/manifests/self_full_normalization.json --seed 20261000
$PY -m experiments.pain_self_other.run physics-report --raw experiments/pain_self_other/data/raw/self_full --output experiments/pain_self_other/reports/STAGE2_PHYSICS_VALIDATION_FULL.md

# Stages 3A-3C.
$PY -m experiments.pain_self_other.run train --manifest experiments/pain_self_other/data/manifests/self_full.csv --normalization experiments/pain_self_other/data/manifests/self_full_normalization.json --modalities XP --output experiments/pain_self_other/checkpoints/S3A_DMBN_XP_full --steps 20000
$PY -m experiments.pain_self_other.run train --manifest experiments/pain_self_other/data/manifests/self_full.csv --normalization experiments/pain_self_other/data/manifests/self_full_normalization.json --modalities XT --output experiments/pain_self_other/checkpoints/S3B_DMBN_XT_full --steps 30000
$PY -m experiments.pain_self_other.run train --manifest experiments/pain_self_other/data/manifests/self_full.csv --normalization experiments/pain_self_other/data/manifests/self_full_normalization.json --modalities XTPI --output experiments/pain_self_other/checkpoints/S3C_DMBN_XTPI_full --steps 40000

# Stage 7 paired physics. This creates one Other-actual and one Self-reference episode per pair.
$PY -m experiments.pain_self_other.run generate --design dissociation --repetitions 20 --output experiments/pain_self_other/data/raw/dissociation --seed 20262000 --no-controls
$PY -m experiments.pain_self_other.run prepare --raw experiments/pain_self_other/data/raw/dissociation --processed experiments/pain_self_other/data/processed/dissociation --manifest experiments/pain_self_other/data/manifests/dissociation.csv --normalization experiments/pain_self_other/data/manifests/dissociation_normalization.json --seed 20262000
```

`generate` skips already complete episodes by default, so interrupted runs resume without overwriting data. The authoritative record of commands actually executed, rather than merely available, is `docs/PAIN_SELF_OTHER_HANDOFF.md`.

## Data and normalization

- Raw physics/contact/P/I are sampled at **240 Hz**; left-eye RGB is sampled at **30 Hz** and retained at **128 x 128 x 3**.
- Processed trajectories contain **60 steps over 2 seconds**. The CPU image encoder uses deterministic **16 x 16 x 3** area-downsampled RGB.
- Splits are condition-stratified at the **episode level**. Frames from one episode never cross splits.
- RGB stays in `[0,1]`; T/P/I means and standard deviations come only from the training split. Reports invert normalization into physical units.

## DMBN semantics

Each context sample is `(observation time, modality value)`. Modality-specific encoders are mean-aggregated, stochastic coefficients blend the available representations, and modality-specific decoders receive an independently selected target time. Missing modalities receive zero availability. Predictions at earlier and later query times are independent evaluations and are never recursively fed back.

The modern learner retains Gaussian mean/scale outputs and adds normalized mean MSE to NLL to keep difficult tactile/internal predictive means from collapsing into uncertainty. The exact differences from the official TensorFlow notebook are documented in `docs/DMBN_IMPLEMENTATION_NOTES.md`.

## Evaluation and controls

- **T**: trajectory MAE/RMSE, onset, peak force, impulse, and peak timing.
- **P**: joint-position and joint-velocity MAE.
- **I**: trajectory error, peak torque, accumulated load, and peak timing.
- **Baselines**: unconditional training mean; nearest visual trajectory is used diagnostically.
- **Shortcut controls**: one probe geometry across outcomes, appearance randomization, matched event seeds across body conditions, Self-projection ablation, shuffled body context, and shifted visual timestamps.

The action readout uses predicted peak force, impulse, peak torque, and accumulated torque load. It remains downstream from DMBN and is not a pain label or a claim of subjective experience.
