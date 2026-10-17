/* Focus Ledger web: local time everywhere, station clocks, and the timetables.
   Every name that comes from the server is inserted as text, never as markup. */
(() => {
  "use strict";
  const doc = document;
  const SVG = "http://www.w3.org/2000/svg";
  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  const BOARD_POLL = 30;
  const LIVE_POLL = 10;
  // Wider ranges scan more rows on the server and change more slowly, so they refresh less often.
  const PERSON_POLL = { day: 60, week: 300, month: 300, year: 900 };
  let realtime = null;

  // ——— DOM ———
  function h(tag, props, ...children) {
    const node = doc.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value == null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "onclick") node.addEventListener("click", value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child != null && child !== false) node.append(child instanceof Node ? child : String(child));
    }
    return node;
  }
  function s(tag, attrs) {
    const node = doc.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attrs || {})) if (value != null) node.setAttribute(key, value);
    return node;
  }
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const stagger = (node, index) => { node.style.setProperty("--i", index); return node; };
  const appColor = (colors, index) => colors && colors[index] || "slate";
  const swatch = color => h("i", { class: "app-swatch app-color", "data-color": color, "aria-hidden": "true" });
  /** Entrance animations play only while a container is marked as entering; later redraws stay still. */
  function enter(node, ms = 2400) {
    if (calm.matches) return;
    node.classList.add("is-entering");
    clearTimeout(node._entering);
    node._entering = setTimeout(() => node.classList.remove("is-entering"), ms);
  }
  /** Re-rendering replaces nodes; put keyboard focus back on the element with the same key. */
  function keepFocus(render) {
    const key = doc.activeElement && doc.activeElement.dataset ? doc.activeElement.dataset.key : null;
    render();
    if (key) {
      const again = doc.querySelector(`[data-key="${CSS.escape(key)}"]`);
      if (again) again.focus({ preventScroll: true });
    }
  }

  // ——— Time: the server's clock, the viewer's zone ———
  let skew = 0;
  const now = () => Date.now() / 1000 + skew;
  const sync = serverNow => { if (Number.isFinite(serverNow)) skew = serverNow - Date.now() / 1000; };
  const pad = n => String(n).padStart(2, "0");
  const at = t => new Date(t * 1000);
  const WEEK = "日一二三四五六";
  function midnight(t, addDays = 0) {
    const d = at(t);
    d.setHours(0, 0, 0, 0);
    if (addDays) d.setDate(d.getDate() + addDays);
    return d.getTime() / 1000;
  }
  function hourOf(dayStart, hour) {
    const d = at(dayStart);
    d.setHours(hour, 0, 0, 0);
    return d.getTime() / 1000;
  }
  const hm = t => { const d = at(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const md = t => { const d = at(t); return `${d.getMonth() + 1}月${d.getDate()}日`; };
  const weekday = (t, long) => (long ? "星期" : "周") + WEEK[at(t).getDay()];
  const isoDay = t => { const d = at(t); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  function parseDay(text) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text || "");
    if (!m) return null;
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    return Number.isNaN(d.getTime()) ? null : d.getTime() / 1000;
  }
  function when(t) {
    if (t >= midnight(now())) return hm(t);
    if (t >= midnight(now(), -1)) return `昨天 ${hm(t)}`;
    return `${md(t)} ${hm(t)}`;
  }
  function ago(t) {
    const gone = now() - t;
    if (gone < 45) return "刚刚";
    if (gone < 3600) return `${Math.round(gone / 60)} 分钟前`;
    if (gone < 86400) return `${Math.floor(gone / 3600)} 小时前`;
    return `${Math.floor(gone / 86400)} 天前`;
  }
  function span(seconds) {
    const sec = Math.max(0, Math.round(seconds));
    if (sec < 60) return `${sec}秒`;
    const hours = Math.floor(sec / 3600), minutes = Math.floor(sec % 3600 / 60);
    if (!hours) return `${minutes}分`;
    return minutes ? `${hours}小时 ${minutes}分` : `${hours}小时`;
  }
  /** Duration as large figures with small units. */
  function figure(seconds) {
    const sec = Math.max(0, Math.round(seconds));
    const hours = Math.floor(sec / 3600), minutes = Math.floor(sec % 3600 / 60);
    if (!hours) return h("span", { class: "dur" }, String(minutes), h("i", { text: "分" }));
    return h("span", { class: "dur" }, String(hours), h("i", { text: "小时" }), pad(minutes), h("i", { text: "分" }));
  }

  // ——— Station clocks ———
  const minuteHooks = [];
  /** Hands only ever turn forward. Angles stay small: some browsers keep them in single precision, which
      drops whole degrees once they pass a few million. */
  function turn(node, degrees) {
    const place = (angle, animate) => {
      if (!animate) node.style.transition = "none";
      node._deg = angle;
      node.style.transform = `rotate(${angle}deg)`;
      if (!animate) {
        node.getBoundingClientRect();
        node.style.transition = "";
      }
    };
    if (node._deg === undefined) return place(degrees % 360, false);
    // Fold whole turns away without a visible jump: the orientation is the same.
    if (node._deg > 7200) place(node._deg % 360, false);
    place(node._deg + ((degrees - node._deg) % 360 + 360) % 360, true);
  }
  function startClocks() {
    const dials = [...doc.querySelectorAll("[data-sbb]")];
    const minuteEls = doc.querySelectorAll("[data-hm]"), secondEls = doc.querySelectorAll("[data-ss]");
    const todayEls = doc.querySelectorAll("[data-today]");
    const secondLine = doc.querySelector("[data-second-line]");
    let lastMinute = null, timer = 0;
    // The sweep is a CSS animation; a negative delay puts the red hand where the second is now.
    const resync = () => {
      for (const dial of dials) {
        dial.classList.remove("is-live");
        dial.style.setProperty("--sbb-delay", `${-(now() % 60)}s`);
        dial.getBoundingClientRect();
        dial.classList.add("is-live");
      }
    };
    const tick = () => {
      clearTimeout(timer);
      const t = now();
      const minute = Math.floor(t / 60 - at(t).getTimezoneOffset());
      if (minute !== lastMinute) {
        for (const dial of dials) {
          turn(dial.querySelector('[data-hand="m"]'), minute * 6);
          turn(dial.querySelector('[data-hand="h"]'), minute * .5);
        }
        for (const node of minuteEls) node.textContent = hm(t);
        for (const node of todayEls) node.textContent = `${md(t)} ${weekday(t, true)}`;
        if (lastMinute !== null) minuteHooks.forEach(hook => hook());
        lastMinute = minute;
      }
      const second = Math.floor(t % 60);
      for (const node of secondEls) node.textContent = pad(second);
      // Sixty positions include both ends: 00 starts at the left, 59 reaches the right.
      // The same tick drives the digits and this responsive line; polling never restarts it.
      if (secondLine) secondLine.style.setProperty("--second-progress", second / 59);
      timer = setTimeout(tick, 1000 - ((t * 1000) % 1000) + 8);
    };
    tick();
    resync();
    doc.addEventListener("visibilitychange", () => {
      clearTimeout(timer);
      if (!doc.hidden) { resync(); tick(); }
    });
  }

  async function getJSON(url, options = {}) {
    const response = await fetch(url, { ...options, credentials: "same-origin", headers: { Accept: "application/json" } });
    if (response.status === 401) { location.href = "/login"; throw new Error("请先登录"); }
    if (!response.ok) {
      let detail = `服务器返回 ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch (error) { /* keep the status */ }
      throw Object.assign(new Error(detail), { status: response.status });
    }
    return response.json();
  }

  // ——— Drawing helpers ———
  /** One path for many bars; bars closer than a pixel merge, so a busy day stays light. */
  function barsPath(spans, x, y, height) {
    let d = "", a = null, b = null;
    const flush = () => { if (b !== null) d += `M${a.toFixed(1)} ${y}h${(b - a).toFixed(1)}v${height}h${(a - b).toFixed(1)}z`; };
    for (const [start, end] of spans) {
      const x0 = x(start);
      let x1 = x(end);
      if (x1 - x0 < 1) x1 = x0 + 1;
      if (b !== null && x0 - b < .75) { if (x1 > b) b = x1; continue; }
      flush();
      a = x0;
      b = x1;
    }
    flush();
    return d;
  }
  function findRun(runs, t) {
    let low = 0, high = runs.length - 1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (runs[mid][1] <= t) low = mid + 1;
      else if (runs[mid][0] > t) high = mid - 1;
      else return runs[mid];
    }
    return null;
  }
  function overlap(runs, from, to) {
    let total = 0;
    for (const [start, end] of runs) total += Math.max(0, Math.min(end, to) - Math.max(start, from));
    return total;
  }
  /** One occupied interval whenever any of a person's devices was in use. */
  function combinedUsage(lanes, from, to) {
    const spans = lanes.flatMap(lane => lane.runs)
      .map(([start, end]) => [Math.max(start, from), Math.min(end, to)])
      .filter(([start, end]) => end > start)
      .sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [start, end] of spans) {
      const last = merged[merged.length - 1];
      if (last && start <= last[1]) last[1] = Math.max(last[1], end);
      else merged.push([start, end]);
    }
    return merged;
  }
  const resizer = new ResizeObserver(entries => {
    for (const entry of entries) {
      const width = entry.contentRect.width;
      if (width && entry.target._paint && Math.abs(width - (entry.target._width || 0)) > .5) {
        entry.target._width = width;
        entry.target._paint(width);
      }
    }
  });
  function observe(node, paint) {
    node._paint = paint;
    node._width = 0;
    resizer.observe(node);
    return node;
  }

  const STATES = {
    active: "is-active", idle: "is-idle", asleep: "is-asleep", off: "is-off", offline: "is-offline",
  };
  function stateText(device) {
    switch (device.state) {
      case "active": return `使用中 · ${span(now() - device.since)}`;
      case "idle": return device.since ? `空闲 · ${span(now() - device.since)}` : "空闲";
      case "asleep": return `休眠 · ${when(device.since)} 起`;
      case "off": return `已关机 · ${when(device.since)}`;
      default: return `离线 · ${ago(device.last_seen)}联络`;
    }
  }
  const lamp = state => h("i", { class: `lamp ${STATES[state] || STATES.offline}`, "aria-hidden": "true" });
  function currentMusic(device) {
    return device.music && now() - device.music.observed_at <= 330 && now() - device.last_seen <= 330 ? device.music : null;
  }
  function musicLine(device, stale = false) {
    const track = currentMusic(device);
    if (!track) return null;
    const label = stale ? "上次播放" : track.state === "playing" ? "正在听" : "已暂停";
    const details = [track.artist, track.app_name].filter(Boolean).join(" · ");
    return h("span", { class: `music-line${track.state === "paused" || stale ? " is-paused" : ""}`,
      title: [label, track.title, track.artist, track.album, track.app_name].filter(Boolean).join(" · ") },
      h("span", { class: "music-title", text: `♫ ${label} · ${track.title}` }),
      details ? h("span", { class: "music-detail", text: details }) : null);
  }
  function battery(info) {
    if (!info || info.percent == null || now() - info.at > 86400) return null;
    const cell = h("i");
    cell.style.width = `${clamp(info.percent, 0, 100)}%`;
    const low = info.percent <= 20 && !info.charging;
    return h("span", { class: `batt${low ? " is-low" : ""}` },
      h("span", { class: "batt-cell", "aria-hidden": "true" }, cell),
      `${info.percent}%${info.charging ? " 充电中" : ""}`);
  }

  // A compact view of the latest reported foreground apps, independent of history filters.
  function initLiveApps() {
    const host = doc.querySelector("[data-live-apps]");
    if (!host) return null;
    const list = host.querySelector("[data-live-list]");
    const count = host.querySelector("[data-live-count]");
    const note = host.querySelector("[data-live-note]");
    const username = host.dataset.livePerson;
    const scope = host.dataset.liveScope;
    const seed = doc.getElementById("board-data");
    let data = seed ? JSON.parse(seed.textContent) : null;
    const authenticated = data?.authenticated;
    let timer = 0, pending = null, failed = false, queued = false;
    const listeners = new Set();

    function render() {
      if (!data) return;
      const selected = username ? new URLSearchParams(location.search).get("device") : "";
      const people = data.people.filter(person => !scope || (scope === "members" ? !person.shared : person.shared));
      const devices = people.flatMap(person => person.devices
        .filter(device => !selected || device.id === selected).map(device => ({ person, device: { ...device, music: currentMusic(device) } })));
      const active = devices.filter(({ device }) => device.state === "active" && device.last);
      const playing = devices.filter(({ device }) => device.music?.state === "playing");
      const stale = failed || now() - data.now > LIVE_POLL * 3;
      host.classList.toggle("is-stale", stale);
      count.textContent = stale ? "等待更新" : `${active.length} 台使用中${playing.length ? ` · ${playing.length} 台播放中` : ""}`;
      note.textContent = stale ? "更新暂时中断，显示上次上报 · 10 秒后重试"
        : realtime?.state === "connected" ? "实时更新 · 每 10 秒定时校验"
        : realtime?.state === "reconnecting" ? "实时连接恢复中 · 每 10 秒定时刷新"
        : "每 10 秒定时刷新 · 随客户端上报更新";
      const cards = devices.filter(({ device }) => (device.state === "active" && device.last) || device.music).map(({ person, device }) => {
        const using = device.state === "active" && device.last;
        const app = using ? device.last : { app: device.music.app_name, process: device.music.process_name, until: device.music.observed_at };
        const owner = username ? device.name : `${person.username} · ${device.name}`;
        const updated = `上报于 ${when(device.last_seen)} · ${ago(device.last_seen)}`;
        const song = device.music ? `，${stale ? "上次播放" : device.music.state === "playing" ? "正在听" : "音乐已暂停"} ${device.music.title}${device.music.artist ? `，${device.music.artist}` : ""}` : "";
        return h("li", null,
          h("a", { class: "live-app", href: `/people/${encodeURIComponent(person.username)}?device=${encodeURIComponent(device.id)}`,
            "data-key": `live:${device.id}`, "aria-label": `${owner}，${stale ? "上次上报" : using ? "正在使用" : "播放器"} ${app.app}${song}，${updated}` },
            h("div", { class: "live-app-top" },
              h("span", { class: "live-app-name" }, swatch(app.color), app.app),
              h("span", { class: "live-badge", text: stale ? "上次上报" : using ? "使用中" : device.music.state === "playing" ? "播放中" : "已暂停" })),
            h("span", { class: "live-device", text: owner, title: owner }),
            musicLine(device, stale),
            h("span", { class: "live-updated", text: updated, title: `${app.process} · 最近使用 ${when(app.until)}` })));
      });
      if (!cards.length) {
        const labels = { idle: "空闲", asleep: "休眠", off: "已关机", offline: "离线" };
        const states = Object.entries(labels).map(([state, label]) => {
          const total = devices.filter(({ device }) => device.state === state).length;
          return total ? `${total} 台${label}` : "";
        }).filter(Boolean).join(" · ");
        cards.push(h("li", { class: "live-empty" },
          h("b", { text: stale ? "等待状态更新" : devices.length ? "当前没有正在使用的应用" : "等待客户端上报" }),
          h("span", { text: stale ? "连接恢复后会自动更新。" : states || "设备开始记录并上传后，当前前台应用会显示在这里。" })));
      }
      list.replaceChildren(...cards);
    }

    async function poll() {
      clearTimeout(timer);
      if (doc.hidden) return;
      if (pending) { queued = true; return; }
      pending = new AbortController();
      const timeout = setTimeout(() => pending?.abort(), LIVE_POLL * 1000);
      try {
        const query = username ? `?username=${encodeURIComponent(username)}` : "";
        const next = await getJSON(`/api/web/live${query}`, { signal: pending.signal });
        if (authenticated != null && next.authenticated !== authenticated) {
          host.replaceChildren();
          location.reload();
          return;
        }
        sync(next.now);
        data = next;
        failed = false;
        keepFocus(render);
        listeners.forEach(listener => listener(next));
      } catch (error) {
        failed = true;
        if (error.status === 404) { data = null; list.replaceChildren(); }
        if (data) keepFocus(render);
        else {
          host.classList.add("is-stale");
          count.textContent = "等待更新";
          note.textContent = "暂时无法读取状态 · 10 秒后重试";
        }
      } finally {
        clearTimeout(timeout);
        pending = null;
      }
      if (queued) { queued = false; queueMicrotask(poll); return; }
      timer = setTimeout(poll, LIVE_POLL * 1000);
    }

    if (data) { sync(data.now); render(); timer = setTimeout(poll, LIVE_POLL * 1000); }
    else poll();
    doc.addEventListener("visibilitychange", () => {
      clearTimeout(timer);
      if (doc.hidden) pending?.abort();
      else poll();
    });
    realtime?.subscribe(areas => { if (areas.includes("live") || areas.includes("access")) poll(); });
    realtime?.onState(() => { if (data) keepFocus(render); });
    return { render, subscribe: listener => listeners.add(listener) };
  }

  // ——— The timetable: lanes on one day, a needle for now, a line to scrub through time ———
  class Timetable {
    constructor(host, options) {
      this.host = host;
      this.options = options;
      this.lanes = [];
      this.highlight = null;
      this.frac = null;
      host.classList.add("timetable");
      this.title = h("h2", { class: "label tt-title" });
      this.scale = h("div", { class: "scale", "aria-hidden": "true" });
      this.flag = h("span", { class: "scale-flag" });
      this.scrubFlag = h("span", { class: "scale-scrub" });
      this.asideHead = h("div", { class: "tt-aside-head" });
      this.grid = h("div", { class: "tt-grid", "aria-hidden": "true" });
      this.rows = h("div", { class: "tt-rows" });
      this.body = h("div", { class: "tt-body", tabindex: "0", "aria-label": options.bodyLabel },
        this.grid, this.rows,
        h("div", { class: "tt-over", "aria-hidden": "true" }, h("i", { class: "tt-needle" }), h("i", { class: "tt-scrub" })));
      host.replaceChildren(h("div", { class: "tt-head" }, this.title, this.scale, this.asideHead), this.body);
      this.retitle(options);
      this.bindScrub();
    }

    retitle(options) {
      Object.assign(this.options, options);
      this.title.replaceChildren(this.options.title, h("small", { text: this.options.subtitle }));
      this.setAsideHead();
    }

    frame(from, to, multi) {
      this.from = from;
      this.to = to;
      this.multi = multi;
      this.host.classList.toggle("is-multi", multi);
      this.host.classList.toggle("is-day", !multi);
      for (const lane of this.lanes) resizer.unobserve(lane.track);
      this.lanes = [];
      this.rows.replaceChildren();
      const ticks = [], lines = [];
      this.labels = [];
      for (let hour = 0; hour <= 24; hour++) {
        const f = multi ? hour / 24 : ((hour === 24 ? to : hourOf(from, hour)) - from) / (to - from);
        const left = `${(f * 100).toFixed(3)}%`;
        const tick = h("i", { class: `scale-tick${hour % 6 ? "" : " is-major"}` });
        tick.style.left = left;
        ticks.push(tick);
        if (hour % 3) continue;
        const label = h("span", { class: `scale-h${hour === 0 ? " is-first" : hour === 24 ? " is-last" : ""}${hour % 6 ? " is-minor" : ""}`, text: pad(hour) });
        label.style.left = left;
        label._f = f;
        this.labels.push(label);
        ticks.push(label);
        if (hour && hour < 24) {
          const line = stagger(h("i", { class: hour % 6 ? null : "is-major" }), hour / 3);
          line.style.left = left;
          lines.push(line);
        }
      }
      this.scale.replaceChildren(...ticks, this.flag, this.scrubFlag);
      this.grid.replaceChildren(h("i", { class: "tt-future" }), ...lines);
    }

    group(head) {
      const group = stagger(h("div", { class: "tt-group" }), this.rows.children.length);
      if (head) this.lane(group, { ...head, rowClass: "tt-group-head",
        label: h("div", { class: "tt-person-label" }, head.label,
          head.meta ? h("div", { class: "tt-group-meta", text: head.meta }) : null) });
      this.rows.append(group);
      return group;
    }

    lane(parent, spec) {
      const svgNode = s("svg", { "aria-hidden": "true", focusable: "false" });
      const dot = h("i", { class: "t-dot" });
      const track = h("div", { class: `track${spec.sub ? " track-sub" : ""}` }, svgNode, h("i", { class: "t-needle" }), dot);
      const scrubApp = h("span", { class: "aside-app" }), scrubSub = h("span", { class: "aside-sub" });
      const aside = h("div", { class: "lane-aside" },
        h("div", { class: "aside-now" }, spec.aside),
        h("div", { class: "aside-scrub", "aria-hidden": "true" }, scrubApp, scrubSub));
      const row = h("div", { class: `tt-row ${spec.rowClass || "tt-lane"}` }, spec.label, track);
      if (spec.battery) spec.label.append(aside);
      else row.append(aside);
      parent.append(row);
      const lane = Object.assign(spec, { row, track, svg: svgNode, dot, scrubApp, scrubSub });
      this.lanes.push(lane);
      observe(track, width => this.paint(lane, width));
      return lane;
    }

    paint(lane, width) {
      const height = lane.track.clientHeight || 34;
      const mid = Math.round(height / 2);
      const k = width / (lane.to - lane.from);
      const x = t => (t - lane.from) * k;
      lane.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const parts = [];
      if (lane.battery) {
        const charging = lane.battery.filter(point => point[2]).map(point => [point[0], point[0] + 300]);
        parts.push(s("path", { class: "charging", d: barsPath(charging, x, 0, height) }));
        parts.push(s("line", { class: "axis-line", x1: 0, x2: width, y1: height - .5, y2: height - .5 }));
        let d = "", last = null;
        for (const [t, percent] of lane.battery) {
          d += `${last === null || t - last > 1200 ? "M" : "L"}${x(t).toFixed(1)} ${(height - 2 - percent / 100 * (height - 4)).toFixed(1)}`;
          last = t;
        }
        if (d) parts.push(s("path", { class: "battery", d, pathLength: "1" }));
      } else {
        parts.push(s("line", { class: "rail", x1: 0, x2: width, y1: mid + .5, y2: mid + .5 }));
      }
      if (lane.marks && lane.marks.length) {
        let d = "";
        for (const [t] of lane.marks) if (t >= lane.from && t <= lane.to) d += `M${Math.round(x(t)) + .5} ${mid - 11}V${mid + 11}`;
        parts.push(s("path", { class: "marks", d }));
      }
      const bar = Math.max(10, Math.round(height * .42));
      const top = mid - bar / 2 + .5;
      if (lane.usage) parts.push(s("path", { class: "runs usage", d: barsPath(lane.usage, x, top, bar) }));
      if (lane.runs) {
        const groups = new Map();
        for (const run of lane.runs) {
          const color = appColor(lane.colors, run[2]);
          if (!groups.has(color)) groups.set(color, []);
          groups.get(color).push(run);
        }
        for (const [color, runs] of groups) {
          parts.push(s("path", { class: "runs app-color", "data-color": color, d: barsPath(runs, x, top, bar) }));
        }
        if (this.highlight != null) {
          parts.push(s("path", { class: "hl app-color", "data-color": appColor(lane.colors, this.highlight),
            d: barsPath(lane.runs.filter(run => run[2] === this.highlight), x, top, bar) }));
        }
      }
      if (lane.bins) {
        // Colour identifies the most-used program in a bin; four shades show occupied time.
        const groups = new Map();
        for (const [t, seconds, app] of lane.bins) {
          const level = clamp(Math.ceil(seconds / lane.binSize * 4), 1, 4);
          const color = appColor(lane.colors, app), key = `${color}:${level}`;
          if (!groups.has(key)) groups.set(key, { color, level, spans: [] });
          groups.get(key).spans.push([t, t + lane.binSize]);
        }
        for (const { color, level, spans } of groups.values()) {
          parts.push(s("path", { class: "bins app-color", "data-color": color,
            "fill-opacity": level / 4, d: barsPath(spans, x, top - 3, bar + 6) }));
        }
        if (this.highlight != null) {
          const hot = lane.bins.filter(bin => bin[2] === this.highlight).map(bin => [bin[0], bin[0] + lane.binSize]);
          parts.push(s("path", { class: "hl app-color", "data-color": appColor(lane.colors, this.highlight),
            d: barsPath(hot, x, top - 3, bar + 6) }));
        }
      }
      lane.svg.replaceChildren(...parts);
    }

    setHighlight(index) {
      if (this.highlight === index) return;
      this.highlight = index;
      this.host.classList.toggle("is-focus", index != null);
      for (const lane of this.lanes) if (lane.track._width) this.paint(lane, lane.track._width);
    }

    /** Put the needle at now. Returns its position in percent, or null when now is off this page. */
    needle() {
      const t = now();
      let pct = null;
      if (!this.multi && t >= this.from && t < this.to) pct = (t - this.from) / (this.to - this.from) * 100;
      for (const lane of this.lanes) {
        const live = t >= lane.from && t < lane.to;
        lane.row.classList.toggle("has-now", live);
        if (this.multi && live) pct = (t - lane.from) / (lane.to - lane.from) * 100;
      }
      this.host.classList.toggle("no-now", pct == null);
      if (pct != null) {
        this.host.style.setProperty("--needle", `${pct.toFixed(3)}%`);
        this.flag.textContent = hm(t);
      }
      if (!this.sweeping) this.cover(this.multi ? null : pct);
      return pct;
    }

    /** The flag's stem runs through the hour numbers; fade the one it would strike. */
    cover(pct) {
      const room = this.scale.clientWidth / 100;
      for (const label of this.labels || []) {
        label.classList.toggle("is-covered", pct != null && Math.abs(label._f * 100 - pct) * room < 14);
      }
    }

    /** Once per page the needle sweeps from midnight to now and the day is drawn in behind it. */
    intro() {
      // Hour numbers stay put until the needle has arrived; only then does it cover one.
      this.sweeping = !calm.matches;
      const target = this.needle();
      if (calm.matches) return;
      const end = this.multi || target == null ? 100 : target;
      const style = this.host.style;
      style.transition = "none";
      style.setProperty("--reveal", "0%");
      if (target != null) style.setProperty("--needle", "0%");
      this.host.getBoundingClientRect();
      style.transition = "";
      requestAnimationFrame(() => requestAnimationFrame(() => {
        style.setProperty("--reveal", `${end}%`);
        if (target != null) style.setProperty("--needle", `${target.toFixed(3)}%`);
        clearTimeout(this.revealTimer);
        this.revealTimer = setTimeout(() => {
          style.transition = "none";
          style.setProperty("--reveal", "100%");
          this.host.getBoundingClientRect();
          style.transition = "";
          this.sweeping = false;
          this.cover(this.multi ? null : target);
        }, 1700);
      }));
    }

    setAsideHead(time) {
      const [title, sub] = this.options.aside;
      this.asideHead.replaceChildren(time
        ? h("p", { class: "label" }, h("b", { text: time }), h("small", { text: "Scrub" }))
        : h("p", { class: "label" }, title, h("small", { text: sub })));
    }

    scrub(frac) {
      if (frac == null) {
        if (this.frac == null) return;
        this.frac = null;
        this.host.classList.remove("is-scrub");
        this.setAsideHead();
        return;
      }
      this.frac = frac;
      this.host.classList.add("is-scrub");
      this.host.style.setProperty("--scrub", `${(frac * 100).toFixed(3)}%`);
      const minutes = Math.min(1439, Math.round(frac * 1440));
      const label = this.multi ? `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}` : hm(this.from + frac * (this.to - this.from));
      this.scrubFlag.textContent = label;
      this.setAsideHead(label);
      for (const lane of this.lanes) {
        const reading = lane.read ? lane.read(lane.from + frac * (lane.to - lane.from)) : null;
        lane.dot.classList.toggle("is-on", !!(reading && reading.on));
        lane.scrubApp.textContent = reading ? reading.app : "";
        lane.scrubApp.title = reading ? reading.app : "";
        if (reading && reading.on && reading.color) lane.scrubApp.prepend(swatch(reading.color));
        lane.scrubApp.classList.toggle("is-none", !(reading && reading.on));
        lane.scrubSub.textContent = reading ? reading.sub || "" : "";
        lane.scrubSub.title = reading ? reading.sub || "" : "";
      }
    }

    bindScrub() {
      const body = this.body;
      let touching = false, release = 0;
      const fracAt = event => {
        const track = event.target.closest(".track") || this.rows.querySelector(".track");
        if (!track) return null;
        const box = track.getBoundingClientRect();
        if (event.clientX < box.left - 8 || event.clientX > box.right + 8) return null;
        return clamp((event.clientX - box.left) / box.width, 0, 1);
      };
      body.addEventListener("pointermove", event => {
        if (event.pointerType === "mouse" || touching) this.scrub(fracAt(event));
      });
      body.addEventListener("pointerleave", event => { if (event.pointerType === "mouse") this.scrub(null); });
      body.addEventListener("pointerdown", event => {
        if (event.pointerType === "mouse" || !event.target.closest(".track")) return;
        touching = true;
        clearTimeout(release);
        this.scrub(fracAt(event));
      });
      const end = () => {
        if (!touching) return;
        touching = false;
        release = setTimeout(() => this.scrub(null), 2600);
      };
      addEventListener("pointerup", end);
      addEventListener("pointercancel", end);
      body.addEventListener("keydown", event => {
        if (event.key === "Escape") { this.scrub(null); return; }
        const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
        if (!step && event.key !== "Home" && event.key !== "End") return;
        event.preventDefault();
        let frac = this.frac ?? (this.needle() ?? 50) / 100;
        if (event.key === "Home") frac = 0;
        else if (event.key === "End") frac = 1;
        else frac += step * (event.shiftKey ? 3600 : 900) / 86400;
        this.scrub(clamp(frac, 0, 1));
      });
      body.addEventListener("blur", () => this.scrub(null));
    }
  }

  /** What a device lane was doing at time t: an app, asleep, switched off, or nothing. */
  function readRuns(lane, apps, t) {
    if (t > now()) return { app: "—", sub: "还没到这个时间", on: false };
    const run = findRun(lane.runs, t);
    if (run) {
      const [name, process] = apps[run[2]] || ["?", ""];
      return { app: name, sub: `${hm(run[0])}–${run[3] ? "现在" : hm(run[1])} · ${process}`,
        color: appColor(lane.colors, run[2]), on: true };
    }
    let mark = null;
    for (const item of lane.marks || []) { if (item[0] <= t) mark = item; else break; }
    if (mark && (mark[1] === "shutdown" || mark[1] === "suspend")) {
      const before = lane.runs.filter(item => item[1] <= t).pop();
      if (!before || before[1] <= mark[0] + 5) return { app: mark[1] === "shutdown" ? "已关机" : "休眠中", sub: `${hm(mark[0])} 起`, on: false };
    }
    return { app: "未使用", sub: "", on: false };
  }
  function readPerson(lanes, apps, t) {
    if (t > now()) return { app: "—", sub: "还没到这个时间", on: false };
    const active = lanes.map(lane => ({ lane, run: findRun(lane.runs, t) })).filter(item => item.run);
    if (!active.length) return { app: "未使用", sub: "所有设备均无使用记录", on: false };
    return {
      app: active.length === 1 ? (apps[active[0].run[2]]?.[0] || "?") : `${active.length} 台设备使用中`,
      sub: active.map(({ lane, run }) => `${lane.device.name} · ${apps[run[2]]?.[0] || "?"}`).join("；"),
      on: true,
    };
  }
  /** Runs arrive as offsets from a base; the last one keeps growing while its device is in use. */
  function liveRuns(device, offsets, base, limit, apps) {
    const runs = offsets.map(([start, end, app]) => [base + start, base + end, app, false]);
    const last = runs[runs.length - 1];
    if (device.state === "active" && last && device.last && last[1] >= device.last.until - 2 &&
        apps[last[2]]?.[1]?.toLowerCase() === device.last.process.toLowerCase()) {
      last[3] = true;
      last[1] = Math.max(last[1], Math.min(now(), limit));
    }
    return runs;
  }

  // ——— Board ———
  function initBoard(liveApps) {
    const host = doc.querySelector("[data-board]");
    const seed = doc.getElementById("board-data");
    if (!host || !seed) return;
    let data = JSON.parse(seed.textContent);
    const authenticated = data.authenticated;
    const memberScope = host.dataset.boardScope === "members";
    sync(data.now);
    const status = doc.querySelector("[data-board-status]");
    const figures = Object.fromEntries([...doc.querySelectorAll("[data-fig]")].map(node => [node.dataset.fig, node]));
    const table = new Timetable(host, {
      title: "时刻表", subtitle: "Timetable", aside: ["此刻", "Now"],
      bodyLabel: "今日时刻表。按左右方向键，查看某个时刻每台设备在用什么。",
    });
    const heading = doc.title;
    let first = true, timer = 0, pending = false, queued = false, latestLive = null;

    function mergeLive(next) {
      if (!next || next.now < data.now) return;
      const old = new Map(data.people.flatMap(person => person.devices.map(device => [device.id, device])));
      data.people = next.people.map(person => ({ ...person, devices: person.devices.map(device => ({
        ...device, runs: old.get(device.id)?.runs || [], marks: old.get(device.id)?.marks || [],
      })) }));
      data.now = next.now;
    }

    function render() {
      const t = now(), from = midnight(t), to = midnight(t, 1);
      if (first) enter(host);
      table.frame(from, to, false);
      let online = 0, devices = 0, usage = 0;
      const busy = [];
      const people = data.people.filter(person => memberScope ? !person.shared : person.shared);
      if (!people.length) {
        table.rows.append(h("div", { class: "board-empty" },
          h("h3", { text: memberScope ? "暂无仅成员可见的设备" : "暂无公开设备" }),
          h("p", { text: memberScope ? "成员将记录设为不公开后，会在这里显示。已公开的设备可在公开看板查看。"
            : "成员公开记录后，设备使用时间就会显示在这里。未公开记录需登录后查看。" }),
          h("a", { class: "btn is-small", href: memberScope ? "/" : authenticated ? "/settings#sharing" : "/login?next=members",
            text: memberScope ? "查看公开设备" : authenticated ? "管理我的公开设置" : "登录查看成员记录" })));
      }
      for (const person of people) {
        const lanes = person.devices.map(device => {
          const runs = liveRuns(device, device.runs, data.base, to, data.apps);
          return { device, runs, marks: device.marks.map(([offset, reason]) => [data.base + offset, reason]), today: overlap(runs, from, t) };
        });
        const total = lanes.reduce((sum, lane) => sum + lane.today, 0);
        usage += total;
        if (person.devices.some(device => device.state === "active")) busy.push(person.username);
        const group = table.group({
          label: h("div", { class: "tt-person" },
            h("a", { href: `/people/${encodeURIComponent(person.username)}`, "data-key": `p:${person.username}`, text: person.username }),
            person.self ? h("span", { class: "tt-you", text: "你" }) : null),
          meta: person.devices.length ? `${person.devices.length} 台设备` : "",
          aside: h("div", { class: "tt-total" }, h("small", { text: "今日" }), figure(total)),
          from, to, usage: combinedUsage(lanes, from, t), read: time => readPerson(lanes, data.apps, time),
        });
        if (!person.devices.length) {
          group.append(h("div", { class: "tt-row tt-lane" }, h("div"), h("p", { class: "tt-empty" }, person.self
            ? ["还没有设备上传记录。", h("a", { href: "/settings#key", text: "生成上传密钥" }), "，填到 Windows 客户端里。"]
            : "这个成员还没有设备上传记录。")));
          continue;
        }
        for (const lane of lanes) {
          const { device } = lane;
          devices += 1;
          if (device.state === "active" || device.state === "idle") online += 1;
          const active = device.state === "active" && device.last;
          const label = h("div", { class: "lane-label" }, lamp(device.state),
            h("a", { class: "lane-name", "data-key": `d:${device.id}`, text: device.name,
              href: `/people/${encodeURIComponent(person.username)}?device=${encodeURIComponent(device.id)}` }),
            h("div", { class: "lane-state" }, h("span", { text: stateText(device) }), battery(device.battery)));
          const aside = !device.last ? [h("span", { class: "aside-app is-none", text: "还没有使用记录" })] : [
            h("span", { class: `aside-app${active ? "" : " is-none"}` }, swatch(device.last.color), active ? device.last.app : `上次 · ${device.last.app}`),
            h("span", { class: "aside-sub", text: active ? `${device.last.process} · 今日 ${span(lane.today)}` : `今日 ${span(lane.today)} · 最后使用 ${when(device.last.until)}` })];
          aside.push(musicLine(device));
          const spec = { label, aside, from, to, runs: lane.runs, marks: lane.marks, colors: data.app_colors };
          spec.read = time => readRuns(spec, data.apps, time);
          table.lane(group, spec);
        }
      }
      figures.online.textContent = String(online);
      figures.devices.textContent = `/ ${devices} 台`;
      figures["online-note"].textContent = devices ? `另有 ${devices - online} 台休眠、关机或离线` : "还没有设备";
      figures.busy.textContent = String(busy.length);
      figures["busy-names"].textContent = busy.length ? busy.join("、") : "此刻没有人在用电脑";
      figures.total.replaceChildren(figure(usage));
      figures["total-note"].textContent = devices ? `${devices} 台${memberScope ? "成员" : "公开"}设备时长相加` : "有使用记录后开始累计";
      // A tab left in the background still tells how many people are at their computers.
      doc.title = busy.length ? `(${busy.length}) ${heading}` : heading;
      if (first) table.intro();
      else table.needle();
      first = false;
      if (table.frac != null) table.scrub(table.frac);
    }

    async function poll() {
      clearTimeout(timer);
      if (doc.hidden) return;
      if (pending) { queued = true; return; }
      pending = true;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        data = await getJSON(`/api/web/board?since=${Math.floor(midnight(now()) - 300)}`, { signal: controller.signal });
        if (data.authenticated !== authenticated) {
          host.replaceChildren();
          location.reload();
          return;
        }
        sync(data.now);
        mergeLive(latestLive);
        keepFocus(render);
        status.textContent = "";
        status.classList.remove("is-failed");
      } catch (error) {
        status.textContent = `更新失败：${error.message}。${BOARD_POLL} 秒后重试。`;
        status.classList.add("is-failed");
      } finally {
        clearTimeout(timeout);
        pending = false;
      }
      if (queued) { queued = false; queueMicrotask(poll); return; }
      timer = setTimeout(poll, BOARD_POLL * 1000);
    }

    render();
    timer = setTimeout(poll, BOARD_POLL * 1000);
    doc.addEventListener("visibilitychange", () => { if (!doc.hidden) poll(); });
    minuteHooks.push(() => keepFocus(render));
    liveApps?.subscribe(next => {
      // Foreground-only reports need no history scan: keep the stored runs and marks.
      latestLive = next;
      mergeLive(next);
      keepFocus(render);
    });
    realtime?.subscribe(areas => { if (areas.includes("history") || areas.includes("access")) poll(); });
  }

  // ——— Person page ———
  const SPANS = { day: 1, week: 7, month: 30, year: 365 };
  const EVENTS = { startup: ["开机", true], resume: ["唤醒", true], suspend: ["休眠", false], shutdown: ["关机", false] };

  function initPerson(liveApps) {
    const head = doc.querySelector("[data-person]");
    const body = doc.querySelector("[data-person-body]");
    if (!head || !body) return;
    const username = head.dataset.person;
    const els = {
      meta: doc.querySelector("[data-person-meta]"), spans: doc.querySelector("[data-spans]"),
      label: doc.querySelector("[data-range-label]"), devices: doc.querySelector("[data-devices]"),
      steps: [...doc.querySelectorAll("[data-step]")],
      stats: body.querySelector("[data-stats]"), view: body.querySelector("[data-view]"),
      ranking: body.querySelector("[data-ranking]"), columns: body.querySelector("[data-columns]"),
      records: body.querySelector("[data-records]"), status: body.querySelector("[data-status]"),
    };
    let table = null, payload = null, pinned = null, timer = 0, request = 0, intro = true;
    let pendingRequest = null, bodyMotion = null, previousState = null, queued = false, latestLive = null;

    function mergeLive() {
      if (!payload || !latestLive || latestLive.now < payload.now) return;
      const owner = latestLive.people.find(person => person.username === username);
      if (owner) payload.devices = owner.devices;
    }
    calm.addEventListener("change", () => { if (calm.matches) bodyMotion?.cancel(); });

    const readState = () => {
      const query = new URLSearchParams(location.search);
      return { span: SPANS[query.get("span")] ? query.get("span") : "day", date: query.get("date") || "", device: query.get("device") || "" };
    };
    const href = changes => {
      const next = { ...readState(), ...changes };
      const query = new URLSearchParams();
      if (next.span !== "day") query.set("span", next.span);
      if (next.date && next.date !== isoDay(now())) query.set("date", next.date);
      if (next.device) query.set("device", next.device);
      const text = query.toString();
      return text ? `?${text}` : location.pathname;
    };
    function range(state) {
      const day = parseDay(state.date);
      const anchor = day != null && day <= now() ? day : midnight(now());
      return { start: midnight(anchor, 1 - SPANS[state.span]), end: midnight(anchor, 1), anchor };
    }

    function controls(state, bounds) {
      liveApps?.render();
      els.spans.style.setProperty("--seg", Object.keys(SPANS).indexOf(state.span));
      for (const link of els.spans.querySelectorAll("[data-span]")) {
        link.href = href({ span: link.dataset.span });
        if (link.dataset.span === state.span) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
      }
      const days = SPANS[state.span];
      els.label.textContent = days === 1 ? `${md(bounds.start)} ${weekday(bounds.start, true)}`
        : days === 365 ? `${isoDay(bounds.start).replace(/-/g, ".")} – ${isoDay(bounds.end - 1).replace(/-/g, ".")}`
        : `${md(bounds.start)} – ${md(bounds.end - 1)}`;
      const latest = bounds.end > now();
      for (const link of els.steps) {
        const step = +link.dataset.step;
        link.href = href({ date: isoDay(step ? midnight(bounds.anchor, step * days) : now()) });
        link.setAttribute("aria-disabled", String(step >= 0 && latest));
      }
    }

    function deviceChips(state) {
      // Keep the actual links so focus and the selection transition survive data refreshes.
      const existing = new Map([...els.devices.children].map(link => [link.dataset.device, link]));
      const devices = [{ id: "", name: "全部设备" }, ...payload.devices];
      devices.forEach((device, index) => {
        const id = String(device.id);
        const link = existing.get(id) || h("a", { class: "chip", "data-device": id, "data-key": `device-${id}` });
        existing.delete(id);
        link.href = href({ device: id });
        if (state.device === id) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
        link.replaceChildren(...(id ? [lamp(device.state), device.name] : [device.name]));
        if (els.devices.children[index] !== link) els.devices.insertBefore(link, els.devices.children[index] || null);
      });
      for (const link of existing.values()) link.remove();
      const contact = Math.max(0, ...payload.devices.map(device => device.last_seen));
      els.meta.textContent = payload.devices.length ? `${payload.devices.length} 台设备 · 最近联络 ${ago(contact)}` : "还没有设备上传记录";
    }

    function stats(state, bounds, lanesRuns) {
      const total = Object.values(payload.totals).reduce((a, b) => a + b, 0);
      const items = [["合计", "Total", figure(total), state.device ? "所选设备" : "各设备时长相加"]];
      if (state.span === "day") {
        const all = lanesRuns.flat();
        items.push(["活跃时段", "Active span", all.length ? `${hm(Math.min(...all.map(run => run[0])))}–${hm(Math.max(...all.map(run => run[1])))}` : "—",
          all.length ? "第一次到最后一次使用" : "这一天没有记录"]);
      } else {
        const elapsed = clamp(Math.ceil((Math.min(now(), bounds.end) - bounds.start) / 86400), 1, SPANS[state.span]);
        items.push(["日均", "Per day", figure(total / elapsed), `按 ${elapsed} 天平均`]);
      }
      const streak = payload.streak;
      items.push(["最长连续", "Longest", streak ? figure(streak[1] - streak[0]) : "—", streak
        ? `${state.span === "day" ? "" : `${md(payload.start + streak[0])} `}${hm(payload.start + streak[0])}–${hm(payload.start + streak[1])}`
        : "中断不超过 1 分钟算连续"]);
      const top = payload.ranking[0];
      items.push(["最常用", "Top app", top ? payload.apps[top[0]][0] : "—", top && total ? `占 ${Math.round(top[1] / total * 100)}% · ${span(top[1])}` : "暂无"]);
      els.stats.replaceChildren(h("div", { class: "label stats-title" }, "概要", h("small", { text: "Summary" })),
        ...items.map(([title, sub, value, note], index) => stagger(h("div", { class: "stat" },
          h("dt", null, title, h("small", { text: sub })),
          h("dd", { class: index === 3 && top ? "is-text" : null }, value),
          h("p", { text: note })), index)));
    }

    function ensureTable(state) {
      const options = state.span === "day"
        ? { title: "时刻表", subtitle: "Timetable", aside: ["合计", "Total"] }
        : { title: "逐日", subtitle: "Day by day", aside: ["当天合计", "Day total"] };
      if (!table || !els.view.contains(table.host)) {
        const host = h("div");
        els.view.replaceChildren(host);
        table = new Timetable(host, { ...options, bodyLabel: "时刻表。按左右方向键查看某个时刻在用什么。" });
      } else table.retitle(options);
      table.highlight = pinned;
      table.host.classList.toggle("is-focus", pinned != null);
    }

    function dayLanes(bounds) {
      const shown = payload.devices.filter(device => !payload.device || device.id === payload.device);
      table.frame(bounds.start, bounds.end, false);
      const group = table.group(null);
      const statusBy = {};
      for (const [device, offset, reason, percent, charging] of payload.status) {
        (statusBy[device] ||= []).push([payload.start + offset, reason, percent, charging]);
      }
      const lanesRuns = [];
      for (const device of shown) {
        const runs = liveRuns(device, payload.runs[device.id] || [], payload.start, bounds.end, payload.apps);
        lanesRuns.push(runs);
        const events = statusBy[device.id] || [];
        const total = payload.totals[device.id] || 0;
        const spec = {
          from: bounds.start, to: bounds.end, runs, colors: payload.app_colors,
          marks: events.filter(event => event[1] !== "periodic").map(([t, reason]) => [t, reason]),
          label: h("div", { class: "lane-label" }, lamp(device.state), h("span", { class: "lane-name", text: device.name }),
            h("div", { class: "lane-state" }, h("span", { text: stateText(device) }))),
          aside: [h("span", { class: `aside-app${total ? "" : " is-none"}`, text: total ? span(total) : "没有记录" }),
            h("span", { class: "aside-sub", text: runs.length ? `${runs.length} 段 · 每段为连续使用同一应用` : "这一天没有使用" })],
        };
        spec.read = t => readRuns(spec, payload.apps, t);
        table.lane(group, spec);
        const levels = events.filter(event => event[2] != null).map(([t, , percent, charging]) => [t, percent, charging]);
        if (levels.length > 1) {
          const latest = levels[levels.length - 1];
          const sub = {
            sub: true, from: bounds.start, to: bounds.end, battery: levels,
            label: h("div", { class: "lane-label is-day" }, h("div", { class: "lane-state" }, h("span", { text: `${device.name} · 电量` }))),
            aside: [h("span", { class: "aside-sub", text: `最后一次 ${latest[1]}%${latest[2] ? " · 充电中" : ""}` })],
          };
          sub.read = t => {
            let point = null;
            for (const item of levels) { if (item[0] <= t + 150) point = item; else break; }
            return point && t - point[0] < 900 ? { app: `电量 ${point[1]}%`, sub: point[2] ? "充电中" : "电池供电", on: false } : { app: "—", sub: "没有电量读数", on: false };
          };
          table.lane(group, sub);
        }
      }
      if (!shown.length) {
        group.append(h("div", { class: "tt-row tt-lane" }, h("div"), h("p", { class: "tt-empty" }, payload.person.self
          ? ["还没有设备上传记录。", h("a", { href: "/settings#key", text: "生成上传密钥" }), "，填到 Windows 客户端里。"]
          : "这个成员还没有设备上传记录。")));
      }
      return lanesRuns;
    }

    function binsByDay() {
      const byDay = new Map();
      for (const [slot, seconds, app] of payload.bins) {
        const t = payload.start + slot * payload.bin, key = midnight(t);
        if (!byDay.has(key)) byDay.set(key, []);
        byDay.get(key).push([t, seconds, app]);
      }
      return byDay;
    }
    function daysOf(bounds) {
      const days = [];
      for (let day = bounds.start; day < bounds.end; day = midnight(day, 1)) days.push(day);
      return days;
    }

    function dayRows(bounds, days, byDay) {
      table.frame(bounds.start, bounds.end, true);
      const group = table.group(null);
      const today = midnight(now());
      for (const day of days) {
        const bins = byDay.get(day) || [];
        const total = bins.reduce((sum, bin) => sum + bin[1], 0);
        const spec = {
          from: day, to: midnight(day, 1), bins, binSize: payload.bin, colors: payload.app_colors,
          label: h("div", { class: "lane-label is-day" },
            h("a", { class: "lane-name", href: href({ span: "day", date: isoDay(day) }), text: `${md(day)} ${weekday(day)}` }),
            day === today ? h("div", { class: "lane-state" }, h("span", { class: "lane-today", text: "今天" })) : null),
          aside: [h("span", { class: `aside-app${total ? "" : " is-none"}`, text: total ? span(total) : "没有记录" })],
        };
        spec.read = t => {
          if (t > now()) return { app: "—", sub: "还没到这个时间", on: false };
          const bin = bins.find(item => t >= item[0] && t < item[0] + payload.bin);
          return bin ? { app: payload.apps[bin[2]][0], color: appColor(payload.app_colors, bin[2]),
            sub: `${hm(bin[0])} 起的 ${Math.round(payload.bin / 60)} 分钟里用了 ${span(bin[1])}`, on: true }
            : { app: "未使用", sub: "", on: false };
        };
        table.lane(group, spec);
      }
    }

    function calendar(days, totals) {
      const steps = [3600, 3 * 3600, 6 * 3600];
      const level = seconds => (!seconds ? 0 : 1 + steps.filter(limit => seconds >= limit).length);
      const shades = [0, .22, .48, .74, 1];
      const readout = h("p", { class: "chart-readout" });
      const say = day => {
        const seconds = totals.get(day) || 0;
        readout.replaceChildren(`${md(day)} ${weekday(day, true)}`, h("span", { text: seconds ? `用了 ${span(seconds)} · 点一下看这一天` : "没有记录" }));
      };
      const wrap = h("div", { class: "calendar" });
      const offset = (at(days[0]).getDay() + 6) % 7;
      const weeks = Math.ceil((days.length + offset) / 7);
      const today = midnight(now());
      observe(wrap, width => {
        // A resize redraws the cells without replaying their entrance.
        if (wrap._painted) wrap.classList.add("is-drawn");
        wrap._painted = true;
        const left = 24, topPad = 20;
        const cell = clamp(Math.floor((Math.max(width, 720) - left) / weeks), 10, 24);
        const size = cell - 2;
        const svgNode = s("svg", { viewBox: `0 0 ${left + weeks * cell} ${topPad + 7 * cell}`, role: "img", "aria-label": "一年中每天的使用时长" });
        ["一", "三", "五"].forEach((text, index) => {
          const label = s("text", { x: 0, y: topPad + index * 2 * cell + size - 2 });
          label.textContent = text;
          svgNode.append(label);
        });
        let month = -1;
        days.forEach((day, index) => {
          const position = index + offset, week = Math.floor(position / 7), row = position % 7, d = at(day);
          // Months are named above their first Monday; the first column only when its month has room.
          if (d.getMonth() !== month && (row === 0 || (index === 0 && d.getDate() <= 14))) {
            const label = s("text", { x: left + week * cell, y: 11 });
            label.textContent = `${d.getMonth() + 1}月`;
            svgNode.append(label);
            month = d.getMonth();
          }
          const seconds = totals.get(day) || 0, step = level(seconds);
          const rect = s("rect", { class: `cell${step ? "" : " is-zero"}${day === today ? " is-today" : ""}`,
            x: left + week * cell, y: topPad + row * cell, width: size, height: size, "fill-opacity": step ? shades[step] : null });
          rect.style.setProperty("--i", week);
          const title = s("title");
          title.textContent = `${md(day)} · ${seconds ? span(seconds) : "没有记录"}`;
          rect.append(title);
          rect.addEventListener("pointerenter", () => say(day));
          rect.addEventListener("click", () => go(href({ span: "day", date: isoDay(day) })));
          svgNode.append(rect);
        });
        wrap.replaceChildren(svgNode);
        wrap.scrollLeft = wrap.scrollWidth;
      });
      const legend = h("span", { class: "legend" }, h("span", { text: "少" }), h("i", { class: "is-zero" }),
        ...shades.slice(1).map(opacity => { const swatch = h("i"); swatch.style.opacity = opacity; return swatch; }), h("span", { text: "多" }));
      els.view.replaceChildren(
        h("div", { class: "block-head" }, h("h2", { class: "label" }, "全年", h("small", { text: "Year" })), h("p", { class: "block-note", text: "每格一天，点一格看当天的时刻表" })),
        readout, wrap,
        h("div", { class: "calendar-foot" }, legend, h("span", { text: "分档：没有记录 · 1 小时内 · 1–3 小时 · 3–6 小时 · 6 小时以上" })));
      say(days.reduce((best, day) => ((totals.get(day) || 0) > (totals.get(best) || 0) ? day : best), days[days.length - 1]));
    }

    function ranking() {
      const list = payload.ranking;
      const max = list.length ? list[0][1] : 1;
      const total = list.reduce((sum, item) => sum + item[1], 0) + payload.other;
      const items = list.map(([app, seconds], index) => {
        const [name, process] = payload.apps[app];
        const color = appColor(payload.app_colors, app);
        const bar = stagger(h("i", { class: "app-color", "data-color": color }), index);
        bar.style.width = `${(seconds / max * 100).toFixed(2)}%`;
        const item = stagger(h("li", { tabindex: "0", role: "button", "aria-pressed": String(pinned === app),
          "data-app": app, "data-key": `app-${app}`, class: pinned === app ? "is-on" : null },
          h("span", { class: "rank-no", text: pad(index + 1) }),
          h("span", { class: "rank-name" }, h("b", null, swatch(color), name), h("small", { text: process })),
          h("span", { class: "rank-val" }, span(seconds), h("small", { text: `${total ? Math.round(seconds / total * 100) : 0}%` })),
          h("span", { class: "rank-bar", "aria-hidden": "true" }, bar)), Math.min(index, 12));
        item.hidden = index >= 12;
        return item;
      });
      const listNode = h("ol", { class: "rank" }, items);
      const focus = app => { if (table) table.setHighlight(app ?? pinned); };
      const appOf = event => { const item = event.target.closest("li"); return item ? +item.dataset.app : null; };
      listNode.addEventListener("pointerover", event => { const app = appOf(event); if (app != null) focus(app); });
      listNode.addEventListener("pointerleave", () => focus(null));
      listNode.addEventListener("focusin", event => focus(appOf(event)));
      listNode.addEventListener("focusout", () => focus(null));
      const toggle = event => {
        const app = appOf(event);
        if (app == null) return;
        pinned = pinned === app ? null : app;
        for (const node of listNode.children) {
          const selected = +node.dataset.app === pinned;
          node.classList.toggle("is-on", selected);
          node.setAttribute("aria-pressed", String(selected));
        }
        focus(pinned);
      };
      listNode.addEventListener("click", toggle);
      listNode.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(event); } });
      const parts = [h("div", { class: "block-head" }, h("h2", { class: "label" }, "应用", h("small", { text: "Apps" })),
        h("p", { class: "block-note", text: table ? "颜色对应程序，指向或点选可突出显示" : `共 ${list.length} 个应用` }))];
      parts.push(list.length ? listNode : h("p", { class: "empty", text: "这段时间没有使用记录。" }));
      if (list.length > 12) {
        parts.push(h("button", { class: "btn is-small more", type: "button", onclick: event => {
          for (const node of items) node.hidden = false;
          event.currentTarget.remove();
        } }, `显示全部 ${list.length} 个应用`));
      }
      if (payload.other) parts.push(h("p", { class: "rank-other", text: `其余应用合计 ${span(payload.other)}` }));
      els.ranking.replaceChildren(...parts);
    }

    /** Columns with one readout line; the tallest column carries its own value. */
    function columns(title, sub, note, bars, unit) {
      if (els.columns._chart) resizer.unobserve(els.columns._chart);
      els.columns._chart = null;
      const head = h("div", { class: "block-head" }, h("h2", { class: "label" }, title, h("small", { text: sub })),
        h("p", { class: "block-note", text: note }));
      if (!bars.some(bar => bar.value > 0)) {
        els.columns.replaceChildren(head, h("p", { class: "empty", text: "这段时间没有使用记录。" }));
        return;
      }
      const readout = h("p", { class: "chart-readout" });
      const chart = h("div", { class: "chart" });
      const peak = bars.reduce((best, bar, index) => (bar.value > bars[best].value ? index : best), 0);
      const say = index => readout.replaceChildren(bars[index] ? span(bars[index].value) : "—", h("span", { text: bars[index] ? bars[index].title : "" }));
      observe(chart, width => {
        if (chart._painted) chart.classList.add("is-drawn");
        chart._painted = true;
        const height = 196, bottom = 22, topPad = 20, plot = height - bottom - topPad;
        const max = Math.max(...bars.map(bar => bar.value), 0);
        const step = unit === "min" ? (max <= 1800 ? 600 : 1800)
          : max <= 4 * 3600 ? 3600 : max <= 12 * 3600 ? 3 * 3600 : Math.ceil(max / 4 / 36000) * 36000;
        const ceiling = Math.max(step, Math.ceil(max / step) * step);
        const y = value => topPad + plot - value / ceiling * plot;
        const slot = width / bars.length, barWidth = clamp(slot * .62, 2, 24);
        const svgNode = s("svg", { viewBox: `0 0 ${width} ${height}`, height, role: "img", "aria-label": `${title}柱状图` });
        for (let value = step; value <= ceiling; value += step) {
          const line = Math.round(y(value)) + .5;
          svgNode.append(s("line", { class: "grid", x1: 0, x2: width, y1: line, y2: line }));
          const label = s("text", { x: 0, y: line - 5 });
          label.textContent = unit === "min" ? `${value / 60} 分` : `${value / 3600} 小时`;
          svgNode.append(label);
        }
        const cols = bars.map((bar, index) => {
          const cx = slot * index + slot / 2;
          const col = s("rect", { class: "col", x: (cx - barWidth / 2).toFixed(1), y: y(bar.value).toFixed(1), width: barWidth.toFixed(1), height: (topPad + plot - y(bar.value)).toFixed(1) });
          col.style.setProperty("--i", index);
          svgNode.append(col);
          if (bar.tick) {
            const label = s("text", { x: cx, y: height - 5, "text-anchor": "middle" });
            label.textContent = bar.tick;
            svgNode.append(label);
          }
          return col;
        });
        svgNode.append(s("line", { class: "base", x1: 0, x2: width, y1: topPad + plot + .75, y2: topPad + plot + .75 }));
        if (bars[peak] && bars[peak].value) {
          const label = s("text", { class: "peak", x: slot * peak + slot / 2, y: y(bars[peak].value) - 6, "text-anchor": "middle" });
          label.textContent = unit === "min" ? `${Math.round(bars[peak].value / 60)}` : (bars[peak].value / 3600).toFixed(1);
          svgNode.append(label);
        }
        bars.forEach((bar, index) => {
          const hit = s("rect", { class: "hit", x: slot * index, y: 0, width: slot, height });
          hit.addEventListener("pointerenter", () => { cols.forEach((col, i) => col.classList.toggle("is-hot", i === index)); say(index); });
          svgNode.append(hit);
        });
        svgNode.addEventListener("pointerleave", () => { cols.forEach(col => col.classList.remove("is-hot")); say(peak); });
        chart.replaceChildren(svgNode);
      });
      say(peak);
      els.columns._chart = chart;
      els.columns.replaceChildren(head, readout, chart);
    }

    function tableBlock(target, title, sub, note, head, rows, limit, empty, more) {
      const parts = [h("div", { class: "block-head" }, h("h2", { class: "label" }, title, h("small", { text: sub })), h("p", { class: "block-note", text: note }))];
      rows.forEach((row, index) => { row.hidden = index >= limit; stagger(row, Math.min(index, limit)); });
      if (!rows.length) parts.push(h("p", { class: "empty", text: empty }));
      else {
        parts.push(h("div", { class: "table-scroll" }, h("table", { class: "table" },
          h("thead", null, h("tr", null, head.map(([text, numeric]) => h("th", { class: numeric ? "num" : null, text })))), h("tbody", null, rows))));
        if (rows.length > limit) {
          parts.push(h("button", { class: "btn is-small more", type: "button", onclick: event => {
            for (const row of rows) row.hidden = false;
            event.currentTarget.remove();
          } }, `${more} ${rows.length} ${title === "使用记录" ? "段" : "条"}`));
        }
      }
      target.replaceChildren(...parts);
    }

    function records(state) {
      const names = Object.fromEntries(payload.devices.map(device => [device.id, device.name]));
      const rows = payload.records.map(([device, a, b, app]) => {
        const [name, process] = payload.apps[app];
        const start = payload.start + a, end = payload.start + b;
        return h("tr", null,
          h("td", { class: "when" }, state.span === "day" ? null : h("small", { text: md(start) }), `${hm(start)}–${hm(end)}`),
          h("td", null, h("b", null, swatch(appColor(payload.app_colors, app)), name), h("small", { text: process })),
          h("td", { text: names[device] || "已删除的设备" }),
          h("td", { class: "num", text: span(end - start) }));
      });
      tableBlock(els.records, "使用记录", "Log", "连续使用同一个应用算一段，最新的在前",
        [["时间"], ["应用"], ["设备"], ["时长", true]], rows, 20, "这段时间没有使用记录。", "显示全部");
    }

    function powerLog(state) {
      const names = Object.fromEntries(payload.devices.map(device => [device.id, device.name]));
      const rows = payload.status.filter(event => event[2] !== "periodic").reverse().map(([device, offset, reason, percent]) => {
        const t = payload.start + offset;
        const [word, up] = EVENTS[reason] || [reason, false];
        return h("tr", null,
          h("td", { class: "when" }, state.span === "day" ? null : h("small", { text: md(t) }), hm(t)),
          h("td", { text: names[device] || "已删除的设备" }),
          h("td", null, h("span", { class: `event-word${up ? " is-up" : ""}` }, h("i", { "aria-hidden": "true" }), word)),
          h("td", { class: "num", text: percent == null ? "—" : `${percent}%` }));
      });
      tableBlock(els.status, "开关机", "Power", "客户端在开机、休眠、唤醒和关机时上报",
        [["时间"], ["设备"], ["事件"], ["电量", true]], rows, 12, "这段时间没有开关机或休眠记录。", "显示全部");
      const charged = payload.devices.filter(device => (!payload.device || device.id === payload.device) && battery(device.battery));
      if (charged.length) {
        els.status.querySelector(".block-head").after(h("p", { class: "chart-readout" },
          ...charged.map(device => h("span", null, `${device.name} `, battery(device.battery)))));
      }
    }

    function render(state, bounds) {
      controls(state, bounds);
      deviceChips(state);
      if (intro) enter(body);
      let lanesRuns = [];
      if (state.span === "year") {
        table = null;
        const days = daysOf(bounds), totals = new Map();
        for (const [slot, seconds] of payload.bins) {
          const key = midnight(payload.start + slot * payload.bin);
          totals.set(key, (totals.get(key) || 0) + seconds);
        }
        calendar(days, totals);
        const months = new Map();
        for (const day of days) {
          const d = at(day), key = d.getFullYear() * 12 + d.getMonth();
          if (!months.has(key)) months.set(key, { value: 0, tick: `${d.getMonth() + 1}月`, title: `${d.getFullYear()}年${d.getMonth() + 1}月` });
          months.get(key).value += totals.get(day) || 0;
        }
        columns("每月", "Monthly", "各月合计", [...months.values()], "hour");
      } else {
        ensureTable(state);
        if (state.span === "day") {
          lanesRuns = dayLanes(bounds);
          const hours = [];
          for (let hour = 0; hour < 24; hour++) {
            const a = hourOf(bounds.start, hour), b = hour === 23 ? bounds.end : hourOf(bounds.start, hour + 1);
            hours.push({ value: lanesRuns.reduce((sum, runs) => sum + overlap(runs, a, b), 0), tick: hour % 6 ? "" : pad(hour), title: `${pad(hour)}:00–${pad(hour + 1)}:00` });
          }
          columns("每小时", "Hourly", payload.device ? "所选设备" : "各设备相加", hours, "min");
        } else {
          const days = daysOf(bounds), byDay = binsByDay();
          dayRows(bounds, days, byDay);
          const every = days.length > 10 ? 5 : 1;
          columns("每天", "Daily", payload.device ? "所选设备" : "各设备相加", days.map((day, index) => ({
            value: (byDay.get(day) || []).reduce((sum, bin) => sum + bin[1], 0),
            tick: (days.length - 1 - index) % every ? "" : `${at(day).getDate()}`, title: `${md(day)} ${weekday(day)}`,
          })), "hour");
        }
        if (intro) table.intro(); else table.needle();
      }
      stats(state, bounds, lanesRuns);
      ranking();
      records(state);
      powerLog(state);
      intro = false;
    }

    async function load(quiet) {
      if (quiet && doc.hidden) return;
      if (quiet && body.getAttribute("aria-busy") === "true") { queued = true; return; }
      clearTimeout(timer);
      pendingRequest?.abort();
      pendingRequest = new AbortController();
      const controller = pendingRequest;
      let timedOut = false;
      const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
      const state = readState(), bounds = range(state), ticket = ++request, every = PERSON_POLL[state.span];
      const hadPayload = !!payload;
      const order = Object.keys(SPANS);
      const direction = previousState ? Math.sign(order.indexOf(state.span) - order.indexOf(previousState.span)
        || bounds.anchor - range(previousState).anchor) || 1 : 1;
      previousState = state;
      body.setAttribute("aria-busy", "true");
      if (!quiet) {
        bodyMotion?.cancel();
        keepFocus(() => { controls(state, bounds); if (payload) deviceChips(state); });
      }
      // Fast responses never flash a loading state. Slow responses keep their current content visible.
      const loading = !quiet ? setTimeout(() => {
        if (ticket === request) body.classList.add("is-loading");
      }, 120) : 0;
      try {
        const query = new URLSearchParams({ start: String(bounds.start), end: String(bounds.end) });
        if (state.device) query.set("device", state.device);
        const next = await getJSON(`/api/web/people/${encodeURIComponent(username)}?${query}`, { signal: controller.signal });
        if (ticket !== request) return;
        sync(next.now);
        payload = next;
        mergeLive();
        keepFocus(() => render(state, bounds));
        if (!quiet && hadPayload && !calm.matches && body.animate) {
          body.classList.remove("is-loading", "is-entering");
          bodyMotion = body.animate([
            { opacity: .35, transform: `translateX(${direction * 8}px)` },
            { opacity: 1, transform: "translateX(0)" },
          ], { duration: 220, easing: "cubic-bezier(.2,.75,0,1)" });
        }
      } catch (error) {
        if (ticket !== request || (error.name === "AbortError" && !timedOut)) return;
        if (!quiet) {
          for (const part of [els.stats, els.ranking, els.columns, els.records, els.status]) part.replaceChildren();
        }
        els.view.replaceChildren(h("p", { class: "notice is-error" }, h("b", { text: "未能载入" }),
          h("span", { text: timedOut ? "读取超时，将自动重试。" : error.message })));
        table = null;
      } finally {
        clearTimeout(timeout);
        clearTimeout(loading);
        if (ticket === request) {
          body.classList.remove("is-loading");
          body.setAttribute("aria-busy", "false");
        }
      }
      if (queued && !doc.hidden) { queued = false; queueMicrotask(() => load(true)); return; }
      if (bounds.end > now()) timer = setTimeout(() => load(true), every * 1000);
    }

    function go(url) {
      if (new URL(url, location.href).href === location.href) return;
      history.pushState(null, "", url);
      pinned = null;
      load(false);
    }
    const follow = event => {
      const link = event.target.closest("a[href]");
      if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button) return;
      event.preventDefault();
      if (link.getAttribute("aria-disabled") !== "true") go(link.getAttribute("href"));
    };
    doc.querySelector("[data-controls]").addEventListener("click", follow);
    els.view.addEventListener("click", event => { if (event.target.closest("a.lane-name")) follow(event); });
    addEventListener("popstate", () => load(false));
    doc.addEventListener("visibilitychange", () => { if (!doc.hidden && payload && payload.end > now()) load(true); });
    minuteHooks.push(() => { if (table) table.needle(); });
    liveApps?.subscribe(next => {
      latestLive = next;
      mergeLive();
      if (payload && payload.end > now() && body.getAttribute("aria-busy") !== "true") {
        const state = readState();
        keepFocus(() => render(state, range(state)));
      }
    });
    realtime?.subscribe(areas => {
      const state = readState();
      if (areas.includes("access") || areas.includes("metadata") ||
          (areas.includes("history") && state.span === "day" && range(state).end > now())) load(true);
    });
    load(false);
  }

  // ——— Small page helpers ———
  function localTimes() {
    for (const node of doc.querySelectorAll("time[datetime][data-format]")) {
      const t = Date.parse(node.getAttribute("datetime")) / 1000;
      if (!Number.isFinite(t)) continue;
      node.title = `${isoDay(t)} ${hm(t)}`;
      node.textContent = node.dataset.format === "ago" ? ago(t) : isoDay(t);
    }
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    for (const node of doc.querySelectorAll("[data-tz]")) node.textContent = zone || "本机时区";
  }
  function connectHints() {
    const secure = location.protocol === "https:";
    const fields = { host: location.hostname, port: location.port || (secure ? "443" : "80"), protocol: secure ? "HTTPS" : "HTTP" };
    for (const node of doc.querySelectorAll("[data-connect]")) node.textContent = fields[node.dataset.connect];
  }
  function copyToken() {
    const button = doc.querySelector("[data-copy]"), field = doc.querySelector("[data-token]");
    if (!button || !field) return;
    button.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(field.value); } catch (error) { field.select(); doc.execCommand("copy"); }
      button.textContent = "已复制";
      setTimeout(() => { button.textContent = "复制密钥"; }, 2200);
    });
  }
  function mastHeight() {
    const mast = doc.querySelector(".mast");
    if (!mast) return;
    const update = () => doc.documentElement.style.setProperty("--mast-h",
      getComputedStyle(mast).position === "sticky" ? `${mast.offsetHeight}px` : "0px");
    update();
    new ResizeObserver(update).observe(mast);
  }

  function navigationIndicator() {
    const tabs = doc.querySelector(".tabs"), current = tabs?.querySelector("[aria-current]");
    if (!current) return;
    const marker = h("i", { class: "tab-indicator", "aria-hidden": "true" });
    tabs.append(marker);
    const place = () => {
      marker.style.width = `${current.offsetWidth}px`;
      marker.style.transform = `translateX(${current.offsetLeft}px)`;
      tabs.classList.add("has-indicator");
    };
    place();
    new ResizeObserver(place).observe(tabs);
    doc.fonts?.ready.then(place);
  }

  function start() {
    const liveHost = doc.querySelector("[data-live-apps]");
    if (liveHost && window.FocusRealtime) {
      const username = liveHost.dataset.livePerson;
      realtime = new window.FocusRealtime(`/api/web/events${username ? `?username=${encodeURIComponent(username)}` : ""}`);
    }
    mastHeight();
    navigationIndicator();
    localTimes();
    connectHints();
    copyToken();
    startClocks();
    const liveApps = initLiveApps();
    initBoard(liveApps);
    initPerson(liveApps);
    minuteHooks.push(localTimes);
    realtime?.start();
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start);
  else start();
})();
