import type { ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, sansFont } from "../theme";

export const SceneFrame: React.FC<{
  children: ReactNode;
  accent?: string;
  kicker?: string;
  durationInFrames: number;
}> = ({
  children,
  accent = colors.teal,
  kicker = "OPTICYCLE",
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();

  // Subtle background grid drift
  const gridOffset = interpolate(frame, [0, durationInFrames], [0, 40], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Soft ambient glow pulse
  const glowOpacity = interpolate(
    Math.sin((frame / fps) * Math.PI * 0.8),
    [-1, 1],
    [0.08, 0.18],
  );

  // Scene-level fade in and fade out to avoid crossfade overlap
  const sceneOpacity = interpolate(
    frame,
    [0, 14, durationInFrames - 16, durationInFrames],
    [0, 1, 1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.16, 1, 0.3, 1),
    },
  );

  return (
    <AbsoluteFill
      style={{
        backgroundColor: colors.bg,
        fontFamily: sansFont,
        color: colors.text,
        opacity: sceneOpacity,
      }}
    >
      {/* Background gradient */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(180deg, rgba(12,20,36,0.95) 0%, rgba(5,8,15,1) 60%)",
        }}
      />

      {/* Subtle animated high-tech grid */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `
            linear-gradient(to right, rgba(255,255,255,0.03) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255,255,255,0.03) 1px, transparent 1px)
          `,
          backgroundSize: "60px 60px",
          backgroundPosition: `${gridOffset}px ${gridOffset}px`,
          opacity: 0.7,
        }}
      />

      {/* Soft ambient color glow */}
      <div
        style={{
          position: "absolute",
          top: -200,
          left: width / 2 - 400,
          width: 800,
          height: 600,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${accent} 0%, transparent 70%)`,
          opacity: glowOpacity,
          pointerEvents: "none",
        }}
      />

      {/* Top progress accent line */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          height: 6,
          width: interpolate(frame, [0, 0.6 * fps], [0, width], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
          backgroundColor: accent,
        }}
      />

      {/* Top Header Bar */}
      <div
        style={{
          position: "absolute",
          top: 36,
          left: 96,
          fontSize: 22,
          letterSpacing: 4.5,
          fontWeight: 700,
          color: accent,
          opacity: interpolate(frame, [8, 22], [0, 1], {
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
          letterSpacing: 2.2,
          fontWeight: 500,
          color: colors.muted,
          opacity: interpolate(frame, [8, 22], [0, 1], {
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
