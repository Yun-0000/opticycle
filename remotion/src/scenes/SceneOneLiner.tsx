import { Audio, Easing, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { colors } from "../theme";
import { SceneFrame } from "./SceneFrame";

export const SceneOneLiner: React.FC<{ durationInFrames?: number }> = ({
  durationInFrames = 300,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <SceneFrame durationInFrames={durationInFrames}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.35} />
      <Audio src={staticFile("sfx/hit.wav")} startFrom={0} volume={0.3} />

      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          top: 210,
          opacity: interpolate(frame, [14, 34], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
          translate: interpolate(frame, [14, 34], ["0px 24px", "0px 0px"], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      >
        <div style={{ fontSize: 104, fontWeight: 800, lineHeight: 1.05, letterSpacing: -2 }}>
          Opticycle
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
          Autonomous options-only paper trading agent on Alpaca. One cycle: decide, gate, then send an option order.
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 96,
          bottom: 120,
          display: "flex",
          gap: 20,
          opacity: interpolate(frame, [0.8 * fps, 1.2 * fps], [0, 1], {
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
              padding: "16px 24px",
              fontSize: 26,
              fontWeight: 600,
              letterSpacing: 1.5,
              borderRadius: 4,
            }}
          >
            {label}
          </div>
        ))}
      </div>
    </SceneFrame>
  );
};
