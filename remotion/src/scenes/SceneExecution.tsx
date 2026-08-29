import { Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { colors, monoFont } from "../theme";
import { SceneFrame } from "./SceneFrame";

export const SceneExecution: React.FC<{ durationInFrames?: number }> = ({
  durationInFrames = 300,
}) => {
  const frame = useCurrentFrame();

  return (
    <SceneFrame accent={colors.teal} kicker="EXECUTION" durationInFrames={durationInFrames}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.35} />
      <Audio src={staticFile("sfx/hit.wav")} volume={0.3} />

      {/* Positive confirm chime when primary MCP highlights */}
      <Sequence from={35} layout="none">
        <Audio src={staticFile("sfx/confirm_beep.wav")} volume={0.45} />
      </Sequence>

      <div
        style={{
          position: "absolute",
          left: 96,
          top: 180,
          opacity: interpolate(frame, [14, 34], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      >
        <div style={{ fontSize: 84, fontWeight: 700, letterSpacing: -1.4 }}>
          Alpaca MCP first, CLI fallback
        </div>
        <div style={{ marginTop: 18, fontSize: 36, color: colors.muted, maxWidth: 1600 }}>
          Orders do not use alpaca-py submit_order on this path. Paper flags stay forced.
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          top: 430,
          display: "flex",
          gap: 32,
        }}
      >
        <div
          style={{
            flex: 1.15,
            backgroundColor: colors.bgLift,
            border: `1px solid ${colors.teal}`,
            boxShadow: `0 0 20px rgba(62, 224, 176, 0.15)`,
            padding: "40px 44px",
            borderRadius: 6,
            opacity: interpolate(frame, [25, 45], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          <div style={{ fontSize: 24, color: colors.teal, letterSpacing: 2, fontWeight: 700 }}>
            PRIMARY
          </div>
          <div style={{ marginTop: 16, fontSize: 44, fontWeight: 700 }}>Alpaca MCP Server 2.3.0</div>
          <div
            style={{
              marginTop: 22,
              fontFamily: monoFont,
              fontSize: 30,
              color: colors.text,
              backgroundColor: "#071018",
              padding: "18px 22px",
              borderRadius: 4,
            }}
          >
            uvx alpaca-mcp-server==2.3.0
            <br />
            place_option_order
          </div>
        </div>

        <div
          style={{
            flex: 1,
            backgroundColor: colors.bgLift,
            border: `1px solid ${colors.line}`,
            padding: "40px 44px",
            borderRadius: 6,
            opacity: interpolate(frame, [45, 65], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          <div style={{ fontSize: 24, color: colors.blue, letterSpacing: 2, fontWeight: 700 }}>
            FALLBACK
          </div>
          <div style={{ marginTop: 16, fontSize: 44, fontWeight: 700 }}>Official Alpaca CLI</div>
          <div
            style={{
              marginTop: 22,
              fontFamily: monoFont,
              fontSize: 30,
              color: colors.text,
              backgroundColor: "#071018",
              padding: "18px 22px",
              borderRadius: 4,
            }}
          >
            alpaca order submit
          </div>
        </div>
      </div>
    </SceneFrame>
  );
};
