import {Audio} from "@remotion/media";
import {Easing, Sequence, interpolate, staticFile, useCurrentFrame} from "remotion";
import {c} from "../theme";
import {Label, SceneFrame, show} from "./SceneFrame";

export const SceneRisk: React.FC<{durationInFrames?: number}> = ({durationInFrames = 240}) => {
  const frame = useCurrentFrame();
  const hash = "6e08d55b04b3ae463747259c69cb930962c5debcd22a73a0b43de6d5dacc4e53";
  const lock = show(frame, 84, 18);
  return (
    <SceneFrame durationInFrames={durationInFrames} index="03 / 06" accent={c.yellow}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.32} />
      <Sequence from={86} layout="none"><Audio src={staticFile("sfx/confirm_beep.wav")} volume={0.48} /></Sequence>
      <Label color={c.yellow} style={{position: "absolute", left: 72, top: 142}}>EXACT-PAYLOAD CERTIFICATE</Label>
      <div style={{position: "absolute", left: 72, top: 230, width: 470, opacity: show(frame, 20, 16)}}>
        <Label color={c.red}>SELL 768C</Label><div style={{height: 1, background: c.red, marginTop: 18}} />
        <Label color={c.white} style={{marginTop: 58}}>BUY 769C</Label><div style={{height: 1, background: c.white, marginTop: 18}} />
      </div>
      <div style={{position: "absolute", left: 640, top: 200, width: 540, height: 420, border: `1px solid ${c.white}`, opacity: show(frame, 42, 18)}}>
        <Label color={c.gray} style={{position: "absolute", left: 24, top: 24}}>PAYLOAD HASH / SHA-256</Label>
        <div style={{position: "absolute", left: 24, right: 24, top: 86, fontSize: 38, lineHeight: 1.35, wordBreak: "break-all", letterSpacing: -2}}>{hash}</div>
        <div style={{position: "absolute", left: 24, right: 24, bottom: 24, display: "flex", justifyContent: "space-between"}}><Label>QTY 01</Label><Label>MCP MLEG</Label><Label>SPY</Label></div>
      </div>
      <div style={{position: "absolute", left: 1180, top: 409, width: interpolate(frame, [64, 88], [0, 250], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), height: 2, background: c.yellow}} />
      <div style={{position: "absolute", right: 76, top: 258, width: 410, height: 310, background: c.yellow, color: c.black, display: "flex", alignItems: "center", justifyContent: "center", opacity: lock, scale: interpolate(frame, [84, 102], [0.82, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.16, 1, 0.3, 1)})}}>
        <div style={{fontSize: 58, fontWeight: 700, letterSpacing: -5}}>AUTHORIZED</div>
      </div>
      <Label color={c.red} style={{position: "absolute", right: 76, bottom: 98, opacity: show(frame, 124, 14), fontSize: 18}}>ANY MUTATION → VETO</Label>
    </SceneFrame>
  );
};
