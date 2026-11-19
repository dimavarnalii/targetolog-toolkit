"""tl_inspect.py NAME [step_sec] -> prints timed transcript (line per phrase) + timeline contact sheet of proxy/NAME.mp4
(preview/t_NAME.png). Run from the project folder."""
import json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vm_config as vm  # noqa: E402

P = Path.cwd()  # run from the project folder
(P / "preview").mkdir(exist_ok=True)
n = sys.argv[1]
step = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
wf = P / f"{n}.words_m.json"
if not wf.exists():
    wf = P / f"{n}.words.json"
d = json.loads(wf.read_text(encoding="utf-8"))
line, prev = "", 0
for w in d["words"]:
    if w["start"] - prev > 0.6 and line:
        print(line); line = ""
    if not line:
        line = f"[{w['start']:6.2f}] "
    line += w["word"] + " "
    prev = w["end"]
print(line)
dur = float(subprocess.run([vm.FFPROBE, "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(P / "proxy" / f"{n}.mp4")], capture_output=True, text=True).stdout)
cols = 12
rows = int(dur // step // cols) + 1
subprocess.run([vm.FFMPEG, "-y", "-v", "error", "-i", str(P / "proxy" / f"{n}.mp4"), "-vf",
                f"fps=1/{step},scale=150:-2,drawtext={vm.drawtext_font_opt()}text='%{{pts\\:gmtime\\:0\\:%M\\\\\\:%S}}':"
                "fontcolor=yellow:fontsize=20:box=1:boxcolor=black,"
                f"tile={cols}x{rows}", "-frames:v", "1", str(P / "preview" / f"t_{n}.png")], check=True)
