"""Точні межі слів: вирівнювання тексту Whisper по звуку моделлю MMS_FA (torchaudio, 1100+ мов, є українська).

Whisper розпізнає слова добре, але межі ставить приблизно: на злитій мові приклеює «і» до сусіднього слова
(«І тоді» → «Тоді», «калорій. І… але» → «Але»), і склейка захоплює зайве. Вирівнювання знаходить, де саме
звучить кожне слово, тож звуки поза текстом (заповнювачі, фальстарти) лишаються в паузах і вирізаються.

Текст і слова не змінюються — лише start/end. Оригінал зберігається в <name>.transcript.whisper.json.
Окремий процес: torch не вантажимо разом із PyAV (faster-whisper) і OpenCV.
  python align.py work/<name>.transcript.json
"""
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np
import config  # noqa: F401  — TORCH_HOME: де лежить модель MMS
import torch
import torchaudio.functional as F
from torchaudio.pipelines import MMS_FA

PAD = 0.4          # запас аудіо навколо сегмента Whisper, с
MIN_SCORE = 0.05   # нижче — вирівнюванню слова не віримо, лишаємо межі Whisper; слабші за 0,6 — див. cut.py


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as f:
        sr = f.getframerate()
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return x, sr


def romanize(words: list[str], ur) -> list[str]:
    """Латиниця для словника MMS: uroman («калорій» → «kaloriy»), лише a–z і апостроф."""
    out = []
    for w in words:
        r = ur.romanize_string(w.lower())
        out.append(re.sub(r"[^a-z']", "", r.lower()))
    return out


def align_segment(audio, sr, words, model, dictionary, ur, device):
    """Вирівнює слова одного шматка аудіо. Повертає [(start, end, score)] у секундах відносно шматка або None."""
    toks = romanize([w["w"] for w in words], ur)
    # слова без літер (числа «80», «10») — зірочка: модель відводить їм будь-який звук
    toks = [t if t else "*" for t in toks]
    # «поглинач» на краях: мову, якої немає в тексті (Whisper часом ставить сегмент на 6 с раніше, де звучить
    # інша репліка), забирає зірочка — інакше слова «розтягуються» по чужій мові й з'їжджають на ~0,5 с
    tokens = [[dictionary["*"]]] + [[dictionary[c] for c in t] for t in toks] + [[dictionary["*"]]]
    wav = torch.from_numpy(audio).unsqueeze(0)
    if sr != MMS_FA.sample_rate:
        wav = F.resample(wav, sr, MMS_FA.sample_rate)
    with torch.inference_mode():
        emission, _ = model(wav.to(device))
    flat = [t for w in tokens for t in w]
    if emission.size(1) < len(flat):
        return None
    aligned, scores = F.forced_align(emission, torch.tensor([flat], dtype=torch.int32, device=device))
    spans = F.merge_tokens(aligned[0], scores[0].exp())
    ratio = audio.shape[0] / sr / emission.size(1)
    out, k = [], len(tokens[0])
    for w in tokens[1:-1]:
        ws = spans[k:k + len(w)]
        k += len(w)
        sc = float(sum(s.score * (s.end - s.start) for s in ws) / max(1, sum(s.end - s.start for s in ws)))
        out.append((ws[0].start * ratio, ws[-1].end * ratio, sc))
    return out


if __name__ == "__main__":
    tr_path = Path(sys.argv[1])
    tr = json.loads(tr_path.read_text())
    orig = tr_path.with_name(tr_path.name.replace(".transcript.json", ".transcript.whisper.json"))
    if tr.get("aligned"):
        if "--force" not in sys.argv or not orig.exists():
            print("  вже вирівняно")
            sys.exit(0)
        tr = json.loads(orig.read_text())  # перевирівняти з оригіналу Whisper
    wav_path = tr_path.with_name(tr_path.name.replace(".transcript.json", ".wav"))
    audio, sr = load_wav(wav_path)

    device = torch.device("cpu")
    model = MMS_FA.get_model(with_star=True).to(device)
    dictionary = MMS_FA.get_dict(star="*")
    import uroman
    ur = uroman.Uroman()

    moved, kept, n = [], 0, 0
    for seg in tr["segments"]:
        words = [w for w in seg["words"] if w["w"].strip()]
        if not words:
            continue
        t0 = max(0.0, words[0]["start"] - PAD)
        t1 = min(len(audio) / sr, words[-1]["end"] + PAD)
        res = align_segment(audio[int(t0 * sr):int(t1 * sr)], sr, words, model, dictionary, ur, device)
        if res is None:
            kept += len(words)
            continue
        for w, (s, e, sc) in zip(words, res):
            n += 1
            if sc < MIN_SCORE:
                kept += 1
                continue
            ns, ne = round(t0 + s, 3), round(t0 + e, 3)
            moved.append(abs(ns - w["start"]) + abs(ne - w["end"]))
            w["whisper"] = [w["start"], w["end"]]
            w["start"], w["end"], w["a"] = ns, ne, round(sc, 3)

    if not orig.exists():
        orig.write_text(json.dumps(json.loads(tr_path.read_text()), ensure_ascii=False))
    tr["aligned"] = True
    tr_path.write_text(json.dumps(tr, ensure_ascii=False))
    mv = np.array(moved) if moved else np.zeros(1)
    print(f"  слів: {n}, уточнено: {len(moved)}, лишили межі Whisper: {kept}; "
          f"зсув меж: медіана {np.median(mv) * 1000:.0f} мс, 90% ≤ {np.percentile(mv, 90) * 1000:.0f} мс")
