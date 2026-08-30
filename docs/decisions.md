# 架构决策记录 ADR

先写问题和选项。起仓库时不得无理由推翻。想改，先改本文件。

## ADR-001 产品名与定位

决策：对外叫探店雷达 ScoutBite，不做「缩小版大众点评」叙事。
理由：面试第一句要像独立产品。点评是参照物，不是品牌。
替代：继续叫点评+agent。拒绝，辨识度差。

## ADR-002 前后端分离

决策：`apps/web`（Vue 3 + Vite）只通过 HTTP JSON 访问 `services/shop-api`。不加服务端模板，不把 Vue 塞进 Spring 静态资源当长期方案（开发期代理即可）。
理由：
1. 职责清楚：前端管交互，后端管状态机和权限。
2. 后端岗演示可以只用 Swagger，前端挂了系统仍可验收。
3. 和同事对接的真实工作方式就是接口合同。
你要会的：JWT 放 `Authorization: Bearer`、CORS、401/403、错误码、字段名。
你不必手写的：样式、地图动画、组件库主题。交给 AI，但你要能讲每个按钮打了哪个接口。

## ADR-003 主站语言 Java 21 + Spring Boot 3

决策：业务主站用 Java 21。
理由：
1. 国内后端面试主栈，事务、鉴权、状态机最好讲。
2. 21 是当前 LTS，新项目没有理由停在 17。
3. 21 的 Record、模式匹配、虚拟线程你要认识；10 天里虚拟线程不是深度点，不要为了用而用。
替代：纯 Python 一体。拒绝作为主方案——交易和权限的面试表达会弱。Agent 才用 Python。

## ADR-004 Agent 独立进程，语言 Python

决策：`services/agent-api` 用 Python 3.11+ / FastAPI / LangGraph。只调 Java 的 `/internal` 与门面转发，不直连改库存。
理由：工具编排、结构化输出、评测脚本在 Python 里改得快。
你现在只需要建立这个心智模型：

```
用户说话
  → Java 验登录，把身份和坐标转给 Python
  → Python 按固定步骤调用 Java 内部接口拿事实
  → 模型只在「事实」上做对比或写草稿
  → 若要发布评价，再调回 Java 写库
```

还不会 Python / LangGraph 没关系。会从「什么是一次 HTTP 工具调用」开始带。今天禁止先写 prompt。

## ADR-005 数据库 PostgreSQL

决策：主库 PostgreSQL。后续评论语义检索预留 `pgvector`，先不用向量。
理由：你明确要 AI 友好的向量能力，且不想为向量再引一套库。结构化检索（距离、品类、状态）仍然走普通 SQL，这是正确的——向量不是附近 3km 的正确答案。
替代：MySQL。事务和八股更贴国内 Java 口述，但没有好用的向量类型，后面为语义检索换库成本高。按你的目标锁 PostgreSQL，面试用对比句讲即可。
价格：一律用整数分，不用浮点。

## ADR-006 缓存与延迟任务用 Redis

决策：券热点库存、订单延迟关单用 Redis。不上 Kafka / RabbitMQ。
理由：一人 10 天，Redis 能演示原子扣减和延迟队列。简历里对比「生产可换 MQ TTL + 死信」，不要假装已经上了消息中台。
兜底：定时扫 `expire_at` 防止漏关单。

## ADR-007 检索先 SQL，不上 ES

决策：店铺过滤 + 距离排序走 PostgreSQL。
理由：种子 40 家店，ES 没有痛点。向量检索以后用 pgvector，全文搜索才考虑 ES。

## ADR-008 部署形态：两服务 + 一前端，不是微服务全家桶

决策：Docker Compose 拉起 `web` / `shop-api` / `agent-api` / `postgres` / `redis` / `minio`。
面试答「为什么不是微服务」：一人团队、交易要本地事务、先按 Java 包划分限界上下文（user/shop/trade/content/agentbridge）。某个模块真要独立扩缩再拆。

## ADR-009 评价绑定订单，Agent 不能自动发

决策：`reviews.order_id` 唯一；发布必须经过用户确认 + Java 二次校验。
理由：反刷评、反幻觉、反名誉风险。这是产品，不是妥协。

## ADR-010 手打合同（贯穿 10 天）

决策：AI 可以打第一版代码，但每个模块收工标准是「你能对着空白文件重写关键路径」。
关键路径包括：JWT 过滤器、店铺状态机、nearby 查询、Lua 扣券、下单 CAS、关单回补、PRED 图节点、CASDG Gate、评测脚本。
讲不出来的代码，删掉或重写，不准留在简历里。

## ADR-011 订单是电子套餐券，到店核销才算完成

决策：订单状态拆成「钱」和「履约」两段，评价只绑履约完成。

```
CREATED            未支付
PAID               已支付未核销   ← 用户可随时退单
REDEEMED           已核销未评价   ← 唯一可评价入口
REVIEWED           已核销已评价
CANCELLED_TIMEOUT  超时未支付
REFUNDED           未核销退单
```

规则：
1. 套餐是到店核销的电子券，支付只证明买了券，不证明去吃过。
2. 只有 `REDEEMED` 能发评价；`PAID` 不能评。这是反「付完款就写假评」。
3. `PAID` 之前超时关单；`PAID` 之后、核销之前，用户可退单并回补套餐库存和满减券。
4. 核销后不可退、不可再改成未核销。
5. 展示销量在核销成功后 +1，退单不计入销量。
6. 满减券：下单冻结，支付保持占用，退单/超时释放，核销后才算真正用掉。
7. 「优惠券核销」和「到店核销」口头必须加定语，代码里到店用 `redeem`，满减券用 `coupon.used`。

替代：支付即可评价。拒绝——这不是点评，是电商好评返现。

## 今天不做的决策（再填细节）

- Maven 还是 Gradle（默认 Maven，除非你更熟 Gradle）
- 包名（默认 `com.scoutbite`）
- 地图用高德还是 Leaflet（前端 AI 选一个，后端只出 lat/lng）
- LangGraph 具体节点代码

---

## 补遗决策（2026-08-21 仓库落地时填写）

### ADR-012 构建工具：Maven（不选 Gradle）
理由：与工作技术栈一致（公司项目 Maven + 私服），面试八股也更贴 Maven 生命周期。

### ADR-013 包名：com.scoutbite.shop / com.scoutbite（预留）
理由：与产品名 ScoutBite 对齐；`shop` 后缀与 `agent-api` 的 Python 模块名区分边界。

### ADR-014 本地镜像策略：项目级 settings 覆盖，不动全局
决策：`services/shop-api/maven-settings.xml` 配阿里云镜像，启动命令 `mvn -s maven-settings.xml spring-boot:run`。
背景：全局 `~/.m2/settings.xml` 指向公司 Nexus(172.16.8.3:8081)，居家网络不可达（实测连接超时）。
理由：不污染公司电脑的全局配置——上班时全局配置照常生效，本项目独立走公网镜像。

### ADR-015 端口偏移：容器 PG=5433、Redis=6380
决策：compose 宿主端口映射 5433:5432、6380:6379。
背景：本机已自装 PostgreSQL（占 5432）和 Redis（占 6379）且正在运行。
理由：不动用户本机已有服务；JDBC 连 `localhost:5433`，Redis 客户端连 `localhost:6380`。
替代：复用本机 PG/Redis。拒绝——验收要求 compose 一键起全套，且版本/密码不受控。

### ADR-016 容器化范围：只容器化三大件，应用本机跑
决策：compose 只含 postgres/redis/minio；shop-api 与 agent-api 用 `mvn spring-boot:run` / `uvicorn` 本机跑，再做应用容器化。
理由：Java 多阶段 Dockerfile 是新手高频失败区，验收口径（两个文档站可开 + 三大件 healthy）不要求应用进容器。渐进式容器化。

### ADR-017 依赖纪律：最小依赖集
决策：shop-api 只引 web / validation / actuator / springdoc 四件；刻意不引 data-jpa、data-redis、security。
理由：依赖 = 功能清单。引 JPA 而无数据源会直接启动失败；security 全家桶会拦掉所有接口（含 Swagger），手写轻量 JWT 过滤器更可控。Python 侧 requirements.txt 由 `pip freeze` 锁定精确版本，容器化可复现。

### ADR-018 统一返回体 + 全局异常兜底（合同强制力的落地点）
决策：`ApiResponse<T>`（code/message/data/requestId）+ `ErrorCode` 枚举 + `@RestControllerAdvice` 兜底（50000 系统码）。
理由：接口合同从「文档约定」升级为「代码强制」——连未捕获异常也逃不出统一信封；requestId 为 观测体系预留线索。

### ADR-020 评价锚定核销订单（已落地）
决策：`reviews.order_id` 唯一索引；发布校验「订单属于本人 + status=REDEEMED」。
理由：支付只证明买券不证明消费（ADR-011 规则2 的实现）。核销接口 redeemCas（PAID→REDEEMED，同事务销量+1）是评价唯一入口；未核销评价返回 40903、重复评价 40901。
幂等三部曲就此齐活：下单（idempotency_key）、支付/核销（状态 CAS）、评价（order_id 唯一）——同一个数据库特性，三种业务语义。

### ADR-021 is_merchant 服务端判定（已落地）
决策：回复的商家标由服务端写入：token role=MERCHANT 且 shop.ownerId=userId。请求体里的身份字段一概不采信。
理由：客户端只提供诉求，身份永远服务端说了算（与 角色边界、归属校验同一条原则的第三次出现）。普通用户也可回复（社交属性），只是无标。

### ADR-022 推流五因子与 diversityPenalty 的工程化（已落地）
决策：score = quality × freshness^0.5 × proximity × exploreBoost × diversityPenalty。quality 用评分平滑（(sum+3×2)/(count+2)，新店给中位数 3.0 而非 0——否则 quality=0 会把 exploreBoost 乘没）；diversityPenalty 不做公式惩罚，改为输出阶段同店去重（一屏一条）+ nearby/hot 流探索位配额（前 3 无新店则把最高分新店插到第 2 位）。
理由：公式的归公式（可解释、可调参），算法的归算法（去重 10 行代码立竿见影）。explore 做成请求级开关——验收要同屏对比「开关前后新店存没」。
场景三队列：nearby（proximity² 主导）/ hot（quality² 主导）/ new（候选只留 7 日新店）。每次输出写 impressions（append-only，已读降权 + 商家归因的原料）。

### ADR-023 种子评价用负数合成 orderId（已落地）
决策：种子评价的 order_id 取负数序列（-1, -2, ...），不伪造真实订单。
理由：真实订单 id 从 1 正数增长，负数永不冲突；且一眼可辨「这是种子数据不是真实评价」。同理 likes 表种子允许撞联合唯一时静默跳过。
已知毛边（顺延）：1）评价 scores 的 jsonb 用 Hibernate 6 @JdbcTypeCode(SqlTypes.JSON) 映射 String——读写在测，但复杂 JSON 查询（如按 taste>4 过滤）要走原生 SQL，Agent 证据接口时再补。2）scene=new 流会混入无店帖子——设计上可接受（自由内容不受店铺队列约束），若产品认为"新"应纯指新店再过滤。3）对账任务（Redis 券余量 vs DB）仍未做，观测日一起。

### ADR-024 推荐 Agent：LangGraph 五步 + 程序化护栏（已落地）
决策：agent-api 用 LangGraph StateGraph 编排 PRED 五步（意图→画像→检索→证据→对比生成），生成后过纯代码护栏三查（店ID⊆检索候选 / 引用 evidenceId 存在 / 每家缺点非空），违者 42201 不放行。LLM 为 DeepSeek deepseek-chat（OpenAI 兼容接口，httpx 直调，response_format=json_object），key 走 .env（已 gitignore）。
理由：能用确定计算消灭的失败不进生成（检索裁剪+证据锚定）；必须生成的部分用结构化+引用钉在证据上（对比式解码约束：3家/必有一缺点/必须引用）；幻觉从概率问题变成可拦截错误。位置同源性：/internal/shops/search 直接复用 GeoService.nearby——Agent 与用户地图的"附近"永远一致。

修订（验收后，用户提出）：**取消模板兜底，改为诚实降级**。LLM 未配置/调用失败、或主站 /internal 未连通 → 一律返回 50000「服务未连通，本次请求已中止，未生成任何内容」，绝不拿模板内容冒充 AI 推荐，也不拿空结果伪装"附近没有店"。
理由：降级的最大风险不是不可用，而是用户不知道已经降级——宁可报错，不可冒充（产品诚实性原则）。检索结果为空仍如实回答"附近没有"，因为那是真实结论不是故障。顺带修复存量 bug：画像兜底分支此前只更新约束不检索（topCategories 命中时返回空候选）。

### ADR-025 服务间鉴权与身份注入（已落地）
决策：/internal/** 由 InternalTokenFilter 校验 X-Internal-Token（与 agent-api 共享密钥，配置注入）；AgentFacadeController 转发时注入 X-User-Id 头，agent-api 不解析 JWT。
理由：人类走 JWT 门（/api/*），机器走服务门（/internal/*）——两扇门两把锁；身份注入在门面层发生，Python 侧零鉴权复杂度（也不给它伪造空间：它只知道"用户是谁"，改不了"是不是用户"）。

### ADR-026 画像离线刷新与冷启动策略（已落地）
决策：user_profiles 由 ProfileService.refreshAll() 聚合 likes/reviews/orders 生成（启动时刷新，模拟夜间任务；权重：消费3>评价2>点赞1）。冷启动（无画像）不瞎猜——意图解析不出品类时先问一个问题（needClarify 短路），有画像时用 topCategories 兜底。
理由：画像不要求实时，在线现算徒增时延；冷启动瞎猜比问一句更伤信任。

### ADR-027 trace 落库与统一信封的边界（已落地）
决策：agent-api 的端点返回统一信封 {code,message,data} 但**不设 FastAPI response_model**——门面按信封拆包透传；trace（input/tools/output/latency）由门面落 agent_traces。
教训：给返回信封的端点设 response_model 会让 FastAPI 用 DTO 校验信封本身，直接 ResponseValidationError 500（实测踩坑，修法是去掉 response_model 而不是改信封——信封是跨服务合同，DTO 只是内部形状）。

### ADR-028 评价草稿 CASDG 与签字权闭环（已落地）
决策：草稿生成走 CASDG（Collect 订单事实→Align 事实清单→Score+Draft LLM 起草→Gate 护栏），草稿存 Python 进程内仓（drafts.py，发布即消费）；发布写路径只在 Java 门面——publish = 门面取草稿（Python 验归属并 pop）→ ReviewService.create 原路二次校验（归属/REDEEMED/order_id 唯一）→ 写库。
理由：Python 没有写库通道，模型只能起草、用户 JWT 签字才发布——人审是产品不是妥协（行程思考点）。纵深防御：哪怕草稿被篡改，发布关的二次校验也过不去；连点双评被"草稿已消费 + 唯一索引"双层兜住。草稿仓内存化的诚实代价：重启丢草稿（重生成即损失为零）；升级路径 Redis+TTL。
预设分规则：preferScores 用户给定的维度 LLM 必须原样保留（输出侧强制覆盖），LLM 只填其余维度。

### ADR-029 商家分析三层结构与护栏的措辞规则（已落地）
决策：三技能（ops→metrics / reviews→关键词分桶聚类 / competitors→同品类 3km 公开信息）各走独立数据源，输出强制三层：观察（数字必须在工具结果中，正则存在性校验）/ 假设 / 建议（≤2 条）。假设层规则：必含「可能/或许」类限定词；**未限定的确定性断言（证明了/肯定是/就是由于）才拦截，带限定的因果连接词（因为/导致）放行**——「可能因为券活动导致新客上升」是合规推测。
教训（实测迭代）：初版把"导致"一刀切进黑名单，LLM 合规的带限定假设被误拦（2/3 失败率）。护栏管的是断言语气（确定 vs 推测），不是连接词本身——过严的护栏和没有护栏一样伤产品。
MVP 诚实口径：评论聚类是关键词分桶（五主题桶+正则），非语义聚类；竞品只用系统内公开信息。

### ADR-030 环境不稳定对策：服务进程独立化（已落地）
背景：本会话内机器三次全灭（Docker daemon/Java/Python 同时死，疑似睡眠/重启循环），依附终端的后台进程随终端回收消亡。
决策：deploy/recover.ps1 一键恢复（Docker 等待→容器 healthy→Start-Process 独立窗口起 shop-api/agent-api，与终端生命周期解耦）；验证脚本 verify.py（Python，UTF-8 安全，幂等键带时间戳可重复跑）。
理由：恢复从"15 分钟手工流程"变成一条命令；验证从"临时命令拼接"变成可重放资产（评测可复用其结构）。

### ADR-031 离线评测体系（已落地）
决策：evals/ 目录承载评测资产——三个黄金集（recommend 30 / review 20 / merchant 15，含 6 负例：跨城×2、冷启动澄清×1、诱导编造×4）+ run_eval.py（一条命令生成 reports/latest.md）+ replay.html（trace 回放页）。指标四层：程序化（约束满足/引用存在/schema/是否自动发布/编造抓拍，全部独立反查公开接口复核）、Judge 抽样 5 条（量规冻结于代码，长度惩罚条款，同族偏差如实标注）、系统（p50/p95/工具调用数/token 成本——llm.py 记 usage）、人工抽检（流程声明）。
关键设计：①评测进程内跑图（import 直调），为破坏性试验保留 monkeypatch 能力；②「是否自动发布」为独立指标——跑完 20 条草稿后测试订单 0 新评价（ADR-028 的回归守门员）；③区分度试验：--mode broken 把 tools.search_shops 补丁成"丢品类过滤+半径 50km"，constraint_category 应显著下跌——一个永远不会失败的测试等于没有测试。
实测迭代（评测抓到的真问题，比全绿更有价值）：①首轮 rev-009~012 编造抓拍 4/4 全中——提示词防线是概率性的（两轮运行一轮免责一轮断言），加硬提示词后部分收敛；菜品级编造仍为已知缺口（确定性解法=Gate 实体抽取对照事实词表，升级路径记录在案）；②mer-008/014 被护栏正确拦截（模型自行换算均分 4.67，数据里现成 avgScore 不用）——提示词补"聚合数字直接引用字段值"；③数据集校准：rec-028"有没有好玩的地方"能解析出 ENTERTAIN，expectClarify 期望过严（v1.0.1 修正）；④检查器校准：免责词表与锚定前缀（"未达到米其林水准"是免责不是编造；"四人欢聚套餐"缩写为"四人套餐"应算锚定）。
诚实边界：judge=DeepSeek 评 DeepSeek 有同族偏好；n=30 的 p95 只是第 28 大值；评测测不到长期留存与线上分布漂移。

### ADR-032 压测与关单对账（已落地）
决策：deploy/ 两脚本收口验收——loadtest_claims.py（200 独立用户并发抢 100 张券）+ close_order_check.py（未支付单超时后三资源归位）。
工具决策：Python ThreadPoolExecutor 受控并发，不装 k6/JMeter——本项目要的是**正确性断言**（不超卖/幂等/一致性）而非吞吐曲线；200 人用 13900000100+ 段独立注册（per_user_limit=1，复用用户会全员 40901 测不出真实竞争），每线程独立 httpx.Client（共享连接池会把并发退化成排队）。
对账原则：**验证者独立于被验证者**——三查断言全部绕过服务端自报，直接 docker exec 读 PG 与 Redis：① success ≤ 100；② Redis 余量 == 100 − success；③ DB user_coupons 新增行数 == success。关单对账等**真实超时**（sleep 35s，expire-seconds=30 + 5s 缓冲），断言订单 CANCELLED_TIMEOUT + 库存回补 + 券 FROZEN→UNUSED 三源互相印证。
实测：成功恰好 100 / Redis 余量 0 / DB 新增 100 行（13900000100~205 段独立用户）；同人 20 并发双击只成功 1 次（幂等）；对账订单 75/76 双双归位。
诚实边界：本压测验证的是**正确性**（无超卖/幂等），不是容量（未测 QPS 上限与长尾延迟——那是 k6 的领域，上量级再换）。

### ADR-019 主站端口：8081（原计划 8080）
背景：本机 Docker 存在自启容器 `aio-sandbox-mcp`（restart 策略），占用宿主 8079-8080；该端口经 WSL 中继绑定，netstat 不可见，表现为「netstat 空、bind 失败」的隐身占用。
决策：shop-api 使用 8081，不动既有容器。
理由：那是既有工具链的一部分，停掉影响面未知；改端口是零风险变更。Swagger 入口同步变为 http://localhost:8081/swagger-ui.html。
教训（可迁移）：Windows 上端口「绑定失败但 netstat 无显示」→ 优先怀疑 Docker/WSL 中继占用，`docker ps` 看 PORTS 列一步定位。
