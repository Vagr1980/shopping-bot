# -*- coding: utf-8 -*-
"""
Семейный список покупок в Telegram.
"""
import asyncio
import html
import logging
import os
import re
import secrets
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "shopping.db")
NOTIFY_PARTNER = True
MAX_LEN = 120

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS families(
    id INTEGER PRIMARY KEY, code TEXT UNIQUE, title TEXT);
CREATE TABLE IF NOT EXISTS members(
    family_id INTEGER, user_id INTEGER, name TEXT,
    PRIMARY KEY(family_id, user_id));
CREATE TABLE IF NOT EXISTS items(
    id INTEGER PRIMARY KEY, family_id INTEGER, text TEXT,
    done INTEGER DEFAULT 0, added_name TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS panels(
    family_id INTEGER, user_id INTEGER, message_id INTEGER,
    PRIMARY KEY(family_id, user_id));
""")
db.commit()

DELETE_MODE: set[int] = set()
BOT_USERNAME = ""


def q(sql,
