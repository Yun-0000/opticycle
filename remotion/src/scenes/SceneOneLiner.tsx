import {Audio} from "@remotion/media";
import {Sequence, interpolate, staticFile, useCurrentFrame} from "remotion";
import {c} from "../theme";
import {Convergence, Label, SceneFrame, show} from "./SceneFrame";

export const SceneOneLiner: React.FC<{durationInFrames?: number}> = ({durationInFrames = 180}) => {
  const frame = useCurrentFrame();
  const verifiedWidth = interpolate(frame, [70, 104], [0, 380], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <SceneFrame durationInFrames={durationInFrames} index="PROOF-CARRYING AGENT" accent={c.acid}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.28} />
      <Sequence from={74} layout="none"><Audio src={staticFile("sfx/hit.wav")} volume={0.42} /></Sequence>
      <Convergence start={8} />
      <div style={{position: "absolute", left: 176, top: 104, fontSize: 224, fontWeight: 700, lineHeight: 0.82, letterSpacing: -17, opacity: show(frame, 8, 18)}}>
        PROOF<br />BEFORE<br />CAPITAL
      </div>
      <div style={{position: "absolute", left: 1480, top: 538, width: verifiedWidth, height: 3, background: c.acid, boxShadow: `0 0 12px ${c.acid}`}} />
      <Label color={c.acid} style={{position: "absolute", left: 1490, top: 490, opacity: show(frame, 66, 12)}}>VERIFIED PATH</Label>
      <Label color={c.gray} style={{position: "absolute", right: 72, bottom: 62, opacity: show(frame, 94, 12)}}>FRESH EVIDENCE / EXACT PAYLOAD / BROKER GET</Label>
    </SceneFrame>
  );
};
