# ScoutBite 演示验收记录

完成日期：2026-10-11。用途：面试 / 项目答辩。分支：`codex/demo-ready`。

## 交付结果

独立示例模式与真实服务模式都可以演示完整用户→商家闭环：发现/搜索→推荐证据→套餐→领券选券→模拟支付→核销→修改草稿并确认发布→商家回复→三层分析。商家供给、入驻与审核界面也可操作。

真实模式已使用项目隔离 PostgreSQL18.4、Redis3.0.504、Java21和Python/DeepSeek完成实际验证；不是接口桩或浏览器样本替代。当前机器 Docker Desktop 因全局IPC问题不能运行，项目提供并已验证 Native 路径。未重置 Docker 卷、原有数据库或系统 Redis。

## 本轮补齐

- 重建双端视觉、导航、店卡、图片、搜索筛选、响应布局与错误/空/加载反馈。
- 将领券接入选券结算，修 userCouponId、实付减免、幂等、取消/退款回补和消费状态。
- 修改后的评价正文/评分真正发布，生成不写库，确认按钮需要用户核对；Python先读取、Java成功后消费草稿。
- 补商家概览、真实自有订单核销、套餐/券管理、回复、三分析与管理员审核。
- 补商家账号归属、地址增量持久化、真实评价评分/数量与可售起价，阻止待审店绕过列表直接购买。
- 防止迟到身份响应污染新模式、旧401注销新身份、定位拒绝隐藏列表、分析换店错位和回复重复提交。
- 评价改为事实与合法体验ID闭包，防无笔记编造菜品、评级及否定语义反转。商家三技能观察使用原始事实ID，精确Decimal复核；推荐扩检有供给候选并参考套餐起价预算。
- 新真实验收/并发脚本不消耗固定旧券，每次建专用资源且独立查PG/Redis；评测复用真实既有事实，不偷偷造订单。
- 后台启动、端口和进程归属、项目数据目录、profile/构建版本、有界等待、现场900秒支付窗口、重复场景准备齐全。

## 验证证据

- 前端逻辑15/15；独立浏览器12/12；真实浏览器2/2（真实推荐证据和真实消费/核销/模型/回复）；390/1024/1440宽度检查与脚本错误检查通过。
- `npm run build` 成功，JS241.30KB / gzip84.78KB。
- Java74/74、Agent Python42/42、评测CLI27/27、验收/并发/准备工具27/27。
- [严格真实验收13/13](reports/real-integration-final-pass-20261011.json)：角色、可见性、领券扣价、幂等、取消/退款、商家核销、草稿确认、公开回复、三分析、引用/trace和独立DB/Redis。
- [并发与超时6/6](reports/concurrency-20261010.json)：200同步发起请求抢100新券，100成功/100拒绝/0异常；Redis0/DB100；同人20仅1次；SKU库存1争抢仅1单；两个真实未付订单实际到期后库存和券恢复。
- [真实Agent65/65](../evals/reports/full-20261011-release.md)：推荐30、评价20、商家15全部过；生成20条草稿后新增评价0；92次模型调用粗估¥0.5046。商家只1个独立真实门店，预算仅最低套餐价参考，样本通过不等于线上质量保证。
- 历史与本轮失败报告保留。首轮58/65暴露事实生成问题，后续严格拦截与评测工具精度问题均留下证据，不删失败只留成功。
- Native/App正反只读检查通过：项目PID/数据目录/port/profile允许；外部workspace、错误profile、5432/6379或错误目录拒绝；不终止未知进程。
- 图片与页面截图已视觉检查，配图来源含AI火锅展示图片见 `apps/web/public/images/CREDITS.md`，非实际店铺实拍。

## 现场启动

```powershell
# 真实模式（本机Auto会选Native；首次需安装对应工具）
powershell -ExecutionPolicy Bypass -File deploy\start-all.ps1
python deploy\prepare-demo.py

# 无模型/基础设施依赖的独立模式
powershell -ExecutionPolicy Bypass -File deploy\start-demo.ps1
```

打开 `http://127.0.0.1:5173/#/discover`，顶部选择数据模式。操作导览 `/#/demo`。准备脚本输出 `deploy/logs/demo-scenario.json`：真实门店1、演示双人198元、满100减20、已核销未评订单；消费过的券再次准备时会创建新的演示券。不会删除旧评价/订单或覆盖他人门店。

Java/Python更新后需停止旧的本项目进程再启动；启动会核对版本并明确拒绝错误的旧服务。原生工具位置可用 `-PostgresBin` 和 `-RedisServer` 配置。Runtime/logs/.env不入库。

## 复验命令

前端：`npm test`、`npm run build`、`npm run test:e2e`。真实浏览器：`$env:SCOUTBITE_LIVE_TESTS='1'; npx playwright test tests/e2e/live.spec.js`，会请求实时模型。

Java：`mvn -B -ntp -s maven-settings.xml package`。Python：在agent-api执行 `.venv\Scripts\python.exe -m unittest discover -p 'test_*.py' -v`。

真实API：设置进程 `PGPASSWORD` 后执行 `python deploy/verify_real.py --db-mode native --psql E:/PSG/bin/psql.exe --redis-port 6380`。可选 `--skip-agent` 会明确标SKIP而非模型通过。

并发/关单：先启动临时Java实例 `--server.port=8082 --scoutbite.order.expire-seconds=5`，复用项目PG/Redis；运行 `verify_concurrency.py --timeout-shop-url http://127.0.0.1:8082`，结束后只停止该测试实例。展示8081保持demo900秒。

评测：先 `verify_real.py --skip-agent --prepare-eval` 创建专用真实fixture，设置输出中引用的密码环境变量，再 `run_eval.py --check --fixtures deploy/logs/eval-fixtures.json`；`--mode full --fixtures ... --report 新文件.md` 实际请求模型。Cold用户必须没有画像，运行期间不要重启Java刷新所有画像。脚本会拒绝无效fixture、报告覆盖及模型错误。

## 明确边界

这是本地可演示项目，使用模拟支付与演示核销。单轮推荐、套餐预算参考、Python草稿内存、评论关键词分桶、未做图片上传/生产支付/跨实例草稿/多轮记忆。MinIO可选但当前主线不依赖。生产安全配置与规模性能不属于本轮；本次本地正确性/65样本通过不能宣称生产吞吐或普遍零幻觉。
