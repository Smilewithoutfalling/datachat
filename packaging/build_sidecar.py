"""用 PyInstaller 把 app/sidecar.py 打成 onedir（dist/datachat-sidecar/）。在仓库根目录运行：

    python packaging/build_sidecar.py

onedir 而不是 onefile：onefile 每次启动要解压到临时目录（慢，且沙箱子进程每次都要再启动一遍 exe）。
"""
import os
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARGS = [
    os.path.join(ROOT, "app", "sidecar.py"),
    "--name", "datachat-sidecar",
    "--onedir", "--console", "--noconfirm", "--clean",
    "--paths", ROOT,
    "--distpath", os.path.join(ROOT, "dist"),
    "--workpath", os.path.join(ROOT, "build"),
    "--specpath", os.path.join(ROOT, "build"),
    # app 内部有按名字延迟导入的模块（sandbox_worker、server 等），全部收进来
    "--collect-submodules", "app",
    # uvicorn 按字符串加载协议 / 事件循环实现
    "--collect-submodules", "uvicorn",
    # jieba 的词典文件；keyring 通过 entry points 发现后端，需要包元数据
    "--collect-data", "jieba",
    "--copy-metadata", "keyring",
    "--collect-submodules", "keyring.backends",
    # 用不到、但会被分析器拖进来的大包
    "--exclude-module", "streamlit",
    "--exclude-module", "tkinter",
    "--exclude-module", "IPython",
    "--exclude-module", "pytest",
]

if __name__ == "__main__":
    PyInstaller.__main__.run(ARGS + sys.argv[1:])
