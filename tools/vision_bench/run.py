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
  kev-vision[:<hf id>]  local VLM, letter probabilities from the LM head, image
                        encoded once per screenshot (see kev_vision.py; run
                        this script with ~/Work/kev/.venv/bin/python)
  vlm+jev[:<hf id>]     the local VLM writes ONE description per screenshot;
                        TypeSafe Jev answers every question from that text
                        (the description goes to TypeSafe; the image stays)

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
DESC_LOG = PRIVATE / "results" / "last-descriptions.json"
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


def _row(backend: str, item: dict, got: int | None, secs: float, reply: str) -> dict:
    gold = item["options"].index(item["answer"])
    return {
        "backend": backend, "image": item["image"], "tag": item["tag"],
        "kind": item["kind"], "source": item["source"], "crop": bool(item.get("crop")),
        "question": item["question"], "gold": item["answer"],
        "got": item["options"][got] if got is not None else None,
        "ok": got == gold, "secs": round(secs, 3), "reply": reply[:80],
    }


def run_kev_vision(backend: str, items: list[dict], max_edge: int) -> list[dict]:
    sys.path.insert(0, str(HERE))
    from kev_vision import MODEL_ID, KevVision

    model_id = backend.partition(":")[2] or MODEL_ID
    t = time.monotonic()
    kv = KevVision(model_id)
    print(f"{backend}: loaded in {time.monotonic() - t:.1f} s", file=sys.stderr)
    groups: dict[Path, list[dict]] = defaultdict(list)
    for item in items:
        groups[prepared(item, max_edge)].append(item)
    kv.many(str(next(iter(groups))), [("warm-up", 2)])  # CUDA kernels, allocator
    rows = []
    for img, group in groups.items():
        res = kv.many(str(img), [(prompt(i), len(i["options"])) for i in group])
        share = res["prefix_s"] / len(group)
        for item, probs, sfx in zip(group, res["probs"], res["suffix_s"], strict=True):
            got = max(range(len(probs)), key=probs.__getitem__)
            row = _row(backend, item, got, share + sfx, f"p={probs[got]:.2f}")
            row["p"] = round(probs[got], 3)
            row["p_gold"] = round(probs[item["options"].index(item["answer"])], 3)
            row["prefix_s"] = round(res["prefix_s"], 3)
            rows.append(row)
    return rows


def run_vlm_jev(backend: str, items: list[dict], jobs: int, max_edge: int) -> list[dict]:
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent.parent / "src"))
    import os

    from kev_vision import MODEL_ID, KevVision, describe

    from hyprcu import pick

    os.environ.setdefault("HYPRCU_CHOOSER", "jev")
    kv = KevVision(backend.partition(":")[2] or MODEL_ID)
    groups: dict[Path, list[dict]] = defaultdict(list)
    for item in items:
        groups[prepared(item, max_edge)].append(item)
    describe(kv, str(next(iter(groups))), max_new_tokens=8)  # warm-up
    descs = {}
    for img in groups:
        text, secs, ntok = describe(kv, str(img))
        descs[img] = (text, secs, ntok)
        print(f"  described {img.name}: {ntok} tokens in {secs:.1f} s", file=sys.stderr)
    DESC_LOG.parent.mkdir(parents=True, exist_ok=True)
    DESC_LOG.write_text(json.dumps({str(k): v for k, v in descs.items()}, indent=1))

    def one(pair: tuple[Path, dict]) -> dict:
        img, item = pair
        text, dsecs, _n = descs[img]
        opts = CLAIM_HELP if item["kind"] == "claim" else None
        crit = {LETTERS[i]: (opts[o] if opts else o) for i, o in enumerate(item["options"])}
        if item["kind"] == "claim":
            instr = f"Based only on the screenshot description, is this claim: {item['question']}"
        else:
            instr = f"Based only on the screenshot description: {item['question']}"
        state = f"Description of a screenshot:\n{text}"
        ans = pick.choose(state, instr, crit)
        got = LETTERS.index(ans["choice"]) if ans and ans["choice"] in crit else None
        secs = dsecs / len(groups[img]) + (ans["ms"] / 1000 if ans else 0)
        row = _row(backend, item, got, secs, f"p={ans['p']:.2f}" if ans else "jev failed")
        row["p"] = round(ans["p"], 3) if ans else 0.0
        return row

    pairs = [(img, it) for img, g in groups.items() for it in g]
    with cf.ThreadPoolExecutor(jobs) as pool:
        return list(pool.map(one, pairs))


def run(backend: str, items: list[dict], jobs: int, max_edge: int) -> list[dict]:
    kind, _, model = backend.partition(":")
    if kind == "kev-vision":
        return run_kev_vision(backend, items, max_edge)
    if kind == "vlm+jev":
        return run_vlm_jev(backend, items, jobs, max_edge)
    if kind != "pi":
        raise SystemExit(f"unknown backend {backend!r} (pi:<provider/model> | kev-vision)")

    def one(item: dict) -> dict:
        img = prepared(item, max_edge)
        reply, secs = ask_pi(model, img, prompt(item))
        return _row(backend, item, parse(reply, len(item["options"])), secs, reply)

    with cf.ThreadPoolExecutor(jobs) as pool:
        return list(pool.map(one, items))


def report(results: list[dict]) -> None:
    by_backend = defaultdict(list)
    for r in results:
        by_backend[r["backend"]].append(r)
    for backend, rs in by_backend.items():
        n, ok = len(rs), sum(r["ok"] for r in rs)
        med = statistics.median(r["secs"] for r in rs)
        unit = "s/q (incl. pi startup)" if backend.startswith("pi:") else "s/q (amortised)"
        print(f"\n{backend}: {ok}/{n} = {ok / n:.0%}   median {med:.2f} {unit}")
        if "p" in rs[0]:  # calibrated backends: does low confidence flag the errors?
            wrong = [r["p"] for r in rs if not r["ok"]]
            right = [r["p"] for r in rs if r["ok"]]
            print(f"  mean p when right {statistics.mean(right) if right else 0:.2f}, "
                  f"when wrong {statistics.mean(wrong) if wrong else 0:.2f}")
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
