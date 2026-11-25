"""一次性迁移执行器：对 DATABASE_URL 指向的库跑指定 .sql 文件。用完即删。"""
import sys
from urllib.parse import urlparse

import pymysql
from pymysql.constants import CLIENT

# 从 .env 取 DATABASE_URL，避免硬编码
url = None
with open("../.env", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line.startswith("DATABASE_URL=") and not line.startswith("#"):
            url = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
if not url:
    print("DATABASE_URL not found in ../.env")
    sys.exit(1)

p = urlparse(url)
conn = pymysql.connect(
    host=p.hostname,
    port=p.port or 3306,
    user=p.username,
    password=p.password or "",
    database=p.path.lstrip("/"),
    charset="utf8mb4",
    autocommit=True,
    client_flag=CLIENT.MULTI_STATEMENTS,
)

sql_path = sys.argv[1]
with open(sql_path, encoding="utf-8") as f:
    sql = f.read()

with conn.cursor() as cur:
    cur.execute(sql)
    while cur.nextset():  # 消费多语句结果
        pass
conn.close()
print(f"OK: executed {sql_path}")
