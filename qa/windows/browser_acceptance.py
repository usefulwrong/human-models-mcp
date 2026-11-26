"""Inspect operator-installed real anatomy and replay through local Playwright."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:8766"


async def mcp_queries(requests):
    source = StdioServerParameters(
        command=sys.executable, args=["-X", "utf8", str(ROOT / "scripts/native.py"), "anatomy-mcp"],
        cwd=str(ROOT), env=dict(os.environ),
    )
    async with Client(source, read_timeout_seconds=120) as client:
        assert "anatomy_lab" in {tool.name for tool in (await client.list_tools()).tools}
        output = []
        for request in requests:
            reply = await client.call_tool("anatomy_lab", {"request": request})
            assert not reply.is_error, reply
            output.append(reply.structured_content)
        return output


def request(page, payload):
    reply = page.request.post(ORIGIN + "/api/query", data=payload)
    assert reply.ok, reply.status
    result = reply.json()
    assert result["status"] == "ok", result
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--motion", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    faults, evidence, comparisons = [], {}, []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=args.channel, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        for mobile in (False, True):
            label = "mobile" if mobile else "desktop"
            context = browser.new_context(
                viewport={"width": 393, "height": 852} if mobile else {"width": 1440, "height": 900},
                is_mobile=mobile, has_touch=mobile)
            page = context.new_page()
            page.set_default_timeout(90_000)
            page.on("pageerror", lambda exc: faults.append(str(exc)))
            page.goto(ORIGIN + "/", wait_until="domcontentloaded")
            page.wait_for_function("() => window.hmmViewer?.stats().revision > 0")
            page.locator("#query").fill("heart")
            page.locator('#matches [data-fma="FMA7088"]').click()
            page.wait_for_function("() => window.hmmViewer?.getScene().selection[0] === 'FMA7088'")
            page.locator("#isolate").click()
            page.wait_for_function("() => window.hmmViewer?.getScene().selection[0] === 'FMA7088'")
            search = {"operation": "anatomy.search", "query": "FMA7088"}
            result = request(page, search)
            assert "FMA7088" in json.dumps(result)
            with page.expect_download() as request_download:
                page.locator("#export").click()
            path = args.output / f"{label}-scene.json"
            request_download.value.save_as(path)
            page.locator("#import").set_input_files(path)
            page.wait_for_function("() => window.hmmViewer?.getScene().selection[0] === 'FMA7088'")
            page.screenshot(path=args.output / f"{label}-heart.png")
            audit = {"search": result}
            if args.motion:
                page.goto(ORIGIN + "/?motion=whole", wait_until="domcontentloaded")
                page.wait_for_function("() => window.hmmViewer?.whole.status()?.nodeCount > 400")
                page.evaluate("() => window.hmmViewer.whole.seek(55)")
                frame = page.evaluate("() => window.hmmViewer.whole.status().frame")
                assert frame["state_index"] == 55
                run = request(page, {"operation": "whole.discover"})["runs"][0]["run_id"]
                params = {"operation": "whole.contact", "run_id": run, "part": "hand_r", "sample": 55}
                contact = request(page, params)
                assert contact["state_sha256"] == frame["state_sha256"]
                overlay = page.locator('#whole-layers input[value="OVERLAYS"]')
                overlay.check()
                page.screenshot(path=args.output / f"{label}-contact.png")
                muscles = {"operation": "muscle.search", "run_id": run, "query": "pectoralis major",
                           "inventory": "display", "side": "right"}
                result = request(page, muscles)
                assert "pectoralis_major:right" in json.dumps(result)
                page.locator("#muscle-browser summary").click()
                page.locator("#muscle-inventory").select_option("display")
                page.locator("#muscle-side").select_option("right")
                page.locator("#muscle-query").fill("pectoralis major")
                page.locator('#muscle-search button[type="submit"]').click()
                asset = next(row for row in result["assets"] if row.get("group_id") == "pectoralis_major:right")
                node = asset["display_copy"]
                page.locator(f'#muscle-results [data-node="{node}"]').click()
                page.locator("#muscle-inspector").wait_for()
                page.locator("#muscle-metric").select_option("force_N")
                page.wait_for_function("() => document.querySelector('#muscle-value').textContent.includes('#55')")
                signed = {"operation": "muscle.timeseries", "run_id": run, "group_id": "pectoralis_major:right",
                          "metric": "force_N", "unit": "N", "start_s": frame["frame_time"],
                          "end_s": frame["frame_time"]}
                force = request(page, signed)
                assert force["aggregate"] and force["scientific_quantity"]["quantities"]["aggregate"]["origin"]
                displayed = page.evaluate("v => v.toPrecision(6)", force["aggregate"][0])
                page.wait_for_function("v => document.querySelector('#muscle-value').textContent.includes(v)", arg=displayed)
                page.screenshot(path=args.output / f"{label}-pectoralis.png")
                comparisons.extend(zip([params, muscles, signed], [contact, result, force], strict=True))
                audit |= {"frame": frame, "contact": contact, "muscle": result, "signed_force": force}
            else:
                comparisons.append((search, result))
            evidence[label] = audit
            context.close()
        browser.close()
    assert not faults, faults
    requests, expected = zip(*comparisons, strict=True)
    assert asyncio.run(mcp_queries(requests)) == list(expected)
    (args.output / "browser.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8", newline="\n")
    print("WINDOWS_BROWSER_ACCEPTANCE_PASS")


if __name__ == "__main__":
    main()
