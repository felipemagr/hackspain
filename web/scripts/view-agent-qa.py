"""Check view changes in the running local demo without calling a paid model."""

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

OUT = Path(os.environ.get("VIEW_AGENT_QA_DIR", "data/processed/v3-qa"))
OUT.mkdir(parents=True, exist_ok=True)
URL = os.environ.get("VIEW_AGENT_URL", "http://127.0.0.1:8765/xray-v3.html?group=GROUP_0080")
API = (
    os.environ.get("VIEW_AGENT_API_URL", "http://127.0.0.1:8000")
    + "/api/v1/scoring/entities/GROUP_0080"
)
HEADERS = {"X-API-Key": os.environ["VITE_API_KEY"]} if os.environ.get("VITE_API_KEY") else {}
BAR_SELECTOR = '.chart g[clip-path="url(#bar-plot)"] rect'

with urlopen(Request(API, headers=HEADERS)) as response:
    detail = json.load(response)
expected = detail["monthly"][-1]["scoring"]["families"]["financial"]["score"]
chart = {
    "type": "bar",
    "series": ["financial", "liquidity", "receivables", "payables"],
    "months": 6,
    "show_grid": False,
    "color": "blue",
    "title": "Four pillars",
}
plans = [
    {
        "reply": (
            "**Applied financial capacity at 100%** using existing pillar scores.\n\n"
            "- Existing scores preserved.\n- Weight: `100%`."
        ),
        "actions": [
            {
                "type": "set_weights",
                "weights": {"financial": 1, "liquidity": 0, "receivables": 0, "payables": 0},
            }
        ],
    },
    {
        "reply": "Showing four pillars as bars for the latest six months.",
        "actions": [{"type": "set_chart", "chart": chart}],
    },
    {"reply": "A 3D chart is not supported. I can show lines, areas or bars.", "actions": []},
]
checks = {}
requests = []
errors = []
bodies = []

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        headless=True,
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))

    def answer(route):
        bodies.append(route.request.post_data_json)
        route.fulfill(json={**plans.pop(0), "queries": [], "model_available": True})

    page.route("**/api/v1/view-chats", answer)
    page.goto(URL)
    page.get_by_text("Cash snapshot:", exact=False).first.wait_for()
    page.wait_for_timeout(600)
    initial = page.locator(".score__level").inner_text()
    checks["upstream_search"] = page.get_by_label("Search groups").count() == 1
    page.get_by_role("button", name="Zoom in", exact=True).click()
    checks["upstream_zoom"] = page.get_by_role("button", name="Reset", exact=True).count() == 1
    page.get_by_role("button", name="Reset", exact=True).click()
    page.get_by_label("Lay a market's health behind the score").click()
    page.locator(".pick").first.click()
    checks["upstream_market"] = page.locator(".chart__line--macro").count() == 1
    page.get_by_role("heading", name="Health score, August 2026").click()
    page.get_by_role("button", name="Ask Lighthouse", exact=True).click()
    checks["button_bottom_right"] = page.locator(".view-ai-button").bounding_box()["x"] > 1300
    checks["titled_chat_header"] = (
        page.get_by_role("heading", name="Ask Lighthouse").is_visible()
        and "GROUP_0080" not in page.get_by_role("dialog").inner_text()
        and page.get_by_role("button", name="Close AI").is_visible()
    )
    checks["empty_chat_compact"] = page.get_by_role("dialog").bounding_box()["height"] < 340

    def ask(text):
        page.get_by_label("Ask AI about this view").fill(text)
        page.get_by_role("button", name="Send", exact=True).click()
        page.wait_for_timeout(850)

    ask("Set financial capacity to 100 percent")
    checks["markdown_rendered"] = (
        page.locator(".view-ai__message--assistant strong").count() == 1
        and page.locator(".view-ai__message--assistant li code").inner_text() == "100%"
    )
    checks["weights_update_score"] = (
        abs(float(page.locator(".score__level").inner_text()) - expected) < 0.51
    )
    checks["weights_table"] = (
        page.locator(".pillars")
        .first.locator("tbody tr")
        .first.locator("td")
        .first.inner_text()
        .startswith("100.0%")
    )
    checks["no_engine_evaluate"] = not any("/evaluate" in url for url in requests)
    checks["date_and_profile"] = bodies[0]["month"] == "2026-08" and "current_profile" in bodies[0]
    ask("Show four pillars as bars, last six months, blue, without grid")
    checks["chart_bars"] = page.locator(BAR_SELECTOR).count() > 6
    checks["chart_six_months"] = "over 6 months" in page.locator(".chart > svg").get_attribute(
        "aria-label"
    )
    checks["chart_grid_hidden"] = (
        page.locator(".chart__grid").count() == 0 and page.locator(".chart__threshold").count() == 0
    )
    checks["chart_legend"] = page.locator(".view-chart-legend .legend__item").count() == 3
    checks["single_observation_omitted"] = (
        "Liquidity" not in page.locator(".view-chart-legend").inner_text()
        and "Liquidity omitted: only 1 observation" in page.locator(".view-chart-note").inner_text()
    )
    checks["accurate_chart_title"] = (
        page.get_by_role("heading", name="Pillar scores, August 2026").count() == 1
    )
    checks["bars_inside_plot"] = page.locator(".chart > svg").evaluate("""svg => {
        const right = Number(svg.getAttribute('width')) - 44;
        return Array.from(svg.querySelectorAll('g[clip-path="url(#bar-plot)"] rect')).every(bar => {
            const x = Number(bar.getAttribute('x'));
            const width = Number(bar.getAttribute('width'));
            return x >= 96 && x + width <= right;
        });
    }""")
    checks["bar_endpoint_labels_removed"] = (
        page.locator(".chart__end").count() == 0 and page.locator(".chart__dot").count() == 0
    )
    plot = page.locator(".chart > svg").bounding_box()
    plot_width = plot["width"] - 140
    page.mouse.move(plot["x"] + 96 + plot_width / 12, plot["y"] + 150)
    checks["first_band_tooltip"] = page.locator(".tooltip__title").inner_text() == "March 2026"
    page.mouse.move(plot["x"] + 96 + plot_width * 11 / 12, plot["y"] + 150)
    checks["last_band_tooltip"] = page.locator(".tooltip__title").inner_text() == "August 2026"
    page.mouse.move(10, 10)
    checks["comparison_hidden"] = (
        page.get_by_label("Lay a market's health behind the score").count() == 0
    )
    ask("Make it 3D")
    checks["unsupported_explained"] = (
        "3D chart is not supported" in page.locator(".view-ai__messages").inner_text()
    )
    checks["intro_hidden_during_chat"] = page.locator(".view-ai__intro").count() == 0
    page.screenshot(path=str(OUT / "view-agent-refined-desktop.png"))
    page.get_by_role("button", name="Close AI").click()
    page.get_by_role("dialog").wait_for(state="hidden")
    page.screenshot(path=str(OUT / "view-agent-refined-chart.png"))
    page.get_by_role("button", name="Ask Lighthouse", exact=True).click()
    page.get_by_role("button", name="Reset AI changes").click()
    page.wait_for_timeout(550)
    checks["reset_restores"] = (
        page.locator(".score__level").inner_text() == initial
        and page.locator(BAR_SELECTOR).count() == 0
    )
    page.keyboard.press("Escape")
    page.get_by_role("dialog", name="Ask Lighthouse").wait_for(state="hidden")
    checks["escape_closes"] = page.get_by_role("dialog", name="Ask Lighthouse").count() == 0
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    page.get_by_role("button", name="Ask Lighthouse", exact=True).click()
    box = page.get_by_role("dialog", name="Ask Lighthouse").bounding_box()
    checks["mobile_panel_fits"] = box["x"] >= 0 and box["x"] + box["width"] <= 390 and box["y"] >= 0
    page.screenshot(path=str(OUT / "view-agent-refined-mobile.png"))
    browser.close()

checks["no_console_errors"] = not errors
print(json.dumps({"checks": checks, "errors": errors}, indent=2))
assert all(checks.values())
