from __future__ import annotations

import argparse
import importlib.util
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
REQUIRED_FILES = [
    ROOT_DIR / "dashboard" / "server.py",
    ROOT_DIR / "dashboard" / "frontend" / "index.html",
    ROOT_DIR / "data" / "online_shopping_10_cats.csv",
]
CORE_MODULES = ["fastapi", "uvicorn", "pandas"]


def emit(message: str) -> None:
    print(message, flush=True)


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_dependencies() -> list[str]:
    return [name for name in CORE_MODULES if not module_available(name)]


def check_required_files() -> list[Path]:
    return [path for path in REQUIRED_FILES if not path.exists()]


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) != 0


def find_available_port(host: str, preferred_port: int, tries: int = 20) -> int:
    for port in range(preferred_port, preferred_port + tries):
        if port_is_free(host, port):
            return port
    raise RuntimeError(f"未找到可用端口：{preferred_port}..{preferred_port + tries - 1}")


def wait_until_ready(url: str, timeout_sec: int = 30) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.6)
    return False


def start_server(host: str, port: int, reload: bool) -> subprocess.Popen:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "dashboard.server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        command.append("--reload")
    emit("[start] " + " ".join(command))
    return subprocess.Popen(command, cwd=ROOT_DIR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Week14 M4 系统联调一键启动脚本")
    parser.add_argument("--host", default="127.0.0.1", help="FastAPI 监听地址")
    parser.add_argument("--port", type=int, default=8014, help="首选端口，若占用则自动顺延")
    parser.add_argument("--no-browser", action="store_true", help="只启动服务，不自动打开浏览器")
    parser.add_argument("--reload", action="store_true", help="启用 Uvicorn reload，适合开发调试")
    args = parser.parse_args()

    missing_modules = check_dependencies()
    if missing_modules:
        emit("[error] 缺少依赖：" + ", ".join(missing_modules))
        emit("[hint] 请先运行：python -m pip install -r requirements.txt")
        return 2

    missing_files = check_required_files()
    if missing_files:
        emit("[warning] 以下核心文件缺失，服务会尝试使用后端 fallback 机制：")
        for path in missing_files:
            emit(f"  - {path.relative_to(ROOT_DIR)}")

    port = find_available_port(args.host, args.port)
    if port != args.port:
        emit(f"[warning] 端口 {args.port} 已被占用，自动切换到 {port}")

    health_url = f"http://{args.host}:{port}/api/health"
    page_url = f"http://{args.host}:{port}/"
    process = start_server(args.host, port, args.reload)

    try:
        emit(f"[wait] 正在等待服务就绪：{health_url}")
        if not wait_until_ready(health_url):
            emit("[error] 服务启动超时，请检查控制台日志。")
            return 3

        emit(f"[ok] 后端服务已就绪：{health_url}")
        emit(f"[ok] 前端页面地址：{page_url}")
        if not args.no_browser:
            webbrowser.open(page_url)
            emit("[ok] 已请求系统默认浏览器打开前端页面。")

        emit("[info] 按 Ctrl+C 可优雅关闭服务。")
        while process.poll() is None:
            time.sleep(0.8)
        return process.returncode or 0
    except KeyboardInterrupt:
        emit("\n[stop] 捕获 Ctrl+C，正在关闭 FastAPI 子进程...")
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            emit("[stop] 子进程未及时退出，执行 kill。")
            process.kill()
        emit("[stop] 已完成清理。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
