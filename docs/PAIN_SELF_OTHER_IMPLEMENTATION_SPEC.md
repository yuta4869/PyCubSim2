# Implementation Specification: Physical Self/Other DMBN

## Research question

**The primary question is whether a self-trained multimodal body model can distinguish "what would happen to Self" from "what actually happens to Other" under the same external event.** Prediction error alone is secondary; the decisive cases are Self-high/Other-low and Self-low/Other-high.

The study makes no claim of **subjective pain**, **biological empathy**, **human interoception**, consciousness, or moral agency. `I` means **robot internal mechanical state / load proxy**.

## Variables and causal roles

### Physical variables

- **X - exteroception**
  - Raw: left-eye RGB, `128 x 128 x 3`, about 30 Hz.
  - Learner view: deterministic area-downsampled `16 x 16 x 3`, values in `[0,1]`; raw images are retained.
  - Logged controls: depth, segmentation, probe pose, and object metadata are not supplied to the initial DMBN.
- **T - touch**
  - Raw per contact point: body/link IDs, world positions on A/B, normal, distance, normal force, lateral forces, and relative velocity when derivable.
  - Per step: count, contact flag, total/peak normal force, impulse increment/cumulative impulse, contact duration, force-weighted position, and contacted-link ID.
- **P - proprioception**
  - Seven left-arm joints: shoulder pitch/roll/yaw, elbow, wrist pronation/supination, wrist pitch/yaw.
  - Joint position and velocity in SI-compatible PyBullet units.
- **I - internal mechanical state**
  - Direct applied joint torque from `getJointState`.
  - Deterministic transforms: `abs(torque * angular_velocity)`, cumulative mechanical load, and exponentially filtered mechanical load.

### Three references that must not be conflated

- **Self actual**: measured `T_self/P_self/I_self` when A is contacted.
- **Self counterfactual**: prediction for A under the probe event observed on B; paired A reruns provide a physical evaluation reference.
- **Other actual**: measured `T_other/P_other/I_other` from B during B's event.

### Downstream harm and behavior

**DMBN does not predict a hidden `Y_pain`.** Reports retain peak force, impulse, peak torque, and accumulated load separately. The action-only scalar is:

`H_action = 0.35*F_peak/F95 + 0.25*impulse/J95 + 0.20*tau_peak/tau95 + 0.20*load/L95`

Each denominator is estimated from the training split only, ratios are clipped to `[0,2]`, and the initial action threshold is **0.75**. This is an engineering decision criterion, not subjective pain.

## Raw episode schema

Each episode directory contains:

- `metadata.json`
  - schema/software version, git commit, episode ID, seed, role, probe parameters, speed, posture, target link/region, body condition, controller parameters, physics/camera rates, and timestamps.
- `trajectory.npz`
  - `time_s [N]`, selected joint names, `joint_position [N,7]`, `joint_velocity [N,7]`, `joint_torque [N,7]`, `mechanical_power [N,7]`, cumulative/filtered load, probe pose/velocity, `contact_count [N]`, and padded contact-point fields `[N,K,...]`.
- `rgb.npz`
  - `time_s [M]`, left-eye `rgb [M,128,128,3]`; optional depth/segmentation are logged only when requested.

All physical values stay in physical units. **Raw clocks are preserved before resampling.**

## Processed trajectory schema

Processed episodes use **60 normalized query steps over 2.0 s** and store:

- `time_s`, `time_normalized`;
- `X [60,16,16,3]`;
- `T [60,d_T]`;
- `P [60,14]`;
- `I [60,16]`;
- physical summaries and condition metadata.

Continuous signals use linear interpolation; contact flags/link IDs use nearest/previous sampling; RGB uses nearest camera timestamp. Train/validation/test statistics are fitted on training episodes only.

## Physical protocol

### Self factorial design

- **Speed**: slow, medium, fast; pilot values are calibrated from actual contact results.
- **Posture**: flexed, neutral, extended left arm.
- **Contact region**: hand, forearm.
- **Repetitions**: 20 for the full target, giving **360 episodes**.
- **Timing**: 0.0-0.4 s baseline, 0.4-0.9 approach, 0.9-1.1 contact, 1.1-1.4 removal, 1.4-2.0 recovery.

The same spherical probe geometry is used across outcomes. Motion and body condition, not object category, create consequence variation.

### Paired Self/Other design

Every dissociation event has a deterministic pair:

- B receives the visible probe trajectory and provides **Other actual**.
- A receives the same saved probe trajectory in a matched rerun and provides the **Self-counterfactual physical reference**.

Body conditions change measured mechanics through controller gain/force limits and posture. No arbitrary vulnerability label creates the target.

## DMBN implementation strategy

### Preserved invariants

**Each modality has its own encoder.** Every encoder consumes one or more `(time, value)` observations, observations are mean-aggregated per modality, equal-width representations are stochastically blended, and every decoder receives `(common latent, independent target time)`.

Availability/reliability `w_m` is explicit. Missing modalities use `w_m=0`. Training draws mixture coefficients over the available modalities; evaluation uses equal coefficients unless a controlled reliability manipulation is specified.

Every modality decoder emits **mean and log-scale**. Scale is `softplus(log_scale)`. The executed loss is per-modality Gaussian negative log likelihood plus normalized mean MSE, both averaged per output element; the added mean term follows the Artificial Pain tactile-regression precedent and prevents difficult signals from being represented only as inflated uncertainty. Queries are vectorized but independent; predicted values never become later inputs.

### Practical modernization

- Modern, dependency-light **NumPy reverse-mode autodiff** is reused from an already finite-difference-tested local DMBN implementation.
- Raw RGB remains 128x128; the CPU smoke learner uses a modality-specific MLP over 16x16 RGB rather than the historical six-block CNN.
- Deterministic seeds, checkpoint state, optimizer state where needed, history, validation selection, and manifests are added.
- Full-size CNN replacement is deferred until the physical and semantic gates pass; it does not change observation/query semantics.

### Other-specific prediction

Stage 5 uses A's context to produce Self counterfactual. Stage 6/7 produce a separate Other prediction using either:

- **calibration fraction**: 0%, 5%, 20%, or 100% of B episodes; or
- a controlled body-context covariate attached to X encoding: controller gain scale, motor-force scale, and protection/compliance setting.

The body context is never a hidden harm label. Context ablation and shuffling test whether it contains genuine explanatory information.

## Data split and normalization

**Splits occur at the episode level**, never at the frame level. The default is 70% train, 15% validation, 15% test, stratified by experimental condition and seed. Stage 7 additionally holds out body-condition/event combinations when counts allow.

- RGB: divide by 255, then downsample; no test statistics.
- Time: map each episode's supported domain to `[0,1]` while retaining `time_s`.
- T/P/I: training mean and standard deviation with a minimum scale guard; binary contact remains binary for reports.
- Physical-unit metrics are computed after inverse transformation.

## Stages and automatic gates

| Stage | Implementation and execution target | DONE gate |
|---|---|---|
| **0** | Repository/reference audit and specification | Required papers/repository inspected; audit/spec/notes exist |
| **1** | Headless synchronized X/T/P/I acquisition | Deterministic rerun; no-contact near zero; contact nonzero; synchronized clocks; 100-episode command works |
| **2** | Self dataset and physics validation | At least one speed effect and one body/posture effect in measured physical quantities; reports/plots exist |
| **3A** | X+P original-style DMBN sanity | Past/future queries, both missing directions, weights, multiple independent targets, non-autoregression tests pass; primary relation beats unconditional mean |
| **3B** | X+T pain-study-style adaptation | Vision-to-touch and touch-to-vision run; onset, peak, impulse, MAE saved |
| **3C** | Full X/T/P/I Self model | Conditions A-F execute; T/P/I physical-unit and temporal metrics saved |
| **4** | Self harm readout and protection | Transparent components and threshold saved; low/high policy smoke passes |
| **5** | Two-PyCub observation and Self counterfactual | A camera records B interaction; separate Self-counterfactual output and paired reference exist |
| **6** | Other actual prediction and calibration fractions | B actual sensors recorded; 0/5/20/100% experiments or feasible smoke subsets saved |
| **7** | Four dissociation conditions and controls | Conditions 2 and 3 physically realized; separate Self/Other predictions; ablation/shuffle/time-shift/X-only controls evaluated |
| **8** | Other protection | Self-high/Other-low does not intervene and Self-low/Other-high intervenes in proof-of-concept smoke |

## Evaluation strategy

### Physical state metrics

- **T**: trajectory MAE/RMSE, contact onset error, peak force error, impulse error, peak timing.
- **P**: position/velocity MAE, correlation where defined, movement onset.
- **I**: torque/load MAE, peak error/time, cumulative load, recovery.
- **X**: normalized pixel MAE and representative reconstruction images; no claim that this is perceptual quality.

### Baselines and controls

- Unconditional train-mean trajectory.
- Condition-wise train mean when condition information is legitimately available.
- Nearest training trajectory based only on supplied observations.
- X-only, body-context ablation, shuffled body context, time-shifted X, and identity shuffle if identity is supplied.

### Dissociation metrics

Reports preserve trajectory differences and physical summary differences:

- `Delta_force = predicted Other peak force - predicted Self-CF peak force`.
- `Delta_load = predicted Other accumulated load - predicted Self-CF accumulated load`.
- Self-CF prediction is evaluated against paired A actual; Other prediction is evaluated against B actual.

## Failure classification

**Implementation failures** include NaNs, blank cameras, disconnected gradients, invalid timestamps, no physical contact, leakage, shape errors, and failure of basic DMBN completion. They are fixed and rerun.

**Scientific failures** include no Self-to-Other transfer, no benefit from Other context, failure to recover mismatch, or no multimodal advantage after implementation validity is established. They are preserved and reported.

## Optional later work

Human ratings, physiological signals, robot-human transfer, ODRC memory, habituation/sensitization, long-term pain, costly helping, social/intentional context, and LLM integration are **not implemented** in this study.
