import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

test.describe("real PostgreSQL/Redis/Agent integration", () => {
  test.skip(
    process.env.SCOUTBITE_LIVE_TESTS !== "1",
    "Requires explicitly enabled local real services.",
  );
  test.setTimeout(180000);
  const shopApi = "http://127.0.0.1:8081";
  let merchantToken, shopId, sku, coupon;
  const run = Date.now().toString(36);
  async function call(request, path, token, method = "GET", data) {
    const response = await request.fetch(shopApi + path, {
      method,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      data,
    });
    const body = await response.json();
    expect(body.code, `${method} ${path}: ${body.message}`).toBe(0);
    return body.data;
  }
  test.beforeAll(async ({ request }) => {
    const auth = await call(request, "/api/auth/login", null, "POST", {
      phone: "13611110004",
      password: "merchant123456",
    });
    merchantToken = auth.token;
    const shops = await call(request, "/api/merchant/shops", merchantToken);
    shopId =
      shops.find((s) => s.id === 1 && s.status === "approved")?.id ||
      shops.find((s) => s.status === "approved")?.id;
    expect(shopId).toBeTruthy();
    sku = await call(request, "/api/merchant/skus", merchantToken, "POST", {
      shopId,
      title: `真实浏览器双人套餐 ${run}`,
      price: 19800,
      stock: 10,
    });
    coupon = await call(
      request,
      "/api/merchant/coupons",
      merchantToken,
      "POST",
      {
        shopId,
        title: `浏览器满减券 ${run}`,
        threshold: 10000,
        amount: 2000,
        total: 20,
      },
    );
  });
  test("real user checkout, edited Agent review and real merchant reply", async ({
    page,
    request,
  }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await page.getByRole("button", { name: "本地演示", exact: true }).click();
    await page.getByRole("button", { name: "切换模式", exact: true }).click();
    await page.getByRole("button", { name: "体验用户", exact: true }).click();
    await expect(page.locator(".account-name")).toHaveText("辣妹小队长");
    await expect(
      page.getByRole("button", { name: "真实服务", exact: true }),
    ).toBeVisible();
    await expect(page.locator(".shop-tile").first()).toBeVisible();
    await page.goto(`/#/shop/${shopId}`);
    const ticket = page
      .locator(".coupon-ticket")
      .filter({ hasText: coupon.title });
    await ticket.getByRole("button", { name: "领取", exact: true }).click();
    await expect(
      ticket.getByRole("button", { name: "已领取", exact: true }),
    ).toBeDisabled();
    await page
      .locator(".sku-item")
      .filter({ hasText: sku.title })
      .getByRole("button", { name: "立即购买", exact: true })
      .click();
    await page
      .getByLabel("使用优惠券")
      .selectOption({ label: `${coupon.title} · 满 100 减 20` });
    await expect(page.locator(".checkout-summary")).toContainText("178");
    await page.getByRole("button", { name: "提交订单", exact: true }).click();
    await expect(
      page.locator(".order-card").filter({ hasText: sku.title }),
    ).toContainText("¥178");
    await page
      .locator(".order-card")
      .filter({ hasText: sku.title })
      .getByRole("button", { name: "模拟支付", exact: true })
      .click();
    const userSession = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("scoutbite-session")),
    );
    const orders = await call(request, "/api/orders", userSession.token);
    const order = orders.find((o) => o.skuId === sku.id);
    expect(order.status).toBe("PAID");
    await page.goto("/#/login");
    await page.getByRole("button", { name: "体验商家", exact: true }).click();
    await expect(page.locator(".account-name")).toHaveText("蜀味里店长");
    await page.goto("/#/merchant/orders");
    await page.getByLabel("搜索订单").fill(String(order.id));
    await page.getByRole("button", { name: "确认核销", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "确认核销", exact: true })
      .click();
    await expect(
      page.locator("tbody tr").filter({ hasText: sku.title }),
    ).toContainText("待评价");
    const redeemedOrders = await call(
      request,
      "/api/orders",
      userSession.token,
    );
    expect(redeemedOrders.find((o) => o.id === order.id).status).toBe(
      "REDEEMED",
    );
    await page.goto("/#/login");
    await page.getByRole("button", { name: "体验用户", exact: true }).click();
    await expect(page.locator(".account-name")).toHaveText("辣妹小队长");
    await page.goto(`/#/orders/${order.id}/review`);
    await page.getByLabel("体验笔记").fill("到店等位十分钟，套餐份量合适。");
    await page.getByRole("button", { name: "帮我整理成评价草稿" }).click();
    await expect(page.getByLabel("评价正文")).toBeVisible({ timeout: 70000 });
    const edited = `真实服务核对后的评价 ${run}：到店等位十分钟，套餐份量合适。`;
    await page.getByLabel("评价正文").fill(edited);
    await page.getByLabel("确认评价真实").check();
    await page.getByRole("button", { name: "确认，发布我的评价" }).click();
    await expect(
      page.getByRole("heading", { name: "谢谢你，认真分享这一次。" }),
    ).toBeVisible();
    await page.getByRole("link", { name: /查看我的评价/ }).click();
    await expect(
      page.locator(".review-item").filter({ hasText: edited }),
    ).toBeVisible();
    await page.goto("/#/login");
    await page.getByRole("button", { name: "体验商家", exact: true }).click();
    await expect(page.locator(".account-name")).toHaveText("蜀味里店长");
    await page.goto("/#/merchant/reviews");
    await page.getByLabel("评价门店").selectOption(String(shopId));
    const review = page.locator(".review-item").filter({ hasText: edited });
    await review
      .locator("textarea")
      .fill("已收到你的真实反馈，我们会继续改善等位安排。");
    await review.getByRole("button", { name: "发布商家回复" }).click();
    await expect(review.locator(".merchant-reply")).toContainText("商家");
    const apiOrders = await call(request, "/api/orders", userSession.token);
    expect(apiOrders.find((o) => o.id === order.id).status).toBe("REVIEWED");
    await mkdir(
      fileURLToPath(new URL("../../../../docs/screenshots/", import.meta.url)),
      { recursive: true },
    );
    await page.screenshot({
      path: fileURLToPath(
        new URL(
          "../../../../docs/screenshots/live-merchant-reply.png",
          import.meta.url,
        ),
      ),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
  test("real recommendation evidence and three-layer merchant analysis", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "本地演示", exact: true }).click();
    await page.getByRole("button", { name: "切换模式", exact: true }).click();
    await page.getByRole("button", { name: "体验用户", exact: true }).click();
    await expect(page.locator(".account-name")).toHaveText("辣妹小队长");
    await page.goto("/#/agent");
    await page.getByRole("button", { name: /朋友聚餐，热辣一点/ }).click();
    await expect(page.locator(".agent-shop-card").first()).toBeVisible({
      timeout: 70000,
    });
    await page.locator(".evidence-buttons button").first().click();
    await expect(
      page.getByRole("heading", { name: "推荐依据，原文在这里。" }),
    ).toBeVisible();
    await page.getByLabel("关闭评价证据").click();
    await page.goto("/#/login");
    await page.getByRole("button", { name: "体验商家", exact: true }).click();
    await expect(page.locator(".account-name")).toHaveText("蜀味里店长");
    await page.goto("/#/merchant/ai");
    await page.getByRole("combobox").selectOption(String(shopId));
    await page.getByRole("button", { name: "开始分析这家店" }).click();
    await expect(page.locator(".analysis-layer")).toHaveCount(3, {
      timeout: 70000,
    });
    await page.screenshot({
      path: fileURLToPath(
        new URL(
          "../../../../docs/screenshots/live-merchant-analysis.png",
          import.meta.url,
        ),
      ),
      fullPage: true,
    });
  });
});
