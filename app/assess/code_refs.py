"""兼容层：口径抽取与判定在阶段 7.5 第 3 步 S3-2 搬到了 `app/tools/code_scope.py`（判定只有一份）。

这里只 re-export，旧的 `from app.assess.code_refs import analyze_code, filter_conditions` 照常可用。
新代码请直接 import `app.tools.code_scope`。
"""
from app.tools.code_scope import (  # noqa: F401
    CodeRefs, analyze_code, filter_conditions, frame_attrs, library_names, parse,
)
