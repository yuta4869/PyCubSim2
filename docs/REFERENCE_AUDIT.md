# Reference Audit: Physical Self/Other DMBN Study

## Audit scope and authority

**The original DMBN paper is the architectural authority; the current study prompt is the authority for the new Self/Other question.** The audit used the complete local PDFs, the complete eight-cell official notebook, its bundled 100-interaction dataset inventory, and PyCubSim2 `main` at commit `2335326`.

Primary sources:

- Seker et al., "Imitation and Mirror Systems in Robots through Deep Modality Blending Networks," *Neural Networks* 146 (2022), pp. 22-35, DOI [10.1016/j.neunet.2021.11.004](https://doi.org/10.1016/j.neunet.2021.11.004).
- [Official DMBN repository](https://github.com/myunusseker/Deep-Modality-Blending-Networks), especially `notebooks/DMBN.ipynb` cells 4-7.
- Ribeiro et al., "Artificial Pain Representation with Tactile and Vision Blending," *Humanoids 2025*, pp. 799-806, DOI [10.1109/Humanoids65713.2025.11203122](https://doi.org/10.1109/Humanoids65713.2025.11203122).
- Asada, "Silicopathy: Artificial Empathy through Cognitive and Affective Development of Pain," *ICDL 2025*, pp. 1-6, DOI [10.1109/ICDL63968.2025.11204355](https://doi.org/10.1109/ICDL63968.2025.11204355).
- [PyCubSim2](https://github.com/yuta4869/PyCubSim2), commit `2335326`.

## Four generations

| Generation | Relevant section, figure, or code | Actually implemented in the source | Proposed but not validated there | Reused here | Changed here | Scientific reason |
|---|---|---|---|---|---|---|
| **A - Original DMBN** | Paper Sec. 3, Eqs. 1-5, Figs. 1-2, Appendix C; notebook cells 4-7 | Vision + 7-DoF proprioception; timed observation samples; modality-specific encoders; mean aggregation; stochastic arithmetic latent blending; explicit target-time query; modality-specific probabilistic decoders; past/future and missing-modality reconstruction | A biologically faithful mirror-neuron account; unrestricted development beyond the fixed action repertoire | Observation/query semantics, set aggregation, stochastic blending, availability weights, common latent, independent target queries | Extend from **2 to 4 modalities**; deterministic seeds/checkpoints; validation split; practical stopping; raw 128x128 images but CPU learner uses documented 16x16 RGB views | Preserve the algorithm while making the experiment reproducible and feasible on the available CPU |
| **B - Artificial Pain Representation** | Secs. III-V; Figs. 1-10; Table I | Vision + touch DMBN adaptation; 50 synchronized 55-step trajectories; RGB at 30 Hz and touch at 100 Hz resampled to video; bounded tactile regression; vision-to-touch, touch-to-vision, thresholded discrimination, reflexive withdrawal, preliminary other-gripper observation | General artificial empathy and richer pain-memory mechanisms | Separate physical trajectory prediction, downstream threshold, and behavior; Stage 3B vision-touch gate; partial vision to future touch | Replace **Pen=harm / Sponge=non-harm** with one probe whose consequence varies by speed, posture, location, and body condition; add P and mechanical I; retain physical units | Prevent object identity from trivially determining harm and ground targets in simulator measurements |
| **C - Silicopathy** | Secs. III-VII; Figs. 1, 3-7 | Separate preliminary modules for tactile discrimination, DMBN vision-touch prediction, and ODRC fear conditioning are described; the paper explicitly calls integration preliminary and partial | Full memory/language/social integration, LLM episodic memory, long-term mental pain, cultural learning, universal moral agency | Embodied self experience, self-other mapping, external-event-to-internal-simulation progression, touch/pain pathway separation | Restrict scope to **short-term physical consequence prediction**; no ODRC, LLM, long-term pain, morality, or subjective-pain claim | The broader architecture is a roadmap, not evidence that all components work as one validated system |
| **D - Current study** | This specification and Stages 0-8 | To be established by executed PyBullet data, DMBN tests, saved predictions, and stage gates | Subjective pain, biological empathy, consciousness, human interoception, and moral agency remain outside scope | Physical embodiment and self-based internal simulation | Add actual Self, Self counterfactual, and actual Other as **three non-interchangeable targets**; pair A/B physics; test Other calibration and selective protection | Directly tests where self-projection fails and whether Other-specific information recovers actual Other T/P/I |

## Algorithmic invariants extracted before implementation

### Known objective facts

**A DMBN observation is `(time, modality value)`, not a whole-state vector without time.** Within each modality, independently encoded observations are averaged, so their order is irrelevant (Seker et al., Sec. 3, Eqs. 1-2; notebook cells 4 and 6).

**The common representation is an arithmetic blend of equal-width modality representations.** The paper specifies a normalized weighted average using stochastic coefficients `p_m` and availability/reliability weights `w_m`; the notebook implements `p*R_image + (1-p)*R_joint` without a denominator because the two coefficients sum to one (Seker et al., Eq. 3; notebook cell 6).

**Target time is independent of observation time and is concatenated to the common latent before decoding.** The model may query before or after supplied observations, and a trajectory is decoded by independent queries rather than by feeding the prediction at `t+1` into the prediction at `t+2` (Seker et al., Secs. 1, 3, 5.3; notebook cell 6).

**A missing modality has zero availability rather than a learned absence embedding.** The surviving available representations are re-normalized; at least one modality must be available for a conditioned prediction (Seker et al., Eq. 3; notebook cells 4 and 6).

### Analysis and implementation decision

For **four modalities**, stochastic coefficients are sampled from a flat Dirichlet distribution over available modalities, the direct multi-modality generalization of the paper's constrained random mixture. The implementation uses the paper's normalized Eq. 3 so arbitrary reliability weights remain well-defined. This differs from the two-modality notebook shortcut but follows the higher-authority paper.

## Material contradictions and resolutions

| Topic | Paper | Official notebook | Resolution here |
|---|---|---|---|
| **Availability denominator** | Eq. 3 divides by `sum(p_m w_m)` | No explicit denominator or separate `w`; coefficients sum to one | Implement normalized Eq. 3 with separate availability weights |
| **Image uncertainty** | Eq. 4 requires mean and variance for each modality; Appendix C table shows only 3 image channels | Image decoder emits 6 channels: 3 mean + 3 log-scale | Retain mean and softplus scale for every learner modality |
| **Loss balance** | Eq. 5 sums modality log likelihoods | Image loss weight 1, joint weight 0.01 | Use per-element averaged Gaussian NLL and equal default modality weights; report any override |
| **Dataset split** | 100 interactions, 80/20 train/test | IDs 0-39 train, 40-44 validation, 45-49 test per action; sampler hard-codes only `move` | Episode-level 70/15/15 split, deterministic and condition-stratified |
| **Training duration** | 1,000,000 batch-one iterations | Same, without active validation/checkpointing | Validation checkpoint selection and practical early stopping |
| **Pain target** | Not applicable | Not applicable | DMBN predicts X/T/P/I; harm is a separate transparent readout |

## What is deliberately not reused

- **Object-category harm labels** from the Artificial Pain experiment are rejected as the core manipulation.
- **Ordinary autoregression**, Transformers, LSTMs, GRUs, generic autoencoders, and generic regressors do not replace DMBN.
- **Researcher-authored hidden pain or vulnerability latents** are not targets.
- **ODRC, LLM memory, long-term mental pain, moral reasoning, and human experiments** are documented only as later work.

