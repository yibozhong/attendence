# Canvas Lab Attendance

从 Canvas 成绩导出文件生成两列签到表，再按姓名将成绩回填到完整成绩表副本。

## 安装

需要 uv 和 Python 3.12 或更高版本：

```bash
uv sync --locked
```

## 使用

### 共用电脑网页签到

```bash
uv sync --locked
uv run lab.py serve --lab Lab-P2 --source grades.csv
```

1. 在这台电脑的浏览器中打开终端输出的 **Check-in page** 完整链接（包含 `#` 后的管理密钥），点击「Open check-in」。
2. 学生依次上前，在同一个页面搜索、选择自己的姓名，点击「Check in」。界面和错误提示均为英文。
3. 每次成功提交立即把 `lab_p2_attendance.csv` 中对应分数保存为 `10`。已有签到表会保留，文件不存在时自动创建。
4. 成功后，右侧立即显示姓名、签到时间和人数统计；搜索和选择自动清空，光标回到搜索框，方便下一位学生直接操作。
5. 点击「Close check-in」后，后台立即拒绝后续提交。服务每次启动都默认关闭；开关和签到记录都在同一页面。
6. 按 `Ctrl+C` 停止服务，然后照常 merge、导入 Canvas：

```bash
uv run lab.py merge --lab Lab-P2 --source grades.csv
```

签到不会自动修改 Canvas。`serve` 要求所选作业满分至少为 10，支持 `--scores` 指定签到文件。

**本机使用：** 默认监听 `127.0.0.1:8000`，学生共用这台电脑，不需要手机、二维码或局域网端口转发。在 WSL 中运行时，可从同一台 Windows 电脑的浏览器打开终端链接。支持 `--port` 更换端口。已移除原来的二维码接口和 `--public-url` 参数。

**连续签到：** 不限制浏览器或设备提交次数，也不限制同一姓名重复签到；每次都会记录，分数保持 `10`。人数统计按不同姓名计数，提交次数包含重复提交。

网页显示的是提交记录；CSV 中原有的手动分数不算网页签到记录。记录保存在签到表旁的 `.csv.sqlite3` 文件中，兼容之前扫码版本的历史记录。CSV 和 SQLite 文件应一起保留；运行期间避免手动编辑 CSV，结束后可以修正选错姓名的分数。

包含管理密钥的链接会在同一页面显示开关按钮；直接打开 `http://127.0.0.1:8000/` 也能签到和查看记录，但新的浏览器会话需要完整链接才能控制开关。共用的管理会话允许现场操作开关，需要老师现场管理。

### 手动编辑签到表

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
