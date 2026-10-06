"""Exercise the real UI using Playwright and a freshly started local server."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from opensourceguard.cli import Handler, LocalHTTPServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", help="Browser executable, e.g. Microsoft Edge")
    parser.add_argument("--libraries", help="Optional directory containing the Playwright package")
    args = parser.parse_args()
    if args.libraries:
        sys.path.insert(0, args.libraries)
    from playwright.sync_api import sync_playwright, expect

    class QuietHandler(Handler):
        repo = ROOT / "examples" / "buggy_csv"
        def log_message(self, *args): pass

    output = ROOT / "artifacts" / "acceptance"
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with LocalHTTPServer(("127.0.0.1", 0), QuietHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=args.browser)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
                page = context.new_page()
                page.set_default_timeout(10000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                page.goto(base)
                expect(page.locator("#auth-screen")).to_be_visible()
                page.locator("#demo-login").click()
                expect(page.locator("#connection-text")).to_have_text("本地服务已连接")
                expect(page.locator("#view-home")).to_be_visible()
                checks.append("local login, demo workspace, assets and service connection")

                page.locator('[data-nav="projects"]').click()
                expect(page.locator("#project-list .project-card")).to_have_count(1)
                expect(page.locator("#issue-list .issue-card")).to_have_count(1)
                page.locator("#issue-list [data-assist-issue]").click()
                expect(page.locator("#project-agent-result")).to_be_visible()
                expect(page.locator("#project-agent-result")).to_contain_text("Agent 已完成第一轮分析")
                checks.append("project center loads demo project/issues and generates an Agent plan")

                page.locator("#profile-button").click()
                expect(page.locator("#profile-menu")).to_be_visible()
                page.locator("#logout-button").click()
                expect(page.locator("#auth-screen")).to_be_visible()
                page.locator("#login-name").fill("验收工作区")
                page.locator("#login-passcode").fill("1234")
                page.locator("#login-form").press("Enter")
                expect(page.locator("#auth-screen")).to_be_hidden()
                page.reload()
                expect(page.locator("#auth-screen")).to_be_hidden()
                checks.append("logout, password validation path, and remembered local session")

                page.locator('[data-nav="repair"]').click()
                page.locator("#model-test").click()
                expect(page.locator("#status")).to_contain_text("尚未配置模型地址和模型名")
                checks.append("model connection test keeps offline mode when no credentials are configured")

                page.locator("#run").click()
                expect(page.locator("#report-state")).to_have_text("未执行代码")
                assert "环境错误" not in page.locator("#result").inner_text()
                checks.append("static analysis is marked not executed")
                page.locator("#repair-form details summary").click()
                page.locator("#execute").select_option("local")
                with page.expect_response(lambda r: r.url.endswith("/analyze") and r.request.method == "POST") as response:
                    page.locator("#run").click()
                report = response.value.json()
                expect(page.locator("#report-state")).to_have_text("已验证")
                assert report["verification_status"] == "verified"
                assert [t["passed"] for t in report["tests"]] == [False, True, True]
                expect(page.locator("#result")).to_contain_text("补丁后全量测试")
                # Verify real clipboard text and downloaded content, not just button clicks.
                page.locator("#result [data-copy]").first.click()
                expect(page.locator("#toast")).to_have_text("已复制到剪贴板")
                copied = page.evaluate("navigator.clipboard.readText()")
                assert copied.replace("\r\n", "\n") == report["reproduction_test"].replace("\r\n", "\n"), repr(copied)
                for kind, extension in [("report-json", "json"), ("report-md", "md")]:
                    with page.expect_download() as download:
                        page.locator(f'[data-download="{kind}"]').click()
                    destination = output / f"browser-report.{extension}"
                    download.value.save_as(destination)
                    text = destination.read_text(encoding="utf-8")
                    assert "candidate_full" in text
                    if extension == "json": assert json.loads(text) == report
                page.screenshot(path=str(output / "repair-desktop.png"), full_page=True)
                checks.append("local reproduction, full suite, clipboard, JSON and Markdown export")

                page.locator('[data-nav="publish"]').click()
                page.locator("#onboard-name").fill("acceptance-agent")
                page.locator("#onboard-run").click()
                expect(page.locator("#onboard-result .onboarding-step")).to_have_count(5)
                expect(page.locator("#onboard-result")).to_contain_text("尚未上传代码")
                expect(page.locator("#onboard-result")).to_contain_text("先补充平台用户名")
                page.locator("#onboarding-form details summary").click()
                page.locator("#onboard-user").fill("builder")
                page.locator("#onboard-description").fill('<img src=x onerror="window.injected=true">')
                page.locator("#onboard-run").click()
                expect(page.locator("#onboard-result")).not_to_contain_text("YOUR_USERNAME")
                assert not page.evaluate("Boolean(window.injected)")
                with page.expect_download() as download:
                    page.locator('[data-download="onboarding-json"]').click()
                download.value.save_as(output / "onboarding.json")
                data = json.loads((output / "onboarding.json").read_text(encoding="utf-8"))
                assert "<img" not in data["website_card"]["html"]
                checks.append("publish guide, placeholder warning, escaped website card and export")

                page.locator('[data-nav="arena"]').click()
                page.locator("#arena-run").click()
                expect(page.locator("#arena-result .arena-row:not(.header)")).to_have_count(3)
                expect(page.locator("#arena-result .detail-card")).to_have_count(9)
                with page.expect_download() as download:
                    page.locator('[data-download="arena-json"]').click()
                download.value.save_as(output / "arena.json")
                assert len(json.loads((output / "arena.json").read_text(encoding="utf-8"))["details"]) == 3
                page.locator("#arena-form details summary").click()
                page.locator('label:has(input[value="http"])').click()
                expect(page.locator("#agent-endpoint")).to_be_visible()
                page.locator("#agent-endpoint").fill("not a url")
                page.locator('label:has(input[value="responses"])').click()
                expect(page.locator("#agent-endpoint")).to_be_disabled()
                page.locator("#use-advanced").check()
                page.locator("#arena-agents").fill("[invalid")
                page.locator("#arena-run").click()
                expect(page.locator("#arena-status")).to_have_text("高级配置不是有效 JSON")
                page.locator("#arena-agents").fill('[{"name":"empty","kind":"responses","responses":{}}]')
                page.locator("#arena-run").click()
                expect(page.locator("#arena-result .arena-row:not(.header)")).to_have_count(1)
                expect(page.locator("#arena-result .arena-row .score-big")).to_have_text("0.0")
                checks.append("arena baseline comparison, export, mode switching, invalid input, zero for empty responses")

                page.locator("#motion-toggle").click()
                page.locator('[data-nav="home"]').click()
                assert page.locator("#view-home").evaluate("el => getComputedStyle(el).opacity") == "1"
                page.reload()
                expect(page.locator("body")).to_have_class("motion-paused")
                checks.append("motion pause persists and never hides routed content")

                for width in [390, 820]:
                    page.set_viewport_size({"width": width, "height": 900})
                    for route in ["home", "projects", "repair", "publish", "arena"]:
                        page.goto(base + "/#" + route)
                        expect(page.locator("#view-" + route)).to_be_visible()
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"overflow: {route}/{width}"
                    page.screenshot(path=str(output / f"arena-{width}.png"), full_page=True)
                checks.append("all routes at 390px and 820px without horizontal overflow")
                assert errors == [], errors
                # Offline behavior is intentionally induced after the no-error check.
                page.route("**/analyze", lambda route: route.abort())
                page.goto(base + "/#repair")
                page.locator("#run").click()
                expect(page.locator("#status")).to_contain_text("无法连接本地服务")
                expect(page.locator("#run")).to_be_enabled()
                checks.append("network failure has a visible error and retry remains available")
                browser.close()
        finally:
            server.shutdown()
            thread.join()
    result = {"passed": True, "time": datetime.now(timezone.utc).isoformat(), "checks": checks}
    (output / "browser-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
