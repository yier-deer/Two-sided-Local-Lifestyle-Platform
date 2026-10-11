import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const screenshots = fileURLToPath(
  new URL("../../../../docs/screenshots/", import.meta.url),
);
test.beforeEach(async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.__errors = errors;
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "附近值得去" })).toBeVisible();
});
test.afterEach(async ({ page }) => {
  expect(page.__errors, "浏览器不能出现脚本错误").toEqual([]);
});
async function shot(page, name) {
  await mkdir(screenshots, { recursive: true });
  await page.locator(".toast-stack").evaluate((element) => {
    element.style.visibility = "hidden";
  });
  await page.screenshot({ path: `${screenshots}/${name}.png`, fullPage: true });
  await page.locator(".toast-stack").evaluate((element) => {
    element.style.visibility = "";
  });
}

test("discovery search, categories, local images and recommendation evidence are usable", async ({
  page,
}) => {
  await expect(page.locator(".shop-tile")).toHaveCount(6);
  await expect
    .poll(() =>
      page
        .locator("img")
        .evaluateAll((images) =>
          images.every((i) => i.complete && i.naturalWidth > 0),
        ),
    )
    .toBe(true);
  await shot(page, "discovery-desktop");
  await page.getByRole("button", { name: "咖啡茶饮", exact: true }).click();
  await expect(page.locator(".shop-tile")).toHaveCount(2);
  await page.getByLabel("搜索店铺").fill("查无此店");
  await page.getByRole("button", { name: "发现", exact: true }).click();
  await expect(
    page.getByText("还没找到合适的店", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "查看全部", exact: true }).click();
  await expect(page.locator(".shop-tile")).toHaveCount(6);
  await page.getByRole("button", { name: "附近示意图" }).click();
  await expect(page.getByText("附近坐标示意 · 非街道地图")).toBeVisible();
  await page.getByRole("link", { name: "AI 探店助手 AI", exact: true }).click();
  await page.getByRole("button", { name: /朋友聚餐，热辣一点/ }).click();
  await expect(page.locator(".agent-shop-card")).toHaveCount(3);
  await expect(
    page.getByText("本地示例 · 未调用模型", { exact: true }),
  ).toBeVisible();
  await page.locator(".evidence-buttons button").first().click();
  await expect(
    page.getByRole("heading", { name: "推荐依据，原文在这里。" }),
  ).toBeVisible();
  await expect(page.locator(".evidence-card")).toContainText("已消费评价");
  await page.getByLabel("关闭评价证据").click();
  await shot(page, "agent-evidence");
});

test("coupon checkout, payment, redemption, edited review and merchant reply form a complete journey", async ({
  page,
}) => {
  await page.goto("/#/shop/1");
  await expect(
    page.getByRole("heading", { name: "蜀味里 · 巷子火锅", exact: true }),
  ).toBeVisible();
  await shot(page, "shop-detail");
  await page.getByRole("button", { name: "领取", exact: true }).click();
  await expect(page.getByRole("button", { name: "已领取" })).toBeDisabled();
  await page
    .getByRole("button", { name: "立即购买", exact: true })
    .first()
    .click();
  await page.getByLabel("使用优惠券").selectOption({ index: 1 });
  await expect(page.locator(".checkout-summary")).toContainText("178");
  await page.getByRole("button", { name: "提交订单", exact: true }).click();
  await expect(page.locator(".order-card")).toHaveCount(1);
  await expect(page.locator(".order-card")).toContainText("¥178");
  await page.getByRole("button", { name: "模拟支付", exact: true }).click();
  await page.getByRole("button", { name: /^待核销/ }).click();
  const newest = page.locator(".order-card").first();
  await newest.getByRole("button", { name: "到店核销", exact: true }).click();
  await page.getByRole("button", { name: "确认核销", exact: true }).click();
  await page.getByRole("button", { name: /^待评价/ }).click();
  await page
    .locator(".order-card")
    .first()
    .getByRole("link", { name: /写评价/ })
    .click();
  await page.getByLabel("体验笔记").fill("到店等位约十分钟，套餐份量合适。");
  await page.getByRole("button", { name: "帮我整理成评价草稿" }).click();
  const published =
    "这是答辩中核对并修改后的正文，套餐份量合适，等位约十分钟。";
  await page.getByLabel("评价正文").fill(published);
  await expect(
    page.getByRole("button", { name: "确认，发布我的评价" }),
  ).toBeDisabled();
  await page.getByLabel("确认评价真实").check();
  await page.getByRole("button", { name: "确认，发布我的评价" }).click();
  await expect(
    page.getByRole("heading", { name: "谢谢你，认真分享这一次。" }),
  ).toBeVisible();
  await page.getByRole("link", { name: /查看我的评价/ }).click();
  await expect(page.locator(".review-content").first()).toHaveText(published);
  await page.getByRole("button", { name: "进入商家中心" }).click();
  await expect(
    page.getByRole("heading", { name: "你好，蜀味里店长。" }),
  ).toBeVisible();
  await shot(page, "merchant-dashboard");
  await page.getByRole("link", { name: "评价管理", exact: true }).click();
  const review = page.locator(".review-item").filter({ hasText: published });
  const response = "谢谢认真反馈，我们会继续改善周末的等位体验。";
  await review.locator("textarea").fill(response);
  await review.getByRole("button", { name: "发布商家回复" }).click();
  await expect(review.locator(".merchant-reply")).toContainText(response);
  await page.getByRole("button", { name: "返回用户端" }).click();
  await page.goto("/#/shop/1");
  await expect(
    page
      .locator(".review-item")
      .filter({ hasText: published })
      .locator(".merchant-reply"),
  ).toContainText(response);
  await page.reload();
  await expect(page.locator(".review-content").first()).toHaveText(published);
});

test("merchant catalog, merchant redemption and analysis are actionable", async ({
  page,
}) => {
  await page.getByRole("button", { name: "进入商家中心" }).click();
  await page.getByRole("link", { name: "套餐与优惠券", exact: true }).click();
  await page.getByRole("button", { name: "编辑", exact: true }).first().click();
  await page.getByLabel("供给名称").fill("答辩双人套餐");
  await page.getByLabel("套餐价格（元）").fill("188");
  await page.getByLabel("可售库存（份）").fill("8");
  await page.getByRole("button", { name: "确认保存", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /答辩双人套餐/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^优惠券/ }).click();
  await page.getByRole("button", { name: "创建优惠券" }).click();
  await page.getByLabel("供给名称").fill("答辩专属满减券");
  await page.getByLabel("使用门槛（元）").fill("100");
  await page.getByLabel("减免金额（元）").fill("15");
  await page.getByLabel("发行总量（张）").fill("30");
  await page.getByRole("button", { name: "确认保存", exact: true }).click();
  await expect(
    page.locator(".coupon-ticket").filter({ hasText: "答辩专属满减券" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "订单核销", exact: true }).click();
  await page.getByRole("button", { name: "待核销", exact: true }).click();
  await page
    .getByRole("button", { name: "确认核销", exact: true })
    .first()
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认核销", exact: true })
    .click();
  await expect(
    page.getByText("这里暂时没有订单", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "AI 经营助手 AI", exact: true }).click();
  await page.getByRole("button", { name: "开始分析这家店" }).click();
  await expect(page.locator(".analysis-layer")).toHaveCount(3);
  await expect(page.locator(".analysis-layer.hypothesis")).toContainText(
    "可能",
  );
  await shot(page, "merchant-analysis");
});

test("administrator approval changes consumer visibility and role guards protect management", async ({
  page,
}) => {
  await page.goto("/#/merchant/catalog");
  await expect(
    page.getByRole("heading", { name: "欢迎回到探店雷达" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "店铺审核", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "让靠谱的门店，被看见。" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "青禾 · 社区咖啡" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "通过审核", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "通过审核", exact: true })
    .click();
  await expect(
    page.getByText("当前队列已处理完毕", { exact: true }),
  ).toBeVisible();
  await page.goto("/#/login");
  await page.getByRole("button", { name: "体验用户", exact: true }).click();
  await expect(page.locator(".shop-tile")).toHaveCount(7);
  await page.getByLabel("搜索店铺").fill("青禾");
  await page.getByRole("button", { name: "发现", exact: true }).click();
  await expect(page.locator(".shop-tile")).toHaveCount(1);
  await expect(page.locator(".shop-tile")).toContainText("青禾");
});

test("mobile pages and checkout fit viewport, navigation works", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await shot(page, "discovery-mobile");
  await page.getByLabel("打开导航").click();
  await page.getByRole("link", { name: "我的订单", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "我的到店计划" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await page.goto("/#/shop/1");
  await page
    .getByRole("button", { name: "立即购买", exact: true })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
});

test("real-service errors remain errors and switching modes clears identity", async ({
  page,
}) => {
  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        code: 50000,
        message: "业务服务尚未启动，请稍后重试",
      }),
    }),
  );
  await page.getByRole("button", { name: "本地演示", exact: true }).click();
  await page.getByRole("button", { name: "切换模式", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "真实服务", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".account-name")).toHaveCount(0);
  await page.getByRole("button", { name: "体验用户", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("业务服务尚未启动");
  await expect(page).toHaveURL(/login/);
  await page.getByRole("button", { name: "真实服务", exact: true }).click();
  await page.getByRole("button", { name: "切换模式", exact: true }).click();
  await expect(page.locator(".shop-tile")).toHaveCount(6);
});

test("permission-denied location keeps loaded shops visible", async ({
  page,
}) => {
  await page.evaluate(() => {
    navigator.geolocation.getCurrentPosition = (_, failure) =>
      failure({ code: 1, message: "denied" });
  });
  await page.getByRole("button", { name: "使用我的位置" }).click();
  await expect(page.locator(".shop-tile")).toHaveCount(6);
  await expect(page.locator(".toast").last()).toContainText("定位未授权");
});

test("a late real login response cannot replace the new demo identity", async ({
  page,
}) => {
  let complete;
  const gate = new Promise((resolve) => {
    complete = resolve;
  });
  await page.route("**/api/auth/login", async (route) => {
    await gate;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: {
          userId: 444,
          role: "MERCHANT",
          token: "real-late-jwt",
          nickname: "旧真实商家",
        },
      }),
    });
  });
  await page.getByRole("button", { name: "本地演示", exact: true }).click();
  await page.getByRole("button", { name: "切换模式", exact: true }).click();
  const requested = page.waitForRequest("**/api/auth/login");
  await page.getByRole("button", { name: "体验商家", exact: true }).click();
  await requested;
  await page.getByRole("button", { name: "真实服务", exact: true }).click();
  await page.getByRole("button", { name: "切换模式", exact: true }).click();
  const response = page.waitForResponse("**/api/auth/login");
  complete();
  await response;
  await expect(page.getByRole("heading", { name: "附近值得去" })).toBeVisible();
  await expect(page.locator(".account-name")).toHaveText("辣妹小队长");
  await expect
    .poll(() =>
      page.evaluate(
        () => JSON.parse(localStorage.getItem("scoutbite-session")).token,
      ),
    )
    .toBe("demo-1");
});

test("real community posts have content and no broken shop links", async ({
  page,
}) => {
  await page.route("**/api/feed?*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: [
          {
            contentId: 10,
            contentType: "POST",
            shopId: null,
            shopName: null,
            content: { text: "西湖散步之后，给自己留一杯咖啡的时间。" },
            score: 3,
          },
        ],
      }),
    }),
  );
  await page.getByRole("button", { name: "本地演示", exact: true }).click();
  await page.getByRole("button", { name: "切换模式", exact: true }).click();
  await page.goto("/#/feed");
  await expect(
    page.getByRole("heading", { name: "社区生活分享" }),
  ).toBeVisible();
  await expect(page.locator(".note-card")).toContainText("西湖散步之后");
  await expect(page.locator(".note-card a")).toHaveCount(0);
});

test("all demonstration views fit mobile and small desktop viewports", async ({
  page,
}) => {
  for (const width of [390, 1024]) {
    await page.setViewportSize({ width, height: 844 });
    for (const path of [
      "/discover",
      "/feed",
      "/agent",
      "/orders",
      "/orders/101/review",
      "/shop/1",
      "/demo",
      "/login",
    ]) {
      await page.goto("/#" + path);
      await expect
        .poll(
          () =>
            page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth,
            ),
          `overflow ${path} @${width}`,
        )
        .toBe(true);
    }
    await page.goto("/#/login");
    await page.getByRole("button", { name: "体验商家", exact: true }).click();
    for (const path of [
      "/merchant",
      "/merchant/catalog",
      "/merchant/orders",
      "/merchant/reviews",
      "/merchant/ai",
      "/my",
      "/join",
    ]) {
      await page.goto("/#" + path);
      await expect
        .poll(
          () =>
            page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth,
            ),
          `overflow ${path} @${width}`,
        )
        .toBe(true);
    }
    await page.goto("/#/login");
    await page.getByRole("button", { name: "体验用户", exact: true }).click();
  }
});

test("slow merchant analysis locks the selected store until its result arrives", async ({
  page,
}) => {
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: {
          userId: 4,
          role: "MERCHANT",
          nickname: "演示店长",
          token: "test-only-jwt",
        },
      }),
    }),
  );
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: { userId: 4, role: "MERCHANT", nickname: "演示店长" },
      }),
    }),
  );
  await page.route("**/api/merchant/shops", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: [
          { id: 1, name: "门店甲", status: "approved" },
          { id: 2, name: "门店乙", status: "approved" },
        ],
      }),
    }),
  );
  let complete;
  const gate = new Promise((resolve) => {
    complete = resolve;
  });
  await page.route("**/api/agent/merchant/analyze", async (route) => {
    await gate;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: {
          observations: ["门店甲的订单数据"],
          hypotheses: ["可能与时段有关"],
          suggestions: ["记录高峰时段"],
        },
      }),
    });
  });
  await page.getByRole("button", { name: "本地演示", exact: true }).click();
  await page.getByRole("button", { name: "切换模式", exact: true }).click();
  await page.getByRole("button", { name: "体验商家", exact: true }).click();
  await page.goto("/#/merchant/ai");
  await expect(page.getByRole("combobox")).toHaveValue("1");
  const request = page.waitForRequest("**/api/agent/merchant/analyze");
  await page.getByRole("button", { name: "开始分析这家店" }).click();
  await request;
  await expect(page.getByRole("combobox")).toBeDisabled();
  complete();
  await expect(page.locator(".analysis-layer").first()).toContainText("门店甲");
  await expect(page.getByRole("combobox")).toBeEnabled();
});

test("slow merchant reply cannot reenable another reply and create duplicate posts", async ({
  page,
}) => {
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: {
          userId: 4,
          role: "MERCHANT",
          nickname: "演示店长",
          token: "test-only-jwt",
        },
      }),
    }),
  );
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: { userId: 4, role: "MERCHANT", nickname: "演示店长" },
      }),
    }),
  );
  await page.route("**/api/merchant/shops", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: [{ id: 1, name: "门店甲", status: "approved" }],
      }),
    }),
  );
  await page.route("**/api/shops/1/reviews", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        data: [201, 202].map((id) => ({
          id,
          nickname: "顾客",
          content: "认真反馈" + id,
          scores: { taste: 4, wait: 4, env: 4 },
          replies: [],
        })),
      }),
    }),
  );
  let complete,
    posts = 0;
  const gate = new Promise((resolve) => {
    complete = resolve;
  });
  await page.route("**/api/reviews/*/replies", async (route) => {
    posts++;
    await gate;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ code: 0, data: { id: 1 } }),
    });
  });
  await page.getByRole("button", { name: "本地演示", exact: true }).click();
  await page.getByRole("button", { name: "切换模式", exact: true }).click();
  await page.getByRole("button", { name: "体验商家", exact: true }).click();
  await page.goto("/#/merchant/reviews");
  await page.getByLabel("回复评价201").fill("谢谢反馈A");
  await page.getByLabel("回复评价202").fill("谢谢反馈B");
  await page
    .locator("[data-testid=merchant-review-201]")
    .getByRole("button", { name: "发布商家回复" })
    .click();
  await expect(
    page
      .locator("[data-testid=merchant-review-202]")
      .getByRole("button", { name: "发布商家回复" }),
  ).toBeDisabled();
  await expect(page.getByLabel("评价门店")).toBeDisabled();
  complete();
  await expect(page.locator(".toast").last()).toContainText("回复已发布");
  expect(posts).toBe(1);
});
