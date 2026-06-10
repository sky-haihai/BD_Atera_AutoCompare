# CSV Compare Module Program Implementation Plan

## 模块目标

CSV Compare 模块负责读取标准化 Atera CSV 和标准化 BD CSV，应用可选 device alias，然后输出 exception-only review report。该模块不关心 Atera 或 BD 数据如何取得，只消费标准化 CSV 或标准化 row object。

compare 模块是业务规则最集中的部分，需要保持函数小而明确：读入标准化 rows、规范化 key、应用 alias、检测重复、识别精确匹配、识别低置信度候选、生成异常报告。

## 输入与输出契约

输入：

- `data/atera_agents.csv`
- `data/bd_endpoint_status.csv`
- 可选 device alias CSV

Alias CSV columns：

- `Company Name`
- `Raw Device Name`
- `Canonical Device Name`

输出示例：

- `reports/mismatch.csv`

输出列：

- `Atera Device Name`
- `BD Device Name`
- `Canonical Device Name`
- `Company Name`
- `Missing Software`
- `Issue Type`
- `Match Evidence`
- `Name Similarity`
- `Atera IPv4`
- `BD IPv4`
- `Atera Status`
- `BD Status`
- `Atera Last Seen`
- `BD Last Seen`
- `Atera Count`
- `BD Count`
- `Atera Agent IDs`
- `Atera Machine IDs`
- `Atera Device GUIDs`
- `BD Row Numbers`
- `Alias Applied`
- `Notes`

## 建议文件结构

- `src/bd_atera_autocompare/compare.py`
  - 标准化 row object。
  - alias 读取与应用。
  - key normalization。
  - duplicate detection。
  - exact match detection。
  - low-confidence candidate detection。
  - exception report row builder。
  - `compare` CLI 入口。
- `src/bd_atera_autocompare/csv_io.py`
  - 通用 CSV 读写与 header 校验。
- `tests/test_compare.py`
  - compare 业务规则测试。

## 核心数据结构

建议使用统一的 endpoint record，承载 compare 所需字段：

- `EndpointRecord`
  - `source`
  - `raw_device`
  - `canonical_device`
  - `company`
  - `ip_raw`
  - `ipv4s`
  - `status_raw`
  - `offline`
  - `last_seen_raw`
  - `last_seen`
  - `last_seen_has_time`
  - `bd_row_number`
  - `atera_agent_id`
  - `atera_machine_id`
  - `atera_device_guid`
  - `alias_applied`
  - `notes`
- `PotentialCandidate`
  - `atera`
  - `bd`
  - `similarity`
  - `evidence`

## 匹配规则实现步骤

1. 定义输出 schema。
   - 输出列顺序固定成常量。
   - 所有 report row builder 使用同一份 schema。

2. 读取标准化 CSV。
   - Atera CSV 必须包含 Atera 标准化列。
   - BD CSV 必须包含 BD 标准化列。
   - 缺少 required headers 时输出或抛出清晰的 data quality 信息。

3. 读取 alias CSV。
   - 校验 `Company Name`、`Raw Device Name`、`Canonical Device Name`。
   - alias key 使用 company-scoped key：`normalized_company + normalized_raw_device`。
   - alias row 缺值时输出 `Data Quality Review`，并忽略该 alias row。

4. 建立 key normalization。
   - company 和 device 比对时 trim 并 case-insensitive。
   - 不自动删除括号备注，例如 `(Datatrasfer to Alison)`。
   - 这类备注只通过 alias 归一。

5. 构建 endpoint records。
   - Atera 和 BD 使用同一 record shape。
   - `canonical_device` 默认等于 trim 后的 raw device。
   - 如果命中 alias，则 `canonical_device` 使用 alias 值，`Alias Applied` 标记为 `Yes`。
   - 提取 IPv4，忽略 IPv6。
   - 解析 `Last Seen`，有 timezone 时使用原 timezone，没有 timezone 时按 `America/Edmonton` 处理。
   - loose offline detection 支持 `false`、`0`、`offline`、`disconnected`、`inactive` 等常见值。

6. 检测行级 data quality。
   - device 或 company 缺失时输出 `Data Quality Review`。
   - 无法解析的关键时间字段可在 notes 中保留，不直接阻断比对。
   - data quality rows 保留 source 信息，例如 BD row number 或 Atera ID。

7. 执行 primary matching。
   - 仅在同一 normalized company 内匹配。
   - 使用 `(normalized company, normalized canonical device)` 作为 primary key。
   - Atera 1 条且 BD 1 条时视为 exact single match，报告中省略。

8. 执行 duplicate handling。
   - alias 之后，同一 company + canonical device 如果任一侧出现多条，输出 `Duplicate Manual Review`。
   - duplicate 记录不再自动输出 Missing Atera 或 Missing BD。
   - report row 聚合 Atera IDs、Machine IDs、Device GUIDs 和 BD row numbers。

9. 执行 low-confidence pairing。
   - 只处理 primary matching 和 duplicate handling 后的 unmatched records。
   - 只在同一 company 内寻找候选。
   - 名称相似度使用 Python stdlib `difflib.SequenceMatcher`。
   - 阈值为 `80%`。
   - 如果 IPv4 有交集且名称相似度达到阈值，输出 `Potential Match Manual Review`。
   - IPv4 缺失或不匹配时，只有双方都离线才进入 Last Seen fallback。
   - offline fallback 要求同一 local date，且 Last Seen 相差不超过 60 分钟。
   - 低置信度配对成功后，不再输出对应的 Missing Atera 或 Missing BD。

10. 处理 ambiguous candidates。
    - 如果一条 Atera 可匹配多条 BD，或一条 BD 可匹配多条 Atera，输出 `Ambiguous Potential Match Manual Review`。
    - 每个候选 row 保留 evidence 和 similarity，供人工判断。
    - ambiguous 记录不再额外输出 Missing Atera 或 Missing BD。

11. 输出 missing exceptions。
    - Atera only：
      - `Missing Software = Bitdefender Endpoint Protection`
      - `Issue Type = Missing BD`
    - BD only：
      - `Missing Software = Atera Agent`
      - `Issue Type = Missing Atera`

12. 写出 exception-only CSV。
    - exact single match 不输出。
    - 所有输出 row 使用固定 schema。
    - 自动创建 `reports/` 目录。

## 开发调试入口

compare 模块可以保留一个薄 CLI，方便开发时单独验证 CSV 比对逻辑，但最终用户入口是 PyInstaller 打包后的桌面 app。

调试命令形状：

`compare --atera-csv data/atera_agents.csv --bd-csv data/bd_endpoint_status.csv --output reports/mismatch.csv --device-aliases path\to\device_aliases.csv`

参数：

- `--atera-csv`：必填。
- `--bd-csv`：必填。
- `--output`：必填。
- `--device-aliases`：选填。

这个入口只做参数解析、调用 compare service、写 CSV、打印输出 row 数量。它不调用 Atera API，也不读取原始 BD 数据源。

## 测试计划

- exact single match 被省略。
- device 和 company 的 case/space normalization 生效。
- alias 可以把带备注名称映射到 canonical name。
- alias 是 company-scoped，不跨 company 生效。
- duplicate detection 发生在 alias 之后。
- duplicate 不输出 Missing Atera 或 Missing BD。
- Atera only 输出 `Missing BD`。
- BD only 输出 `Missing Atera`。
- IPv4 overlap 加 80% 相似名称输出 `Potential Match Manual Review`。
- IPv6 被忽略。
- 双方 offline 且 Last Seen 同一天 60 分钟内输出 `Potential Match Manual Review`。
- Last Seen 超过 60 分钟不匹配。
- timezone 缺失时按 `America/Edmonton` 解析。
- ambiguous candidates 输出 `Ambiguous Potential Match Manual Review`。
- alias CSV 缺值输出 `Data Quality Review` 并忽略坏 alias。
- source row 缺 device 或 company 输出 `Data Quality Review`。
- 输出 CSV 列顺序固定。

## 验收标准

- 开发时执行 `compare --atera-csv data/atera_agents.csv --bd-csv data/bd_endpoint_status.csv --output reports/mismatch.csv` 可以生成 mismatch-only report。
- compare 模块不导入 Atera API provider，也不读取原始 BD 手动报表。
- exact matches 不出现在报告中。
- duplicate、potential、ambiguous、missing 和 data quality 五类人工审核场景都有测试覆盖。
