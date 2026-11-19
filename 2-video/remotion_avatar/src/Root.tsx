import { Composition } from "remotion";
import { CrossList, KgCounter, TwoActions } from "./avatar/AvatarCards";
import { AvatarCreative, AvatarCreative45, calcAvatarCreative } from "./avatar/AvatarCreative";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* everything video-specific lives in public/<dir>/creative.json */}
      <Composition id="AvatarCreative" component={AvatarCreative} durationInFrames={1} fps={25} width={1080} height={1920} defaultProps={{ config: "example/creative.json" }} calculateMetadata={calcAvatarCreative} />
      <Composition id="AvatarCreative45" component={AvatarCreative45} durationInFrames={1} fps={25} width={1080} height={1350} defaultProps={{ config: "example/creative.json" }} calculateMetadata={calcAvatarCreative} />
      {/* card previews (optional) */}
      <Composition id="CardCounter" component={KgCounter} durationInFrames={75} fps={25} width={1080} height={1920} />
      <Composition id="CardTwo" component={TwoActions} durationInFrames={96} fps={25} width={1080} height={1920} />
      <Composition
        id="CardCross"
        component={CrossList}
        durationInFrames={110}
        fps={25}
        width={1080}
        height={1920}
        defaultProps={{
          items: [
            { text: "ПУНКТ ПЕРШИЙ", at: 0.2 },
            { text: "ПУНКТ ДРУГИЙ", at: 1.7 },
            { text: "ПУНКТ ТРЕТІЙ", at: 2.4 },
          ],
        }}
      />
    </>
  );
};
