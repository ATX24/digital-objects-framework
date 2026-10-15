"""A small, escaped inspection report derived from campaign artifacts."""

from html import escape
import json
from pathlib import Path


def render(campaign: dict, destination: Path) -> Path:
    content = []
    for result in campaign["results"]:
        metrics = [
            {
                "seed": p["seed"],
                "parent": p.get("parent_score"),
                "candidate": p.get("candidate_score"),
                "delta": p["delta"],
            }
            for p in result.get("panels", [])
        ]
        content.append(
            f"<section><h2>{escape(result['reason'])}</h2>"
            f"<pre>{escape(json.dumps(metrics, indent=2))}</pre>"
            f"<details open><summary>Source change</summary><pre>{escape(result.get('diff', ''))}</pre></details>"
            f"<details><summary>Evaluations and native trace references</summary>"
            f"<pre>{escape(json.dumps(result, indent=2))}</pre></details></section>"
        )
    destination.write_text(
        """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Digital object · Learning report</title><style>
body{max-width:1000px;margin:60px auto;padding:0 24px;background:#faf9f5;color:#202723;font:16px/1.6 system-ui}
h1{font-size:36px;letter-spacing:-1px}section{border-top:1px solid #ccd4ca;padding:24px 0}
pre{overflow:auto;white-space:pre-wrap;font:13px/1.6 monospace;background:#edf0e8;padding:20px;border-radius:8px}
summary{cursor:pointer}small{color:#566459}</style><h1>Digital object</h1>
<p>Run → traces → evaluate → optimize → compare → retain.</p>"""
        + f"<small>Mode: {escape(campaign['mode'])} · Fresh calls: {campaign['fresh_calls']}</small>"
        + f"<p>Retained source: <code>{escape(campaign['retained'])}</code></p>"
        + "".join(content)
        + "</html>"
    )
    return destination
