# Canvas Lab Attendance

从 Canvas 成绩导出文件生成两列签到表，再按姓名将成绩回填到完整成绩表副本。

## 安装

需要 uv 和 Python 3.12 或更高版本：

```bash
uv sync --locked
```

## 使用

从 Canvas 导出成绩 CSV，放在本地，通过 `--source` 指定路径：

```bash
uv run lab.py init --lab Lab-P2 --source grades.csv
```

生成 `lab_p2_attendance.csv`，包含 `Student` 和对应 Lab 成绩两列，所有学生初始分为 `0`。修改签到表中的分数，保留姓名和列名；`10` 和 `10.0` 都可以。

修改完成后回填：

```bash
uv run lab.py merge --lab Lab-P2 --source grades.csv
```

生成 `lab_p2_import.csv`，在 Canvas 的 Grades → Import 中上传，核对预览后保存。回填使用最新 Canvas 导出，避免重新导入其他作业的旧成绩。

下次 Lab 将 `--lab` 改为 `Lab-P3` 等。可用 `--scores` 指定签到表路径，`merge` 还支持 `--output` 指定输出文件。

## 行为

- 按姓名匹配，忽略大小写、首尾空格和连续空白；允许调整签到表的行顺序。
- 检查重名、重复 ID、缺失或未知姓名，以及分数是否在 `0` 到 `Points Possible` 之间。
- 仅更新所选 Lab 的学生分数，保留其他字段和满分信息。
- `init` 不覆盖已有签到表；`merge` 可覆盖输出文件，但不能覆盖 source 或签到表。
- CSV 文件包含学生信息，已加入 `.gitignore`，不随代码提交。

学生共用签到表时仍能修改其他人的分数，需要现场核对。
