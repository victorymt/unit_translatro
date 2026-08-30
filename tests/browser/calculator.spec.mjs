import { expect, test } from "@playwright/test";

test("calculates defaults and switches conversion modes", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("API 已连接")).toBeVisible();
  await expect(page.locator("#input-tokens")).toHaveValue("7453961.104025");

  const defaultResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/v1/convert") && response.status() === 200,
  );
  await page.getByRole("button", { name: "计算成本" }).click();
  await defaultResponse;
  await expect(page.locator("#multiplier-result")).toHaveText("0.05x");
  await expect(page.locator("#token-cost-result")).toHaveText("4.50678902 元");
  await expect(page.locator("#comparison-body tr")).toHaveCount(5);

  await page.getByRole("button", { name: "1 亿实际支出" }).click();
  await expect(page.locator("#value")).toHaveValue("5");
  await expect(page.locator("#value-label")).toHaveText("用户自有 1 亿 Token 实际支出（元）");
  await expect(page.locator("#value-help")).toContainText("实际支付的人民币金额");
  const tokenCostResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/v1/convert") && response.status() === 200,
  );
  await page.getByRole("button", { name: "计算成本" }).click();
  await tokenCostResponse;
  await expect(page.locator("#token-cost-result")).toHaveText("5 元");
  await expect(page.locator("#result-mode")).toHaveText("固定 1 亿实际支出模式");
});

test("shows validation feedback on the matching field", async ({ page }) => {
  await page.goto("/");
  await page.locator("#value").fill("-1");
  await page.getByRole("button", { name: "计算成本" }).click();
  await expect(page.locator("#value")).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#form-error")).toContainText("不能小于 0");
});

test("keeps the page within the viewport", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "计算成本" }).click();
  await expect(page.locator("#comparison-body tr")).toHaveCount(5);
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});

test("formats decimal strings without binary floating point drift", async ({ page }) => {
  await page.goto("/");
  const values = await page.evaluate(() => ({
    rounded: displayNumber("4.506789018123456789"),
    large: displayNumber("123456789012345678901234"),
    scientific: displayNumber("1e100"),
  }));
  expect(values.rounded).toBe("4.50678902");
  expect(values.large).toBe("1.23456789e+23");
  expect(values.scientific).toBe("1e+100");
});
