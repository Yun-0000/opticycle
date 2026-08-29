import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, monoFont } from "../theme";
import { SceneFrame } from "./SceneFrame";

export const SceneRunOnce: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <SceneFrame accent={colors.blue} kicker="RUN ONCE">
      <div
        style={{
          position: "absolute",
          left: 96,
          top: 176,
          opacity: interpolate(frame, [4, 20], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      >
        <div style={{ fontSize: 84, fontWeight: 700, letterSpacing: -1.4 }}>One dry-run cycle</div>
        <div style={{ marginTop: 16, fontSize: 36, color: colors.muted }}>
          No keys required. Drop --dry-run only when paper credentials are in the environment.
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          top: 400,
          backgroundColor: "#071018",
          border: `1px solid ${colors.line}`,
          padding: "40px 48px",
          fontFamily: monoFont,
          fontSize: 34,
          lineHeight: 1.55,
          opacity: interpolate(frame, [0.45 * fps, 0.9 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        <div style={{ color: colors.muted }}># decision → risk gate → MCP payload, no submit</div>
        <div style={{ color: colors.teal }}>
          python3 -m gaussoptions run --profile hackathon --backend mcp --once --dry-run
        </div>
        <div style={{ marginTop: 18, color: colors.blue }}>
          python3 scripts/verify-paper-mcp-order.py --dry-run
        </div>
      </div>
    </SceneFrame>
  );
};
