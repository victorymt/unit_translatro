# ChatGPT 中转 / DeepSeek 官方成本换算器

用于换算 ChatGPT 账号的“几分 1 刀”成本与中转站倍率，并将同一份 Token 用量与 DeepSeek 官方 API 直付成本进行对比。项目只有 Python 标准库依赖。

## 终端界面

```bash
python3 unit_converter.py
```

这是一个 `curses` 交互界面，支持倍率、几分一刀和 ChatGPT 中转 1 亿 Token 成本三种方向的实时换算。可以修改充值比例、ChatGPT 每百万输入/输出/缓存 Token 的官方价格，以及美元兑人民币汇率。默认按 `1 元 = 1 刀站内额度`、ChatGPT 输入 `5 刀`、输出 `30 刀`、缓存 `0.5 刀`、`1 USD = 7.2 CNY` 计算。

界面下方始终并列显示 ChatGPT 中转、DeepSeek V4 Flash 峰谷价和 DeepSeek V4 Pro 峰谷价。终端窗口至少需要 `60 x 22`；低于 `80 x 34` 时自动使用紧凑布局并缩短表格小数位，面板宽度和垂直位置会随窗口尺寸自动调整。

- `←` / `→` 或 `M`：切换换算方向
- `Tab` / `↑` / `↓`：切换换算值、充值比例、ChatGPT 单价和美元汇率
- 数字、`.`、退格、`Ctrl+U`：编辑当前输入项
- `Enter`：确认并在退出界面后打印结果
- `Q` 或 `Esc`：退出

## 命令行

倍率换算为几分 1 刀：

```bash
python3 unit_converter.py --multiplier 0.05
```

几分 1 刀换算为倍率：

```bash
python3 unit_converter.py --fen 5
```

根据 ChatGPT 中转 1 亿混合 Token 的实付成本反算倍率和几分一刀：

```bash
python3 unit_converter.py --token-cost 5
```

默认价格与充值比例下，结果约为 `0.05547187x`、`5.54718668 分/刀`。

三种换算方向的固定量不同：

- `--multiplier` 或“固定倍率”：倍率和账号成本固定，官方价格变化会改变 1 亿 Token 的实际成本。
- `--fen` 或“固定账号成本”：几分/刀固定，官方价格变化会改变 1 亿 Token 的实际成本。
- `--token-cost` 或“固定 1 亿成本”：实际成本固定，官方价格变化会反向改变倍率和几分/刀。

例如要在官方价格调整后保持 1 亿混合 Token 仍然实付 5 元，应使用 `--token-cost 5`，而不是固定 `--multiplier`。

如果平台充值 1 元可获得 1.2 刀站内额度：

```bash
python3 unit_converter.py --multiplier 0.12 --ratio 1.2
```

覆盖 ChatGPT 的官方 Token 价格，例如每百万输入、输出、缓存 Token 分别为 2、16、0.2 刀：

```bash
python3 unit_converter.py --fen 5 --token-price 2 --output-price 16 --cache-price 0.2
```

`--token-price` 继续兼容原命令，也可以写成 `--input-price`。

自定义美元兑人民币汇率：

```bash
python3 unit_converter.py --multiplier 0.05 --usd-cny-rate 7
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
ChatGPT 中转成本（CNY） = 官方混合成本 × 几分/刀 ÷ 100
DeepSeek 官方成本（CNY） = DeepSeek 官方混合成本（USD） × 美元汇率
相对成本倍数 = DeepSeek 官方成本（CNY） ÷ ChatGPT 中转成本（CNY）
```

这里的“相对倍数/成本倍数”只是渠道成本对比，不是中转站倍率。中转站倍率仍按账号成本与充值比例换算；如果需要随官方价格调整而保持用户 Token 成本不变，应使用固定 Token 成本模式反推倍率。

混合用量按以下样本比例归一化到 1 亿 Token：

- 输入：`12.73M`，占 `7.453961%`
- 输出：`381.68K`，占 `0.223490%`
- 缓存：`157.67M`，占 `92.322549%`

样本合计 `170.78168M` Token。使用默认价格时，混合单价约为 `0.90135780 刀/百万 Token`；`5 分/刀`对应的 1 亿混合 Token 成本约为 `4.50678902 元`。

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

`TokenUsage` 允许传入任意输入、输出、缓存 Token 数量；默认值仍保持原来的 1 亿 Token 归一化样本。领域结果保留 `Decimal` 精度，适配层 JSON 会将金额和倍率序列化为字符串。

## JSON、批处理与配置

使用 `--format json` 或 `--format csv` 获取稳定的机器可读结果：

```bash
python3 unit_converter.py --multiplier 0.05 --format json
python3 unit_converter.py --fen 5 --format csv
```

批处理输入支持 JSONL 和 CSV。JSONL 每行是一个转换请求，例如：

```json
{"mode":"multiplier","value":"0.05"}
{"mode":"fen","value":"5","usage":{"input_tokens":"1000000","output_tokens":"200000","cached_tokens":"800000"}}
```

```bash
python3 unit_converter.py --input-file requests.jsonl --format json
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
python3 unit_converter.py --config settings.toml --multiplier 0.05
```

同一个配置文件也会用于终端界面、JSONL/CSV 批处理和本地 Web API：

```bash
python3 unit_converter.py --config settings.toml
python3 unit_converter.py --config settings.toml --input-file requests.jsonl --format json
python3 unit_converter.py --serve --config settings.toml --host 127.0.0.1 --port 8787
```

配置中的 `usage`、`chatgpt_profile`、`comparison_profiles` 和 `usd_cny_rate` 会作为各入口的默认值；请求或命令行显式提供的值优先。价格目录快照和汇率都通过可替换 provider 解析，计算结果仍保持显式汇率和精确字符串输出。

## Web API

项目提供零依赖的本地 HTTP 适配器，适合先做内部工具或前端原型：

```bash
python3 unit_converter.py --serve --host 127.0.0.1 --port 8787
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

Web API 默认只监听本机地址，公网部署前应放在反向代理或 FastAPI/ASGI 服务后，并补充认证、限流、日志和价格更新策略。

价格目录位于 `config/default_profiles.json`，每条记录包含 provider、model、三类 Token 单价、来源、生效日期和版本。Web API 会从目录读取 `/api/v1/profiles`，也可通过 `create_server(pricing_catalog_path=...)` 注入另一份目录；请求中显式提供 `comparison_profiles` 时仍可做临时比较。`as_of=YYYY-MM-DD` 查询可筛选生效日期不晚于指定日期的价格。

汇率保持显式传入以保证换算可复现；`StaticExchangeRateProvider` 和 `ExchangeRateProvider` 已提供可替换边界，后续可以接入带缓存和来源信息的联网 provider，而无需修改领域计算函数。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
