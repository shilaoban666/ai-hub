---
name: 使用mysqlsh执行数据库操作
description: 用户已安装mysqlsh，数据库操作应直接使用mysqlsh命令而非Python脚本
type: feedback
---

使用 mysqlsh 命令直接执行数据库迁移和查询操作，不要创建 Python 迁移脚本。

**Why:** 用户已经安装了 mysqlsh 工具，直接使用命令行工具更高效、更直接，避免创建临时的 Python 脚本文件。

**How to apply:** 当需要执行数据库操作（ALTER TABLE、UPDATE、SELECT 等）时，使用 mysqlsh 命令连接到数据库并执行 SQL。数据库连接信息在 backend/.env 文件中。

示例命令格式：
```bash
mysqlsh --host=106.15.224.155 --port=3326 --user=root --password=root123 --database=aihub --sql -e "SQL语句"
```
