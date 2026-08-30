# ChatGPT 中转 / DeepSeek 官方成本换算器

用于换算 ChatGPT 账号的“几分 1 刀”成本与中转站倍率，并将同一份 Token 用量与可配置的官方 API 渠道直付成本进行对比。交互终端界面使用标准库 ncurses，项目依赖由 `uv` 管理。

## 终端工作台

```bash
uv sync
uv run unit-translator
```

也可以使用 `uv run python unit_converter.py` 直接运行源码。这是一个 ncurses 工作台，主屏包含换算和价格对比，渠道维护通过 `c` 进入：

- 工作台实时计算倍率、账号成本、用户自有 1 亿混合 Token 的实际支出，并在同一页展示 ChatGPT 中转与所有配置渠道的 USD、CNY 和相对成本。充值比例、ChatGPT 输入/输出/缓存价和美元汇率在主屏编辑，输入/输出/缓存用量配比通过 `u` 调整。
- 渠道管理可新建、编辑和删除名称、提供商、模型、三类单价、生效日期、来源和版本。渠道单价固定为 `USD / 1M tokens`；ChatGPT 中转价格不在渠道列表中重复维护。

默认按 `1 元 = 1 刀站内额度`、ChatGPT 输入 `5 刀`、输出 `30 刀`、缓存 `0.5 刀`、`1 USD = 7.2 CNY` 计算。终端至少需要 `72 x 20`，推荐使用 `80 x 24` 或更大的窗口；主屏不使用滚动布局。

主屏使用 `Tab`/`Shift+Tab` 或上下方向键切换输入框，左右方向键编辑当前数字，`m` 切换换算模式，`u` 编辑高级 Token 用量配比，`s` 保存，`r` 还原，`c` 管理渠道，`q` 退出。固定 1 亿实际支出模式会把该配比归一化到 1 亿 Token；其他模式的结果标为“当前用量成本”并按实际总量计算。渠道页使用 `n`/`e`/`d` 新建、编辑和删除；删除渠道始终要求确认，存在未保存修改时退出和还原也会要求确认。主屏在较矮窗口中会压缩渠道对比并显示完整数量，按 `c` 可查看全部渠道。

首次启动时，工作台会从内置价格目录生成可编辑的配置。未传 `--config` 时，目标路径由 `platformdirs` 决定（Linux 通常为 `~/.config/unit-translator/settings.toml`，也会遵从 `$XDG_CONFIG_HOME`）；文件只会在按 `s` 保存后创建。传入 `--config path/to/settings.toml` 或 `--config path/to/settings.json` 可改用指定文件，指定文件不存在时同样以默认配置打开，直到保存才创建。

## 命令行

倍率换算为几分 1 刀：

```bash
uv run unit-translator --multiplier 0.05
```

几分 1 刀换算为倍率：

```bash
uv run unit-translator --fen 5
```

根据用户自有 1 亿混合 Token 的实际支出反算倍率和几分一刀：

```bash
uv run unit-translator --token-cost 5
```

默认价格与充值比例下，结果约为 `0.05547187x`、`5.54718668 分/刀`。

三种换算方向的固定量不同：

- `--multiplier` 或“固定倍率”：倍率和账号成本固定，官方价格变化会改变当前 Token 用量对应的实际成本。
- `--fen` 或“固定账号成本”：几分/刀固定，官方价格变化会改变当前 Token 用量对应的实际成本。
- `--token-cost` 或“固定 1 亿实际支出”：用户自有 1 亿混合 Token 的实际支出固定，官方价格变化会反向改变倍率和几分/刀。

例如要在官方价格调整后保持用户自有 1 亿混合 Token 仍然实付 5 元，应使用 `--token-cost 5`，而不是固定 `--multiplier`。

如果平台充值 1 元可获得 1.2 刀站内额度：

```bash
uv run unit-translator --multiplier 0.12 --ratio 1.2
```

覆盖 ChatGPT 的官方 Token 价格，例如每百万输入、输出、缓存 Token 分别为 2、16、0.2 刀：

```bash
uv run unit-translator --fen 5 --token-price 2 --output-price 16 --cache-price 0.2
```

`--token-price` 继续兼容原命令，也可以写成 `--input-price`。

自定义美元兑人民币汇率：

```bash
uv run unit-translator --multiplier 0.05 --usd-cny-rate 7
```

默认 `0.05x` 和 `7.2` 汇率下，渠道对比结果为：

```text
渠道                            USD              CNY       相对成本倍数
ChatGPT 中转             4.50678902 元       基准
DeepSeek V4 Flash 谷     $2.43363269 / 17.5221554 元 / 3.88794668x
DeepSeek V4 Flash 峰     $4.86726539 / 35.04431079 元 / 7.77589336x
DeepSeek V4 Pro 谷       $7.39322063 / 53.23118854 元 / 11.8113336x
DeepSeek V4 Pro 峰       $14.78644126 / 106.46237709 元 / 23.62266719x
```

## 换算口径

```text
几分/刀 = 倍率 × 100 ÷ 每元获得的站内刀数
倍率 = 几分/刀 × 每元获得的站内刀数 ÷ 100
官方混合成本（USD） = (输入量 × 输入价 + 输出量 × 输出价 + 缓存量 × 缓存价) ÷ 1,000,000
固定 1 亿实际支出模式 = 先按输入/输出/缓存配比归一化到 100,000,000 Token，再反推几分/刀和倍率
ChatGPT 中转成本（CNY） = 官方混合成本 × 几分/刀 ÷ 100
DeepSeek 官方成本（CNY） = DeepSeek 官方混合成本（USD） × 美元汇率
相对成本倍数 = DeepSeek 官方成本（CNY） ÷ ChatGPT 中转成本（CNY）
```

这里的“相对倍数/成本倍数”只是渠道成本对比，不是中转站倍率。中转站倍率仍按账号成本与充值比例换算；如果需要随官方价格调整而保持用户自有 1 亿 Token 实际支出不变，应使用固定 1 亿实际支出模式反推倍率。

混合用量按以下样本比例归一化到 1 亿 Token：

- 输入：`12.73M`，占 `7.453961%`
- 输出：`381.68K`，占 `0.223490%`
- 缓存：`157.67M`，占 `92.322549%`

样本合计 `170.78168M` Token。使用默认价格时，混合单价约为 `0.90135780 刀/百万 Token`；`5 分/刀`对应的 1 亿混合 Token 成本约为 `4.50678902 元`。通过 TUI 的 `u` 或 API 的 `usage` 传入其他样本时，固定 1 亿实际支出模式只取其输入/输出/缓存配比，并自动归一化到 1 亿。

例如默认充值比例下，`0.05x` 等价于 `5 分/刀`，`3 分/刀` 等价于 `0.03x`。

## DeepSeek 官方价格

DeepSeek 普通输入对应官网的 Cache Miss，样本中的缓存 Token 对应 Cache Hit。以下价格单位均为 `USD / 1M Token`：

| 模型与时段 | Cache Miss 输入 | 输出 | Cache Hit |
| --- | ---: | ---: | ---: |
| V4 Flash 谷值 | 0.22 | 0.66 | 0.007 |
| V4 Flash 峰值 | 0.44 | 1.32 | 0.014 |
| V4 Pro 谷值 | 0.66 | 1.98 | 0.022 |
| V4 Pro 峰值 | 1.32 | 3.96 | 0.044 |

峰值时段为 `01:00-04:00 UTC` 和 `06:00-10:00 UTC`，其余时间为谷值。程序始终并列展示两档价格，不根据当前时间自动切换。

价格来源：[DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)，核对日期 `2026-08-21`。价格固定在代码中，运行时不会联网；官方调价后需要同步更新价格常量和测试预期。

## 可编程 API

领域计算已经从终端适配器中抽出，可以直接作为 Python 库使用：

```python
from unit_translator import ConversionRequest, TokenUsage, calculate_conversion

result = calculate_conversion(
    ConversionRequest(
        mode="multiplier",
        value="0.05",
        usage=TokenUsage(input_tokens="1000000", output_tokens="200000", cached_tokens="800000"),
    )
)
print(result.token_cost_yuan)
```

`TokenUsage` 允许传入任意输入、输出、缓存 Token 数量；默认值仍保持原来的 1 亿 Token 归一化样本。固定 1 亿实际支出模式会将自定义用量按配比归一化到 1 亿，其他模式按传入总量计算。领域结果保留 `Decimal` 精度，适配层 JSON 会将金额和倍率序列化为字符串。

## JSON、批处理与配置

使用 `--format json` 或 `--format csv` 获取稳定的机器可读结果：

```bash
uv run unit-translator --multiplier 0.05 --format json
uv run unit-translator --fen 5 --format csv
```

批处理输入支持 JSONL 和 CSV。JSONL 每行是一个转换请求，例如：

```json
{"mode":"multiplier","value":"0.05"}
{"mode":"fen","value":"5","usage":{"input_tokens":"1000000","output_tokens":"200000","cached_tokens":"800000"}}
```

```bash
uv run unit-translator --input-file requests.jsonl --format json
```

价格、汇率和用量可以放在 JSON 或 TOML 配置中，并通过 `--config` 使用。命令行参数优先级高于配置文件：

```toml
version = "pricing-2026-08"
balance_per_yuan = "1.2"
usd_cny_rate = "7.0"

[chatgpt_profile]
input_price = "5"
output_price = "30"
cached_price = "0.5"
```

```bash
uv run unit-translator --config settings.toml --multiplier 0.05
```

将同一个已保存的配置显式传给工作台、JSONL/CSV 批处理或本地 Web API：

```bash
uv run unit-translator --config settings.toml
uv run unit-translator --config settings.toml --input-file requests.jsonl --format json
uv run unit-translator --serve --config settings.toml --host 127.0.0.1 --port 8787
```

配置中的 `usage`、`chatgpt_profile`、`comparison_profiles` 和 `usd_cny_rate` 会作为各入口的默认值；请求或命令行显式提供的值优先。交互工作台可以从不存在的 JSON/TOML 文件开始编辑；批处理和 Web API 对不存在的 `--config` 仍会报错，避免自动生成配置掩盖脚本错误。价格目录快照和汇率都通过可替换 provider 解析，计算结果仍保持显式汇率和精确字符串输出。

批处理 JSON/CSV 会直接写入标准输出并逐条处理，适合较大的请求文件；`--serve` 只能与 `--config`、`--host` 和 `--port` 一起使用，不能同时传入换算或批处理参数。

## Web API

项目提供零依赖的本地 HTTP 适配器，适合先做内部工具或前端原型：

```bash
uv run unit-translator --serve --host 127.0.0.1 --port 8787
```

接口包括：

- `GET /health`
- `GET /api/v1/profiles`
- `POST /api/v1/convert`
- `POST /api/v1/compare`

`POST /api/v1/convert` 的请求体与 JSON CLI 相同，例如：

```json
{
  "mode": "multiplier",
  "value": "0.05",
  "balance_per_yuan": "1",
  "usage": {
    "input_tokens": "1000000",
    "output_tokens": "200000",
    "cached_tokens": "800000"
  }
}
```

固定用户自有 1 亿 Token 实际支出时，将 `mode` 设为 `token_cost`，`value` 填写人民币金额；`usage` 只用于输入、输出、缓存配比，计算时会归一化到 1 亿 Token：

```json
{
  "mode": "token_cost",
  "value": "5",
  "usage": {
    "input_tokens": "10",
    "output_tokens": "20",
    "cached_tokens": "30"
  }
}
```

Web API 默认只监听本机地址，公网部署前应放在反向代理或 FastAPI/ASGI 服务后，并补充认证、限流、日志和价格更新策略。

生产部署的 systemd、Nginx、安全边界和健康检查示例见 [`docs/deployment.md`](docs/deployment.md)。内置服务会返回基础浏览器安全头，但认证、TLS、限流和公网访问日志仍由反向代理负责。

价格目录位于 `config/default_profiles.json`，每条记录包含 provider、model、三类 Token 单价、来源、生效日期和版本。Web API 会从目录读取 `/api/v1/profiles`，也可通过 `create_server(pricing_catalog_path=...)` 注入另一份目录；请求中显式提供 `comparison_profiles` 时仍可做临时比较。`as_of=YYYY-MM-DD` 查询可筛选生效日期不晚于指定日期的价格。

修改目录后可用本地命令先校验再启动服务：

```bash
uv run unit-translator-catalog config/default_profiles.json --summary
uv run unit-translator-catalog config/default_profiles.json --json --as-of 2026-08-28
```

命令会检查 JSON 结构、非负价格、非空版本和 `YYYY-MM-DD` 生效日期；校验失败时返回退出码 `2` 并输出具体字段错误。

汇率保持显式传入以保证换算可复现；`StaticExchangeRateProvider` 和 `ExchangeRateProvider` 已提供可替换边界，后续可以接入带缓存和来源信息的联网 provider，而无需修改领域计算函数。

## 测试

```bash
uv run python -m unittest discover -s tests -v
```

浏览器端到端用例位于 `tests/browser/`，覆盖桌面与 `390 x 844` 移动视口。开发机上的浏览器验收使用 BrowserOS MCP，不需要安装或下载 Chromium；先启动本地服务，再通过 BrowserOS MCP 打开 `http://127.0.0.1:8787` 完成交互检查。

CI 中仍使用 Playwright 的隔离浏览器环境执行同一组用例：

```bash
npm ci
npm run test:e2e
```
