const modeLabels = {
  multiplier: ["中转站倍率", "例如 0.05 表示 0.05x", "倍率模式"],
  fen: ["账号成本（分/刀）", "例如 5 表示每刀 5 分", "分/刀模式"],
  token_cost: [
    "用户自有 1 亿 Token 实际支出（元）",
    "输入你实际支付的人民币金额；用量配比会归一化到 1 亿",
    "固定 1 亿实际支出模式",
  ],
};
const modeDefaults = {
  multiplier: "0.05",
  fen: "5",
  token_cost: "5",
};

const $ = (id) => document.getElementById(id);
let selectedMode = "multiplier";

function setMode(mode) {
  selectedMode = mode;
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  const [label, help, resultMode] = modeLabels[mode];
  $("value").value = modeDefaults[mode];
  $("value-label").textContent = label;
  $("value-help").textContent = help;
  $("result-mode").textContent = resultMode;
}

function value(id) {
  return $(id).value.trim();
}

function payload() {
  return {
    mode: selectedMode,
    value: value("value"),
    balance_per_yuan: value("balance-per-yuan"),
    usd_cny_rate: value("usd-cny-rate"),
    usage: {
      input_tokens: value("input-tokens"),
      output_tokens: value("output-tokens"),
      cached_tokens: value("cached-tokens"),
    },
    chatgpt_profile: {
      name: "ChatGPT 中转",
      provider: "ChatGPT relay",
      model: "custom",
      input_price: value("input-price"),
      output_price: value("output-price"),
      cached_price: value("cached-price"),
    },
  };
}

function clearErrors() {
  document.querySelectorAll("input[aria-invalid]").forEach((input) => input.removeAttribute("aria-invalid"));
  $("form-error").textContent = "";
}

function stripLeadingZeros(value) {
  return value.replace(/^0+/, "") || "0";
}

function incrementDigits(value) {
  const digits = value.split("");
  let carry = 1;
  for (let index = digits.length - 1; index >= 0 && carry; index -= 1) {
    if (digits[index] === "9") {
      digits[index] = "0";
    } else {
      digits[index] = String.fromCharCode(digits[index].charCodeAt(0) + 1);
      carry = 0;
    }
  }
  return carry ? `1${digits.join("")}` : digits.join("");
}

function roundDecimalParts(integerPart, fractionPart, maxPlaces) {
  if (fractionPart.length <= maxPlaces) {
    return {
      integerPart,
      fractionPart: fractionPart.replace(/0+$/, ""),
    };
  }
  let keptFraction = fractionPart.slice(0, maxPlaces);
  let roundedInteger = integerPart;
  if (fractionPart[maxPlaces] >= "5") {
    const combined = incrementDigits(`${integerPart}${keptFraction.padEnd(maxPlaces, "0")}`);
    const split = Math.max(1, combined.length - maxPlaces);
    roundedInteger = combined.slice(0, split);
    keptFraction = combined.slice(split);
  }
  return {
    integerPart: stripLeadingZeros(roundedInteger),
    fractionPart: keptFraction.replace(/0+$/, ""),
  };
}

function scientificNumber(sign, integerPart, fractionPart, maxPlaces) {
  let exponent = integerPart.length - 1;
  const rounded = roundDecimalParts(
    integerPart[0],
    `${integerPart.slice(1)}${fractionPart}`,
    maxPlaces,
  );
  let mantissaInteger = rounded.integerPart;
  let mantissaFraction = rounded.fractionPart;
  if (mantissaInteger.length > 1) {
    exponent += 1;
    mantissaInteger = "1";
    mantissaFraction = "";
  }
  const mantissa = mantissaFraction
    ? `${mantissaInteger}.${mantissaFraction}`
    : mantissaInteger;
  return `${sign}${mantissa}e${exponent >= 0 ? "+" : ""}${exponent}`;
}

function displayNumber(value, maxPlaces = 8) {
  const original = String(value);
  const text = original.trim();
  const match = text.match(/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
  if (!match) return original;
  const places = Math.max(0, Math.floor(maxPlaces));
  const sign = match[1] === "-" ? "-" : "";
  const integerInput = match[2];
  const fractionInput = match[3] || "";
  const exponent = match[4] ? parseInt(match[4], 10) : 0;
  const rawDigits = `${integerInput}${fractionInput}`;
  const firstNonZero = rawDigits.search(/[1-9]/);
  if (firstNonZero < 0) return "0";
  const digits = rawDigits.slice(firstNonZero);
  const decimalPosition = integerInput.length + exponent - firstNonZero;
  let integerPart;
  let fractionPart;
  if (decimalPosition <= 0) {
    integerPart = "0";
    fractionPart = `${"0".repeat(-decimalPosition)}${digits}`;
  } else if (decimalPosition >= digits.length) {
    integerPart = `${digits}${"0".repeat(decimalPosition - digits.length)}`;
    fractionPart = "";
  } else {
    integerPart = digits.slice(0, decimalPosition);
    fractionPart = digits.slice(decimalPosition);
  }
  const rounded = roundDecimalParts(integerPart, fractionPart, places);
  if (rounded.integerPart.length > 21) {
    return scientificNumber(sign, rounded.integerPart, rounded.fractionPart, places);
  }
  const result = rounded.fractionPart
    ? `${rounded.integerPart}.${rounded.fractionPart}`
    : rounded.integerPart;
  return result === "0" ? "0" : `${sign}${result}`;
}

function showError(error) {
  const fieldMap = {
    value: "value",
    倍率: "value",
    每刀价格: "value",
    "用户自有 1 亿 Token 实际支出（元）": "value",
    充值比例: "balance-per-yuan",
    "美元兑人民币汇率": "usd-cny-rate",
    usage: "input-tokens",
    "输入 Token 数量": "input-tokens",
    "输出 Token 数量": "output-tokens",
    "缓存 Token 数量": "cached-tokens",
    chatgpt_profile: "input-price",
    "输入 Token 官方价": "input-price",
    "输出 Token 官方价": "output-price",
    "缓存 Token 官方价": "cached-price",
  };
  const input = $(fieldMap[error.field]);
  if (input) {
    input.setAttribute("aria-invalid", "true");
    input.focus();
  }
  $("form-error").textContent = error.message || "请求失败，请检查输入";
}

function render(result) {
  $("multiplier-result").textContent = `${displayNumber(result.multiplier)}x`;
  $("fen-result").textContent = `${displayNumber(result.fen_per_dollar)} 分/刀`;
  $("token-cost-result-label").textContent = result.mode === "token_cost"
    ? "1 亿实际支出"
    : "当前用量成本";
  $("token-cost-result").textContent = `${displayNumber(result.token_cost_yuan)} 元`;
  $("official-cost-result").textContent = `${displayNumber(result.official_cost_usd)} USD`;
  const rows = result.comparison || [];
  $("comparison-count").textContent = `${rows.length} 个渠道`;
  $("comparison-body").innerHTML = rows.map((row, index) => `
    <tr class="${index === 0 ? "row-primary" : ""}">
      <td>${escapeHtml(row.name)}</td>
      <td>${row.usd == null ? "基准" : escapeHtml(displayNumber(row.usd))}</td>
      <td>${escapeHtml(displayNumber(row.yuan))}</td>
      <td>${row.relative_to_chatgpt == null ? "基准" : `${escapeHtml(displayNumber(row.relative_to_chatgpt))}x`}</td>
    </tr>`).join("");
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[character]));
}

async function submit(event) {
  event.preventDefault();
  clearErrors();
  const button = document.querySelector(".submit-button");
  button.disabled = true;
  button.textContent = "计算中...";
  try {
    const response = await fetch("/api/v1/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    const body = await response.json();
    if (!response.ok) throw body.error || { message: "请求失败" };
    render(body);
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
    button.textContent = "计算成本";
  }
}

document.querySelectorAll(".mode-button").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});
$("conversion-form").addEventListener("submit", submit);
setMode(selectedMode);

fetch("/api/v1/health")
  .then((response) => {
    if (!response.ok) throw new Error("health check failed");
    $("api-status").textContent = "API 已连接";
    $("api-status").dataset.state = "ready";
  })
  .catch(() => {
    $("api-status").textContent = "API 不可用";
    $("api-status").dataset.state = "error";
  });
