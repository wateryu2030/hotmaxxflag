# -*- coding: utf-8 -*-
"""
飞书机器人：话术（soul.md）+ 指令映射（command_map.json）+ 安全只读库查询。
不执行用户自定义 SQL，仅白名单模板 + 参数绑定。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config", "feishu_bot")
_SOUL_PATH = os.path.join(_CONFIG_DIR, "soul.md")
_COMMAND_MAP_PATH = os.path.join(_CONFIG_DIR, "command_map.json")
_CONFIG_YAML_PATH = os.path.join(_CONFIG_DIR, "config.yaml")

logger = logging.getLogger("feishu_bot")

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None

_BOT_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_SOUL_BLOCK_CACHE: Dict[str, str] = {}


def _ensure_file_logging() -> None:
    if getattr(_ensure_file_logging, "_done", False):
        return
    try:
        cfg = _load_yaml_config()
        log_cfg = (cfg.get("logging") or {}) if cfg else {}
        rel = (log_cfg.get("file") or "logs/feishu_bot.log").strip()
        log_path = rel if os.path.isabs(rel) else os.path.join(_PROJECT_ROOT, rel)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        from logging.handlers import RotatingFileHandler

        max_b = int(log_cfg.get("max_bytes") or 2 * 1024 * 1024)
        backup = int(log_cfg.get("backup_count") or 7)
        fh = RotatingFileHandler(log_path, maxBytes=max_b, backupCount=backup, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root = logging.getLogger("feishu_bot")
        root.setLevel(logging.INFO)
        if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            root.addHandler(fh)
    except Exception as e:
        logging.getLogger("feishu_bot").warning("feishu_bot 文件日志未启用: %s", e)
    setattr(_ensure_file_logging, "_done", True)


def _load_yaml_config() -> Dict[str, Any]:
    global _BOT_CONFIG_CACHE
    if _BOT_CONFIG_CACHE is not None:
        return _BOT_CONFIG_CACHE
    out: Dict[str, Any] = {}
    if yaml and os.path.isfile(_CONFIG_YAML_PATH):
        try:
            with open(_CONFIG_YAML_PATH, "r", encoding="utf-8") as f:
                out = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("读取 config.yaml 失败: %s", e)
    _BOT_CONFIG_CACHE = out
    return out


def _feature(name: str) -> bool:
    cfg = _load_yaml_config()
    feats = (cfg.get("features") or {}) if cfg else {}
    if name in feats:
        return bool(feats[name])
    env = (os.environ.get(f"FEISHU_BOT_FEATURE_{name.upper()}") or "").strip().lower()
    if env in ("0", "false", "no"):
        return False
    if env in ("1", "true", "yes"):
        return True
    return True


def _extract_soul_block(tag: str) -> str:
    if tag in _SOUL_BLOCK_CACHE:
        return _SOUL_BLOCK_CACHE[tag]
    if not os.path.isfile(_SOUL_PATH):
        _SOUL_BLOCK_CACHE[tag] = ""
        return ""
    try:
        raw = open(_SOUL_PATH, "r", encoding="utf-8").read()
    except Exception:
        _SOUL_BLOCK_CACHE[tag] = ""
        return ""
    start = f"<!-- FEISHU_BOT:{tag} -->"
    end = f"<!-- /FEISHU_BOT:{tag} -->"
    i = raw.find(start)
    j = raw.find(end)
    if i < 0 or j < 0 or j <= i:
        _SOUL_BLOCK_CACHE[tag] = ""
        return ""
    text = raw[i + len(start) : j].strip()
    _SOUL_BLOCK_CACHE[tag] = text
    return text


def _load_command_map() -> List[Dict[str, Any]]:
    if not os.path.isfile(_COMMAND_MAP_PATH):
        return []
    try:
        with open(_COMMAND_MAP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("commands") or [])
    except Exception as e:
        logger.warning("读取 command_map.json 失败: %s", e)
        return []


def _text_matches_command(text: str, cmd: Dict[str, Any]) -> bool:
    kws = cmd.get("keywords") or []
    t = text.strip()
    for kw in kws:
        if isinstance(kw, str) and kw and kw in t:
            return True
    return False


def _db_allowlist_check(user_open_id: str) -> Tuple[bool, str]:
    raw = (os.environ.get("FEISHU_BOT_DB_ALLOWED_OPEN_IDS") or "").strip()
    cfg = _load_yaml_config()
    sec = (cfg.get("security") or {}) if cfg else {}
    require = sec.get("db_require_allowlist")
    if require is None:
        require = (os.environ.get("FEISHU_BOT_DB_REQUIRE_ALLOWLIST") or "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
    if not raw:
        if not require:
            return True, ""
        return False, _extract_soul_block("DB_DENIED") or "未开放数据库查询（未配置白名单）。"
    if raw in ("*", "any", "ANY"):
        return True, ""
    allowed = {x.strip() for x in raw.replace(";", ",").split(",") if x.strip()}
    if user_open_id and user_open_id in allowed:
        return True, ""
    return False, _extract_soul_block("DB_DENIED") or "无数据库查询权限。"


def _db_connect():
    import pymysql
    from db_config import DB_CONFIG

    cfg = dict(DB_CONFIG)
    ru = (os.environ.get("FEISHU_BOT_MYSQL_USER") or "").strip()
    if ru:
        cfg["user"] = ru
        cfg["password"] = (os.environ.get("FEISHU_BOT_MYSQL_PASSWORD") or "").strip()
    last_err = None
    for _ in range(2):
        try:
            return pymysql.connect(**cfg)
        except Exception as e:
            last_err = e
            time.sleep(0.4)
    raise last_err or RuntimeError("mysql connect failed")


def _safe_table_stats(conn) -> List[str]:
    """只读：固定表名白名单。"""
    tables: List[Tuple[str, str]] = [
        ("t_htma_sale", "销售明细"),
        ("t_htma_stock", "库存"),
        ("t_htma_profit", "毛利"),
        ("t_htma_products", "平台商品"),
        ("t_htma_category", "品类毛利汇总"),
        ("t_htma_product_master", "分店商品档案"),
    ]
    lines: List[str] = []
    with conn.cursor() as cur:
        for tbl, label in tables:
            try:
                cur.execute(
                    f"SELECT COUNT(*) AS c, MIN(data_date) AS dmin, MAX(data_date) AS dmax FROM `{tbl}`"
                )
                row = cur.fetchone()
                if not row:
                    continue
                c = row.get("c") if isinstance(row, dict) else row[0]
                dmin = row.get("dmin") if isinstance(row, dict) else row[1]
                dmax = row.get("dmax") if isinstance(row, dict) else row[2]
                dr = ""
                if dmin or dmax:
                    dr = f" 日期:{dmin}~{dmax}"
                lines.append(f"• {label}（{tbl}）行数 {c}{dr}")
            except Exception:
                try:
                    cur.execute(f"SELECT COUNT(*) AS c FROM `{tbl}`")
                    row = cur.fetchone()
                    c = row.get("c") if isinstance(row, dict) else row[0]
                    lines.append(f"• {label}（{tbl}）行数 {c}（无 data_date 或未统计日期）")
                except Exception as e:
                    lines.append(f"• {label}（{tbl}）跳过（{e!s:.80}）")
    return lines


def _stock_threshold_from_text(text: str) -> Optional[int]:
    if "高库存" in text and not re.search(r"库存\s*(?:大于|>|>=)\s*\d+", text):
        return 100
    m = re.search(r"库存\s*(?:大于|>|>=)\s*(\d+)", text)
    if m:
        v = int(m.group(1))
        return min(max(v, 1), 500000)
    return None


def _run_stock_high(conn, threshold: int) -> str:
    sql = """
        SELECT product_name, sku_code, stock_qty, stock_amount, data_date
        FROM t_htma_stock
        WHERE stock_qty > %s
        ORDER BY stock_qty DESC
        LIMIT 15
    """
    lines = [f"【高库存示例】stock_qty > {threshold}（最多15条）"]
    with conn.cursor() as cur:
        cur.execute(sql, (threshold,))
        rows = cur.fetchall()
        if not rows:
            lines.append("无匹配记录。")
            return "\n".join(lines)
        for i, row in enumerate(rows, 1):
            if isinstance(row, dict):
                name = row.get("product_name") or ""
                sku = row.get("sku_code") or ""
                qty = row.get("stock_qty")
                amt = row.get("stock_amount")
                dd = row.get("data_date")
            else:
                name, sku, qty, amt, dd = row[0], row[1], row[2], row[3], row[4]
            lines.append(f"{i}. {name} | 货号 {sku} | 数量 {qty} | 金额 {amt} | 日期 {dd}")
    lines.append("——————\n以上为只读示例，完整数据请登录看板。")
    return "\n".join(lines)


def build_reply(user_text: str, user_open_id: str) -> str:
    """
    根据用户明文与飞书 open_id 生成回复（不含外层前缀）。
    """
    _ensure_file_logging()
    text = (user_text or "").strip()
    if not text:
        return _extract_soul_block("FALLBACK") or "发送「项目介绍」或「数据概览」试试。"

    commands = _load_command_map()
    intro_cmds = [c for c in commands if c.get("id") == "project_intro"]
    overview_cmds = [c for c in commands if c.get("id") == "db_overview"]

    intro_hit = False
    if _feature("project_intro"):
        if intro_cmds:
            intro_hit = _text_matches_command(text, intro_cmds[0])
        else:
            intro_hit = any(
                k in text for k in ("项目介绍", "项目情况", "介绍下项目", "好特卖介绍", "看板介绍", "进销存介绍")
            )

    # 1) 项目介绍
    if intro_hit:
        body = _extract_soul_block("PROJECT_INTRO")
        if body:
            logger.info("cmd=project_intro open_id=%s", user_open_id)
            return body
        return "（未找到 soul.md 中的项目介绍段落，请检查 config/feishu_bot/soul.md）"

    # 2) 高库存（优先于泛化「查数据库」类，避免误触）
    th = _stock_threshold_from_text(text)
    if th is not None and _feature("db_stock_threshold_query"):
        ok, deny_msg = _db_allowlist_check(user_open_id)
        if not ok:
            logger.info("cmd=stock_high denied open_id=%s", user_open_id)
            return deny_msg
        try:
            conn = _db_connect()
            try:
                out = _run_stock_high(conn, th)
                logger.info("cmd=stock_high ok open_id=%s th=%s", user_open_id, th)
                return out
            finally:
                conn.close()
        except Exception as e:
            logger.exception("stock_high 查询失败: %s", e)
            return _extract_soul_block("DB_ERROR") or "数据库查询失败。"

    overview_hit = False
    if _feature("db_overview"):
        if overview_cmds:
            overview_hit = _text_matches_command(text, overview_cmds[0])
        else:
            overview_hit = any(
                k in text
                for k in (
                    "报告数据库",
                    "数据库内容",
                    "数据概览",
                    "查数据库",
                    "进销存数据",
                    "报告数据",
                    "库表统计",
                )
            )

    # 3) 库表概览
    if overview_hit:
        ok, deny_msg = _db_allowlist_check(user_open_id)
        if not ok:
            logger.info("cmd=db_overview denied open_id=%s", user_open_id)
            return deny_msg
        try:
            conn = _db_connect()
            try:
                stats = _safe_table_stats(conn)
                body = "【数据库概览-核心表】\n" + "\n".join(stats)
                logger.info("cmd=db_overview ok open_id=%s", user_open_id)
                return body
            finally:
                conn.close()
        except Exception as e:
            logger.exception("db_overview 失败: %s", e)
            return _extract_soul_block("DB_ERROR") or "数据库查询失败。"

    fb = _extract_soul_block("FALLBACK")
    logger.info("cmd=fallback open_id=%s text=%s", user_open_id, text[:80])
    return fb or "未识别的指令。"
