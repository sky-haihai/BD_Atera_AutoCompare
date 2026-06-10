# BD / Atera AutoCompare

这个工具会拉取 Atera agent 数据和 Bitdefender endpoint inventory 数据，生成标准化 CSV，然后输出只包含异常项的人工复核报告。

主入口按桌面应用设计：最终用 PyInstaller 打包成 `BD_Atera_AutoCompare.exe`，用户双击运行，不需要记 CLI 参数。

## 打包后的使用方式

把这些文件放在同一个文件夹：

- `BD_Atera_AutoCompare.exe`
- `.env`

`.env` 可以从 `.env.example` 复制后填写：

```dotenv
ATERA_API_KEY=your-atera-api-key
# ATERA_BASE_URL=https://app.atera.com/api/v3
# ATERA_USER_AGENT=BD-Atera-AutoCompare/0.1

BD_API_KEY=your-bitdefender-api-key
# BD_API_URL=https://cloud.gravityzone.bitdefender.com/api/v1.0/jsonrpc/network
# BD_PARENT_ID=optional-company-or-group-id
# BD_COMPANY_NAME=optional-company-name-for-output
```

运行后默认会在 exe 同目录的 `data/` 文件夹生成：

- `atera_agents.csv`
- `bd_endpoint_status.csv`
- `mismatch.csv`
- `duplicates.csv`

如果需要别名修正，可以在同一个 `data/` 文件夹放：

- `company_aliases.csv`
- `device_aliases.csv`

`company_aliases.csv` 列名：

- `Atera Company Name`
- `BD Company Name`

`device_aliases.csv` 列名：

- `Company Name`
- `Raw Device Name`
- `Canonical Device Name`

## 本地开发运行

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python run_autocompare.py
```

也可以运行包入口：

```powershell
python -m bd_atera_autocompare
```

## PyInstaller 打包

用于打包的 Python 需要包含 Tcl/Tk。Windows 官方 Python installer 默认会安装；如果安装时取消了 `tcl/tk and IDLE`，桌面界面不会被打进 exe。

先安装打包依赖：

```powershell
python -m pip install -e .[build]
```

然后打包：

```powershell
python -m PyInstaller BD_Atera_AutoCompare.spec
```

生成的 exe 在：

```text
dist\BD_Atera_AutoCompare.exe
```

## 开发调试入口

项目仍保留薄 CLI 入口，方便单独调试模块或写自动化测试，但它不是最终用户入口。

```powershell
bd-atera-autocompare
atera-export --help
bd-prepare --help
compare --help
```

## 测试

```powershell
python -m unittest discover tests
```

测试会 mock API provider，不需要真实访问 Atera 或 Bitdefender。
