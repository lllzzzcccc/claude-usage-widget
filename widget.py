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


# ---------- 配置读写 ----------

def _save_config(cfg: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def _load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _prompt_api_id(existing: str = "") -> Optional[str]:
    """弹出输入框让用户输入 api_id，返回 None 表示用户取消。"""
    w = rumps.Window(
        message="请输入你的 API ID：",
        title="ClaudeUsage 配置",
        default_text=existing,
        ok="确定",
        cancel="取消",
        dimensions=(320, 24),
    )
    resp = w.run()
    if resp.clicked:
        return resp.text.strip()
    return None


# ---------- 应用 ----------

class ClaudeUsageApp(rumps.App):
    def __init__(self, refresh_seconds: int):
        super().__init__("✦ Claude …", quit_button=None)
        self.refresh_seconds = refresh_seconds
        self.api_id = ""
        self._first_fire = True
        self._build_loading_menu()
        self._timer = rumps.Timer(self._tick, 1.0)
        self._timer.start()

    def _ensure_api_id(self) -> bool:
        """确保 api_id 已配置，未配置则弹窗引导。返回是否就绪。"""
        if self.api_id:
            return True
        cfg = _load_config()
        if cfg.get("api_id"):
            self.api_id = cfg["api_id"]
            return True
        # 弹窗让用户输入
        new_id = _prompt_api_id()
        if not new_id:
            return False
        cfg["api_id"] = new_id
        cfg.setdefault("refresh_seconds", 300)
        _save_config(cfg)
        self.api_id = new_id
        return True

    def _tick(self, sender):
        if not self._ensure_api_id():
            self.title = "✦ 未配置"
            self._build_unconfigured_menu()
            if self._first_fire:
                self._first_fire = False
                self._timer.stop()
                self._timer = rumps.Timer(self._tick, self.refresh_seconds)
                self._timer.start()
            return
        self.update(sender)
        if self._first_fire:
            self._first_fire = False
            self._timer.stop()
            self._timer = rumps.Timer(self._tick, self.refresh_seconds)
            self._timer.start()

    # --- 菜单构建 ---

    def _build_loading_menu(self):
        self.menu.clear()
        self.menu = ["加载中…"]

    def _build_unconfigured_menu(self):
        self.menu.clear()
        self.menu = [
            "⚠️ 未配置 API ID",
            None,
            rumps.MenuItem("⚙️ 设置 API ID", callback=self._on_set_api_id),
            rumps.MenuItem("❌ 退出", callback=rumps.quit_application),
        ]

    def _build_error_menu(self):
        self.menu.clear()
        self.menu = [
            "⚠️ 获取失败",
            None,
            rumps.MenuItem("⚙️ 设置 API ID", callback=self._on_set_api_id),
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
        items.append(rumps.MenuItem("⚙️ 设置 API ID", callback=self._on_set_api_id))
        items.append(rumps.MenuItem("🔄 立即刷新", callback=self._tick))
        items.append(rumps.MenuItem("❌ 退出", callback=rumps.quit_application))

        self.menu = items

    # --- 回调 ---

    def _on_set_api_id(self, _sender):
        new_id = _prompt_api_id(self.api_id)
        if new_id is None or new_id == self.api_id:
            return
        cfg = _load_config()
        cfg["api_id"] = new_id
        _save_config(cfg)
        self.api_id = new_id
        self.update(None)

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

def hide_from_dock():
    """把进程设为菜单栏驻留模式（不在 Dock/Cmd+Tab 显示）。"""
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception:
        traceback.print_exc()


def main():
    hide_from_dock()
    cfg = _load_config()
    refresh = int(cfg.get("refresh_seconds", 300))
    app = ClaudeUsageApp(refresh_seconds=refresh)
    app.run()


if __name__ == "__main__":
    main()
