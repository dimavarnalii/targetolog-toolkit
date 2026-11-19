import React, { useMemo } from "react";
import { AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { createTikTokStyleCaptions } from "@remotion/captions";
import type { Caption, TikTokPage } from "@remotion/captions";
import { loadFont } from "@remotion/google-fonts/Montserrat";

const { fontFamily } = loadFont("normal", { weights: ["900"], subsets: ["cyrillic", "latin"] });

export const LIME = "#C6FF1A";
const SWITCH_MS = 700;

const Page: React.FC<{ page: TikTokPage; y: number; accent: string }> = ({ page, y, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = page.startMs + (frame / fps) * 1000;
  const enter = spring({ frame, fps, config: { damping: 13, stiffness: 220, mass: 0.5 } });
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-start" }}>
      <div
        style={{
          marginTop: y,
          maxWidth: 960,
          textAlign: "center",
          fontFamily,
          fontWeight: 900,
          fontSize: 72,
          lineHeight: 1.18,
          textTransform: "uppercase",
          whiteSpace: "pre-wrap",
          scale: String(interpolate(enter, [0, 1], [0.82, 1])),
          translate: `0 ${interpolate(enter, [0, 1], [24, 0])}px`,
        }}
      >
        {page.tokens.map((tok, i) => {
          const active = tok.fromMs <= t && tok.toMs + 120 > t;
          const p = spring({
            frame: frame - Math.round(((tok.fromMs - page.startMs) / 1000) * fps),
            fps,
            config: { damping: 12, stiffness: 260, mass: 0.4 },
          });
          return (
            <span key={`${tok.fromMs}-${i}`}>
              {i > 0 ? " " : ""}
              <span
                style={{
                  display: "inline-block",
                  padding: "2px 10px 6px",
                  margin: "0 -6px",
                  borderRadius: 18,
                  color: active ? "#0b0b0b" : "white",
                  background: active ? accent : "transparent",
                  WebkitTextStroke: active ? "0px" : "14px black",
                  paintOrder: "stroke fill",
                  textShadow: active ? "none" : "0 8px 22px rgba(0,0,0,0.55)",
                  boxShadow: active ? "0 10px 30px rgba(0,0,0,0.35)" : "none",
                  scale: active ? String(interpolate(p, [0, 1], [0.9, 1.06])) : "1",
                  rotate: active ? "-2deg" : "0deg",
                }}
              >
                {tok.text.trim()}
              </span>
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** TikTok-style pages of 2–3 words, current word on a lime box. hide = [startSec, endSec] ranges. */
export const Captions7: React.FC<{ captions: Caption[]; y: number; hide: [number, number][]; accent?: string }> = ({
  captions,
  y,
  hide,
  accent = LIME,
}) => {
  const { fps } = useVideoConfig();
  const { pages } = useMemo(() => {
    const visible = captions
      .filter((c) => {
        const mid = (c.startMs + c.endMs) / 2000;
        return !hide.some(([a, b]) => mid >= a && mid < b);
      })
      .map((c, i, arr) => ({
        ...c,
        // new page after punctuation or before a gap (pause / hidden words)
        pageBreakAfter: /[.,!?:]$/.test(c.text.trim()) || (arr[i + 1] ? arr[i + 1].startMs - c.endMs > 400 : false),
      }));
    return createTikTokStyleCaptions({ captions: visible, combineTokensWithinMilliseconds: SWITCH_MS });
  }, [captions, hide]);

  return (
    <AbsoluteFill>
      {pages.map((page, i) => {
        const next = pages[i + 1] ?? null;
        const from = Math.round((page.startMs / 1000) * fps);
        const lastTo = page.tokens[page.tokens.length - 1].toMs;
        // hold until the next page (pauses keep the last words on screen, max 1.2 s past the word)
        // never run into a hidden range (cards / CTA)
        const hideStart = Math.min(...hide.map(([a]) => a * 1000).filter((a) => a > page.startMs), Infinity);
        const endMs = Math.min(next ? next.startMs : Infinity, lastTo + 1200, hideStart);
        const dur = Math.round((endMs / 1000) * fps) - from;
        if (dur <= 0) return null;
        return (
          <Sequence key={i} from={from} durationInFrames={dur} layout="none">
            <Page page={page} y={y} accent={accent} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
