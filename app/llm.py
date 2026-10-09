"""兼容层：模型相关实现已移到 app/core/llm.py（超时 / 重试 / token 统计）。"""
from app.core.llm import DEEPSEEK_BASE_URL, LLMClient, LLMConfig, build_chat_model, strip_code  # noqa: F401


def get_llm(temperature: float = 0.0):
    """旧接口：返回按环境变量配置、带显式超时与 SDK 重试的 ChatOpenAI。新代码请用 analyze()。"""
    cfg = LLMConfig.from_env(temperature=temperature)
    return build_chat_model(cfg, sdk_retries=cfg.max_retries)
