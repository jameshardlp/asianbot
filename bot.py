import asyncio
import os
import random
import sys
import re
import requests
import json
import time
import gc
import hashlib
from urllib.parse import quote
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

# Для Redis (опционально)
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("⚠️ Redis не установлен. Использую локальную очередь")

# Для Telegram
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ChatMember, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramConflictError

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# Redis настройки (опционально, только если Redis установлен)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_URL = os.getenv("REDIS_URL", None)  # Для Railway

# Очередь задач
QUEUE_NAME = "post_queue"
MODERATION_QUEUE = "moderation_queue"

if not BOT_TOKEN:
    print("❌ Ошибка: BOT_TOKEN не задан")
    sys.exit(1)

if not OWNER_ID:
    print("⚠️ ВНИМАНИЕ: OWNER_ID не задан. Команды для владельца НЕ РАБОТАЮТ.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ ДАННЫХ =====
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"

# ===== ПОИСКОВЫЕ ЗАПРОСЫ =====
SEARCH_QUERIES = [
    "japanese girl casual selfie",
    "japanese woman everyday life",
    "japanese girl instagram photo",
    "japanese woman casual style",
    "japanese girl natural portrait",
    "japanese woman street style",
    "japanese girl city selfie",
    "japanese woman cafe selfie",
    "japanese girl summer outfit",
    "japanese woman modern style",
    "chinese girl casual selfie",
    "chinese woman everyday life",
    "chinese girl instagram photo",
    "chinese woman casual style",
    "chinese girl natural portrait",
    "chinese woman street style",
    "chinese girl city selfie",
    "chinese woman cafe selfie",
    "chinese girl summer dress",
    "chinese woman modern outfit",
    "korean girl casual selfie",
    "korean woman everyday life",
    "korean girl instagram photo",
    "korean woman casual style",
    "korean girl natural portrait",
    "korean woman street style",
    "korean girl city selfie",
    "korean woman cafe selfie",
    "korean girl summer dress",
    "korean woman modern style",
    "thai girl casual selfie",
    "thai woman everyday life",
    "thai girl instagram photo",
    "thai woman casual style",
    "thai girl natural portrait",
    "thai woman street style",
    "thai girl city selfie",
    "thai woman cafe selfie",
    "thai girl summer outfit",
    "thai woman modern dress",
    "japanese girl bikini beach",
    "korean girl bikini photo",
    "chinese girl swimsuit",
    "thai girl bikini",
    "japanese woman swimsuit",
    "korean woman bikini beach",
]

FITNESS_QUERIES = [
    "japanese fitness girl",
    "korean gym girl",
    "chinese fitness woman",
    "thai sport girl",
]

# ===== КЛЮЧЕВЫЕ СЛОВА =====
AGE_POSITIVE_KEYWORDS = [
    '18', '19', '20', '21', '22', '23', '24', '25',
    '26', '27', '28', '29', '30', '20s',
    'young', 'college', 'university'
]

EXCLUDE_KEYWORDS = [
    'african', 'black', 'white', 'caucasian', 'european', 'american',
    'latina', 'mexican', 'brazilian', 'indian', 'middle eastern',
    'arab', 'persian', 'turkish',
    'malaysian', 'filipina', 'vietnamese', 'indonesian',
    'mature', 'old', 'age 40', 'age 50', 'age 60', 'senior',
    'grandma', 'elderly', 'wrinkles',
    'kid', 'child', 'baby', 'toddler', 'infant', 'girl 12', 'girl 13',
    'girl 14', 'girl 15', 'girl 16', 'girl 17', 'teenager', 'teen',
    'man', 'male', 'guy', 'boy', 'men', 'dude', 'bro', 'brother',
    'father', 'dad', 'son', 'husband', 'boyfriend', 'gentleman',
    'мужчина', 'парень', 'мужик', 'пацан', 'мальчик', 'юноша',
    'мужской', 'мужские', 'man model', 'male model', 'fitness man',
    'korean man', 'japanese man', 'chinese man', 'thai man',
    'asian male', 'asian man', 'guy portrait', 'male portrait',
]

TRADITIONAL_EXCLUDE = [
    'kimono', 'hanbok', 'cheongsam', 'qi pao', 'sari', 'ao dai',
    'traditional', 'folk costume', 'national dress'
]

# ===== СТИЛИ ДЛЯ ГЕНЕРАЦИИ =====
style_prompts = {
    'everyday': """
Ты — Анатолий, холостой блогер, который много путешествует по Азии и ведёт блог от своего лица.

Твой стиль:
- Рассказываешь реальные истории, будто они произошли вчера или сегодня.
- Всегда сначала действие, потом размышления.
- Главный объект самоиронии — ты сам. Ты не строишь из себя альфа-самца и часто оказываешься в неловких ситуациях.
- Юмор строится на постиронии и иронии над собой.
- Любишь слегка провоцировать читателей, но без грубости и унижения людей.
- Пишешь живым разговорным языком, будто рассказываешь историю друзьям.

Напиши пост про молодую азиатку, которой восхищаешься и объясняешь почему читателям нужна азиатка (18–30 лет).

Структура поста:
1. Первое предложение должно цеплять необычной бытовой ситуацией.
2. Затем короткая история с неожиданным поворотом.
3. Несколько самоироничных наблюдений.
4. Заканчивай естественным выводом, который вытекает из истории.

Требования:
- 700–800 символов.
- Мат 1–2 раза (бля, сука, пиздец, хуйня), только как эмоциональное слово, без оскорблений.
- Обращайся к читателям во множественном числе (вы, вам, вас).
- Не упоминай жену.
- Не используй штампы вроде "в этот момент я понял", "жизнь научила", "есть о чём задуматься".
- Не начинай пост с общих рассуждений. Сразу начинай с действия.
- Последнее предложение должно звучать как естественный вывод, а не мораль.
- Пиши только готовый пост.
""",

    'funny': """
Ты — Анатолий, холостой блогер, который много путешествует по Азии и ведёт блог от своего лица.

Твой стиль:
- Рассказываешь реальные истории, будто они произошли вчера или сегодня.
- Всегда сначала действие, потом размышления.
- Главный объект самоиронии — ты сам. Ты не строишь из себя альфа-самца и часто оказываешься в неловких ситуациях.
- Юмор строится на постиронии и иронии над собой.
- Любишь слегка провоцировать читателей, но без грубости и унижения людей.
- Пишешь живым разговорным языком, будто рассказываешь историю друзьям.

Напиши смешной пост про молодых азиаток (18–30 лет).

Структура поста:
1. Первое предложение должно цеплять необычной бытовой ситуацией.
2. Затем короткая история с неожиданным поворотом.
3. Несколько самоироничных наблюдений.
4. Заканчивай естественным выводом, который вытекает из истории.

Требования:
- 700–800 символов.
- Мат 1–2 раза (бля, сука, пиздец, хуйня), только как эмоциональное слово, без оскорблений.
- Обращайся к читателям во множественном числе (вы, вам, вас).
- Не упоминай жену.
- Не используй штампы вроде "в этот момент я понял", "жизнь научила", "есть о чём задуматься".
- Не начинай пост с общих рассуждений. Сразу начинай с действия.
- Последнее предложение должно звучать как естественный вывод, а не мораль.
- Пиши только готовый пост.
""",

    'romantic': """
Ты — Анатолий, холостой блогер, который много путешествует по Азии и ведёт блог от своего лица.

Твой стиль:
- Рассказываешь реальные истории, будто они произошли вчера или сегодня.
- Всегда сначала действие, потом размышления.
- Главный объект самоиронии — ты сам. Ты не строишь из себя альфа-самца и часто оказываешься в неловких ситуациях.
- Юмор строится на постиронии и иронии над собой.
- Любишь слегка провоцировать читателей, но без грубости и унижения людей.
- Пишешь живым разговорным языком, будто рассказываешь историю друзьям.

Напиши романтичный пост про молодых японок, китаянок, кореянок или таек (18–30 лет). С сарказмом и самоиронией. Пиши о том что снова влюбился в азиатку.

Структура поста:
1. Первое предложение должно цеплять необычной бытовой ситуацией.
2. Затем короткая история с неожиданным поворотом.
3. Несколько самоироничных наблюдений.
4. Заканчивай естественным выводом, который вытекает из истории.

Требования:
- 700–800 символов.
- Мат 1–2 раза (бля, сука, пиздец, хуйня), только как эмоциональное слово, без оскорблений.
- Обращайся к читателям во множественном числе (вы, вам, вас).
- Не упоминай жену.
- Не используй штампы вроде "в этот момент я понял", "жизнь научила", "есть о чём задуматься".
- Не начинай пост с общих рассуждений. Сразу начинай с действия.
- Последнее предложение должно звучать как естественный вывод, а не мораль.
- Пиши только готовый пост.
""",

    'envy': """
Ты — Анатолий, холостой блогер, который много путешествует по Азии и ведёт блог от своего лица.

Твой стиль:
- Рассказываешь реальные истории, будто они произошли вчера или сегодня.
- Всегда сначала действие, потом размышления.
- Главный объект самоиронии — ты сам. Ты не строишь из себя альфа-самца и часто оказываешься в неловких ситуациях.
- Юмор строится на постиронии и иронии над собой.
- Любишь слегка провоцировать читателей, но без грубости и унижения людей.
- Пишешь живым разговорным языком, будто рассказываешь историю друзьям.

Напиши пост, вызывающий зависть у читателя, про молодых японок, китаянок, кореянок или таек (18-30 лет). С сарказмом, самоиронией, провокацией.

Структура поста:
1. Первое предложение должно цеплять необычной бытовой ситуацией.
2. Затем короткая история с неожиданным поворотом.
3. Несколько самоироничных наблюдений.
4. Заканчивай естественным выводом, который вытекает из истории.

Требования:
- 700–800 символов.
- Мат 1–2 раза (бля, сука, пиздец, хуйня), только как эмоциональное слово, без оскорблений.
- Обращайся к читателям во множественном числе (вы, вам, вас).
- Не упоминай жену.
- Не используй штампы вроде "в этот момент я понял", "жизнь научила", "есть о чём задуматься".
- Не начинай пост с общих рассуждений. Сразу начинай с действия.
- Последнее предложение должно звучать как естественный вывод, а не мораль.
- Пиши только готовый пост.
""",
}

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def clean_punctuation(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'[.!?]{2,}', '.', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('«', '"').replace('»', '"')
    text = text.replace('„', '"').replace('“', '"')
    text = text.replace('`', "'").replace('´', "'")
    text = re.sub(r'[()\[\]{}<>]', '', text)
    text = re.sub(r',\s*\.', '.', text)
    return text.strip()

def ensure_ends_with_dot(text: str) -> str:
    if not text:
        return ''
    text = text.strip()
    if text[-1] in ('.', '!', '?'):
        return text
    last_end = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
    if last_end != -1:
        return text[:last_end + 1].strip()
    return text

def get_last_sentence(text: str) -> str:
    if not text:
        return ''
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if sentences:
        return sentences[-1].strip()
    return ''

def get_sentences(text: str) -> list:
    if not text:
        return []
    return re.split(r'(?<=[.!?])\s+', text.strip())

def is_sentence_complete(sentence: str) -> bool:
    if not sentence:
        return False
    
    clean = re.sub(r'[.!?]$', '', sentence).strip()
    words = clean.split()
    
    if len(words) < 5:
        return False
    
    incomplete_words = ['и', 'а', 'но', 'да', 'или', 'либо', 'за', 'перед', 'под', 'над', 'без', 'для', 'про', 'через', 'между', 'среди', 'у', 'о', 'об', 'от', 'до', 'из', 'с', 'к', 'по', 'на', 'в', 'во', 'вот', 'тем', 'того', 'этого', 'того']
    
    last_word = words[-1].lower()
    if last_word in incomplete_words:
        return False
    
    incomplete_endings = [
        'в её глазах', 'в моей голове', 'в моих мыслях', 'в моей душе',
        'в моём сердце', 'в моей жизни', 'в моём мире', 'в его глазах',
        'в её голове', 'в моём сознании', 'в моей памяти', 'в моих мечтах',
        'на его лице', 'на её лице', 'в моём воображении',
        'и вы знаете', 'и я понимаю', 'и мне кажется', 'и я думаю',
        'но вы понимаете', 'но я знаю', 'и вы понимаете',
        'и я чувствую', 'и я понимаю, что', 'и я думаю, что',
        'я начинаю', 'я продолжаю', 'я хочу сказать', 'я хочу отметить',
        'я думаю о том', 'я говорю о том', 'я говорю про', 'я думаю про',
        'в общем', 'короче говоря', 'так что', 'поэтому',
        'в темноте', 'в тем', 'на тем', 'в том', 'о том',
        'и я', 'но я', 'а я', 'что я', 'когда я', 'пока я',
        'она берет', 'он берет', 'они берут', 'я беру', 'ты берешь',
        'упа', 'будто', 'как', 'словно', 'точно', 'прямо', 'почти'
    ]
    
    clean_lower = clean.lower()
    for ending in incomplete_endings:
        if clean_lower.endswith(ending):
            return False
    
    incomplete_adverbs = ['тогда', 'потом', 'сейчас', 'здесь', 'там', 'тут', 'вчера', 'сегодня', 'завтра', 'всегда', 'никогда', 'иногда', 'уже', 'ещё', 'просто', 'даже', 'почти', 'совсем', 'очень', 'слишком', 'также', 'тоже']
    
    if last_word in incomplete_adverbs and len(words) < 8:
        return False
    
    verbs = [
        'быть', 'стать', 'являться', 'иметь', 'делать', 'сказать', 'пойти',
        'знать', 'думать', 'смотреть', 'видеть', 'слышать', 'чувствовать',
        'понимать', 'хотеть', 'мочь', 'бывать', 'начинать', 'продолжать',
        'заканчивать', 'становиться', 'оставаться', 'казаться', 'стоить',
        'говорить', 'идти', 'стоять', 'сидеть', 'лежать', 'бежать',
        'плыть', 'лететь', 'ехать', 'работать', 'учиться', 'читать',
        'писать', 'рисовать', 'петь', 'танцевать', 'играть', 'смотреть',
        'слушать', 'дышать', 'жить', 'умирать', 'родиться', 'расти',
        'помнить', 'забывать', 'любить', 'ненавидеть', 'мечтать',
        'получаться', 'получиться', 'случаться', 'случиться', 'происходить',
        'произойти', 'существовать', 'обладать', 'пользоваться', 'управлять',
        'думаю', 'знаю', 'понимаю', 'вижу', 'слышу', 'чувствую'
    ]
    
    has_verb = any(verb in clean_lower for verb in verbs)
    has_subject = bool(re.search(r'\b(я|ты|он|она|оно|мы|вы|они|это|тот|всё|все|кто|что|который|которые|которое|эта|этот|эти|сам|себя)\b', clean, re.IGNORECASE))
    
    if len(clean) > 50:
        return True
    
    return has_verb and has_subject

def drop_incomplete_tail(text: str) -> str:
    text = text.strip()
    if not text:
        return ''
    if text[-1] in '.!?':
        return text
    last_end = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
    if last_end != -1:
        return text[:last_end + 1].strip()
    return text

def truncate_by_sentences(text: str, max_length: int = 1023) -> str:
    if not text:
        return ''
    
    text = text.strip()
    text = drop_incomplete_tail(text)
    
    if len(text) <= max_length:
        return ensure_ends_with_dot(text)
    
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result = []
    current_length = 0
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if current_length + len(sentence) + 1 <= max_length:
            result.append(sentence)
            current_length += len(sentence) + 1
        else:
            break
    
    if not result and sentences:
        first = sentences[0].strip()
        if len(first) <= max_length:
            result.append(first)
    
    final_text = ' '.join(result).strip()
    if final_text:
        final_text = ensure_ends_with_dot(final_text)
    return final_text

def validate_caption(text: str, min_length: int = 700, max_length: int = 1023) -> tuple:
    if not text:
        return '', 'Текст пустой'
    
    text = clean_text(text)
    
    if len(text) < 10:
        return '', 'Слишком короткий'
    
    if not text.endswith(('.', '!', '?')):
        text = ensure_ends_with_dot(text)
    
    all_sentences = get_sentences(text)
    
    if not all_sentences:
        return '', 'Нет предложений'
    
    last_sentence = all_sentences[-1].strip() if all_sentences else ''
    
    if last_sentence:
        if not last_sentence.endswith(('.', '!', '?')):
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', 'Последнее предложение не завершено'
        
        word_count = len(last_sentence.split())
        if word_count < 5:
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', f'Последнее предложение слишком короткое ({word_count} слов)'
        
        if not is_sentence_complete(last_sentence):
            print(f"⚠️ Последнее предложение логически не завершено: '{last_sentence}'")
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', 'Последнее предложение не завершено логически'
    
    if len(text) < min_length:
        if len(all_sentences) < 2:
            return '', f'Слишком короткий ({len(text)} символов)'
    
    return text, None

def clean_text(text: str) -> str:
    if not text:
        return ''
    text = text.replace('—', '-').replace('–', '-')
    text = text.replace('@maddysontg', '').replace('@Maddysontg', '').replace('@MADDYSONTG', '')
    text = text.replace('maddysontg', '').replace('Maddysontg', '').replace('MADDYSONTG', '')
    text = re.sub(r'\s+', ' ', text).strip()
    text = clean_punctuation(text)
    return text

def is_age_appropriate(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in AGE_POSITIVE_KEYWORDS:
        if word in url_lower:
            return True
    if re.search(r'\b(age|years?|yo|y/o)\b', url_lower, re.IGNORECASE):
        for word in AGE_POSITIVE_KEYWORDS:
            if word in url_lower:
                return True
        return False
    return True

def is_traditional_clothing(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in TRADITIONAL_EXCLUDE:
        if word in url_lower:
            return True
    return False

def is_definitely_not_asian(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in EXCLUDE_KEYWORDS:
        if word in url_lower:
            return True
    return False

def is_photo_acceptable(url: str) -> bool:
    if not url:
        return False
    
    if is_definitely_not_asian(url):
        return False
    
    if not is_age_appropriate(url):
        return False
    
    if is_traditional_clothing(url):
        return False
    
    return True

# ===== РАБОТА С РАСПИСАНИЕМ =====

def load_schedule():
    try:
        with open(SCHEDULE_FILE, "r") as f:
            data = json.load(f)
            if not data or not data.get("times"):
                return {"times": ["12:00", "21:00"]}
            return data
    except:
        return {"times": ["12:00", "21:00"]}

def save_schedule(schedule_data):
    try:
        with open(SCHEDULE_FILE, "w") as f:
            json.dump(schedule_data, f)
        return True
    except:
        return False

schedule_data = load_schedule()

# ===== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ =====

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_users(users):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)
    except:
        pass

users = load_users()

def load_history():
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_history(history):
    try:
        if len(history) > 100:
            history = history[-100:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except:
        pass

history = load_history()

# ===== КЭШ =====
last_posts = []

def add_to_last_posts(text: str):
    global last_posts
    if not text:
        return
    key = text[:100]
    last_posts.append(key)
    if len(last_posts) > 20:
        last_posts.pop(0)

def is_similar(text: str) -> bool:
    global last_posts
    if not text:
        return False
    key = text[:150]
    for post in last_posts:
        same_chars = sum(1 for a, b in zip(key, post) if a == b)
        if len(key) > 10 and same_chars / len(key) > 0.65:
            return True
    return False

# ===== ПРОДОЛЖЕНИЕ ОБРЕЗАННОГО ТЕКСТА =====

def request_continuation(previous_text: str) -> str:
    try:
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        tail = previous_text[-500:]
        data = {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "Ты стендап-комик Анатолий. Текст поста был обрезан. Допиши ТОЛЬКО концовку — 1-3 завершающих предложения с логическим выводом. Не повторяй уже написанное. Только текст продолжения."},
                {"role": "user", "content": f"Вот текст, который оборвался:\n\n...{tail}\n\nДопиши концовку (1-3 предложения, завершающих мысль). Не повторяй текст выше."}
            ],
            "temperature": 0.9,
            "max_tokens": 400,
        }
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0].get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"⚠️ Ошибка запроса продолжения: {e}")
    return ""

def complete_truncated_text(content: str, finish_reason: str) -> str:
    if finish_reason == "length" and content:
        print(f"⚠️ Текст обрезан (finish_reason=length, {len(content)} символов). Запрашиваю продолжение...")
        continuation = request_continuation(content)
        if continuation:
            continuation = clean_text(continuation)
            tail_100 = content[-100:].lower()
            cont_start = continuation[:100].lower()
            if tail_100 and cont_start and (tail_100 in cont_start or cont_start in tail_100):
                print("⚠️ Продолжение дублирует хвост, не склеиваю")
            elif continuation:
                content = content.rstrip() + " " + continuation.strip()
                print(f"✅ Продолжение получено (+{len(continuation)} символов)")
        else:
            print("⚠️ Продолжение не получено, работаю с тем что есть")
    return content

# ===== ГЕНЕРАЦИЯ ПОСТОВ =====

def generate_caption() -> str:
    print("🧠 Генерирую уникальный пост...")
    
    if not DEEPSEEK_API_KEY:
        print("⚠️ Нет ключа DeepSeek, использую резерв")
        caption = get_fallback_caption()
        caption = clean_text(caption)
        caption = truncate_by_sentences(caption)
        validated, error = validate_caption(caption)
        if validated:
            return validated
        return clean_text(truncate_by_sentences(get_fallback_caption()))
    
    style = random.choice(['everyday', 'funny', 'romantic', 'envy'])
    
    prompt = style_prompts.get(style, style_prompts['funny'])
    prompt += "\n\nТвой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
    
    alternative_prompts = [
        "Напиши саркастичный пост о молодых японках, китаянках, кореянках или тайках. С матом 1-2 раза. 700-800 символов. ЗАКОНЧИ ВЫВОДОМ.",
        "Напиши самоироничный пост про молодых японок, китаянок, кореянок или таек. С матом 1-2 раза. 700-800 символов. ЗАКОНЧИ ВЫВОДОМ.",
        "Напиши провокационный пост про молодых японок, китаянок, кореянок или таек. С юмором и матом. 700-800 символов. ЗАКОНЧИ ВЫВОДОМ.",
    ]
    
    for attempt in range(5):
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            current_prompt = prompt
            if attempt > 0:
                current_prompt = random.choice(alternative_prompts) + "\n\nТвой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
                print(f"🔄 Пробую альтернативный промпт (попытка {attempt+1})...")
            
            data = {
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": "Ты стендап-комик Анатолий. Отвечай ТОЛЬКО готовым постом. НИКАКИХ РАССУЖДЕНИЙ. Только текст поста. Используй мат 1-2 раза (бля, сука, пиздец, хуйня). НЕ ОСКОРБЛЯЙ НАЦИОНАЛЬНОСТИ. НЕ УПОМИНАЙ ЖЕНУ. Пиши с сарказмом, самоиронией и провокацией. ОБЯЗАТЕЛЬНО ЗАВЕРШИ МЫСЛЬ — пост должен заканчиваться логическим выводом или итогом. НЕ ЗАКАНЧИВАЙ НА СЛОВА 'упа', 'будто', 'как', 'словно'."},
                    {"role": "user", "content": current_prompt}
                ],
                "temperature": 1.1,
                "max_tokens": 1500,
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 400:
                error_text = response.text.lower()
                if "извините" in error_text or "не могу" in error_text or "не разрешено" in error_text:
                    print(f"⚠️ Контент заблокирован, пробую другой промпт (попытка {attempt+1})...")
                    continue
            
            if response.status_code != 200:
                print(f"❌ DeepSeek ошибка: {response.status_code}")
                continue
            
            result = response.json()
            choice = result["choices"][0]
            content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason
