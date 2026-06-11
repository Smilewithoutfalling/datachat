import os
from langchain_openai import ChatOpenAI

# DeepSeek 提供 OpenAI 兼容接口，直接用 ChatOpenAI 指向其 base_url 即可。
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
    )


def strip_code(text: str) -> str:
    """去掉模型可能输出的 ```python ... ``` 代码块标记，只留纯代码。"""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        lines = lines[1:]                      # 去掉开头 ```python
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]                 # 去掉结尾 ```
        t = "\n".join(lines)
    return t.strip()
