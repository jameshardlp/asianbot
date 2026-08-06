# ===== payment_system.py =====
"""
Модуль системы оплаты (FreeKassa, AuraPay, Stars)
"""
import os
import json
import time
import hashlib
import requests
import logging
from urllib.parse import urlencode
from typing import Optional, Dict, Any
from aiohttp import web

logger = logging.getLogger(__name__)

# ===== КОНФИГУРАЦИЯ =====
FREEKASSA_SHOP_ID = os.getenv("FREEKASSA_SHOP_ID", "")
FREEKASSA_SECRET1 = os.getenv("FREEKASSA_SECRET1", "")
FREEKASSA_SECRET2 = os.getenv("FREEKASSA_SECRET2", "")
FREEKASSA_API_KEY = os.getenv("FREEKASSA_API_KEY", "")
FREEKASSA_CURRENCY = os.getenv("FREEKASSA_CURRENCY", "RUB")

AURAPAY_MERCHANT_ID = os.getenv("AURAPAY_MERCHANT_ID", "6a70ee5492726")
AURAPAY_API_KEY = os.getenv("AURAPAY_API_KEY", "")
AURAPAY_API_URL = os.getenv("AURAPAY_API_URL", "https://app.aurapay.tech")
AURAPAY_WEBHOOK_URL = os.getenv("AURAPAY_WEBHOOK_URL", "")
AURAPAY_MINIAPP_URL = os.getenv("AURAPAY_MINIAPP_URL", "https://jameshardlp.github.io/asianbot/aura-payment.html")

BROADCAST_PRICE_FILE = "broadcast_price.json"

# ===== ГЛОБАЛЬНЫЕ ДАННЫЕ (будут заполнены из main) =====
broadcast_data = {}
pending_broadcasts = {}

# ===== РАБОТА С ЦЕНОЙ =====

def load_broadcast_price() -> dict:
    try:
        with open(BROADCAST_PRICE_FILE, "r") as f:
            data = json.load(f)
            return data
    except:
        return {"stars": 100, "rub": 100}

def save_broadcast_price(prices: dict):
    try:
        with open(BROADCAST_PRICE_FILE, "w") as f:
            json.dump(prices, f)
        return True
    except:
        return False

broadcast_prices = load_broadcast_price()

# ===== FREEKASSA =====

def generate_freekassa_signature(shop_id: str, amount: str, order_id: str) -> str:
    sign_str = f"{shop_id}:{amount}:{FREEKASSA_SECRET1}:{FREEKASSA_CURRENCY}:{order_id}"
    return hashlib.md5(sign_str.encode()).hexdigest()

def verify_freekassa_webhook_signature(data: dict) -> bool:
    required_fields = ['MERCHANT_ID', 'AMOUNT', 'MERCHANT_ORDER_ID', 'SIGN']
    for field in required_fields:
        if field not in data:
            return False
    
    shop_id = str(data.get('MERCHANT_ID'))
    amount = str(data.get('AMOUNT'))
    order_id = str(data.get('MERCHANT_ORDER_ID'))
    sign = str(data.get('SIGN'))
    
    sign_str = f"{shop_id}:{amount}:{FREEKASSA_SECRET2}:{FREEKASSA_CURRENCY}:{order_id}"
    expected_sign = hashlib.md5(sign_str.encode()).hexdigest()
    return sign == expected_sign

def create_freekassa_payment_link(amount: float, order_id: str, description: str = "") -> str:
    if not FREEKASSA_SHOP_ID or not FREEKASSA_SECRET1:
        logger.error("❌ FreeKassa не настроен")
        return ""
    
    shop_id = str(FREEKASSA_SHOP_ID)
    amount_int = int(amount)
    amount_str = str(amount_int)
    order_id_str = str(order_id)
    
    signature = generate_freekassa_signature(shop_id, amount_str, order_id_str)
    
    params = {
        "m": shop_id,
        "oa": amount_str,
        "currency": FREEKASSA_CURRENCY,
        "o": order_id_str,
        "s": signature,
    }
    if description:
        params["description"] = description[:255]
    
    return f"https://pay.fk.money/?{urlencode(params)}"

async def check_freekassa_payment_status(order_id: str) -> Optional[dict]:
    if not FREEKASSA_API_KEY:
        return None
    try:
        url = "https://api.freekassa.ru/v1/orders/status"
        headers = {"Content-Type": "application/json"}
        data = {
            "merchant_id": FREEKASSA_SHOP_ID,
            "api_key": FREEKASSA_API_KEY,
            "order_id": order_id
        }
        response = requests.post(url, headers=headers, json=data, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                return result.get("data", {})
        return None
    except Exception as e:
        logger.error(f"Ошибка проверки статуса: {e}")
        return None

# ===== AURAPAY =====

def create_aurapay_payment(amount: float, order_id: str, user_id: int, method: str = "card") -> Optional[dict]:
    if not AURAPAY_API_KEY or not AURAPAY_MERCHANT_ID:
        logger.error("❌ AuraPay не настроен")
        return None
    
    possible_endpoints = [
        f"{AURAPAY_API_URL}/invoice/create",
        f"{AURAPAY_API_URL}/api/invoice/create",
        f"{AURAPAY_API_URL}/v1/invoice/create",
        f"{AURAPAY_API_URL}/api/v1/invoice/create",
    ]
    
    for endpoint in possible_endpoints:
        try:
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": AURAPAY_API_KEY,
                "X-Merchant-Id": AURAPAY_MERCHANT_ID
            }
            
            payload = {
                "merchant_id": AURAPAY_MERCHANT_ID,
                "order_id": order_id,
                "amount": str(amount),
                "currency": "RUB",
                "description": f"Оплата рассылки #{order_id}",
                "callback_url": f"{AURAPAY_WEBHOOK_URL}/aurapay/webhook",
                "success_url": f"{AURAPAY_WEBHOOK_URL}/aurapay-success",
                "fail_url": f"{AURAPAY_WEBHOOK_URL}/aurapay-fail",
                "payment_methods": [method] if method else ["card", "sbp", "crypto"],
                "metadata": {
                    "user_id": str(user_id),
                    "order_type": "broadcast"
                }
            }
            
            response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
            
            if response.status_code in [200, 201]:
                result = response.json()
                if result.get("payment_url"):
                    return {
                        "payment_url": result["payment_url"],
                        "payment_id": result.get("payment_id"),
                        "status": result.get("status", "pending")
                    }
                elif result.get("redirect_url"):
                    return {
                        "payment_url": result["redirect_url"],
                        "payment_id": result.get("payment_id"),
                        "status": "pending"
                    }
        except Exception as e:
            logger.error(f"❌ Ошибка AuraPay: {e}")
            continue
    
    return None

async def check_aurapay_payment_status(order_id: str) -> Optional[dict]:
    if not AURAPAY_API_KEY:
        return None
    try:
        url = f"{AURAPAY_API_URL}/invoice/status"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": AURAPAY_API_KEY,
            "X-Merchant-Id": AURAPAY_MERCHANT_ID
        }
        payload = {"order_id": order_id}
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return result.get("data") or result
        return None
    except Exception as e:
        logger.error(f"Ошибка проверки статуса AuraPay: {e}")
        return None

# ===== WEBHOOK ОБРАБОТЧИКИ =====

async def aurapay_webhook(request):
    try:
        data = await request.json()
        logger.info(f"📩 Получен webhook от AuraPay: {data}")
        
        order_id = data.get('order_id') or data.get('merchant_order_id')
        status = data.get('status') or data.get('payment_status')
        
        if not order_id:
            return web.Response(text="Missing order_id", status=400)
        
        if status in ['paid', 'success', 'completed']:
            base_order_id = order_id.replace('_aurapay', '')
            
            for uid, info in broadcast_data.items():
                if info.get('order_id') == base_order_id:
                    logger.info(f"✅ Платёж {order_id} подтверждён для {uid}")
                    break
        
        return web.Response(text="OK", status=200)
    except Exception as e:
        logger.error(f"❌ Ошибка в webhook AuraPay: {e}")
        return web.Response(text="Error", status=500)

async def freekassa_webhook(request):
    try:
        data = await request.post()
        data = dict(data)
        logger.info(f"📩 Получен webhook: {data.get('MERCHANT_ORDER_ID', 'unknown')}")
        
        if not verify_freekassa_webhook_signature(data):
            return web.Response(text="Invalid signature", status=400)
        
        order_id = data.get('MERCHANT_ORDER_ID')
        status = data.get('STATUS')
        
        if status == 'SUCCESS':
            base_order_id = order_id.replace('_rub', '')
            for uid, info in broadcast_data.items():
                if info.get('order_id') == base_order_id:
                    logger.info(f"✅ Платёж {order_id} подтверждён для {uid}")
                    break
        
        return web.Response(text="OK", status=200)
    except Exception as e:
        logger.error(f"❌ Ошибка в webhook: {e}")
        return web.Response(text="Error", status=500)