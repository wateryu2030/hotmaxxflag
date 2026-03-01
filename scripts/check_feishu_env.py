#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动前检查：.env 中飞书登录配置是否可被正确加载（与 app 同逻辑）"""
import os
import sys

# 项目根 = 本脚本所在目录的上级
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_env_path = os.path.join(_project_root, ".env")
_keys = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "HTMA_PUBLIC_URL", "FLASK_SECRET_KEY")


def load_env(path):
    n = 0
    if not path or not os.path.isfile(path):
        return n
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip().strip("\r\n")
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip("'\"").strip()
                if key in _keys and val:
                    os.environ[key] = val
                    n += 1
    except Exception:
        pass
    return n


if __name__ == "__main__":
    # 与 app.py 相同的多路径
    for p in (_env_path, os.path.join(os.getcwd(), ".env"), os.path.abspath(os.path.join(os.getcwd(), "..", ".env"))):
        load_env(p)
    aid = (os.environ.get("FEISHU_APP_ID") or "").strip()
    secret = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if aid and secret:
        print("OK: FEISHU_APP_ID 与 FEISHU_APP_SECRET 已加载（飞书登录可用）", flush=True)
        sys.exit(0)
    print("WARN: 未读到飞书配置，.env 路径尝试: " + _env_path, flush=True)
    print("  请确认项目根目录 .env 中存在 FEISHU_APP_ID 与 FEISHU_APP_SECRET", flush=True)
    sys.exit(1)
