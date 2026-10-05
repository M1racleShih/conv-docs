"use strict";
/**
 * conv-docs mobile viewer — read-only workspace docs on the go.
 *
 * Rendering pipeline: marked → DOMPurify → inject; full-fidelity HTML mode
 * uses a one-shot ticket and a sandboxed iframe. The server-side CSP is the
 * last line of defence: scripts in documents never execute in this origin.
 *
 * Build: `npm run build` (tsc) → src/conv_docs/web/app.js
 */
const I18N = {
    en: {
        brand: "conv-docs",
        langBtn: "中文",
        themeBtn: "Theme",
        themeAuto: "Theme: auto",
        themeDark: "Theme: dark",
        themeLight: "Theme: light",
        logout: "Sign out",
        loginTitle: "conv-docs",
        loginHint: "Read-only workspace docs. Paste the access token generated on your PC; it stays in this browser only.",
        loginPlaceholder: "Paste access token",
        loginBtn: "Enter",
        loginInvalid: "Token invalid or expired — please re-enter",
        loading: "Loading…",
        workspaces: "Workspaces",
        workspacesSub: "Only explicitly published directories appear here.",
        nonePublished: "Nothing published yet. On your PC run: uv run conv-docs publish <dir>",
        docsOnly: "docs-only",
        emptyDir: "Empty directory",
        backToWorkspaces: "Back to workspaces",
        modified: "Modified",
        oversized: "This file is larger than the render limit. Rendering anyway may be slow.",
        forceRender: "Render anyway",
        safeMode: "Safe render",
        fullMode: "Full mode (sandboxed)",
        fullModeNote: "Full mode: scripts run in a sandbox with no access to this origin. The one-time ticket has been used.",
        imgFailed: "(image failed to load)",
        loadFailed: "Failed to load:",
        unknownError: "unknown error",
    },
    zh: {
        brand: "conv-docs",
        langBtn: "EN",
        themeBtn: "主题",
        themeAuto: "主题: 跟随系统",
        themeDark: "主题: 深色",
        themeLight: "主题: 浅色",
        logout: "退出",
        loginTitle: "conv-docs",
        loginHint: "workspace 文档只读查看。输入 PC 端生成的访问 token；它只保存在本机浏览器。",
        loginPlaceholder: "粘贴访问 token",
        loginBtn: "进入",
        loginInvalid: "token 无效或已失效，请重新输入",
        loading: "加载中……",
        workspaces: "工作区",
        workspacesSub: "只显示已显式发布的目录。",
        nonePublished: "还没有发布任何目录。在 PC 上运行：uv run conv-docs publish <目录>",
        docsOnly: "仅文档",
        emptyDir: "空目录",
        backToWorkspaces: "返回工作区列表",
        modified: "修改于",
        oversized: "文件超过渲染上限，仍然渲染可能较慢。",
        forceRender: "仍然渲染",
        safeMode: "安全渲染",
        fullMode: "完整模式（脚本沙箱）",
        fullModeNote: "完整模式：脚本运行在沙箱里（无本源权限），一次性票据已使用。",
        imgFailed: "（图片加载失败）",
        loadFailed: "加载失败：",
        unknownError: "未知错误",
    },
};
const LANG_KEY = "conv-docs.lang";
const TOKEN_KEY = "conv-docs.token";
const THEME_KEY = "conv-docs.theme";
function currentLang() {
    return localStorage.getItem(LANG_KEY) === "zh" ? "zh" : "en";
}
function t(key) {
    const table = I18N[currentLang()];
    return table[key] ?? I18N.en[key] ?? key;
}
// ---------- token ----------
function getToken() {
    return localStorage.getItem(TOKEN_KEY) || "";
}
function setToken(value) {
    if (value)
        localStorage.setItem(TOKEN_KEY, value);
    else
        localStorage.removeItem(TOKEN_KEY);
}
// ---------- API ----------
async function api(path) {
    const res = await fetch(path, {
        headers: { Authorization: "Bearer " + getToken() },
        credentials: "omit",
    });
    if (res.status === 401 || res.status === 429) {
        const err = new Error("auth");
        err.status = res.status;
        throw err;
    }
    return res;
}
async function apiJson(path) {
    const res = await api(path);
    if (!res.ok) {
        const err = new Error("http");
        err.status = res.status;
        try {
            err.detail = (await res.json()).error || "";
        }
        catch {
            err.detail = "";
        }
        throw err;
    }
    return (await res.json());
}
// ---------- theme & language ----------
function applyTheme() {
    const mode = localStorage.getItem(THEME_KEY) || "auto";
    if (mode === "auto")
        document.documentElement.removeAttribute("data-theme");
    else
        document.documentElement.setAttribute("data-theme", mode);
}
function themeLabel() {
    const mode = localStorage.getItem(THEME_KEY) || "auto";
    if (mode === "dark")
        return t("themeDark");
    if (mode === "light")
        return t("themeLight");
    return t("themeAuto");
}
function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const key of Object.keys(attrs ?? {})) {
        const value = attrs[key];
        if (key === "text")
            node.textContent = value;
        else if (key === "class")
            node.className = value;
        else
            node.setAttribute(key, value);
    }
    for (const child of children ?? [])
        node.appendChild(child);
    return node;
}
function byId(id) {
    const node = document.getElementById(id);
    if (!node)
        throw new Error("missing element #" + id);
    return node;
}
const app = byId("app");
function fmtSize(bytes) {
    if (bytes < 1024)
        return bytes + " B";
    if (bytes < 1024 * 1024)
        return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
}
function fmtTime(unixSeconds) {
    const d = new Date(unixSeconds * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return (d.getFullYear() +
        "-" +
        pad(d.getMonth() + 1) +
        "-" +
        pad(d.getDate()) +
        " " +
        pad(d.getHours()) +
        ":" +
        pad(d.getMinutes()));
}
function resolveRel(dir, target) {
    const parts = dir ? dir.split("/").filter(Boolean) : [];
    for (const seg of target.split("/")) {
        if (seg === "" || seg === ".")
            continue;
        if (seg === "..")
            parts.pop();
        else
            parts.push(seg);
    }
    return parts.join("/");
}
function extOf(name) {
    const i = name.lastIndexOf(".");
    return i > 0 ? name.slice(i + 1).toLowerCase() : "";
}
const LANG_BY_EXT = {
    md: "markdown", py: "python", js: "javascript", ts: "typescript",
    sh: "bash", yml: "yaml", json: "json", html: "xml", xml: "xml", css: "css",
    rs: "rust", go: "go", java: "java", sql: "sql", c: "c", cpp: "cpp", h: "c",
};
function langOf(name) {
    return LANG_BY_EXT[extOf(name)] || "";
}
const VIEWABLE_EXTS = new Set([
    "md", "markdown", "mdown", "mkd", "html", "htm", "txt", "rst", "adoc", "org",
    "csv", "tsv", "json", "yaml", "yml", "toml", "ini", "cfg", "conf", "log",
    "text", "py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "css", "scss", "less",
    "java", "kt", "go", "rs", "rb", "php", "swift", "c", "h", "cc", "cpp",
    "hpp", "sh", "bash", "zsh", "sql", "xml", "vue", "svelte", "lua", "pl", "r",
    "dart", "ipynb", "png", "jpg", "jpeg", "gif", "webp", "bmp", "avif", "ico",
    "svg", "pdf",
]);
function isViewable(ext) {
    return VIEWABLE_EXTS.has(ext);
}
function encodePath(rel) {
    return rel.split("/").map(encodeURIComponent).join("/");
}
function rawUrl(root, rel) {
    return ("/api/v1/raw?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel));
}
// ---------- post-processing: rewrite links, authenticate images ----------
function postProcess(container, root, dir) {
    container.querySelectorAll("a[href]").forEach((a) => {
        const href = a.getAttribute("href") || "";
        if (/^(https?:|mailto:|tel:)/i.test(href)) {
            a.setAttribute("target", "_blank");
            a.setAttribute("rel", "noopener noreferrer");
            return;
        }
        if (href.charAt(0) === "#")
            return; // in-page anchor
        const clean = href.split("#")[0].split("?")[0];
        if (!clean)
            return;
        if (clean.endsWith("/")) {
            const dirRel = resolveRel(dir, clean);
            a.setAttribute("href", "#/b/" + encodeURIComponent(root) + "/" + encodePath(dirRel));
            return;
        }
        const rel = resolveRel(dir, clean);
        if (isViewable(extOf(rel))) {
            a.setAttribute("href", "#/v/" + encodeURIComponent(root) + "/" + encodePath(rel));
        }
        else {
            a.removeAttribute("href");
        }
    });
    container.querySelectorAll("img[src]").forEach((img) => {
        const src = img.getAttribute("src") || "";
        if (/^(https?:|data:|blob:)/i.test(src))
            return;
        const rel = resolveRel(dir, src.split("?")[0]);
        api(rawUrl(root, rel))
            .then((res) => {
            if (!res.ok)
                throw new Error("img");
            return res.blob();
        })
            .then((blob) => {
            img.src = URL.createObjectURL(blob);
        })
            .catch(() => {
            img.alt = (img.alt || "") + t("imgFailed");
        });
    });
}
// ---------- pages ----------
function renderLogin(message) {
    app.innerHTML = "";
    const input = el("input", {
        type: "password",
        placeholder: t("loginPlaceholder"),
        autocomplete: "current-password",
    });
    input.value = getToken();
    const err = el("p", { class: "error", text: message || "" });
    if (!message)
        err.style.display = "none";
    const form = el("form", { class: "token-form" }, [
        input,
        el("button", { type: "submit", text: t("loginBtn") }),
    ]);
    form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        setToken(input.value.trim());
        location.hash = "#/";
        void route();
    });
    app.appendChild(el("h1", { text: t("loginTitle") }));
    app.appendChild(el("p", { class: "muted", text: t("loginHint") }));
    app.appendChild(err);
    app.appendChild(form);
}
async function renderRoots() {
    const data = await apiJson("/api/v1/roots");
    app.innerHTML = "";
    app.appendChild(el("h1", { text: t("workspaces") }));
    app.appendChild(el("p", { class: "muted small", text: t("workspacesSub") }));
    const list = el("div", { class: "list" });
    if (!data.roots.length) {
        list.appendChild(el("div", { class: "panel", text: t("nonePublished") }));
    }
    for (const r of data.roots) {
        list.appendChild(el("a", { class: "list-item", href: "#/b/" + encodeURIComponent(r.name) }, [
            el("div", { class: "glyph", text: "📁" }),
            el("div", { class: "body" }, [
                el("div", { class: "name", text: r.name }),
                el("div", {
                    class: "sub",
                    text: r.path + (r.docs_only ? " · " + t("docsOnly") : ""),
                }),
            ]),
            el("div", { class: "chev", text: "›" }),
        ]));
    }
    app.appendChild(list);
}
function breadcrumb(root, rel) {
    const wrap = el("div", { class: "breadcrumb" });
    wrap.appendChild(el("a", { href: "#/", text: t("workspaces") }));
    wrap.appendChild(el("span", { class: "sep", text: "/" }));
    wrap.appendChild(el("a", { href: "#/b/" + encodeURIComponent(root), text: root }));
    const parts = rel ? rel.split("/").filter(Boolean) : [];
    const acc = [];
    parts.forEach((part, i) => {
        acc.push(part);
        wrap.appendChild(el("span", { class: "sep", text: "/" }));
        const isLast = i === parts.length - 1;
        wrap.appendChild(isLast
            ? el("span", { text: part })
            : el("a", {
                href: "#/b/" + encodeURIComponent(root) + "/" + encodePath(acc.join("/")),
                text: part,
            }));
    });
    return wrap;
}
const KIND_GLYPH = {
    dir: "📁", markdown: "📝", html: "🌐", text: "📄", image: "🖼", pdf: "📕",
};
async function renderTree(root, rel) {
    const data = await apiJson("/api/v1/tree?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel));
    app.innerHTML = "";
    app.appendChild(breadcrumb(root, rel));
    const list = el("div", { class: "list" });
    if (!data.entries.length) {
        list.appendChild(el("div", { class: "panel", text: t("emptyDir") }));
    }
    for (const entry of data.entries) {
        const route = (entry.kind === "dir" ? "#/b/" : "#/v/") +
            encodeURIComponent(root) +
            "/" +
            encodePath(entry.path);
        list.appendChild(el("a", { class: "list-item", href: route }, [
            el("div", { class: "glyph", text: KIND_GLYPH[entry.kind] || "📄" }),
            el("div", { class: "body" }, [
                el("div", { class: "name", text: entry.name }),
                el("div", {
                    class: "sub",
                    text: entry.kind === "dir"
                        ? fmtTime(entry.mtime)
                        : fmtSize(entry.size) + " · " + fmtTime(entry.mtime),
                }),
            ]),
            el("div", { class: "chev", text: "›" }),
        ]));
    }
    app.appendChild(list);
}
async function renderFile(root, rel) {
    const meta = await apiJson("/api/v1/meta?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel));
    app.innerHTML = "";
    const dir = rel.split("/").slice(0, -1).join("/");
    app.appendChild(breadcrumb(root, rel));
    if (meta.kind === "image") {
        const res = await api(rawUrl(root, rel));
        const img = el("img", { class: "img-view", alt: meta.name });
        img.src = URL.createObjectURL(await res.blob());
        app.appendChild(img);
        return;
    }
    if (meta.kind === "pdf") {
        const res = await api(rawUrl(root, rel));
        const frame = el("iframe", { class: "raw-frame", title: meta.name });
        frame.src = URL.createObjectURL(await res.blob());
        app.appendChild(frame);
        return;
    }
    app.appendChild(el("h1", { text: meta.name }));
    app.appendChild(el("p", {
        class: "muted small",
        text: fmtSize(meta.size) + " · " + t("modified") + " " + fmtTime(meta.mtime),
    }));
    const body = el("div", { class: "doc-body" });
    const modeBar = el("div", { class: "mode-bar" });
    const safeBtn = el("button", { type: "button", text: t("safeMode") });
    let fullBtn = null;
    function setMode(mode) {
        safeBtn.className = mode === "safe" ? "active" : "";
        if (fullBtn)
            fullBtn.className = mode === "full" ? "active" : "";
    }
    async function loadText() {
        const res = await api(rawUrl(root, rel));
        return res.text();
    }
    function renderSafe(text) {
        body.innerHTML = "";
        if (meta.kind === "markdown") {
            const html = DOMPurify.sanitize(marked.parse(text), { ADD_ATTR: ["target"] });
            body.innerHTML = html;
            body.querySelectorAll("pre code").forEach((block) => {
                try {
                    hljs.highlightElement(block);
                }
                catch {
                    /* highlighting is best-effort */
                }
            });
        }
        else if (meta.kind === "html") {
            // Collect stylesheet links BEFORE sanitisation (DOMPurify strips <link>);
            // they are inlined afterwards because CSP forbids document-relative loads.
            const rawDoc = new DOMParser().parseFromString(text, "text/html");
            const sheetHrefs = [];
            rawDoc.querySelectorAll('link[rel="stylesheet"]').forEach((l) => {
                const href = (l.getAttribute("href") || "").split("?")[0];
                if (href)
                    sheetHrefs.push(href);
            });
            const clean = DOMPurify.sanitize(text, {
                WHOLE_DOCUMENT: true,
                ADD_TAGS: ["style"],
                ADD_ATTR: ["target"],
            });
            const doc = new DOMParser().parseFromString(clean, "text/html");
            doc.querySelectorAll("style").forEach((s) => {
                body.appendChild(document.importNode(s, true));
            });
            body.insertAdjacentHTML("beforeend", doc.body.innerHTML);
            for (const href of sheetHrefs) {
                if (/^(https?:)/i.test(href))
                    continue; // external styles need full mode
                void api(rawUrl(root, resolveRel(dir, href)))
                    .then((r) => (r.ok ? r.text() : Promise.reject()))
                    .then((css) => {
                    const st = document.createElement("style");
                    st.textContent = css;
                    body.appendChild(st);
                })
                    .catch(() => undefined);
            }
        }
        else {
            const pre = el("pre", {});
            const code = el("code", { text: text });
            const lang = langOf(meta.name);
            if (lang)
                code.className = "language-" + lang;
            pre.appendChild(code);
            body.appendChild(pre);
            try {
                hljs.highlightElement(code);
            }
            catch {
                /* highlighting is best-effort */
            }
        }
        postProcess(body, root, dir);
    }
    async function showSafe() {
        renderSafe(await loadText());
        setMode("safe");
    }
    async function showFull() {
        body.innerHTML = "";
        const ticket = await apiJson("/api/v1/html-ticket?root=" +
            encodeURIComponent(root) +
            "&path=" +
            encodeURIComponent(rel));
        const frame = el("iframe", {
            class: "raw-frame",
            sandbox: "allow-scripts allow-modals allow-forms",
            title: meta.name,
        });
        frame.src =
            "/api/v1/rawhtml?root=" +
                encodeURIComponent(root) +
                "&path=" +
                encodeURIComponent(rel) +
                "&ticket=" +
                encodeURIComponent(ticket.ticket);
        body.appendChild(frame);
        body.appendChild(el("p", { class: "muted small", text: t("fullModeNote") }));
        setMode("full");
    }
    safeBtn.addEventListener("click", () => {
        void showSafe().catch(showError);
    });
    modeBar.appendChild(safeBtn);
    if (meta.kind === "html") {
        fullBtn = el("button", { type: "button", text: t("fullMode") });
        fullBtn.addEventListener("click", () => {
            void showFull().catch(showError);
        });
        modeBar.appendChild(fullBtn);
    }
    const oversized = meta.size > meta.max_render_bytes;
    if (oversized) {
        app.appendChild(el("div", { class: "notice", text: t("oversized") }));
        const forceBtn = el("button", { class: "icon-btn", type: "button", text: t("forceRender") });
        forceBtn.addEventListener("click", () => {
            app.appendChild(modeBar);
            app.appendChild(body);
            forceBtn.remove();
            void showSafe().catch(showError);
        });
        app.appendChild(forceBtn);
        return;
    }
    app.appendChild(modeBar);
    app.appendChild(body);
    await showSafe();
}
// ---------- error & routing ----------
function showError(err) {
    if (err && err.status === 401) {
        location.hash = "#/login";
        return;
    }
    app.innerHTML = "";
    app.appendChild(el("p", {
        class: "error",
        text: t("loadFailed") + ((err && (err.detail || err.message)) || t("unknownError")),
    }));
    app.appendChild(el("p", {}, [el("a", { href: "#/", text: t("backToWorkspaces") })]));
}
async function route() {
    const hash = location.hash || "#/";
    if (!getToken() && hash !== "#/login") {
        location.hash = "#/login";
        return;
    }
    try {
        if (hash === "#/login") {
            renderLogin();
            return;
        }
        if (hash === "#/") {
            await renderRoots();
            return;
        }
        const m = hash.match(/^#\/([bv])\/([^/]+)(?:\/(.*))?$/);
        if (!m) {
            location.hash = "#/";
            return;
        }
        const root = decodeURIComponent(m[2]);
        const rel = m[3] ? m[3].split("/").map(decodeURIComponent).join("/") : "";
        if (m[1] === "b")
            await renderTree(root, rel);
        else
            await renderFile(root, rel);
    }
    catch (err) {
        const e = err;
        if (e && e.status === 401) {
            renderLogin(t("loginInvalid"));
            return;
        }
        showError(e);
    }
}
// ---------- header controls ----------
function refreshHeader() {
    const langBtn = byId("lang-btn");
    langBtn.textContent = t("langBtn");
    langBtn.title = currentLang() === "en" ? "切换到中文" : "Switch to English";
    byId("theme-btn").textContent = themeLabel();
    byId("logout-btn").textContent = t("logout");
}
byId("lang-btn").addEventListener("click", () => {
    localStorage.setItem(LANG_KEY, currentLang() === "en" ? "zh" : "en");
    document.documentElement.lang = currentLang() === "zh" ? "zh-CN" : "en";
    refreshHeader();
    void route();
});
byId("theme-btn").addEventListener("click", () => {
    const order = ["auto", "dark", "light"];
    const cur = localStorage.getItem(THEME_KEY) || "auto";
    const next = order[(order.indexOf(cur) + 1) % order.length];
    localStorage.setItem(THEME_KEY, next);
    applyTheme();
    refreshHeader();
});
byId("logout-btn").addEventListener("click", () => {
    setToken("");
    location.hash = "#/login";
});
applyTheme();
document.documentElement.lang = currentLang() === "zh" ? "zh-CN" : "en";
refreshHeader();
window.addEventListener("hashchange", () => {
    void route();
});
void route();
