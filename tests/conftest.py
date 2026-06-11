"""
模块名: tests.conftest
功能概述: 配置服务端测试导入路径。
对外接口: 无
依赖关系: pathlib、sys
输入输出: 输入测试运行目录，输出可导入 server 模块的 sys.path。
异常与错误: 无特殊异常处理。
维护说明: 测试从仓库根目录或 server 目录执行都应可用。
"""

from pathlib import Path
import sys

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))
