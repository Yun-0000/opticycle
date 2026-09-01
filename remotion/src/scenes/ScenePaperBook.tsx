import {Audio} from "@remotion/media";
import {Easing, Sequence, interpolate, staticFile, useCurrentFrame} from "remotion";
import {golden} from "../golden";
import {c, typeface} from "../theme";
import {Label, SceneFrame, show} from "./SceneFrame";

const Row: React.FC<{left: string; right: string; color?: string}> = ({left, right, color = c.ink}) => (
  <div style={{display: "flex", justifyContent: "space-between", borderTop: `2px solid ${c.ink}`, padding: "15px 0 13px", color, fontSize: 22, fontWeight: 700, letterSpacing: -1}}><span>{left}</span><span>{right}</span></div>
);

export const ScenePaperBook: React.FC<{durationInFrames?: number}> = ({durationInFrames = 300}) => {
  const frame = useCurrentFrame();
  const receiptIn = interpolate(frame, [14, 44], [80, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.16, 1, 0.3, 1)});
  const stamp = show(frame, 96, 10);
  return (
    <SceneFrame durationInFrames={durationInFrames} index="BROKER RECEIPT" accent={c.acid}>
      <Audio src={staticFile("sfx/whoosh.wav")} volume={0.3} />
      <Sequence from={96} layout="none"><Audio src={staticFile("sfx/hit.wav")} volume={0.5} /></Sequence>
      <Label color={c.acid} style={{position: "absolute", left: 72, top: 138}}>SANITIZED ALPACA PAPER EVIDENCE</Label>
      <div style={{position: "absolute", left: 72, top: 220, width: 660, opacity: show(frame, 18, 16)}}>
        <div style={{fontSize: 118, fontWeight: 700, lineHeight: 0.86, letterSpacing: -9}}>BROKER<br />READBACK.</div>
        <Label color={c.gray} style={{marginTop: 44, maxWidth: 490, lineHeight: 1.55}}>THE TOOL RETURN IS NOT THE RECEIPT.</Label>
      </div>
      <div style={{position: "absolute", left: 880, top: 116 + receiptIn, width: 790, height: 820, padding: "42px 48px", background: c.paper, color: c.ink, fontFamily: typeface, rotate: "-1.1deg", opacity: show(frame, 12, 16), boxShadow: `22px 22px 0 ${c.dim}`}}>
        <div style={{display: "flex", justifyContent: "space-between", alignItems: "flex-start"}}>
          <div><div style={{fontSize: 18, fontWeight: 700, letterSpacing: 2}}>PAPER EXECUTION RECEIPT</div><div style={{fontSize: 54, fontWeight: 700, letterSpacing: -4, marginTop: 8}}>ALPACA / MLEG</div></div>
          <div style={{fontSize: 18, fontWeight: 700, textAlign: "right"}}>{golden.filledAt}<br />2026-09-01</div>
        </div>
        <div style={{marginTop: 42}}>
          <Row left="CLIENT ORDER ID" right={golden.clientOrderId} />
          <Row left={`SELL ${golden.quantity}`} right={`${golden.sellLeg} @ ${golden.sellFill}`} /><Row left={`BUY ${golden.quantity}`} right={`${golden.buyLeg} @ ${golden.buyFill}`} />
          <Row left="LIMIT / BROKER AVG" right={`${golden.limit} / ${golden.fill}`} /><Row left="EXPIRY" right={golden.expiry} />
          <Row left="EQUITY AFTER FILL" right={golden.equity} />
        </div>
        <div style={{borderTop: `2px solid ${c.ink}`, paddingTop: 18, fontSize: 15, fontWeight: 700, letterSpacing: 1.1}}>{golden.model} · MODEL_CALLED TRUE · PAPER ONLY · SANITIZED</div>
        <div style={{position: "absolute", right: 54, bottom: 52, border: `8px solid ${c.orange}`, color: c.orange, padding: "12px 20px 8px", fontSize: 58, fontWeight: 700, letterSpacing: -3, rotate: "-7deg", opacity: stamp, scale: interpolate(stamp, [0, 1], [1.35, 1], {easing: Easing.bezier(0.16, 1, 0.3, 1)})}}>MATCHED</div>
      </div>
      <div style={{position: "absolute", left: 72, bottom: 72, display: "flex", gap: 54, opacity: show(frame, 152, 14)}}>
        <Label color={c.acid}>PRICE-BOUND MATCHED</Label><Label>ALPACA GET READBACK</Label><Label color={c.gray}>MCP-ONLY MLEG</Label>
      </div>
    </SceneFrame>
  );
};
