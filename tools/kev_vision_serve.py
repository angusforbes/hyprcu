#!/usr/bin/env python3
"""kev-vision server: one local vision-language model for hyprcu's text AND
visual decisions. Localhost only.

  POST /v1/systemone   Jev/kev-compatible text choice (state + questions of
                       type "choice"): letter probabilities from the LM head.
                       Point hyprcu at it with
                         HYPRCU_CHOOSER=kev KEV_URL=http://127.0.0.1:8010/v1/systemone
  POST /v1/ask         {"image": path, "questions": [{"question", "options"}]}
                       -> {"answers": [{"choice", "p", "probs"}], "ms"}.
                       The image is encoded once for all questions.
  POST /v1/locate      {"image": path, "target"} -> {"point": [x, y] | null}
                       in image pixels (Qwen3-VL grounding, 0-1000 grid).
  POST /v1/read        {"image": path, "question", "max_new_tokens"?}
                       -> {"text", "ms", "tokens"}: a short generated answer
                       for open questions ("which files are listed?").

Run with kev's venv (torch, transformers>=4.57, bitsandbytes, torchvision):
  ~/Work/kev/.venv/bin/python tools/kev_vision_serve.py [--port 8010]
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vision_bench"))
from kev_vision import LETTERS, KevVision  # noqa: E402

_lock = threading.Lock()  # one GPU, one request at a time
kv: KevVision | None = None


def text_choice(state: str, instructions: str, criteria: dict[str, str]) -> dict:
    keys = list(criteria)
    lines = [f"{LETTERS[i]}) {criteria[k]}" for i, k in enumerate(keys)]
    prompt = (
        f"{state}\n\n{instructions}\n" + "\n".join(lines)
        + "\nReply with only the letter of the answer."
    )
    probs = kv.text_probs(prompt, len(keys))
    best = max(range(len(keys)), key=probs.__getitem__)
    return {
        "choice": keys[best],
        "probabilities": {k: probs[i] for i, k in enumerate(keys)},
    }


def ask(image: str, questions: list[dict]) -> list[dict]:
    qs = []
    for q in questions:
        opts = q["options"]
        lines = [f"{LETTERS[i]}) {o}" for i, o in enumerate(opts)]
        qs.append((
            f"Look at the screenshot and answer: {q['question']}\n" + "\n".join(lines)
            + "\nReply with only the letter of the answer.",
            len(opts),
        ))
    res = kv.many(image, qs)
    out = []
    for q, probs in zip(questions, res["probs"], strict=True):
        best = max(range(len(probs)), key=probs.__getitem__)
        out.append({"choice": q["options"][best], "p": probs[best],
                    "probs": dict(zip(q["options"], probs, strict=True))})
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"ok": True, "model": kv.model_id})

    def do_POST(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
            t0 = time.monotonic()
            with _lock:
                if self.path == "/v1/systemone":
                    answers = {
                        name: text_choice(req.get("state", ""), q.get("instructions", ""),
                                          q["criteria"])
                        for name, q in req["questions"].items()
                        if q.get("type", "choice") == "choice"
                    }
                    out = {"answers": answers}
                elif self.path == "/v1/ask":
                    out = {"answers": ask(req["image"], req["questions"])}
                elif self.path == "/v1/locate":
                    pt, raw = kv.locate(req["image"], req["target"])
                    out = {"point": pt, "raw": raw[:200]}
                elif self.path == "/v1/read":
                    text, _s, n = kv.read(req["image"], req["question"],
                                          int(req.get("max_new_tokens", 120)))
                    out = {"text": text, "tokens": n}
                else:
                    return self._send(404, {"error": f"no endpoint {self.path}"})
            out["ms"] = int((time.monotonic() - t0) * 1000)
            self._send(200, out)
        except Exception as exc:  # report, never crash the server
            self._send(400, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    global kv
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    t = time.monotonic()
    kv = KevVision(a.model) if a.model else KevVision()
    kv.model_id = a.model or "Qwen/Qwen3-VL-4B-Instruct"
    kv.text_probs("Warm-up. A) yes B) no", 2)
    print(f"kev-vision ready in {time.monotonic() - t:.1f}s on 127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
