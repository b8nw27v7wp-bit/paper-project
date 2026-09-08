"""pytest conftest：保证现有测试走 dev 回退 + 关闭全局限流。

必须在任何 app import 之前置环境变量：
- DEBUG=true（config 默认 debug=False，prod 强鉴权；现有测试依赖
  dev 下 X-User-Id 回退/默认 user 1）。
- RATELIMIT_DISABLED=1：全套件约 40+ 次 POST /plans，5/min 生产配额下
  必然误杀（ sliding 窗口内自踩）。限流逻辑由 test_security.py 的专用
  单测覆盖（它们自行 delenv + _store.clear + 自定义配额），业务流测试
  不测限流。此开关与 ratelimit.py 注释约定的测试用法一致。
"""
import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("RATELIMIT_DISABLED", "1")
