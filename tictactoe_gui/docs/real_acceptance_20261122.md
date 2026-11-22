# Real Piper acceptance - 2026-11-22

Writing height: 206 mm. Contact speed and acceleration: 45%. Control feedback: /joint_states. Model: xo_newest.pt.

## Recorded edge cases

| Case | Cell (row, column) | Mark | Result | Confidence | Seconds |
|---|---|---|---|---|---|
| right-edge-a-0-X-r9c9 | (9, 9) | X | confirmed | X 0.902 | 32.469 |
| right-edge-a-1-O-r8c9 | (8, 9) | O | confirmed | O 0.657, X 0.320 | 36.787 |
| right-edge-a-2-X-r7c9 | (7, 9) | X | confirmed | X 0.931 | 29.209 |
| right-edge-a-3-O-r6c9 | (6, 9) | O | confirmed | O 0.872 | 30.477 |
| right-edge-a-4-X-r5c9 | (5, 9) | X | confirmed | X 0.917 | 31.88 |
| right-edge-a-5-O-r4c9 | (4, 9) | O | conflicting_cells | O 0.834, X 0.404 | 71.073 |
| top-edge-a-0-X-r1c1 | (1, 1) | X | confirmed | X 0.917 | 29.354 |
| top-edge-a-1-O-r1c2 | (1, 2) | O | confirmed | O 0.939 | 26.198 |
| top-edge-a-2-X-r1c3 | (1, 3) | X | confirmed | X 0.781 | 29.481 |
| top-edge-a-3-O-r1c4 | (1, 4) | O | confirmed | O 0.931 | 27.071 |
| top-edge-a-4-X-r1c5 | (1, 5) | X | motion_interruption | none | 13.679 |
| top-edge-a-recovered-0-X-r1c5 | (1, 5) | X | confirmed | X 0.753 | 28.715 |
| top-edge-a-recovered-1-O-r1c6 | (1, 6) | O | confirmed | O 0.867 | 23.951 |
| top-edge-a-recovered-2-X-r1c7 | (1, 7) | X | confirmed | X 0.860 | 29.844 |
| top-edge-a-recovered-3-O-r1c8 | (1, 8) | O | no_detection_at_target | none | 68.018 |
| top-right-corner-x-0-X-r1c9 | (1, 9) | X | no_detection_at_target | none | 70.441 |
| upper-right-a-0-X-r3c9 | (3, 9) | X | confirmed | X 0.830 | 28.693 |
| upper-right-a-1-O-r2c9 | (2, 9) | O | not_confirmed | O 0.263 | 67.83 |

A feedback stop before ink is a motion interruption, not a recognition miss. Pictures for each case are under captures/<case>/. Raw, box-overlay and cell-overlay images are fetched sequentially after the physical scene is stable; they are not claimed to share one exact frame.

## Verified continuity and UI checks

- Completed a three-by-three handwritten human-vs-human game after a controlled stop and inspected resume; X won the middle row.
- Interrupted nine-by-nine grid preparation after 11 complete lines; resumed only the 5 unstarted lines, then returned to zero.
- Natural feedback interruption before the fifth top-row mark retained the original four marks; inspected resume returned to zero and allowed a fresh drawing request.
- Fifteen-second active game-tab freeze did not stop cloud execution or replay a POST. Camera sequence advanced from 3003 to 3103.
- Rectified, edge and detection views, camera toggle, ROI/full-image, brightness and cyan preview controls produced no motion POSTs.

## Remaining / limitations

- Workbench XYZ +/- 1 mm, clear/zero presets, record with screenshot, return from zero and deletion passed. Original 18 records remain; the unreferenced temporary screenshot was removed.
- Canvas Chair/Whale/Smile loading, Undo/Clear, native drawing execution and physical Reset passed.
- All 17 unique top-row/right-column cells were tested once with one selected symbol: 13 confirmed, 4 did not. This is a targeted edge smoke test, not general accuracy or both-class coverage.
- Failed edge checks: O (1,8) absent; X (1,9) absent; O (2,9) unstable across frames; O (4,9) X/O conflict.
- Central nine-by-nine human-vs-human Four-in-a-Row completed all seven camera-confirmed turns; X won row 5, columns 4 through 7. Evidence: captures/central-four-complete.
- Human-vs-AI three-by-three regression completed: O won the diagonal after three camera-confirmed player handwriting turns. Evidence: captures/ai-three-finished.
- A separate natural grid stop during 2_lift did not qualify for suffix recovery; it required inspected feedback recovery and safe retraction before a new board. Do not count that attempt as a finished game.
- No lowered writing height or changed confidence/NMS threshold was used.
- Long upstream joint-feedback receipt gaps were observed. Their precise robot/bridge/network source is not established by a cloud-only subscriber.
- Bounded automatic initial-approach recovery passed 233 local functional tests; runtime deployment c635045 is separate from the manually inspected recovery evidence above.

## Final recovery patch and closeout

- Code revision cf8b80a was built and loaded in the cloud. The raised-lift test first exposed a busy-terminal race at 6aa0b76. A read-only bounded terminal wait repaired it.
- On cf8b80a a controlled stop at 1_lift, measured Z=211.0005 mm, preserved the completed line. Native inspected Resume drew exactly the remaining three lines and returned to zero. Evidence: captures/lift-terminal-fixed-paused and captures/verified-lift-resume-complete.
- Latest local GUI/coordinator/perception functional regression: 245 passed; 3 existing linter tests deselected. Existing broad style debt was not reformatted.
- Automatic pre-contact approach replan has local safety tests and is deployed, but no matching natural interruption exercised that exact automatic branch in this run. Inspected player/grid recovery was exercised on the real arm.
- Final physical Reset and return to zero passed with fresh feedback, no active game and no active job. Joint1-6 maximum absolute feedback was 0.00009915 rad. The original 18 pose records remain; only the temporary test record/photo was removed.
- Deadline guardian was disarmed only after verified zero; the owned read-only feedback sampler was stopped. Browser, Connect, MoveGroup and GUI services remain available.

## Feedback transport evidence and remaining work

- An independent cloud /joint_states subscriber recorded 2,603,350 callbacks with a final median interval of 1.998 ms, plus eight gaps over 0.3 s. The longest measured gap was 7.319 s. Workstation execution ticks remained about 40 ms with observed maxima under 70 ms in the relevant incidents.
- This confirms a real feedback-delivery outage beyond a frozen game tab. It does not identify whether the robot publisher, bridge or network is the source. No robot-side instrumentation or transport relay was deployed.
- Camera-based edge failures remain unresolved at the fixed 206 mm writing height and unchanged 0.25 confidence / 0.70 NMS configuration. Retain the four cases for image/label/model investigation and repeat both classes at the same cells.
- Partially written contact strokes, interrupted AI strokes and process-restart game restoration still require separate handling; they are not blindly replayed.
- Raw images, overlays, exact per-frame numeric observations and verification results remain in this local output folder; cloud evidence remains under data/real_recovery_20261122_pm.

Local artifact root: C:/Users/Administrator/Documents/Robot_Developer_Masterclass/outputs/real-recovery-20261122-pm.
