"""
Claude 用量菜单栏小组件

常驻 macOS 菜单栏，定时轮询 claude.ver0.cc 的 stats 接口，
显示今日费用、请求数，点开查看本月与分模型明细。

运行: python3 widget.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import webbrowser
from typing import Optional

import requests
import rumps


APP_VERSION = "1.4.0"
GITHUB_REPO = "lllzzzcccc/claude-usage-widget"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

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


STATS_URL = "https://claude.ver0.cc/admin-next/api-stats"


def _prompt_api_id(existing: str = "") -> Optional[str]:
    """弹出输入框让用户输入 api_id，返回 None 表示用户取消。"""
    if not existing:
        clicked = rumps.alert(
            title="获取 API ID",
            message=(
                "需要先获取你的 API ID：\n\n"
                "1. 点击「打开获取页面」跳转到浏览器\n"
                "2. 输入你的 API Key 并刷新页面\n"
                "3. 地址栏会出现 appId=xxx，复制该值"
            ),
            ok="打开获取页面",
            cancel="我已有 API ID",
        )
        if clicked:
            webbrowser.open(STATS_URL)

    w = rumps.Window(
        message="粘贴你的 API ID：",
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
        self._cancel_count = 0
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
            self._cancel_count += 1
            if self._cancel_count >= 2:
                rumps.quit_application()
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


# ---------- 版本检查与自动更新 ----------

def _get_app_path() -> Optional[str]:
    """获取当前 .app bundle 的路径，非 .app 环境返回 None。"""
    # PyInstaller 打包后 sys.executable 位于 .app/Contents/MacOS/ 下
    exe = os.path.realpath(sys.executable)
    parts = exe.split(os.sep)
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return os.sep + os.path.join(*parts[1:i + 1])
    return None


def _download_and_update(download_url: str, app_path: str):
    """下载新版 zip，解压替换当前 app，然后重启。"""
    tmp_dir = tempfile.mkdtemp(prefix="claude_usage_update_")
    zip_path = os.path.join(tmp_dir, "ClaudeUsage.zip")

    # 下载
    with requests.get(download_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    # 解压（用 ditto 保留 macOS 权限和元数据）
    extract_dir = os.path.join(tmp_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    subprocess.run(
        ["ditto", "-xk", zip_path, extract_dir],
        check=True, timeout=60,
    )

    # 找到解压后的 .app
    new_app = None
    for name in os.listdir(extract_dir):
        if name.endswith(".app"):
            new_app = os.path.join(extract_dir, name)
            break
    if not new_app:
        raise FileNotFoundError("zip 中未找到 .app")

    # 用 shell 脚本完成替换和重启（当前进程退出后执行）
    script = f"""#!/bin/bash
sleep 2
rm -rf "{app_path}"
mv "{new_app}" "{app_path}"
chmod -R +x "{app_path}/Contents/MacOS/"
xattr -cr "{app_path}"
open "{app_path}"
rm -rf "{tmp_dir}"
"""
    script_path = os.path.join(tmp_dir, "update.sh")
    with open(script_path, "w") as f:
        f.write(script)
    os.chmod(script_path, 0o755)

    subprocess.Popen(["/bin/bash", script_path], start_new_session=True)
    sys.exit(0)


def _check_update():
    """检查是否有新版本，有则自动下载更新并重启。"""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=10,
        )
        resp.raise_for_status()
        release = resp.json()
        latest = release.get("tag_name", "")
        latest_ver = latest.lstrip("v")
        if not latest_ver or latest_ver == APP_VERSION:
            return
        from packaging.version import Version
        if Version(latest_ver) <= Version(APP_VERSION):
            return
    except Exception:
        traceback.print_exc()
        return

    # 找到 zip 下载链接
    download_url = None
    for asset in release.get("assets", []):
        if asset["name"].endswith(".zip"):
            download_url = asset["browser_download_url"]
            break
    if not download_url:
        return

    app_path = _get_app_path()

    clicked = rumps.alert(
        title="发现新版本",
        message=f"当前版本：v{APP_VERSION}\n最新版本：{latest}\n\n点击「立即更新」将自动下载并重启。",
        ok="立即更新",
        cancel="稍后提醒",
    )
    if not clicked:
        return

    if app_path:
        try:
            _download_and_update(download_url, app_path)
        except Exception:
            traceback.print_exc()
            rumps.alert("更新失败", "自动更新出错，请手动前往 GitHub 下载。")
            webbrowser.open(RELEASES_URL)
            sys.exit(0)
    else:
        # 非 .app 环境（开发模式），打开浏览器
        webbrowser.open(RELEASES_URL)
        sys.exit(0)


# ---------- 入口 ----------

def _check_quarantine():
    """检测 app 是否被 macOS 隔离，若是则尝试自动移除并提示重启。"""
    app_path = _get_app_path()
    if not app_path:
        return
    try:
        result = subprocess.run(
            ["xattr", "-l", app_path],
            capture_output=True, text=True, timeout=5,
        )
        if "com.apple.quarantine" not in result.stdout:
            return
    except Exception:
        return

    # 尝试自动移除隔离属性
    removed = False
    try:
        subprocess.run(
            ["xattr", "-cr", app_path],
            capture_output=True, timeout=5,
        )
        removed = True
    except Exception:
        pass

    if removed:
        rumps.alert(
            title="首次启动配置",
            message="已自动完成安全设置，请重新打开应用。",
        )
    else:
        rumps.alert(
            title="需要解除安全限制",
            message=(
                "macOS 阻止了未签名应用运行，请在终端执行：\n\n"
                f"xattr -cr \"{app_path}\"\n\n"
                "然后重新打开应用。"
            ),
        )
    sys.exit(0)


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
    _check_quarantine()
    _check_update()
    cfg = _load_config()
    refresh = int(cfg.get("refresh_seconds", 300))
    app = ClaudeUsageApp(refresh_seconds=refresh)
    app.run()


if __name__ == "__main__":
    main()
