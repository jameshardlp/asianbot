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

# Redis настройки (опционально)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_URL = os.getenv("REDIS_URL", None)

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

def validate_caption(text: str, min_length: int = 700, max_length: int = 1023) -> Tuple[str, Optional[str]]:
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

def get_fallback_caption() -> str:
    fallbacks = [
        "Вот вы сидите тут, паритесь, копите на квартиры, на тачки. А я смотрю на фото молодой японки в Instagram и думаю: блядь, как же они умеют жить. Обычный день, обычное фото, а выглядит как обложка журнала. И я понимаю, что всё дело не в деньгах, а в умении жить красиво — они просто умеют радоваться каждому моменту, а мы, мужики, даже не замечаем этих мелочей и тратим время на ерунду. Это и есть главный урок, который я вынес из этого общения.",
        
        "Слушайте, я влюбился в молодую кореянку. Она выложила фото в Instagram, и у меня сердце замирает. Обычный день, обычная улица, а выглядит как фотосессия. И я понимаю, что красота — это не просто внешность, а умение видеть прекрасное в простых вещах, и именно этому они нас учат каждый день, сами того не замечая, и это действительно впечатляет. Вот такая вот простая истина.",
        
        "Сижу, ем доширак, смотрю на фото тайки в соц-сетях. Она в обычной одежде, а я в трусах. И мне хорошо. Потому что я знаю: она всё равно улыбнётся мне. В этом и есть магия — они умеют радоваться жизни даже с такими, как я, и делают это так искренне, что хочется стать лучше ради их улыбки, и это главное, что я понял за всё это время.",
        
        "Пиздец, я только что понял, что жизнь удалась. Я в Instagram, рядом молодая китаянка в обычном образе. И я понимаю, что счастье не в деньгах, а в умении замечать красоту вокруг, и они, эти девушки, показывают нам, как это делать — просто жить и улыбаться, несмотря ни на что, и это урок для всех нас, который я запомню надолго.",
        
        "Знаете, что я понял? Молодые японки, китаянки, кореянки и тайки из соц-сетей - это лучшее, что случалось со мной. Они показывают, что жизнь может быть красивой даже в простых вещах, и это вдохновляет меня на то, чтобы каждый день замечать что-то прекрасное, даже если это просто чашка кофе с утра, и я благодарен им за это понимание.",
        
        "Раньше я думал, что знаю, что такое красота. А потом увидел фото азиатки в обычной жизни. И понял, что красота — это не то, что мы видим, а то, что мы чувствуем, и они умеют передать это чувство даже через экран телефона, заставляя нас улыбаться и мечтать о чём-то большем, и это действительно волшебно. Вот что я хотел сказать.",
    ]
    return random.choice(fallbacks)

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
            finish_reason = choice.get("finish_reason", "")
            usage = result.get("usage", {})
            print(f"📊 finish_reason={finish_reason} | tokens={usage.get('completion_tokens', '?')} | chars={len(content)}")
            
            if finish_reason == "length":
                content = complete_truncated_text(content, finish_reason)
            
            if not content or len(content.strip()) < 20:
                print("❌ Пустой или короткий ответ")
                continue
            
            caption = content.strip().strip('"').strip("'")
            
            if caption.lower().startswith(("мы должны", "нужно", "я должен", "напиши", "вот", "давайте", "попробуем", "извините")):
                print("⚠️ DeepSeek выдал рассуждение или отказ, пробуем другой промпт...")
                continue
            
            if is_similar(caption):
                print("⚠️ Пост похож на недавний, пробуем ещё...")
                continue
            
            caption = clean_text(caption)
            caption = truncate_by_sentences(caption)
            
            validated, error = validate_caption(caption)
            if validated:
                print(f"✅ Сгенерирован пост ({len(validated)} символов)")
                add_to_last_posts(validated)
                return validated
            else:
                print(f"⚠️ Текст не прошёл проверку: {error}, пробуем ещё...")
                continue
            
        except Exception as e:
            print(f"❌ Ошибка генерации (попытка {attempt+1}): {e}")
            continue
    
    print("⚠️ Не удалось сгенерировать уникальный пост, использую резерв")
    caption = get_fallback_caption()
    caption = clean_text(caption)
    caption = truncate_by_sentences(caption)
    validated, error = validate_caption(caption)
    if validated:
        return validated
    return clean_text(get_fallback_caption())

# ===== ПОИСК ФОТО =====

def search_bing(query):
    if not query:
        return None
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        encoded_query = quote(query)
        url = f"https://www.bing.com/images/search?q={encoded_query}&form=HDRSC3&first=1&count=35&safeSearch=moderate"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        pattern = r'"murl":"([^"]+)"'
        images = re.findall(pattern, response.text)
        
        pattern2 = r'"mediaurl":"([^"]+)"'
        images.extend(re.findall(pattern2, response.text))
        
        clean_images = []
        for img in images:
            img = img.replace('\\u0026', '&')
            img = img.replace('\\/', '/')
            
            if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo', 'bing', 'avatar']):
                    if is_photo_acceptable(img):
                        clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Bing: {e}")
        return None

def search_google_direct(query):
    if not query:
        return None
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        encoded_query = quote(query)
        url = f"https://www.google.com/search?q={encoded_query}&tbm=isch&safe=active&tbs=isz:l,itp:photo"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        pattern = r'imgurl=([^&]+)'
        images = re.findall(pattern, response.text)
        
        pattern2 = r'"([^"]+\.jpg[^"]*)"'
        images.extend(re.findall(pattern2, response.text))
        
        clean_images = []
        for img in images:
            img = img.replace('\\u0026', '&')
            img = img.replace('\\/', '/')
            
            if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo']):
                    if not img.startswith('data:'):
                        if is_photo_acceptable(img):
                            clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Google: {e}")
        return None

def search_yandex(query):
    if not query:
        return None
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        
        encoded_query = quote(query)
        url = f"https://yandex.ru/images/search?text={encoded_query}&rdrnd=1&rpt=imageview&noreask=1"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        patterns = [
            r'"img_url":"([^"]+)"',
            r'"url":"([^"]+\.(jpg|jpeg|png|webp))"',
            r'<img[^>]+src="([^"]+\.(jpg|jpeg|png|webp))"',
        ]
        
        images = []
        for pattern in patterns:
            found = re.findall(pattern, response.text)
            for item in found:
                if isinstance(item, tuple):
                    item = item[0]
                if item and not any(x in item.lower() for x in ['logo', 'favicon', 'gif']):
                    images.append(item.replace('\\u0026', '&').replace('\\/', '/'))
        
        clean_images = []
        for img in images:
            if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo']):
                    if not img.startswith('data:'):
                        if is_photo_acceptable(img):
                            clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Yandex: {e}")
        return None

def search_pexels(query):
    if not query:
        return None
    
    try:
        PEXELS_KEY = os.getenv("PEXELS_KEY")
        if not PEXELS_KEY:
            return None
            
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_KEY}
        params = {
            "query": query,
            "per_page": 30,
            "orientation": "portrait",
            "size": "large"
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("photos"):
                photos = data["photos"]
                photo = random.choice(photos)
                url = photo["src"]["large"]
                if is_photo_acceptable(url):
                    return url
        
        return None
        
    except Exception as e:
        print(f"Ошибка Pexels: {e}")
        return None

def get_random_photo():
    global history
    
    if len(history) > 80:
        print("📊 История переполнена, очищаю...")
        history = []
        save_history(history)
    
    queries = SEARCH_QUERIES.copy()
    
    if random.random() < 0.1:
        queries.extend(FITNESS_QUERIES)
        print("💪 Добавлен фитнес-запрос (редко)")
    
    random.shuffle(queries)
    
    search_functions = [
        ('Bing', search_bing),
        ('Google', search_google_direct),
        ('Yandex', search_yandex),
        ('Pexels', search_pexels),
    ]
    
    for query in queries:
        for source_name, search_func in search_functions:
            try:
                print(f"🔍 Поиск в {source_name}: {query}")
                photo = search_func(query)
                if photo and photo not in history and is_photo_acceptable(photo):
                    history.append(photo)
                    save_history(history)
                    print(f"✅ Найдено фото в {source_name}: {photo[:60]}...")
                    return photo
            except Exception as e:
                print(f"⚠️ Ошибка в {source_name}: {e}")
                continue
            
            time.sleep(0.3)
    
    print("⚠️ Не удалось найти новое фото, очищаю историю...")
    history = []
    save_history(history)
    
    for query in queries:
        for source_name, search_func in search_functions:
            try:
                photo = search_func(query)
                if photo and is_photo_acceptable(photo):
                    history.append(photo)
                    save_history(history)
                    print(f"✅ Найдено фото после очистки: {photo[:60]}...")
                    return photo
            except:
                continue
    
    return None

# ===== ОЧЕРЕДЬ ЗАДАЧ =====

class TaskQueue:
    def __init__(self):
        self.redis = None
        self.connected = False
        self._local_queue = {}
    
    async def connect(self):
        if not REDIS_AVAILABLE:
            print("⚠️ Redis недоступен, использую локальную очередь")
            return False
        
        try:
            if REDIS_URL:
                self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            else:
                self.redis = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    password=REDIS_PASSWORD,
                    decode_responses=True
                )
            await self.redis.ping()
            self.connected = True
            print("✅ Redis подключен")
            return True
        except Exception as e:
            print(f"⚠️ Ошибка подключения к Redis: {e}")
            self.connected = False
            return False
    
    async def push(self, queue_name: str, data: Dict[str, Any]):
        """Добавить задачу в очередь"""
        if self.connected:
            try:
                task_id = f"{queue_name}:{int(time.time())}:{hashlib.md5(str(data).encode()).hexdigest()[:8]}"
                await self.redis.rpush(queue_name, json.dumps({
                    "id": task_id,
                    "data": data,
                    "created_at": time.time()
                }))
                print(f"✅ Задача добавлена в очередь {queue_name}: {task_id}")
                return True
            except Exception as e:
                print(f"❌ Ошибка добавления в Redis: {e}")
                return False
        else:
            if queue_name not in self._local_queue:
                self._local_queue[queue_name] = []
            self._local_queue[queue_name].append(data)
            print(f"✅ Задача добавлена в локальную очередь {queue_name}")
            return True
    
    async def pop(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """Получить задачу из очереди"""
        if self.connected:
            try:
                item = await self.redis.lpop(queue_name)
                if item:
                    return json.loads(item)
                return None
            except Exception as e:
                print(f"❌ Ошибка получения из Redis: {e}")
                return None
        else:
            if queue_name in self._local_queue and self._local_queue[queue_name]:
                return self._local_queue[queue_name].pop(0)
            return None
    
    async def get_queue_length(self, queue_name: str) -> int:
        """Получить длину очереди"""
        if self.connected:
            try:
                return await self.redis.llen(queue_name)
            except:
                return 0
        else:
            if queue_name in self._local_queue:
                return len(self._local_queue[queue_name])
            return 0

task_queue = TaskQueue()

# ===== СИСТЕМА МОДЕРАЦИИ =====

class ModerationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"

@dataclass
class PostContent:
    photo_url: str
    caption: str
    chat_id: str
    user_id: int
    timestamp: float
    status: ModerationStatus = ModerationStatus.PENDING
    moderator_id: Optional[int] = None
    moderation_note: Optional[str] = None
    moderation_timestamp: Optional[float] = None

class ContentModerator:
    def __init__(self):
        self.pending_posts = {}
        self.approved_history = []
        self.rejected_history = []
        self.auto_approve_threshold = 0.85
        
        self.banned_words = [
            'naked', 'nude', 'explicit', 'porn', 'sex', 'fuck',
            'наркотики', 'оружие', 'насилие', 'убийство', 'экстремизм'
        ]
        
        self.suspicious_patterns = [
            r'https?://\S+\.(ru|su|cc|to|top|club|online|site|xyz|click|win|bid)',
            r'\b(купить|продать|деньги|заработать|бизнес|инвестиции)\b',
        ]
    
    async def moderate_content(self, post: PostContent) -> Tuple[Optional[bool], str]:
        """Модерация контента. Возвращает: (одобрено, причина)"""
        text_lower = post.caption.lower()
        photo_lower = post.photo_url.lower()
        
        for word in self.banned_words:
            if word in text_lower or word in photo_lower:
                return False, f"Обнаружено запрещенное слово: {word}"
        
        for pattern in self.suspicious_patterns:
            if re.search(pattern, post.caption, re.IGNORECASE):
                return False, "Обнаружена подозрительная ссылка"
        
        if len(post.caption) < 100:
            return False, "Слишком короткий текст"
        
        if len(post.caption) > 1024:
            return False, "Превышен лимит символов"
        
        caption_hash = hashlib.md5(post.caption.encode()).hexdigest()
        if caption_hash in [p.get('hash') for p in self.approved_history[-50:]]:
            return False, "Похожий пост уже был опубликован"
        
        quality_score = self._check_text_quality(post.caption)
        if quality_score >= self.auto_approve_threshold:
            return True, "auto_approved"
        
        return None, "manual_review_required"
    
    def _check_text_quality(self, text: str) -> float:
        """Проверка качества текста (0-1)"""
        score = 0.0
        
        if 500 <= len(text) <= 900:
            score += 0.3
        elif 300 <= len(text) < 500:
            score += 0.2
        
        sentences = re.split(r'[.!?]+', text)
        if 5 <= len(sentences) <= 15:
            score += 0.2
        
        if re.search(r'\b(бля|сука|пиздец|хуйня)\b', text.lower()):
            score += 0.1
        
        if re.search(r'\b(вы|вам|вас|ваши)\b', text.lower()):
            score += 0.1
        
        if re.search(r'\b(я|меня|мне|мой|моя|моего|моему)\b', text.lower()):
            if re.search(r'\b(дурак|глупый|смешной|неловкий|странный)\b', text.lower()):
                score += 0.1
        
        if self._check_structure(text):
            score += 0.2
        
        return min(score, 1.0)
    
    def _check_structure(self, text: str) -> bool:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        
        if len(sentences) < 5:
            return False
        
        first_sentence = sentences[0].lower()
        hooks = ['сижу', 'стою', 'иду', 'вчера', 'сегодня', 'зашел', 'увидел', 'подумал']
        has_hook = any(hook in first_sentence for hook in hooks)
        
        last_sentence = sentences[-1].lower()
        conclusion_words = ['понял', 'вывод', 'итог', 'вот', 'значит', 'оказывается']
        has_conclusion = any(word in last_sentence for word in conclusion_words)
        
        return has_hook and has_conclusion
    
    async def manual_moderate(self, post_id: str, approved: bool, moderator_id: int, note: str = ""):
        """Ручная модерация"""
        if post_id in self.pending_posts:
            post = self.pending_posts[post_id]
            post.status = ModerationStatus.APPROVED if approved else ModerationStatus.REJECTED
            post.moderator_id = moderator_id
            post.moderation_note = note
            post.moderation_timestamp = time.time()
            
            if approved:
                self.approved_history.append({
                    'id': post_id,
                    'hash': hashlib.md5(post.caption.encode()).hexdigest(),
                    'timestamp': time.time()
                })
                if len(self.approved_history) > 100:
                    self.approved_history = self.approved_history[-100:]
            else:
                self.rejected_history.append({
                    'id': post_id,
                    'note': note,
                    'timestamp': time.time()
                })
            
            return True
        return False

moderator = ContentModerator()

# ===== ОБРАБОТЧИК ОЧЕРЕДИ =====

async def send_post(chat_id, photo_url=None, caption=None):
    """Отправка поста"""
    try:
        if not photo_url:
            photo_url = get_random_photo()
        
        if not photo_url:
            return False
        
        if not caption:
            caption = generate_caption()
            caption = clean_text(caption)
            caption = truncate_by_sentences(caption)
            validated, error = validate_caption(caption)
            if validated:
                caption = validated
            else:
                caption = clean_text(get_fallback_caption())
                caption = truncate_by_sentences(caption)
                validated, error = validate_caption(caption)
                if validated:
                    caption = validated
        
        if not caption:
            await bot.send_photo(chat_id=chat_id, photo=photo_url)
            print(f"✅ Фото (без подписи) отправлено в чат {chat_id}")
            return True
        
        if len(caption) > 1024:
            caption = truncate_by_sentences(caption, max_length=1023)
        
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo_url,
            caption=caption
        )
        print(f"✅ Пост отправлен в чат {chat_id}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка отправки в {chat_id}: {e}")
        if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
            users = load_users()
            if chat_id in users:
                users.remove(chat_id)
                save_users(users)
                print(f"🗑️ Пользователь {chat_id} удалён из-за ошибки")
        return False

async def queue_processor():
    """Обработчик очереди задач"""
    print("🔄 Запущен обработчик очереди...")
    
    while True:
        try:
            task = await task_queue.pop(QUEUE_NAME)
            
            if task:
                print(f"📨 Получена задача из очереди: {task.get('id', 'unknown')}")
                
                # Извлекаем данные из задачи
                if 'data' in task:
                    data = task['data']
                else:
                    data = task
                
                if data.get('needs_moderation', False):
                    await task_queue.push(MODERATION_QUEUE, data)
                    print("📋 Задача отправлена на модерацию")
                    continue
                
                await process_post_task(data)
            
            mod_task = await task_queue.pop(MODERATION_QUEUE)
            if mod_task:
                print(f"📋 Получена задача модерации: {mod_task.get('id', 'unknown')}")
                if 'data' in mod_task:
                    data = mod_task['data']
                else:
                    data = mod_task
                await process_moderation_task(data)
            
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"❌ Ошибка в обработчике очереди: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(5)

async def process_post_task(data: Dict[str, Any]):
    """Обработка задачи на отправку поста"""
    try:
        chat_id = data.get('chat_id')
        photo_url = data.get('photo_url')
        caption = data.get('caption')
        
        if not chat_id:
            print("❌ Нет chat_id в задаче")
            return
        
        await send_post(chat_id, photo_url, caption)
        print(f"✅ Пост отправлен в {chat_id}")
        
    except Exception as e:
        print(f"❌ Ошибка обработки задачи: {e}")

async def process_moderation_task(data: Dict[str, Any]):
    """Обработка задачи модерации"""
    try:
        # Проверяем структуру данных
        post_data = data.get('post_data', {})
        if not post_data:
            post_data = data
        
        post_id = post_data.get('id', f"post_{int(time.time())}")
        
        post = PostContent(
            photo_url=post_data.get('photo_url', ''),
            caption=post_data.get('caption', ''),
            chat_id=post_data.get('chat_id', ''),
            user_id=post_data.get('user_id', 0),
            timestamp=time.time()
        )
        
        approved, reason = await moderator.moderate_content(post)
        
        if approved is True:
            post.status = ModerationStatus.AUTO_APPROVED
            print(f"✅ Пост {post_id} автоматически одобрен: {reason}")
            
            await task_queue.push(QUEUE_NAME, {
                'id': post_id,
                'chat_id': post.chat_id,
                'photo_url': post.photo_url,
                'caption': post.caption,
                'user_id': post.user_id,
                'timestamp': post.timestamp,
                'needs_moderation': False
            })
            
        elif approved is None:
            post.status = ModerationStatus.PENDING
            moderator.pending_posts[post_id] = post
            
            await notify_owner_for_moderation(post_id, post)
            print(f"📋 Пост {post_id} отправлен на ручную модерацию")
            
        else:
            post.status = ModerationStatus.REJECTED
            print(f"❌ Пост {post_id} отклонен: {reason}")
            
    except Exception as e:
        print(f"❌ Ошибка модерации: {e}")
        import traceback
        traceback.print_exc()

async def notify_owner_for_moderation(post_id: str, post: PostContent):
    """Уведомление владельца о необходимости модерации"""
    if not OWNER_ID:
        return
    
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve_{post_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject_{post_id}")
            ]
        ])
        
        caption_preview = post.caption[:200] + "..." if len(post.caption) > 200 else post.caption
        
        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"📋 Требуется модерация поста #{post_id}\n\n"
                 f"📸 Фото: {post.photo_url[:100]}...\n"
                 f"📝 Текст:\n{caption_preview}\n\n"
                 f"👤 Автор: {post.user_id}\n"
                 f"📢 Канал: {post.chat_id}",
            reply_markup=keyboard
        )
    except Exception as e:
        print(f"❌ Ошибка уведомления владельца: {e}")

async def generate_and_queue_post(chat_id: str, user_id: int = 0, skip_moderation: bool = False):
    """Генерирует пост и добавляет в очередь"""
    try:
        photo_url = get_random_photo()
        if not photo_url:
            print("❌ Не удалось найти фото")
            return False
        
        caption = generate_caption()
        if not caption:
            print("❌ Не удалось сгенерировать текст")
            return False
        
        post_id = f"post_{int(time.time())}_{hashlib.md5(caption.encode()).hexdigest()[:8]}"
        
        post_data = {
            'id': post_id,
            'chat_id': chat_id,
            'photo_url': photo_url,
            'caption': caption,
            'user_id': user_id,
            'timestamp': time.time(),
            'needs_moderation': not skip_moderation
        }
        
        if skip_moderation:
            await task_queue.push(QUEUE_NAME, post_data)
            print(f"✅ Пост {post_id} добавлен в очередь отправки")
            return True
        
        await task_queue.push(MODERATION_QUEUE, {
            'id': post_id,
            'post_data': post_data
        })
        print(f"📋 Пост {post_id} добавлен в очередь модерации")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка генерации поста: {e}")
        return False

async def send_to_all_users():
    """Отправка поста всем пользователям через очередь"""
    users = load_users()
    
    if not users:
        print("⚠️ Нет пользователей для отправки")
        return
    
    print(f"📤 Добавление постов в очередь для {len(users)} пользователей...")
    
    photo_url = get_random_photo()
    if not photo_url:
        print("❌ Не удалось найти фото")
        return
    
    caption = generate_caption()
    caption = clean_text(caption)
    caption = truncate_by_sentences(caption)
    validated, error = validate_caption(caption)
    if validated:
        caption = validated
    else:
        caption = clean_text(get_fallback_caption())
        caption = truncate_by_sentences(caption)
        validated, error = validate_caption(caption)
        if validated:
            caption = validated
    
    base_post_id = f"post_{int(time.time())}"
    
    for chat_id in users:
        post_data = {
            'id': f"{base_post_id}_{chat_id}",
            'chat_id': chat_id,
            'photo_url': photo_url,
            'caption': caption,
            'user_id': 0,
            'timestamp': time.time(),
            'needs_moderation': False
        }
        
        await task_queue.push(QUEUE_NAME, post_data)
    
    channel_id = CHANNEL_ID
    if not channel_id or not channel_id.strip():
        channel_id = await get_channel_id()
    
    if channel_id:
        await task_queue.push(QUEUE_NAME, {
            'id': f"{base_post_id}_channel",
            'chat_id': channel_id,
            'photo_url': photo_url,
            'caption': caption,
            'user_id': 0,
            'timestamp': time.time(),
            'needs_moderation': False
        })
    
    print(f"✅ {len(users)} задач добавлены в очередь")

async def get_channel_id() -> Optional[str]:
    """Получение ID канала"""
    if CHANNEL_ID and CHANNEL_ID.strip():
        return CHANNEL_ID.strip()
    
    try:
        me = await bot.get_me()
        print(f"🤖 Бот: @{me.username}")
        
        try:
            async with asyncio.timeout(10):
                updates = await bot.get_updates(offset=-1, limit=10)
                for update in updates:
                    if update.channel_post:
                        chat_id = update.channel_post.chat.id
                        try:
                            chat_member = await bot.get_chat_member(chat_id, bot.id)
                            if chat_member.status in ["administrator", "creator"]:
                                print(f"✅ Найден канал: {chat_id}")
                                return str(chat_id)
                        except:
                            pass
        except asyncio.TimeoutError:
            print("⚠️ Таймаут получения обновлений")
        except Exception as e:
            print(f"⚠️ Ошибка получения обновлений: {e}")
            
    except Exception as e:
        print(f"⚠️ Ошибка поиска канала: {e}")
    
    return None

# ===== КОМАНДЫ =====

async def check_user_can_use_command(message: Message) -> bool:
    """Проверяет, может ли пользователь использовать команду"""
    chat_type = message.chat.type
    
    if chat_type == "private":
        return True
    
    if chat_type in ["group", "supergroup"]:
        return await is_user_admin(message.chat.id, message.from_user.id)
    
    return False

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except:
        return False

@dp.callback_query(lambda c: c.data.startswith('mod_'))
async def handle_moderation_callback(callback: CallbackQuery):
    """Обработка callback'ов модерации"""
    if callback.from_user.id != OWNER_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return
    
    parts = callback.data.split('_')
    action = parts[1]
    post_id = '_'.join(parts[2:])
    approved = action == 'approve'
    
    if post_id not in moderator.pending_posts:
        await callback.answer("❌ Пост не найден", show_alert=True)
        return
    
    post = moderator.pending_posts[post_id]
    
    if approved:
        await moderator.manual_moderate(post_id, True, callback.from_user.id, "Одобрено владельцем")
        
        await task_queue.push(QUEUE_NAME, {
            'id': post_id,
            'chat_id': post.chat_id,
            'photo_url': post.photo_url,
            'caption': post.caption,
            'user_id': 0,
            'timestamp': time.time(),
            'needs_moderation': False
        })
        
        await callback.answer("✅ Пост одобрен и отправлен в очередь", show_alert=True)
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ ОДОБРЕН",
            reply_markup=None
        )
    else:
        await moderator.manual_moderate(post_id, False, callback.from_user.id, "Отклонено владельцем")
        await callback.answer("❌ Пост отклонен", show_alert=True)
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ ОТКЛОНЕН",
            reply_markup=None
        )

@dp.message(Command("start"))
async def start(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type == "channel":
        await msg.answer("ℹ️ Я работаю в канале автоматически, команды не требуются.")
        return
    
    if not await check_user_can_use_command(msg):
        await msg.reply("⛔ Эта команда только для администраторов группы.")
        return
    
    if chat_type in ["group", "supergroup"]:
        try:
            chat_member = await bot.get_chat_member(chat_id, bot.id)
            is_admin = chat_member.status in ["administrator", "creator"]
        except:
            is_admin = False
        
        if not is_admin:
            await msg.answer("❌ Я должен быть администратором группы!")
            return
    
    if chat_id not in users:
        users.append(chat_id)
        save_users(users)
        print(f"✅ Добавлен пользователь: {chat_id}")
    
    await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
    
    channel_status = f"\n📢 Канал: {'✅ подключён' if CHANNEL_ID and CHANNEL_ID.strip() else '🔄 авто-поиск'}"
    current_schedule = load_schedule()
    times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
    
    await msg.answer(
        f"✅ Вы подписаны на рассылку!\n"
        f"📸 Уникальные посты про молодых азиаток (18-30 лет)\n"
        f"⏰ Расписание: {times}\n"
        f"{channel_status}\n"
        f"🔄 /photo - получить фото сейчас\n"
        f"⏰ /schedule - изменить расписание\n"
        f"🛑 /stop - отписаться"
    )

@dp.message(Command("photo"))
async def photo(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type == "channel":
        await msg.answer("ℹ️ В канале отправка по команде не требуется.")
        return
    
    if not await check_user_can_use_command(msg):
        await msg.reply("⛔ Только администраторы могут запрашивать фото.")
        return
    
    if chat_id not in users:
        await msg.answer("⚠️ Бот не активирован. Напишите /start")
        return
    
    is_owner = (user_id == OWNER_ID)
    
    if is_owner:
        await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
        
        channel_id = CHANNEL_ID
        if not channel_id or not channel_id.strip():
            channel_id = await get_channel_id()
        
        if channel_id:
            await generate_and_queue_post(str(channel_id), user_id, skip_moderation=True)
            await msg.answer("✅ Посты добавлены в очередь")
    else:
        await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
        await msg.answer("✅ Пост добавлен в очередь")

@dp.message(Command("stop"))
async def stop(msg: Message):
    chat_id = msg.chat.id
    chat_type = msg.chat.type
    
    if chat_type == "channel":
        await msg.answer("ℹ️ В канале отписка не требуется.")
        return
    
    if not await check_user_can_use_command(msg):
        await msg.reply("⛔ Только администраторы могут отключить бота.")
        return
    
    if chat_id in users:
        users.remove(chat_id)
        save_users(users)
        await msg.answer("🛑 Вы отписаны от рассылки")
        print(f"🛑 Удалён пользователь: {chat_id}")
    else:
        await msg.answer("ℹ️ Вы и так не подписаны")

@dp.message(Command("status"))
async def status(msg: Message):
    chat_id = msg.chat.id
    chat_type = msg.chat.type
    
    if chat_type == "channel":
        channel_info = f"📊 Статус канала:\n"
        channel_info += f"• ID: {chat_id}\n"
        channel_info += f"• Бот: {'✅ админ' if await is_user_admin(chat_id, bot.id) else '❌ не админ'}"
        await msg.answer(channel_info)
        return
    
    if not await check_user_can_use_command(msg):
        await msg.reply("⛔ Только администраторы могут смотреть статус.")
        return
    
    is_subscribed = chat_id in users
    channel_id = CHANNEL_ID or await get_channel_id()
    current_schedule = load_schedule()
    times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
    
    status_text = (
        f"📊 Статус бота:\n"
        f"• Подписка: {'✅ Активна' if is_subscribed else '❌ Неактивна'}\n"
        f"• Всего подписчиков: {len(users)}\n"
        f"• Фото в истории: {len(history)}\n"
        f"• Расписание: {times}\n"
        f"• Канал: {'✅ ' + channel_id if channel_id else '❌ не найден'}"
    )
    
    await msg.answer(status_text)

@dp.message(Command("schedule"))
async def schedule(msg: Message):
    if not await check_user_can_use_command(msg):
        await msg.reply("⛔ Только администраторы могут изменять расписание.")
        return
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён. Только для владельца.")
        return
    
    args = msg.text.replace("/schedule", "").strip()
    
    if not args:
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        await msg.answer(
            f"📅 Текущее расписание: {times}\n\n"
            f"Чтобы изменить, напишите:\n"
            f"/schedule 10:00, 15:00, 22:00\n\n"
            f"Укажите от 1 до 4 времен в формате ЧЧ:ММ через запятую."
        )
        return
    
    new_times = []
    for time_str in args.split(','):
        time_str = time_str.strip()
        try:
            hour, minute = map(int, time_str.split(':'))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                new_times.append(f"{hour:02d}:{minute:02d}")
        except:
            continue
    
    if not new_times:
        await msg.answer("❌ Неверный формат. Используйте: /schedule 12:00, 21:00")
        return
    
    if len(new_times) > 4:
        await msg.answer("❌ Максимум 4 времени.")
        return
    
    schedule_data["times"] = new_times
    save_schedule(schedule_data)
    
    times = ", ".join(new_times)
    await msg.answer(f"✅ Расписание обновлено: {times}")

@dp.message(Command("moderate"))
async def moderate_pending(msg: Message):
    """Показать посты на модерации"""
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён")
        return
    
    if not moderator.pending_posts:
        await msg.answer("📭 Нет постов на модерации")
        return
    
    count = len(moderator.pending_posts)
    await msg.answer(f"📋 На модерации: {count} постов\n"
                    f"Используйте кнопки в уведомлениях для модерации")

@dp.message(Command("moderation_stats"))
async def moderation_stats(msg: Message):
    """Статистика модерации"""
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён")
        return
    
    stats = f"📊 Статистика модерации:\n"
    stats += f"• На модерации: {len(moderator.pending_posts)}\n"
    stats += f"• Одобрено: {len(moderator.approved_history)}\n"
    stats += f"• Отклонено: {len(moderator.rejected_history)}\n"
    
    queue_len = await task_queue.get_queue_length(QUEUE_NAME)
    mod_queue_len = await task_queue.get_queue_length(MODERATION_QUEUE)
    
    stats += f"\n📊 Очереди:\n"
    stats += f"• Отправка: {queue_len}\n"
    stats += f"• Модерация: {mod_queue_len}"
    
    await msg.answer(stats)

# ===== РАСПИСАНИЕ =====

is_sending = False

async def scheduler():
    global is_sending
    
    await asyncio.sleep(10)
    print("✅ Планировщик запущен")
    
    while True:
        now = datetime.now()
        current_schedule = load_schedule()
        times = current_schedule.get("times", ["12:00", "21:00"])
        
        target_times = []
        for time_str in times:
            try:
                hour, minute = map(int, time_str.split(':'))
                target = datetime(now.year, now.month, now.day, hour, minute, 0)
                if target <= now:
                    target += timedelta(days=1)
                target_times.append(target)
            except:
                continue
        
        if not target_times:
            target_times = [
                datetime(now.year, now.month, now.day, 12, 0, 0),
                datetime(now.year, now.month, now.day, 21, 0, 0)
            ]
            if target_times[0] <= now:
                target_times[0] += timedelta(days=1)
            if target_times[1] <= now:
                target_times[1] += timedelta(days=1)
        
        target_times.sort()
        
        for target_time in target_times:
            wait_seconds = (target_time - now).total_seconds()
            if wait_seconds > 0:
                print(f"⏳ Следующая отправка в {target_time.strftime('%H:%M')} (через {wait_seconds/3600:.1f} часов)")
                await asyncio.sleep(wait_seconds)
            
            if not is_sending:
                is_sending = True
                try:
                    await send_to_all_users()
                except Exception as e:
                    print(f"❌ Ошибка отправки: {e}")
                finally:
                    is_sending = False
            else:
                print("⚠️ Отправка уже идёт, пропускаем")
            
            now = datetime.now()

# ===== ЗАПУСК =====

async def main():
    print("=" * 60)
    print("🤖 Бот запущен с очередью и модерацией")
    print("🔍 Приоритет: Bing → Google → Yandex → Pexels")
    print(f"📊 Подписчиков: {len(load_users())}")
    
    current_schedule = load_schedule()
    times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
    print(f"⏰ Расписание: {times}")
    
    print(f"📢 Канал: {CHANNEL_ID if CHANNEL_ID else 'авто-поиск'}")
    print(f"👤 Владелец: {OWNER_ID if OWNER_ID else '❌ не задан'}")
    print("🇯🇵 Японки | 🇨🇳 Китаянки | 🇰🇷 Кореянки | 🇹🇭 Тайки")
    print("📋 Модерация: включена")
    
    await task_queue.connect()
    print("=" * 60)
    
    gc.collect()
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook удалён")
    except Exception as e:
        print(f"⚠️ Ошибка webhook: {e}")
    
    asyncio.create_task(queue_processor())
    asyncio.create_task(scheduler())
    
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            skip_updates=True
        )
    except TelegramConflictError as e:
        print(f"⚠️ Конфликт: {e}")
        await asyncio.sleep(5)
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
