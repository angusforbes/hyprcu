"""kev-vision: local screenshot decisions, Visual-Jev style.

A small vision-language model (Qwen3-VL-4B-Instruct, NF4 on the laptop GPU)
answers lettered multiple-choice questions about a screenshot WITHOUT
generating text: one forward pass, then the next-token probabilities of the
option letters are read from the LM head and renormalised. That is the
readout the Visual Jev paper (arXiv 2609.25845) found as good as a trained
decision head.

Shared prefix: the image is encoded once per screenshot. The prompt is split
into prefix (chat header + image) and suffix (question + options + assistant
header); the prefix's KV cache is kept and each question runs only its
suffix, then the cache is cropped back to the prefix for the next one.

Run with kev's venv (torch, transformers>=4.57, bitsandbytes):
  ~/Work/kev/.venv/bin/python tools/vision_bench/run.py kev-vision
"""

from __future__ import annotations

import time
from typing import Any

MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
LETTERS = "ABCDEFGHIJKLMNOP"
_MARK = "\u2063QUESTION\u2063"  # a placeholder that cannot occur in real text


class KevVision:
    def __init__(self, model_id: str = MODEL_ID, max_pixels: int = 1568 * 1000):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(
            model_id, min_pixels=256 * 32 * 32, max_pixels=max_pixels
        )
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_id,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                # the vision tower stays in bf16: quantising it hurts reading
                llm_int8_skip_modules=["visual", "lm_head"],
            ),
            device_map="cuda",
            dtype=torch.bfloat16,
        ).eval()
        tok = self.processor.tokenizer
        self.letter_ids = []
        for ch in LETTERS:
            ids = tok.encode(ch, add_special_tokens=False)
            if len(ids) != 1:
                raise RuntimeError(f"letter {ch!r} is not a single token: {ids}")
            self.letter_ids.append(ids[0])

    def _split_prompt(self, image: Any) -> tuple[str, str]:
        """(prefix, suffix template) of the chat prompt, split where the
        question text goes. The suffix contains _MARK to be replaced."""
        messages = [
            {"role": "user", "content": [{"type": "image", "image": image},
                                         {"type": "text", "text": _MARK}]}
        ]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        i = text.index(_MARK)
        return text[:i], text[i:]

    def _probs(self, logits: Any, n: int) -> list[float]:
        sel = logits[self.letter_ids[:n]].float()
        return self.torch.softmax(sel, dim=-1).tolist()

    def text_probs(self, prompt: str, n: int) -> list[float]:
        """Letter probabilities for a text-only question (no image): the same
        readout, so one model serves hyprcu's text choices too."""
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(text=[text], return_tensors="pt").to("cuda")
        with self.torch.inference_mode():
            out = self.model(**inputs)
        return self._probs(out.logits[0, -1], n)

    def read(self, image_path: str, question: str, max_new_tokens: int = 120):
        """A short generated answer to an open question about an image.
        Returns (text, seconds, tokens)."""
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        messages = [{"role": "user", "content": [
            {"type": "image", "image": img},
            {"type": "text", "text": question + "\nAnswer briefly and factually; "
             "say 'not visible' if the screenshot does not show it."}]}]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(text=[text], images=[img], return_tensors="pt").to("cuda")
        t0 = time.monotonic()
        with self.torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        new = out[0, inputs["input_ids"].shape[1]:]
        return (self.processor.tokenizer.decode(new, skip_special_tokens=True).strip(),
                time.monotonic() - t0, len(new))

    def locate(self, image_path: str, target: str):
        """Where `target` is in the image, as (x, y) image pixels of its centre,
        or None. Qwen3-VL grounds objects as bbox_2d on a 0-1000 grid."""
        import json as _json
        import re as _re

        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        prompt = (f'Locate "{target}" in the image. Output its bounding box as JSON: '
                  '[{"bbox_2d": [x1, y1, x2, y2], "label": "..."}]. '
                  'If it is not visible, output [].')
        messages = [{"role": "user", "content": [{"type": "image", "image": img},
                                                 {"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(text=[text], images=[img], return_tensors="pt").to("cuda")
        with self.torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=80, do_sample=False)
        raw = self.processor.tokenizer.decode(
            out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )
        m = _re.search(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,"
                       r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", raw)
        if not m:
            return None, raw
        x1, y1, x2, y2 = (float(v) for v in m.groups())
        w, h = img.size
        _ = _json  # (kept for callers that want the raw JSON)
        return ((x1 + x2) / 2 / 1000 * w, (y1 + y2) / 2 / 1000 * h), raw

    def full(self, image_path: str, question: str, n: int) -> list[float]:
        """Reference path: one full forward pass for one question."""
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        prefix, suffix = self._split_prompt(img)
        text = prefix + suffix.replace(_MARK, question)
        inputs = self.processor(text=[text], images=[img], return_tensors="pt").to("cuda")
        with self.torch.inference_mode():
            out = self.model(**inputs)
        return self._probs(out.logits[0, -1], n)

    def many(self, image_path: str, questions: list[tuple[str, int]]) -> dict[str, Any]:
        """Answer several questions about one image with a shared prefix.

        Returns {"probs": [...per question...], "prefix_s": .., "suffix_s": [..]}.
        """
        from PIL import Image
        from transformers import DynamicCache

        torch = self.torch
        img = Image.open(image_path).convert("RGB")
        prefix, suffix_tpl = self._split_prompt(img)
        t0 = time.monotonic()
        pre = self.processor(text=[prefix], images=[img], return_tensors="pt").to("cuda")
        cache = DynamicCache()
        with torch.inference_mode():
            self.model(**pre, past_key_values=cache, use_cache=True)
        torch.cuda.synchronize()
        prefix_len = pre["input_ids"].shape[1]
        prefix_s = time.monotonic() - t0

        tok = self.processor.tokenizer
        out_probs, suffix_s = [], []
        for question, n in questions:
            t1 = time.monotonic()
            ids = tok(suffix_tpl.replace(_MARK, question), add_special_tokens=False,
                      return_tensors="pt")["input_ids"].to("cuda")
            pos = torch.arange(prefix_len, prefix_len + ids.shape[1], device="cuda")
            attn = torch.ones(1, prefix_len + ids.shape[1], dtype=torch.long, device="cuda")
            with torch.inference_mode():
                out = self.model(input_ids=ids, past_key_values=cache, use_cache=True,
                                 cache_position=pos, attention_mask=attn)
            out_probs.append(self._probs(out.logits[0, -1], n))
            cache.crop(prefix_len)  # rewind to "image seen, no question yet"
            torch.cuda.synchronize()
            suffix_s.append(time.monotonic() - t1)
        return {"probs": out_probs, "prefix_s": prefix_s, "suffix_s": suffix_s}


DESCRIBE_PROMPT = (
    "Describe this screenshot for someone who cannot see it and must answer questions "
    "about it. List: the app and window/tab titles; all readable text, verbatim where short; "
    "every button, link, field, checkbox and menu with its current value or state (checked, "
    "selected, typed text); any dialog, popup, error, warning or loading indicator; and the "
    "layout (what is where). Be factual and concise; do not guess what is not visible."
)


def describe(kv: KevVision, image_path: str, max_new_tokens: int = 400) -> tuple[str, float, int]:
    """One general description of a screenshot (for a text-only decider such as
    Jev). Returns (text, seconds, generated tokens)."""
    from PIL import Image

    torch = kv.torch
    img = Image.open(image_path).convert("RGB")
    messages = [{"role": "user", "content": [{"type": "image", "image": img},
                                             {"type": "text", "text": DESCRIBE_PROMPT}]}]
    text = kv.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = kv.processor(text=[text], images=[img], return_tensors="pt").to("cuda")
    t0 = time.monotonic()
    with torch.inference_mode():
        out = kv.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    new = out[0, inputs["input_ids"].shape[1]:]
    secs = time.monotonic() - t0
    return kv.processor.tokenizer.decode(new, skip_special_tokens=True).strip(), secs, len(new)
