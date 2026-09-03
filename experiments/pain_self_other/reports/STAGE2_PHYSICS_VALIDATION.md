# Stage 2 Physics Validation

## Known objective facts

**54 physical Self-contact episodes** and **3 no-contact controls** were executed.

| Speed | Posture | Location | n | Peak force N | Impulse N s | Peak torque N m | Load N m s |
|---|---|---|---:|---:|---:|---:|---:|
| fast | extended | forearm | 3 | 24.8841 | 7.9997 | 5.4017 | 13.9010 |
| fast | extended | hand | 3 | 12.7815 | 3.3323 | 3.2584 | 12.5682 |
| fast | flexed | forearm | 3 | 20.2891 | 4.7910 | 2.4951 | 12.3746 |
| fast | flexed | hand | 3 | 8.2401 | 1.2692 | 2.4951 | 12.5550 |
| fast | neutral | forearm | 3 | 24.2271 | 8.1761 | 3.4493 | 14.1194 |
| fast | neutral | hand | 3 | 10.0294 | 2.3561 | 3.0335 | 14.0706 |
| medium | extended | forearm | 3 | 24.3719 | 10.5180 | 4.8192 | 14.0849 |
| medium | extended | hand | 3 | 13.8562 | 5.0569 | 3.0033 | 12.3145 |
| medium | flexed | forearm | 3 | 18.8638 | 6.0096 | 2.4950 | 11.9477 |
| medium | flexed | hand | 3 | 5.2750 | 1.0958 | 2.4948 | 12.6352 |
| medium | neutral | forearm | 3 | 24.1968 | 12.3999 | 3.4358 | 13.4329 |
| medium | neutral | hand | 3 | 9.0868 | 2.9368 | 3.0628 | 13.8284 |
| slow | extended | forearm | 3 | 24.9256 | 18.9057 | 4.8161 | 15.1054 |
| slow | extended | hand | 3 | 12.2767 | 7.1577 | 3.0846 | 11.8427 |
| slow | flexed | forearm | 3 | 18.1086 | 8.7205 | 2.4944 | 11.2546 |
| slow | flexed | hand | 3 | 3.9607 | 1.0221 | 2.4949 | 12.6227 |
| slow | neutral | forearm | 3 | 22.8173 | 25.9609 | 3.2114 | 10.7060 |
| slow | neutral | hand | 3 | 8.4373 | 3.8853 | 3.0719 | 13.3444 |

### Effect sizes

- **speed_peak_force_eta_squared**: 0.0087
- **speed_impulse_eta_squared**: 0.1744
- **posture_peak_torque_eta_squared**: 0.5477
- **posture_load_eta_squared**: 0.1946

### Automatic gate

- **contact_nonzero**: PASS
- **no_contact_near_zero**: PASS
- **speed_effect**: PASS
- **posture_effect**: PASS

## Fact-based analysis

The gate requires real contact, zero-force controls, and at least a small (eta-squared >= 0.01) speed and posture association. It does not assert causality or subjective pain.

## Figures

- `experiments/pain_self_other/outputs/figures/stage2_physics_factors.png`
- `experiments/pain_self_other/outputs/figures/stage2_example_xtpi.png`
