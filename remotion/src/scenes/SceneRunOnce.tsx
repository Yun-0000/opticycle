import { Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { colors, monoFont } from "../theme";
import { SceneFrame } from "./SceneFrame";

export const SceneRunOnce: React.FC<{ durationInFrames?: number }> = ({
  durationInFrames = 360,
}) => {
  const frame = useCurrentFrame();

  return (
    <SceneFrame accent={colors.blue} kicker="RUN ONCE" durationInFrames={durationInFrames}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.35} />
      <Audio src={staticFile("sfx/hit.wav")} volume={0.3} />

      {/* Terminal typing SFX for journal steps */}
      <Sequence from={65} layout="none">
        <Audio src={staticFile("sfx/terminal_tick.wav")} volume={0.4} />
      </Sequence>
      <Sequence from={115} layout="none">
        <Audio src={staticFile("sfx/terminal_tick.wav")} volume={0.4} />
      </Sequence>
      <Sequence from={165} layout="none">
        <Audio src={staticFile("sfx/confirm_beep.wav")} volume={0.45} />
      </Sequence>

      <div
        style={{
          position: "absolute",
          left: 96,
          top: 140,
          opacity: interpolate(frame, [14, 34], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      >
        <div style={{ fontSize: 74, fontWeight: 700, letterSpacing: -1.2 }}>One dry-run cycle</div>
        <div style={{ marginTop: 12, fontSize: 32, color: colors.muted }}>
          No keys required. Drop --dry-run only when paper credentials are in the environment.
        </div>
      </div>

      {/* Command Card */}
      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          top: 310,
          backgroundColor: "#071018",
          border: `1px solid ${colors.line}`,
          borderRadius: 6,
          padding: "24px 36px",
          fontFamily: monoFont,
          fontSize: 27,
          lineHeight: 1.5,
          opacity: interpolate(frame, [25, 45], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        <div style={{ color: colors.muted }}># decision → risk gate → MCP payload, no submit</div>
        <div style={{ color: colors.teal }}>
          python3 -m opticycle run --profile hackathon --backend mcp --once --dry-run
        </div>
        <div style={{ marginTop: 8, color: colors.blue }}>
          python3 scripts/verify-paper-mcp-order.py --dry-run
        </div>
      </div>

      {/* Terminal Journal Output Echo Card */}
      <div
        style={{
          position: "absolute",
          left: 96,
          right: 96,
          top: 540,
          backgroundColor: "#040912",
          border: `1px solid rgba(62, 224, 176, 0.35)`,
          boxShadow: `0 0 24px rgba(62, 224, 176, 0.1)`,
          borderRadius: 6,
          padding: "26px 36px",
          fontFamily: monoFont,
          fontSize: 24,
          lineHeight: 1.6,
          opacity: interpolate(frame, [45, 65], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        <div style={{ color: colors.muted, fontSize: 18, letterSpacing: 2, marginBottom: 10, fontWeight: 600 }}>
          JOURNAL RECORD (DRY-RUN VERIFICATION)
        </div>

        {/* Step 1: Decision */}
        <div
          style={{
            color: colors.text,
            opacity: interpolate(frame, [65, 75], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}
        >
          <span style={{ color: colors.teal, fontWeight: 600 }}>[1/3 DECISION]</span>{" "}
          strategy="wheel" | symbol="SPY260918P00550000" | action="SELL_TO_OPEN" | limit=62.09
        </div>

        {/* Step 2: Risk Gate */}
        <div
          style={{
            marginTop: 8,
            color: colors.text,
            opacity: interpolate(frame, [115, 125], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}
        >
          <span style={{ color: colors.gold, fontWeight: 600 }}>[2/3 RISK GATE]</span>{" "}
          approved=true | book=$100,000 | delta=-0.22 | vega=8.00 | OCC symbol validated
        </div>

        {/* Step 3: MCP Order */}
        <div
          style={{
            marginTop: 8,
            color: colors.text,
            opacity: interpolate(frame, [165, 175], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}
        >
          <span style={{ color: colors.blue, fontWeight: 600 }}>[3/3 MCP ORDER]</span>{" "}
          tool="place_option_order" | backend="mcp" | dry_run=true | status="OK"
        </div>
      </div>
    </SceneFrame>
  );
};
