"""Preview bundle inspection, live session rendering, and popup helpers."""

from __future__ import annotations

import functools
import html
import json
import os
import shutil
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_bundle_ref(bundle_ref: str) -> Tuple[Path, Path]:
    ref = Path(bundle_ref).expanduser().resolve()
    if ref.is_dir():
        manifest = ref / "manifest.json"
        if not manifest.is_file():
            raise FileNotFoundError(f"manifest.json not found in bundle directory: {ref}")
        return ref, manifest
    if ref.is_file():
        if ref.name != "manifest.json":
            raise ValueError("Bundle ref must be a bundle directory or a manifest.json path")
        return ref.parent, ref
    raise FileNotFoundError(f"Bundle ref not found: {bundle_ref}")


def resolve_session_ref(session_ref: str) -> Tuple[Path, Path]:
    ref = Path(session_ref).expanduser().resolve()
    if ref.is_dir():
        session_path = ref / "session.json"
        if not session_path.is_file():
            raise FileNotFoundError(f"session.json not found in live session directory: {ref}")
        return ref, session_path
    if ref.is_file():
        if ref.name != "session.json":
            raise ValueError("Session ref must be a live session directory or a session.json path")
        return ref.parent, ref
    raise FileNotFoundError(f"Session ref not found: {session_ref}")


def is_live_session_ref(preview_ref: str) -> bool:
    ref = Path(preview_ref).expanduser().resolve()
    if ref.is_dir():
        return (ref / "session.json").is_file()
    return ref.is_file() and ref.name == "session.json"


def load_bundle(bundle_ref: str) -> Tuple[Path, Dict[str, Any], Dict[str, Any]]:
    bundle_dir, manifest_path = resolve_bundle_ref(bundle_ref)
    manifest = _read_json(manifest_path)
    summary_rel = manifest.get("summary_path", "summary.json")
    summary_path = (bundle_dir / summary_rel).resolve()
    summary = _read_json(summary_path) if summary_path.is_file() else {}
    return bundle_dir, manifest, summary


def load_session(session_ref: str) -> Tuple[Path, Dict[str, Any]]:
    session_dir, session_path = resolve_session_ref(session_ref)
    return session_dir, _read_json(session_path)


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def inspect_bundle(bundle_ref: str) -> Dict[str, Any]:
    bundle_dir, manifest, summary = load_bundle(bundle_ref)
    return {
        "bundle_dir": str(bundle_dir),
        "manifest": manifest,
        "summary": summary,
        "artifact_count": len(manifest.get("artifacts", [])),
    }


def inspect_session(session_ref: str) -> Dict[str, Any]:
    session_dir, session = load_session(session_ref)
    current_bundle = None
    try:
        current_bundle = inspect_bundle(str(session_dir / session.get("current_link", "current")))
    except (FileNotFoundError, ValueError):
        current_bundle = None
    return {
        "session_dir": str(session_dir),
        "session": session,
        "current_bundle": current_bundle,
    }


def render_inspect_text(bundle_ref: str) -> str:
    bundle_dir, manifest, summary = load_bundle(bundle_ref)
    lines = [
        f"Bundle:      {bundle_dir}",
        f"Protocol:    {manifest.get('protocol_version', 'unknown')}",
        f"Software:    {manifest.get('software', 'unknown')}",
        f"Recipe:      {manifest.get('recipe', 'unknown')}",
        f"Kind:        {manifest.get('bundle_kind', 'unknown')}",
        f"Status:      {manifest.get('status', 'unknown')}",
        f"Created:     {manifest.get('created_at', 'unknown')}",
    ]
    source = manifest.get("source", {})
    if source:
        lines.append(
            "Source:      "
            + (
                source.get("project_path")
                or source.get("capture_path")
                or source.get("project_name")
                or "n/a"
            )
        )
        if source.get("project_fingerprint"):
            lines.append(f"Fingerprint: {source['project_fingerprint']}")
        elif source.get("capture_fingerprint"):
            lines.append(f"Fingerprint: {source['capture_fingerprint']}")
    if summary:
        lines.append("")
        lines.append("Summary")
        lines.append(f"  Headline: {summary.get('headline', '(none)')}")
        facts = summary.get("facts", {})
        for key, value in facts.items():
            lines.append(f"  {key}: {value}")
        for warning in summary.get("warnings", []):
            lines.append(f"  Warning: {warning}")
    lines.append("")
    lines.append("Artifacts")
    for artifact in manifest.get("artifacts", []):
        desc = (
            f"  - {artifact.get('artifact_id', '?')} "
            f"[{artifact.get('role', '?')}] {artifact.get('label', '')}"
        )
        desc += f" -> {artifact.get('path', '')}"
        if artifact.get("bytes") is not None:
            desc += f" ({format_bytes(int(artifact['bytes']))})"
        lines.append(desc)
    return "\n".join(lines) + "\n"


def render_session_text(session_ref: str) -> str:
    session_dir, session = load_session(session_ref)
    lines = [
        f"Live Session: {session_dir}",
        f"Protocol:     {session.get('protocol_version', 'unknown')}",
        f"Software:     {session.get('software', 'unknown')}",
        f"Recipe:       {session.get('recipe', 'unknown')}",
        f"Status:       {session.get('status', 'unknown')}",
        f"Updated:      {session.get('updated_at', 'unknown')}",
        f"Current:      {session.get('current_bundle_id', 'n/a')}",
        f"Project:      {session.get('project_path') or session.get('project_name') or 'n/a'}",
    ]
    if session.get("watch_command"):
        lines.append(f"Watch:        {session['watch_command']}")
    history = session.get("history", [])
    if history:
        lines.append("")
        lines.append("History")
        for item in history:
            lines.append(
                f"  - {item.get('bundle_id', '?')} "
                f"[{item.get('status', 'unknown')}] {item.get('created_at', 'unknown')}"
            )
    return "\n".join(lines) + "\n"


def _artifact_href(output_dir: Path, bundle_dir: Path, artifact_path: str) -> str:
    target = (bundle_dir / artifact_path).resolve()
    return os.path.relpath(target, output_dir)


def _render_artifact_card(output_dir: Path, bundle_dir: Path, artifact: Dict[str, Any]) -> str:
    role = html.escape(artifact.get("role", "artifact"))
    label = html.escape(artifact.get("label", artifact.get("artifact_id", "artifact")))
    path_ref = _artifact_href(output_dir, bundle_dir, artifact.get("path", ""))
    media_type = artifact.get("media_type", "")
    size = artifact.get("bytes")
    meta = []
    if artifact.get("width") and artifact.get("height"):
        meta.append(f"{artifact['width']}×{artifact['height']}")
    if artifact.get("duration_s") is not None:
        meta.append(f"{artifact['duration_s']}s")
    if size is not None:
        meta.append(format_bytes(int(size)))
    meta_line = " · ".join(meta)

    if media_type.startswith("image/"):
        body = f'<img src="{html.escape(path_ref)}" alt="{label}" loading="lazy">'
    elif media_type.startswith("video/"):
        body = (
            f'<video controls preload="metadata" src="{html.escape(path_ref)}">'
            "Your browser does not support embedded video."
            "</video>"
        )
    else:
        body = (
            '<div class="artifact-file">'
            f'<a href="{html.escape(path_ref)}">{html.escape(artifact.get("path", ""))}</a>'
            "</div>"
        )

    badge = f'<span class="artifact-role">{role}</span>'
    details = f'<div class="artifact-meta">{html.escape(meta_line)}</div>' if meta_line else ""
    return (
        '<article class="artifact-card">'
        f"{badge}"
        f'<h3>{label}</h3>'
        f"{details}"
        f"{body}"
        "</article>"
    )


def render_html(bundle_ref: str, output_path: str) -> str:
    bundle_dir, manifest, summary = load_bundle(bundle_ref)
    output_file = Path(output_path).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    headline = html.escape(
        summary.get("headline", f"{manifest.get('software', 'Preview')} preview bundle")
    )
    warnings = summary.get("warnings", [])
    facts = summary.get("facts", {})
    fact_cards = "".join(
        f'<div class="fact-card"><span>{html.escape(str(key))}</span><strong>{html.escape(str(value))}</strong></div>'
        for key, value in facts.items()
    )
    warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in warnings)
    artifact_cards = "".join(
        _render_artifact_card(output_file.parent, bundle_dir, artifact)
        for artifact in manifest.get("artifacts", [])
    )

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(manifest.get("software", "Preview"))} Preview Bundle</title>
  <style>
    :root {{
      --paper: #f6f1e8;
      --ink: #171717;
      --muted: #5b554c;
      --panel: rgba(255,255,255,0.68);
      --edge: rgba(23,23,23,0.14);
      --accent: #b23a2b;
      --accent-soft: rgba(178,58,43,0.1);
      --shadow: 0 20px 60px rgba(25,20,14,0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Georgia", "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(178,58,43,0.12), transparent 28rem),
        radial-gradient(circle at bottom right, rgba(23,23,23,0.08), transparent 30rem),
        linear-gradient(180deg, #fbf7ef 0%, var(--paper) 100%);
      min-height: 100vh;
    }}
    .shell {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 32px 18px 60px;
    }}
    .hero {{
      border: 1px solid var(--edge);
      background: var(--panel);
      backdrop-filter: blur(10px);
      box-shadow: var(--shadow);
      border-radius: 28px;
      overflow: hidden;
    }}
    .hero-top {{
      padding: 28px 28px 18px;
      border-bottom: 1px solid var(--edge);
      display: grid;
      gap: 16px;
      background:
        linear-gradient(135deg, rgba(178,58,43,0.12), transparent 45%),
        linear-gradient(180deg, rgba(255,255,255,0.9), rgba(255,255,255,0.58));
    }}
    .kicker {{
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 12px;
      color: var(--muted);
    }}
    h1 {{
      margin: 0;
      font-size: clamp(2rem, 4vw, 4rem);
      line-height: 0.92;
      font-weight: 600;
    }}
    .subtitle {{
      color: var(--muted);
      font-size: 1rem;
      max-width: 60rem;
    }}
    .facts {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
    }}
    .fact-card {{
      border: 1px solid var(--edge);
      border-radius: 18px;
      background: rgba(255,255,255,0.72);
      padding: 14px 16px;
    }}
    .fact-card span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 8px;
    }}
    .fact-card strong {{
      font-size: 1.02rem;
    }}
    .warning-box {{
      margin-top: 16px;
      border: 1px solid rgba(178,58,43,0.28);
      background: var(--accent-soft);
      border-radius: 18px;
      padding: 14px 18px;
    }}
    .warning-box ul {{
      margin: 10px 0 0;
      padding-left: 18px;
    }}
    .meta-grid {{
      padding: 24px 28px 28px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .meta-item {{
      border-left: 2px solid var(--accent);
      padding-left: 12px;
      color: var(--muted);
    }}
    .meta-item strong {{
      color: var(--ink);
      display: block;
      margin-top: 4px;
    }}
    .section {{
      margin-top: 28px;
    }}
    .section h2 {{
      margin: 0 0 14px;
      font-size: 1.1rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }}
    .artifact-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 18px;
    }}
    .artifact-card {{
      position: relative;
      border: 1px solid var(--edge);
      border-radius: 24px;
      background: rgba(255,255,255,0.78);
      padding: 16px;
      box-shadow: 0 16px 40px rgba(33,28,22,0.08);
      overflow: hidden;
    }}
    .artifact-role {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      padding: 6px 10px;
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }}
    .artifact-card h3 {{
      margin: 0 0 8px;
      font-size: 1.08rem;
    }}
    .artifact-meta {{
      color: var(--muted);
      font-size: 0.9rem;
      margin-bottom: 14px;
    }}
    .artifact-card img,
    .artifact-card video {{
      display: block;
      width: 100%;
      border-radius: 16px;
      border: 1px solid var(--edge);
      background: #ffffff;
    }}
    .artifact-file {{
      border: 1px dashed var(--edge);
      border-radius: 16px;
      padding: 14px;
      background: rgba(255,255,255,0.58);
      word-break: break-word;
    }}
    .artifact-file a {{
      color: var(--accent);
      text-decoration: none;
    }}
    @media (max-width: 720px) {{
      .shell {{ padding: 18px 12px 36px; }}
      .hero-top, .meta-grid {{ padding: 20px 18px; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="hero-top">
        <div class="kicker">CLI-Anything Preview Bundle</div>
        <h1>{headline}</h1>
        <div class="subtitle">Software: {html.escape(str(manifest.get("software", "unknown")))} · Recipe: {html.escape(str(manifest.get("recipe", "unknown")))} · Kind: {html.escape(str(manifest.get("bundle_kind", "capture")))}</div>
        <div class="facts">{fact_cards or '<div class="fact-card"><span>Artifacts</span><strong>' + str(len(manifest.get("artifacts", []))) + '</strong></div>'}</div>
        {"<div class='warning-box'><strong>Warnings</strong><ul>" + warning_html + "</ul></div>" if warning_html else ""}
      </div>
      <div class="meta-grid">
        <div class="meta-item">Bundle ID<strong>{html.escape(str(manifest.get("bundle_id", "unknown")))}</strong></div>
        <div class="meta-item">Status<strong>{html.escape(str(manifest.get("status", "unknown")))}</strong></div>
        <div class="meta-item">Created<strong>{html.escape(str(manifest.get("created_at", "unknown")))}</strong></div>
        <div class="meta-item">Source<strong>{html.escape(str(manifest.get("source", {}).get("project_path") or manifest.get("source", {}).get("capture_path") or "n/a"))}</strong></div>
      </div>
    </section>
    <section class="section">
      <h2>Artifacts</h2>
      <div class="artifact-grid">{artifact_cards}</div>
    </section>
  </main>
</body>
</html>
"""
    with open(output_file, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    return str(output_file)


def render_live_html(session_ref: str, output_path: str, poll_ms: int = 1500) -> str:
    session_dir, session = load_session(session_ref)
    output_file = Path(output_path).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    headline = html.escape(
        session.get("project_name")
        or session.get("project_path")
        or f"{session.get('software', 'Preview')} live preview"
    )
    poll_ms = max(250, int(poll_ms))
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(str(session.get("software", "Preview")))} Live Preview</title>
  <style>
    :root {{
      --paper: #efe8dc;
      --ink: #111215;
      --muted: #64615b;
      --panel: rgba(255,255,255,0.8);
      --panel-strong: rgba(255,255,255,0.92);
      --edge: rgba(17,18,21,0.12);
      --accent: #c24b2f;
      --accent-soft: rgba(194,75,47,0.12);
      --success: #147a4b;
      --shadow: 0 24px 60px rgba(27,22,18,0.14);
      --mono: "SFMono-Regular", "Menlo", "Consolas", monospace;
      --sans: "Avenir Next", "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: var(--sans);
      background:
        radial-gradient(circle at top left, rgba(194,75,47,0.18), transparent 24rem),
        radial-gradient(circle at bottom right, rgba(0,0,0,0.08), transparent 28rem),
        linear-gradient(180deg, #f8f2e8 0%, var(--paper) 100%);
      min-height: 100vh;
    }}
    .shell {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 22px 18px 32px;
    }}
    .masthead {{
      display: grid;
      gap: 14px;
      padding: 20px 22px;
      border: 1px solid var(--edge);
      border-radius: 28px;
      background:
        linear-gradient(135deg, rgba(194,75,47,0.14), transparent 48%),
        linear-gradient(180deg, rgba(255,255,255,0.94), rgba(255,255,255,0.7));
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 12px;
      color: var(--muted);
    }}
    .title-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: baseline;
      justify-content: space-between;
    }}
    h1 {{
      margin: 0;
      font-family: "Iowan Old Style", "Georgia", serif;
      font-size: clamp(2rem, 4vw, 3.75rem);
      line-height: 0.94;
      font-weight: 600;
    }}
    .status-chip {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 9px 14px;
      background: rgba(20,122,75,0.12);
      color: var(--success);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .status-chip[data-state="error"] {{
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .subtitle {{
      color: var(--muted);
      font-size: 1rem;
      max-width: 64rem;
    }}
    .fact-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
    }}
    .fact-card {{
      border: 1px solid var(--edge);
      border-radius: 18px;
      background: rgba(255,255,255,0.74);
      padding: 14px 16px;
    }}
    .fact-card span {{
      display: block;
      margin-bottom: 7px;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
    }}
    .fact-card strong {{
      display: block;
      font-size: 1rem;
      word-break: break-word;
    }}
    .command-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .command-chip {{
      border: 1px solid var(--edge);
      border-radius: 999px;
      padding: 10px 14px;
      background: rgba(255,255,255,0.72);
      font-family: var(--mono);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 100%;
    }}
    .grid {{
      margin-top: 20px;
      display: grid;
      grid-template-columns: minmax(0, 1.9fr) minmax(320px, 0.9fr);
      gap: 18px;
    }}
    .panel {{
      border: 1px solid var(--edge);
      border-radius: 28px;
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
      min-height: 220px;
    }}
    .panel-header {{
      padding: 16px 18px;
      border-bottom: 1px solid var(--edge);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      background: var(--panel-strong);
    }}
    .panel-header h2 {{
      margin: 0;
      font-size: 0.95rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
    }}
    .panel-body {{
      padding: 18px;
    }}
    .hero-frame {{
      display: block;
      width: 100%;
      border-radius: 20px;
      border: 1px solid var(--edge);
      background: #fff;
      min-height: 280px;
      object-fit: contain;
    }}
    video.hero-frame {{
      background: #0e1013;
    }}
    .stack {{
      display: grid;
      gap: 18px;
    }}
    .gallery {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
    }}
    .thumb {{
      border: 1px solid var(--edge);
      border-radius: 20px;
      padding: 10px;
      background: rgba(255,255,255,0.7);
    }}
    .thumb img {{
      display: block;
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--edge);
      background: #fff;
    }}
    .thumb .label {{
      margin-top: 10px;
      font-size: 0.9rem;
      font-weight: 600;
    }}
    .thumb .meta {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .notes {{
      display: grid;
      gap: 10px;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .notes ul {{
      margin: 0;
      padding-left: 18px;
    }}
    .history {{
      display: grid;
      gap: 10px;
    }}
    .history-item {{
      border: 1px solid var(--edge);
      border-radius: 16px;
      background: rgba(255,255,255,0.72);
      padding: 12px 14px;
    }}
    .history-item strong {{
      display: block;
      font-size: 0.92rem;
    }}
    .history-item span {{
      display: block;
      margin-top: 4px;
      font-size: 0.82rem;
      color: var(--muted);
      word-break: break-word;
    }}
    .empty {{
      padding: 28px;
      border: 1px dashed var(--edge);
      border-radius: 18px;
      background: rgba(255,255,255,0.46);
      color: var(--muted);
      text-align: center;
    }}
    @media (max-width: 1100px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 700px) {{
      .shell {{ padding: 14px 10px 20px; }}
      .masthead, .panel-body, .panel-header {{ padding-left: 14px; padding-right: 14px; }}
      .command-chip {{ white-space: normal; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="masthead">
      <div class="eyebrow">CLI-Anything Live Preview Session</div>
      <div class="title-row">
        <h1>{headline}</h1>
        <div id="status-chip" class="status-chip">Watching</div>
      </div>
      <div id="subtitle" class="subtitle">Polling the latest preview bundle every {poll_ms} ms.</div>
      <div id="fact-row" class="fact-row"></div>
      <div id="command-strip" class="command-strip"></div>
    </section>
    <section class="grid">
      <div class="stack">
        <article class="panel">
          <div class="panel-header">
            <h2>Hero Frame</h2>
            <span id="hero-meta" class="subtitle">Waiting for the first bundle</span>
          </div>
          <div class="panel-body" id="hero-slot">
            <div class="empty">Run <code>{html.escape(session.get("publish_command", "shotcut preview live push"))}</code> to publish or refresh the session.</div>
          </div>
        </article>
        <article class="panel">
          <div class="panel-header">
            <h2>Gallery</h2>
            <span id="gallery-meta" class="subtitle">Sampled stills for fast visual checks</span>
          </div>
          <div class="panel-body">
            <div id="gallery" class="gallery"></div>
          </div>
        </article>
      </div>
      <div class="stack">
        <article class="panel">
          <div class="panel-header">
            <h2>Review Clip</h2>
            <span id="clip-meta" class="subtitle">Low-res preview render</span>
          </div>
          <div class="panel-body" id="clip-slot">
            <div class="empty">No preview clip has been published yet.</div>
          </div>
        </article>
        <article class="panel">
          <div class="panel-header">
            <h2>Session Notes</h2>
            <span class="subtitle">Agent-native summary + refresh state</span>
          </div>
          <div class="panel-body">
            <div id="notes" class="notes"></div>
          </div>
        </article>
        <article class="panel">
          <div class="panel-header">
            <h2>Recent Bundles</h2>
            <span id="history-meta" class="subtitle">Latest publishes first</span>
          </div>
          <div class="panel-body">
            <div id="history" class="history"></div>
          </div>
        </article>
      </div>
    </section>
  </main>
  <script>
    const POLL_MS = {poll_ms};
    const CURRENT_LINK = {json.dumps(session.get("current_link", "current"))};

    function escapeHtml(value) {{
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    async function fetchJson(path) {{
      const sep = path.includes("?") ? "&" : "?";
      const response = await fetch(`${{path}}${{sep}}ts=${{Date.now()}}`, {{ cache: "no-store" }});
      if (!response.ok) {{
        throw new Error(`Failed to load ${{path}} (${{response.status}})`);
      }}
      return response.json();
    }}

    function setStatus(text, isError = false) {{
      const chip = document.getElementById("status-chip");
      chip.textContent = text;
      chip.dataset.state = isError ? "error" : "ok";
    }}

    function renderFacts(session, manifest, summary) {{
      const facts = Object.assign(
        {{
          software: manifest.software || session.software || "unknown",
          recipe: manifest.recipe || session.recipe || "unknown",
          bundle: manifest.bundle_id || session.current_bundle_id || "n/a",
          updated: session.updated_at || "unknown",
        }},
        summary.facts || {{}}
      );
      const row = document.getElementById("fact-row");
      row.innerHTML = Object.entries(facts)
        .slice(0, 8)
        .map(([key, value]) => `
          <div class="fact-card">
            <span>${{escapeHtml(key)}}</span>
            <strong>${{escapeHtml(value)}}</strong>
          </div>
        `)
        .join("");
    }}

    function renderCommands(session) {{
      const commands = [
        session.publish_command,
        session.watch_command,
        session.inspect_command,
      ].filter(Boolean);
      const strip = document.getElementById("command-strip");
      strip.innerHTML = commands.map((command) => `<div class="command-chip">${{escapeHtml(command)}}</div>`).join("");
    }}

    function artifactUrl(session, artifact) {{
      const rev = encodeURIComponent(session.updated_at || Date.now());
      return `${{CURRENT_LINK}}/${{artifact.path}}?rev=${{rev}}`;
    }}

    function pickArtifact(manifest, role, mediaPrefix) {{
      return (manifest.artifacts || []).find((artifact) => artifact.role === role)
        || (manifest.artifacts || []).find((artifact) => (artifact.media_type || "").startsWith(mediaPrefix));
    }}

    function renderHero(session, manifest) {{
      const hero = pickArtifact(manifest, "hero", "image/");
      const slot = document.getElementById("hero-slot");
      const meta = document.getElementById("hero-meta");
      if (!hero) {{
        slot.innerHTML = '<div class="empty">No hero frame was published in the current bundle.</div>';
        meta.textContent = "No hero frame";
        return;
      }}
      slot.innerHTML = `<img class="hero-frame" src="${{artifactUrl(session, hero)}}" alt="${{escapeHtml(hero.label || hero.artifact_id || "Hero frame")}}">`;
      const bits = [];
      if (hero.width && hero.height) bits.push(`${{hero.width}}×${{hero.height}}`);
      if (hero.time_s != null) bits.push(`t=${{hero.time_s}}s`);
      meta.textContent = bits.join(" · ") || (hero.label || "Hero frame");
    }}

    function renderClip(session, manifest) {{
      const clip = pickArtifact(manifest, "preview-clip", "video/");
      const slot = document.getElementById("clip-slot");
      const meta = document.getElementById("clip-meta");
      if (!clip) {{
        slot.innerHTML = '<div class="empty">No preview clip was published in the current bundle.</div>';
        meta.textContent = "No clip";
        return;
      }}
      slot.innerHTML = `
        <video class="hero-frame" controls preload="metadata" src="${{artifactUrl(session, clip)}}">
          Your browser does not support embedded video.
        </video>
      `;
      const bits = [];
      if (clip.width && clip.height) bits.push(`${{clip.width}}×${{clip.height}}`);
      if (clip.duration_s != null) bits.push(`${{clip.duration_s}}s`);
      if (clip.render_method) bits.push(clip.render_method);
      meta.textContent = bits.join(" · ") || (clip.label || "Preview clip");
    }}

    function renderGallery(session, manifest) {{
      const items = (manifest.artifacts || [])
        .filter((artifact) => artifact.role === "gallery" && (artifact.media_type || "").startsWith("image/"));
      const root = document.getElementById("gallery");
      if (!items.length) {{
        root.innerHTML = '<div class="empty">No gallery frames were published in the current bundle.</div>';
        return;
      }}
      root.innerHTML = items.map((artifact) => `
        <article class="thumb">
          <img src="${{artifactUrl(session, artifact)}}" alt="${{escapeHtml(artifact.label || artifact.artifact_id || "Gallery frame")}}">
          <div class="label">${{escapeHtml(artifact.label || artifact.artifact_id || "Frame")}}</div>
          <div class="meta">${{artifact.time_s != null ? `t=${{artifact.time_s}}s` : ""}}</div>
        </article>
      `).join("");
    }}

    function renderNotes(session, manifest, summary) {{
      const warnings = summary.warnings || manifest.warnings || [];
      const actions = summary.next_actions || [];
      const notes = document.getElementById("notes");
      const lines = [
        `<div><strong>Current bundle</strong><br>${{escapeHtml(session.current_bundle_id || manifest.bundle_id || "n/a")}}</div>`,
        `<div><strong>Session path</strong><br>${{escapeHtml(session.project_path || session.project_name || "n/a")}}</div>`,
        `<div><strong>Last update</strong><br>${{escapeHtml(session.updated_at || "unknown")}}</div>`,
      ];
      if (warnings.length) {{
        lines.push(`<div><strong>Warnings</strong><ul>${{warnings.map((item) => `<li>${{escapeHtml(item)}}</li>`).join("")}}</ul></div>`);
      }}
      if (actions.length) {{
        lines.push(`<div><strong>Suggested checks</strong><ul>${{actions.map((item) => `<li>${{escapeHtml(item)}}</li>`).join("")}}</ul></div>`);
      }}
      notes.innerHTML = lines.join("");
    }}

    function renderHistory(session) {{
      const history = session.history || [];
      const root = document.getElementById("history");
      if (!history.length) {{
        root.innerHTML = '<div class="empty">No live preview publishes yet.</div>';
        return;
      }}
      root.innerHTML = history.map((item) => `
        <article class="history-item">
          <strong>${{escapeHtml(item.bundle_id || "unknown")}}</strong>
          <span>${{escapeHtml(item.created_at || "unknown")}}</span>
          <span>${{escapeHtml(item.bundle_dir || "")}}</span>
        </article>
      `).join("");
    }}

    async function refresh() {{
      try {{
        const session = await fetchJson("session.json");
        const manifest = await fetchJson(`${{CURRENT_LINK}}/manifest.json`);
        let summary = {{}};
        const summaryPath = manifest.summary_path ? `${{CURRENT_LINK}}/${{manifest.summary_path}}` : `${{CURRENT_LINK}}/summary.json`;
        try {{
          summary = await fetchJson(summaryPath);
        }} catch (error) {{
          summary = {{}};
        }}

        document.getElementById("subtitle").textContent =
          (summary.headline || "Latest bundle loaded") +
          ` · polling every ${{POLL_MS}} ms`;

        renderFacts(session, manifest, summary);
        renderCommands(session);
        renderHero(session, manifest);
        renderClip(session, manifest);
        renderGallery(session, manifest);
        renderNotes(session, manifest, summary);
        renderHistory(session);
        setStatus("Watching", false);
      }} catch (error) {{
        setStatus("Waiting", true);
        document.getElementById("notes").innerHTML = `<div><strong>Viewer state</strong><br>${{escapeHtml(error.message)}}</div>`;
      }}
    }}

    refresh();
    window.setInterval(refresh, POLL_MS);
  </script>
</body>
</html>
"""
    with open(output_file, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    return str(output_file)


class _NoCacheHandler(SimpleHTTPRequestHandler):
    """Serve preview assets without cache so live sessions refresh correctly."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_static_server(directory: str, host: str = "127.0.0.1", port: int = 0) -> Tuple[ThreadingHTTPServer, str]:
    root = Path(directory).expanduser().resolve()
    handler = functools.partial(_NoCacheHandler, directory=str(root))
    server = ThreadingHTTPServer((host, int(port)), handler)
    base_url = f"http://{host}:{server.server_port}"
    return server, base_url


def open_in_browser(target: str) -> Dict[str, Any]:
    candidates = [
        ("chromium", ["chromium", f"--app={target}"]),
        ("google-chrome", ["google-chrome", f"--app={target}"]),
        ("google-chrome-stable", ["google-chrome-stable", f"--app={target}"]),
        ("microsoft-edge", ["microsoft-edge", f"--app={target}"]),
        ("firefox", ["firefox", "--new-window", target]),
        ("xdg-open", ["xdg-open", target]),
    ]
    for label, command in candidates:
        binary = shutil.which(command[0])
        if not binary:
            continue
        full_command = [binary] + command[1:]
        process = subprocess.Popen(
            full_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "launched": True,
            "browser": label,
            "pid": process.pid,
            "command": full_command,
        }
    return {
        "launched": False,
        "browser": None,
        "command": [],
        "reason": "No supported browser launcher found on PATH",
    }
