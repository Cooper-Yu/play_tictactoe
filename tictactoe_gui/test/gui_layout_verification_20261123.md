# GUI layout acceptance — 2026-11-23

Code revision: cfeb610. Cloud rosject: 1063805.

Local Chrome fixtures passed: two-player controls, camera confirmation without
precommit, paused-turn resume without command replay, workbench polling recovery.

Cloud checkout was clean and fast-forwarded to cfeb610. `colcon build
--packages-select tictactoe_gui` passed in 3.86 seconds. Both GUI backends were
idle before restarting only the launcher-owned GUI group. MoveGroup and the
robot connection were preserved.

Actual cloud page checks:
- Workbench and game page each returned HTTP 200.
- Camera / Detection toggle and edges / detections processing selection worked.
- Returning from another tab showed Robot connected; no JavaScript errors.
- Game: ready, not busy, fresh camera and robot feedback, camera sequence 189.
- Workbench: ready, not busy, fresh feedback and camera, sequence 206,
  camera age approximately 0.045 seconds at observation.
- At 1440 / 1024 / 390 pixels, the layout used three / two / one columns;
  no horizontal overflow was observed.
- No drawing or physical movement was sent. Button presence does not prove
  execution of motion commands.

These are bounded functional checks. Indefinite uptime, long background periods
and true feedback-loss recovery remain separate acceptance work.
