import {Audio} from "@remotion/media";
import {TransitionSeries, linearTiming} from "@remotion/transitions";
import {fade} from "@remotion/transitions/fade";
import {AbsoluteFill, interpolate, staticFile} from "remotion";
import {SceneCycle} from "./scenes/SceneCycle";
import {SceneExecution} from "./scenes/SceneExecution";
import {SceneOneLiner} from "./scenes/SceneOneLiner";
import {ScenePaperBook} from "./scenes/ScenePaperBook";
import {SceneRisk} from "./scenes/SceneRisk";
import {SceneRunOnce} from "./scenes/SceneRunOnce";

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const TRANSITION_FRAMES = 6;
export const SCENE_FRAMES = {oneLiner: 180, cycle: 210, risk: 240, execution: 240, paperBook: 300, runOnce: 210} as const;
export const DEMO_DURATION_IN_FRAMES = Object.values(SCENE_FRAMES).reduce((sum, frames) => sum + frames, 0) - TRANSITION_FRAMES * 5;
const transition = linearTiming({durationInFrames: TRANSITION_FRAMES});

const Soundtrack: React.FC = () => (
  <Audio
    src={staticFile("audio/opticycle-bed.mp3")}
    volume={(frame) => interpolate(frame, [0, 24, DEMO_DURATION_IN_FRAMES - 40, DEMO_DURATION_IN_FRAMES - 1], [0, 0.62, 0.62, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}
  />
);

export const OpticycleDemo: React.FC = () => (
  <AbsoluteFill>
    <Soundtrack />
    <TransitionSeries>
      <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.oneLiner}><SceneOneLiner durationInFrames={SCENE_FRAMES.oneLiner} /></TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={transition} />
      <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.cycle}><SceneCycle durationInFrames={SCENE_FRAMES.cycle} /></TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={transition} />
      <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.risk}><SceneRisk durationInFrames={SCENE_FRAMES.risk} /></TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={transition} />
      <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.execution}><SceneExecution durationInFrames={SCENE_FRAMES.execution} /></TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={transition} />
      <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.paperBook}><ScenePaperBook durationInFrames={SCENE_FRAMES.paperBook} /></TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={transition} />
      <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.runOnce}><SceneRunOnce durationInFrames={SCENE_FRAMES.runOnce} /></TransitionSeries.Sequence>
    </TransitionSeries>
  </AbsoluteFill>
);
