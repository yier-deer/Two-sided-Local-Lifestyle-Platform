export function createClient({
  mode,
  session,
  demo,
  fetchImpl = globalThis.fetch,
}) {
  return {
    async request(path, opts = {}) {
      const current = { ...session() };
      const requestMode = mode();
      const signature = (value) =>
        [value.revision, value.userId, value.role, value.token].join("|");
      const initialSignature = signature(current);
      const verifySession = () => {
        if (
          requestMode !== mode() ||
          initialSignature !== signature(session())
        ) {
          const error = new Error("会话已切换，本次旧请求的结果已丢弃。");
          error.code = "SESSION_CHANGED";
          throw error;
        }
      };
      if (requestMode === "demo") {
        const result = await demo.request(path, opts, current);
        verifySession();
        return result;
      }
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), opts.timeout || 70000);
      try {
        const response = await fetchImpl(path, {
          method: opts.method || "GET",
          headers: {
            "Content-Type": "application/json",
            ...(current.token
              ? { Authorization: `Bearer ${current.token}` }
              : {}),
            ...opts.headers,
          },
          body: opts.body != null ? JSON.stringify(opts.body) : undefined,
          signal: controller.signal,
        });
        let envelope;
        try {
          envelope = await response.json();
        } catch {
          throw new Error("业务服务未就绪，请检查服务连接后重试。");
        }
        verifySession();
        if (!response.ok || envelope.code !== 0) {
          const error = new Error(
            envelope.message || `请求失败（${response.status}）`,
          );
          error.code = envelope.code;
          error.requestId = envelope.requestId;
          throw error;
        }
        return envelope.data;
      } catch (e) {
        verifySession();
        if (e.name === "AbortError")
          throw new Error(
            "本次请求超时，请稍后重试。当前操作没有切换到示例数据。",
          );
        if (e instanceof TypeError)
          throw new Error(
            "无法连接业务服务，请确认 shop-api 已启动，或主动切换本地演示。",
          );
        throw e;
      } finally {
        clearTimeout(timer);
      }
    },
  };
}
