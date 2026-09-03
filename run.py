# -*- coding: utf-8 -*-
import sys

# 打包态一致性自检：必须拦在 import app.main 之前——app/main.py 模块级就 setup_logging()
# 并按真 home 打开 faulthandler.log，等进了 main() 再剥 argv 已经碰过用户环境了。
# selftest 自己把 HOME 换进沙箱，顺带天然绕开 SingleInstance（否则会被判成二次启动）。
if "--selftest" in sys.argv:
    from app.selftest import entry
    entry(sys.argv[1:])       # 不返回：写完结果即 os._exit

from app.main import main

if __name__ == "__main__":
    main()
