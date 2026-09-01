# externalBin - P2 sidecar 双探针

- prod 第一探针：externalBin/bin/server(.exe) -> process.resourcesPath/bin/server (electron-builder extraResources externalBin -> bin)
- 第二探针：extraResources/server -> process.resourcesPath/server (python 源码，extraResources ../server -> server)
- dev：join(__dirname,'../../server') 直接 python -m uvicorn`n- better-sqlite3 WAL：PRAGMA journal_mode=WAL synchronous=NORMAL busy_timeout=5000 与后端 database.py 一致
