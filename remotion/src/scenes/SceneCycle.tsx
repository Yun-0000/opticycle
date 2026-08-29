import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, monoFont } from "../theme";
import { SceneFrame } from "./SceneFrame";

export const SceneCycle: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <SceneFrame accent={colors.blue} kicker="AI CYCLE">
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
          Wheel and vertical spreads
        </div>
        <div style={{ marginTop: 18, fontSize: 36, color: colors.muted }}>
          Each unattended cycle asks the pin option modules for an ActionPlan, then maps it to OCC.
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
            flex: 1,
            backgroundColor: colors.bgLift,
            border: `1px solid ${colors.line}`,
            padding: "40px 44px",
            opacity: interpolate(frame, [0.5 * fps, 0.95 * fps], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: interpolate(frame, [0.5 * fps, 0.95 * fps], ["-24px 0px", "0px 0px"], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            }),
          }}
        >
          <div style={{ fontFamily: monoFont, color: colors.teal, fontSize: 26, letterSpacing: 2 }}>
            WHEEL
          </div>
          <div style={{ marginTop: 18, fontSize: 44, fontWeight: 700 }}>Cash-secured put</div>
          <div style={{ marginTop: 16, fontSize: 32, color: colors.muted, lineHeight: 1.35 }}>
            Sell a put you are willing to be assigned on. If shares land, rotate into a covered call.
          </div>
        </div>
        <div
          style={{
            flex: 1,
            backgroundColor: colors.bgLift,
            border: `1px solid ${colors.line}`,
            padding: "40px 44px",
            opacity: interpolate(frame, [0.75 * fps, 1.2 * fps], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: interpolate(frame, [0.75 * fps, 1.2 * fps], ["24px 0px", "0px 0px"], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            }),
          }}
        >
          <div style={{ fontFamily: monoFont, color: colors.blue, fontSize: 26, letterSpacing: 2 }}>
            VERTICAL
          </div>
          <div style={{ marginTop: 18, fontSize: 44, fontWeight: 700 }}>Defined-risk spread</div>
          <div style={{ marginTop: 16, fontSize: 32, color: colors.muted, lineHeight: 1.35 }}>
            Two-leg mleg credit or debit. Stock-only symbols are rejected before any submit.
          </div>
        </div>
      </div>
    </SceneFrame>
  );
};
