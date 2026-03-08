# -*- coding: utf-8 -*-
"""
数据库配置：统一从项目根目录 .env 读取 MYSQL_*，供 app 与所有脚本共用。
使用前确保已安装 python-dotenv；脚本单独运行时本模块会先加载 .env。
"""
import os

# 项目根目录（htma_dashboard 的上一级）
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ENV_PATH = os.path.join(_ROOT, ".env")

try:
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH)
    load_dotenv()
except ImportError:
    pass

import pymysql

# 与 .env 中 MYSQL_* 对应；未配置时使用下列默认值
DB_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", "62102218"),
    "database": os.environ.get("MYSQL_DATABASE", "htma_dashboard"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}


def get_conn():
    """返回 pymysql 连接（与 app 及所有脚本共用同一配置）。"""
    return pymysql.connect(**DB_CONFIG)
