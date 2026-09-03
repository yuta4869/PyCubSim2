# Stage 2 Physics Validation

## Known objective facts

**360 physical Self-contact episodes** and **3 no-contact controls** were executed.

| Speed | Posture | Location | n | Peak force N | Impulse N s | Peak torque N m | Load N m s |
|---|---|---|---:|---:|---:|---:|---:|
| fast | extended | forearm | 20 | 24.6219 | 7.9246 | 5.3030 | 13.8297 |
| fast | extended | hand | 20 | 13.2992 | 3.3741 | 3.2212 | 12.4893 |
| fast | flexed | forearm | 20 | 20.0015 | 4.6713 | 2.4948 | 12.3786 |
| fast | flexed | hand | 20 | 7.1224 | 1.0276 | 2.4950 | 12.6774 |
| fast | neutral | forearm | 20 | 24.7147 | 8.4324 | 3.5394 | 14.0674 |
| fast | neutral | hand | 20 | 10.9142 | 2.3382 | 3.2313 | 14.0813 |
| medium | extended | forearm | 20 | 24.0293 | 10.2817 | 4.7893 | 14.0157 |
| medium | extended | hand | 20 | 13.1838 | 4.8437 | 3.1488 | 12.3450 |
| medium | flexed | forearm | 20 | 18.7237 | 5.9384 | 2.4948 | 12.0219 |
| medium | flexed | hand | 20 | 5.2584 | 1.0841 | 2.4949 | 12.6236 |
| medium | neutral | forearm | 20 | 23.4935 | 11.8199 | 3.2920 | 13.4982 |
| medium | neutral | hand | 20 | 8.7998 | 2.7804 | 3.1003 | 13.8440 |
| slow | extended | forearm | 20 | 24.0886 | 18.6638 | 4.6261 | 14.8372 |
| slow | extended | hand | 20 | 12.3173 | 7.2302 | 3.0375 | 11.7591 |
| slow | flexed | forearm | 20 | 17.9574 | 8.4896 | 2.4945 | 11.2096 |
| slow | flexed | hand | 20 | 4.6692 | 1.2894 | 2.4949 | 12.4764 |
| slow | neutral | forearm | 20 | 23.3339 | 26.0159 | 3.2907 | 10.9019 |
| slow | neutral | hand | 20 | 8.6706 | 4.0990 | 3.0736 | 13.3595 |

### Effect sizes

- **speed_peak_force_eta_squared**: 0.0091
- **speed_impulse_eta_squared**: 0.1820
- **posture_peak_torque_eta_squared**: 0.5558
- **posture_load_eta_squared**: 0.2024

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
