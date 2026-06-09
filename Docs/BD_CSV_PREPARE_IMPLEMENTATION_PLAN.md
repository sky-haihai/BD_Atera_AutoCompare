# BD CSV Prepare Module Program Implementation Plan

## 模块目标

BD CSV Prepare 模块负责接收 Bitdefender Endpoint Protection Status 数据，并输出标准化后的 BD CSV。V1 使用手动下载的 Bitdefender CSV 报表作为输入。未来可加入 BD Reports API provider，但必须保持同一份标准化输出契约，避免影响 compare 模块。

该模块只处理 BD 数据读取、source header 校验、字段清洗、row number 补充和 CSV 写入，不处理 device alias，也不判断是否缺少 Atera。

## 输入与输出契约

V1 输入：

- 手动下载的 Bitdefender Endpoint Protection Status CSV。

V1 必填 source headers：

- `Device Name`
- `Company Name`
- `IP Address`
- `Status`
- `Last Seen`

未来输入：

- BD Reports API provider。
- API provider 必须输出与手动 CSV provider 相同的标准化 row。

标准化 CSV 输出示例：

- `data/bd_endpoint_status.csv`

输出列：

- `Device Name`
- `Company Name`
- `IP Address`
- `Status`
- `Last Seen`
- `BD Row Number`

## 建议文件结构

- `src/bd_atera_autocompare/bd_prepare.py`
  - BD provider 协议或基类。
  - 手动 BD CSV provider。
  - BD source header 校验。
  - BD source row 到标准化 row 的映射。
  - `bd-prepare` CLI 入口。
- `src/bd_atera_autocompare/csv_io.py`
  - 通用 CSV 读写函数。
  - 必填 header 校验函数。
- `tests/test_bd_prepare.py`
  - source header、row mapping、row number、CSV 输出、CLI 测试。

如果 Atera 模块已经抽出 `csv_io.py`，BD 模块直接复用；如果还没有抽出，可在实现 BD 模块时把重复 CSV 逻辑移过去。

## 核心数据结构

建议使用轻量数据结构：

- `BdNormalizedRow`
  - `device_name`
  - `company_name`
  - `ip_address`
  - `status`
  - `last_seen`
  - `bd_row_number`
- `BdProvider`
  - `get_rows() -> list[BdNormalizedRow]`
- `ManualBdCsvProvider`
  - 读取手动 BD CSV。
  - 校验 source headers。
  - 给每行补充原始 CSV 行号。
  - 返回标准化 rows。

## 实现步骤

1. 定义 BD 标准化 CSV schema。
   - 输出列顺序必须固定。
   - schema 作为模块常量，写 CSV 和测试共用。

2. 建立 provider 边界。
   - 定义 `BdProvider` 协议或轻量类。
   - provider 对外只返回标准化 rows。
   - 未来 BD API provider 只需要实现同一接口。

3. 实现手动 CSV 读取。
   - 使用 `csv.DictReader`。
   - 编码优先支持 `utf-8-sig`，避免 BOM 干扰 header。
   - 保留 source row 的原始上下文，尤其是 CSV 行号。

4. 实现 source header 校验。
   - 读取前检查必填 headers。
   - 缺 header 时抛出清晰错误，例如列出缺失 header 名称。
   - header 校验函数保持单一职责，便于 Atera 或 alias CSV 复用。

5. 实现 source row 到标准化 row 的映射。
   - `Device Name` -> `Device Name`
   - `Company Name` -> `Company Name`
   - `IP Address` -> `IP Address`
   - `Status` -> `Status`
   - `Last Seen` -> `Last Seen`
   - CSV 实际行号 -> `BD Row Number`
   - device 和 company 只 trim 前后空格。
   - 不修改大小写、不删除括号备注、不应用 alias。

6. 实现 row number 规则。
   - 如果 CSV 第 1 行是 header，第一条数据通常是第 2 行。
   - `BD Row Number` 使用 source CSV 的真实行号，便于人工回查。
   - 空行处理策略需要固定：跳过完全空行，或作为 data quality 交给 compare。建议 V1 跳过完全空行并记录测试。

7. 实现标准化 row 校验。
   - device 和 company 缺失时标记为 data quality 候选，或在 prepare 阶段失败。
   - 推荐 prepare 阶段只校验 header，行级坏数据保留给 compare 模块输出 `Data Quality Review`，这样不会因为个别坏行阻断整份报告。

8. 实现 CSV 写入。
   - 固定输出列顺序。
   - 自动创建输出目录，例如 `data/`。
   - 写出 `BD Row Number`，确保人工审核能追溯原始报表。

9. 实现 CLI。
   - 命令形状：`bd-prepare --bd-report path\to\bd_report.csv --output data/bd_endpoint_status.csv`
   - CLI 只负责参数解析、调用 provider、写 CSV、打印结果。

## 测试计划

- 缺少任一 required header 时失败，错误信息列出缺失列。
- 含 BOM 的 CSV header 能正确识别。
- 标准输入行能映射到完整标准列。
- device 和 company 前后空格被 trim。
- device 名称中的括号备注被保留。
- `BD Row Number` 对应 source CSV 的真实数据行号。
- 完全空行处理符合约定。
- 输出 CSV 列顺序固定。
- 输出目录不存在时会自动创建。
- CLI 参数缺失时返回非零退出码。

## 验收标准

- 执行 `bd-prepare --bd-report path\to\bd_report.csv --output data/bd_endpoint_status.csv` 可以生成标准化 BD CSV。
- 输出 CSV 包含 `BD Row Number`，并能回查到 source 报表行。
- 模块不包含 alias、Atera API 或 compare 逻辑。
- 测试覆盖 header 校验、row mapping、row number、CSV 写入和 CLI 基本路径。
