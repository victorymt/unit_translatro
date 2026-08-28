const modeLabels = {
  multiplier: ["中转站倍率", "例如 0.05 表示 0.05x", "倍率模式"],
  fen: ["账号成本（分/刀）", "例如 5 表示每刀 5 分", "分/刀模式"],
  token_cost: ["1 亿 Token 实付成本（元）", "例如 5 表示实付 5 元", "Token 成本模式"],
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

function displayNumber(value, maxPlaces = 8) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return number.toFixed(maxPlaces).replace(/0+$/, "").replace(/\.$/, "") || "0";
}

function showError(error) {
  const fieldMap = {
    value: "value",
    倍率: "value",
    每刀价格: "value",
    "ChatGPT 中转 1 亿 Token 成本": "value",
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
