import type {ReactNode} from "react";
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from "remotion";
import {c, typeface} from "../theme";

export const show = (frame: number, start: number, duration = 12) =>
  interpolate(frame, [start, start + duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1)
  });

export const Label: React.FC<{children: ReactNode; color?: string; style?: React.CSSProperties}> = ({children, color = c.white, style}) => (
  <div style={{color, fontSize: 16, fontWeight: 700, letterSpacing: 2.4, lineHeight: 1.25, textTransform: "uppercase", ...style}}>
    {children}
  </div>
);

export const Corner: React.FC<{x: number; y: number; flipX?: boolean; flipY?: boolean; color?: string}> = ({x, y, flipX, flipY, color = c.white}) => (
  <div style={{position: "absolute", left: flipX ? undefined : x, right: flipX ? x : undefined, top: flipY ? undefined : y, bottom: flipY ? y : undefined, width: 22, height: 22, borderLeft: flipX ? undefined : `1px solid ${color}`, borderRight: flipX ? `1px solid ${color}` : undefined, borderTop: flipY ? undefined : `1px solid ${color}`, borderBottom: flipY ? `1px solid ${color}` : undefined}} />
);

export const SceneFrame: React.FC<{children: ReactNode; durationInFrames: number; index: string; accent?: string}> = ({children, durationInFrames, index, accent = c.white}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 5, durationInFrames - 5, durationInFrames - 1], [0, 1, 1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{backgroundColor: c.black, color: c.white, fontFamily: typeface, opacity}}>
      <Corner x={28} y={28} color={accent} />
      <Corner x={28} y={28} flipX color={accent} />
      <Corner x={28} y={28} flipY color={accent} />
      <Corner x={28} y={28} flipX flipY color={accent} />
      <div style={{position: "absolute", left: 56, top: 46, display: "flex", gap: 18, alignItems: "center"}}>
        <Label color={accent}>OPTICYCLE</Label>
        <div style={{width: 44, height: 1, background: c.dim}} />
        <Label color={c.gray}>{index}</Label>
      </div>
      <Label color={c.gray} style={{position: "absolute", right: 56, top: 46}}>PAPER / MCP MLEG</Label>
      <div style={{position: "absolute", inset: 0, overflow: "hidden"}}>{children}</div>
    </AbsoluteFill>
  );
};

const seeds = Array.from({length: 86}, (_, i) => ({x: 30 + ((i * 83) % 980), y: 70 + ((i * 137) % 920), alpha: 0.14 + ((i * 17) % 52) / 100, delay: (i * 7) % 45}));

export const Convergence: React.FC<{targetX?: number; targetY?: number; color?: string; start?: number}> = ({targetX = 1490, targetY = 540, color = c.white, start = 10}) => {
  const frame = useCurrentFrame();
  return <>{seeds.map((seed, i) => {
    const dx = targetX - seed.x;
    const dy = targetY - seed.y;
    const length = Math.sqrt(dx * dx + dy * dy);
    const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
    const p = show(frame, start + seed.delay, 22);
    const trim = interpolate(p, [0, 1], [0.08, 1]);
    return <div key={i} style={{position: "absolute", left: seed.x, top: seed.y, width: length * trim, height: 1, background: color, opacity: seed.alpha * p, transformOrigin: "0 50%", rotate: `${angle}deg`}}><div style={{position: "absolute", right: -2, top: -1.5, width: 4, height: 4, background: color}} /></div>;
  })}</>;
};
