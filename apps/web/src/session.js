import { reactive } from "vue";
import { accounts } from "./demo/data.js";

const storage = globalThis.localStorage;
let saved;
try {
  saved = JSON.parse(storage?.getItem("scoutbite-session") || "null");
} catch {
  saved = null;
}
export const session = reactive(
  saved || {
    mode: "demo",
    userId: 1,
    role: "USER",
    nickname: "辣妹小队长",
    token: "demo-1",
    phone: "13611110001",
  },
);
session.revision = Number(session.revision) || 0;
export const ui = reactive({
  toasts: [],
  location: { lat: 30.24, lng: 120.15, name: "杭州 · 湖滨商圈" },
  modal: null,
  merchantShopId: null,
});
const persist = () =>
  storage?.setItem("scoutbite-session", JSON.stringify(session));
export function setIdentity(data) {
  Object.assign(session, data);
  session.revision++;
  persist();
}
export function logout() {
  Object.assign(session, {
    token: "",
    userId: null,
    role: "",
    nickname: "",
    phone: "",
  });
  session.revision++;
  persist();
}
export function setMode(mode) {
  logout();
  session.mode = mode;
  ui.merchantShopId = null;
  persist();
}
export function demoLogin(role = "USER") {
  const a = accounts.find((a) => a.role === role);
  const { password, ...identity } = a;
  setIdentity({ ...identity, token: `demo-${a.userId}` });
}
export function toast(message, type = "success") {
  const id = Date.now() + Math.random();
  ui.toasts.push({ id, message, type });
  ui.toasts = ui.toasts.slice(-2);
  setTimeout(() => {
    ui.toasts = ui.toasts.filter((t) => t.id !== id);
  }, 4500);
}
export function askConfirm({
  title,
  text,
  confirm = "确认",
  danger = false,
  action,
}) {
  ui.modal = { title, text, confirm, danger, action, busy: false };
}
