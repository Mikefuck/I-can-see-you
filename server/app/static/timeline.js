/* Continuous, anchored timetable navigation. No page-wide wheel or touch interception. */
(() => {
  "use strict";
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const MAX_ZOOM = 96; // A full day down to a fifteen-minute window.

  class Viewport {
    constructor(start = 0, size = 1) {
      this.size = clamp(size, 1 / MAX_ZOOM, 1);
      this.start = clamp(start, 0, 1 - this.size);
    }
    get zoom() { return 1 / this.size; }
    at(position) { return this.start + position * this.size; }
    project(time) { return (time - this.start) / this.size; }
    copy() { return new Viewport(this.start, this.size); }
    zoomTo(zoom, position = .5, anchor = this.at(position)) {
      this.size = 1 / clamp(zoom, 1, MAX_ZOOM);
      this.start = clamp(anchor - position * this.size, 0, 1 - this.size);
      return this;
    }
    panTo(start) { this.start = clamp(start, 0, 1 - this.size); return this; }
  }

  function wheelPixels(event, height) {
    return event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1);
  }

  let serial = 0;
  class Zoom {
    constructor({ host, axis, body, onChange, onScrub, getScrub, formatRange }) {
      Object.assign(this, { host, axis, body, onChange, onScrub, getScrub, formatRange });
      this.view = new Viewport();
      this.target = this.view.copy();
      this.calm = matchMedia("(prefers-reduced-motion: reduce)");
      this.abort = new AbortController();
      this.enabled = false;
      this.hover = "idle";
      this.timers = {};
      this.makeControls();
      this.bind();
    }

    makeControls() {
      const el = (tag, className, text) => {
        const node = document.createElement(tag);
        node.className = className;
        if (text) node.textContent = text;
        return node;
      };
      const button = (text, label, action) => {
        const node = el("button", "tt-zoom-button", text);
        node.type = "button";
        node.setAttribute("aria-label", label);
        node.title = label;
        node.addEventListener("click", action, { signal: this.abort.signal });
        return node;
      };
      const tools = el("div", "tt-tools");
      const top = el("div", "tt-zoom-top");
      const hint = el("p", "tt-zoom-hint");
      const indicator = el("i", "tt-zoom-indicator");
      indicator.setAttribute("aria-hidden", "true");
      this.hint = el("span", "tt-zoom-instruction");
      hint.append(indicator, this.hint);
      const controls = el("div", "tt-zoom-controls");
      controls.setAttribute("role", "group");
      controls.setAttribute("aria-label", "时间轴缩放");
      this.minus = button("−", "缩小时间轴（减号键）", () => this.step(-.5));
      this.factor = el("output", "tt-zoom-factor");
      this.factor.setAttribute("aria-label", "缩放倍数");
      this.factor.setAttribute("aria-live", "off");
      this.plus = button("+", "放大时间轴（加号键）", () => this.step(.5));
      this.fit = button("全天", "恢复全天视图（数字 0）", () => this.reset());
      this.fit.classList.add("tt-zoom-fit");
      controls.append(this.minus, this.factor, this.plus, this.fit);
      top.append(hint, controls);
      const bottom = el("div", "tt-zoom-bottom");
      this.range = el("span", "tt-zoom-range");
      this.overview = el("div", "tt-overview");
      this.overview.setAttribute("role", "scrollbar");
      this.overview.setAttribute("aria-orientation", "horizontal");
      this.overview.setAttribute("aria-label", "平移可见时段，方向键移动，Home 到开始，End 到结束");
      this.overview.setAttribute("aria-valuemin", "0");
      this.overview.setAttribute("aria-valuemax", "100");
      this.body.id ||= `timetable-${++serial}`;
      this.overview.setAttribute("aria-controls", this.body.id);
      this.window = el("i", "tt-window");
      this.overview.append(this.window);
      this.duration = el("span", "tt-zoom-duration");
      bottom.append(this.range, this.overview, this.duration);
      this.announcement = el("span", "sr-only");
      this.announcement.setAttribute("role", "status");
      this.announcement.setAttribute("aria-live", "polite");
      this.announcement.setAttribute("aria-atomic", "true");
      tools.append(top, bottom, this.announcement);
      this.host.prepend(tools);
      this.tools = tools;
      this.body.setAttribute("aria-label", `${this.body.getAttribute("aria-label")} 加减键缩放，0 恢复全天，Alt 加左右键平移，Escape 退出时间查看。`);
      this.updateHint();
    }

    later(key, action, delay) {
      clearTimeout(this.timers[key]);
      this.timers[key] = setTimeout(action, delay);
    }

    refresh() {
      const view = this.view, full = view.zoom < 1.00001;
      const { range, duration } = this.formatRange(view.start, view.at(1));
      this.factor.textContent = `${view.zoom.toFixed(2)}×`;
      this.range.textContent = range;
      this.duration.textContent = duration;
      this.window.style.left = `${view.start * 100}%`;
      this.window.style.width = `${view.size * 100}%`;
      this.overview.tabIndex = full ? -1 : 0;
      this.overview.setAttribute("aria-disabled", String(full));
      this.overview.setAttribute("aria-valuenow", String(full ? 0 : Math.round(view.start / (1 - view.size) * 100)));
      this.overview.setAttribute("aria-valuetext", `可见 ${range}`);
      this.minus.disabled = this.fit.disabled = full;
      this.plus.disabled = view.zoom >= MAX_ZOOM - .00001;
      this.host.classList.toggle("is-zoomed", !full);
    }

    updateHint() {
      this.hint.textContent = this.limit && this.notice ? this.notice : this.drag ? "平移中 · 松手保留当前时段"
        : this.pinch ? "双指缩放中 · 可同时移动查看时段"
        : this.notice || (this.hover === "ready" ? "已就绪 · 滚轮缩放，放大后拖动平移"
          : this.hover === "waiting" ? "停留 0.5 秒后启用滚轮缩放…"
          : "悬停 0.5 秒后滚轮缩放 · 触屏双指缩放");
    }

    feedback(text, limit = false) {
      this.notice = text;
      this.limit = limit;
      this.host.classList.toggle("is-zoom-limit", limit);
      this.updateHint();
      this.later("notice", () => {
        this.notice = "";
        this.limit = false;
        this.host.classList.remove("is-zoom-limit");
        this.updateHint();
      }, 1500);
    }

    announce() {
      this.later("announce", () => {
        this.announcement.textContent = `时间轴 ${this.factor.textContent}，可见 ${this.range.textContent}，${this.duration.textContent}`;
      }, 180);
    }

    apply() {
      this.refresh();
      this.onChange(this.view);
      if (this.pointerPosition != null && !this.drag && !this.pinch) this.onScrub(this.view.at(this.pointerPosition));
    }

    move(next, animate = false) {
      cancelAnimationFrame(this.animation);
      this.target = next.copy();
      this.host.classList.add("is-zooming");
      this.later("active", () => this.host.classList.remove("is-zooming"), 180);
      if (!animate || this.calm.matches) {
        this.view = next.copy();
        this.apply();
        return;
      }
      const before = this.view.copy(), started = performance.now();
      const frame = time => {
        const progress = clamp((time - started) / 90, 0, 1);
        // Interpolating both edges keeps the anchor fixed throughout the linear animation.
        this.view = new Viewport(before.start + (next.start - before.start) * progress,
          before.size + (next.size - before.size) * progress);
        this.apply();
        if (progress < 1) this.animation = requestAnimationFrame(frame);
      };
      this.animation = requestAnimationFrame(frame);
    }

    settle(finish = false) {
      cancelAnimationFrame(this.animation);
      if (finish) { this.view = this.target.copy(); this.apply(); }
      this.target = this.view.copy();
    }

    step(delta, position = .5) {
      if (!this.enabled) return;
      const next = this.target.copy().zoomTo(this.target.zoom + delta, position, this.view.at(position));
      this.move(next, true);
      this.feedback(next.zoom === 1 ? "已恢复全天 · 已到最小缩放"
        : next.zoom === MAX_ZOOM ? "已到最大缩放 · 可拖动查看相邻时段" : "缩放中 · 指向的时刻保持原位",
      next.zoom === 1 || next.zoom === MAX_ZOOM);
      this.announce();
    }

    reset(silent = false) {
      this.cancelGesture();
      this.move(new Viewport(), !silent);
      this.onScrub(null);
      if (!silent) { this.feedback("已恢复全天视图"); this.announce(); }
    }

    position(event, element = this.axis) {
      const box = element.getBoundingClientRect();
      return box.width ? clamp((event.clientX - box.left) / box.width, 0, 1) : .5;
    }

    hit(event) {
      return this.enabled && this.host.contains(event.target) && !!event.target.closest(".track, .scale");
    }

    hoverAt(event) {
      if (!this.hit(event)) { this.leave(); return; }
      this.pointerPosition = this.position(event);
      if (this.hover !== "idle") return;
      this.hover = "waiting";
      this.host.classList.add("is-zoom-waiting");
      this.updateHint();
      this.later("hover", () => {
        this.hover = "ready";
        this.host.classList.remove("is-zoom-waiting");
        this.host.classList.add("is-zoom-ready");
        this.updateHint();
      }, 500);
    }

    leave() {
      clearTimeout(this.timers.hover);
      this.hover = "idle";
      this.pointerPosition = null;
      this.host.classList.remove("is-zoom-waiting", "is-zoom-ready");
      this.updateHint();
    }

    pan(start) {
      const next = this.view.copy().panTo(start);
      this.move(next);
      if (start < 0 || start > 1 - next.size) this.feedback(start < 0 ? "已到当天开始" : "已到当天结束", true);
      else if (this.limit) this.feedback("平移中 · 松手保留当前时段");
    }

    endDrag() {
      if (!this.drag) return;
      const id = this.drag.id;
      this.drag = null;
      if (this.host.hasPointerCapture(id)) this.host.releasePointerCapture(id);
      this.host.classList.remove("is-panning");
      this.feedback("已保留当前时段 · 可继续缩放或平移");
      this.announce();
    }

    cancelGesture() {
      this.endDrag();
      this.pinch = null;
      this.touching = this.suppressTouch = false;
      clearTimeout(this.timers.scrub);
      this.host.classList.remove("is-pinching");
      this.leave();
    }

    bind() {
      const listen = (node, name, action, options = {}) => node.addEventListener(name, action,
        { ...options, signal: this.abort.signal });
      listen(this.host, "pointermove", event => {
        if (this.drag && event.pointerId === this.drag.id) {
          const width = (this.drag.overview ? this.overview : this.axis).getBoundingClientRect().width;
          if (width) this.pan(this.drag.start + (event.clientX - this.drag.x) / width * (this.drag.overview ? 1 : -this.view.size));
          return;
        }
        if (event.pointerType !== "mouse") return;
        this.hoverAt(event);
        this.onScrub(this.hit(event) ? this.view.at(this.position(event)) : null);
      });
      listen(this.host, "pointerover", event => { if (event.pointerType === "mouse" && !this.drag) this.hoverAt(event); });
      listen(this.host, "pointerleave", event => {
        if (event.pointerType === "mouse" && !this.drag) { this.leave(); this.onScrub(null); }
      });
      listen(this.host, "wheel", event => {
        // Browser zoom and ordinary page scrolling remain available outside the armed axis.
        if (event.ctrlKey || event.metaKey || this.hover !== "ready" || !this.hit(event) || this.drag) return;
        const delta = wheelPixels(event, window.innerHeight || 800);
        if (!delta) return;
        event.preventDefault();
        this.pointerPosition = this.position(event);
        this.step(-delta * .005, this.pointerPosition);
      }, { passive: false });
      listen(this.host, "pointerdown", event => {
        const overview = this.overview.contains(event.target);
        if (this.drag || event.button !== 0 || (!overview && (event.pointerType !== "mouse" || !this.hit(event))) || this.view.zoom <= 1) return;
        event.preventDefault();
        this.settle();
        if (overview) {
          const at = this.position(event, this.overview);
          if (at < this.view.start || at > this.view.at(1)) this.pan(at - this.view.size / 2);
          this.overview.focus({ preventScroll: true });
        } else { this.body.focus({ preventScroll: true }); this.onScrub(null); }
        this.drag = { id: event.pointerId, x: event.clientX, start: this.view.start, overview };
        this.host.setPointerCapture(event.pointerId);
        this.host.classList.add("is-panning");
        this.updateHint();
      });
      const endPointer = event => { if (event.pointerId === this.drag?.id) this.endDrag(); };
      listen(this.host, "pointerup", endPointer);
      listen(this.host, "pointercancel", endPointer);
      listen(this.host, "lostpointercapture", endPointer);

      const touches = event => [...event.touches].filter(touch => this.hit(touch));
      const beginPinch = points => {
        const [a, b] = points;
        const distance = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
        if (distance < 10) return;
        this.settle();
        this.leave();
        this.onScrub(null);
        this.pinch = { ids: [a.identifier, b.identifier], distance, zoom: this.view.zoom,
          anchor: this.view.at(this.position({ clientX: (a.clientX + b.clientX) / 2 })) };
        this.host.classList.add("is-pinching");
        this.updateHint();
      };
      listen(this.host, "touchstart", event => {
        const points = touches(event);
        if (!points.length || this.suppressTouch) return;
        clearTimeout(this.timers.scrub);
        if (points.length >= 2) {
          if (event.cancelable) event.preventDefault();
          if (!this.pinch) beginPinch(points);
        } else {
          this.touching = true;
          this.onScrub(this.view.at(this.position(points[0])));
        }
      }, { passive: false });
      listen(this.host, "touchmove", event => {
        if (this.suppressTouch) { if (event.cancelable) event.preventDefault(); return; }
        const points = touches(event);
        if (points.length >= 2 && !this.pinch) beginPinch(points);
        if (this.pinch) {
          if (event.cancelable) event.preventDefault();
          const pair = this.pinch.ids.map(id => points.find(point => point.identifier === id));
          if (pair.some(point => !point)) return;
          const [a, b] = pair, distance = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
          const zoom = this.pinch.zoom * distance / this.pinch.distance;
          this.move(this.view.copy().zoomTo(zoom, this.position({ clientX: (a.clientX + b.clientX) / 2 }), this.pinch.anchor));
          if (zoom < 1 || zoom > MAX_ZOOM) this.feedback(zoom < 1 ? "已到最小缩放 · 全天视图" : "已到最大缩放 · 可双指平移", true);
          else if (this.limit) this.feedback("双指缩放中 · 可同时移动查看时段");
        } else if (this.touching && points.length === 1) this.onScrub(this.view.at(this.position(points[0])));
      }, { passive: false });
      listen(this.host, "touchend", event => {
        if (this.pinch && this.pinch.ids.some(id => ![...event.touches].some(point => point.identifier === id))) {
          this.pinch = null;
          this.touching = false;
          this.suppressTouch = event.touches.length > 0;
          this.host.classList.remove("is-pinching");
          this.feedback("已保留当前时段 · 双指可继续缩放和平移");
          this.announce();
        }
        if (!event.touches.length) {
          if (this.touching) this.later("scrub", () => this.onScrub(null), 2600);
          this.touching = this.suppressTouch = false;
        }
      });
      listen(this.host, "touchcancel", () => { this.cancelGesture(); this.onScrub(null); });

      listen(this.overview, "keydown", event => {
        if (!this.enabled || this.view.zoom <= 1) return;
        const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
        if (!step && event.key !== "Home" && event.key !== "End") return;
        event.preventDefault();
        this.settle(true);
        this.pan(event.key === "Home" ? 0 : event.key === "End" ? 1 - this.view.size
          : this.view.start + step * this.view.size * (event.shiftKey ? .5 : .1));
        this.announce();
      });
      listen(this.body, "keydown", event => {
        if (!this.enabled || event.ctrlKey || event.metaKey) return;
        if (event.key === "Escape") { this.cancelGesture(); this.onScrub(null); return; }
        if (["+", "=", "-", "_", "0"].includes(event.key)) {
          event.preventDefault();
          if (event.key === "0") this.reset();
          else this.step(["-", "_"].includes(event.key) ? -.5 : .5);
          return;
        }
        const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
        if (!step && event.key !== "Home" && event.key !== "End") return;
        event.preventDefault();
        this.settle(true);
        if (event.altKey && step) {
          this.pan(this.view.start + step * this.view.size * .1);
          this.announce();
          return;
        }
        const fraction = event.key === "Home" ? this.view.start : event.key === "End" ? this.view.at(1)
          : (this.getScrub() ?? this.view.at(.5)) + step * this.view.size / (event.shiftKey ? 24 : 96);
        this.onScrub(clamp(fraction, this.view.start, this.view.at(1)));
      });
      listen(this.body, "blur", () => this.onScrub(null));
      const pause = () => { this.settle(); this.cancelGesture(); this.onScrub(null); };
      listen(window, "blur", pause);
      listen(document, "visibilitychange", () => { if (document.hidden) pause(); });
    }

    destroy() {
      this.abort.abort();
      this.cancelGesture();
      cancelAnimationFrame(this.animation);
      Object.values(this.timers).forEach(clearTimeout);
    }
  }

  const api = { Viewport, Zoom, wheelPixels, MAX_ZOOM };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else window.FocusTimeline = api;
})();
