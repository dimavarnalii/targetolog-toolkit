/**
 * Avatar-creative template (coral accent).
 * Style lives here; everything video-specific lives in public/<dir>/creative.json (see CreativeConfig).
 * All times in the config are SOURCE seconds; the avatar plays at `speed` and every time is divided by it,
 * so animations keep their normal pace while the speaker is slowed down.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  AbsoluteFill,
  Audio,
  CalculateMetadataFunction,
  Easing,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useDelayRender,
  useVideoConfig,
} from "remotion";
import type { Caption } from "@remotion/captions";
import { loadFont } from "@remotion/google-fonts/Unbounded";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { Captions7 } from "./Captions7";
import { CrossList, KgCounter, TwoActions } from "./AvatarCards";

const { fontFamily: HEAD } = loadFont("normal", { weights: ["900"], subsets: ["cyrillic", "latin"] });
const { fontFamily: BODY } = loadMontserrat("normal", { weights: ["900"], subsets: ["cyrillic", "latin"] });

export const CORAL = "#FF6F91";
const FPS = 25;

type Side = "l" | "r";
type Line = { t: string; hl: boolean };
type Card =
  | { type: "counter"; at: number; dur: number; value: number; unit: string; from?: number }
  | { type: "two"; at: number; dur: number; title: string; sub: string }
  | { type: "cross"; at: number; dur: number; title: string; items: { text: string; at: number }[] };

export type CreativeConfig = {
  /** folder under public/ with src.mp4, voice, music, captions.json, sfx and b-roll */
  dir: string;
  /** source duration, seconds */
  sourceDur: number;
  speed?: number;
  accent?: string;
  musicVol?: number;
  voice?: string;
  music?: string;
  /** top — optional plate y (px in 9:16 image coords, also used by 4:5) when the default covers the face, e.g. a wide shot */
  /** size — optional hook font px for 9:16 when a long line would wrap (4:5 keeps its smaller default) */
  hook: { dur: number; lines: Line[]; top?: number; size?: number };
  plates: { at: number; dur: number; lines: Line[]; top?: number }[];
  /** optional plate kept on screen for the whole video (montage-only hook); hidden during `hide` ranges, e.g. cards and CTA */
  pinned?: { lines: Line[]; top: number; size?: number; hide?: [number, number][] };
  punches: number[];
  stickers: { src: string; at: number; dur: number; side: Side; w: number; y: number; rot: number }[];
  clips: { src: string; at: number; dur: number; ss: number; side: Side }[];
  cards: Card[];
  cta: { at: number; lines: string[] };
  captionHide: [number, number][];
};

export type AvatarCreativeProps = { config: string; cropTop?: number; cfg?: CreativeConfig };

const zoomAt = (t: number, hookDur: number, punches: number[]) => {
  let z = 1 + interpolate(t, [0, hookDur], [0, 0.07], { extrapolateRight: "clamp", easing: Easing.inOut(Easing.quad) });
  if (t > hookDur) z = 1.07 - interpolate(t, [hookDur, hookDur + 0.5], [0, 0.04], { extrapolateRight: "clamp" });
  for (const p of punches) {
    const env =
      interpolate(t, [p - 0.04, p + 0.12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }) *
      interpolate(t, [p + 1.0, p + 1.35], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.quad) });
    z += 0.14 * env;
  }
  return z;
};

const Plate: React.FC<{ dur: number; lines: Line[]; top: number; size: number; accent: string }> = ({ dur, lines, top, size, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const out = interpolate(frame, [dur * fps - 8, dur * fps], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-start", opacity: out }}>
      <div style={{ marginTop: top, display: "flex", flexDirection: "column", gap: 14 }}>
        {lines.map(({ t, hl }, i) => {
          const p = spring({ frame: frame - i * 5, fps, config: { damping: 11, stiffness: 200, mass: 0.6 } });
          return (
            <div
              key={t}
              style={{
                alignSelf: "center",
                fontFamily: HEAD,
                fontWeight: 900,
                fontSize: size,
                lineHeight: 1.05,
                padding: "10px 28px 16px",
                borderRadius: 20,
                color: hl ? "#0b0b0b" : "white",
                background: hl ? accent : "rgba(12,12,16,0.88)",
                boxShadow: "0 14px 40px rgba(0,0,0,0.45)",
                scale: String(interpolate(p, [0, 1], [0.5, 1])),
                opacity: p,
                rotate: `${i % 2 ? 2 : -2}deg`,
                translate: `${interpolate(p, [0, 1], [i % 2 ? 120 : -120, 0])}px 0`,
              }}
            >
              {t}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Sticker: React.FC<{ src: string; dur: number; side: Side; w: number; y: number; rot: number }> = ({ src, dur, side, w, y, rot }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame, fps, config: { damping: 10, stiffness: 170, mass: 0.6 } });
  const out = interpolate(frame, [dur * fps - 6, dur * fps], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const bob = Math.sin(frame / 7) * 6;
  return (
    <AbsoluteFill>
      <Img
        src={staticFile(src)}
        style={{
          position: "absolute",
          top: y + bob,
          [side === "l" ? "left" : "right"]: 30,
          width: w,
          rotate: `${interpolate(p, [0, 1], [side === "l" ? -40 : 40, rot])}deg`,
          scale: String(interpolate(p, [0, 1], [0.2, 1]) * out),
          filter:
            "drop-shadow(0 0 4px white) drop-shadow(0 0 4px white) drop-shadow(0 0 3px white) drop-shadow(0 18px 30px rgba(0,0,0,0.5))",
        }}
      />
    </AbsoluteFill>
  );
};

const ClipCard: React.FC<{ src: string; dur: number; ss: number; side: Side }> = ({ src, dur, ss, side }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame, fps, config: { damping: 12, stiffness: 160, mass: 0.7 } });
  const out = interpolate(frame, [dur * fps - 6, dur * fps], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const dir = side === "r" ? 1 : -1;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          [side === "r" ? "right" : "left"]: 40,
          top: 700,
          width: 420,
          height: 540,
          borderRadius: 34,
          overflow: "hidden",
          border: "10px solid white",
          boxShadow: "0 24px 60px rgba(0,0,0,0.55)",
          rotate: `${interpolate(p, [0, 1], [18, 5]) * dir}deg`,
          translate: `${interpolate(p, [0, 1], [600, 0]) * dir}px 0`,
          opacity: out,
        }}
      >
        <OffthreadVideo src={staticFile(src)} muted startFrom={Math.round(ss * fps)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
    </AbsoluteFill>
  );
};

const Cta: React.FC<{ top: number; accent: string; lines: string[] }> = ({ top, accent, lines }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame, fps, config: { damping: 10, stiffness: 180, mass: 0.6 } });
  const pulse = 1 + Math.sin(frame / 4) * 0.035;
  const arrow = Math.abs(Math.sin(frame / 5)) * 18;
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-start" }}>
      <div
        style={{
          marginTop: top,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 6,
          scale: String(interpolate(p, [0, 1], [0.3, 1]) * pulse),
          opacity: p,
        }}
      >
        <div
          style={{
            fontFamily: BODY,
            fontWeight: 900,
            fontSize: 64,
            lineHeight: 1.1,
            textAlign: "center",
            color: "#0b0b0b",
            background: accent,
            borderRadius: 999,
            padding: "22px 54px 26px",
            boxShadow: `0 0 0 8px ${accent}59, 0 18px 50px rgba(0,0,0,0.5)`,
          }}
        >
          {lines.map((l, i) => (
            <React.Fragment key={l}>
              {i > 0 ? <br /> : null}
              {l}
            </React.Fragment>
          ))}
        </div>
        <div style={{ fontSize: 90, color: accent, translate: `0 ${arrow}px`, textShadow: "0 6px 20px rgba(0,0,0,0.6)" }}>▼</div>
      </div>
    </AbsoluteFill>
  );
};

/** cropTop > 0: layout for a 4:5 crop starting cropTop px below the 9:16 top edge. */
export const AvatarCreative: React.FC<AvatarCreativeProps> = ({ cfg, cropTop = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const c = cfg as CreativeConfig; // filled by calculateMetadata
  const speed = c.speed ?? 0.9;
  const accent = c.accent ?? CORAL;
  const d = (p: string) => staticFile(`${c.dir}/${p}`);
  const total = Math.round((c.sourceDur / speed) * fps);
  const t = frame / fps;
  const [captions, setCaptions] = useState<Caption[] | null>(null);
  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender());

  const load = useCallback(async () => {
    try {
      const res = await fetch(staticFile(`${c.dir}/captions.json`));
      const raw: Caption[] = await res.json();
      setCaptions(
        raw.map((x) => ({ ...x, startMs: x.startMs / speed, endMs: x.endMs / speed, timestampMs: x.timestampMs === null ? null : x.timestampMs / speed })),
      );
      continueRender(handle);
    } catch (e) {
      cancelRender(e);
    }
  }, [continueRender, cancelRender, handle, c.dir, speed]);

  useEffect(() => {
    load();
  }, [load]);

  // source seconds -> output frames
  const f = (s: number) => Math.round((s / speed) * fps);
  const plateTop = cropTop ? cropTop + 40 : 150;
  const plateSize = cropTop ? 64 : 76;
  const plates = [{ at: 0, dur: c.hook.dur, lines: c.hook.lines, top: c.hook.top, size: c.hook.size }, ...c.plates].filter((p) => p.lines.length);
  const pinnedOpacity = (c.pinned?.hide ?? []).reduce(
    (o, [a, b]) => o * interpolate(t * speed, [a - 0.2, a, b, b + 0.2], [1, 0, 0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
    1,
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <AbsoluteFill style={{ scale: String(zoomAt(t * speed, c.hook.dur, c.punches)), transformOrigin: "50% 36%" }}>
        <OffthreadVideo
          src={d("src.mp4")}
          muted
          playbackRate={speed}
          style={{ width: "100%", height: "100%", filter: "contrast(1.07) saturate(1.18) brightness(1.03)" }}
        />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.45) 100%)" }} />

      {c.stickers.map((s, i) => (
        <Sequence key={`s${i}`} from={f(s.at)} durationInFrames={f(s.dur)}>
          <Sticker {...s} src={`${c.dir}/${s.src}`} dur={s.dur / speed} />
          <Audio src={d("pop.mp3")} volume={0.35} />
        </Sequence>
      ))}
      {c.clips.map((k, i) => (
        <Sequence key={`k${i}`} from={f(k.at)} durationInFrames={f(k.dur)}>
          <ClipCard {...k} src={`${c.dir}/${k.src}`} dur={k.dur / speed} />
          <Audio src={d("whoosh.mp3")} volume={0.3} />
        </Sequence>
      ))}
      {c.cards.map((k, i) => (
        <Sequence key={`c${i}`} from={f(k.at)} durationInFrames={f(k.dur)}>
          {k.type === "counter" ? <KgCounter value={k.value} unit={k.unit} from={k.from} /> : null}
          {k.type === "two" ? (
            <>
              <TwoActions accent={accent} title={k.title} sub={k.sub} />
              <Audio src={d("whoosh.mp3")} volume={0.3} />
            </>
          ) : null}
          {k.type === "cross" ? <CrossList accent={accent} title={k.title} items={k.items.map((it) => ({ ...it, at: it.at / speed }))} /> : null}
        </Sequence>
      ))}
      <Sequence from={f(c.cta.at)}>
        <Cta top={cropTop ? 1200 : 1280} accent={accent} lines={c.cta.lines} />
        <Audio src={d("pop.mp3")} volume={0.35} />
      </Sequence>

      {captions ? (
        <Captions7 captions={captions} y={1340} accent={accent} hide={c.captionHide.map(([a, b]) => [a / speed, b / speed] as [number, number])} />
      ) : null}

      {plates.map((p) => (
        <Sequence key={`p${p.at}`} from={f(p.at)} durationInFrames={f(p.dur)}>
          <Plate dur={p.dur / speed} lines={p.lines} top={p.top ?? plateTop} size={"size" in p && p.size && !cropTop ? p.size : plateSize} accent={accent} />
          <Audio src={d("whoosh.mp3")} volume={0.3} />
        </Sequence>
      ))}

      {c.pinned ? (
        <AbsoluteFill style={{ opacity: pinnedOpacity }}>
          <Plate dur={total / fps} lines={c.pinned.lines} top={c.pinned.top} size={c.pinned.size ?? plateSize} accent={accent} />
          <Audio src={d("whoosh.mp3")} volume={0.3} />
        </AbsoluteFill>
      ) : null}

      <div style={{ position: "absolute", top: cropTop, left: 0, height: 12, width: `${Math.min(1, frame / total) * 100}%`, background: accent }} />

      <Audio src={d(c.voice ?? "voice_090.wav")} />
      <Audio src={d(c.music ?? "music.mp3")} volume={c.musicVol ?? 0.05} />
    </AbsoluteFill>
  );
};

export const CROP_45 = 240;

/** 4:5 (1080×1350): the 9:16 layout shifted up by CROP_45. */
export const AvatarCreative45: React.FC<AvatarCreativeProps> = (props) => (
  <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "black" }}>
    <div style={{ position: "absolute", left: 0, top: -CROP_45, width: 1080, height: 1920 }}>
      <AvatarCreative {...props} cropTop={CROP_45} />
    </div>
  </AbsoluteFill>
);

/** Reads public/<config>, sets duration = sourceDur / speed. Render another video with --props='{"config":"<dir>/creative.json"}'. */
export const calcAvatarCreative: CalculateMetadataFunction<AvatarCreativeProps> = async ({ props }) => {
  const cfg: CreativeConfig = await (await fetch(staticFile(props.config))).json();
  return { durationInFrames: Math.ceil((cfg.sourceDur / (cfg.speed ?? 0.9)) * FPS), fps: FPS, props: { ...props, cfg } };
};
