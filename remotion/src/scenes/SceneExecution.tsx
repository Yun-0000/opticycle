import {Audio} from "@remotion/media";
import {Sequence, interpolate, staticFile, useCurrentFrame} from "remotion";
import {c} from "../theme";
import {Label, SceneFrame, show} from "./SceneFrame";

export const SceneExecution: React.FC<{durationInFrames?: number}> = ({durationInFrames = 240}) => {
  const frame = useCurrentFrame();
  const stopWidth = interpolate(frame, [36, 66], [0, 560], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const lookupWidth = interpolate(frame, [92, 126], [0, 760], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <SceneFrame durationInFrames={durationInFrames} index="04 / 06" accent={c.red}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.28} />
      <Sequence from={126} layout="none"><Audio src={staticFile("sfx/confirm_beep.wav")} volume={0.45} /></Sequence>
      <div style={{position: "absolute", left: 68, top: 178, fontSize: 178, fontWeight: 700, letterSpacing: -13, lineHeight: 0.86, opacity: show(frame, 12, 18)}}>
        TIMEOUT<br /><span style={{color: c.red}}>≠ RETRY</span>
      </div>
      <div style={{position: "absolute", left: 76, top: 598, width: 1220, height: 170}}>
        <div style={{position: "absolute", left: 0, top: 38, width: stopWidth, height: 2, background: c.red}} />
        <div style={{position: "absolute", left: 556, top: 28, width: 22, height: 22, background: c.red, opacity: show(frame, 62, 5)}} />
        <Label color={c.red} style={{position: "absolute", left: 0, top: 0, opacity: show(frame, 24, 12)}}>RESPONSE LOST / ORDER STATE UNKNOWN</Label>
        <div style={{position: "absolute", left: 578, top: 104, width: lookupWidth, height: 2, background: c.yellow}} />
        <Label color={c.yellow} style={{position: "absolute", left: 578, top: 70, opacity: show(frame, 86, 12)}}>LOOK UP THE SAME CLIENT ID</Label>
        <div style={{position: "absolute", left: 1326, top: 94, width: 22, height: 22, background: c.acid, opacity: show(frame, 122, 5)}} />
      </div>
      <div style={{position: "absolute", right: 76, top: 248, width: 490, opacity: show(frame, 128, 16)}}>
        <Label color={c.gray}>CLIENT ORDER ID</Label>
        <div style={{fontSize: 29, marginTop: 16, letterSpacing: -1.5}}>oc-715ad36a630d408e</div>
        <div style={{height: 1, background: c.dim, margin: "26px 0"}} />
        <Label color={c.acid} style={{fontSize: 24}}>FOUND / FILLED</Label>
      </div>
      <div style={{position: "absolute", left: 76, bottom: 82, display: "flex", gap: 56, opacity: show(frame, 154, 14)}}>
        <Label>SUBMITS 01</Label><Label color={c.red}>SECOND SUBMIT FALSE</Label>
      </div>
    </SceneFrame>
  );
};
