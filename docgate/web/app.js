/* docgate 移动端查看器 —— 零依赖 SPA。
 * 渲染管线：marked → DOMPurify → 注入；HTML 完整模式走一次性 ticket + 沙箱 iframe。
 * CSP 保证即使清洗漏网，脚本也不会在本源执行。 */
(function () {
  "use strict";

  var TOKEN_KEY = "docgate.token";
  var THEME_KEY = "docgate.theme";
  var app = document.getElementById("app");

  // ---------- token ----------

  function getToken() { return localStorage.getItem(TOKEN_KEY) || ""; }
  function setToken(t) {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  }

  // ---------- API ----------

  async function api(path) {
    var res = await fetch(path, {
      headers: { "Authorization": "Bearer " + getToken() },
      credentials: "omit",
    });
    if (res.status === 401 || res.status === 429) {
      var err = new Error("auth");
      err.status = res.status;
      throw err;
    }
    return res;
  }

  async function apiJson(path) {
    var res = await api(path);
    if (!res.ok) {
      var e = new Error("http");
      e.status = res.status;
      try { e.detail = (await res.json()).error || ""; } catch (_) { e.detail = ""; }
      throw e;
    }
    return res.json();
  }

  // ---------- 主题 ----------

  function applyTheme() {
    var t = localStorage.getItem(THEME_KEY) || "auto";
    if (t === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
  }
  document.getElementById("theme-btn").addEventListener("click", function () {
    var order = ["auto", "dark", "light"];
    var cur = localStorage.getItem(THEME_KEY) || "auto";
    var next = order[(order.indexOf(cur) + 1) % order.length];
    localStorage.setItem(THEME_KEY, next);
    applyTheme();
    this.textContent = "主题:" + next;
  });
  applyTheme();

  document.getElementById("logout-btn").addEventListener("click", function () {
    setToken("");
    location.hash = "#/login";
  });

  // ---------- 工具 ----------

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "class") node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { node.appendChild(c); });
    return node;
  }

  function fmtSize(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(1) + " MB";
  }

  function fmtTime(ts) {
    var d = new Date(ts * 1000);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0") + " " + String(d.getHours()).padStart(2, "0") + ":" +
      String(d.getMinutes()).padStart(2, "0");
  }

  function resolveRel(dir, target) {
    // 相对路径解析（POSIX 风格），返回发布根内的相对路径
    var parts = (dir ? dir.split("/") : []).filter(Boolean);
    var segs = target.split("/");
    for (var i = 0; i < segs.length; i++) {
      var s = segs[i];
      if (s === "" || s === ".") continue;
      if (s === "..") { parts.pop(); continue; }
      parts.push(s);
    }
    return parts.join("/");
  }

  function extOf(name) {
    var i = name.lastIndexOf(".");
    return i > 0 ? name.slice(i + 1).toLowerCase() : "";
  }

  function langOf(name) {
    var map = { md: "markdown", py: "python", js: "javascript", ts: "typescript",
      sh: "bash", yml: "yaml", json: "json", html: "xml", xml: "xml", css: "css",
      rs: "rust", go: "go", java: "java", sql: "sql", c: "c", cpp: "cpp", h: "c" };
    return map[extOf(name)] || "";
  }

  // ---------- 渲染后处理：链接改写与图片认证加载 ----------

  function postProcess(container, root, dir, isMarkdown) {
    container.querySelectorAll("a[href]").forEach(function (a) {
      var href = a.getAttribute("href") || "";
      if (/^(https?:|mailto:|tel:)/i.test(href)) {
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener noreferrer");
        return;
      }
      if (href.charAt(0) === "#") return; // 页内锚点
      var clean = href.split("#")[0].split("?")[0];
      if (!clean) return;
      if (clean.endsWith("/")) {
        var dirRel = resolveRel(dir, clean);
        a.setAttribute("href", "#/b/" + encodeURIComponent(root) + "/" + dirRel.split("/").map(encodeURIComponent).join("/"));
        return;
      }
      var rel = resolveRel(dir, clean);
      var kind = isViewable(extOf(rel));
      if (kind) {
        a.setAttribute("href", "#/v/" + encodeURIComponent(root) + "/" + rel.split("/").map(encodeURIComponent).join("/"));
      } else {
        a.removeAttribute("href");
      }
    });
    container.querySelectorAll("img[src]").forEach(function (img) {
      var src = img.getAttribute("src") || "";
      if (/^(https?:|data:|blob:)/i.test(src)) return;
      var rel = resolveRel(dir, src.split("?")[0]);
      api("/api/v1/raw?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel))
        .then(function (res) {
          if (!res.ok) throw new Error("img");
          return res.blob();
        })
        .then(function (blob) { img.src = URL.createObjectURL(blob); })
        .catch(function () { img.alt = (img.alt || "") + "（图片加载失败）"; });
    });
  }

  function isViewable(ext) {
    return ["md", "markdown", "mdown", "mkd", "html", "htm", "txt", "rst", "adoc", "org",
      "csv", "tsv", "json", "yaml", "yml", "toml", "ini", "cfg", "conf", "log", "text",
      "py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "css", "scss", "less", "java", "kt",
      "go", "rs", "rb", "php", "swift", "c", "h", "cc", "cpp", "hpp", "sh", "bash", "zsh",
      "sql", "xml", "vue", "svelte", "lua", "pl", "r", "dart", "ipynb", "png", "jpg",
      "jpeg", "gif", "webp", "bmp", "avif", "ico", "svg", "pdf"].indexOf(ext) >= 0;
  }

  // ---------- 页面：登录 ----------

  function renderLogin(message) {
    app.innerHTML = "";
    var input = el("input", { type: "password", placeholder: "粘贴访问 token", autocomplete: "current-password" });
    input.value = getToken();
    var err = el("p", { class: "error", text: message || "" });
    if (!message) err.style.display = "none";
    var form = el("form", { class: "token-form" }, [
      input,
      el("button", { type: "submit", text: "进入" }),
    ]);
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      setToken(input.value.trim());
      location.hash = "#/";
      route();
    });
    app.appendChild(el("h1", { text: "docgate" }));
    app.appendChild(el("p", { class: "muted", text: "workspace 文档只读查看。输入 PC 端生成的访问 token；它只保存在本机浏览器。" }));
    app.appendChild(err);
    app.appendChild(form);
  }

  // ---------- 页面：发布根列表 ----------

  async function renderRoots() {
    var data = await apiJson("/api/v1/roots");
    app.innerHTML = "";
    app.appendChild(el("h1", { text: "工作区" }));
    app.appendChild(el("p", { class: "muted small", text: "只显示已显式发布的目录。" }));
    var list = el("div", { class: "list" });
    if (!data.roots.length) {
      list.appendChild(el("div", { class: "panel", text: "还没有发布任何目录。在 PC 上运行：python3 -m docgate publish <目录>" }));
    }
    data.roots.forEach(function (r) {
      var item = el("a", { class: "list-item", href: "#/b/" + encodeURIComponent(r.name) }, [
        el("div", { class: "glyph", text: "📁" }),
        el("div", { class: "body" }, [
          el("div", { class: "name", text: r.name }),
          el("div", { class: "sub", text: r.path + (r.docs_only ? " · docs-only" : "") }),
        ]),
        el("div", { class: "chev", text: "›" }),
      ]);
      list.appendChild(item);
    });
    app.appendChild(list);
  }

  // ---------- 页面：目录浏览 ----------

  async function renderTree(root, rel) {
    var data = await apiJson("/api/v1/tree?root=" + encodeURIComponent(root) +
      "&path=" + encodeURIComponent(rel));
    app.innerHTML = "";
    app.appendChild(breadcrumb(root, rel));
    var list = el("div", { class: "list" });
    if (!data.entries.length) {
      list.appendChild(el("div", { class: "panel", text: "空目录" }));
    }
    var glyphs = { dir: "📁", markdown: "📝", html: "🌐", text: "📄", image: "🖼", pdf: "📕" };
    data.entries.forEach(function (e) {
      var route = (e.kind === "dir" ? "#/b/" : "#/v/") + encodeURIComponent(root) + "/" +
        e.path.split("/").map(encodeURIComponent).join("/");
      var item = el("a", { class: "list-item", href: route }, [
        el("div", { class: "glyph", text: glyphs[e.kind] || "📄" }),
        el("div", { class: "body" }, [
          el("div", { class: "name", text: e.name }),
          el("div", { class: "sub", text: e.kind === "dir" ? fmtTime(e.mtime) : fmtSize(e.size) + " · " + fmtTime(e.mtime) }),
        ]),
        el("div", { class: "chev", text: "›" }),
      ]);
      list.appendChild(item);
    });
    app.appendChild(list);
  }

  function breadcrumb(root, rel) {
    var wrap = el("div", { class: "breadcrumb" });
    wrap.appendChild(el("a", { href: "#/", text: "工作区" }));
    wrap.appendChild(el("span", { class: "sep", text: "/" }));
    wrap.appendChild(el("a", { href: "#/b/" + encodeURIComponent(root), text: root }));
    var parts = rel ? rel.split("/").filter(Boolean) : [];
    var acc = [];
    parts.forEach(function (p, i) {
      acc.push(p);
      wrap.appendChild(el("span", { class: "sep", text: "/" }));
      var isLast = i === parts.length - 1;
      wrap.appendChild(isLast
        ? el("span", { text: p })
        : el("a", { href: "#/b/" + encodeURIComponent(root) + "/" + acc.map(encodeURIComponent).join("/"), text: p }));
    });
    return wrap;
  }

  // ---------- 页面：文件查看 ----------

  async function renderFile(root, rel) {
    var meta = await apiJson("/api/v1/meta?root=" + encodeURIComponent(root) +
      "&path=" + encodeURIComponent(rel));
    app.innerHTML = "";
    var dir = rel.split("/").slice(0, -1).join("/");
    app.appendChild(breadcrumb(root, rel));

    if (meta.kind === "image") {
      var res = await api("/api/v1/raw?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel));
      var img = el("img", { class: "img-view", alt: meta.name });
      img.src = URL.createObjectURL(await res.blob());
      app.appendChild(img);
      return;
    }
    if (meta.kind === "pdf") {
      var pres = await api("/api/v1/raw?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel));
      var frame = el("iframe", { class: "raw-frame", title: meta.name });
      frame.src = URL.createObjectURL(await pres.blob());
      app.appendChild(frame);
      return;
    }

    app.appendChild(el("h1", { text: meta.name }));
    app.appendChild(el("p", { class: "muted small", text: fmtSize(meta.size) + " · 修改于 " + fmtTime(meta.mtime) }));

    var oversized = meta.size > meta.max_render_bytes;
    var body = el("div", { class: "doc-body" });
    var modeBar = el("div", { class: "mode-bar" });

    async function loadText() {
      var res = await api("/api/v1/raw?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel));
      return res.text();
    }

    function renderSafe(text) {
      if (meta.kind === "markdown") {
        var html = DOMPurify.sanitize(window.marked.parse(text), { ADD_ATTR: ["target"] });
        body.innerHTML = html;
        body.querySelectorAll("pre code").forEach(function (block) {
          try { hljs.highlightElement(block); } catch (_) {}
        });
        postProcess(body, root, dir, true);
      } else if (meta.kind === "html") {
        // 先从原文收集外链样式表（DOMPurify 会剥掉 <link>，需提前截获后内联）
        var rawDoc = new DOMParser().parseFromString(text, "text/html");
        var sheetHrefs = [];
        rawDoc.querySelectorAll('link[rel="stylesheet"]').forEach(function (l) {
          var h = (l.getAttribute("href") || "").split("?")[0];
          if (h) sheetHrefs.push(h);
        });
        var clean = DOMPurify.sanitize(text, { WHOLE_DOCUMENT: true, ADD_TAGS: ["style"], ADD_ATTR: ["target"] });
        var doc = new DOMParser().parseFromString(clean, "text/html");
        body.innerHTML = "";
        doc.querySelectorAll("style").forEach(function (s) { body.appendChild(document.importNode(s, true)); });
        body.insertAdjacentHTML("beforeend", doc.body.innerHTML);
        sheetHrefs.forEach(function (href) {
          if (/^(https?:)/i.test(href)) return; // CSP 拦截外站样式，完整模式可用
          api("/api/v1/raw?root=" + encodeURIComponent(root) + "&path=" +
              encodeURIComponent(resolveRel(dir, href)))
            .then(function (r) { return r.ok ? r.text() : Promise.reject(); })
            .then(function (css) {
              var st = document.createElement("style");
              st.textContent = css;
              body.appendChild(st);
            })
            .catch(function () {});
        });
        postProcess(body, root, dir, false);
      } else {
        var pre = el("pre", {});
        var code = el("code", { text: text });
        if (langOf(meta.name)) code.className = "language-" + langOf(meta.name);
        pre.appendChild(code);
        body.innerHTML = "";
        body.appendChild(pre);
        try { hljs.highlightElement(code); } catch (_) {}
      }
    }

    async function showSafe() {
      var text = await loadText();
      renderSafe(text);
      setMode("safe");
    }

    async function showFull() {
      body.innerHTML = "";
      var tdata = await apiJson("/api/v1/html-ticket?root=" + encodeURIComponent(root) +
        "&path=" + encodeURIComponent(rel));
      var frame = el("iframe", {
        class: "raw-frame",
        sandbox: "allow-scripts allow-modals allow-forms",
        title: meta.name,
      });
      frame.src = "/api/v1/rawhtml?root=" + encodeURIComponent(root) + "&path=" +
        encodeURIComponent(rel) + "&ticket=" + encodeURIComponent(tdata.ticket);
      body.appendChild(frame);
      body.appendChild(el("p", { class: "muted small",
        text: "完整模式：脚本运行在沙箱里（无本源权限），30 秒内有效的一次性票据已使用。" }));
      setMode("full");
    }

    var safeBtn = el("button", { type: "button", text: "安全渲染" });
    safeBtn.addEventListener("click", function () {
      showSafe().catch(showError);
    });
    modeBar.appendChild(safeBtn);
    var fullBtn = null;
    if (meta.kind === "html") {
      fullBtn = el("button", { type: "button", text: "完整模式（脚本沙箱）" });
      fullBtn.addEventListener("click", function () {
        showFull().catch(showError);
      });
      modeBar.appendChild(fullBtn);
    }

    function setMode(mode) {
      safeBtn.className = mode === "safe" ? "active" : "";
      if (fullBtn) fullBtn.className = mode === "full" ? "active" : "";
    }

    if (oversized) {
      app.appendChild(el("div", { class: "notice",
        text: "文件 " + fmtSize(meta.size) + " 超过渲染上限 " + fmtSize(meta.max_render_bytes) + "，点下方按钮仍可渲染（可能较慢）。" }));
      var forceBtn = el("button", { class: "icon-btn", type: "button", text: "仍然渲染" });
      forceBtn.addEventListener("click", function () {
        app.appendChild(modeBar);
        app.appendChild(body);
        forceBtn.remove();
        showSafe().catch(showError);
      });
      app.appendChild(forceBtn);
      return;
    }

    app.appendChild(modeBar);
    app.appendChild(body);
    await showSafe();
  }

  // ---------- 路由 ----------

  function showError(err) {
    if (err && err.status === 401) {
      location.hash = "#/login";
      return;
    }
    app.innerHTML = "";
    app.appendChild(el("p", { class: "error", text: "加载失败：" + ((err && err.detail) || (err && err.message) || "未知错误") }));
    app.appendChild(el("p", {}, [el("a", { href: "#/", text: "返回工作区列表" })]));
  }

  async function route() {
    var hash = location.hash || "#/";
    if (!getToken() && hash !== "#/login") { location.hash = "#/login"; return; }
    try {
      if (hash === "#/login" || hash === "#/") {
        if (hash === "#/login") { renderLogin(); return; }
        await renderRoots();
        return;
      }
      var m = hash.match(/^#\/([bv])\/([^/]+)(?:\/(.*))?$/);
      if (!m) { location.hash = "#/"; return; }
      var root = decodeURIComponent(m[1] === "b" ? m[2] : m[2]);
      var rel = m[3] ? m[3].split("/").map(decodeURIComponent).join("/") : "";
      if (m[1] === "b") await renderTree(root, rel);
      else await renderFile(root, rel);
    } catch (err) {
      if (err && err.status === 401) {
        renderLogin("token 无效或已失效，请重新输入");
        return;
      }
      showError(err);
    }
  }

  window.addEventListener("hashchange", route);
  route();
})();
