# Three-model real-image regression audit — 2026-11-22

391 unique reviewed real originals, 98 capture groups, three frozen models,
1,173 image/model evaluations. No training, threshold tuning, real motion or
cloud access. Confidence .25, IoU NMS .70, imgsz640, end2end=False, no enhancement.
3x3 uses full-frame predictions; 9x9 uses the deployed four-zone pipeline.

Shared non-training subset: 143 earlier/larger-mark originals and 60 9x9
originals. These are historical data, not a new blind test.

| Model | Larger-mark exact boxes /143 | FN / FP | 9x9 exact reviewed cells /60 | FN / FP |
| --- | --- | --- | --- | --- |
| xo_real.pt | 122 | 16 / 8 | 16 (no scored marks detected) | 184 / 0 |
| xo_real_nine.pt | 120 | 13 / 15 | 57 | 4 / 0 |
| xo_real_nine_zero_candidate.pt | 119 | 12 / 20 | 59 | 0 / 1 |

The zero candidate improves small-symbol recall but adds false positives in
historical large-mark/hard-negative scenes. A triangle was predicted O at .82.
The 9x9 regression is one nominally blank top-right O prediction at .33; retain
the original label and flag weak texture/residual-ink ambiguity for re-review.

Same-cell 3x3 diagnostics on the 100 eligible untrained frames: 90/100, 86/100,
86/100 exact respectively. Different X/O predictions in one cell remain conflicts.
The latest model's benefit is not simply removable same-class duplicate boxes.

139 unreadable intended cell observations are excluded across the 160 9x9
frames. Full-array statistics are not a promise that the complete board is
visible/readable. Five-stage photos remain correlated within capture groups;
there are no fully occupied 81-mark physical boards in this selection.

Paired capture-group bootstrap latest-minus-comparator exact rate:
- 3x3 box match vs original: -2.10 percentage points, 95% [-8.39,+3.57].
- 9x9 reviewed cells vs nine model: +3.33 points, 95% [0,+8.33].

Keep the user-selected latest test default and preserve older weights. Before
another fine-tune, strengthen real hard-negative replay and maintain 3x3 positive
coverage; tune only on validation data, then collect a new untouched test batch.
Three consistent frames cannot eliminate a stable false positive.

Artifacts: data/evaluations/three_models_20261122/{manifest.json,summary.json,
metrics.csv,per-image.csv,analysis.json,REPORT.md,review.html,comparison.png}.
The review embeds 33 selected four-panel comparisons; raw real images are not
added to Git. Full per-model JSON retains file/pixel hashes, splits, training
exposure, TP/FN/FP, duplicate boxes, conflicts and ignored-cell accounting.

Reproduction: source Humble/workspace overlay; run
`python3 tools/compare_real_models.py --output <new-directory> --device 0`.
`python3 -m pytest -q tools/test_compare_real_models.py`: 5 passed.
Focused Ruff E9/F63/F7/F82 checks passed. Runtime GUI/controller code and model
files were unchanged, so additional ROS motion, colcon rebuilds, rosbag,
PlotJuggler, debugger and coverage runs were not required for this offline audit.
