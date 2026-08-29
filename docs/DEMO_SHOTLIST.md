# Opticycle — official demo shot list

Programmatic Remotion composition `OpticycleDemo` (1920×1080, 30 fps, 1860 frames = 62.0 s). Source: `remotion/`. Rendered file: `artifacts/demo.mp4`.

All motion uses `useCurrentFrame()` + `interpolate()`. Programmatic rendering with embedded SFX cues — not a screen recording.

| # | Scene file | Composition id | Duration | On-screen story | Audio / SFX cues |
| --- | --- | --- | --- | --- | --- |
| 1 | `remotion/src/scenes/SceneOneLiner.tsx` | `SceneOneLiner` | 300 frames (10.0 s) | Product one-liner: Opticycle is an autonomous options-only paper trading agent on Alpaca. Cycle: decide, gate, option order. | Soft intro whoosh + hit |
| 2 | `remotion/src/scenes/ScenePaperBook.tsx` | `ScenePaperBook` | 270 frames (9.0 s) | Dedicated $100,000 paper book. Live trading off. No keys on screen. | Scene transition whoosh + hit |
| 3 | `remotion/src/scenes/SceneCycle.tsx` | `SceneCycle` | 360 frames (12.0 s) | AI cycle: wheel cash-secured put / covered-call rotation and vertical defined-risk spreads. | Transition whoosh + hit |
| 4 | `remotion/src/scenes/SceneRisk.tsx` | `SceneRisk` | 360 frames (12.0 s) | Fail-closed gates: options-only, notional cap, daily cap. Rejected gates do not submit. | Transition whoosh + hit; lock-tick per VETO card pulse (f25, f45, f65) |
| 5 | `remotion/src/scenes/SceneExecution.tsx` | `SceneExecution` | 300 frames (10.0 s) | Alpaca MCP Server 2.3.0 primary (`place_option_order`) and official Alpaca CLI fallback (`alpaca order submit`). | Transition whoosh + hit; positive confirm chime on MCP primary highlight |
| 6 | `remotion/src/scenes/SceneRunOnce.tsx` | `SceneRunOnce` | 360 frames (12.0 s) | How to run once: `python3 -m opticycle run --profile hackathon --backend mcp --once --dry-run` and `python3 scripts/verify-paper-mcp-order.py --dry-run`. Terminal echo card shows live dry-run journal sequence. | Transition whoosh + hit; terminal line-tick echo on step 1 (decision), step 2 (risk gate), and confirm chime on step 3 (MCP order) |

Five 18-frame fades sit between scenes, so the full composition is 1860 frames (62.0 s).

Render:

```bash
cd remotion
npx remotion render OpticycleDemo ../artifacts/demo.mp4
```
