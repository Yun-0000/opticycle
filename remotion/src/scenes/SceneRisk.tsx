import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors } from "../theme";
import { SceneFrame } from "./SceneFrame";

const gates = [
  { title: "Options-only", detail: "OCC symbols required. Equity tickers fail closed." },
  { title: "Notional cap", detail: "Position size vs the $100k book. Oversize is vetoed." },
  { title: "Daily cap", detail: "Trade-count limit. Extra cycles journal and stop." },
];

export const SceneRisk: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <SceneFrame accent={colors.coral} kicker="RISK GATES">
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
        {gates.map((gate, index) => (
          <div
            key={gate.title}
            style={{
              flex: 1,
              backgroundColor: colors.bgLift,
              border: `1px solid ${colors.line}`,
              padding: "36px 32px",
              opacity: interpolate(
                frame,
                [0.45 * fps + index * 8, 0.85 * fps + index * 8],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
              ),
              translate: interpolate(
                frame,
                [0.45 * fps + index * 8, 0.85 * fps + index * 8],
                ["0px 24px", "0px 0px"],
                {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                  easing: Easing.bezier(0.16, 1, 0.3, 1),
                },
              ),
            }}
          >
            <div style={{ fontSize: 22, color: colors.coral, letterSpacing: 2, fontWeight: 600 }}>
              VETO
            </div>
            <div style={{ marginTop: 14, fontSize: 40, fontWeight: 700 }}>{gate.title}</div>
            <div style={{ marginTop: 14, fontSize: 28, color: colors.muted, lineHeight: 1.35 }}>
              {gate.detail}
            </div>
          </div>
        ))}
      </div>
    </SceneFrame>
  );
};
