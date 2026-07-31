# 倍率换算器

用于换算 GPT 账号的“几分 1 刀”成本与中转站倍率，只有 Python 标准库依赖。

## 终端界面

```bash
python3 unit_converter.py
```

这是一个 `curses` 交互界面，支持两个方向的实时换算，并可以修改充值比例。默认按 `1 元 = 1 刀站内额度` 计算。

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

如果平台充值 1 元可获得 1.2 刀站内额度：

```bash
python3 unit_converter.py --multiplier 0.12 --ratio 1.2
```

## 换算口径

```text
几分/刀 = 倍率 × 100 ÷ 每元获得的站内刀数
倍率 = 几分/刀 × 每元获得的站内刀数 ÷ 100
```

例如默认充值比例下，`0.05x` 等价于 `5 分/刀`，`3 分/刀` 等价于 `0.03x`。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
