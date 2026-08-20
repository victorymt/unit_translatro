# 倍率换算器

用于换算 GPT 账号的“几分 1 刀”成本与中转站倍率，只有 Python 标准库依赖。

## 终端界面

```bash
python3 unit_converter.py
```

这是一个 `curses` 交互界面，支持倍率、几分一刀和 1 亿 Token 成本三种方向的实时换算，并可以修改充值比例，以及每百万输入、输出、缓存 Token 的官方价格。默认按 `1 元 = 1 刀站内额度`、输入 `5 刀`、输出 `30 刀`、缓存 `0.5 刀` 计算。

- `←` / `→` 或 `M`：切换换算方向
- `Tab` / `↑` / `↓`：切换输入项
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

根据 1 亿混合 Token 的实付成本反算倍率和几分一刀：

```bash
python3 unit_converter.py --token-cost 5
```

默认价格与充值比例下，结果约为 `0.05547187x`、`5.54718668 分/刀`。

如果平台充值 1 元可获得 1.2 刀站内额度：

```bash
python3 unit_converter.py --multiplier 0.12 --ratio 1.2
```

覆盖模型的官方 Token 价格，例如每百万输入、输出、缓存 Token 分别为 2、16、0.2 刀：

```bash
python3 unit_converter.py --fen 5 --token-price 2 --output-price 16 --cache-price 0.2
```

`--token-price` 继续兼容原命令，也可以写成 `--input-price`。

## 换算口径

```text
几分/刀 = 倍率 × 100 ÷ 每元获得的站内刀数
倍率 = 几分/刀 × 每元获得的站内刀数 ÷ 100
混合单价 = (输入量 × 输入价 + 输出量 × 输出价 + 缓存量 × 缓存价) ÷ 总量
1 亿混合 Token 成本（元） = 几分/刀 × 混合单价
几分/刀 = 1 亿混合 Token 成本（元） ÷ 混合单价
```

混合用量按以下样本比例归一化到 1 亿 Token：

- 输入：`12.73M`，占 `7.453961%`
- 输出：`381.68K`，占 `0.223490%`
- 缓存：`157.67M`，占 `92.322549%`

样本合计 `170.78168M` Token。使用默认价格时，混合单价约为 `0.90135780 刀/百万 Token`；`5 分/刀`对应的 1 亿混合 Token 成本约为 `4.50678902 元`。

例如默认充值比例下，`0.05x` 等价于 `5 分/刀`，`3 分/刀` 等价于 `0.03x`。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
