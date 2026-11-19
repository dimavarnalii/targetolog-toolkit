import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/Montserrat";

const { fontFamily } = loadFont("normal", { weights: ["800", "900"], subsets: ["cyrillic", "latin"] });
const YELLOW = "#FFE500";
const RED = "#FF3B3B";
const GREEN = "#3CE07A";

const usePop = (delay = 0) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - delay, fps, config: { damping: 12, stiffness: 180, mass: 0.6 } });
};

const useOut = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return interpolate(frame, [durationInFrames - 6, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
};

/** Counter stamp ("100 UNIT"): counts up fast, overshoots in scale, slight tilt. */
export const KgCounter: React.FC<{ readonly value?: number; readonly unit?: string; readonly from?: number }> = ({
  value: target = 100,
  unit = "",
  from = 0,
}) => {
  const frame = useCurrentFrame();
  const pop = usePop(0);
  const out = useOut();
  const value = Math.round(
    interpolate(frame, [0, 14], [from, target], { extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }),
  );
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", opacity: out }}>
      <div
        style={{
          marginTop: 930,
          scale: String(interpolate(pop, [0, 1], [0.4, 1])),
          rotate: "-4deg",
          background: RED,
          borderRadius: 28,
          padding: "14px 46px",
          boxShadow: "0 14px 40px rgba(0,0,0,0.45)",
          fontFamily,
          fontWeight: 900,
          fontSize: 150,
          color: "white",
          letterSpacing: -2,
          lineHeight: 1,
        }}
      >
        {value} <span style={{ fontSize: 90 }}>{unit}</span>
      </div>
    </AbsoluteFill>
  );
};

/** Title card with two numbered badges and a subtitle. */
export const TwoActions: React.FC<{ readonly accent?: string; readonly title?: string; readonly sub?: string }> = ({
  accent = GREEN,
  title = "ЗАГОЛОВОК",
  sub: subText = "ПІДПИС",
}) => {
  const head = usePop(0);
  const b1 = usePop(8);
  const b2 = usePop(14);
  const sub = usePop(36);
  const out = useOut();
  const badge = (n: number, p: number) => (
    <div
      style={{
        width: 210,
        height: 210,
        borderRadius: 105,
        background: accent,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 130,
        fontWeight: 900,
        color: "#0b1a10",
        scale: String(p),
        boxShadow: "0 12px 36px rgba(0,0,0,0.4)",
      }}
    >
      {n}
    </div>
  );
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-start", fontFamily, opacity: out }}>
      <div
        style={{
          marginTop: 900,
          background: "rgba(10,10,14,0.82)",
          borderRadius: 40,
          padding: "40px 60px 46px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 28,
          scale: String(interpolate(head, [0, 1], [0.7, 1])),
          opacity: head,
        }}
      >
        <div style={{ fontSize: 92, fontWeight: 900, color: YELLOW, letterSpacing: -1 }}>{title}</div>
        <div style={{ display: "flex", gap: 60 }}>
          {badge(1, b1)}
          {badge(2, b2)}
        </div>
        <div style={{ fontSize: 50, fontWeight: 800, color: "white", opacity: sub, textAlign: "center" }}>
          {subText}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** Crossed-out list: each line pops in at its word, then a red strike draws across it. */
export const CrossList: React.FC<{ readonly items: { text: string; at: number }[]; readonly accent?: string; readonly title?: string }> = ({
  items,
  accent = GREEN,
  title = "БЕЗ:",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const out = useOut();
  const plate = usePop(0);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-start", fontFamily, opacity: out }}>
      <div
        style={{
          marginTop: 880,
          background: "rgba(10,10,14,0.82)",
          borderRadius: 40,
          padding: "36px 56px",
          display: "flex",
          flexDirection: "column",
          gap: 22,
          opacity: plate,
          scale: String(interpolate(plate, [0, 1], [0.85, 1])),
        }}
      >
        <div style={{ fontSize: 60, fontWeight: 900, color: accent, textAlign: "center" }}>{title}</div>
        {items.map((it) => {
          const f0 = Math.round(it.at * fps);
          const p = spring({ frame: frame - f0, fps, config: { damping: 14, stiffness: 200 } });
          const strike = interpolate(frame, [f0 + 6, f0 + 16], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.out(Easing.quad),
          });
          return (
            <div
              key={it.text}
              style={{
                fontSize: 62,
                fontWeight: 900,
                color: "white",
                whiteSpace: "nowrap",
                opacity: p,
                translate: `${interpolate(p, [0, 1], [-60, 0])}px 0`,
              }}
            >
              <span style={{ color: RED, marginRight: 20 }}>✕</span>
              <span style={{ position: "relative" }}>
                {it.text}
                <span
                  style={{
                    position: "absolute",
                    left: -4,
                    top: "50%",
                    height: 9,
                    borderRadius: 5,
                    width: `calc(${strike * 100}% + 8px)`,
                    background: RED,
                  }}
                />
              </span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
