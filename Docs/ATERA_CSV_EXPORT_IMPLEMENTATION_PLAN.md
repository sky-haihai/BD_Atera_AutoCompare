# Atera CSV Export Module Program Implementation Plan

## 模块目标

Atera CSV Export 模块负责从 Atera 获取 agent 数据，并输出标准化后的 Atera CSV。该模块只处理 Atera 数据采集、字段映射、行级校验和 CSV 写入，不参与设备别名处理，也不参与 Atera 与 Bitdefender 的比对。

V1 数据源使用 Atera API。模块需要保留 provider 边界，后续如果要改成手动 Atera CSV 导入，只需要替换 provider，不影响 compare 模块。

## 输入与输出契约

输入环境变量：

- `ATERA_API_KEY`：必填。
- `ATERA_BASE_URL`：选填，默认 `https://app.atera.com/api/v3`。

API 数据源：

- `GET /api/v3/agents`

期望 API 字段：

- `MachineName`
- `CustomerName`
- `IPAddress`
- `Online`
- `LastSeen`
- `AgentID`
- `MachineID`
- `DeviceGUID`

标准化 CSV 输出示例：

- `data/atera_agents.csv`

输出列：

- `Device Name`
- `Company Name`
- `IP Address`
- `Status`
- `Last Seen`
- `Atera Agent ID`
- `Atera Machine ID`
- `Atera Device GUID`

## 建议文件结构

建议后续实现时把 Atera 模块独立成单一职责文件，并保留轻量共享工具：

- `src/bd_atera_autocompare/atera_export.py`
  - Atera provider 协议或基类。
  - Atera API provider。
  - Atera 原始行到标准化行的映射。
  - 标准化 Atera 行校验。
  - `atera-export` CLI 入口。
- `src/bd_atera_autocompare/csv_io.py`
  - 通用 CSV 读写函数。
  - 必填 header 校验函数。
- `tests/test_atera_export.py`
  - Atera API provider、映射、校验、CSV 输出测试。

如果项目保持很小，也可以先把通用 CSV 函数放在 `atera_export.py` 内部，等 BD 模块复用时再抽到 `csv_io.py`。

## 核心数据结构

建议使用清晰的 plain data structure，避免过深继承：

- `AteraNormalizedRow`
  - `device_name`
  - `company_name`
  - `ip_address`
  - `status`
  - `last_seen`
  - `atera_agent_id`
  - `atera_machine_id`
  - `atera_device_guid`
- `AteraProvider`
  - `get_rows() -> list[AteraNormalizedRow]`
- `AteraApiProvider`
  - 读取 API key 和 base URL。
  - 调用 `/agents`。
  - 返回标准化 row，不泄漏 API response 形状给调用方。

## 实现步骤

1. 定义 Atera 标准化 CSV schema。
   - 把输出列顺序定义成常量，后续写 CSV 和测试都引用同一份 schema。
   - 标准化列名必须与总实现计划保持一致。

2. 建立 provider 边界。
   - 定义 `AteraProvider` 协议或轻量类。
   - provider 对外只暴露获取标准化 rows 的方法。
   - compare 模块不能调用 provider，也不能知道 Atera API 细节。

3. 实现 Atera API provider。
   - 从 `ATERA_API_KEY` 读取凭据。
   - 从 `ATERA_BASE_URL` 读取 base URL，缺省使用 `https://app.atera.com/api/v3`。
   - 请求 `GET /agents`。
   - 支持常见分页 response 形状，例如 list payload、`items`、`data`、`agents`。
   - 对 transient HTTP 错误做有限重试。
   - API key 缺失时抛出清晰错误。

4. 实现原始记录到标准化行的映射。
   - `MachineName` -> `Device Name`
   - `CustomerName` -> `Company Name`
   - `IPAddress` -> `IP Address`
   - `Online` -> `Status`
   - `LastSeen` -> `Last Seen`
   - `AgentID` -> `Atera Agent ID`
   - `MachineID` -> `Atera Machine ID`
   - `DeviceGUID` -> `Atera Device GUID`
   - `MachineName` 和 `CustomerName` 只 trim 前后空格，保留原文主体。
   - 不在本模块处理 device alias。

5. 实现状态转换。
   - 将 `Online=True` 转成 compare 模块可识别的在线状态，例如 `Online`。
   - 将 `Online=False` 转成 compare 模块可识别的离线状态，例如 `Offline`。
   - 空值或异常状态保留原始可诊断信息，并交给校验或 compare 的 data quality 规则处理。

6. 实现标准化 row 校验。
   - 必填值至少包含 device 和 company。
   - 缺少关键字段时返回清晰错误或 data quality 记录，具体策略在编码前统一。
   - 校验逻辑独立成小函数，便于测试。

7. 实现 CSV 写入。
   - 使用 UTF-8 with BOM 或 UTF-8，优先保持和项目现有 CSV 输出一致。
   - 固定列顺序。
   - 自动创建输出目录，例如 `data/`。

8. 实现 CLI。
   - 命令形状：`atera-export --output data/atera_agents.csv`
   - 可选参数：`--http-timeout`
   - CLI 只负责解析参数、调用 provider、写出 CSV、返回退出码。

## 测试计划

- API key 缺失时失败信息清晰。
- Atera API payload 为 list 时能正确解析。
- Atera API payload 为 `items` 或 `data` 时能正确解析。
- 字段映射输出完整标准列。
- device 和 company 前后空格被 trim。
- device 名称中的括号、注释或大小写不被修改。
- `Online=True` 输出在线状态。
- `Online=False` 输出离线状态。
- CSV 输出列顺序固定。
- 输出目录不存在时会自动创建。

## 验收标准

- 执行 `atera-export --output data/atera_agents.csv` 可以生成标准化 Atera CSV。
- 输出 CSV 只包含约定列，列顺序稳定。
- 模块不包含 alias、Bitdefender 或 compare 逻辑。
- 测试覆盖 provider、映射、状态转换、CSV 写入和 CLI 基本路径。
