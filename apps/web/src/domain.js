export const categories = {
  HOTPOT: "火锅美食",
  COFFEE: "咖啡茶饮",
  ENTERTAIN: "休闲玩乐",
};
export const statusText = {
  CREATED: "待支付",
  PAID: "待核销",
  REDEEMED: "待评价",
  REVIEWED: "已完成",
  CANCELLED_TIMEOUT: "超时关闭",
  CANCELLED_USER: "已取消",
  REFUNDED: "已退款",
  UNUSED: "可使用",
  FROZEN: "待支付占用",
  USED: "已使用",
};
export const money = (value) =>
  value == null ? "—" : (Number(value) / 100).toFixed(2).replace(/\.00$/, "");
export const distance = (value) =>
  value == null
    ? "距离待确认"
    : Number(value) >= 1000
      ? `${(value / 1000).toFixed(1)} km`
      : `${Math.round(value)} m`;
export const dateTime = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
};
const categoryImage = {
  HOTPOT: "hotpot",
  COFFEE: "coffee",
  ENTERTAIN: "cinema",
};
export const shopImage = (shop) =>
  `/images/${(shop?.image || categoryImage[shop?.category]) === "hotpot" ? "hotpot-demo" : shop?.image || categoryImage[shop?.category] || "restaurant"}.jpg`;
export const isNewShop = (shop) =>
  shop?.approvedAt && Date.parse(shop.approvedAt) > Date.now() - 7 * 86400000;
export const averageScore = (reviews) =>
  reviews.length
    ? (
        reviews.reduce(
          (sum, r) =>
            sum +
            Object.values(r.scores || {}).reduce((a, b) => a + Number(b), 0) /
              3,
          0,
        ) / reviews.length
      ).toFixed(1)
    : null;
export function evidenceRef(value, fallbackShopId) {
  const match = String(value).match(/^ev-(\d+)-(\d+)$/);
  return match
    ? { shopId: Number(match[1]), reviewId: Number(match[2]) }
    : {
        shopId: fallbackShopId,
        reviewId: Number(String(value).replace(/^review-/, "")),
      };
}

export function chooseMerchantShop(shops, requestedId = null) {
  const owned = shops.find((shop) => shop.id === Number(requestedId));
  if (owned) return owned.id;
  const candidates = [...shops]
    .filter((shop) => shop.status === "approved")
    .sort((a, b) => (b.reviewCount || 0) - (a.reviewCount || 0));
  return candidates[0]?.id ?? shops[0]?.id ?? null;
}
