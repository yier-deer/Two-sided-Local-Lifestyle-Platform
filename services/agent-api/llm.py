# llm.py —— DeepSeek 客户端（OpenAI 兼容接口，httpx 直调，不引 openai 包）。
# 设计要点：
#  - json 模式：response_format=json_object（DeepSeek 要求提示词里含 "json" 字样并给示例）
#  - 显式超时：LLM 慢生成不能拖死调用方（默认 5s 会掐死，这里 60s）
#  - key 从 .env 读，永不进代码
import json
import os

import httpx
from dotenv import load_dotenv

load_dotenv()  # 读取 services/agent-api/.env

BASE_URL = os.getenv("SCOUTBITE_LLM_BASE_URL", "https://api.deepseek.com")
API_KEY = os.getenv("SCOUTBITE_LLM_API_KEY", "")
MODEL = os.getenv("SCOUTBITE_LLM_MODEL", "deepseek-chat")

# 共享超时客户端（连接 5s / 读 60s——生成慢是常态）
_client = httpx.Client(timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0))

# 用量累计（系统指标）：每次调用的 usage 记到模块级列表，eval 读取算 token 成本
_usage: list[dict] = []


def reset_usage() -> None:
    """清零用量统计（评测开始前调用）"""
    _usage.clear()


def get_usage() -> dict:
    """汇总用量：调用次数 / prompt+completion tokens（DeepSeek 单价折算成本，元）"""
    prompt = sum(u.get("prompt_tokens", 0) for u in _usage)
    completion = sum(u.get("completion_tokens", 0) for u in _usage)
    # deepseek-chat 价目（2026）：输入 ¥0.004/千 token，输出 ¥0.016/千 token（缓存命中忽略，粗估）
    cost = prompt / 1000 * 0.004 + completion / 1000 * 0.016
    return {"calls": len(_usage), "prompt_tokens": prompt,
            "completion_tokens": completion, "cost_yuan": round(cost, 4)}


def llm_available() -> bool:
    """LLM 是否已配置（未配置时上层走诚实降级，绝不生成内容冒充）"""
    return bool(API_KEY)


def chat_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    """
    调 LLM 并要求 JSON 输出。
    :param system: 系统提示词（角色与硬规矩）
    :param user:   用户内容（约束/证据/画像的拼装）
    :return: 解析后的 dict；解析失败抛异常（由上层转 50000）
    """
    if not API_KEY:
        raise RuntimeError("LLM 未配置（.env 缺 SCOUTBITE_LLM_API_KEY）")

    resp = _client.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},  # 强制 JSON（提示词需含 json 示例）
            "temperature": 0.3,   # 推荐场景要稳不要浪
            "max_tokens": max_tokens,
        },
    )
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body.get("usage"), dict):   # 记录用量（系统指标）
        _usage.append(body["usage"])
    content = body["choices"][0]["message"]["content"]
    return json.loads(content)
