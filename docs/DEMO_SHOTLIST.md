# GaussOptions Agent — official demo shot list

Programmatic Remotion composition `GaussOptionsDemo` (1920×1080, 30 fps, 1830 frames ≈ 61 s). Source: `remotion/`. Rendered file: `artifacts/demo.mp4`.

All motion uses `useCurrentFrame()` + `interpolate()`. This is not a screen recording.

| # | Scene file | Composition id | Duration | On-screen story |
| --- | --- | --- | --- | --- |
| 1 | `remotion/src/scenes/SceneOneLiner.tsx` | `SceneOneLiner` | 300 frames (10.0 s) | Product one-liner: GaussOptions Agent is an autonomous options-only paper agent. Cycle: decide, gate, option order. |
| 2 | `remotion/src/scenes/ScenePaperBook.tsx` | `ScenePaperBook` | 270 frames (9.0 s) | Dedicated $100,000 paper book. Live trading off. No keys on screen. |
| 3 | `remotion/src/scenes/SceneCycle.tsx` | `SceneCycle` | 360 frames (12.0 s) | AI cycle: wheel cash-secured put / covered-call rotation and vertical defined-risk spreads. |
| 4 | `remotion/src/scenes/SceneRisk.tsx` | `SceneRisk` | 360 frames (12.0 s) | Fail-closed gates: options-only, notional cap, daily cap. Rejected gates do not submit. |
| 5 | `remotion/src/scenes/SceneExecution.tsx` | `SceneExecution` | 300 frames (10.0 s) | Alpaca MCP Server 2.3.0 primary (`place_option_order`) and official Alpaca CLI fallback (`alpaca order submit`). |
| 6 | `remotion/src/scenes/SceneRunOnce.tsx` | `SceneRunOnce` | 330 frames (11.0 s) | How to run once: `python3 -m gaussoptions run --profile hackathon --backend mcp --once --dry-run` and `python3 scripts/verify-paper-mcp-order.py --dry-run`. |

Five 18-frame fades sit between scenes, so the full composition is 1830 frames, not the raw 1920-frame sum.

Render:

```bash
cd remotion
npx remotion render GaussOptionsDemo ../artifacts/demo.mp4
```
