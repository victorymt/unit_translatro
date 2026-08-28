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

  await page.getByRole("button", { name: "Token 成本" }).click();
  await expect(page.locator("#value")).toHaveValue("5");
  const tokenCostResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/v1/convert") && response.status() === 200,
  );
  await page.getByRole("button", { name: "计算成本" }).click();
  await tokenCostResponse;
  await expect(page.locator("#token-cost-result")).toHaveText("5 元");
  await expect(page.locator("#result-mode")).toHaveText("Token 成本模式");
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
