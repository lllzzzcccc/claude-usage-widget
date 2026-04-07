"""最小化菜单栏测试 + 强诊断日志。"""
import sys
import os
import traceback

LOG = "/tmp/minimal_test_trace.log"

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{os.getpid()}] {msg}\n")
        f.flush()

# 清空上次日志
open(LOG, "w").close()

log(f"脚本启动, python={sys.executable}")
log(f"sys.argv={sys.argv}")
log(f"cwd={os.getcwd()}")
log(f"HOME={os.environ.get('HOME')}")
log(f"PATH={os.environ.get('PATH', '')[:200]}")

try:
    log("import rumps 开始")
    import rumps
    log(f"import rumps 成功, 版本: {getattr(rumps, '__version__', 'unknown')}")
except Exception:
    log(f"import rumps 失败: {traceback.format_exc()}")
    sys.exit(1)

try:
    log("创建 App 实例")
    class Hello(rumps.App):
        def __init__(self):
            super().__init__("🔴 TEST-MENU-BAR", quit_button="退出")
            log("Hello.__init__ 完成")
            rumps.Timer(self.heartbeat, 2).start()

        def heartbeat(self, sender):
            log("heartbeat (run loop 活跃)")

    app = Hello()
    log("准备调用 app.run()")
    app.run()
    log("app.run() 返回（退出）")
except Exception:
    log(f"主流程异常: {traceback.format_exc()}")
