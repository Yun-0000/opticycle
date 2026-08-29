import { Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { colors } from "../theme";
import { SceneFrame } from "./SceneFrame";

const gates = [
  { title: "Options-only", detail: "OCC symbols required. Equity tickers fail closed.", startFrame: 25 },
  { title: "Notional cap", detail: "Position size vs the $100k book. Oversize is vetoed.", startFrame: 45 },
  { title: "Daily cap", detail: "Trade-count limit. Extra cycles journal and stop.", startFrame: 65 },
];

export const SceneRisk: React.FC<{ durationInFrames?: number }> = ({
  durationInFrames = 360,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <SceneFrame accent={colors.coral} kicker="RISK GATES" durationInFrames={durationInFrames}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.35} />
      <Audio src={staticFile("sfx/hit.wav")} volume={0.3} />

      {/* Audio ticks for each VETO card */}
      <Sequence from={25} layout="none">
        <Audio src={staticFile("sfx/tick.wav")} volume={0.4} />
      </Sequence>
      <Sequence from={45} layout="none">
        <Audio src={staticFile("sfx/tick.wav")} volume={0.4} />
      </Sequence>
      <Sequence from={65} layout="none">
        <Audio src={staticFile("sfx/tick.wav")} volume={0.4} />
      </Sequence>

      <div
        style={{
          position: "absolute",
          left: 96,
          top: 176,
          opacity: interpolate(frame, [14, 34], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      >
        <div style={{ fontSize: 84, fontWeight: 700, letterSpacing: -1.2 }}>Fail closed</div>
        <div style={{ marginTop: 16, fontSize: 38, color: colors.muted }}>
          A rejected gate is journaled. No MCP or CLI call is made.
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          top: 430,
          display: "flex",
          gap: 24,
        }}
      >
        {gates.map((gate, index) => {
          const cardOpacity = interpolate(
            frame,
            [gate.startFrame, gate.startFrame + 18],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          );
          const cardTranslateY = interpolate(
            frame,
            [gate.startFrame, gate.startFrame + 18],
            [24, 0],
            {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            },
          );

          // Subtle pulse / border glow after card entrance
          const pulseProgress = Math.sin(((frame - gate.startFrame) / fps) * Math.PI * 2.5);
          const borderGlow =
            frame > gate.startFrame + 18
              ? interpolate(pulseProgress, [-1, 1], [0.3, 0.9])
              : 0.3;

          return (
            <div
              key={gate.title}
              style={{
                flex: 1,
                backgroundColor: colors.bgLift,
                border: `1px solid rgba(255, 107, 107, ${borderGlow})`,
                boxShadow: `0 0 16px rgba(255, 107, 107, ${borderGlow * 0.25})`,
                padding: "36px 32px",
                borderRadius: 6,
                opacity: cardOpacity,
                translate: `0px ${cardTranslateY}px`,
              }}
            >
              <div
                style={{
                  display: "inline-block",
                  fontSize: 22,
                  color: colors.coral,
                  letterSpacing: 2,
                  fontWeight: 700,
                  padding: "4px 10px",
                  backgroundColor: "rgba(255, 107, 107, 0.12)",
                  borderRadius: 4,
                  border: "1px solid rgba(255, 107, 107, 0.4)",
                }}
              >
                VETO
              </div>
              <div style={{ marginTop: 16, fontSize: 40, fontWeight: 700 }}>{gate.title}</div>
              <div style={{ marginTop: 14, fontSize: 28, color: colors.muted, lineHeight: 1.35 }}>
                {gate.detail}
              </div>
            </div>
          );
        })}
      </div>
    </SceneFrame>
  );
};
