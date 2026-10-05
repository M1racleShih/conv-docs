#!/usr/bin/env node
/**
 * 浏览器端到端冒烟测试（需本机 Chrome + 已运行的 conv-doc）。
 *
 *   TOKEN=... BASE=http://127.0.0.1:8380 node scripts/browser-smoke.mjs
 *
 * 通过 DevTools 协议驱动无头 Chrome：登录 → 浏览发布目录 →
 * Markdown 渲染 → HTML 安全渲染（脚本/事件被剥离）→ 完整模式沙箱断言。
 */
import { spawn } from "node:child_process";
import process from "node:process";

const BASE = (process.env.BASE || "http://127.0.0.1:8380").replace(/\/$/, "");
const TOKEN = process.env.TOKEN || "";
const CHROME = process.env.CHROME || "google-chrome";
const ROOT = process.env.ROOT || "ai-fundamentals";
const MD_FILE = process.env.MD_FILE || "README.md";
const HTML_FILE = process.env.HTML_FILE || "chapters/01-fundamentals.html";
const PORT = 9333;

if (!TOKEN) {
  console.error("缺少 TOKEN 环境变量");
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn(CHROME, [
  "--headless", "--no-first-run", "--disable-gpu",
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=/tmp/conv-doc-smoke-profile-${process.pid}`,
  "about:blank",
], { stdio: "ignore" });
process.on("exit", () => { try { chrome.kill(); } catch {} });

async function waitFor(fn, label, timeoutMs = 15000) {
  const start = Date.now();
  for (;;) {
    let v;
    try { v = await fn(); } catch { v = undefined; }
    if (v) return v;
    if (Date.now() - start > timeoutMs) throw new Error("超时：" + label);
    await sleep(250);
  }
}

// ---- 最小 CDP 客户端 ----
let ws, nextId = 1;
const pending = new Map();
const networkResponses = []; // [url, status]
function cdp(method, params = {}, sessionId) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params, sessionId }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject, method }));
}

const version = await waitFor(async () => {
  const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
  return r.ok ? r.json() : null;
}, "chrome devtools 启动");

ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.method === "Network.responseReceived" && msg.params && msg.params.response) {
    networkResponses.push([msg.params.response.url, msg.params.response.status]);
  }
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject, method } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(method + ": " + msg.error.message)) : resolve(msg.result);
  }
};

const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = targets.find((t) => t.type === "page");
const { sessionId } = await cdp("Target.attachToTarget", { targetId: page.id, flatten: true });
await cdp("Page.enable", {}, sessionId);
await cdp("Runtime.enable", {}, sessionId);
await cdp("Network.enable", {}, sessionId);

async function evalJs(expression) {
  const r = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, sessionId);
  if (r.exceptionDetails) throw new Error("页面脚本报错：" + JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function navigate(hash) {
  await cdp("Page.navigate", { url: BASE + "/index.html" + hash }, sessionId);
  await sleep(600);
}
const checks = [];
function check(name, ok, detail = "") {
  checks.push([name, ok]);
  console.log((ok ? "✓" : "✗") + " " + name + (detail ? `  (${detail})` : ""));
}

// 1. 登录：写入 token 并进入工作区列表
await navigate("#/login");
await evalJs(`localStorage.setItem("conv-doc.token", ${JSON.stringify(TOKEN)}); location.hash = "#/"; "ok"`);
await waitFor(async () => (await evalJs(`document.querySelectorAll(".list-item").length`)) > 0, "工作区列表");
const rootsText = await evalJs(`document.getElementById("app").innerText`);
check("登录后看到已发布工作区", rootsText.includes(ROOT), ROOT);

// 2. 浏览目录：隐藏目录与不支持类型不可见
await navigate(`#/b/${ROOT}`);
const treeText = await evalJs(`document.getElementById("app").innerText`);
check("目录列表显示 README.md", treeText.includes("README.md"));
check("目录列表显示 chapters", treeText.includes("chapters"));
check(".git 不出现在目录列表", !treeText.includes(".git"));
check("媒体文件不出现在列表", !treeText.includes(".mp4"));

// 3. Markdown 渲染
await navigate(`#/v/${ROOT}/${MD_FILE}`);
await waitFor(async () => (await evalJs(`document.querySelectorAll(".doc-body h1").length`)) > 0, "Markdown 渲染");
const mdInfo = await evalJs(`JSON.stringify({
  h1: document.querySelector(".doc-body h1") ? document.querySelector(".doc-body h1").innerText : "",
  code: document.querySelectorAll(".doc-body pre code").length,
  hljs: document.querySelectorAll(".doc-body pre code.hljs").length,
  extLinks: Array.from(document.querySelectorAll(".doc-body a[target=_blank]")).every(a => /noopener/.test(a.rel)),
})`);
const md = JSON.parse(mdInfo);
check("Markdown 标题渲染", md.h1.length > 0, md.h1.slice(0, 24));
check("代码块高亮（highlight.js）", md.code > 0 && md.hljs > 0, `${md.hljs}/${md.code}`);
check("外链带 noopener noreferrer", md.extLinks);

// 4. HTML 安全渲染：脚本与事件被剥离，样式保留
await navigate(`#/v/${ROOT}/${HTML_FILE}`);
await waitFor(async () => (await evalJs(`document.querySelectorAll(".doc-body h1, .doc-body h2").length`)) > 0, "HTML 渲染");
const htmlInfo = await evalJs(`JSON.stringify({
  scripts: document.querySelectorAll(".doc-body script").length,
  onAttrs: document.querySelectorAll(".doc-body [onclick], .doc-body [onerror], .doc-body [onload]").length,
  title: (document.querySelector(".doc-body h1, .doc-body h2") || {innerText: ""}).innerText,
})`);
const hi = JSON.parse(htmlInfo);
check("HTML 内容渲染", hi.title.length > 0, hi.title.slice(0, 24));
check("脚本标签被清洗（安全渲染）", hi.scripts === 0, `${hi.scripts} 个`);
check("事件属性被清洗", hi.onAttrs === 0, `${hi.onAttrs} 个`);
// 样式内联是异步 fetch，轮询等待
const styled = await waitFor(async () => {
  const n = await evalJs(`document.querySelectorAll(".doc-body style").length + document.querySelectorAll(".doc-body link[rel=stylesheet]").length`);
  return n > 0 ? n : null;
}, "文档样式内联", 8000).catch(() => 0);
check("文档样式被保留/内联", styled > 0, `${styled} 处`);

// 5. 完整模式：沙箱 iframe + 一次性 ticket
await evalJs(`Array.from(document.querySelectorAll(".mode-bar button")).find(b => b.innerText.includes("完整模式")).click(); "ok"`);
const frame = await waitFor(async () => {
  return await evalJs(`(function(){var f=document.querySelector(".raw-frame");return f&&f.src?"yes":null})()`);
}, "完整模式 iframe").catch(() => null);
if (frame === null) {
  check("完整模式 iframe 出现", false, "未找到");
} else {
  const frameInfo = await evalJs(`JSON.stringify({
    sandbox: document.querySelector(".raw-frame").getAttribute("sandbox"),
    src: document.querySelector(".raw-frame").src,
  })`);
  const fi = JSON.parse(frameInfo);
  check("沙箱不含 allow-same-origin", fi.sandbox.includes("allow-scripts") && !fi.sandbox.includes("allow-same-origin"), fi.sandbox);
  check("URL 携带一次性 ticket 而非 token", fi.src.includes("ticket=") && !fi.src.includes(TOKEN));
  // 沙箱 iframe 是浏览器导航（无 Authorization 头）——通过网络事件验证其响应真实为 200 文档
  const got = await waitFor(async () => {
    const hit = networkResponses.find(([u]) => u.includes("/api/v1/rawhtml"));
    return hit ? hit[1] : null;
  }, "rawhtml 响应").catch(() => null);
  check("完整模式内容真实加载（HTTP 200）", got === 200, `HTTP ${got}`);
}

const passed = checks.filter(([, ok]) => ok).length;
console.log(`\n浏览器冒烟：${passed}/${checks.length} 通过`);
process.exit(passed === checks.length ? 0 : 1);
