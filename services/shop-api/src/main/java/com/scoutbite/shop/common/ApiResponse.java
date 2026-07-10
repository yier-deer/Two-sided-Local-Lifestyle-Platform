package com.scoutbite.shop.common;

import java.util.UUID;

/**
 * 统一响应体（信封模式）：所有接口（含异常兜底）的返回都套这个结构。
 * 字段名与《接口实现》合同一字不差：code / message / data / requestId。
 *
 * @param <T> 业务数据的类型——信封只有一个，信纸随便换（这就是用泛型的原因）
 */
public class ApiResponse<T> {

    /** 业务码：0 成功，其余见 ErrorCode 枚举 */
    private int code;

    /** 人类可读的提示信息 */
    private String message;

    /** 业务数据本体 */
    private T data;

    /** 链路追踪 ID：把一次请求散落在各处的日志串成一条线（观测体系的地基） */
    private String requestId;

    /** 成功快捷构造（静态工厂）：方法名即文档，一眼看出这是成功路径 */
    public static <T> ApiResponse<T> ok(T data) {
        ApiResponse<T> r = new ApiResponse<>();
        r.code = 0;
        r.message = "ok";
        r.data = data;
        r.requestId = shortId();
        return r;
    }

    /** 失败快捷构造（静态工厂）：code 取自 ErrorCode，失败必须给原因 */
    public static <T> ApiResponse<T> fail(ErrorCode ec, String message) {
        ApiResponse<T> r = new ApiResponse<>();
        r.code = ec.getCode();
        r.message = message;
        r.requestId = shortId();
        return r;
    }

    /**
     * 失败快捷构造（透传版，）：跨服务转发时保留上游业务码原样返回
     * （如 agent-api 的 42201/40903——前端看到的错误码 = Agent 层的错误码，不二次翻译）。
     */
    public static <T> ApiResponse<T> fail(int code, String message) {
        ApiResponse<T> r = new ApiResponse<>();
        r.code = code;
        r.message = message;
        r.requestId = shortId();
        return r;
    }

    /** 生成 8 位短随机 ID；演示项目够用，升级为完整链路追踪 */
    private static String shortId() {
        return UUID.randomUUID().toString().substring(0, 8);
    }

    // ---- getters / setters：Jackson 序列化要读，全局异常兜底要写 ----

    public int getCode() { return code; }
    public void setCode(int code) { this.code = code; }

    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }

    public T getData() { return data; }
    public void setData(T data) { this.data = data; }

    public String getRequestId() { return requestId; }
    public void setRequestId(String requestId) { this.requestId = requestId; }
}
