#!/usr/bin/env python3
"""Vision-decision benchmark: can a fast model answer an agent's questions
about a screenshot?

Questions are what an agent asks after acting, not puzzles: read a value,
locate a control, is a dialog up / still loading, which option is selected,
and claims the screenshot cannot settle ("cannot tell"). Each is a choice
among lettered options; the model replies with one letter.

  public  tools/vision_bench/questions.json + images/   (nested test session)
  private ~/.local/share/hyprcu/vision-bench/           (Angus's real desktop;
          never committed)

Backends:
  pi:<provider/model>   one-shot `pi -p` with the image attached (includes
                        ~1 s of pi startup; reported separately)

Usage:
  tools/vision_bench/run.py pi:anthropic/claude-haiku-4-5 pi:anthropic/claude-sonnet-4-6
  tools/vision_bench/run.py --set public --jobs 4 pi:anthropic/claude-haiku-4-5
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIVATE = Path.home() / ".local/share/hyprcu/vision-bench"
CACHE = Path("/tmp/hyprcu-vision-bench")
LETTERS = "ABCDEFGHIJKLMNOP"
CLAIM_HELP = {
    "supported": "supported (the screenshot shows the claim is true)",
    "contradicted": "contradicted (the screenshot shows the claim is false)",
    "cannot tell": "cannot tell (the screenshot does not show enough to decide)",
}


def load(which: str) -> list[dict]:
    items = []
    if which in ("public", "all"):
        for q in json.loads((HERE / "questions.json").read_text()):
            path = HERE / "images" / f"{q['image']}.jpg"
            items.append({**q, "source": "public", "path": path})
    if which in ("private", "all") and (PRIVATE / "questions.json").exists():
        for q in json.loads((PRIVATE / "questions.json").read_text()):
            items.append(
                {**q, "source": "private", "path": PRIVATE / "images" / f"{q['image']}.jpg"}
            )
    return items


def prepared(item: dict, max_edge: int) -> Path:
    """The image as hyprcu would deliver it: optional crop, long edge capped."""
    key = hashlib.sha1(f"{item['path']}|{item.get('crop')}|{max_edge}".encode()).hexdigest()[:12]
    out = CACHE / f"{item['image']}-{key}.jpg"
    if not out.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        args = ["magick", str(item["path"])]
        if item.get("crop"):
            x, y, w, h = item["crop"]
            args += ["-crop", f"{w}x{h}+{x}+{y}", "+repage"]
        args += ["-resize", f"{max_edge}x{max_edge}>", "-quality", "90", str(out)]
        subprocess.run(args, check=True)
    return out


def prompt(item: dict) -> str:
    if item["kind"] == "claim":
        head = f"Look at the screenshot. Claim: {item['question']}\nIs the claim:"
        opts = [CLAIM_HELP[o] for o in item["options"]]
    else:
        head = f"Look at the screenshot and answer: {item['question']}"
        opts = item["options"]
    lines = [f"{LETTERS[i]}) {o}" for i, o in enumerate(opts)]
    return head + "\n" + "\n".join(lines) + "\nReply with only the letter of the answer."


def parse(text: str, n: int) -> int | None:
    m = re.search(rf"\b([{LETTERS[:n]}])\b", text.strip())
    return LETTERS.index(m.group(1)) if m else None


def ask_pi(model: str, image: Path, text: str) -> tuple[str, float]:
    t = time.monotonic()
    proc = subprocess.run(
        ["pi", "-p", "--no-session", "-nt", "-ne", "-ns", "-np", "-nc",
         "--model", model, "--thinking", "off", f"@{image}", text],
        capture_output=True, text=True, timeout=180,
    )
    return (proc.stdout or proc.stderr).strip(), time.monotonic() - t


def run(backend: str, items: list[dict], jobs: int, max_edge: int) -> list[dict]:
    kind, _, model = backend.partition(":")
    if kind != "pi":
        raise SystemExit(f"unknown backend {backend!r} (want pi:<provider/model>)")

    def one(item: dict) -> dict:
        img = prepared(item, max_edge)
        reply, secs = ask_pi(model, img, prompt(item))
        got = parse(reply, len(item["options"]))
        gold = item["options"].index(item["answer"])
        return {
            "backend": backend, "image": item["image"], "tag": item["tag"],
            "kind": item["kind"], "source": item["source"], "crop": bool(item.get("crop")),
            "question": item["question"], "gold": item["answer"],
            "got": item["options"][got] if got is not None else None,
            "ok": got == gold, "secs": round(secs, 2), "reply": reply[:80],
        }

    with cf.ThreadPoolExecutor(jobs) as pool:
        return list(pool.map(one, items))


def report(results: list[dict]) -> None:
    by_backend = defaultdict(list)
    for r in results:
        by_backend[r["backend"]].append(r)
    for backend, rs in by_backend.items():
        n, ok = len(rs), sum(r["ok"] for r in rs)
        med = statistics.median(r["secs"] for r in rs)
        print(f"\n{backend}: {ok}/{n} = {ok / n:.0%}   median {med:.1f} s/q (incl. pi startup)")
        for field in ("tag", "source"):
            groups = defaultdict(list)
            for r in rs:
                groups[r[field]].append(r["ok"])
            print("  " + "  ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(groups.items())))
        for r in rs:
            if not r["ok"]:
                crop = " [crop]" if r["crop"] else ""
                q = r["question"][:60]
                print(f"  ✗ {r['image']}{crop}: {q!r} gold={r['gold']!r} got={r['got']!r}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("backends", nargs="+")
    ap.add_argument("--set", choices=("public", "private", "all"), default="all")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", default="", help="regex on image name")
    ap.add_argument("--max-edge", type=int, default=1568, help="hyprcu's default image cap")
    a = ap.parse_args()
    items = [i for i in load(a.set) if re.search(a.only, i["image"])]
    if not items:
        raise SystemExit("no questions found")
    print(f"{len(items)} questions ({a.set})", file=sys.stderr)
    results = []
    for b in a.backends:
        results += run(b, items, a.jobs, a.max_edge)
    outdir = PRIVATE / "results"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in results))
    report(results)
    print(f"\nresults: {out}")


if __name__ == "__main__":
    main()
