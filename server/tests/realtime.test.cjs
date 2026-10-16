const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function harness(supported = true) {
  let now = 0, serial = 0, reloads = 0;
  const timers = new Map(), connections = [];
  const events = () => ({
    handlers: new Map(),
    addEventListener(name, callback) {
      if (!this.handlers.has(name)) this.handlers.set(name, new Set());
      this.handlers.get(name).add(callback);
    },
    removeEventListener(name, callback) { this.handlers.get(name)?.delete(callback); },
    emit(name) { this.handlers.get(name)?.forEach(callback => callback()); },
  });
  class EventSource {
    static CLOSED = 2;
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.handlers = new Map();
      connections.push(this);
    }
    addEventListener(name, callback) { this.handlers.set(name, callback); }
    emit(name, data = {}) { this.handlers.get(name)?.({ data: JSON.stringify(data) }); }
    close() { this.closed = true; this.readyState = 2; }
    error(state) { this.readyState = state; this.onerror(); }
  }
  const document = { ...events(), hidden: false };
  const window = { ...events(), EventSource: supported ? EventSource : undefined };
  const context = {
    document, window, EventSource, location: { reload() { reloads++; } },
    setTimeout(callback, delay) { timers.set(++serial, { at: now + delay, callback }); return serial; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/static/realtime.js"), "utf8"), context);
  const client = new window.FocusRealtime("/api/web/events?username=alice");
  function advance(milliseconds) {
    const until = now + milliseconds;
    for (let count = 0; count < 1000; count++) {
      const next = [...timers].filter(([, timer]) => timer.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) { now = until; return; }
      timers.delete(next[0]);
      now = next[1].at;
      next[1].callback();
    }
    throw new Error("Unbounded timer loop");
  }
  return { client, window, document, connections, advance, reloads: () => reloads };
}

test("one stream coalesces bursts without losing history or metadata invalidations", () => {
  const h = harness(), delivered = [];
  h.client.subscribe(areas => delivered.push([...areas].sort()));
  h.client.start();
  h.client.start();
  assert.equal(h.connections.length, 1);
  const source = h.connections[0];
  source.emit("ready");
  source.emit("changed", { areas: ["metadata"] });
  for (let i = 0; i < 100; i++) source.emit("changed", { areas: ["live"] });
  h.advance(150);
  assert.deepEqual(delivered, [["access", "history", "live", "metadata"]]);
  assert.equal(h.client.state, "connected");
});

test("temporary disconnect keeps native reconnection and ready requests fresh snapshots", () => {
  const h = harness(), delivered = [];
  h.client.subscribe(areas => delivered.push([...areas].sort()));
  h.client.start();
  const source = h.connections[0];
  source.emit("ready");
  h.advance(150);
  source.error(0);
  assert.equal(h.client.state, "reconnecting");
  h.advance(3000);
  assert.equal(h.connections.length, 1);
  source.emit("ready");
  h.advance(150);
  assert.equal(h.client.state, "connected");
  assert.deepEqual(delivered[1], ["access", "history", "live"]);
});

test("terminal errors retry with backoff while regular refresh remains independent", () => {
  const h = harness();
  h.client.start();
  h.connections[0].error(2);
  h.advance(2999);
  assert.equal(h.connections.length, 1);
  h.advance(1);
  assert.equal(h.connections.length, 2);
  h.connections[1].error(2);
  h.advance(5999);
  assert.equal(h.connections.length, 2);
  h.advance(1);
  assert.equal(h.connections.length, 3);
});

test("hidden pages release the connection and resume with a fresh snapshot", () => {
  const h = harness(), delivered = [];
  h.client.subscribe(areas => delivered.push([...areas].sort()));
  h.client.start();
  h.connections[0].emit("ready");
  h.document.hidden = true;
  h.document.emit("visibilitychange");
  h.advance(60000);
  assert.equal(h.connections.length, 1);
  assert.equal(h.connections[0].closed, true);
  assert.deepEqual(delivered, []);
  h.document.hidden = false;
  h.document.emit("visibilitychange");
  h.advance(150);
  assert.equal(h.connections.length, 2);
  assert.deepEqual(delivered, [["access", "history", "live"]]);
});

test("missing heartbeats reconnect and ignore frames from the old connection", () => {
  const h = harness();
  h.client.start();
  const old = h.connections[0];
  old.emit("ready");
  h.advance(30000);
  old.emit("ping");
  h.advance(30000);
  assert.equal(h.connections.length, 1);
  h.advance(15000);
  assert.equal(h.connections.length, 2);
  assert.equal(old.closed, true);
  old.emit("ready");
  assert.equal(h.client.state, "reconnecting");
});

test("permission reset closes the stream, reloads, and cancels retries", () => {
  const h = harness();
  h.client.start();
  h.connections[0].emit("reset");
  h.advance(120000);
  assert.equal(h.reloads(), 1);
  assert.equal(h.connections.length, 1);
  assert.equal(h.connections[0].closed, true);
});

test("unsupported browsers keep the periodic-refresh mode", () => {
  const h = harness(false);
  h.client.start();
  h.advance(120000);
  assert.equal(h.client.state, "fallback");
  assert.equal(h.connections.length, 0);
});
