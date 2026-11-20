"""Вибір музики для вже змонтованого ролика без перескладання монтажу: «мозок» читає текст ролика й обирає
один трек із бібліотеки монтажера (input/audio/music/tracks.json) за настроєм. Пише edl["music"].
  python music_pick.py <name>
"""
import json
import sys

from audio import tracks
from config import WORK
from plan import ask_claude_cli

if __name__ == "__main__":
    name = sys.argv[1]
    edl_path = WORK / f"{name}.edl.json"
    edl = json.loads(edl_path.read_text())
    tr = json.loads((WORK / f"{name}.transcript.json").read_text())
    words = [w for s in tr["segments"] for w in s["words"]]
    text = " ".join(words[i]["w"] for a, b in edl["keep"] for i in range(a, b + 1))
    tl = tracks()
    prompt = ("рекламний ролик про результат клієнта"
              "ролик (посеред ролика музика не змінюється) — за настроєм і темпом розповіді. Треки монтажера:\n"
              + "\n".join(f"- `{k}` — {v['mood']}, {v['duration']:.0f} с" for k, v in tl.items())
              + f"\n\nТекст ролика:\n{text}\n\nПоверни назву файлу і коротко чому.")
    schema = {"type": "object", "properties": {"music": {"type": "string", "enum": list(tl)},
                                               "why": {"type": "string"}}, "required": ["music", "why"]}
    r = ask_claude_cli(prompt, "opus", schema)
    edl["music"] = r["music"]
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=1))
    print(f"  {name}: {r['music']} — {r['why']}")
