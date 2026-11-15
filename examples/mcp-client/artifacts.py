"""Download verified result bytes into a named, standalone user directory."""

import base64
import hashlib
from html import escape
import json
from pathlib import Path
from urllib.parse import quote


async def export_run(call, run: dict, destination: Path):
    if run["status"] != "computed":
        raise ValueError("only completed runs can be exported as a scientific result")
    artifacts = run["artifacts"]
    if len(artifacts) > 128 or sum(item["bytes"] for item in artifacts.values()) > 64 * 1024 * 1024:
        raise ValueError("result exceeds client export bounds")
    for name in artifacts:
        if name in ("manifest.json", "index.html", "client.json") or Path(name).name != name or name in (".", ".."):
            raise ValueError("invalid artifact filename")
    destination.mkdir(parents=True, exist_ok=False)
    for name, expected in artifacts.items():
        artifact = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": name})
        if artifact.get("status") != "ok":
            raise ValueError("artifact transfer failed: " + name)
        data = base64.b64decode(artifact["data"], validate=True) if artifact["encoding"] == "base64" else artifact["data"].encode()
        if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError("artifact size/checksum mismatch: " + name)
        with (destination / name).open("xb") as stream:
            stream.write(data)
    (destination / "manifest.json").write_text(json.dumps(run, indent=2) + "\n")
    metrics = "".join(f"<tr><td>{escape(item['name'])}</td><td>{item['value']:.8g}</td><td>{escape(item['unit'])}</td></tr>" for item in run["outputs"]["metrics"])
    figures = "".join(f'<figure><img src="{quote(name)}" alt="{escape(name)}"><figcaption>{escape(name)}</figcaption></figure>'
                      for name in ("overview.png", "animation.gif", "plots.png", "pose.png") if name in artifacts)
    links = "".join(f'<li><a href="{quote(name)}">{escape(name)}</a> — SHA-256 {item["sha256"]}</li>' for name, item in artifacts.items())
    limitations = "".join("<li>" + escape(item) + "</li>" for item in run["scientific"]["limitations"])
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UsefulWrong / {escape(run['scenario_id'])}</title><style>
body{{font:16px system-ui;max-width:1120px;margin:40px auto;padding:0 20px;background:#101923;color:#dfe7ef}}
a{{color:#56c9d8}}img{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #354454}}
li{{overflow-wrap:anywhere;margin:8px 0}}figure{{margin:28px 0}}figcaption{{color:#b6c6d4}}
</style><h1>UsefulWrong / {escape(run['scenario_id'])}</h1>
<p>{escape(run['scientific']['scope'])}</p><p>Execution: <strong>{escape(run['status'])}</strong> · method: {escape(run['execution']['method'])} · evidence: <strong>{escape(run['scientific']['validation_level'])}</strong></p>
<p>Model: {escape(run['model']['id'])} · revision {escape(run['model']['revision'])}<br>
Engine: {escape(run['engine']['name'])} {escape(run['engine']['version'])} · physics: {escape(run['execution']['physics_backend'])} · graphics: {escape(run['execution']['render_backend'])}</p>
<table><tr><th>Metric</th><th>Value</th><th>Unit</th></tr>{metrics}</table>{figures}
<h2>Interpretation limits</h2><ul>{limitations}</ul><h2>Files and provenance</h2>
<p>Run {escape(run['run_id'])} · <a href="manifest.json">manifest.json</a>. Artifact bytes were transferred through MCP and verified against this manifest.</p><ul>{links}</ul></html>'''
    (destination / "index.html").write_text(page)
    return destination.resolve() / "index.html"
