import {Audio} from "@remotion/media";
import {Sequence, staticFile, useCurrentFrame} from "remotion";
import {golden} from "../golden";
import {c} from "../theme";
import {Label, SceneFrame, show} from "./SceneFrame";

export const SceneCycle: React.FC<{durationInFrames?: number}> = ({durationInFrames = 210}) => {
  const frame = useCurrentFrame();
  return (
    <SceneFrame durationInFrames={durationInFrames} index="LLM STANCE">
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.28} />
      <Sequence from={112} layout="none"><Audio src={staticFile("sfx/tick.wav")} volume={0.4} /></Sequence>
      <Label color={c.gray} style={{position: "absolute", left: 72, top: 168, opacity: show(frame, 10, 14)}}>MODEL OUTPUT / STRICT SCHEMA</Label>
      <div style={{position: "absolute", left: 68, top: 236, fontSize: 174, fontWeight: 700, lineHeight: 0.92, letterSpacing: -13, opacity: show(frame, 16, 18)}}>
        STANCE.<br />NOT ORDER.
      </div>
      <div style={{position: "absolute", left: 74, bottom: 150, display: "flex", gap: 54, opacity: show(frame, 58, 14)}}>
        <Label color={c.acid} style={{fontSize: 22}}>■ {golden.stance}</Label>
        <Label style={{fontSize: 22}}>MODEL_CALLED = TRUE</Label>
        <Label color={c.gray} style={{fontSize: 22}}>{golden.model}</Label>
      </div>
      <div style={{position: "absolute", right: 82, top: 458, opacity: show(frame, 122, 14)}}>
        <Label color={c.red} style={{fontSize: 22}}>NO LEGS · NO QTY · NO PRICE</Label>
        <div style={{height: 2, background: c.red, marginTop: 16}} />
      </div>
    </SceneFrame>
  );
};
