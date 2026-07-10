package com.scoutbite.shop.common;

/**
 * 错误码枚举：数字来自《接口实现》合同，禁止自由发挥。
 * code 给程序判断（前端 if resp.code == 40902），desc 给人看（打日志不用回查）。
 */
public enum ErrorCode {
    OK(0, "成功"),
    PARAM_ERROR(40001, "参数或约束错误"),
    UNAUTHORIZED(40100, "未登录或 token 失效"),
    FORBIDDEN(40300, "角色不对"),
    IDEMPOTENT_CONFLICT(40901, "幂等冲突或重复评价"),
    STOCK_SHORTAGE(40902, "库存或券不足"),
    STATE_CONFLICT(40903, "状态机冲突"),
    GUARDRAIL(42201, "Agent 护栏拦截");

    private final int code;
    private final String desc;

    /** 枚举构造器：PARAM_ERROR(40001, "...") 就是在调它 */
    ErrorCode(int code, String desc) {
        this.code = code;
        this.desc = desc;
    }

    public int getCode() { return code; }
    public String getDesc() { return desc; }
}
