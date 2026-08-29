import type { ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, sansFont } from "../theme";

export const SceneFrame: React.FC<{
  children: ReactNode;
  accent?: string;
  kicker?: string;
}> = ({ children, accent = colors.teal, kicker = "GAUSSOPTIONS AGENT" }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: colors.bg,
        fontFamily: sansFont,
        color: colors.text,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(180deg, rgba(12,20,36,0.9) 0%, rgba(5,8,15,1) 55%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          height: 7,
          width: interpolate(frame, [0, 0.7 * fps], [0, width], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
          backgroundColor: accent,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 36,
          left: 96,
          fontSize: 22,
          letterSpacing: 4.2,
          fontWeight: 600,
          color: accent,
          opacity: interpolate(frame, [0, 0.35 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {kicker}
      </div>
      <div
        style={{
          position: "absolute",
          top: 36,
          right: 96,
          fontSize: 20,
          letterSpacing: 2,
          color: colors.muted,
          opacity: interpolate(frame, [0, 0.35 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        ALPACA PAPER · OPTIONS ONLY
      </div>
      {children}
    </AbsoluteFill>
  );
};
