import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors } from "../theme";
import { SceneFrame } from "./SceneFrame";

export const SceneOneLiner: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <SceneFrame>
      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          top: 210,
          opacity: interpolate(frame, [8, 28], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
          translate: interpolate(frame, [8, 28], ["0px 28px", "0px 0px"], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      >
        <div style={{ fontSize: 104, fontWeight: 700, lineHeight: 1.05, letterSpacing: -2 }}>
          GaussOptions Agent
        </div>
        <div
          style={{
            marginTop: 36,
            maxWidth: 1480,
            fontSize: 48,
            lineHeight: 1.25,
            color: colors.muted,
            fontWeight: 500,
          }}
        >
          Autonomous options-only paper agent. One cycle: decide, gate, then send an option order.
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 96,
          bottom: 120,
          display: "flex",
          gap: 18,
          opacity: interpolate(frame, [0.7 * fps, 1.15 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {["OPTIONS ONLY", "UNATTENDED CYCLE", "PAPER TRADING"].map((label) => (
          <div
            key={label}
            style={{
              border: `1px solid ${colors.line}`,
              backgroundColor: colors.bgLift,
              color: colors.teal,
              padding: "16px 22px",
              fontSize: 26,
              fontWeight: 600,
              letterSpacing: 1.4,
            }}
          >
            {label}
          </div>
        ))}
      </div>
    </SceneFrame>
  );
};
