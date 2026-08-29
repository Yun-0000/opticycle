import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { AbsoluteFill } from "remotion";
import { SceneCycle } from "./scenes/SceneCycle";
import { SceneExecution } from "./scenes/SceneExecution";
import { SceneOneLiner } from "./scenes/SceneOneLiner";
import { ScenePaperBook } from "./scenes/ScenePaperBook";
import { SceneRisk } from "./scenes/SceneRisk";
import { SceneRunOnce } from "./scenes/SceneRunOnce";

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const TRANSITION_FRAMES = 18;

export const SCENE_FRAMES = {
  oneLiner: 300,
  paperBook: 270,
  cycle: 360,
  risk: 360,
  execution: 300,
  runOnce: 360,
} as const;

export const DEMO_DURATION_IN_FRAMES =
  SCENE_FRAMES.oneLiner +
  SCENE_FRAMES.paperBook +
  SCENE_FRAMES.cycle +
  SCENE_FRAMES.risk +
  SCENE_FRAMES.execution +
  SCENE_FRAMES.runOnce -
  TRANSITION_FRAMES * 5;

const fadeTiming = linearTiming({ durationInFrames: TRANSITION_FRAMES });

export const OpticycleDemo: React.FC = () => {
  return (
    <AbsoluteFill>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.oneLiner} name="OneLiner">
          <SceneOneLiner durationInFrames={SCENE_FRAMES.oneLiner} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />

        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.paperBook} name="PaperBook">
          <ScenePaperBook durationInFrames={SCENE_FRAMES.paperBook} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />

        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.cycle} name="Cycle">
          <SceneCycle durationInFrames={SCENE_FRAMES.cycle} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />

        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.risk} name="Risk">
          <SceneRisk durationInFrames={SCENE_FRAMES.risk} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />

        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.execution} name="Execution">
          <SceneExecution durationInFrames={SCENE_FRAMES.execution} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={fadeTiming} />

        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.runOnce} name="RunOnce">
          <SceneRunOnce durationInFrames={SCENE_FRAMES.runOnce} />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
