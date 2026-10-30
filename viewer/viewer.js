/* Classic script on purpose: file:// pages block modules and fetch(). */
(function () {
  const MM = window.MM;
  const byId = new Map((MM.manifest || []).map((chat) => [chat.id, chat]));
  const pending = {};
  let openId = "";
  let requestToken = 0;
  let scope = "chat";
  let query = "";
  let chatHits = [];
  let chatHitIndex = 0;
  let allHits = [];
  let allHitIndex = -1;
  let searchTimer = 0;
  let scrollTimer = 0;
  let ignoreScroll = false;
  let holdPlace = false;
  const places = new Map();

  window.MM_LOAD = function (data) {
    const id = data && data.channel && data.channel.id;
    if (!id) return;
    MM.chats[id] = data;
    const wait = pending[id];
    if (wait) {
      delete pending[id];
      wait.resolve(data);
    }
  };

  window.MM_SEARCH = function (rows) {
    MM.search = rows || [];
    if (MM._searchResolve) MM._searchResolve(MM.search);
  };

  const transcript = document.getElementById("transcript");
  const results = document.getElementById("results");
  const title = document.getElementById("chat-title");
  const meta = document.getElementById("chat-meta");
  const status = document.getElementById("search-status");
  const searchInput = document.getElementById("search-input");

  document.getElementById("chat-list").innerHTML = renderSidebar(MM.manifest || []);
  document.getElementById("chat-filter").addEventListener("input", filterChats);
  document.getElementById("chat-list").addEventListener("click", (event) => {
    const button = event.target.closest(".chat-button");
    if (!button) return;
    showChannel(button.dataset.id);
  });
  document.getElementById("scope-chat").addEventListener("click", () => setScope("chat"));
  document.getElementById("scope-all").addEventListener("click", () => setScope("all"));
  document.getElementById("search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    step(1);
  });
  searchInput.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(runSearch, 120);
  });
  document.getElementById("search-next").addEventListener("click", () => step(1));
  document.getElementById("search-prev").addEventListener("click", () => step(-1));
  document.getElementById("jump-start").addEventListener("click", () => jumpTo("start"));
  document.getElementById("jump-end").addEventListener("click", () => jumpTo("end"));
  transcript.addEventListener("scroll", notePlace, { passive: true });
  window.addEventListener("scroll", notePlace, { passive: true });
  transcript.addEventListener("wheel", releasePlace, { passive: true });
  transcript.addEventListener("touchmove", releasePlace, { passive: true });
  transcript.addEventListener("pointerdown", releasePlace);
  transcript.addEventListener(
    "load",
    (event) => {
      if (!event.target || event.target.tagName !== "IMG") return;
      holdOpenPlace();
    },
    true
  );
  results.addEventListener("click", (event) => {
    const button = event.target.closest(".result");
    if (!button) return;
    allHitIndex = Number(button.dataset.index);
    openHit(allHits[allHitIndex]);
    renderHits();
  });
  window.addEventListener("hashchange", () => {
    const parsed = parseHash();
    if (!parsed.channelId || !byId.has(parsed.channelId)) return;
    if (parsed.channelId !== openId) showChannel(parsed.channelId, { postId: parsed.postId });
    else if (parsed.postId) focusOpenPost(parsed.postId);
  });

  const initial = parseHash();
  if (initial.channelId && byId.has(initial.channelId)) showChannel(initial.channelId, { postId: initial.postId });

  function renderSidebar(manifest) {
    const teams = new Map();
    const directs = [];
    const groups = [];
    manifest.forEach((chat) => {
      if (chat.type === "D") directs.push(chat);
      else if (chat.type === "G") groups.push(chat);
      else {
        const key = chat.team || "Channels";
        if (!teams.has(key)) teams.set(key, []);
        teams.get(key).push(chat);
      }
    });
    const chunks = [];
    for (const [team, chats] of teams) {
      chunks.push(section(team, chats));
    }
    if (directs.length) chunks.push(section("Direct messages", directs));
    if (groups.length) chunks.push(section("Group messages", groups));
    if (!chunks.length) chunks.push('<p class="empty">No chats saved yet.</p>');
    return chunks.join("");
  }

  function section(label, chats) {
    const buttons = chats
      .slice()
      .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
      .map((chat) => {
        return (
          '<button type="button" class="chat-button" data-id="' +
          escapeHtml(chat.id) +
          '">' +
          escapeHtml(chat.name || chat.id) +
          "</button>"
        );
      })
      .join("");
    return '<div class="group"><div class="group-label">' + escapeHtml(label) + "</div>" + buttons + "</div>";
  }

  function filterChats() {
    const q = document.getElementById("chat-filter").value.trim().toLowerCase();
    document.querySelectorAll(".chat-button").forEach((button) => {
      const chat = byId.get(button.dataset.id);
      const hay = ((chat && (chat.team + " " + chat.name)) || "").toLowerCase();
      const group = button.parentElement;
      button.hidden = q !== "" && !hay.includes(q);
      if (group) {
        const visible = group.querySelector(".chat-button:not([hidden])");
        group.hidden = !visible;
      }
    });
  }

  function showChannel(id, options) {
    const entry = byId.get(id);
    if (!entry) return Promise.resolve();
    options = options || {};
    if (openId && openId !== id) rememberPlace();
    window.clearTimeout(scrollTimer);
    ignoreScroll = true;
    const token = ++requestToken;
    openId = id;
    document.querySelectorAll(".chat-button").forEach((button) => {
      if (button.dataset.id === id) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
    title.textContent = entry.name || "Channels";
    meta.textContent = chatMeta(entry);
    transcript.innerHTML = '<p class="empty">Loading…</p>';
    return loadChat(entry)
      .then((data) => {
        if (token !== requestToken) return;
        renderTranscript(data, entry);
        settle(id, options);
        if (scope === "chat") runSearchNow({ scroll: false });
      })
      .catch((error) => {
        if (token !== requestToken) return;
        transcript.innerHTML = '<p class="empty">' + escapeHtml(error.message || "Could not load this chat") + "</p>";
      })
      .then(() => {
        if (token === requestToken) ignoreScroll = false;
      });
  }

  function chatMeta(entry) {
    const kind = { O: "Public channel", P: "Private channel", D: "Direct message", G: "Group message" }[entry.type] || "Chat";
    const where = entry.team ? entry.team + " · " + kind : kind;
    const count = entry.posts + (entry.posts === 1 ? " post" : " posts");
    return where + " · " + count + (entry.incomplete ? " · still downloading" : "");
  }

  function loadChat(entry) {
    if (MM.chats[entry.id]) return Promise.resolve(MM.chats[entry.id]);
    if (pending[entry.id]) return pending[entry.id].promise;
    let resolve, reject;
    const promise = new Promise((res, rej) => {
      resolve = res;
      reject = rej;
    });
    pending[entry.id] = { promise: promise, resolve: resolve, reject: reject };
    const script = document.createElement("script");
    script.src = entry.file;
    script.onerror = function () {
      delete pending[entry.id];
      reject(new Error("Could not load this chat. Keep index.html next to the chats folder."));
    };
    document.body.appendChild(script);
    return promise;
  }

  function renderTranscript(data, entry) {
    const posts = (data && data.posts) || [];
    const arranged = arrange(posts);
    const parts = [];
    if ((data.channel && data.channel.incomplete) || entry.incomplete) {
      parts.push(
        '<div class="banner">This chat was still downloading when the archive stopped. Run archive.py again to continue.</div>'
      );
    }
    if (!arranged.roots.length) parts.push('<p class="empty">No messages saved in this chat.</p>');
    let previousDay = "";
    let previousAuthor = "";
    arranged.roots.forEach((post) => {
      const day = dayLabel(post.create_at);
      if (day !== previousDay) {
        parts.push('<div class="day">' + escapeHtml(day) + "</div>");
        previousDay = day;
        previousAuthor = "";
      }
      const continued = previousAuthor && previousAuthor === authorKey(post);
      parts.push(renderPost(post, arranged.replies.get(post.id) || [], continued));
      previousAuthor = authorKey(post);
    });
    transcript.innerHTML = parts.join("");
  }

  function arrange(posts) {
    const sorted = posts.filter(shownPost).slice().sort((a, b) => (a.create_at || 0) - (b.create_at || 0) || String(a.id).localeCompare(String(b.id)));
    const known = new Set(sorted.map((post) => post.id));
    const replies = new Map();
    const roots = [];
    sorted.forEach((post) => {
      if (post.root_id && post.root_id !== post.id && known.has(post.root_id)) {
        if (!replies.has(post.root_id)) replies.set(post.root_id, []);
        replies.get(post.root_id).push(post);
      } else {
        roots.push(post);
      }
    });
    return { roots: roots, replies: replies };
  }

  function renderPost(post, replies, continued) {
    const classes = ["post"];
    if (continued) classes.push("continued");
    if (isSystem(post)) classes.push("system");
    const avatar = continued
      ? '<div class="avatar-slot"></div>'
      : '<div class="avatar" style="background:' +
        safeColor(post.color) +
        '">' +
        escapeHtml(post.initial || "?") +
        "</div>";
    const who = continued
      ? ""
      : '<div class="who"><strong>' +
        escapeHtml(post.display_name || "unknown") +
        '</strong><a class="when" href="' +
        postHref(post) +
        '" title="' +
        escapeHtml(stampTitle(post.create_at)) +
        '">' +
        escapeHtml(timeLabel(post.create_at)) +
        "</a>" +
        (post.edit_at ? '<span class="tag">edited</span>' : "") +
        (post.delete_at ? '<span class="tag">deleted</span>' : "") +
        "</div>";
    let body = post.message || "";
    if (!body && post.delete_at) body = "(message deleted)";
    const repliesHtml = replies.length
      ? '<div class="replies">' + replies.map((reply) => renderPost(reply, [], false)).join("") + "</div>"
      : "";
    return (
      '<article class="' +
      classes.join(" ") +
      '" id="post-' +
      escapeHtml(post.id) +
      '">' +
      avatar +
      '<div class="post-body">' +
      who +
      '<div class="text">' +
      renderMarkdown(body) +
      "</div>" +
      renderFiles(post.files || []) +
      renderReactions(post) +
      repliesHtml +
      "</div></article>"
    );
  }

  function renderFiles(files) {
    if (!files.length) return "";
    const items = files.map((file) => {
      const href = fileHref(file.local_path);
      const name = escapeHtml(file.name || "file");
      const size = file.size ? " (" + escapeHtml(formatSize(file.size)) + ")" : "";
      if (!href) return '<span class="file-link">' + name + size + "</span>";
      const mime = file.mime_type || "";
      let preview = "";
      if (mime.indexOf("image/") === 0) preview = '<a href="' + href + '"><img src="' + href + '" alt="' + name + '"></a>';
      else if (mime.indexOf("video/") === 0) preview = '<video controls src="' + href + '"></video>';
      else if (mime.indexOf("audio/") === 0) preview = '<audio controls src="' + href + '"></audio>';
      return preview + '<a class="file-link" href="' + href + '">' + name + size + "</a>";
    });
    return '<div class="files">' + items.join("") + "</div>";
  }

  function renderReactions(post) {
    const reactions = (post.metadata && post.metadata.reactions) || [];
    if (!reactions.length) return "";
    const counts = new Map();
    reactions.forEach((reaction) => {
      const name = reaction.emoji_name || "reaction";
      counts.set(name, (counts.get(name) || 0) + 1);
    });
    const chips = [];
    counts.forEach((count, name) => {
      chips.push('<span class="reaction">:' + escapeHtml(name) + ": " + count + "</span>");
    });
    return '<div class="reactions">' + chips.join("") + "</div>";
  }

  function setScope(next) {
    scope = next;
    document.getElementById("scope-chat").setAttribute("aria-pressed", next === "chat" ? "true" : "false");
    document.getElementById("scope-all").setAttribute("aria-pressed", next === "all" ? "true" : "false");
    runSearch();
  }

  function runSearch() {
    window.clearTimeout(searchTimer);
    runSearchNow();
  }

  function runSearchNow(options) {
    query = searchInput.value.trim();
    clearMarks(transcript);
    clearMatchClasses();
    if (!query) {
      results.hidden = true;
      results.innerHTML = "";
      status.textContent = "";
      chatHits = [];
      allHits = [];
      return;
    }
    if (scope === "chat") searchThisChat(options);
    else searchEverything();
  }

  function searchThisChat(options) {
    results.hidden = true;
    results.innerHTML = "";
    const data = MM.chats[openId];
    if (!data) {
      status.textContent = "Open a chat, or switch to Everything.";
      return;
    }
    const q = query.toLowerCase();
    chatHits = (data.posts || []).filter((post) => {
      if (!shownPost(post)) return false;
      return haystack(post).toLowerCase().includes(q);
    });
    chatHitIndex = 0;
    chatHits.forEach((post, index) => {
      const el = document.getElementById("post-" + post.id);
      if (!el) return;
      el.classList.add("is-match");
      if (index === 0) el.classList.add("is-current");
      markElement(el, query);
    });
    status.textContent = chatHits.length ? "1 of " + chatHits.length + " in this chat" : "No matches in this chat";
    if (options && options.scroll === false) return;
    const current = chatHits[0] && document.getElementById("post-" + chatHits[0].id);
    if (current) current.scrollIntoView({ block: "center" });
  }

  function searchEverything() {
    status.textContent = "Loading the archive index…";
    loadSearchIndex()
      .then((rows) => {
        if (searchInput.value.trim() !== query || scope !== "all") return;
        const q = query.toLowerCase();
        allHits = [];
        rows.forEach((row) => {
          const inMessage = (row.m || "").toLowerCase().includes(q);
          const fileHit = (row.f || []).find((name) => (name || "").toLowerCase().includes(q)) || "";
          if (!inMessage && !fileHit) return;
          allHits.push({ row: row, inMessage: inMessage, fileHit: fileHit });
        });
        allHitIndex = -1;
        renderHits();
      })
      .catch(() => {
        status.textContent = "Could not load search.js";
      });
  }

  function renderHits() {
    const shown = allHits.slice(0, 80);
    results.hidden = shown.length === 0;
    results.innerHTML = shown
      .map((hit, index) => {
        const chat = byId.get(hit.row.c);
        const where = chat ? (chat.team ? chat.team + " / " + chat.name : chat.name) : hit.row.c;
        const bits = [];
        if (hit.inMessage) bits.push(highlightHtml(snippet(hit.row.m, query), query));
        if (hit.fileHit) bits.push(highlightHtml(hit.fileHit, query));
        return (
          '<button type="button" class="result" data-index="' +
          index +
          (index === allHitIndex ? '" aria-current="true"' : '"') +
          "><div class=\"where\">" +
          escapeHtml(hit.row.u || "unknown") +
          " · " +
          escapeHtml(where) +
          " · " +
          escapeHtml(dayLabel(hit.row.t) + " " + timeLabel(hit.row.t)) +
          '</div><p>' +
          bits.join("<br>") +
          "</p></button>"
        );
      })
      .join("");
    if (!allHits.length) status.textContent = "No matches";
    else if (allHits.length > shown.length) status.textContent = "Showing " + shown.length + " of " + allHits.length;
    else status.textContent = allHits.length + (allHits.length === 1 ? " match" : " matches");
  }

  function step(direction) {
    query = searchInput.value.trim();
    if (!query) return;
    if (scope === "chat") {
      if (!chatHits.length) return;
      chatHitIndex = (chatHitIndex + direction + chatHits.length) % chatHits.length;
      focusChatHit();
      return;
    }
    if (!allHits.length) return;
    if (allHitIndex < 0) allHitIndex = direction > 0 ? 0 : allHits.length - 1;
    else allHitIndex = (allHitIndex + direction + allHits.length) % allHits.length;
    openHit(allHits[allHitIndex]);
    renderHits();
  }

  function focusChatHit() {
    document.querySelectorAll(".post.is-current").forEach((el) => el.classList.remove("is-current"));
    const post = chatHits[chatHitIndex];
    const el = post && document.getElementById("post-" + post.id);
    if (!el) return;
    el.classList.add("is-current");
    markElement(el, query);
    el.scrollIntoView({ block: "center" });
    status.textContent = chatHitIndex + 1 + " of " + chatHits.length + " in this chat";
  }

  function openHit(hit) {
    if (!hit) return;
    const postId = hit.row.p;
    showChannel(hit.row.c, { postId: postId }).then(() => focusOpenPost(postId));
  }

  function focusOpenPost(postId) {
    if (!postId) return false;
    const el = document.getElementById("post-" + postId);
    if (!el) return false;
    const posts = transcript.querySelectorAll("article.post");
    const box = scroller();
    if (el === posts[0]) box.scrollTop = 0;
    else if (el === posts[posts.length - 1]) box.scrollTop = box.scrollHeight;
    else el.scrollIntoView({ block: "start" });
    document.querySelectorAll(".post.is-current").forEach((node) => node.classList.remove("is-current"));
    el.classList.add("is-match", "is-current");
    markElement(el, query);
    setHash(openId, postId);
    return true;
  }

  function loadSearchIndex() {
    if (MM.search) return Promise.resolve(MM.search);
    if (MM._searchPromise) return MM._searchPromise;
    MM._searchPromise = new Promise((resolve, reject) => {
      MM._searchResolve = resolve;
      const script = document.createElement("script");
      script.src = "search.js";
      script.onerror = () => reject(new Error("search"));
      document.body.appendChild(script);
    });
    return MM._searchPromise;
  }

  function haystack(post) {
    const names = (post.files || []).map((file) => file.name || "").join("\n");
    return (post.message || "") + "\n" + names;
  }

  function isSystem(post) {
    return typeof post.type === "string" && post.type.indexOf("system_") === 0;
  }

  function shownPost(post) {
    return !!MM.showSystem || !isSystem(post);
  }

  function authorKey(post) {
    return (post.user_id || "") + "|" + (post.display_name || "");
  }

  function dayLabel(ms) {
    if (!ms) return "";
    return new Date(ms).toLocaleDateString(undefined, { weekday: "short", year: "numeric", month: "short", day: "numeric" });
  }

  function stampTitle(ms) {
    if (!ms) return "";
    const date = new Date(ms);
    const pad = (n) => String(n).padStart(2, "0");
    return (
      date.getFullYear() +
      "-" +
      pad(date.getMonth() + 1) +
      "-" +
      pad(date.getDate()) +
      " " +
      pad(date.getHours()) +
      ":" +
      pad(date.getMinutes()) +
      ":" +
      pad(date.getSeconds())
    );
  }

  function postHref(post) {
    return "#" + encodeURIComponent(openId) + "/" + encodeURIComponent(post.id);
  }

  function parseHash() {
    let raw = location.hash.replace(/^#/, "");
    try {
      raw = decodeURIComponent(raw);
    } catch (error) {
      raw = location.hash.replace(/^#/, "");
    }
    const slash = raw.indexOf("/");
    if (slash === -1) return { channelId: raw, postId: "" };
    return { channelId: raw.slice(0, slash), postId: raw.slice(slash + 1) };
  }

  function scroller() {
    if (transcript.scrollHeight > transcript.clientHeight + 1) return transcript;
    return document.scrollingElement || document.documentElement;
  }

  function edgePost(which) {
    const posts = transcript.querySelectorAll("article.post");
    if (!posts.length) return "";
    const el = which === "start" ? posts[0] : posts[posts.length - 1];
    return el.id.replace(/^post-/, "");
  }

  function postAtTop() {
    const posts = transcript.querySelectorAll("article.post");
    if (!posts.length) return "";
    const edge = scroller() === transcript ? transcript.getBoundingClientRect().top : 0;
    for (let i = 0; i < posts.length; i++) {
      if (posts[i].getBoundingClientRect().bottom > edge + 4) return posts[i].id.replace(/^post-/, "");
    }
    return posts[posts.length - 1].id.replace(/^post-/, "");
  }

  function notePlace() {
    if (ignoreScroll || holdPlace || !openId) return;
    window.clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(rememberPlace, 80);
  }

  function releasePlace() {
    holdPlace = false;
  }

  function rememberPlace() {
    if (!openId) return;
    const saved = capturePlace();
    places.set(openId, saved);
    if (saved.postId) setHash(openId, saved.postId);
  }

  function capturePlace() {
    const box = scroller();
    const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 2;
    const atStart = box.scrollTop <= 2;
    const postId = atEnd ? edgePost("end") : atStart ? edgePost("start") : postAtTop();
    const el = postId && document.getElementById("post-" + postId);
    const origin = box === transcript ? box.getBoundingClientRect().top : 0;
    const offset = el ? el.getBoundingClientRect().top - origin : 0;
    return { top: box.scrollTop, postId: postId, offset: offset, atEnd: atEnd, atStart: atStart };
  }

  function applyPlace(saved) {
    const box = scroller();
    ignoreScroll = true;
    if (!saved) box.scrollTop = 0;
    else if (saved.atEnd) box.scrollTop = box.scrollHeight;
    else if (saved.atStart) box.scrollTop = 0;
    else {
      const el = saved.postId && document.getElementById("post-" + saved.postId);
      if (!el) box.scrollTop = saved.top || 0;
      else {
        const origin = box === transcript ? box.getBoundingClientRect().top : 0;
        box.scrollTop += el.getBoundingClientRect().top - origin - saved.offset;
      }
    }
    ignoreScroll = false;
  }

  function holdOpenPlace() {
    if (!holdPlace || !openId) return;
    const saved = places.get(openId);
    if (!saved) return;
    applyPlace(saved);
  }

  function settle(id, options) {
    if (options.postId && focusOpenPost(options.postId)) {
      places.set(id, capturePlace());
      holdPlace = true;
      return;
    }
    const saved = places.get(id);
    if (saved) {
      applyPlace(saved);
      setHash(id, saved.postId);
      holdPlace = true;
      return;
    }
    jumpTo(MM.openAt === "start" ? "start" : "end");
    holdPlace = true;
  }

  function jumpTo(which) {
    if (!openId) return;
    holdPlace = false;
    if (!transcript.querySelector("article.post")) {
      setHash(openId, "");
      return;
    }
    const box = scroller();
    ignoreScroll = true;
    box.scrollTop = which === "start" ? 0 : box.scrollHeight;
    ignoreScroll = false;
    rememberPlace();
    holdPlace = true;
  }

  function timeLabel(ms) {
    if (!ms) return "";
    return new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  function formatSize(bytes) {
    const size = Number(bytes) || 0;
    if (size < 1024) return size + " B";
    if (size < 1024 * 1024) return (size / 1024).toFixed(1) + " KB";
    return (size / 1024 / 1024).toFixed(1) + " MB";
  }

  function fileHref(path) {
    const parts = String(path || "").split("/");
    if (parts[0] !== "media" || parts.some((part) => part === "" || part === "." || part === "..")) return "";
    return parts.map(encodeURIComponent).join("/");
  }

  function snippet(text, q) {
    const hay = text || "";
    const at = hay.toLowerCase().indexOf(q.toLowerCase());
    if (at < 0) return hay.slice(0, 140);
    const start = Math.max(0, at - 40);
    const end = Math.min(hay.length, at + q.length + 80);
    let piece = hay.slice(start, end);
    if (start > 0) piece = "…" + piece;
    if (end < hay.length) piece += "…";
    return piece;
  }

  function highlightHtml(text, q) {
    const escaped = escapeHtml(text);
    const needle = escapeHtml(q);
    if (!needle) return escaped;
    const pattern = new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig");
    return escaped.replace(pattern, (match) => '<mark class="match">' + match + "</mark>");
  }

  function clearMatchClasses() {
    document.querySelectorAll(".post.is-match, .post.is-current").forEach((el) => {
      el.classList.remove("is-match", "is-current");
    });
  }

  function clearMarks(root) {
    root.querySelectorAll("mark.match").forEach((mark) => {
      const parent = mark.parentNode;
      parent.replaceChild(document.createTextNode(mark.textContent), mark);
      parent.normalize();
    });
  }

  function markElement(root, q) {
    if (!q) return;
    const needle = q.toLowerCase();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      if (!node.nodeValue || node.nodeValue.toLowerCase().indexOf(needle) === -1) return;
      if (node.parentElement && node.parentElement.closest("mark, script, style, .avatar")) return;
      const frag = document.createDocumentFragment();
      let rest = node.nodeValue;
      let lower = rest.toLowerCase();
      while (rest) {
        const at = lower.indexOf(needle);
        if (at === -1) {
          frag.appendChild(document.createTextNode(rest));
          break;
        }
        if (at > 0) frag.appendChild(document.createTextNode(rest.slice(0, at)));
        const mark = document.createElement("mark");
        mark.className = "match";
        mark.textContent = rest.slice(at, at + q.length);
        frag.appendChild(mark);
        rest = rest.slice(at + q.length);
        lower = rest.toLowerCase();
      }
      node.parentNode.replaceChild(frag, node);
    });
  }

  function setHash(channelId, postId) {
    if (!channelId) return;
    const next = "#" + encodeURIComponent(channelId) + (postId ? "/" + encodeURIComponent(postId) : "");
    if (location.hash === next) return;
    try {
      history.replaceState(null, "", next);
    } catch (error) {
      location.hash = next;
    }
  }

  function renderMarkdown(source) {
    const text = String(source || "");
    if (!window.commonmark || !window.MMMarkdown) {
      return escapeHtml(text).replace(/\n/g, "<br>\n");
    }
    return MMMarkdown.render(window.commonmark, text, safeUrl);
  }

  function safeUrl(url) {
    const value = String(url || "").trim();
    if (/^https?:\/\//i.test(value)) return value;
    if (/^media\/[A-Za-z0-9_-]+\/[A-Za-z0-9_-]+\/[^/\s]+$/.test(value)) return value;
    if (/^media\/[A-Za-z0-9_-]+\/[^/\s]+$/.test(value)) return value;
    return "";
  }

  function safeColor(value) {
    const text = String(value || "");
    if (/^hsl\(\d{1,3}, \d{1,3}%, \d{1,3}%\)$/.test(text)) return text;
    return "hsl(215, 40%, 40%)";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
