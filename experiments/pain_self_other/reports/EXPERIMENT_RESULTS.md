# Executed Experiment Results

## Scope

**These results concern simulator-grounded multimodal bodily-consequence prediction, not subjective pain or biological empathy.** All values below come from executed held-out episodes; predictions are independent target-time queries rather than autoregressive rollouts.

## Known objective facts

### Physical data

| Dataset | Episodes | Split | Physics / RGB | Result |
|---|---:|---|---|---|
| **Self Full** | 363 | 255 / 54 / 54 | 240 Hz / 30 Hz | 360 contacts and 3 zero-force controls validated |
| **Dissociation** | 160 | 112 / 24 / 24 | 240 Hz / 30 Hz | 80 paired events; seed leakage across splits = 0 |
| **Research test generation** | 7 per run | temporary | 240 Hz / 30 Hz | deterministic, no-contact, rigid/compliant, stopped-probe cases |

The Full Self manipulation produced speed-to-impulse eta-squared **0.1820**, posture-to-peak-torque eta-squared **0.5558**, and posture-to-load eta-squared **0.2024**. Speed-to-peak-force eta-squared was only **0.0091**.

### DMBN trajectory results

| Stage / context | Target | DMBN MAE | Mean MAE | Relative result |
|---|---|---:|---:|---:|
| **3A X→P** | P | 0.000815 | 0.038775 | 97.9% lower |
| **3A P→X** | X | 0.005895 | 0.043111 | 86.3% lower |
| **3B X→T** | T | 2.944523 | 2.683248 | 9.7% higher |
| **3B T→T** | T | 2.282981 | 2.683248 | 14.9% lower |
| **3C X→P** | P | 0.002578 | 0.038775 | 93.4% lower |
| **3C X→T** | T | 3.269444 | 2.683248 | 21.8% higher |
| **3C X→I** | I | 0.219652 | 0.178898 | 22.8% higher |
| **3C X+P+I→T** | T | 2.404786 | 2.683248 | 10.4% lower |
| **3C X+P+I→I** | I | 0.191741 | 0.178898 | 7.2% higher |

Stage 3B X→T contact-onset error was **−0.0194 s**, compared with **0.1384 s** for the mean trajectory, but peak force was underestimated by **5.55 N** on average.

### Other calibration

| B condition | Calibration requested / realized | T MAE | P MAE | I MAE |
|---|---:|---:|---:|---:|
| **Rigid** | 5% / 7.14% | 0.906795 | 0.000437 | 0.088874 |
| **Rigid** | 20% / 21.43% | 0.936255 | 0.000368 | 0.137808 |
| **Rigid** | 100% / 100% | 1.034545 | 0.000473 | 0.110722 |
| **Compliant** | 5% / 7.14% | 0.286459 | 0.010254 | 0.103849 |
| **Compliant** | 20% / 21.43% | 0.168263 | 0.002660 | 0.054644 |
| **Compliant** | 100% / 100% | 0.175357 | 0.002273 | 0.038963 |

Calibration did **not** improve monotonically. Condition-specific mean trajectories remained stronger than DMBN for most rigid and internal-state comparisons.

### Self/Other dissociation

| Condition | Actual Self H | Predicted Self-CF H | Actual Other H | Predicted Other H | Predicted action |
|---|---:|---:|---:|---:|---|
| **Matched high** | 0.8682 | 0.7081 | 0.9950 | 0.6850 | No intervention |
| **Self high / Other low** | 0.8682 | 0.7080 | 0.3234 | 0.2961 | No intervention |
| **Self low / Other high** | 0.3838 | 0.2963 | 0.9950 | 0.6850 | No intervention |
| **Matched low** | 0.3838 | 0.2963 | 0.3234 | 0.2961 | No intervention |

Other-specific models improved over direct Self projection:

| Target | Self-projection MAE | Other-specific MAE | Improvement | Shuffled-context MAE |
|---|---:|---:|---:|---:|
| **T** | 1.089944 | 0.604951 | 44.5% | 1.543973 |
| **P** | 0.024899 | 0.001373 | 94.5% | 0.047189 |
| **I** | 0.152389 | 0.074842 | 50.9% | 0.227863 |

Shifting early X timestamps by 0.25 changed errors negligibly. In this protocol the early image content encoded body condition, but the model did not measurably rely on its observation timestamps.

## Fact-based analysis by research question

- **Q1 — Self X/T/P/I learning:** partially supported. X and P reconstruction are strong; T becomes better than mean only when early P/I are also supplied; I remains weaker than mean.
- **Q2 — Early X predicts later Self consequence:** supported for P and contact timing, not for T/I amplitude.
- **Q3 — Other observation evokes Self counterfactual:** implemented and evaluated; the predicted Self-CF readout separates rigid and compliant Self conditions, but high consequences are underestimated.
- **Q4 — Self-only transfer to Other:** weak. Direct Self projection has materially larger T/P/I error than Other-specific prediction.
- **Q5 — Other calibration/context:** body-specific context improves over Self projection and shuffling degrades prediction, but increasing calibration fraction is not monotonically beneficial.
- **Q6 — Self-high/Other-low vs Self-low/Other-high:** supported at the continuous readout level: predicted Other H changes from 0.2961 to 0.6850 while Self-CF changes in the opposite direction.
- **Q7 — Selective Other protection:** not supported at threshold 0.75. The high Other prediction remains below threshold, so the required intervention is not triggered.

## Preserved negative results

- **X-only T/I amplitude prediction does not beat the unconditional mean.**
- **Calibration fraction does not produce monotonic improvement.**
- **Time-shift control does not degrade prediction.**
- **The fixed action threshold misses Self-low/Other-high**, so Stage 8 fails despite correct continuous ordering.

## Claim limits

The experiment demonstrates a physically grounded mismatch manipulation and a computational separation between Self-CF and Other-specific continuous predictions. It does not establish subjective pain, consciousness, biological mirror neurons, human interoception, biological empathy, or moral agency.
