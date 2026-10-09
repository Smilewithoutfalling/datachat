"""DataChat 内核（阶段 1）。

对外只暴露：analyze()、结果结构、模型配置。入口脚本、UI、评测、以后的 FastAPI 都只依赖这里。
放在 app/core 而不是顶层 core/：现有代码全部以 app.* 导入、tests/conftest 只把项目根加入 sys.path，
放进 app 包内不需要改打包/导入方式，也避免顶层出现第二个包。
"""
from app.core.llm import LLMClient, LLMConfig, LLMError, TokenUsage
from app.core.result import AnalysisResult, Step, format_result
from app.core.service import AGENTS, analyze

__all__ = [
    "analyze", "AGENTS", "AnalysisResult", "Step", "TokenUsage",
    "LLMConfig", "LLMClient", "LLMError", "format_result",
]
