# -*- coding: utf-8 -*-
"""复现：连接测试功能是否走通 worker → connTestResult 信号链路"""
import os, sys, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QTimer, QElapsedTimer

app = QGuiApplication(sys.argv)
from app.ui.bridge import Bridge

bridge = Bridge()
cid = bridge.cfg["connections"][0]["id"]
print("testing cid =", cid, "name =", bridge.cfg["connections"][0].get("name"))

results = []
bridge.connTestResult.connect(lambda c, ok, msg: results.append((c, ok, msg)))
bridge.modelsFetched.connect(lambda c, models: results.append((c, "models", len(models))))

bridge.testConnection(cid)
bridge.fetchModels(cid)

t = QElapsedTimer()
t.start()
while t.elapsed() < 45000 and len(results) < 2:
    app.processEvents()
    time.sleep(0.05)

print("RESULTS:", results)
if not results:
    print("REPRO_CONFIRMED: 信号链路无返回（功能失效）")
else:
    print("SIGNAL_CHAIN_OK（功能本身通，问题在别处）")
app.quit()
