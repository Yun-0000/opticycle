import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, monoFont } from "../theme";
import { SceneFrame } from "./SceneFrame";

export const SceneExecution: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <SceneFrame accent={colors.teal} kicker="EXECUTION">
      <div
        style={{
          position: "absolute",
          left: 96,
          top: 180,
          opacity: interpolate(frame, [4, 22], [0, 1], {
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
            padding: "40px 44px",
            opacity: interpolate(frame, [0.5 * fps, 0.9 * fps], [0, 1], {
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
            opacity: interpolate(frame, [0.75 * fps, 1.15 * fps], [0, 1], {
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
            }}
          >
            alpaca order submit
          </div>
        </div>
      </div>
    </SceneFrame>
  );
};
