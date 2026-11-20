import React, {useMemo} from 'react';
import {
	AbsoluteFill,
	Audio,
	Easing,
	Img,
	interpolate,
	OffthreadVideo,
	Sequence,
	spring,
	staticFile,
	useCurrentFrame,
} from 'remotion';
import {BOX_GREEN, clamp, FONT} from './theme';

type Word = {t: string; emph: boolean};
type Group = {start: number; end: number; words: Word[]};
type BRollItem = {file: string; kind: 'photo' | 'video'; start: number; dur: number; clipStart: number; portrait: boolean; idx: number; bg?: string; dim?: number;
	focus?: [number, number][]; srcW?: number; srcH?: number; pip?: boolean};
type Overlay = {
	type: 'cta_arrows' | 'title' | 'ig_feed';
	start: number;
	end: number;
	text?: string;
	frame?: string;
	top?: number;
	bottom?: number;
	broll?: string;
	brollKind?: 'photo' | 'video';
	brollStart?: number;
	clipStart?: number;
};

/** Візуальний хук на першу фразу (стиль vit): split — верх сток, низ аватар; text — кінетичний текст + punch-in зум. */
type VHook = {
	mode: 'split' | 'text';
	start: number;
	end: number;
	split: number;
	keyAt: number;
	clips: {file: string; start: number; dur: number; clipStart: number}[];
	pages: {start: number; end: number; words: {t: string; start: number; key: boolean}[]}[];
};

export type CreativeProps = {
	fps: number;
	width: number;
	height: number;
	durationInFrames: number;
	master: string;
	audio: string;
	masterW: number;
	masterH: number;
	crop: {w: number; h: number; path: [number, number, number][]};
	faceY: number;
	cuts: number[];
	style: 'box' | 'pyshka' | 'vit';
	subBottom: number;
	groups: Group[];
	broll: BRollItem[];
	overlays: Overlay[];
	boxColor?: string;
	joinZooms?: [number, number, number][];
	phraseZoom?: [number, number, number][];
	plates?: {start: number; end: number; text: string; color: string; keep?: boolean}[];
	plateTop?: number; // 23.10: MONTAGE_PLATE_TOP — своя висота плашок (частка кадру), напр. 59.1 з ілюстрацією внизу
	dimSpeaker?: number;
	joinGains?: [number, number, number][];
	vhook?: VHook;
	faceYReal?: number;
	banner?: string;
	stickers?: {file: string; start: number; dur: number; side: string; idx: number}[];
	/** правка замовника: світлі жіночні плашки з округлими кутами, наклейки — фото-вирізки без гойдання, одне за раз */
	soft?: boolean;
};

export const creativeDefaults: CreativeProps = {
	fps: 25, width: 1080, height: 1920, durationInFrames: 250, master: '', audio: '', masterW: 1920, masterH: 1080,
	crop: {w: 608, h: 1080, path: [[0, 656, 0]]}, faceY: 0.3, cuts: [0], style: 'box', subBottom: 0.44,
	groups: [], broll: [], overlays: [],
};

// ---------- спікер: кадрування за обличчям + повільні зуми на довгих планах ----------

const cropAt = (p: CreativeProps, t: number): [number, number] => {
	const path = p.crop.path;
	let lo = 0;
	let hi = path.length - 1;
	while (lo < hi) {
		const mid = (lo + hi + 1) >> 1;
		if (path[mid][0] <= t) lo = mid;
		else hi = mid - 1;
	}
	const a = path[lo];
	const b = path[Math.min(lo + 1, path.length - 1)];
	// на монтажному стику камера «стрибає» разом зі склейкою — без проміжних положень
	const cutBetween = p.cuts.some((c) => c > a[0] && c <= b[0]);
	if (b[0] <= a[0] || cutBetween) return [a[1], a[2]];
	const k = (t - a[0]) / (b[0] - a[0]);
	return [a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
};

/** Інтервали, де видно спікерку (без перебивок). Монтажер: якщо мова тримається понад ~10 с — додавати зум 10–20%. */
const speakerZooms = (p: CreativeProps) => {
	const total = p.durationInFrames / p.fps;
	const covered = p.broll.map((b) => [b.start, b.start + b.dur]).sort((x, y) => x[0] - y[0]);
	const free: [number, number][] = [];
	let cur = 0;
	for (const [s, e] of covered) {
		if (s > cur) free.push([cur, s]);
		cur = Math.max(cur, e);
	}
	if (cur < total) free.push([cur, total]);
	return free.filter(([s, e]) => e - s >= 4);
};

const Speaker: React.FC<{p: CreativeProps}> = ({p}) => {
	const frame = useCurrentFrame();
	const t = frame / p.fps;
	const zones = useMemo(() => speakerZooms(p), [p]);
	const title = p.overlays.find((o) => o.type === 'title');
	let z = 1;
	const vh = p.vhook;
	if (vh && vh.mode === 'text' && t >= vh.start && t < vh.end) {
		// візуальний хук text: плавний punch-in 1.0→1.15 на всю фразу + різкий дозум на ключовому слові
		z = interpolate(t, [vh.start, vh.end], [1, 1.15], {...clamp, easing: Easing.out(Easing.quad)});
		z *= interpolate(t, [vh.keyAt, vh.keyAt + 0.1], [1, 1.12], {...clamp, easing: Easing.out(Easing.cubic)});
	} else if (title && t < title.end) {
		// хук: швидкий наїзд на початку (монтажер: «супер швидкий зум» на хуку)
		z = interpolate(t, [0, Math.max(0.3, title.end)], [1, 1.15], {...clamp, easing: Easing.out(Easing.cubic)});
	} else if ((p.phraseZoom ?? []).some(([a, b]) => t >= a && t < b)) {
		// кожна фраза — новий план (різкий стрибок 1.0 ↔ 1.22) + ледь помітний дрейф усередині фрази
		const [a, b, zz] = (p.phraseZoom ?? []).find(([s0, e0]) => t >= s0 && t < e0)!;
		z = zz * interpolate(t, [a, b], [1, 1.03], clamp);
	} else {
		const zone = zones.find(([s, e]) => t >= s && t < e);
		if (zone) {
			const i = zones.indexOf(zone);
			const [a, b] = i % 2 === 0 ? [1, 1.12] : [1.12, 1];
			z = interpolate(t, zone, [a, b], {...clamp, easing: Easing.inOut(Easing.quad)});
		}
	}
	// контроль стиків (joins.py): наїзд після відкритого стику, вирівнювання яскравості дубля
	const jz = (p.joinZooms ?? []).find(([a, b]) => t >= a && t < b);
	if (jz) z = Math.min(1.3, z * jz[2]);
	const jg = (p.joinGains ?? []).find(([a, b]) => t >= a && t < b);
	const [x, y] = cropAt(p, t);
	const s = p.width / p.crop.w;
	return (
		<AbsoluteFill style={{overflow: 'hidden', backgroundColor: 'black'}}>
			<AbsoluteFill style={{transform: `scale(${z})`, transformOrigin: `50% ${p.faceY * 100}%`,
				filter: jg ? `brightness(${jg[2]})` : undefined}}>
				<div
					style={{
						position: 'absolute', left: 0, top: 0, width: p.masterW, height: p.masterH,
						transformOrigin: '0 0', transform: `translate(${-x * s}px, ${-y * s}px) scale(${s})`,
					}}
				>
					<OffthreadVideo src={staticFile(p.master)} muted style={{width: p.masterW, height: p.masterH}} />
				</div>
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

// ---------- перебивки: поява з легким «наїздом» і спалахом, фото завжди рухається ----------

/** Горизонтальний кадр у вертикальному вікні за обличчям (reframe.py): яку частку ширини видно і де вікно.
 * Повертає object-position (лівий край вікна) і точку наїзду Ken Burns (обличчя), обидва у %. */
const focusWindow = (b: BRollItem, t: number, frameAspect: number): [number, number] => {
	const path = b.focus as [number, number][];
	let cx = path[0][1];
	for (let i = 1; i < path.length; i++) {
		if (path[i][0] >= t) {
			const [t0, x0] = path[i - 1];
			const [t1, x1] = path[i];
			cx = x0 + (x1 - x0) * Math.min(1, Math.max(0, (t - t0) / Math.max(1e-6, t1 - t0)));
			break;
		}
		cx = path[i][1];
	}
	const v = Math.min(1, frameAspect / ((b.srcW as number) / (b.srcH as number)));
	if (v >= 1) return [50, 50];
	const left = Math.min(Math.max(cx - v / 2, 0), 1 - v);
	return [(left / (1 - v)) * 100, ((cx - left) / v) * 100];
};

const BRoll: React.FC<{b: BRollItem; fps: number; aspect: number; chained?: boolean}> = ({b, fps, aspect, chained}) => {
	const f = useCurrentFrame();
	const dur = Math.max(1, Math.round(b.dur * fps));
	// впритул за іншою перебивкою — без напівпрозорої появи: інакше на 3 кадри крізь неї видно спікерку
	// (а під суміжними перебивками часто захований стик дублів)
	const enter = chained ? 1 : interpolate(f, [0, 3], [0, 1], clamp);
	const pop = interpolate(f, [0, 6], [1.08, 1], {...clamp, easing: Easing.out(Easing.cubic)});
	const kb = interpolate(f, [0, dur], b.idx % 2 === 0 ? [1, 1.09] : [1.09, 1], clamp);
	const flash = interpolate(f, [0, 4], [0.5, 0], clamp);
	const media = (style: React.CSSProperties) =>
		b.kind === 'photo' ? (
			<Img src={staticFile(b.file)} style={style} />
		) : (
			<OffthreadVideo src={staticFile(b.file)} trimBefore={Math.round(b.clipStart * fps)} muted style={style} />
		);
	return (
		<AbsoluteFill style={{opacity: enter, overflow: 'hidden'}}>
			{b.portrait ? (
				media({width: '100%', height: '100%', objectFit: 'cover', objectPosition: '50% 25%', transform: `scale(${kb * pop})`})
			) : b.focus ? (
				(() => {
					// горизонтальна з обличчям: на весь кадр, вікно йде за обличчям, наїзд — у бік обличчя
					const [pos, origin] = focusWindow(b, f / fps, aspect);
					return media({width: '100%', height: '100%', objectFit: 'cover', objectPosition: `${pos}% 50%`,
						transform: `scale(${kb * pop})`, transformOrigin: `${origin}% 40%`});
				})()
			) : (
				<>
					<AbsoluteFill style={{filter: 'blur(40px) brightness(0.65)', transform: 'scale(1.25)'}}>
						{media({width: '100%', height: '100%', objectFit: 'cover'})}
					</AbsoluteFill>
					<AbsoluteFill>{media({width: '100%', height: '100%', objectFit: 'contain', transform: `scale(${kb * pop})`})}</AbsoluteFill>
				</>
			)}
			<AbsoluteFill style={{backgroundColor: 'white', opacity: flash}} />
		</AbsoluteFill>
	);
};


/** Наклейка-ілюстрація (правка 21.10): PNG з білою обводкою вистрибує, гойдається, плаває; з боку над обличчям. */
const Sticker: React.FC<{p: CreativeProps; s: NonNullable<CreativeProps['stickers']>[number]}> = ({p, s}) => {
	const f = useCurrentFrame();
	const n = Math.round(s.dur * p.fps);
	// наклейка — лише на голові: поверх перебивки/картки не показуємо
	const ta = s.start + f / p.fps;
	if (p.broll.some((b) => ta >= b.start && ta < b.start + b.dur)) return null;
	if (p.soft) {
		// фото-вирізка (як у роликах лікаря): м'яко з'являється, без гойдання; поки плашка — не показуємо (одне за раз)
		if ((p.plates ?? []).some((q) => ta >= q.start && ta < q.end)) return null;
		const k = spring({frame: f, fps: p.fps, config: {damping: 16, stiffness: 160, mass: 0.7}});
		const o = Math.min(interpolate(f, [0, 4], [0, 1], clamp), interpolate(f, [n - 5, n], [1, 0], clamp));
		const sz = p.width * 0.38;
		const lx = s.side === 'l' ? p.width * 0.03 : p.width * 0.97 - sz;
		const ty = p.height * 0.36;
		return (
			<Img src={staticFile(s.file)} style={{position: 'absolute', left: lx, top: ty, width: sz, height: sz, objectFit: 'contain', opacity: o,
				transform: `translateY(${interpolate(k, [0, 1], [30, 0])}px) scale(${interpolate(k, [0, 1], [0.85, 1])}) rotate(${s.side === 'l' ? -4 : 4}deg)`,
				filter: 'drop-shadow(0 8px 16px rgba(80,30,50,0.28))'}} />
		);
	}
	const pop = spring({frame: f, fps: p.fps, config: {damping: 9, stiffness: 210, mass: 0.6}});
	const out = interpolate(f, [n - 5, n], [1, 0], clamp);
	const size = p.width * 0.34;
	const left = s.side === 'l' ? p.width * 0.04 : p.width * 0.96 - size;
	const top = p.height * (p.height > p.width * 1.5 ? 0.2 : 0.16) + (s.idx % 2) * p.height * 0.03;
	const rot = (s.side === 'l' ? -10 : 10) + Math.sin(f / 6) * 4;
	return (
		<Img src={staticFile(s.file)} style={{position: 'absolute', left, top: top + Math.sin(f / 9) * 8, width: size, height: size,
			objectFit: 'contain', transform: `scale(${interpolate(pop, [0, 1], [0.2, 1]) * out}) rotate(${rot}deg)`, opacity: out,
			filter: 'drop-shadow(0 10px 18px rgba(0,0,0,0.35))'}} />
	);
};

// ---------- субтитри: плашка (Submagic) або дрібний білий текст; ключові слова більші ----------

/** Стиль vit (правка 20.10): текст не налазить на обличчя і не заходить у верхні/нижні 20 % кадру.
 * Верх тексту — під підборіддям (центр обличчя + ≈0,2 ширини кадру), низ — не нижче 80 % висоти. */
const VIT_SAFE_BOTTOM = 0.8;
/** Висота зеленої плашки (частка висоти кадру): один рядок капсу з полями. */
const bannerH = (p: CreativeProps) => (p.banner ? (p.width * 0.13) / p.height : 0);
/** Нижня межа для субтитрів/хука/стрілок: 80 % висоти, а з плашкою — над нею. */
const vitBottom = (p: CreativeProps) => VIT_SAFE_BOTTOM - (p.banner ? bannerH(p) + 0.01 : 0);
const vitTextTop = (p: CreativeProps) =>
	Math.min(Math.max(0.2, (p.faceYReal ?? p.faceY) + (0.26 * p.width) / p.height + 0.015), vitBottom(p) - 0.1);

/** Постійна зелена плашка (як у креативах UNIK): на всю ширину, білий жирний капс, низом упирається в 80 % висоти. */
const Banner: React.FC<{p: CreativeProps}> = ({p}) => {
	const tb = useCurrentFrame() / p.fps;
	if (!p.banner) return null;
	// на спліт-хуку аватар унизу — плашка лягла б на обличчя
	if (p.vhook && p.vhook.mode === 'split' && tb >= p.vhook.start && tb < p.vhook.end) return null;
	// на картці з власним текстом плашка перекриває підписи — ховаємо
	if (p.broll.some((b) => (b as {card?: boolean}).card && tb >= b.start && tb < b.start + b.dur)) return null;
	const h = bannerH(p) * p.height;
	return (
		<div style={{position: 'absolute', left: 0, width: p.width, top: VIT_SAFE_BOTTOM * p.height - h, height: h,
			backgroundColor: '#2EE63F', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
			<div style={{color: 'white', fontFamily: FONT, fontWeight: 900, fontSize: Math.min(p.width * 0.085, (p.width * 0.88) / Math.max(1, p.banner.length * 0.78)), lineHeight: 1, whiteSpace: 'nowrap', textAlign: 'center',
				textTransform: 'uppercase', letterSpacing: p.width * 0.002, textShadow: '0 2px 6px rgba(0,0,0,0.25)'}}>{p.banner}</div>
		</div>
	);
};


const plate = (p: CreativeProps, big = false): React.CSSProperties =>
	p.style === 'vit'
		? {
				// стиль vit: жирний курсивний білий капс з чорним обведенням і тінню, без плашки
				color: 'white', fontFamily: FONT, fontWeight: 900, fontStyle: 'italic', fontSize: p.width * (big ? 0.082 : 0.075),
				lineHeight: 1.05, textTransform: 'uppercase', textAlign: 'center', maxWidth: '86%',
				WebkitTextStroke: `${p.width * 0.007}px black`, paintOrder: 'stroke fill',
				textShadow: `0 ${p.width * 0.005}px 0 rgba(0,0,0,0.85), 0 0 ${p.width * 0.02}px rgba(0,0,0,0.45)`,
		  }
		: p.style === 'box'
		? {
				backgroundColor: p.boxColor || BOX_GREEN, borderRadius: 18, padding: big ? '18px 30px' : '10px 24px', color: 'white',
				fontFamily: FONT, fontWeight: 800, fontSize: p.width * (big ? 0.058 : 0.05), lineHeight: 1.18,
				textTransform: 'uppercase', textAlign: 'center', maxWidth: '84%', boxShadow: '0 6px 18px rgba(0,0,0,0.25)',
		  }
		: {
				color: 'white', fontFamily: FONT, fontWeight: 700, fontSize: p.width * (big ? 0.06 : 0.05),
				textTransform: 'uppercase', textAlign: 'center', maxWidth: '84%', textShadow: '0 0 12px rgba(0,0,0,0.75)',
		  };

/** Затемнення під текст (grade.dim_alpha): м'яка смуга за рядком субтитрів, сила — від того, що зараз у кадрі
 * (перебивка чи спікерка). Для стилю box не потрібне — плашка читається на будь-якому фоні. */
const DimBand: React.FC<{p: CreativeProps}> = ({p}) => {
	const t = useCurrentFrame() / p.fps;
	if (p.style === 'box' || p.style === 'vit') return null;
	const b = p.broll.find((x) => t >= x.start && t < x.start + x.dur);
	const alpha = b ? (b.dim ?? 0) : (p.dimSpeaker ?? 0);
	if (alpha <= 0.01) return null;
	const c = (1 - p.subBottom) * 100;
	return (
		<AbsoluteFill style={{background: `linear-gradient(to bottom, transparent ${c - 9}%, rgba(0,0,0,${alpha}) ${c}%, transparent ${c + 9}%)`}} />
	);
};

// м'які плашки (правка замовника): світле тло, округлі кути, ніжні кольори тексту; у зоні 20–80 % висоти
const SOFT_FILL: Record<string, [string, string, string]> = {
	red: ['#FFF3F5', '#B83B62', '#F4C3D1'], yellow: ['#FFF8EE', '#A8573A', '#F3D6BE'],
	green: ['#F2F8F2', '#3D7A57', '#C9E3CF'], blue: ['#F5F2FF', '#6A4FB0', '#D8CEF5'],
};
// 23.10: плашка в зоні 20–80 %; якщо під нею саби (keep) — низ плашки ≤ 60 % висоти, щоб не налазила на саби (вони від ~62 %)
const softPlateTop = (p: CreativeProps, x: NonNullable<CreativeProps['plates']>[number], n: number, fs: number) => {
	const h = n * fs * 1.15 + fs * 0.84 + p.width * 0.008;
	const base = p.height * (p.plateTop ?? (p.height > p.width * 1.5 ? 0.56 : 0.55));
	const lim = x.keep ? Math.min(p.height * 0.6, (1 - p.subBottom) * p.height - p.height * 0.1) : p.height * 0.8;
	return Math.max(p.height * 0.22, Math.min(base, lim - h));
};
const SoftPlate: React.FC<{p: CreativeProps; x: NonNullable<CreativeProps['plates']>[number]; f: number}> = ({p, x, f}) => {
	const [bg, fg, br] = SOFT_FILL[x.color] ?? SOFT_FILL.red;
	const k = spring({frame: f - Math.round(x.start * p.fps), fps: p.fps, config: {damping: 15, stiffness: 170, mass: 0.7}});
	const words = x.text.split(' ');
	const lines: string[] = []; let cur = '';
	for (const w of words) { if ((cur + ' ' + w).trim().length > 18 && cur) { lines.push(cur); cur = w; } else cur = (cur + ' ' + w).trim(); }
	if (cur) lines.push(cur);
	const longest = Math.max(...lines.map((l) => l.length));
	const fs = Math.min(p.width * 0.068, (p.width * 0.76) / (longest * 0.66));
	return (
		<AbsoluteFill style={{alignItems: 'center', justifyContent: 'flex-start', paddingTop: softPlateTop(p, x, lines.length, fs)}}>
			<div style={{transform: `translateY(${interpolate(k, [0, 1], [24, 0])}px) scale(${0.9 + 0.1 * k})`, opacity: interpolate(k, [0, 0.4], [0, 1], clamp),
				backgroundColor: bg, border: `${Math.round(p.width * 0.004)}px solid ${br}`, borderRadius: p.width * 0.06,
				padding: `${fs * 0.42}px ${fs * 0.8}px`, boxShadow: '0 10px 30px rgba(90,30,60,0.22)', textAlign: 'center',
				fontFamily: FONT, fontWeight: 800, fontSize: fs, lineHeight: 1.15, color: fg, letterSpacing: fs * 0.01}}>
				{lines.map((l, i) => <div key={i}>{l}</div>)}
			</div>
		</AbsoluteFill>
	);
};

const PLATE_FILL: Record<string, [string, string]> = {red: ['#E8322B', '#FFFFFF'], yellow: ['#FFD400', '#E8322B'], green: ['#2EE63F', '#0B3D17'], blue: ['#2F7DE1', '#FFFFFF']};
// плашка-ключове слово (як у рефах автор): великий капс з обводкою посеред кадру, «поп» на вході
const Plates: React.FC<{p: CreativeProps}> = ({p}) => {
	const f = useCurrentFrame();
	const t = f / p.fps;
	const x = (p.plates ?? []).find((q) => t >= q.start && t < q.end);
	if (!x || !x.text.trim()) return null; // 23.10: порожня плашка — лише ховає саби (під накладку-картинку, напр. «реклама марафону» 50.1)
	if (p.soft) return <SoftPlate p={p} x={x} f={f} />;
	const [fill, stroke] = PLATE_FILL[x.color] ?? PLATE_FILL.red;
	const k = spring({frame: f - Math.round(x.start * p.fps), fps: p.fps, config: {damping: 11, stiffness: 220, mass: 0.6}});
	const words = x.text.split(' ');
	const lines: string[] = []; let cur = '';
	for (const w of words) { if ((cur + ' ' + w).trim().length > 16 && cur) { lines.push(cur); cur = w; } else cur = (cur + ' ' + w).trim(); }
	if (cur) lines.push(cur);
	// розмір під найдовший рядок: капс Montserrat Black ≈ 0.72 ширини кегля на літеру, поле 88 % кадру
	const longest = Math.max(...lines.map((l) => l.length));
	const fs = Math.min(p.width * (lines.length > 2 ? 0.088 : 0.1), (p.width * 0.88) / (longest * 0.72));
	return (
		<AbsoluteFill style={{alignItems: 'center', justifyContent: 'flex-start', paddingTop: p.height * (p.height > p.width * 1.5 ? 0.52 : 0.5)}}>
			<div style={{transform: `scale(${0.6 + 0.4 * k})`, textAlign: 'center', fontFamily: FONT, fontWeight: 900, fontSize: fs, lineHeight: 1.05,
				color: fill, WebkitTextStroke: `${fs * 0.1}px ${stroke}`, paintOrder: 'stroke fill', textShadow: '0 6px 18px rgba(0,0,0,0.35)', textTransform: 'uppercase'}}>
				{lines.map((l, i) => <div key={i}>{l}</div>)}
			</div>
		</AbsoluteFill>
	);
};

const Captions: React.FC<{p: CreativeProps}> = ({p}) => {
	const frame = useCurrentFrame();
	const t = frame / p.fps;
	if ((p.plates ?? []).some((x) => !x.keep && t >= x.start && t < x.end)) return null;
	const title = p.overlays.find((o) => o.type === 'title');
	if (title && t < title.end) return null;
	if (p.vhook && t >= p.vhook.start && t < p.vhook.end) return null;
	// на картці з власним текстом (card_*) субтитри не дублюємо
	if (p.broll.some((b) => (b as {card?: boolean}).card && t >= b.start && t < b.start + b.dur)) return null;
	const g = p.groups.find((x) => t >= x.start && t < x.end);
	if (!g) return null;
	const local = frame - Math.round(g.start * p.fps);
	const pop = spring({frame: local, fps: p.fps, config: {damping: 14, stiffness: 240, mass: 0.6}});
	return (
		<AbsoluteFill style={p.style === 'vit'
			? {justifyContent: 'flex-start', alignItems: 'center', paddingTop: p.height * vitTextTop(p)}
			: {justifyContent: 'flex-end', alignItems: 'center', paddingBottom: p.height * p.subBottom}}>
			<div style={{...plate(p), transform: `scale(${interpolate(pop, [0, 1], [0.8, 1])})`, opacity: interpolate(local, [0, 2], [0, 1], clamp)}}>
				{g.words.map((w, i) => (
					<span key={i} style={{fontSize: w.emph ? '1.25em' : undefined}}>
						{w.t}
						{i < g.words.length - 1 ? ' ' : ''}
					</span>
				))}
			</div>
		</AbsoluteFill>
	);
};

const TitlePlate: React.FC<{p: CreativeProps; text: string}> = ({p, text}) => {
	const f = useCurrentFrame();
	const pop = spring({frame: f, fps: p.fps, config: {damping: 12, stiffness: 180}});
	return (
		<AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: p.height * 0.26}}>
			<div style={{...plate(p, true), transform: `scale(${interpolate(pop, [0, 1], [0.6, 1])})`}}>{text}</div>
		</AbsoluteFill>
	);
};

// ---------- візуальний хук (стиль vit, відгук замовника 15.10) ----------

const StockClip: React.FC<{c: VHook['clips'][number]; fps: number; idx: number}> = ({c, fps, idx}) => {
	const f = useCurrentFrame();
	const dur = Math.max(1, Math.round(c.dur * fps));
	const kb = interpolate(f, [0, dur], idx % 2 === 0 ? [1.02, 1.12] : [1.12, 1.02], clamp);
	return (
		<OffthreadVideo src={staticFile(c.file)} trimBefore={Math.round(c.clipStart * fps)} muted
			style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${kb})`}} />
	);
};

/** split: верх — стокове відео за змістом хука, низ — аватар (обличчя в кадрі), тонка біла лінія, великі
 * субтитри хука на стику половин. Рендериться замість звичайного Speaker на час хука (глобальний час). */
const SplitHook: React.FC<{p: CreativeProps; h: VHook}> = ({p, h}) => {
	const frame = useCurrentFrame();
	const t = frame / p.fps;
	const fr = (s: number) => Math.round(s * p.fps);
	const top = Math.round(p.height * h.split);
	const mh = p.height - top;
	const shift = Math.min(Math.max(p.height * (p.faceYReal ?? p.faceY) - mh * 0.4, 0), p.height - mh);
	const lw = Math.max(4, Math.round(p.width * 0.006));
	const g = p.groups.find((x) => t >= x.start && t < x.end && x.start < h.end);
	const local = g ? frame - fr(g.start) : 0;
	const pop = spring({frame: local, fps: p.fps, config: {damping: 14, stiffness: 240, mass: 0.6}});
	const intro = spring({frame: frame - fr(h.start), fps: p.fps, config: {damping: 16, stiffness: 160}});
	return (
		<AbsoluteFill style={{backgroundColor: 'black'}}>
			<div style={{position: 'absolute', left: 0, top: 0, width: p.width, height: top, overflow: 'hidden',
				transform: `scale(${interpolate(intro, [0, 1], [1.2, 1])})`, transformOrigin: '50% 100%'}}>
				{h.clips.map((c, i) => (
					<Sequence key={i} from={fr(c.start)} durationInFrames={Math.max(1, fr(c.dur))}>
						<StockClip c={c} fps={p.fps} idx={i} />
					</Sequence>
				))}
			</div>
			<div style={{position: 'absolute', left: 0, top, width: p.width, height: mh, overflow: 'hidden'}}>
				<div style={{position: 'absolute', left: 0, top: -shift, width: p.width, height: p.height}}>
					<Speaker p={p} />
				</div>
			</div>
			<div style={{position: 'absolute', left: 0, top: top - lw / 2, width: p.width, height: lw, backgroundColor: 'white',
				boxShadow: '0 0 10px rgba(0,0,0,0.5)'}} />
			{g ? (
				<div style={{position: 'absolute', left: 0, top, width: p.width, display: 'flex', justifyContent: 'center',
					transform: 'translateY(-50%)'}}>
					<div style={{...plate(p, true), fontSize: p.width * 0.092, maxWidth: '92%',
						transform: `scale(${interpolate(pop, [0, 1], [0.8, 1])})`, opacity: interpolate(local, [0, 2], [0, 1], clamp)}}>
						{g.words.map((w, i) => (
							<span key={i} style={{color: w.emph ? '#FFD84D' : undefined}}>
								{w.t}
								{i < g.words.length - 1 ? ' ' : ''}
							</span>
						))}
					</div>
				</div>
			) : null}
		</AbsoluteFill>
	);
};

/** text: великий кінетичний текст хука (2–3 рядки на сторінку), слова з'являються по одному, ключові — жовті. */
const KineticHook: React.FC<{p: CreativeProps; h: VHook}> = ({p, h}) => {
	const frame = useCurrentFrame();
	const t = frame / p.fps;
	const pg = h.pages.find((x) => t >= x.start && t < x.end);
	if (!pg) return null;
	// кегль ≈2× від звичайних сабів (0.075w → 0.15w) на весь хук; задовге слово стискається окремо, щоб влізти в 88% ширини
	// правка 20.10: текст між підборіддям і 80 % висоти; кегль зменшується, якщо рядки не влазять у цю смугу
	// ширина слова в em (жирний курсив з обведенням): вузькі І/Ї ≈0.4, широкі М/Ш/Ж/Ю/Д ≈0.95, решта ≈0.86
	const em = (t: string) => [...t].reduce((a, c) => a + ('ІЇIі1!.,:;\'’'.includes(c) ? 0.4 : 'МШЩЖЮФДWM—'.includes(c) ? 0.95 : 0.86), 0);
	const topF = vitTextTop(p);
	const fitLines = (f: number) => {
		let lines = 1, cur = 0;
		for (const w of pg.words) {
			const ww = Math.min(p.width * 0.88, em(w.t) * f * (w.key ? 1.1 : 1));
			if (cur > 0 && cur + f * 0.22 + ww > p.width * 0.88) { lines++; cur = ww; } else cur += (cur > 0 ? f * 0.22 : 0) + ww;
		}
		return lines;
	};
	let fs = p.width * 0.15;
	while (fs > p.width * 0.08 && fitLines(fs) * fs * 1.1 > (vitBottom(p) - topF) * p.height) fs *= 0.93;
	const wordScale = (w: {t: string; key: boolean}) => Math.min(1, (p.width * 0.88) / (em(w.t) * fs * (w.key ? 1.1 : 1)));
	const base: React.CSSProperties = {
		display: 'inline-block', fontFamily: FONT, fontWeight: 900, fontStyle: 'italic', textTransform: 'uppercase', lineHeight: 1.02,
		WebkitTextStroke: `${p.width * 0.009}px black`, paintOrder: 'stroke fill',
		textShadow: `0 ${p.width * 0.007}px 0 rgba(0,0,0,0.9), 0 0 ${p.width * 0.03}px rgba(0,0,0,0.55)`,
	};
	return (
		<AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'center', paddingTop: p.height * topF}}>
			<div style={{width: '88%', display: 'flex', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'baseline',
				columnGap: fs * 0.22, rowGap: 0, fontSize: fs}}>
				{pg.words.map((w, i) => {
					const lf = frame - Math.round(w.start * p.fps);
					const pop = spring({frame: Math.max(0, lf), fps: p.fps, config: {damping: 11, stiffness: 230, mass: 0.55}});
					return (
						<span key={i} style={{...base, color: w.key ? '#FFD400' : 'white', fontSize: `${(w.key ? 1.1 : 1) * wordScale(w)}em`,
							opacity: lf < 0 ? 0 : interpolate(lf, [0, 2], [0, 1], clamp),
							transform: `translateY(${interpolate(pop, [0, 1], [fs * 0.35, 0])}px) scale(${interpolate(pop, [0, 1], [0.45, 1])})`}}>
							{w.t}
						</span>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};

// ---------- кружечок спікера поверх скрінів (стиль vit): як у топ-креативах Віталія ----------

/** Початок суцільної серії pip-перебивок, у яку входить b (нарізані шматки одного кліпу — один кружечок). */
const pipRunStart = (p: CreativeProps, b: BRollItem) => {
	let s = b.start;
	for (;;) {
		const prev = p.broll.find((o) => o.pip && Math.abs(o.start + o.dur - s) < 0.05);
		if (!prev || prev.start >= s) return s;
		s = prev.start;
	}
};

const PipSpeaker: React.FC<{p: CreativeProps}> = ({p}) => {
	const frame = useCurrentFrame();
	const t = frame / p.fps;
	const b = p.broll.find((x) => x.pip && t >= x.start && t < x.start + x.dur);
	if (!b) return null;
	const local = frame - Math.round(pipRunStart(p, b) * p.fps);
	const pop = spring({frame: local, fps: p.fps, config: {damping: 13, stiffness: 200, mass: 0.6}});
	const d = p.width * 0.5;
	const k = 0.8; // масштаб кадру спікера в кружечку: обличчя ~45% діаметра
	const top = p.height * (p.height > p.width * 1.5 ? 0.07 : 0.045);
	return (
		<div
			style={{
				position: 'absolute', left: (p.width - d) / 2, top, width: d, height: d, borderRadius: '50%', overflow: 'hidden',
				border: `${p.width * 0.008}px solid white`, boxShadow: '0 8px 28px rgba(0,0,0,0.45)', backgroundColor: 'black',
				transform: `scale(${interpolate(pop, [0, 1], [0.6, 1])})`, opacity: interpolate(local, [0, 3], [0, 1], clamp),
			}}
		>
			<div
				style={{
					position: 'absolute', width: p.width, height: p.height, transformOrigin: '0 0',
					left: d / 2 - (p.width / 2) * k, top: d / 2 - p.height * (p.faceYReal ?? p.faceY) * k, transform: `scale(${k})`,
				}}
			>
				<Speaker p={p} />
			</div>
		</div>
	);
};

// ---------- стрілки на заклику: виліт великими, далі погойдування ----------

const Arrows: React.FC<{p: CreativeProps}> = ({p}) => {
	const f = useCurrentFrame();
	const pop = spring({frame: f, fps: p.fps, config: {damping: 11, stiffness: 160}});
	const bob = f > 8 ? Math.sin(((f - 8) / p.fps) * ((2 * Math.PI) / 0.9)) * 12 : 0;
	let w = p.width * (p.height > p.width * 1.5 ? 0.27 : 0.22);
	// під субтитрами, не поверх них: якщо внизу тісно (субтитри низько) — стрілки менші
	// vit (правка 20.10): субтитри стоять під підборіддям, стрілки — під ними і не нижче 80 % висоти
	const vit = p.style === 'vit';
	const subEnd = vit ? p.height * vitTextTop(p) + p.width * 0.2 : (1 - p.subBottom) * p.height;
	const lim = p.height * (vit ? vitBottom(p) : 0.9);
	let cy = Math.max(p.height * (vit ? 0.6 : 0.7), subEnd + w * 0.6);
	if (cy + w * 0.55 > lim) {
		w = Math.max(p.width * 0.14, (lim - subEnd) / 1.15);
		cy = subEnd + w * 0.6;
	}
	// з плашкою під субтитрами місця під ними нема: стрілки — з боків від субтитру (по краях кадру)
	const side = vit && !!p.banner;
	if (side) {
		w = p.width * 0.12;
		cy = p.height * vitTextTop(p) + p.width * 0.06;
	}
	return (
		<AbsoluteFill>
			{(side ? ['9%', '91%'] : ['50%']).map((left) => (
			<svg
				key={left}
				viewBox="0 0 290 300"
				style={{
					position: 'absolute', left, top: cy + bob, width: w,
					transform: `translate(-50%, -50%) scale(${interpolate(pop, [0, 1], [2.2, 1])})`,
					opacity: interpolate(f, [0, 5], [0, 1], clamp), filter: 'drop-shadow(0 0 14px rgba(255,255,255,0.55))',
				}}
			>
				{[0, 120].map((dy) => (
					<polyline key={dy} points={`29,${29 + dy} 145,${150 + dy} 261,${29 + dy}`} fill="none" stroke="white"
						strokeWidth={58} strokeLinecap="round" strokeLinejoin="round" />
				))}
			</svg>
			))}
		</AbsoluteFill>
	);
};

// ---------- стрічка Instagram: спікерка всередині поста, перебивка заїжджає свайпом, на виході спалах ----------

const IgFeed: React.FC<{p: CreativeProps; o: Overlay}> = ({p, o}) => {
	const f = useCurrentFrame();
	const t = f / p.fps;
	const len = o.end - o.start;
	const top = o.top ?? 400;
	const mh = p.height - top - (o.bottom ?? 440);
	const shift = p.height * p.faceY - mh * 0.32;
	const swipeAt = o.brollStart !== undefined ? o.brollStart - o.start : Infinity;
	const e = interpolate(t, [swipeAt, swipeAt + 0.35], [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});
	const enter = interpolate(t, [0, 0.18], [0, 1], clamp);
	const flash = interpolate(t, [len - 0.2, len - 0.05, len], [0, 0.9, 0], clamp);
	return (
		<AbsoluteFill style={{opacity: enter}}>
			<AbsoluteFill style={{backgroundColor: 'white'}} />
			<div style={{position: 'absolute', left: 0, top, width: p.width, height: mh, overflow: 'hidden'}}>
				<div style={{position: 'absolute', left: -p.width * e, top: -shift, width: p.width, height: p.height}}>
					<Speaker p={p} />
				</div>
				{o.broll ? (
					<div style={{position: 'absolute', left: p.width * (1 - e), top: 0, width: p.width, height: mh}}>
						{o.brollKind === 'photo' ? (
							<Img src={staticFile(o.broll)} style={{width: '100%', height: '100%', objectFit: 'cover', objectPosition: '50% 25%'}} />
						) : (
							<OffthreadVideo src={staticFile(o.broll)} trimBefore={Math.round((o.clipStart ?? 0) * p.fps)} muted
								style={{width: '100%', height: '100%', objectFit: 'cover'}} />
						)}
					</div>
				) : null}
			</div>
			{o.frame ? <Img src={staticFile(o.frame)} style={{position: 'absolute', left: 0, top: 0, width: p.width, height: p.height}} /> : null}
			<AbsoluteFill style={{background: 'radial-gradient(circle at 45% 40%, #fffaf0 0%, #ffd27a 55%, #ff9a3c 100%)', opacity: flash}} />
		</AbsoluteFill>
	);
};

// ---------- ролик ----------

/** Кадри, де перебивка повністю закриває спікерку (після 3-кадрової появи): там майстер не декодуємо —
 * у роликах «інтересу» перебивки займають ~60% часу. PNG можуть мати прозорість — під ними не ховаємо. */
/** Перебивка починається там, де закінчується інша (з точністю до кадру). */
const chainedAt = (p: CreativeProps, b: BRollItem) => {
	const fr = (s: number) => Math.round(s * p.fps);
	// суміжна = інша перебивка ще йде (або щойно скінчилась) у момент початку цієї; окреме округлення start і dur
	// давало різницю 2 кадри — нова перебивка з'являлась напівпрозорою і крізь неї мелькав спікер (36.1, 12,8 с)
	return p.broll.some((o) => o !== b && fr(o.start) < fr(b.start) && fr(o.start) + Math.max(1, fr(o.dur)) >= fr(b.start) - 1);
};

const speakerHidden = (p: CreativeProps, frame: number) => {
	const fr = (s: number) => Math.round(s * p.fps);
	return p.broll.some((b) => {
		const opaque = b.portrait || b.focus ? !b.file.toLowerCase().endsWith('.png') : Boolean(b.bg);
		const from = fr(b.start);
		return opaque && frame >= from + (chainedAt(p, b) ? 0 : 3) && frame < from + Math.max(1, fr(b.dur));
	});
};

export const Creative: React.FC<CreativeProps> = (p) => {
	const fr = (s: number) => Math.round(s * p.fps);
	const frame = useCurrentFrame();
	const vh = p.vhook;
	const inHook = Boolean(vh) && frame >= fr((vh as VHook).start) && frame < fr((vh as VHook).end);
	return (
		<AbsoluteFill style={{backgroundColor: 'black'}}>
			{inHook && vh?.mode === 'split' ? <SplitHook p={p} h={vh} /> : speakerHidden(p, frame) ? null : <Speaker p={p} />}
			{p.broll.map((b, i) => (
				<Sequence key={i} from={fr(b.start)} durationInFrames={Math.max(1, fr(b.dur))}>
					<BRoll b={b} fps={p.fps} aspect={p.width / p.height} chained={chainedAt(p, b)} />
				</Sequence>
			))}
			{p.overlays
				.filter((o) => o.type === 'title' && o.text)
				.map((o, i) => (
					<Sequence key={`t${i}`} from={fr(o.start)} durationInFrames={Math.max(1, fr(o.end - o.start))}>
						<TitlePlate p={p} text={o.text as string} />
					</Sequence>
				))}
			{p.overlays
				.filter((o) => o.type === 'ig_feed')
				.map((o, i) => (
					<Sequence key={`f${i}`} from={fr(o.start)} durationInFrames={Math.max(1, fr(o.end - o.start))}>
						<IgFeed p={p} o={o} />
					</Sequence>
				))}
			{p.style === 'vit' ? <PipSpeaker p={p} /> : null}
			<DimBand p={p} />
			{(p.stickers ?? []).map((s) => (
				<Sequence key={`st${s.idx}`} from={Math.round(s.start * p.fps)} durationInFrames={Math.max(1, Math.round(s.dur * p.fps))}>
					<Sticker p={p} s={s} />
				</Sequence>
			))}
			<Captions p={p} />
			<Plates p={p} />
			{inHook && vh?.mode === 'text' ? <KineticHook p={p} h={vh} /> : null}
			{p.style === 'vit' ? <Banner p={p} /> : null}
			{p.overlays
				.filter((o) => o.type === 'cta_arrows')
				.map((o, i) => (
					<Sequence key={`a${i}`} from={fr(o.start)} durationInFrames={Math.max(1, fr(o.end - o.start))}>
						<Arrows p={p} />
					</Sequence>
				))}
			{p.audio ? <Audio src={staticFile(p.audio)} /> : null}
		</AbsoluteFill>
	);
};
