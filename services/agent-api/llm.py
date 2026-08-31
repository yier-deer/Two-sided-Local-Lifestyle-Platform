# llm.py —— DeepSeek 大模型客户端（OpenAI 兼容接口，httpx 直调，不引 openai 官方包）。
#
# 【这个文件是什么】
#   整个项目「唯一」调用大模型的地方。三张图（推荐/评价/商家）都通过这里的 chat_json() 调模型。
#   把 LLM 调用收口成一个文件的好处：换模型只改这里，超时/成本统计/降级判断都只有一处。
#
# 【三个设计要点（面试可讲）】
#   ① json 模式：请求体带 response_format={"type":"json_object"}，模型保证输出合法 JSON。
#      前提：提示词里必须出现 "json" 字样并给格式示例（DeepSeek 的硬要求，否则报 400）
#   ② 显式超时：读超时给 60 秒——LLM 生成慢是常态，用默认 5 秒会掐死正常请求
#   ③ 密钥从 .env 读，永不进代码、不进 Git（配合 .gitignore）
#
# 【本文件涉及的 Python 语法速览（Java 背景看这里）】
#   import json                      → 标准库，JSON 序列化/反序列化（≈ Jackson）
#   json.loads(字符串)                → JSON 字符串 → Python dict（≈ objectMapper.readValue）
#   _usage: list[dict] = []          → 类型注解 + 初始化为空列表（模块级变量，全局共享）
#   for u in _usage                  → 遍历（≈ for (var u : _usage)）
#   sum(x for x in ...)              → 生成器求和（≈ stream().mapToInt().sum()）
#   round(数, 4)                     → 四舍五入保留 4 位小数
#   body["choices"][0]["message"]    → 逐层取字典的值（≈ Map.get 链式调用）
import json
import os

import httpx
from dotenv import load_dotenv

# 读取 .env 里的密钥（load_dotenv 会找 services/agent-api/.env 并注入环境变量）
load_dotenv()

BASE_URL = os.getenv("SCOUTBITE_LLM_BASE_URL", "https://api.deepseek.com")
API_KEY = os.getenv("SCOUTBITE_LLM_API_KEY", "")     # 空字符串表示没配 key → 上层走诚实降级
MODEL = os.getenv("SCOUTBITE_LLM_MODEL", "deepseek-chat")

# 共享超时客户端（连接 5s / 读 60s / 写 10s / 连接池 5s——LLM 生成慢是常态）
_client = httpx.Client(timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0))

# 用量累计（系统指标）：每次调用的 usage 记到模块级列表，评测脚本读取后折算 token 成本
_usage: list[dict] = []


def reset_usage() -> None:
    """清零用量统计（评测开始前调用，保证本次统计干净）"""
    _usage.clear()


def get_usage() -> dict:
    """汇总用量：调用次数 / prompt+completion tokens（按 DeepSeek 单价折算成本，单位元）

    返回：{"calls": 调用次数, "prompt_tokens": 输入token, "completion_tokens": 输出token, "cost_yuan": 成本}
    用途：评测报告里的「系统指标」——107 次调用 ≈ ¥0.62 就是这么算出来的。
    """
    prompt = sum(u.get("prompt_tokens", 0) for u in _usage)          # 遍历累加输入 token
    completion = sum(u.get("completion_tokens", 0) for u in _usage)  # 累加输出 token
    # deepseek-chat 价目（2026）：输入 ¥0.004/千 token，输出 ¥0.016/千 token（缓存命中忽略，粗估）
    cost = prompt / 1000 * 0.004 + completion / 1000 * 0.016
    return {"calls": len(_usage), "prompt_tokens": prompt,
            "completion_tokens": completion, "cost_yuan": round(cost, 4)}


def llm_available() -> bool:
    """LLM 是否已配置（未配置时上层走诚实降级，绝不生成内容冒充）

    这是「诚实降级」的开关：三张图的 LLM 节点都会先调它，
    返回 False 就直接回 50000「AI 服务未连通，未生成任何内容」。
    """
    return bool(API_KEY)     # 空字符串 → False；有值 → True


def chat_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    """
    调 LLM 并要求 JSON 输出。

    参数：
      system     —— 系统提示词（定义角色 + 硬规矩），对应 messages 里 role=system 那条
      user       —— 用户内容（约束/证据/画像等拼装好的文本），对应 role=user
      max_tokens —— 限制输出长度（防模型啰嗦，也控成本）

    返回：解析后的 dict（如 {"answer": "...", "shops": [...]}）
    异常：未配置 key / 网络错误 / 返回不是合法 JSON → 抛异常，由上层转 50000 诚实降级

    类比 Java：相当于封装好的「调一次大模型并拿到结构化结果」的客户端方法。
    """
    if not API_KEY:
        raise RuntimeError("LLM 未配置（.env 缺 SCOUTBITE_LLM_API_KEY）")

    resp = _client.post(
        f"{BASE_URL}/chat/completions",              # OpenAI 兼容端点
        headers={"Authorization": f"Bearer {API_KEY}"},   # 鉴权头：Bearer + 密钥
        json={
            "model": MODEL,
            # messages 是对话数组：system 定规则，user 给内容
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},  # 强制 JSON 输出（提示词需含 json 示例）
            "temperature": 0.3,   # 采样温度：越低越稳定。推荐/评价场景要稳不要浪
            "max_tokens": max_tokens,
        },
    )
    resp.raise_for_status()          # HTTP 层错误直接抛
    body = resp.json()               # 响应体：{choices:[...], usage:{...}}
    if isinstance(body.get("usage"), dict):   # usage 存在就记账（评测的成本指标来源）
        _usage.append(body["usage"])
    content = body["choices"][0]["message"]["content"]   # 取出模型回复的文本（此时是 JSON 字符串）
    return json.loads(content)       # 字符串 → dict，调用方拿到就能直接 out.get("shops")
