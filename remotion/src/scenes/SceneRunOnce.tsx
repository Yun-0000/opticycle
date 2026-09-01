import {Audio} from "@remotion/media";
import {interpolate, staticFile, useCurrentFrame} from "remotion";
import {c} from "../theme";
import {Label, SceneFrame, show} from "./SceneFrame";

export const SceneRunOnce: React.FC<{durationInFrames?: number}> = ({durationInFrames = 210}) => {
  const frame = useCurrentFrame();
  const line = interpolate(frame, [58, 96], [0, 1740], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <SceneFrame durationInFrames={durationInFrames} index="06 / 06" accent={c.acid}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.26} />
      <div style={{position: "absolute", left: 68, top: 220, fontSize: 164, fontWeight: 700, lineHeight: 0.9, letterSpacing: -12, opacity: show(frame, 12, 18)}}>TRUST<br /><span style={{color: c.acid}}>BROKER STATE.</span></div>
      <div style={{position: "absolute", left: 72, top: 638, width: line, height: 3, background: c.acid}} />
      <div style={{position: "absolute", right: 72, top: 684, fontSize: 54, fontWeight: 700, letterSpacing: -3.5, opacity: show(frame, 92, 16)}}>NOT TOOL RETURN.</div>
      <Label color={c.gray} style={{position: "absolute", left: 72, bottom: 74, opacity: show(frame, 122, 14)}}>OFFICIAL ALPACA MCP · PAPER ONLY · NO LIVE FUNDS</Label>
    </SceneFrame>
  );
};
