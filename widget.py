"""
Claude 用量菜单栏小组件

常驻 macOS 菜单栏，定时轮询 claude.ver0.cc 的 stats 接口，
显示今日费用、请求数，点开查看本月与分模型明细。

运行: python3 widget.py
"""

import json
import os
import sys
import traceback
from typing import Optional

import requests
import rumps


API_BASE = "https://claude.ver0.cc/apiStats/api"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".claude_usage")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


# ---------- 工具 ----------

def fmt_num(n: float) -> str:
    """1_600_000 -> 1.6M, 12_345 -> 12.3K"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def fmt_money(x: float) -> str:
    return f"${x:.2f}"


def short_model(name: str) -> str:
    """claude-opus-4-6 -> Opus, claude-sonnet-4-6 -> Sonnet, claude-haiku-4-5-20251001 -> Haiku"""
    n = name.lower()
    if "opus" in n:
        return "Opus"
    if "sonnet" in n:
        return "Sonnet"
    if "haiku" in n:
        return "Haiku"
    return name


# ---------- 数据获取 ----------

def _post(path: str, body: dict, timeout: int = 10) -> dict:
    resp = requests.post(f"{API_BASE}/{path}", json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"API 返回失败: {data}")
    return data["data"]


def fetch_usage(api_id: str) -> Optional[dict]:
    """拉取所有需要的数据，失败返回 None。"""
    try:
        overall = _post("user-stats", {"apiId": api_id})
        daily = _post("user-model-stats", {"apiId": api_id, "period": "daily"})
        monthly = _post("user-model-stats", {"apiId": api_id, "period": "monthly"})
    except Exception:
        traceback.print_exc()
        return None

    # 今日汇总
    daily_cost = float(overall.get("limits", {}).get("currentDailyCost") or 0)
    daily_requests = sum(m["requests"] for m in daily)
    daily_tokens = sum(m["allTokens"] for m in daily)

    # 本月汇总
    monthly_cost = sum(m["costs"]["total"] for m in monthly)
    monthly_requests = sum(m["requests"] for m in monthly)
    monthly_tokens = sum(m["allTokens"] for m in monthly)

    # 今日模型排行（请求 > 0，按费用倒序）
    daily_models = sorted(
        [m for m in daily if m["requests"] > 0],
        key=lambda m: m["costs"]["total"],
        reverse=True,
    )

    return {
        "daily_cost": daily_cost,
        "daily_requests": daily_requests,
        "daily_tokens": daily_tokens,
        "monthly_cost": monthly_cost,
        "monthly_requests": monthly_requests,
        "monthly_tokens": monthly_tokens,
        "total_cost": float(overall.get("limits", {}).get("currentTotalCost") or 0),
        "daily_models": daily_models,
        "name": overall.get("name", ""),
    }


# ---------- 应用 ----------

class ClaudeUsageApp(rumps.App):
    def __init__(self, api_id: str, refresh_seconds: int):
        super().__init__("✦ Claude …", quit_button=None)
        self.api_id = api_id
        self.refresh_seconds = refresh_seconds
        self._first_fire = True
        self._build_loading_menu()
        # 不能在 __init__ 里直接调用 update()——此时 run loop 还没起，
        # 对 NSStatusItem 的 title/menu 设置无效，结果就是菜单栏空白。
        # 让 timer 在 run loop 启动后才触发首次刷新。
        self._timer = rumps.Timer(self._tick, 1.0)
        self._timer.start()

    def _tick(self, sender):
        self.update(sender)
        if self._first_fire:
            self._first_fire = False
            # 切换到真正的刷新间隔
            self._timer.stop()
            self._timer = rumps.Timer(self._tick, self.refresh_seconds)
            self._timer.start()

    # --- 菜单构建 ---

    def _build_loading_menu(self):
        self.menu.clear()
        self.menu = ["加载中…"]

    def _build_error_menu(self):
        self.menu.clear()
        self.menu = [
            "⚠️ 获取失败",
            None,
            rumps.MenuItem("🔄 立即刷新", callback=self._tick),
            rumps.MenuItem("❌ 退出", callback=rumps.quit_application),
        ]

    def _build_data_menu(self, d: dict):
        self.menu.clear()

        items = []
        items.append(rumps.MenuItem(f"━━ 今日 ━━"))
        items.append(rumps.MenuItem(f"  💰 {fmt_money(d['daily_cost'])}"))
        items.append(rumps.MenuItem(f"  📨 {d['daily_requests']} 次请求"))
        items.append(rumps.MenuItem(f"  🎯 {fmt_num(d['daily_tokens'])} tokens"))
        items.append(None)

        items.append(rumps.MenuItem(f"━━ 本月 ━━"))
        items.append(rumps.MenuItem(f"  💰 {fmt_money(d['monthly_cost'])}"))
        items.append(rumps.MenuItem(f"  📨 {d['monthly_requests']} 次请求"))
        items.append(rumps.MenuItem(f"  🎯 {fmt_num(d['monthly_tokens'])} tokens"))
        items.append(None)

        if d["daily_models"]:
            items.append(rumps.MenuItem("━━ 模型（今日）━━"))
            for m in d["daily_models"]:
                name = short_model(m["model"])
                cost = fmt_money(m["costs"]["total"])
                reqs = m["requests"]
                items.append(rumps.MenuItem(f"  {name}  {cost}  ({reqs}次)"))
            items.append(None)

        items.append(rumps.MenuItem(f"累计总费用: {fmt_money(d['total_cost'])}"))
        items.append(None)
        items.append(rumps.MenuItem("🔄 立即刷新", callback=self._tick))
        items.append(rumps.MenuItem("❌ 退出", callback=rumps.quit_application))

        self.menu = items

    # --- 刷新逻辑 ---

    def update(self, _sender):
        data = fetch_usage(self.api_id)
        if data is None:
            self.title = "⚠️ Claude"
            self._build_error_menu()
            return

        self.title = f"✦ {fmt_money(data['daily_cost'])}"
        self._build_data_menu(data)


# ---------- 入口 ----------

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        template = {"api_id": "", "refresh_seconds": 300}
        with open(CONFIG_PATH, "w") as f:
            json.dump(template, f, indent=2)
        rumps.alert(
            title="ClaudeUsage 首次配置",
            message=f"已创建配置文件:\n{CONFIG_PATH}\n\n请用文本编辑器打开，填入你的 api_id 后重新启动。",
        )
        sys.exit(0)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def hide_from_dock():
    """把进程设为菜单栏驻留模式（不在 Dock/Cmd+Tab 显示）。

    必须在 rumps.App 初始化之前调用。当本脚本被一个没有 LSUIElement=true
    的 .app 壳（例如系统 Python.app）启动时，默认会显示 Dock 图标；
    通过显式设置 ActivationPolicy 可以强制隐藏。
    """
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception:
        traceback.print_exc()


def main():
    hide_from_dock()
    cfg = load_config()
    api_id = cfg.get("api_id")
    if not api_id:
        sys.exit("config.json 缺少 api_id")
    refresh = int(cfg.get("refresh_seconds", 300))

    app = ClaudeUsageApp(api_id=api_id, refresh_seconds=refresh)
    app.run()


if __name__ == "__main__":
    main()
