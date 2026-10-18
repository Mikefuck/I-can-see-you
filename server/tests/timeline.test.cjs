const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const { Viewport, MAX_ZOOM, wheelPixels } = require("../app/static/timeline.js");

const near = (actual, expected, tolerance = 1e-9) => assert.ok(Math.abs(actual - expected) < tolerance, `${actual} != ${expected}`);

test("zoom preserves the pointed time and projection is reversible at every scale", () => {
  for (const position of [0, .17, .5, .91, 1]) {
    const view = new Viewport();
    for (const zoom of [1.125, 1.25, 2.4, 12.75, MAX_ZOOM, 17, 1]) {
      const anchor = view.at(position);
      view.zoomTo(zoom, position);
      near(view.at(position), anchor);
      near(view.project(view.at(.314)), .314);
      assert.ok(view.start >= 0 && view.at(1) <= 1 + 1e-9);
    }
  }
});

test("pan and extreme zoom inputs stay within the day, including both boundaries", () => {
  const view = new Viewport().zoomTo(4, 0);
  view.panTo(-10);
  near(view.start, 0);
  view.panTo(10);
  near(view.at(1), 1);
  view.zoomTo(1e6, 1);
  near(view.zoom, MAX_ZOOM);
  near(view.at(1), 1);
  view.zoomTo(-100, 0);
  near(view.size, 1);
  near(view.start, 0);
});

test("wheel units normalize without discarding fine trackpad deltas", () => {
  near(wheelPixels({ deltaY: .25, deltaMode: 0 }, 600), .25);
  near(wheelPixels({ deltaY: 3, deltaMode: 1 }, 600), 48);
  near(wheelPixels({ deltaY: -1, deltaMode: 2 }, 600), -600);
});

// A deterministic DOM/event harness exercises the actual controller, including touch sequences,
// without requiring a browser driver or changing any global machine/browser preferences.
function harness(reduce = false) {
  let clock = 0, serial = 0;
  const timers = new Map(), changes = [], readings = [];
  class Element {
    constructor(tag = "div") {
      this.tagName = tag;
      this.children = [];
      this.attrs = {};
      this.handlers = new Map();
      this.classes = new Set();
      this.style = { setProperty(name, value) { this[name] = value; } };
      this.captures = new Set();
      this.classList = {
        add: (...names) => names.forEach(name => this.classes.add(name)),
        remove: (...names) => names.forEach(name => this.classes.delete(name)),
        contains: name => this.classes.has(name),
        toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name),
      };
    }
    set className(value) { this.classes = new Set(value.split(/\s+/)); }
    get className() { return [...this.classes].join(" "); }
    get clientWidth() { return 600; }
    getBoundingClientRect() { return { left: 100, right: 700, width: 600, height: 34 }; }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    getAttribute(name) { return this.attrs[name] || null; }
    append(...nodes) { nodes.forEach(node => { node.parent = this; this.children.push(node); }); }
    prepend(node) { node.parent = this; this.children.unshift(node); }
    contains(node) { return node === this || this.children.some(child => child.contains(node)); }
    closest(selector) {
      const names = selector.split(",").map(name => name.trim().slice(1));
      return names.some(name => this.classes.has(name)) ? this : this.parent?.closest(selector) || null;
    }
    addEventListener(name, callback, { signal } = {}) {
      if (!this.handlers.has(name)) this.handlers.set(name, new Set());
      this.handlers.get(name).add(callback);
      signal?.addEventListener("abort", () => this.handlers.get(name).delete(callback), { once: true });
    }
    emit(name, props = {}) {
      const event = { target: this, clientX: 400, clientY: 0, pointerType: "mouse", pointerId: 1,
        button: 0, cancelable: true, prevented: false, preventDefault() { this.prevented = true; }, ...props };
      this.handlers.get(name)?.forEach(callback => callback(event));
      return event;
    }
    focus() { this.focused = true; }
    setPointerCapture(id) { this.captures.add(id); }
    hasPointerCapture(id) { return this.captures.has(id); }
    releasePointerCapture(id) { this.captures.delete(id); }
  }
  const schedule = (callback, delay) => { timers.set(++serial, { at: clock + delay, callback }); return serial; };
  const document = new Element(), window = new Element();
  document.createElement = tag => new Element(tag);
  const context = { window, document, AbortController, matchMedia: query => ({ matches: query.includes("reduced-motion") && reduce }), performance: { now: () => clock },
    setTimeout: schedule, clearTimeout: id => timers.delete(id),
    requestAnimationFrame: callback => schedule(() => callback(clock), 16), cancelAnimationFrame: id => timers.delete(id) };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/static/timeline.js"), "utf8"), context);
  const host = new Element(), axis = new Element(), body = new Element(), track = new Element();
  axis.className = "scale";
  track.className = "track";
  body.append(track);
  host.append(axis, body);
  body.setAttribute("aria-label", "时刻表");
  let scrub = null;
  const zoom = new window.FocusTimeline.Zoom({ host, axis, body,
    onChange: view => changes.push([view.start, view.size]),
    onScrub: value => { scrub = value; readings.push(value); }, getScrub: () => scrub,
    formatRange: (a, b) => ({ range: `${a.toFixed(4)}–${b.toFixed(4)}`, duration: "test duration" }) });
  zoom.enabled = true;
  zoom.refresh();
  function advance(milliseconds) {
    const until = clock + milliseconds;
    for (let count = 0; count < 10000; count++) {
      const next = [...timers].filter(([, timer]) => timer.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) { clock = until; return; }
      timers.delete(next[0]);
      clock = next[1].at;
      next[1].callback();
    }
    throw new Error("Unbounded timer loop");
  }
  const emit = (name, props = {}) => host.emit(name, { target: track, ...props });
  const touch = (identifier, clientX, clientY = 0) => ({ identifier, clientX, clientY, target: track });
  const wheel = (deltaY, props = {}) => emit("wheel", { deltaY, deltaMode: 0, ...props });
  return { zoom, host, axis, body, track, window, document, changes, readings, timers, emit, touch, wheel, advance };
}

test("wheel zooms immediately over the axis without hovering; other areas keep page scrolling", () => {
  const h = harness();
  assert.equal(h.wheel(-120).prevented, true);
  h.advance(100);
  near(h.zoom.view.zoom, Math.sqrt(2));
  h.emit("pointerleave");
  assert.equal(h.wheel(-120, { target: h.body }).prevented, false);
  assert.equal(h.wheel(-120, { target: h.zoom.slider }).prevented, false);
  assert.equal(h.wheel(-120, { target: h.zoom.tools }).prevented, false);
});

test("wheel scale ratios remain consistent during rapid bursts, tiny deltas and reversals", () => {
  const h = harness();
  h.emit("pointerover", { clientX: 250 });
  h.wheel(-120, { clientX: 250 });
  for (let i = 0; i < 5; i++) { h.advance(5); h.wheel(-120, { clientX: 250 }); }
  h.advance(100);
  near(h.zoom.view.zoom, 8);
  near(h.zoom.view.at(.25), .25);
  h.wheel(-.5, { clientX: 250 });
  h.advance(100);
  near(h.zoom.view.zoom, 8 * 2 ** (.5 / 240));
  h.wheel(.5, { clientX: 250 });
  h.advance(100);
  near(h.zoom.view.zoom, 8);
  near(h.zoom.view.at(.25), .25);
  assert.ok(h.changes.length > 5);
});

test("Ctrl/browser zoom, horizontal scrolling, and wheel outside the axis remain native", () => {
  const h = harness();
  h.emit("pointerover");
  assert.equal(h.wheel(-120, { ctrlKey: true }).prevented, false);
  assert.equal(h.wheel(-120, { metaKey: true }).prevented, false);
  assert.equal(h.wheel(0, { deltaX: 120 }).prevented, false);
  assert.equal(h.wheel(-120, { target: h.zoom.plus }).prevented, false);
  near(h.zoom.target.zoom, 1);
});

test("slider controls scale, keeps its original centre through a drag and syncs with buttons", () => {
  const h = harness(true);
  const slider = h.zoom.slider;
  assert.equal(h.zoom.overview.getAttribute("aria-disabled"), "true");
  h.zoom.setZoom(4, .5, false, .2);
  slider.emit("pointerdown");
  slider.value = "0";
  slider.emit("input");
  near(h.zoom.view.zoom, 1);
  slider.value = "100";
  slider.emit("input");
  near(h.zoom.view.zoom, MAX_ZOOM);
  near(h.zoom.view.at(.5), .2);
  assert.equal(h.zoom.overview.getAttribute("aria-disabled"), "false");
  assert.match(slider.getAttribute("aria-valuetext"), /96.00 倍/);
  slider.emit("change");
  assert.equal(h.zoom.sliderAnchor, null);
  h.zoom.minus.emit("click");
  near(h.zoom.view.zoom, MAX_ZOOM / Math.sqrt(2));
  near(Number(slider.value), Math.log(h.zoom.view.zoom) / Math.log(MAX_ZOOM) * 100);
  h.zoom.reset();
  near(Number(slider.value), 0);
  assert.equal(h.zoom.overview.getAttribute("aria-disabled"), "true");
});

test("plus and minus are proportional and reversible at low and high zoom", () => {
  const h = harness(true);
  for (const zoom of [1, 4, 32, 64]) {
    h.zoom.setZoom(zoom);
    const centre = h.zoom.view.at(.5);
    h.zoom.plus.emit("click");
    near(h.zoom.view.zoom, zoom * Math.sqrt(2));
    h.zoom.minus.emit("click");
    near(h.zoom.view.zoom, zoom);
    near(h.zoom.view.at(.5), centre);
  }
});

test("single finger horizontal drag pans a zoomed range; vertical movement stays page scrolling", () => {
  const h = harness(true);
  h.zoom.setZoom(4);
  h.emit("touchstart", { touches: [h.touch(1, 400, 100)] });
  assert.equal(h.emit("touchmove", { touches: [h.touch(1, 520, 103)] }).prevented, true);
  near(h.zoom.view.start, .325);
  assert.equal(h.host.classList.contains("is-panning"), true);
  h.emit("touchend", { touches: [] });
  assert.equal(h.host.classList.contains("is-panning"), false);
  h.emit("touchstart", { touches: [h.touch(2, 400, 100)] });
  assert.equal(h.emit("touchmove", { touches: [h.touch(2, 404, 160)] }).prevented, false);
  assert.equal(h.emit("touchmove", { touches: [h.touch(2, 600, 170)] }).prevented, false);
  near(h.zoom.view.start, .325);
  assert.equal(h.readings.at(-1), null);
  h.emit("touchend", { touches: [] });
  assert.equal(h.readings.at(-1), null);
});

test("a tap inspects only on release; full-day swipes do not become accidental inspection", () => {
  const h = harness(true);
  h.emit("touchstart", { touches: [h.touch(1, 250)] });
  assert.equal(h.readings.at(-1), null);
  h.emit("touchend", { touches: [] });
  near(h.readings.at(-1), .25);
  h.advance(2600);
  assert.equal(h.readings.at(-1), null);
  h.emit("touchstart", { touches: [h.touch(2, 300)] });
  assert.equal(h.emit("touchmove", { touches: [h.touch(2, 500)] }).prevented, false);
  h.emit("touchend", { touches: [] });
  assert.equal(h.readings.at(-1), null);
  near(h.zoom.view.zoom, 1);
});

test("a second finger takes over panning without a time jump, and cancellation clears all state", () => {
  const h = harness(true);
  h.zoom.setZoom(4);
  h.emit("touchstart", { touches: [h.touch(1, 300)] });
  h.emit("touchmove", { touches: [h.touch(1, 340)] });
  const before = h.zoom.view.copy();
  h.emit("touchstart", { touches: [h.touch(1, 340), h.touch(2, 540)] });
  h.emit("touchmove", { touches: [h.touch(1, 340), h.touch(2, 540)] });
  near(h.zoom.view.start, before.start);
  near(h.zoom.view.size, before.size);
  assert.equal(h.host.classList.contains("is-panning"), false);
  h.emit("touchcancel");
  assert.equal(h.zoom.touch, null);
  assert.equal(h.zoom.pinch, null);
  assert.equal(h.readings.at(-1), null);
});

test("overview navigation moves the window without changing its scale", () => {
  const h = harness(true);
  h.zoom.setZoom(8);
  h.emit("pointerdown", { target: h.zoom.overview, clientX: 160, pointerType: "touch" });
  near(h.zoom.view.at(.5), .1);
  h.emit("pointermove", { clientX: 280, pointerType: "touch" });
  near(h.zoom.view.at(.5), .3);
  near(h.zoom.view.zoom, 8);
  h.emit("pointerup");
  assert.equal(h.host.hasPointerCapture(1), false);
});

test("pinch starts immediately, follows finger distance linearly, and pans with its midpoint", () => {
  const h = harness();
  h.emit("touchstart", { touches: [h.touch(1, 300)] });
  h.emit("touchstart", { touches: [h.touch(1, 300), h.touch(2, 500)] });
  assert.ok(h.zoom.pinch);
  const moved = h.emit("touchmove", { touches: [h.touch(1, 200), h.touch(2, 600)] });
  assert.equal(moved.prevented, true);
  near(h.zoom.view.zoom, 2);
  near(h.zoom.view.at(.5), .5);
  h.emit("touchmove", { touches: [h.touch(1, 260), h.touch(2, 660)] });
  near(h.zoom.view.zoom, 2);
  near(h.zoom.view.at(.6), .5);
  // Lifting one finger must not turn the remaining finger into a scrub/scroll jump.
  h.emit("touchend", { touches: [h.touch(2, 660)] });
  const readings = h.readings.length;
  h.emit("touchmove", { touches: [h.touch(2, 500)] });
  assert.equal(h.readings.length, readings);
  h.emit("touchend", { touches: [] });
  assert.equal(h.zoom.suppressTouch, false);
  assert.equal(h.host.classList.contains("is-pinching"), false);
});

test("vertical and cancelled touch sequences keep single-finger page scrolling available", () => {
  const h = harness();
  assert.equal(h.emit("touchstart", { touches: [h.touch(1, 400)] }).prevented, false);
  assert.equal(h.emit("touchmove", { touches: [h.touch(1, 400, 100)] }).prevented, false);
  h.emit("touchstart", { touches: [h.touch(1, 300), h.touch(2, 500)] });
  h.emit("touchcancel");
  assert.equal(h.zoom.pinch, null);
  assert.equal(h.zoom.touch, null);
  assert.equal(h.host.classList.contains("is-pinching"), false);
});

test("pinch boundaries are visible during the gesture and clear when fingers move back inside", () => {
  const h = harness(true);
  h.emit("touchstart", { touches: [h.touch(1, 300), h.touch(2, 500)] });
  h.emit("touchmove", { touches: [h.touch(1, 390), h.touch(2, 410)] });
  near(h.zoom.view.zoom, 1);
  assert.match(h.zoom.hint.textContent, /最小缩放/);
  h.emit("touchmove", { touches: [h.touch(1, 200), h.touch(2, 600)] });
  near(h.zoom.view.zoom, 2);
  assert.equal(h.host.classList.contains("is-zoom-limit"), false);
  assert.match(h.zoom.hint.textContent, /双指缩放中/);
});

test("mouse dragging and overview keyboard navigation reach either edge without overshooting", () => {
  const h = harness(true);
  h.zoom.setZoom(4);
  near(h.zoom.view.zoom, 4);
  h.emit("pointerdown", { clientX: 400 });
  assert.equal(h.host.classList.contains("is-panning"), true);
  h.emit("pointermove", { clientX: 700 });
  near(h.zoom.view.start, .25);
  h.emit("pointermove", { clientX: 5000 });
  near(h.zoom.view.start, 0);
  h.emit("pointerup");
  assert.equal(h.host.hasPointerCapture(1), false);
  h.zoom.overview.emit("keydown", { key: "End" });
  near(h.zoom.view.at(1), 1);
  h.zoom.overview.emit("keydown", { key: "Home" });
  near(h.zoom.view.start, 0);
});

test("zoom limits, reset and reduced motion give explicit state without delayed animations", () => {
  const h = harness(true);
  h.zoom.step(1e6);
  near(h.zoom.view.zoom, MAX_ZOOM);
  assert.equal(h.zoom.plus.disabled, true);
  assert.match(h.zoom.hint.textContent, /最大缩放/);
  h.body.emit("keydown", { key: "0" });
  near(h.zoom.view.zoom, 1);
  near(h.zoom.view.start, 0);
  assert.equal(h.zoom.fit.disabled, true);
  assert.equal(h.zoom.minus.disabled, true);
  assert.equal(h.zoom.overview.getAttribute("aria-disabled"), "true");
  assert.equal(h.host.classList.contains("is-zoomed"), false);
});

test("keyboard inspection during a zoom animation uses the final visible range", () => {
  const h = harness();
  h.zoom.setZoom(13, .5, true);
  h.advance(16);
  h.body.emit("keydown", { key: "Home" });
  near(h.zoom.view.zoom, 13);
  near(h.readings.at(-1), h.zoom.view.start);
  h.advance(100);
  near(h.readings.at(-1), h.zoom.view.start);
  h.body.emit("keydown", { key: "End" });
  near(h.readings.at(-1), h.zoom.view.at(1));
});

test("blur, hidden tabs and destruction release gestures, timers and listeners", () => {
  const h = harness();
  h.emit("pointerover");
  h.advance(500);
  h.window.emit("blur");
  assert.equal(h.zoom.pointerPosition, null);
  h.emit("touchstart", { touches: [h.touch(1, 300), h.touch(2, 500)] });
  h.document.hidden = true;
  h.document.emit("visibilitychange");
  assert.equal(h.zoom.pinch, null);
  h.zoom.step(3);
  h.zoom.destroy();
  assert.equal(h.timers.size, 0);
  assert.equal([...h.host.handlers.values()].reduce((sum, handlers) => sum + handlers.size, 0), 0);
  assert.equal([...h.window.handlers.values()].reduce((sum, handlers) => sum + handlers.size, 0), 0);
});
