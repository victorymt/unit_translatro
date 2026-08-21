# ChatGPT 中转 / DeepSeek 官方成本换算器

用于换算 ChatGPT 账号的“几分 1 刀”成本与中转站倍率，并将同一份 Token 用量与 DeepSeek 官方 API 直付成本进行对比。项目只有 Python 标准库依赖。

## 终端界面

```bash
python3 unit_converter.py
```

这是一个 `curses` 交互界面，支持倍率、几分一刀和 ChatGPT 中转 1 亿 Token 成本三种方向的实时换算。可以修改充值比例、ChatGPT 每百万输入/输出/缓存 Token 的官方价格，以及美元兑人民币汇率。默认按 `1 元 = 1 刀站内额度`、ChatGPT 输入 `5 刀`、输出 `30 刀`、缓存 `0.5 刀`、`1 USD = 7.2 CNY` 计算。

界面下方始终并列显示 ChatGPT 中转、DeepSeek V4 Flash 峰谷价和 DeepSeek V4 Pro 峰谷价。终端窗口至少需要 `80 x 34`。

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
相对倍数 = DeepSeek 官方成本（CNY） ÷ ChatGPT 中转成本（CNY）
```

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

## 测试

```bash
python3 -m unittest discover -s tests -v
```
