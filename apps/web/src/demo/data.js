export const DEMO_KEY = "scoutbite-demo-v1";

export const accounts = [
  {
    userId: 1,
    phone: "13611110001",
    password: "user123456",
    nickname: "辣妹小队长",
    role: "USER",
  },
  {
    userId: 2,
    phone: "13611110002",
    password: "user123456",
    nickname: "奶爸阿伦",
    role: "USER",
  },
  {
    userId: 3,
    phone: "13611110003",
    password: "user123456",
    nickname: "咖啡因选手",
    role: "USER",
  },
  {
    userId: 4,
    phone: "13611110004",
    password: "merchant123456",
    nickname: "蜀味里店长",
    role: "MERCHANT",
  },
  {
    userId: 99,
    phone: "13900000000",
    password: "admin123456",
    nickname: "平台审核员",
    role: "ADMIN",
  },
];

export function initialData() {
  const now = Date.now();
  const ago = (days) => new Date(now - days * 86400000).toISOString();
  const shops = [
    {
      id: 1,
      name: "蜀味里 · 巷子火锅",
      category: "HOTPOT",
      ownerId: 4,
      address: "杭州市上城区湖滨路 18 号",
      description: "巷子深处的一锅烟火气。手炒牛油锅底，和朋友慢慢吃一顿。",
      rating: 4.8,
      reviewCount: 3,
      avgPrice: 99,
      distanceMeters: 380,
      tags: ["朋友聚餐", "牛油锅底", "湖滨商圈"],
      image: "hotpot",
      lat: 30.243,
      lng: 120.153,
      status: "approved",
      approvedAt: ago(30),
    },
    {
      id: 2,
      name: "有间咖啡 · 西湖店",
      category: "COFFEE",
      ownerId: 4,
      address: "杭州市上城区南山路 106 号",
      description: "一杯手冲，一段留白。窗边有西湖，也有适合独处的下午。",
      rating: 4.7,
      reviewCount: 2,
      avgPrice: 38,
      distanceMeters: 650,
      tags: ["手冲咖啡", "安静办公", "窗边座位"],
      image: "coffee",
      lat: 30.237,
      lng: 120.149,
      status: "approved",
      approvedAt: ago(20),
    },
    {
      id: 3,
      name: "野有食 · 山野火锅",
      category: "HOTPOT",
      ownerId: 4,
      address: "杭州市上城区延安路 92 号",
      description: "当季鲜蔬与清香菌汤，也能让一顿火锅吃得轻盈。",
      rating: 4.6,
      reviewCount: 2,
      avgPrice: 86,
      distanceMeters: 920,
      tags: ["菌汤锅底", "家庭聚餐", "清淡友好"],
      image: "dining",
      lat: 30.246,
      lng: 120.159,
      status: "approved",
      approvedAt: ago(3),
    },
    {
      id: 4,
      name: "周末放映室",
      category: "ENTERTAIN",
      ownerId: 4,
      address: "杭州市上城区解放路 68 号 3F",
      description: "把两个小时留给喜欢的电影。小型私享空间，适合和朋友一起。",
      rating: 4.9,
      reviewCount: 2,
      avgPrice: 68,
      distanceMeters: 1200,
      tags: ["私人影院", "双人约会", "可预约"],
      image: "cinema",
      lat: 30.233,
      lng: 120.157,
      status: "approved",
      approvedAt: ago(35),
    },
    {
      id: 5,
      name: "木下 · 日落咖啡",
      category: "COFFEE",
      ownerId: 4,
      address: "杭州市上城区定安路 27 号",
      description: "街角的新面孔，认真做咖啡，也认真烤面包。",
      rating: 4.5,
      reviewCount: 1,
      avgPrice: 32,
      distanceMeters: 1500,
      tags: ["本周新店", "自烘焙", "街角小店"],
      image: "bakery",
      lat: 30.23,
      lng: 120.147,
      status: "approved",
      approvedAt: ago(2),
    },
    {
      id: 6,
      name: "山城老灶 · 湖滨店",
      category: "HOTPOT",
      ownerId: 8,
      address: "杭州市上城区平海路 30 号",
      description: "热闹的重庆老火锅，熟悉的辣味与市井气。",
      rating: 4.6,
      reviewCount: 2,
      avgPrice: 112,
      distanceMeters: 1800,
      tags: ["重庆风味", "深夜食堂"],
      image: "restaurant",
      lat: 30.25,
      lng: 120.167,
      status: "approved",
      approvedAt: ago(50),
    },
    {
      id: 7,
      name: "青禾 · 社区咖啡",
      category: "COFFEE",
      ownerId: 4,
      address: "杭州市上城区惠民路 15 号",
      description: "社区里的咖啡香。",
      rating: null,
      reviewCount: 0,
      avgPrice: 30,
      distanceMeters: 2100,
      tags: [],
      image: "coffee",
      lat: 30.226,
      lng: 120.16,
      status: "pending",
      approvedAt: null,
    },
  ];
  const skus = shops.flatMap((s) => [
    {
      id: s.id * 10 + 1,
      shopId: s.id,
      title:
        s.category === "HOTPOT"
          ? "招牌双人火锅套餐"
          : s.category === "COFFEE"
            ? "手冲咖啡与甜点双人套餐"
            : "双人私享观影套餐",
      price: s.id === 1 ? 19800 : s.avgPrice * 200,
      stock: 36,
      sales: 0,
      onSale: true,
    },
    {
      id: s.id * 10 + 2,
      shopId: s.id,
      title:
        s.category === "HOTPOT"
          ? "三人朋友聚餐套餐"
          : s.category === "COFFEE"
            ? "单人下午茶套餐"
            : "四人周末观影套餐",
      price: s.category === "HOTPOT" ? 26800 : 5800,
      stock: 20,
      sales: 0,
      onSale: true,
    },
  ]);
  const coupons = shops
    .filter((s) => s.status === "approved")
    .map((s) => ({
      id: s.id,
      shopId: s.id,
      title: s.category === "HOTPOT" ? "到店满减券" : "午后好时光券",
      threshold: s.category === "HOTPOT" ? 10000 : 5000,
      amount: s.category === "HOTPOT" ? 2000 : 1000,
      total: 50,
      perUserLimit: 1,
      startAt: ago(1),
      endAt: new Date(now + 30 * 86400000).toISOString(),
    }));
  const reviewTexts = [
    [
      1,
      "锅底很香，和朋友点的双人套餐刚刚好。周六晚上等位十几分钟，建议早点到。",
      5,
      4,
      4,
    ],
    [
      1,
      "牛油锅底够味，店员很热情。高峰时段店里有些热闹，聊天要大声一点。",
      5,
      3,
      4,
    ],
    [1, "湖滨逛完过来很方便，套餐份量合适，下次想试试工作日来。", 4, 4, 5],
    [2, "手冲的香气很舒服，窗边光线很好，适合带本书待一会儿。", 5, 5, 5],
    [2, "周末人有点多，不过咖啡出品稳定。靠窗座位需要等等。", 4, 3, 5],
    [3, "菌汤很清香，家里小朋友也能吃，环境整洁。", 5, 4, 5],
    [3, "新店来试试，口味偏清淡，想吃重辣的朋友可能不适合。", 4, 5, 4],
    [4, "音响不错，房间也干净，两个人看电影很自在。", 5, 5, 5],
    [4, "周末可选场次比较紧张，提前预约会更好。", 4, 4, 5],
    [5, "新开的店，面包和咖啡搭配很好，位置不多。", 4, 5, 4],
    [6, "辣度很过瘾，晚上的氛围很热闹，就是等位久一些。", 5, 3, 4],
    [6, "老火锅味道在线，份量够，环境有点吵。", 5, 3, 3],
  ];
  const reviews = reviewTexts.map(([shopId, content, taste, wait, env], i) => ({
    id: 201 + i,
    shopId,
    orderId: 300 + i,
    userId: 2 + (i % 2),
    nickname: ["周末不加班", "一口一座城", "西湖散步者"][i % 3],
    scores: { taste, wait, env },
    content,
    createdAt: ago(i % 7),
    replies:
      i === 0
        ? [
            {
              id: 1,
              content: "谢谢喜欢！周末可以早点到店，我们会继续改善等位体验。",
              nickname: "蜀味里店长",
              isMerchant: true,
            },
          ]
        : [],
  }));
  const orders = [
    {
      id: 101,
      userId: 1,
      shopId: 1,
      skuId: 11,
      priceSnapshot: 19800,
      status: "REDEEMED",
      createdAt: ago(1),
      expireAt: ago(1),
    },
    {
      id: 102,
      userId: 1,
      shopId: 2,
      skuId: 21,
      priceSnapshot: 7600,
      status: "PAID",
      createdAt: ago(0),
      expireAt: ago(0),
    },
    ...reviews.map((r, i) => ({
      id: r.orderId,
      userId: r.userId,
      shopId: r.shopId,
      skuId: r.shopId * 10 + 1,
      priceSnapshot: skus.find((s) => s.id === r.shopId * 10 + 1).price,
      status: "REVIEWED",
      createdAt: ago(i % 7),
      expireAt: ago(i % 7),
      reviewId: r.id,
    })),
  ];
  for (const s of skus)
    s.sales = orders.filter(
      (o) => o.skuId === s.id && ["REDEEMED", "REVIEWED"].includes(o.status),
    ).length;
  return {
    version: 1,
    shops,
    skus,
    coupons,
    reviews,
    orders,
    accounts: structuredClone(accounts),
    userCoupons: [],
    drafts: [],
    traces: [],
    idempotency: {},
    nextId: 1000,
  };
}
