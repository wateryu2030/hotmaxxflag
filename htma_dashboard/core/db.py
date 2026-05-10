# -*- coding: utf-8 -*-
"""
数据库连接工具函数。
统一封装 pymysql 连接，供 app / 脚本共用。
"""
import pymysql
from db_config import DB_CONFIG, get_conn


def get_dict_conn():
    """返回 pymysql DictCursor 连接。"""
    config = dict(DB_CONFIG)
    config["cursorclass"] = pymysql.cursors.DictCursor
    return pymysql.connect(**config)
