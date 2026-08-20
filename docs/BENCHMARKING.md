# Benchmarking

Phase 15 uses deterministic paired statistical admission. A candidate declares one primary metric before measurements begin. It is admitted only when that metric proves at least 5% improvement and every applicable protected metric independently passes its non-regression gate; no weighted aggregate score exists.

Lower-is-better log-ratio metrics use `ln(candidate / baseline)` for regression and `ln(baseline / candidate)` for benefit. Higher-is-better metrics reverse each ratio. Positive regression is always worse; positive benefit is always better. CPU, memory, disk utilization, and replication lag use absolute deltas. Zero-tolerance invariants reject immediately.

Baseline references are geometric means for log-ratio metrics and arithmetic means for absolute-delta metrics. The allowed regression margin is the minimum applicable relative, absolute, and hard-boundary headroom margins. Baseline variance never widens it. The primary minimum benefit is `ln(1 / 0.95)` for lower-is-better metrics and `ln(1.05)` for higher-is-better metrics.

AUTONOMOUS and PUBLICATION first run A/A calibration. With sample standard deviation `s` (`ddof=1`) in the transformed domain and permitted margin `M`, required pairs are `ceil((1.645 * s / (0.5 * M)) ** 2)`. Required count is the maximum of all protected metrics, primary benefit, and profile minimum; a value above the profile maximum is `INCONCLUSIVE_NOISE`.

Each pair restores equivalent starting state and runs in deterministic SHA-256-derived AB or BA order. The bootstrap seed derives from evaluation run ID, metric key, scope type, scope ID, and `bootstrap`. NumPy explicitly resamples pair indices with replacement, computes arithmetic means, and repeats 1,000 times for SMOKE or 10,000 times otherwise. Protected metrics use the one-sided 95% upper bound; primary benefit uses the one-sided 95% lower bound.

Profiles are SMOKE (5 s warmup, 10 s measurement, 3 pairs, 1,000 draws, never production eligible), AUTONOMOUS (30/60 s, 10–30 pairs, 10 A/A pairs, 10,000 draws), and PUBLICATION (60/120 s, 15–40 pairs, 12 A/A pairs, 10,000 draws). Decision precedence is safety invariant, environment mismatch, missing metric, A/A noise, protected regression, absent meaningful benefit, then admission.
