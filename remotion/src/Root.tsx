import {Composition, Folder} from "remotion";
import {DEMO_DURATION_IN_FRAMES, FPS, HEIGHT, OpticycleDemo, SCENE_FRAMES, WIDTH} from "./OpticycleDemo";
import {SceneCycle} from "./scenes/SceneCycle";
import {SceneExecution} from "./scenes/SceneExecution";
import {SceneOneLiner} from "./scenes/SceneOneLiner";
import {ScenePaperBook} from "./scenes/ScenePaperBook";
import {SceneRisk} from "./scenes/SceneRisk";
import {SceneRunOnce} from "./scenes/SceneRunOnce";

export const RemotionRoot: React.FC = () => (
  <>
    <Folder name="Opticycle-Scenes">
      <Composition id="SceneOneLiner" component={SceneOneLiner} durationInFrames={SCENE_FRAMES.oneLiner} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="SceneCycle" component={SceneCycle} durationInFrames={SCENE_FRAMES.cycle} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="SceneRisk" component={SceneRisk} durationInFrames={SCENE_FRAMES.risk} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="SceneExecution" component={SceneExecution} durationInFrames={SCENE_FRAMES.execution} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="ScenePaperBook" component={ScenePaperBook} durationInFrames={SCENE_FRAMES.paperBook} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="SceneRunOnce" component={SceneRunOnce} durationInFrames={SCENE_FRAMES.runOnce} fps={FPS} width={WIDTH} height={HEIGHT} />
    </Folder>
    <Composition id="OpticycleDemo" component={OpticycleDemo} durationInFrames={DEMO_DURATION_IN_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
  </>
);
