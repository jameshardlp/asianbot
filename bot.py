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

# Для Redis (очередь задач)
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("⚠️ Redis не установлен. Установите: pip install redis")

# Для модерации
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ChatMember, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramConflictError
import asyncio

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# Redis настройки
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

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

# ===== REDIS ОЧЕРЕДЬ =====
class TaskQueue:
    def __init__(self):
        self.redis = None
        self.connected = False
        
    async def connect(self):
        if not REDIS_AVAILABLE:
            print("⚠️ Redis недоступен, использую локальную очередь")
            return False
        
        try:
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
            # Локальная очередь (для разработки)
            if not hasattr(self, '_local_queue'):
                self._local_queue = {}
            if queue_name not in self._local_queue:
                self._local_queue[queue_name] = []
            self._local_queue[queue_name].append(data)
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
            # Локальная очередь
            if hasattr(self, '_local_queue') and queue_name in self._local_queue:
                if self._local_queue[queue_name]:
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
            if hasattr(self, '_local_queue') and queue_name in self._local_queue:
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
        
        # Ключевые слова для автоматической проверки
        self.banned_words = [
            'naked', 'nude', 'explicit', 'porn', 'sex', 'fuck',
            'наркотики', 'оружие', 'насилие', 'убийство', 'экстремизм'
        ]
        
        self.suspicious_patterns = [
            r'https?://\S+\.(ru|su|cc|to|top|club|online|site|xyz|click|win|bid)',
            r'\b(купить|продать|деньги|заработать|бизнес|инвестиции)\b',
        ]
    
    async def moderate_content(self, post: PostContent) -> Tuple[bool, str]:
        """
        Модерация контента
        Возвращает: (одобрено, причина)
        """
        # Проверка на запрещенные слова
        text_lower = post.caption.lower()
        photo_lower = post.photo_url.lower()
        
        for word in self.banned_words:
            if word in text_lower or word in photo_lower:
                return False, f"Обнаружено запрещенное слово: {word}"
        
        # Проверка на подозрительные ссылки
        for pattern in self.suspicious_patterns:
            if re.search(pattern, post.caption, re.IGNORECASE):
                return False, "Обнаружена подозрительная ссылка"
        
        # Проверка длины текста
        if len(post.caption) < 100:
            return False, "Слишком короткий текст"
        
        if len(post.caption) > 1024:
            return False, "Превышен лимит символов"
        
        # Проверка на дубликаты
        caption_hash = hashlib.md5(post.caption.encode()).hexdigest()
        if caption_hash in [p.get('hash') for p in self.approved_history[-50:]]:
            return False, "Похожий пост уже был опубликован"
        
        # Автоматическая проверка качества текста
        quality_score = self._check_text_quality(post.caption)
        if quality_score >= self.auto_approve_threshold:
            return True, "auto_approved"
        
        # Если качество среднее - отправляем на ручную модерацию
        return None, "manual_review_required"
    
    def _check_text_quality(self, text: str) -> float:
        """Проверка качества текста (0-1)"""
        score = 0.0
        
        # Длина
        if 500 <= len(text) <= 900:
            score += 0.3
        elif 300 <= len(text) < 500:
            score += 0.2
        
        # Количество предложений
        sentences = re.split(r'[.!?]+', text)
        if 5 <= len(sentences) <= 15:
            score += 0.2
        
        # Наличие мата (разрешен)
        if re.search(r'\b(бля|сука|пиздец|хуйня)\b', text.lower()):
            score += 0.1
        
        # Наличие обращений к читателям
        if re.search(r'\b(вы|вам|вас|ваши)\b', text.lower()):
            score += 0.1
        
        # Наличие самоиронии
        if re.search(r'\b(я|меня|мне|мой|моя|моего|моему)\b', text.lower()):
            if re.search(r'\b(дурак|глупый|смешной|неловкий|странный)\b', text.lower()):
                score += 0.1
        
        # Наличие структуры (начало - развитие - вывод)
        if self._check_structure(text):
            score += 0.2
        
        return min(score, 1.0)
    
    def _check_structure(self, text: str) -> bool:
        """Проверка структуры текста"""
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        
        if len(sentences) < 5:
            return False
        
        # Проверка наличия начала (зацепка)
        first_sentence = sentences[0].lower()
        hooks = ['сижу', 'стою', 'иду', 'вчера', 'сегодня', 'зашел', 'увидел', 'подумал']
        has_hook = any(hook in first_sentence for hook in hooks)
        
        # Проверка наличия вывода
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

# ===== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ ДАННЫХ =====
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"

# ===== ПОИСКОВЫЕ ЗАПРОСЫ (как в вашем коде) =====
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

# ===== СТИЛИ ДЛЯ ГЕНЕРАЦИИ (обновленные) =====
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

# ===== ОСТАЛЬНЫЕ ФУНКЦИИ (сохранены из вашего кода) =====
# [Здесь должны быть все ваши вспомогательные функции:
# clean_punctuation, ensure_ends_with_dot, get_last_sentence, 
# get_sentences, is_sentence_complete, drop_incomplete_tail,
# truncate_by_sentences, validate_caption, clean_text,
# is_age_appropriate, is_traditional_clothing, 
# is_definitely_not_asian, is_photo_acceptable,
# load_schedule, save_schedule, load_users, save_users,
# load_history, save_history, add_to_last_posts, is_similar,
# request_continuation, complete_truncated_text,
# generate_caption, get_fallback_caption,
# search_bing, search_google_direct, search_yandex, search_pexels,
# get_random_photo
# ]

# ВНИМАНИЕ: Вставьте сюда все ваши существующие функции из оригинального кода!

# ===== ОБРАБОТЧИК ОЧЕРЕДИ =====
async def queue_processor():
    """Обработчик очереди задач"""
    print("🔄 Запущен обработчик очереди...")
    
    while True:
        try:
            # Получаем задачу из очереди
            task = await task_queue.pop(QUEUE_NAME)
            
            if task:
                print(f"📨 Получена задача из очереди: {task.get('id')}")
                
                # Проверяем, есть ли в задаче данные для модерации
                if task.get('data', {}).get('needs_moderation', False):
                    # Добавляем в очередь модерации
                    await task_queue.push(MODERATION_QUEUE, task['data'])
                    print("📋 Задача отправлена на модерацию")
                    continue
                
                # Выполняем задачу
                await process_post_task(task['data'])
            
            # Проверяем очередь модерации
            mod_task = await task_queue.pop(MODERATION_QUEUE)
            if mod_task:
                await process_moderation_task(mod_task)
            
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"❌ Ошибка в обработчике очереди: {e}")
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
        
        # Отправляем пост
        await send_post(chat_id, photo_url, caption)
        
        print(f"✅ Пост отправлен в {chat_id}")
        
    except Exception as e:
        print(f"❌ Ошибка обработки задачи: {e}")

async def process_moderation_task(data: Dict[str, Any]):
    """Обработка задачи модерации"""
    try:
        post_id = data.get('id')
        post_data = data.get('post_data', {})
        
        # Создаем объект поста
        post = PostContent(
            photo_url=post_data.get('photo_url', ''),
            caption=post_data.get('caption', ''),
            chat_id=post_data.get('chat_id', ''),
            user_id=post_data.get('user_id', 0),
            timestamp=time.time()
        )
        
        # Проводим модерацию
        approved, reason = await moderator.moderate_content(post)
        
        if approved is True:
            # Пост одобрен автоматически
            post.status = ModerationStatus.AUTO_APPROVED
            print(f"✅ Пост {post_id} автоматически одобрен: {reason}")
            
            # Отправляем в очередь на публикацию
            await task_queue.push(QUEUE_NAME, {
                'chat_id': post.chat_id,
                'photo_url': post.photo_url,
                'caption': post.caption,
                'post_id': post_id
            })
            
        elif approved is None:
            # Требуется ручная модерация
            post.status = ModerationStatus.PENDING
            moderator.pending_posts[post_id] = post
            
            # Уведомляем владельца
            await notify_owner_for_moderation(post_id, post)
            print(f"📋 Пост {post_id} отправлен на ручную модерацию")
            
        else:
            # Пост отклонен
            post.status = ModerationStatus.REJECTED
            print(f"❌ Пост {post_id} отклонен: {reason}")
            
    except Exception as e:
        print(f"❌ Ошибка модерации: {e}")

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
        
        # Обрезаем текст для сообщения
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

# ===== КОМАНДА ДЛЯ МОДЕРАЦИИ =====
@dp.callback_query(lambda c: c.data.startswith('mod_'))
async def handle_moderation_callback(callback: CallbackQuery):
    """Обработка callback'ов модерации"""
    if callback.from_user.id != OWNER_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return
    
    action, post_id = callback.data.split('_')[1], '_'.join(callback.data.split('_')[2:])
    approved = action == 'approve'
    
    # Получаем пост из pending
    if post_id not in moderator.pending_posts:
        await callback.answer("❌ Пост не найден", show_alert=True)
        return
    
    post = moderator.pending_posts[post_id]
    
    if approved:
        # Одобряем
        await moderator.manual_moderate(post_id, True, callback.from_user.id, "Одобрено владельцем")
        
        # Отправляем в очередь на публикацию
        await task_queue.push(QUEUE_NAME, {
            'chat_id': post.chat_id,
            'photo_url': post.photo_url,
            'caption': post.caption,
            'post_id': post_id
        })
        
        await callback.answer("✅ Пост одобрен и отправлен в очередь", show_alert=True)
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ ОДОБРЕН",
            reply_markup=None
        )
    else:
        # Отклоняем
        await moderator.manual_moderate(post_id, False, callback.from_user.id, "Отклонено владельцем")
        await callback.answer("❌ Пост отклонен", show_alert=True)
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ ОТКЛОНЕН",
            reply_markup=None
        )

# ===== ОБНОВЛЕННАЯ ФУНКЦИЯ ГЕНЕРАЦИИ ПОСТА =====
async def generate_and_queue_post(chat_id: str, user_id: int = 0, skip_moderation: bool = False):
    """Генерирует пост и добавляет в очередь с модерацией"""
    try:
        # Генерируем контент
        photo_url = get_random_photo()
        if not photo_url:
            print("❌ Не удалось найти фото")
            return False
        
        caption = generate_caption()
        if not caption:
            print("❌ Не удалось сгенерировать текст")
            return False
        
        # Создаем ID поста
        post_id = f"post_{int(time.time())}_{hashlib.md5(caption.encode()).hexdigest()[:8]}"
        
        # Подготавливаем данные
        post_data = {
            'id': post_id,
            'chat_id': chat_id,
            'photo_url': photo_url,
            'caption': caption,
            'user_id': user_id,
            'timestamp': time.time(),
            'needs_moderation': not skip_moderation
        }
        
        # Если пропускаем модерацию - сразу в очередь отправки
        if skip_moderation:
            await task_queue.push(QUEUE_NAME, post_data)
            print(f"✅ Пост {post_id} добавлен в очередь отправки (без модерации)")
            return True
        
        # Иначе - на модерацию
        await task_queue.push(MODERATION_QUEUE, post_data)
        print(f"📋 Пост {post_id} добавлен в очередь модерации")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка генерации поста: {e}")
        return False

# ===== ОБНОВЛЕННАЯ ФУНКЦИЯ ОТПРАВКИ =====
async def send_post(chat_id, photo_url=None, caption=None):
    """Отправка поста (без модерации, только отправка)"""
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
            # Удаляем пользователя
            users = load_users()
            if chat_id in users:
                users.remove(chat_id)
                save_users(users)
                print(f"🗑️ Пользователь {chat_id} удалён из-за ошибки")
        return False

# ===== ОБНОВЛЕННАЯ ФУНКЦИЯ РАССЫЛКИ =====
async def send_to_all_users():
    """Отправка поста всем пользователям через очередь"""
    users = load_users()
    
    if not users:
        print("⚠️ Нет пользователей для отправки")
        return
    
    print(f"📤 Добавление постов в очередь для {len(users)} пользователей...")
    
    # Генерируем один пост для всех
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
    
    # Добавляем задачи для каждого пользователя
    for chat_id in users:
        post_id = f"post_{int(time.time())}_{chat_id}_{hashlib.md5(caption.encode()).hexdigest()[:6]}"
        
        task_data = {
            'id': post_id,
            'chat_id': chat_id,
            'photo_url': photo_url,
            'caption': caption,
            'user_id': 0,
            'timestamp': time.time(),
            'needs_moderation': False  # Для массовой рассылки пропускаем модерацию
        }
        
        await task_queue.push(QUEUE_NAME, task_data)
    
    # Отправляем в канал
    channel_id = CHANNEL_ID
    if not channel_id or not channel_id.strip():
        channel_id = await get_channel_id()
    
    if channel_id:
        channel_post_id = f"post_{int(time.time())}_channel_{hashlib.md5(caption.encode()).hexdigest()[:6]}"
        await task_queue.push(QUEUE_NAME, {
            'id': channel_post_id,
            'chat_id': channel_id,
            'photo_url': photo_url,
            'caption': caption,
            'user_id': 0,
            'timestamp': time.time(),
            'needs_moderation': False
        })
    
    print(f"✅ {len(users)} задач добавлены в очередь")

# ===== РАСПИСАНИЕ (обновленное) =====
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

# ===== ОБНОВЛЕННЫЕ КОМАНДЫ =====
@dp.message(Command("start"))
async def start(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type == "channel":
        await msg.answer("ℹ️ Я работаю в канале автоматически, команды не требуются.")
        return
    
    # Проверяем права
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
    
    # Добавляем приветственный пост в очередь
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
        # Владелец: отправляем в канал и в личку
        await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
        
        channel_id = CHANNEL_ID
        if not channel_id or not channel_id.strip():
            channel_id = await get_channel_id()
        
        if channel_id:
            await generate_and_queue_post(str(channel_id), user_id, skip_moderation=True)
            await msg.answer("✅ Посты добавлены в очередь")
    else:
        # Обычный пользователь: только в личку
        await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
        await msg.answer("✅ Пост добавлен в очередь")

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
    
    # Длина очереди
    queue_len = await task_queue.get_queue_length(QUEUE_NAME)
    mod_queue_len = await task_queue.get_queue_length(MODERATION_QUEUE)
    
    stats += f"\n📊 Очереди:\n"
    stats += f"• Отправка: {queue_len}\n"
    stats += f"• Модерация: {mod_queue_len}"
    
    await msg.answer(stats)

# ===== ФУНКЦИЯ ПРОВЕРКИ ПРАВ =====
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
    print("🚫 Мужчины, дети, другие национальности: исключены")
    print("📋 Модерация: включена")
    print("📨 Очередь: Redis" if await task_queue.connect() else "📨 Очередь: локальная")
    print("=" * 60)
    
    gc.collect()
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook удалён")
    except Exception as e:
        print(f"⚠️ Ошибка webhook: {e}")
    
    # Запускаем обработчик очереди
    asyncio.create_task(queue_processor())
    
    # Запускаем планировщик
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
