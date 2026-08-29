import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors } from "../theme";
import { SceneFrame } from "./SceneFrame";

export const ScenePaperBook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <SceneFrame accent={colors.gold} kicker="PAPER BOOK">
      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          top: 200,
          opacity: interpolate(frame, [6, 24], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      >
        <div style={{ fontSize: 92, fontWeight: 700, letterSpacing: -1.5, lineHeight: 1.05 }}>
          Dedicated $100,000 paper book
        </div>
        <div style={{ marginTop: 28, fontSize: 42, color: colors.muted, maxWidth: 1500, lineHeight: 1.3 }}>
          A hackathon-only paper account. Live trading stays off. Keys never appear on screen or in git.
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          bottom: 130,
          display: "flex",
          gap: 28,
          opacity: interpolate(frame, [0.55 * fps, 1.05 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {[
          ["$100,000", "Starting capital"],
          ["PAPER", "Forced environment"],
          ["NO LIVE", "ALPACA_LIVE_TRADE off"],
        ].map(([value, label]) => (
          <div
            key={label}
            style={{
              flex: 1,
              backgroundColor: colors.bgLift,
              border: `1px solid ${colors.line}`,
              padding: "36px 40px",
            }}
          >
            <div style={{ fontSize: 56, fontWeight: 700, color: colors.gold }}>{value}</div>
            <div style={{ marginTop: 12, fontSize: 28, color: colors.muted }}>{label}</div>
          </div>
        ))}
      </div>
    </SceneFrame>
  );
};
