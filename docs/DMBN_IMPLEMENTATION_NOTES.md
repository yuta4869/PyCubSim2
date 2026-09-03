# DMBN Implementation Notes

## Original implementation

**The official implementation is an eight-cell TensorFlow 1.x / standalone Keras notebook.** It uses `tf.ConfigProto`, `tf.Session`, `keras.backend.tensorflow_backend.set_session`, and TensorFlow Probability, with no dependency pins, seeds, active validation, or checkpointing ([official repository](https://github.com/myunusseker/Deep-Modality-Blending-Networks)).

The bundled data inventory contains **100 interactions**: 50 IDs with `move` and `grasp`, 6,962 JPEG frames, and joint/endpoint/object text files. The notebook itself samples only `move` because of a hard-coded debugging assignment.

## Original architecture and loss

- **Image encoder**: timed 128x128 RGB input (time broadcast as a fourth channel), six convolution/pooling blocks, flatten, dense to latent width 128.
- **Joint encoder**: scalar time + seven joint values, dense stack to latent width 128.
- **Aggregation**: mean over observation representations.
- **Blending**: elementwise weighted arithmetic addition.
- **Query**: common 128-vector concatenated with scalar target time.
- **Decoders**: modality-specific; notebook emits image and joint mean/log-scale pairs.
- **Loss**: diagonal Gaussian negative log likelihood with `softplus(log_scale)`; notebook weights image 1 and joints 0.01.

Source: Seker et al., Eqs. 1-5 and Appendix C, DOI [10.1016/j.neunet.2021.11.004](https://doi.org/10.1016/j.neunet.2021.11.004); official notebook cells 4-7.

## Modern implementation

**The modern port preserves the observation/query algorithm without recreating obsolete TensorFlow dependencies.** It uses NumPy and a small reverse-mode autodiff tape whose operators are checked against finite differences.

Changes:

- four modality-specific encoders for X/T/P/I;
- flat-Dirichlet stochastic mixture across available modalities;
- explicit paper-style availability/reliability weights and denominator;
- independent vectorized target queries;
- per-modality mean/log-scale decoders and Gaussian NLL;
- deterministic seeds, episode-level splits, training-only normalization, checkpoints, histories, and early stopping;
- raw 128x128 RGB retained, with a documented 16x16 CPU learner view.

## Preserved invariants

1. **Time is present in every observation.**
2. **Each modality is encoded independently.**
3. **Multiple observations are aggregated by a permutation-invariant mean.**
4. **All modality representations have equal latent width.**
5. **Stochastic arithmetic modality blending trains cross-modal completion.**
6. **Unavailable modalities have zero weight.**
7. **Target query time is independent of observation times.**
8. **Predictions at different times do not feed one another.**
9. **Every modality has its own decoder.**

## Intentional differences

| Item | Official notebook | Current implementation | Reason |
|---|---|---|---|
| Runtime | TensorFlow 1.x, standalone Keras | NumPy reverse-mode autodiff | Current reproducibility without obsolete stack |
| Modalities | Image + joint | X + T + P + I | Scientific question requires measured body consequences |
| Image learner | 128x128 CNN | 16x16 RGB MLP for CPU runs | Feasible end-to-end smoke/full pilot while retaining raw 128x128 data |
| Multiway mixture | `(p, 1-p)` | Dirichlet over available modalities | Direct sum-to-one extension to four modalities |
| Availability | Implicit in coefficients | Separate `w_m`, normalized per Eq. 3 | Preserve paper reliability semantics |
| Loss weights | Image 1, joint 0.01 | Per-element mean, equal modality defaults | Avoid undocumented 100x imbalance |
| Training | 1M single samples | Validation-selected practical run | Avoid unvalidated compute and preserve best checkpoint |

Hidden layers use **Leaky ReLU with slope 0.01**. Plain ReLU made all image-encoder units inactive on positive, uncentered RGB during the first Mini run; the nonzero negative slope preserves the feed-forward structure while preventing a disconnected modality.

The executed loss is **Gaussian negative log likelihood plus normalized mean MSE (weight 1.0)** per modality. The NLL retains learned scale, while the MSE term prevents the decoder from explaining difficult tactile/internal trajectories only by increasing uncertainty and collapsing its predictive mean. This follows the Artificial Pain adaptation's regression emphasis while retaining the original DMBN probabilistic output. Adam gradients are clipped to a global norm of **5.0**, and validation samples the full trajectory every five steps.

## Validation evidence required

The implementation is not considered DMBN-valid until automated checks cover arbitrary observation/query times, past/future queries, missing modalities, availability weighting, four-modality shapes, set-order invariance, independent multiple queries, and parameter independence from earlier predictions. Executed evidence and checkpoint paths are recorded in the handoff.
