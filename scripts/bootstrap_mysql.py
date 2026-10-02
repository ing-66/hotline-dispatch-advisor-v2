import os
import sys

import pymysql
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("DB_HOST", "127.0.0.1")
port = int(os.getenv("DB_PORT", "3306"))
database = os.getenv("DB_NAME", "hotline_ai")
password = os.environ["DB_PASSWORD"]

connection = None
admin_user = None
for candidate in ("root", "hotline_migrator"):
    try:
        connection = pymysql.connect(host=host, port=port, user=candidate, password=password, autocommit=True)
        admin_user = candidate
        break
    except pymysql.MySQLError:
        continue

if connection is None:
    sys.exit("No configured MySQL administrator account could connect")

quoted_database = "`" + database.replace("`", "``") + "`"
with connection.cursor() as cursor:
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {quoted_database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
connection.close()
print(f"MySQL database '{database}' is ready via administrator '{admin_user}'")
